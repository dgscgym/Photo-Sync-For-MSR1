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
from .library import Library
from .setup import Setup
from .auth import Auth
from .thumbnails import Thumbnails
from .metadata import inspect as inspect_media

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
        # Refuse future schemas before any metadata changes.
        with self.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_version'").fetchone():
                current=db.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]
                if current and current > 6:
                    raise ValueError('数据库来自较新版本，请使用兼容版本；禁止自动降级')
                if current and current < 6:
                    import time
                    backups=self.directory/'metadata-backups'
                    backups.mkdir(exist_ok=True)
                    with sqlite3.connect(backups / f'schema-{current}-{time.time_ns()}.sqlite3') as backup:
                        db.backup(backup)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
                INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);
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

        with self.connect() as db:
            if 'actor_id' not in {r['name'] for r in db.execute('PRAGMA table_info(audit_logs)')}:
                db.execute('ALTER TABLE audit_logs ADD COLUMN actor_id INTEGER')

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
        level='WARN' if level.upper()=='WARNING' else level.upper()
        if level not in ('INFO','DEBUG','WARN','ERROR'):raise ValueError('无效的日志级别')
        with self.connect() as db:
            db.execute('INSERT INTO audit_logs(category,level,action,task_id,message,details,created_at,actor_id) VALUES(?,?,?,?,?,?,?,?)',
                       (category, level, action, task_id, message[:1000], json.dumps(details,ensure_ascii=False), datetime.now(timezone.utc).isoformat(),details.get('actor_id')))

    def logs(self, category='', before=0, level='', actor_id=None):
        clauses, values = [], []
        if category:
            clauses.append('category=?'); values.append(category)
        if before:
            clauses.append('id<?'); values.append(before)
        if level:
            clauses.append("CASE WHEN upper(level)='WARNING' THEN 'WARN' ELSE upper(level) END=?"); values.append('WARN' if level.upper()=='WARNING' else level.upper())
        if actor_id is not None:
            clauses.append('actor_id=?');values.append(actor_id)
        query = 'SELECT * FROM audit_logs' + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY id DESC LIMIT 100'
        with self.connect() as db:
            rows = [dict(row) for row in db.execute(query,values)]
        for row in rows:
            row['details'] = json.loads(row['details'])
            row['level']='WARN' if row['level'].upper()=='WARNING' else row['level'].upper()
        return {'items':rows, 'next_before':rows[-1]['id'] if len(rows)==100 else None}

    def resolve(self, sha256):
        managed=self.originals / sha256
        if managed.is_file(): return managed
        library=getattr(self,'library',None)
        if not library:return None
        with self.connect() as db:
            rows=db.execute('SELECT l.*,s.path FROM file_locations l JOIN library_sources s ON s.id=l.source_id WHERE l.sha256=? AND l.available=1',(sha256,)).fetchall()
        for row in rows:
            try:
                root=library.allowed(row['path']); candidate=root / row['relative_path']
                if candidate.is_symlink():continue
                path=candidate.resolve(strict=True)
                if root not in path.parents:continue
                stat=path.stat()
                if stat.st_size==row['size'] and stat.st_mtime_ns==row['mtime_ns']:return path
            except (OSError,ValueError):continue
        return None

    def save(self, temporary, sha256, name, size, media_type):
        # Serialize publication and metadata insertion; SQLite UNIQUE is a second guard.
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            duplicate = db.execute('SELECT 1 FROM photos WHERE sha256=?', (sha256,)).fetchone() is not None
            now = datetime.now(timezone.utc).isoformat()
            if not duplicate or self.resolve(sha256) is None:
                os.replace(temporary, self.originals / sha256)
                db.execute('INSERT OR IGNORE INTO photos VALUES(?,?,?,?,?)', (sha256, name, size, media_type, now))
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
            photo['available'] = self.resolve(photo['sha256']) is not None
        return {'version': VERSION, 'photos': photos, 'events': events,
                'stats': {'photos': len(photos), 'bytes': sum(p['size'] for p in photos), 'duplicates': duplicates},
                'capabilities': {'face_recognition': 'not_configured', 'npu': 'not_verified',
                                 'encryption': 'not_implemented', 'cloud115': 'not_connected'}}


def make_server(directory, host='127.0.0.1', port=8080, snapraid_config=None, library_bases=(), scan_interval=300, storage_bases=(), snapraid_config_bases=(), secure_cookies=False, webauthn_origin=None, prototype=False, prototype_media_from=None):
    directory=Path(directory)
    if prototype_media_from and not prototype:raise ValueError('演示素材只能在原型模式使用')
    if prototype and host not in ('127.0.0.1','localhost'):raise ValueError('免登录预览仅允许本机回环地址')
    if not prototype and (directory/'prototype.marker').exists():raise ValueError('原型数据目录不能直接用于正式认证模式')
    if prototype and (directory/'photosync.sqlite3').exists():
        with sqlite3.connect((directory/'photosync.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
            for name in ('users','accounts'):
                if db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone() and db.execute('SELECT 1 FROM '+name+' LIMIT 1').fetchone():raise ValueError('免登录原型必须使用独立数据目录')
    if prototype_media_from:
        original_root=Path(prototype_media_from).resolve()/'originals'
        library_bases=tuple(library_bases)+(str(original_root),)
    store = Store(directory)
    store.demo=prototype
    if prototype:(directory/'prototype.marker').write_text('Local prototype only. No authentication.\n')
    media = Media(store)
    library = Library(store, library_bases, scan_interval)
    store.library = library
    previews = Previews(store)
    thumbnails = Thumbnails(store)
    persisted=store.directory/'snapraid-monitor.json'
    monitor = Monitor(store, None if prototype else (snapraid_config or (str(persisted) if persisted.exists() else None)))
    auth=Auth(store,secure_cookies,prototype)
    store.auth=auth
    setup = Setup(store,library,monitor,storage_bases,snapraid_config_bases, bool(snapraid_config))
    with store.connect() as db:
        db.execute("DELETE FROM schema_version")
        db.execute("INSERT INTO schema_version VALUES(6)")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, status, body, media_type='application/json', **headers):
            path = urlsplit(self.path).path
            if self.command=='POST' and status in (200,201) and isinstance(body,dict) and body.get('sha256') and getattr(self,'auth_user',None) and path.startswith(('/api/v1/uploads','/api/v1/photos')):
                with store.connect() as db:db.execute('INSERT OR IGNORE INTO photo_access VALUES(?,?)',(self.auth_user['id'],body['sha256']))
            if self.command in ('POST', 'PATCH', 'DELETE') and path.startswith(('/api/v1/uploads', '/api/v1/photos', '/api/v1/live-pairs')):
                context = dict(getattr(self, 'audit_context', {}))
                if getattr(self,'auth_user',None):context['actor_id']=self.auth_user['id']
                if isinstance(body, dict):
                    context.update({key:body[key] for key in ('sha256','duplicate','offset','id','error') if key in body})
                context.update(http_status=status, method=self.command,
                               bytes_received=self.headers.get('Content-Length', '0'))
                if path.startswith('/api/v1/uploads/'):
                    context['session_id'] = path.split('/')[4][:64]
                if self.headers.get('X-Filename'):
                    context['name'] = unquote(self.headers['X-Filename'])[:255]
                store.log('upload', 'error' if status >= 500 else 'warning' if status >= 400 else 'debug' if self.command=='PATCH' else 'info',
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
            if auth.gate(self):
                return
            if not media.route(self):
                self.send(404, {'error': '接口不存在'})

        do_DELETE = do_PATCH

        def do_GET(self):
            if auth.gate(self):
                return
            if setup.route(self):
                return
            if library.route(self):
                return
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
            if path=='/api/v1/client/logs':
                query=parse_qs(urlsplit(self.path).query)
                try:return self.send(200,store.logs('upload',int(query.get('before',['0'])[0]),query.get('level',[''])[0],self.auth_user['id']))
                except ValueError:return self.send(400,{'error':'无效分页参数'})
            if path == '/api/v1/logs':
                query = parse_qs(urlsplit(self.path).query)
                try:
                    return self.send(200, store.logs(query.get('category',[''])[0], int(query.get('before',['0'])[0]), query.get('level',[''])[0]))
                except ValueError:
                    return self.send(400, {'error':'无效的分页参数'})
            if path == '/api/v1/snapraid':
                return self.send(200, monitor.snapshot())
            if path == '/api/v1/client/status':
                state=store.snapshot()
                state['photos']=[p for p in state['photos'] if auth.can_media(self.auth_user,p['sha256'])]
                for photo in state['photos']:
                    if photo['live_video'] and not auth.can_media(self.auth_user,photo['live_video']):photo['live_video']=None
                state['stats']={'photos':len(state['photos']),'bytes':sum(p['size'] for p in state['photos'])}
                return self.send(200,{key:state[key] for key in ('version','photos','stats')})
            if path.startswith('/api/v1/thumbnails/'):
                digest=path.rsplit('/',1)[-1]
                if not auth.can_media(self.auth_user,digest,self.auth_audience):return self.send(404,{'error':'媒体不存在'})
                if len(digest)!=64 or any(char not in '0123456789abcdef' for char in digest):return self.send(404,{'error':'媒体不存在'})
                try:return serve_file(self,thumbnails.get(digest),'image/jpeg',self.command=='HEAD')
                except ValueError as error:return self.send(415,{'error':str(error)})
            if path.startswith('/api/v1/media-details/'):
                digest=path.rsplit('/',1)[-1]
                if not auth.can_media(self.auth_user,digest,self.auth_audience):return self.send(404,{'error':'媒体不存在'})
                try:return self.send(200,inspect_media(store,digest,self.auth_audience))
                except ValueError:return self.send(404,{'error':'媒体不存在'})
            if path == '/api/v1/status':
                return self.send(200, store.snapshot())
            if path.startswith('/api/v1/photos/'):
                digest = path.rsplit('/', 1)[-1]
                if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    return self.send(404, {'error': '照片不存在'})
                with store.connect() as db:
                    photo = db.execute('SELECT * FROM photos WHERE sha256=?', (digest,)).fetchone()
                target = store.resolve(digest) if photo else None
                if target is None:
                    return self.send(404, {'error': '照片不存在'})
                return serve_file(self, target, photo['media_type'], self.command == 'HEAD')
            if path in ('/login','/client/login'):
                page=(ROOT/'server/admin/web'/'login.html').read_text()
                page=page.replace('href="/"','href="/client"' if path=='/client/login' else 'href="/admin"')
                page=page.replace('登录，回到你的回忆。','客户端登录' if path=='/client/login' else '服务端管理登录')
                return self.send(200,page.encode(),'text/html; charset=utf-8')
            if path.startswith('/setup') and path in ('/setup','/setup/welcome','/setup/library','/setup/snapraid','/setup/review'):
                return self.send(200,(ROOT/'server/admin/web'/'setup.html').read_bytes(),'text/html; charset=utf-8')
            if path=='/admin/settings/snapraid':return self.send(302,b'',Location='/admin/settings#snapraid')
            if path=='/client/logs':return self.send(302,b'',Location='/client')
            if path in ('/client/settings','/admin/settings','/client/logs','/admin/logs'):
                home='/client' if path.startswith('/client') else '/admin'
                profile=(ROOT/'shared/web/profile.fragment.html').read_text().replace('__SETTINGS__',home+'/settings').replace('__HOME__',home)
                if home=='/client':profile=profile.replace('<a id="user-logs" href="/client/logs">运行日志</a>','')
                if path.endswith('/logs'):
                    page=(ROOT/'shared/web/logs.html').read_text()
                    if home=='/client':
                        import re
                        page=re.sub(r'<select id="log-category">.*?</select>','<select id="log-category" disabled><option value="upload">上传</option></select>',page,flags=re.S)
                elif home=='/client':page=(ROOT/'client/settings.html').read_text().replace('__PROFILE__',profile)
                else:page=(ROOT/'shared/web/settings.html').read_text()
                page=page.replace('__HOME__',home).replace('__LABEL__','客户端' if home=='/client' else '管理台').replace('__SETTINGS__',home+'/settings')
                return self.send(200,page.encode(),'text/html; charset=utf-8')
            pages={'/admin':('server/admin/web/index.html','text/html; charset=utf-8'),
                   '/client':('client/index.html','text/html; charset=utf-8'),
                   '/admin/settings/snapraid':('server/admin/web/snapraid.html','text/html; charset=utf-8')}
            if path=='/':return self.send(302,b'',Location='/admin')
            if path in pages:
                filename,kind=pages[path];return self.send(200,(ROOT/filename).read_bytes(),kind)
            assets={
                '/client/assets/app.js':('client/app.js','text/javascript; charset=utf-8'),
                '/client/assets/style.css':('client/style.css','text/css; charset=utf-8')}
            for filename in ('app.js','setup.js','login.js','snapraid.js','style.css','setup.css'):
                assets['/admin/assets/'+filename]=('server/admin/web/'+filename,'text/css; charset=utf-8' if filename.endswith('.css') else 'text/javascript; charset=utf-8')
            for filename in ('profile.js','profile.css','settings.js','settings.css','upload.js','snapraid.js','directory-picker.js','webauthn.js','mfa.js','client-settings.js','logs.js','media-details.js'):
                assets['/shared/assets/'+filename]=('shared/web/'+filename,'text/css; charset=utf-8' if filename.endswith('.css') else 'text/javascript; charset=utf-8')
            aliases={'/app.js':'/admin/assets/app.js','/style.css':'/admin/assets/style.css','/setup.js':'/admin/assets/setup.js','/setup.css':'/admin/assets/setup.css','/login.js':'/admin/assets/login.js'}
            path=aliases.get(path,path)
            if path in assets:
                filename,kind=assets[path];return self.send(200,(ROOT/filename).read_bytes(),kind)
            return self.send(404, {'error': '接口不存在'})

        def do_POST(self):
            if auth.gate(self):
                return
            if setup.route(self):
                return
            if library.route(self):
                return
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
            library.close()
            monitor.close()
            previews.pool.shutdown(wait=True)
            super().server_close()
    server = Server((host, port), Handler)
    if webauthn_origin:auth.configure_origin(webauthn_origin)
    elif host in ('127.0.0.1','localhost'):auth.configure_origin(f'http://{host}:{server.server_port}')
    if prototype_media_from:
        import re
        origin=Path(prototype_media_from).resolve()
        with sqlite3.connect((origin/'photosync.sqlite3').as_uri()+'?mode=ro',uri=True) as previous:
            rows=previous.execute('SELECT sha256,name,size,media_type,created_at FROM photos').fetchall()
        with store.connect() as db:
            for row in rows:
                if re.fullmatch('[0-9a-f]{64}',row[0]) and (origin/'originals'/row[0]).is_file():db.execute('INSERT OR IGNORE INTO photos VALUES(?,?,?,?,?)',row)
        if not any(s['path']==str(origin/'originals') for s in library.sources()):library.add(str(origin/'originals'),'已有预览素材（只读引用）')
    server.auth = auth
    server.monitor = monitor
    server.library = library
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--data', default=str(ROOT / 'data'))
    parser.add_argument('--snapraid-monitor-config', help='只读检查配置 JSON 路径')
    parser.add_argument('--library-base', action='append', default=[], help='允许登记的媒体根目录，可重复')
    parser.add_argument('--scan-interval', type=int, default=300)
    parser.add_argument('--storage-base', action='append', default=[], help='SnapRAID 磁盘目录授权范围')
    parser.add_argument('--snapraid-config-base', action='append', default=[], help='现有 SnapRAID 配置文件授权范围')
    parser.add_argument('--secure-cookies', action='store_true', help='HTTPS 部署时使用 Secure 会话 Cookie')
    parser.add_argument('--webauthn-origin', help='可信的 HTTPS origin；本机回环地址自动配置')
    parser.add_argument('--prototype',action='store_true',help='本机免登录预览，必须使用独立数据目录')
    parser.add_argument('--prototype-media-from',help='只读引用旧预览的照片与原片位置，不导入账户')
    args = parser.parse_args()
    server = make_server(args.data, args.host, args.port, args.snapraid_monitor_config, args.library_base, args.scan_interval, args.storage_base, args.snapraid_config_base, args.secure_cookies, args.webauthn_origin, args.prototype, args.prototype_media_from)
    print(f'PhotoSync {VERSION}: http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
