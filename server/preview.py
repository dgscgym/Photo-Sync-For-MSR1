"""Optional FFmpeg browser derivatives; originals are never modified."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess
import threading

class Previews:
    def __init__(self, store):
        self.store = store
        self.directory = store.directory / 'previews'
        self.directory.mkdir(exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.Lock()
        self.states = {}

    def get(self, digest):
        with self.store.connect() as db:
            photo = db.execute('SELECT * FROM photos WHERE sha256=?', (digest,)).fetchone()
        if not photo:
            raise ValueError('资源不存在')
        video = photo['media_type'].startswith('video/')
        path = self.directory / (digest + ('.mp4' if video else '.jpg'))
        return path, 'video/mp4' if video else 'image/jpeg', video

    def start(self, digest):
        path, kind, video = self.get(digest)
        with self.lock:
            if path.exists():
                return {'state': 'ready'}
            if self.states.get(digest) in ('queued', 'processing'):
                return {'state': self.states[digest]}
            if not shutil.which('ffmpeg'):
                return {'state': 'unavailable', 'error': '服务端未安装 FFmpeg，请下载原片或安装 FFmpeg'}
            self.states[digest] = 'queued'
            self.pool.submit(self.run, digest, path, video)
            return {'state': 'queued'}

    def run(self, digest, path, video):
        temporary = path.with_name(path.stem + '.partial' + path.suffix)
        self.states[digest] = 'processing'
        source=self.store.resolve(digest)
        if source is None:
            self.states[digest]='failed'
            return
        command = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source)]
        if video:
            command += ['-map', '0:v:0', '-map', '0:a:0?', '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '25', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', '-threads', '2']
        else:
            command += ['-frames:v', '1']
        try:
            subprocess.run(command + [str(temporary)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=21600)
            temporary.replace(path)
            self.states[digest] = 'ready'
        except (subprocess.SubprocessError, OSError):
            self.states[digest] = 'failed'
        finally:
            temporary.unlink(missing_ok=True)
