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

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.start()

    def start(self):
        self.server = make_server(self.tmp.name, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def tearDown(self):
        self.stop(); self.tmp.cleanup()

    def request(self, method, path, data=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        client.request(method, path, data, headers or {})
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
        self.assertEqual(self.request('GET', '/')[0], 200)
        self.assertEqual(self.request('GET', '/style.css')[0], 200)
        self.assertEqual(self.request('GET', '/api/v1/photos/../../key/key.txt')[0], 404)
        self.assertEqual(self.request('GET', '/key/key.txt')[0], 404)
        self.assertEqual(self.request('POST', '/api/v1/photos', PNG, {'Sec-Fetch-Site': 'cross-site'})[0], 403)

if __name__ == '__main__':
    unittest.main()
