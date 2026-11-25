"""Read-only, content-addressed indexing of allowlisted existing directories."""
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
from .media import media_type


def now():
    return datetime.now(timezone.utc).isoformat()


class Library:
    def __init__(self, store, bases=(), interval=300):
        self.store = store
        self.bases = [Path(p).resolve(strict=True) for p in bases]
        if any(not p.is_dir() for p in self.bases):
            raise ValueError('library-base 必须为目录')
        self.interval = max(30, interval)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.jobs = []
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS library_sources(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT UNIQUE NOT NULL,
                    state TEXT NOT NULL, last_scan TEXT, message TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS file_locations(
                    source_id TEXT NOT NULL, relative_path TEXT NOT NULL, sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, seen TEXT NOT NULL,
                    available INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(source_id,relative_path));
                CREATE INDEX IF NOT EXISTS location_hash ON file_locations(sha256);
                CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
        self.worker = threading.Thread(target=self.loop, daemon=True)
        self.worker.start()

    def allowed(self, value):
        path = Path(value)
        if not path.is_absolute():
            raise ValueError('请输入容器内绝对路径')
        path = path.resolve(strict=True)
        if not path.is_dir() or not any(path == base or base in path.parents for base in self.bases):
            raise ValueError('目录不在服务端 library-base 授权范围内')
        return path

    def sources(self):
        with self.store.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM library_sources ORDER BY name')]
        for row in rows:
            try:
                self.allowed(row['path'])
            except (ValueError, OSError):
                row.update(state='offline', message='目录离线或不在当前授权范围；保留索引')
        return rows

    def snapshot(self):
        with self.store.connect() as db:
            complete = db.execute("SELECT value FROM app_settings WHERE key='setup_complete'").fetchone()
        return {'setup_complete': bool(complete), 'bases':[str(p) for p in self.bases],
                'sources': self.sources(), 'scanning':self.lock.locked(), 'interval_seconds':self.interval}

    def add(self, path, name='', source_id=None):
        root = self.allowed(path)
        with self.lock, self.store.connect() as db:
            # Disallow overlapping roots so a single tree has one stable logical source.
            for row in db.execute('SELECT id,path FROM library_sources'):
                existing = Path(row['path'])
                if row['id'] != source_id and (root == existing or root in existing.parents or existing in root.parents):
                    raise ValueError('目录已登记或与现有目录重叠')
            if source_id:
                if not db.execute('SELECT 1 FROM library_sources WHERE id=?',(source_id,)).fetchone():
                    raise ValueError('来源不存在')
                db.execute("UPDATE library_sources SET path=?,state='pending',message='路径已重新绑定，等待扫描' WHERE id=?", (str(root),source_id))
            else:
                source_id = uuid.uuid4().hex
                db.execute('INSERT INTO library_sources VALUES(?,?,?,?,?,?)', (source_id,name[:200] or root.name,str(root),'pending',None,'等待扫描'))
        self.store.log('library','info','source_bound',source_id,'已登记或重新绑定现有目录',{'path':str(root)})
        self.trigger()
        return source_id

    def scan(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            for source in self.sources():
                if self.stop.is_set(): break
                sid, token = source['id'], uuid.uuid4().hex
                counts = {'indexed':0,'unsupported':0,'unstable':0}
                self.store.log('library','info','scan_started',sid,'开始只读目录扫描',{})
                try:
                    root = self.allowed(source['path'])
                    def walk_error(error): raise error
                    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
                        dirs[:] = [d for d in dirs if not (Path(directory)/d).is_symlink()]
                        for name in files:
                            if self.stop.is_set(): raise InterruptedError()
                            path=Path(directory)/name
                            if path.is_symlink() or name.lower().endswith(('.part','.partial','.tmp','.crdownload')):
                                continue
                            before=path.stat()
                            with path.open('rb') as stream:
                                signature=stream.read(64); kind=media_type(signature)
                                if not kind:
                                    counts['unsupported']+=1;continue
                                digest=hashlib.sha256(signature)
                                for chunk in iter(lambda:stream.read(1024**2),b''):
                                    if self.stop.is_set():raise InterruptedError()
                                    digest.update(chunk)
                            after=path.stat()
                            if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino) or time.time()-after.st_mtime < 2:
                                counts['unstable']+=1
                                # Preserve an existing location while a file is actively changing.
                                with self.store.connect() as db:
                                    db.execute('UPDATE file_locations SET seen=? WHERE source_id=? AND relative_path=?',(token,sid,str(path.relative_to(root))))
                                continue
                            sha=digest.hexdigest();relative=str(path.relative_to(root))
                            with self.store.lock, self.store.connect() as db:
                                db.execute('INSERT OR IGNORE INTO photos VALUES(?,?,?,?,?)',(sha,name,after.st_size,kind,now()))
                                db.execute('INSERT OR REPLACE INTO file_locations VALUES(?,?,?,?,?,?,1)',(sid,relative,sha,after.st_size,after.st_mtime_ns,token))
                            counts['indexed']+=1
                    with self.store.connect() as db:
                        db.execute('UPDATE file_locations SET available=0 WHERE source_id=? AND seen<>?',(sid,token))
                        db.execute("UPDATE library_sources SET state='online',last_scan=?,message=? WHERE id=?",(now(),json.dumps(counts),sid))
                    self.store.log('library','info','scan_finished',sid,'目录扫描完成',counts)
                except (OSError, ValueError):
                    with self.store.connect() as db:
                        db.execute("UPDATE library_sources SET state='offline',message='扫描中断或目录不可访问；保留上次索引' WHERE id=?",(sid,))
                    self.store.log('library','warning','scan_failed',sid,'扫描未完整完成，保留索引',counts)
        finally:
            self.lock.release()

    def trigger(self):
        if self.lock.locked(): return False
        job=threading.Thread(target=self.scan,daemon=True)
        self.jobs = [j for j in self.jobs if j.is_alive()]
        self.jobs.append(job);job.start();return True

    def loop(self):
        while not self.stop.is_set():
            self.scan()
            if self.stop.wait(self.interval): break

    def route(self,h):
        path=urlsplit(h.path).path
        if not path.startswith('/api/v1/library'):return False
        try:
            if h.command=='GET':
                if path=='/api/v1/library':h.send(200,self.snapshot());return True
                if path=='/api/v1/library/manifest':
                    with self.store.connect() as db:
                        locations=[dict(r) for r in db.execute('SELECT * FROM file_locations')]
                        pairs=[dict(r) for r in db.execute('SELECT * FROM live_pairs')]
                        photos=[dict(r) for r in db.execute('SELECT * FROM photos')]
                    h.send(200,{'format':'photosync-library','format_version':1,'sources':self.sources(),'locations':locations,'live_pairs':pairs,'photos':photos});return True
            if h.command=='POST':
                if h.headers.get('Sec-Fetch-Site')=='cross-site':h.send(403,{'error':'不允许跨站请求'});return True
                if path=='/api/v1/library/scan':h.send(202 if self.trigger() else 409,{'queued':True});return True
                if path=='/api/v1/library/finish':
                    with self.store.connect() as db:db.execute("INSERT OR REPLACE INTO app_settings VALUES('setup_complete','true')")
                    h.send(200,{'setup_complete':True});return True
                length=int(h.headers.get('Content-Length','0'))
                if not 0<length<=8192:raise ValueError('配置请求过大或为空')
                data=json.loads(h.rfile.read(length))
                if path=='/api/v1/library/sources':
                    sid=self.add(data['path'],data.get('name',''),data.get('source_id'))
                    h.send(201,{'id':sid});return True
            h.send(404,{'error':'接口不存在'});return True
        except (ValueError,OSError,KeyError,TypeError):
            self.store.log('library','warning','configuration_rejected','','目录登记失败',{})
            h.send(400,{'error':'目录无效、未获授权、重复或不可访问，请检查服务端路径'});return True

    def close(self):
        self.stop.set();self.worker.join()
        for job in self.jobs:job.join()
