import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from server.app import Store, make_server
from server.monitor import Monitor
import http.client
from tests.test_api import authenticate

class LogMonitorTests(unittest.TestCase):
    def test_upload_failure_and_restart_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            server = make_server(directory, port=0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            cookie=authenticate(server)
            def request(method,path,body=None):
                c=http.client.HTTPConnection('127.0.0.1',server.server_port)
                c.request(method,path,body,{"Cookie":cookie}); r=c.getresponse(); status=r.status; data=json.loads(r.read());c.close();return status,data
            try:
                self.assertEqual(request('POST','/api/v1/photos',b'bad')[0],415)
                status, result=request('GET','/api/v1/logs?category=upload&level=warning')
                self.assertEqual(status,200);self.assertEqual(result['items'][0]['details']['http_status'],415)
                self.assertEqual(request('GET','/api/v1/snapraid')[1]['state'],'unknown')
            finally:
                server.shutdown();server.server_close();thread.join()
            store=Store(directory)
            self.assertEqual(len(store.logs('upload')['items']),1)
            baseline=len(store.logs('snapraid')['items'])
            for i in range(105):store.log('snapraid','info','test',str(i),'test',{})
            first=store.logs('snapraid');self.assertEqual(len(first['items']),100)
            second=store.logs('snapraid',first['next_before']);self.assertEqual(len(second['items']),5+baseline)
            self.assertFalse(set(r['id'] for r in first['items']) & set(r['id'] for r in second['items']))

    def test_monitor_failure_acknowledgement_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory); monitor=Monitor(store)
            monitor.check()
            self.assertEqual(monitor.snapshot()['state'],'unknown')
            cfg=Path(directory)/'snapraid.conf';cfg.touch()
            mount=Path(directory)/'disk';mount.mkdir();(mount/'.photosync-volume-id').write_text('disk1')
            monitor.config='configured'
            monitor.settings={'executable':'snapraid','snapraid_config':str(cfg),'mounts':[{'path':str(mount),'identity':'disk1'}]}
            with patch('server.monitor.shutil.which', return_value='/test/snapraid'), patch('server.monitor.os.path.ismount', return_value=False):
                monitor.check()
            self.assertEqual(monitor.snapshot()['state'],'critical')
            monitor.acknowledge();self.assertTrue(monitor.snapshot()['acknowledged'])
            self.assertEqual(monitor.snapshot()['state'],'critical')
            self.assertEqual(Monitor(store).snapshot()['acknowledged'],1)
            with patch('server.monitor.shutil.which', return_value='/test/snapraid'), patch('server.monitor.os.path.ismount', return_value=True):
                with patch('server.monitor.subprocess.run', side_effect=subprocess.TimeoutExpired('snapraid',30)):
                    monitor.check()
                self.assertEqual(monitor.snapshot()['state'],'unknown')
                with patch('server.monitor.subprocess.run', return_value=subprocess.CompletedProcess([],1)):
                    monitor.check()
                self.assertEqual(monitor.snapshot()['state'],'critical')
                with patch('server.monitor.subprocess.run', return_value=subprocess.CompletedProcess([],0)) as run:
                    monitor.check()
                    self.assertEqual(run.call_args[0][0][-1],'status')
                    self.assertNotIn('shell',run.call_args[1])
                self.assertEqual(monitor.snapshot()['state'],'warning')
            messages=store.logs('snapraid')['items'];self.assertTrue(any(row['action']=='check_started' for row in messages))
            self.assertTrue(any(row['action']=='check_finished' for row in messages))
            with store.connect() as db:db.execute("UPDATE monitor_state SET checked_at='2000-01-01T00:00:00+00:00'")
            self.assertEqual(monitor.snapshot()['state'],'unknown')
            self.assertIn('过期',monitor.snapshot()['message'])

    def test_legacy_upload_history_migrated_once(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with store.connect() as db:
                db.execute("DELETE FROM audit_migrations WHERE name='legacy_events'")
                db.execute("INSERT INTO events(sha256,kind,created_at) VALUES(?,?,?)",('a'*64,'uploaded','2026-11-25T00:00:00+00:00'))
            upgraded=Store(directory)
            self.assertEqual(len(upgraded.logs('upload')['items']),1)
            self.assertEqual(len(Store(directory).logs('upload')['items']),1)

    def test_periodic_monitor_runs_without_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor=Monitor(Store(directory));monitor.interval=.01
            count=[]
            def check():
                count.append(1)
                if len(count)==2:monitor.stop_event.set()
            with patch.object(monitor,'check',side_effect=check):monitor.loop()
            self.assertEqual(len(count),2)
