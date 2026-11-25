"""PhotoSync prototype. Python standard library only; single-user local service."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text().strip()
MAX_UPLOAD = 50 * 1024 * 1024


def image_type(data):
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.originals = self.directory / 'originals'
        self.originals.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO schema_version VALUES(1);
                CREATE TABLE IF NOT EXISTS photos(
                    sha256 TEXT PRIMARY KEY, name TEXT NOT NULL,
                    size INTEGER NOT NULL, media_type TEXT NOT NULL,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, sha256 TEXT NOT NULL,
                    kind TEXT NOT NULL, created_at TEXT NOT NULL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.directory / 'photosync.sqlite3', timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def save(self, temporary, sha256, name, size, media_type):
        # Serialize publication and metadata insertion; SQLite UNIQUE is a second guard.
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            duplicate = db.execute('SELECT 1 FROM photos WHERE sha256=?', (sha256,)).fetchone() is not None
            now = datetime.now(timezone.utc).isoformat()
            if not duplicate:
                os.replace(temporary, self.originals / sha256)
                db.execute('INSERT INTO photos VALUES(?,?,?,?,?)', (sha256, name, size, media_type, now))
            db.execute('INSERT INTO events(sha256,kind,created_at) VALUES(?,?,?)',
                       (sha256, 'duplicate' if duplicate else 'uploaded', now))
            return duplicate

    def snapshot(self):
        with self.connect() as db:
            photos = [dict(row) for row in db.execute('SELECT * FROM photos ORDER BY created_at DESC')]
            events = [dict(row) for row in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 30')]
            duplicates = db.execute("SELECT count(*) FROM events WHERE kind='duplicate'").fetchone()[0]
        return {'version': VERSION, 'photos': photos, 'events': events,
                'stats': {'photos': len(photos), 'bytes': sum(p['size'] for p in photos), 'duplicates': duplicates},
                'capabilities': {'face_recognition': 'not_configured', 'npu': 'not_verified',
                                 'encryption': 'not_implemented', 'cloud115': 'not_connected'}}


def make_server(directory, host='127.0.0.1', port=8080):
    store = Store(directory)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, status, body, media_type='application/json', **headers):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', media_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            for key, value in headers.items():
                self.send_header(key.replace('_', '-'), value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/api/v1/status':
                return self.send(200, store.snapshot())
            if path.startswith('/api/v1/photos/'):
                digest = path.rsplit('/', 1)[-1]
                if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    return self.send(404, {'error': '照片不存在'})
                with store.connect() as db:
                    photo = db.execute('SELECT * FROM photos WHERE sha256=?', (digest,)).fetchone()
                if photo is None or not (store.originals / digest).is_file():
                    return self.send(404, {'error': '照片不存在'})
                # Stream original instead of loading large files into memory.
                self.send_response(200)
                self.send_header('Content-Type', photo['media_type'])
                self.send_header('Content-Length', str(photo['size']))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                with (store.originals / digest).open('rb') as source:
                    import shutil
                    shutil.copyfileobj(source, self.wfile)
                return
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path in assets:
                filename, media_type = assets[path]
                return self.send(200, (ROOT / 'client' / filename).read_bytes(), media_type)
            return self.send(404, {'error': '接口不存在'})

        def do_POST(self):
            if urlsplit(self.path).path != '/api/v1/photos':
                return self.send(404, {'error': '接口不存在'})
            # Browser cross-origin forms must not mutate this local service.
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self.send(403, {'error': '不允许跨站上传'})
            try:
                length = int(self.headers.get('Content-Length', '-1'))
            except ValueError:
                return self.send(400, {'error': 'Content-Length 无效'})
            if length <= 0 or length > MAX_UPLOAD:
                return self.send(413, {'error': '文件为空或超过 50 MiB 限制'})
            self.connection.settimeout(30)
            temporary = None
            try:
                digest = hashlib.sha256()
                remaining = length
                signature = b''
                with tempfile.NamedTemporaryFile(dir=store.directory, delete=False) as output:
                    temporary = Path(output.name)
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError('文件上传不完整')
                        if not signature:
                            signature = chunk[:16]
                        digest.update(chunk)
                        output.write(chunk)
                        remaining -= len(chunk)
                media_type = image_type(signature)
                if media_type is None:
                    return self.send(415, {'error': '原型支持 JPEG、PNG、GIF、WebP；文件签名不匹配'})
                name = unquote(self.headers.get('X-Filename', 'photo'))
                name = name.replace('\\', '/').rsplit('/', 1)[-1][:255] or 'photo'
                sha256 = digest.hexdigest()
                duplicate = store.save(temporary, sha256, name, length, media_type)
                return self.send(200 if duplicate else 201, {'sha256': sha256, 'duplicate': duplicate})
            except (ValueError, TimeoutError):
                return self.send(400, {'error': '上传不完整或超时，请重试'})
            except Exception:
                return self.send(500, {'error': '保存失败，请重试并检查存储'})
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)

    return ThreadingHTTPServer((host, port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--data', default=str(ROOT / 'data'))
    args = parser.parse_args()
    server = make_server(args.data, args.host, args.port)
    print(f'PhotoSync {VERSION}: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
