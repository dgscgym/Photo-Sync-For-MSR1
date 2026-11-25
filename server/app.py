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
from urllib.parse import urlsplit, unquote, parse_qs
from .media import Media, serve_file
from .preview import Previews
from .monitor import Monitor

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
                CREATE TABLE IF NOT EXISTS audit_logs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
                    level TEXT NOT NULL, action TEXT NOT NULL, task_id TEXT NOT NULL,
                    message TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS audit_category ON audit_logs(category,id);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, sha256 TEXT NOT NULL,
                    kind TEXT NOT NULL, created_at TEXT NOT NULL);
            ''')

        # Preserve pre-0.3 upload history in the new log center exactly once.
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS audit_migrations(name TEXT PRIMARY KEY)')
            if not db.execute("SELECT 1 FROM audit_migrations WHERE name='legacy_events'").fetchone():
                for row in db.execute('SELECT e.*,p.name FROM events e LEFT JOIN photos p ON p.sha256=e.sha256').fetchall():
                    db.execute('INSERT INTO audit_logs(category,level,action,task_id,message,details,created_at) VALUES(?,?,?,?,?,?,?)',
                               ('upload','info','legacy_'+row['kind'],str(row['id']), '历史上传记录',
                                json.dumps({'sha256':row['sha256'],'name':row['name'],'result':row['kind']},ensure_ascii=False),row['created_at']))
                db.execute("INSERT INTO audit_migrations VALUES('legacy_events')")

    def connect(self):
        db = sqlite3.connect(self.directory / 'photosync.sqlite3', timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def log(self, category, level, action, task_id, message, details):
        with self.connect() as db:
            db.execute('INSERT INTO audit_logs(category,level,action,task_id,message,details,created_at) VALUES(?,?,?,?,?,?,?)',
                       (category, level, action, task_id, message[:1000], json.dumps(details,ensure_ascii=False), datetime.now(timezone.utc).isoformat()))

    def logs(self, category='', before=0, level=''):
        clauses, values = [], []
        if category:
            clauses.append('category=?'); values.append(category)
        if before:
            clauses.append('id<?'); values.append(before)
        if level:
            clauses.append('level=?'); values.append(level)
        query = 'SELECT * FROM audit_logs' + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY id DESC LIMIT 100'
        with self.connect() as db:
            rows = [dict(row) for row in db.execute(query,values)]
        for row in rows:
            row['details'] = json.loads(row['details'])
        return {'items':rows, 'next_before':rows[-1]['id'] if len(rows)==100 else None}

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
        with self.connect() as db:
            pairs = {r['photo']: r['video'] for r in db.execute('SELECT * FROM live_pairs')}
        for photo in photos:
            photo['live_video'] = pairs.get(photo['sha256'])
        return {'version': VERSION, 'photos': photos, 'events': events,
                'stats': {'photos': len(photos), 'bytes': sum(p['size'] for p in photos), 'duplicates': duplicates},
                'capabilities': {'face_recognition': 'not_configured', 'npu': 'not_verified',
                                 'encryption': 'not_implemented', 'cloud115': 'not_connected'}}


def make_server(directory, host='127.0.0.1', port=8080, snapraid_config=None):
    store = Store(directory)
    media = Media(store)
    previews = Previews(store)
    monitor = Monitor(store, snapraid_config)
    with store.connect() as db:
        db.execute("DELETE FROM schema_version")
        db.execute("INSERT INTO schema_version VALUES(3)")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, status, body, media_type='application/json', **headers):
            path = urlsplit(self.path).path
            if self.command in ('POST', 'PATCH', 'DELETE') and path.startswith(('/api/v1/uploads', '/api/v1/photos', '/api/v1/live-pairs')):
                context = dict(getattr(self, 'audit_context', {}))
                if isinstance(body, dict):
                    context.update({key:body[key] for key in ('sha256','duplicate','offset','id','error') if key in body})
                context.update(http_status=status, method=self.command,
                               bytes_received=self.headers.get('Content-Length', '0'))
                if path.startswith('/api/v1/uploads/'):
                    context['session_id'] = path.split('/')[4][:64]
                if self.headers.get('X-Filename'):
                    context['name'] = unquote(self.headers['X-Filename'])[:255]
                store.log('upload', 'error' if status >= 500 else 'warning' if status >= 400 else 'info',
                          self.command + ' ' + path[:150], context.get('session_id', context.get('id', '')),
                          context.get('error', ('重复文件已拦截' if context.get('duplicate') else '文件已校验入库' if context.get('sha256') else '分片已保存' if self.command == 'PATCH' else '上传会话已创建' if status == 201 else '上传操作已记录')), context)
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

        def do_HEAD(self):
            self.do_GET()

        def do_PATCH(self):
            if not media.route(self):
                self.send(404, {'error': '接口不存在'})

        do_DELETE = do_PATCH

        def do_GET(self):
            if media.route(self):
                return
            path = urlsplit(self.path).path
            if path.startswith('/api/v1/previews/'):
                digest = path.rsplit('/', 1)[-1]
                try:
                    target, kind, _ = previews.get(digest)
                    if target.exists():
                        return serve_file(self, target, kind, self.command == 'HEAD')
                    return self.send(404, {'error': '预览尚未生成'})
                except ValueError:
                    return self.send(404, {'error': '资源不存在'})
            if path == '/api/v1/logs':
                query = parse_qs(urlsplit(self.path).query)
                try:
                    return self.send(200, store.logs(query.get('category',[''])[0], int(query.get('before',['0'])[0]), query.get('level',[''])[0]))
                except ValueError:
                    return self.send(400, {'error':'无效的分页参数'})
            if path == '/api/v1/snapraid':
                return self.send(200, monitor.snapshot())
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
                return serve_file(self, store.originals / digest, photo['media_type'], self.command == 'HEAD')
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path in assets:
                filename, media_type = assets[path]
                return self.send(200, (ROOT / 'client' / filename).read_bytes(), media_type)
            return self.send(404, {'error': '接口不存在'})

        def do_POST(self):
            if urlsplit(self.path).path in ('/api/v1/snapraid/check','/api/v1/snapraid/acknowledge'):
                if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    return self.send(403, {'error':'不允许跨站请求'})
                if self.path.endswith('/check'):
                    started = monitor.trigger()
                    return self.send(202 if started else 409, {'started':started})
                monitor.acknowledge()
                return self.send(200, monitor.snapshot())
            if media.route(self):
                return
            if urlsplit(self.path).path.startswith('/api/v1/previews/'):
                if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    return self.send(403, {'error': '不允许跨站请求'})
                try:
                    return self.send(200, previews.start(urlsplit(self.path).path.rsplit('/', 1)[-1]))
                except ValueError:
                    return self.send(404, {'error': '资源不存在'})
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

    class Server(ThreadingHTTPServer):
        def server_close(self):
            monitor.close()
            previews.pool.shutdown(wait=True)
            super().server_close()
    server = Server((host, port), Handler)
    server.monitor = monitor
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--data', default=str(ROOT / 'data'))
    parser.add_argument('--snapraid-monitor-config', help='只读检查配置 JSON 路径')
    args = parser.parse_args()
    server = make_server(args.data, args.host, args.port, args.snapraid_monitor_config)
    print(f'PhotoSync {VERSION}: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
