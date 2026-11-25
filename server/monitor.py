"""Read-only SnapRAID monitoring; no sync/fix or shell execution."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time


def now():
    return datetime.now(timezone.utc).isoformat()


class Monitor:
    def __init__(self, store, config=None):
        self.store = store
        self.config = config
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.manual_thread = None
        self.trigger_lock = threading.Lock()
        self.interval = 3600
        self.timeout = 30
        if config:
            data = json.loads(Path(config).read_text())
            self.interval = max(30, int(data.get('interval_seconds', 3600)))
            self.timeout = max(1, min(120, int(data.get('timeout_seconds', 30))))
            self.settings = data
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS monitor_state(
                id INTEGER PRIMARY KEY CHECK(id=1), state TEXT, message TEXT,
                checked_at TEXT, acknowledged INTEGER NOT NULL DEFAULT 0)''')
            if not db.execute('SELECT 1 FROM monitor_state').fetchone():
                db.execute('INSERT INTO monitor_state VALUES(1,?,?,?,0)',
                           ('unknown', 'SnapRAID 未配置，无法确认多盘保护状态', None))
        if config:
            self.thread = threading.Thread(target=self.loop, daemon=True)
            self.thread.start()

    def snapshot(self):
        with self.store.connect() as db:
            data = dict(db.execute('SELECT * FROM monitor_state WHERE id=1').fetchone())
        data['configured'] = bool(self.config)
        data['interval_seconds'] = self.interval
        data['running'] = self.lock.locked()
        if not self.config:
            data.update(state='unknown', message='SnapRAID 未配置，无法确认多盘保护状态')
        elif data['checked_at'] and time.time() - datetime.fromisoformat(data['checked_at']).timestamp() > self.interval * 2 + self.timeout:
            data.update(state='unknown', message='SnapRAID 检查已过期，请重新检查')
        return data

    def update(self, state, message, details, task_id):
        with self.store.connect() as db:
            previous = db.execute('SELECT * FROM monitor_state WHERE id=1').fetchone()
            acknowledged = previous['acknowledged'] if previous['state'] == state and previous['message'] == message else 0
            db.execute('UPDATE monitor_state SET state=?,message=?,checked_at=?,acknowledged=? WHERE id=1',
                       (state, message, now(), acknowledged))
        self.store.log('snapraid', 'error' if state == 'critical' else 'warning', 'check_finished',
                       task_id, message, details)

    def check(self):
        if not self.lock.acquire(blocking=False):
            return
        import uuid
        task_id = uuid.uuid4().hex
        self.store.log('snapraid', 'info', 'check_started', task_id, '开始只读健康检查', {})
        try:
            if not self.config:
                self.update('unknown', 'SnapRAID 未配置，无法确认多盘保护状态', {}, task_id)
                return
            executable = shutil.which(self.settings.get('executable', 'snapraid'))
            config = Path(self.settings.get('snapraid_config', ''))
            if not executable or not config.is_file():
                self.update('unknown', 'SnapRAID 命令或配置不可用', {}, task_id)
                return
            mounts = self.settings.get('mounts', [])
            if not mounts:
                self.update('unknown', '未配置受保护磁盘的挂载和身份检查', {}, task_id)
                return
            for mount in mounts:
                path = Path(mount['path'])
                if not os.path.ismount(path) or (path / '.photosync-volume-id').read_text().strip() != mount['identity']:
                    self.update('critical', '磁盘未挂载或身份不匹配，请检查存储', {'mount': str(path)}, task_id)
                    return
            with tempfile.TemporaryFile() as output:
                try:
                    result = subprocess.run([executable, '-c', str(config), 'status'],
                                            stdout=output, stderr=subprocess.STDOUT, timeout=self.timeout, check=False)
                    output.seek(0)
                    text = output.read(65536).decode('utf-8', errors='replace')
                    if result.returncode != 0:
                        self.update('critical', 'SnapRAID status 检查失败', {'exit_code':result.returncode, 'output':text}, task_id)
                    else:
                        # A successful command alone is not evidence of fresh parity or scrub.
                        self.update('warning', '状态命令执行成功；保护时间与 scrub 结果仍需核实', {'exit_code':0, 'output':text}, task_id)
                except subprocess.TimeoutExpired:
                    self.update('unknown', 'SnapRAID 检查超时', {'timeout_seconds':self.timeout}, task_id)
        except Exception:
            self.update('critical', '检查失败：存储或检查配置不可用', {}, task_id)
        finally:
            self.lock.release()

    def trigger(self):
        with self.trigger_lock:
            if self.lock.locked() or (self.manual_thread and self.manual_thread.is_alive()):
                return False
            self.manual_thread = threading.Thread(target=self.check, daemon=True)
            self.manual_thread.start()
            return True

    def loop(self):
        while not self.stop_event.is_set():
            self.check()
            self.stop_event.wait(self.interval)

    def acknowledge(self):
        with self.store.connect() as db:
            db.execute('UPDATE monitor_state SET acknowledged=1 WHERE id=1')
        self.store.log('snapraid', 'info', 'alert_acknowledged', '', '告警已知晓，状态未解除', {})

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(self.timeout + 2)
        if self.manual_thread:
            self.manual_thread.join(self.timeout + 2)
