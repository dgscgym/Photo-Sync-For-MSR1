"""Persistent sequential chunk uploads, explicit Live pairs, and byte-range serving."""
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid
from urllib.parse import urlsplit, parse_qs

MAX_FILE = 10 * 1024**3
CHUNK = 8 * 1024**2


def media_type(data):
    from .app import image_type
    image = image_type(data)
    if image:
        return image
    if data[4:8] == b'ftyp':
        brands = data[8:64]
        if any(brand in brands for brand in (b'heic', b'heix', b'hevc', b'hevx', b'mif1')):
            return 'image/heic'
        return 'video/quicktime' if data[8:12] == b'qt  ' else 'video/mp4'
    if data.startswith(b'\x1aE\xdf\xa3'):
        return 'video/webm'
    return None


class Media:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.parts = store.directory / 'uploads'
        self.parts.mkdir(exist_ok=True)
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS uploads(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL,
                    sha256 TEXT, duplicate INTEGER);
                CREATE TABLE IF NOT EXISTS live_pairs(
                    photo TEXT PRIMARY KEY, video TEXT NOT NULL);

            ''')

    def session(self, uid):
        if not re.fullmatch('[a-f0-9]{32}', uid):
            raise ValueError('上传会话无效')
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM uploads WHERE id=?', (uid,)).fetchone()
        if row is None:
            raise ValueError('上传会话不存在')
        result = dict(row)
        result['offset'] = result['size'] if row['sha256'] else (self.parts / uid).stat().st_size
        return result

    def json_body(self, handler):
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 16384:
            raise ValueError('请求内容过大或为空')
        return json.loads(handler.rfile.read(length))

    def route(self, h):
        path = urlsplit(h.path).path
        if not path.startswith(('/api/v1/uploads', '/api/v1/live-pairs')):
            return False
        try:
            if h.command != 'GET' and h.headers.get('Sec-Fetch-Site') == 'cross-site':
                h.send(403, {'error': '不允许跨站请求'}); return True
            if h.command == 'POST' and path == '/api/v1/uploads':
                data = self.json_body(h)
                h.audit_context = {key:data[key] for key in ('name','size') if key in data}
                size = data.get('size')
                if type(size) is not int or not 0 < size <= MAX_FILE:
                    h.send(413, {'error': '文件必须在 1 字节至 10 GiB 之间'}); return True
                name = data.get('name')
                if not isinstance(name, str) or not name:
                    raise ValueError('缺少文件名')
                uid = uuid.uuid4().hex
                with self.lock, self.store.connect() as db:
                    (self.parts / uid).touch()
                    db.execute('INSERT INTO uploads(id,name,size) VALUES(?,?,?)', (uid, Path(name).name[:255], size))
                h.send(201, dict(self.session(uid), chunk_size=CHUNK)); return True
            if h.command == 'POST' and path == '/api/v1/live-pairs':
                data = self.json_body(h)
                with self.store.connect() as db:
                    photo = db.execute('SELECT * FROM photos WHERE sha256=?', (data.get('photo'),)).fetchone()
                    video = db.execute('SELECT * FROM photos WHERE sha256=?', (data.get('video'),)).fetchone()
                    if not photo or not video or not photo['media_type'].startswith('image/') or not video['media_type'].startswith('video/'):
                        raise ValueError('配对需要已上传的照片和视频')
                    existing = db.execute('SELECT video FROM live_pairs WHERE photo=?', (photo['sha256'],)).fetchone()
                    if existing and existing['video'] != video['sha256']:
                        h.send(409, {'error': '照片已有其他 Live 配对，请勿覆盖'}); return True
                    db.execute('INSERT OR IGNORE INTO live_pairs VALUES(?,?)', (photo['sha256'], video['sha256']))
                h.send(200, {'paired': True}); return True
            match = re.fullmatch(r'/api/v1/uploads/([a-f0-9]{32})(/complete)?', path)
            if not match:
                h.send(404, {'error': '接口不存在'}); return True
            uid, complete = match.groups()
            with self.lock:
                session = self.session(uid)
                h.audit_context = {"name":session["name"], "size":session["size"], "offset":session["offset"]}
                part = self.parts / uid
                if h.command == 'GET' and not complete:
                    self.store.log('upload', 'debug', 'resume_queried', uid, '查询上传进度', {'name':session['name'], 'offset':session['offset'], 'size':session['size']})
                    h.send(200, session); return True
                if h.command == 'DELETE' and not complete:
                    if not session['sha256']:
                        part.unlink(missing_ok=True)
                    with self.store.connect() as db:
                        db.execute('DELETE FROM uploads WHERE id=?', (uid,))
                    h.send(200, {'cancelled': True}); return True
                if h.command == 'PATCH' and not complete:
                    offset = int(h.headers.get('Upload-Offset', '-1'))
                    length = int(h.headers.get('Content-Length', '0'))
                    if session['sha256'] or offset != session['offset']:
                        h.send(409, {'error': '分片偏移不匹配', 'offset': session['offset']}); return True
                    if not 0 < length <= CHUNK or offset + length > session['size']:
                        h.send(413, {'error': '分片超出限制'}); return True
                    # Read a bounded chunk before append: disconnected requests cannot publish partial chunks.
                    h.connection.settimeout(120)
                    body = h.rfile.read(length)
                    if len(body) != length:
                        raise ValueError('分片不完整')
                    with part.open('ab') as stream:
                        stream.write(body)
                    h.send(200, {'offset': offset + length}); return True
                if h.command == 'POST' and complete:
                    if session['sha256']:
                        h.send(200, {'sha256': session['sha256'], 'duplicate': bool(session['duplicate'])}); return True
                    if session['offset'] != session['size']:
                        h.send(409, {'error': '文件尚未上传完整'}); return True
                    digest = hashlib.sha256()
                    with part.open('rb') as stream:
                        signature = stream.read(64)
                        digest.update(signature)
                        for chunk in iter(lambda: stream.read(1024**2), b''):
                            digest.update(chunk)
                    kind = media_type(signature)
                    if not kind:
                        h.send(415, {'error': '不支持的媒体格式'}); return True
                    sha256 = digest.hexdigest()
                    # Keep the session file until metadata commit, allowing retry after a crash.
                    staging = self.parts / (uid + '.publish')
                    staging.unlink(missing_ok=True)
                    os.link(part, staging)
                    try:
                        duplicate = self.store.save(staging, sha256, session['name'], session['size'], kind)
                    finally:
                        staging.unlink(missing_ok=True)
                    with self.store.connect() as db:
                        db.execute('UPDATE uploads SET sha256=?, duplicate=? WHERE id=?', (sha256, duplicate, uid))
                    part.unlink(missing_ok=True)
                    h.send(200 if duplicate else 201, {'sha256': sha256, 'duplicate': duplicate}); return True
                h.send(405, {'error': '不支持此方法'}); return True
        except (ValueError, TypeError, OSError) as error:
            h.send(400, {'error': '上传请求无效或存储不可用，请查询进度后重试'})
            return True


def serve_file(h, path, kind, head=False):
    size = path.stat().st_size
    start, end, status = 0, size - 1, 200
    value = h.headers.get('Range')
    if value:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
        try:
            if not match or not any(match.groups()):
                raise ValueError()
            left, right = match.groups()
            if not left:
                suffix = int(right)
                if suffix <= 0:
                    raise ValueError()
                start = max(0, size - suffix)
            else:
                start = int(left)
                end = min(int(right), size - 1) if right else size - 1
            if start >= size or start > end:
                raise ValueError()
            status = 206
        except ValueError:
            h.send(416, {'error': '无效的字节范围'}, Content_Range=f'bytes */{size}')
            return
    h.send_response(status)
    h.send_header('Content-Type', kind)
    h.send_header('Content-Length', str(end - start + 1))
    h.send_header('Accept-Ranges', 'bytes')
    h.send_header('X-Content-Type-Options', 'nosniff')
    if status == 206:
        h.send_header('Content-Range', f'bytes {start}-{end}/{size}')
    h.end_headers()
    if head:
        return
    try:
        with path.open('rb') as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = stream.read(min(1024**2, remaining))
                if not chunk:
                    break
                h.wfile.write(chunk)
                remaining -= len(chunk)
    except (BrokenPipeError, ConnectionResetError):
        pass
