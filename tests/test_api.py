import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from server.app import make_server

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII=')

def finish_mfa(server,challenge,send):
    from server.auth import totp
    from unittest.mock import patch
    import time
    with server.library.store.connect() as db:
        pending=db.execute('SELECT * FROM auth_challenges WHERE token_hash=?',(__import__('hashlib').sha256(challenge['ticket'].encode()).hexdigest(),)).fetchone()
        user=db.execute('SELECT * FROM users WHERE id=?',(pending['user_id'],)).fetchone()
    secret=challenge.get('secret') or server.auth.cipher.decrypt(user['totp_secret'].encode()).decode()
    timestamp=max(time.time(),(user['totp_last_step']+1)*30)
    with patch('server.auth.time.time',return_value=timestamp):
        return send('/api/v1/auth/mfa/verify',{'ticket':challenge['ticket'],'code':totp(secret,timestamp)})

def authenticate(server):
    cookies={}
    def call(path,data):
        c=http.client.HTTPConnection('127.0.0.1',server.server_port)
        c.request('POST',path,json.dumps(data).encode(),{'Content-Type':'application/json','Cookie':'; '.join(k+'='+v for k,v in cookies.items())})
        r=c.getresponse();status=r.status;result=json.loads(r.read());cookie=r.getheader('Set-Cookie');c.close()
        if cookie:
            key,value=cookie.split(';')[0].split('=',1);cookies[key]=value
        if result.get('mfa_required'):return finish_mfa(server,result,call)
        assert status<400,(path,status,result)
        return result
    credentials={'username':'test-admin','password':'test-password-12345'}
    call('/api/v1/auth/login' if server.auth.account() else '/api/v1/auth/bootstrap',credentials)
    if not server.auth.complete():
        call('/api/v1/setup/snapraid',{'skip':True});call('/api/v1/setup/finish',{});call('/api/v1/auth/login',credentials)
    client_credentials={'username':'test-client','password':'test-client-password-12345'}
    if not server.auth.account('test-client'):call('/api/v1/admin/users',client_credentials)
    call('/api/v1/auth/login',dict(client_credentials,audience='client'))
    return '; '.join(k+'='+v for k,v in cookies.items())

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.start()

    def start(self):
        self.server = make_server(self.tmp.name, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie=authenticate(self.server)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def tearDown(self):
        self.stop(); self.tmp.cleanup()

    def request(self, method, path, data=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        client.request(method, path, data, dict({'Cookie':self.cookie}, **(headers or {})))
        result = client.getresponse(); status = result.status; body = result.read(); client.close()
        return status, body

    def upload(self, data=PNG):
        status, body = self.request('POST', '/api/v1/photos', data, {'X-Filename': 'photo.png'})
        return status, json.loads(body)

    def test_parallel_deduplication_and_restart(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.upload(), range(8)))
        self.assertEqual([status for status, _ in results].count(201), 1)
        self.assertEqual(sum(result['duplicate'] for _, result in results), 7)
        self.assertEqual(len(list((Path(self.tmp.name) / 'originals').iterdir())), 1)
        digest = hashlib.sha256(PNG).hexdigest()
        self.assertEqual(self.request('GET', '/api/v1/photos/' + digest), (200, PNG))
        self.stop(); self.start()
        self.assertTrue(self.upload()[1]['duplicate'])
        state = json.loads(self.request('GET', '/api/v1/status')[1])
        self.assertEqual(state['stats']['photos'], 1)
        self.assertEqual(state['stats']['duplicates'], 8)
        self.assertEqual(state['capabilities']['cloud115'], 'not_connected')

    def test_reject_invalid_and_large_uploads(self):
        self.assertEqual(self.upload(b'not an image')[0], 415)
        self.assertEqual(self.request('POST', '/api/v1/photos', b'', {'Content-Length': str(51*1024*1024)})[0], 413)
        self.assertEqual(json.loads(self.request('GET', '/api/v1/status')[1])['stats']['photos'], 0)
        self.assertFalse(list(Path(self.tmp.name).glob('tmp*')))

    def test_static_routes_and_path_boundaries(self):
        self.assertEqual(self.request('GET', '/')[0], 302)
        self.assertEqual(self.request('GET', '/admin')[0], 200)
        self.assertEqual(self.request('GET', '/client')[0], 200)
        self.assertEqual(self.request('GET', '/style.css')[0], 200)
        self.assertEqual(self.request('GET', '/api/v1/photos/../../key/key.txt')[0], 404)
        self.assertEqual(self.request('GET', '/key/key.txt')[0], 404)
        self.assertEqual(self.request('POST', '/api/v1/photos', PNG, {'Sec-Fetch-Site': 'cross-site'})[0], 403)

if __name__ == '__main__':
    unittest.main()
