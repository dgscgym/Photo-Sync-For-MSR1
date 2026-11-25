import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from tests.test_api import ApiTests, PNG
from server.media import MAX_FILE

class MediaTests(ApiTests):
    def json_request(self, method, path, data):
        status, body = self.request(method, path, json.dumps(data).encode(), {'Content-Type': 'application/json'})
        return status, json.loads(body)

    def create(self, size, name='movie.mp4'):
        status, body = self.json_request('POST', '/api/v1/uploads', {'name': name, 'size': size})
        self.assertEqual(status, 201)
        return '/api/v1/uploads/' + body['id']

    def finish(self, content, name):
        route = self.create(len(content), name)
        self.assertEqual(self.request('PATCH', route, content, {'Upload-Offset':'0'})[0], 200)
        status, body = self.request('POST', route + '/complete')
        self.assertEqual(status, 201)
        return json.loads(body)['sha256']

    def test_chunk_resume_restart_and_live_pair(self):
        movie = b'\x00\x00\x00\x18ftypqt  ' + b'video' * 100
        route = self.create(len(movie))
        self.assertEqual(self.request('PATCH', route, movie[:20], {'Upload-Offset':'0'})[0], 200)
        self.assertEqual(self.request('PATCH', route, movie[:20], {'Upload-Offset':'0'})[0], 409)
        self.assertEqual(self.request('POST', route + '/complete')[0], 409)
        self.stop(); self.start()
        self.assertEqual(json.loads(self.request('GET', route)[1])['offset'], 20)
        self.assertEqual(self.request('PATCH', route, movie[20:], {'Upload-Offset':'20'})[0], 200)
        status, body = self.request('POST', route + '/complete'); self.assertEqual(status, 201)
        video = json.loads(body)['sha256']
        self.assertEqual(json.loads(self.request('POST', route + '/complete')[1])['sha256'], video)
        photo = self.finish(PNG, 'live.png')
        self.assertEqual(self.json_request('POST', '/api/v1/live-pairs', {'photo':photo,'video':video})[0], 200)
        snapshot = json.loads(self.request('GET','/api/v1/status')[1])
        self.assertEqual(next(p for p in snapshot['photos'] if p['sha256'] == photo)['live_video'], video)
        self.assertEqual(self.request('GET','/api/v1/photos/' + video)[1], movie)

    def test_limits_and_actual_51_mib(self):
        self.assertEqual(self.json_request('POST', '/api/v1/uploads', {'name':'big.mp4','size':MAX_FILE+1})[0], 413)
        boundary = self.create(MAX_FILE)
        self.assertEqual(self.request('DELETE', boundary)[0], 200)
        total = 51 * 1024**2
        route = self.create(total)
        digest = hashlib.sha256(); offset = 0
        while offset < total:
            chunk = b'\x00' * min(8*1024**2, total-offset)
            if offset == 0: chunk = b'\x00\x00\x00\x18ftypisom' + chunk[12:]
            digest.update(chunk)
            self.assertEqual(self.request('PATCH', route, chunk, {'Upload-Offset':str(offset)})[0], 200)
            offset += len(chunk)
        result = json.loads(self.request('POST',route+'/complete')[1])
        self.assertEqual(result['sha256'],digest.hexdigest())
        # A 10-GiB sparse fixture validates 64-bit offsets and range serving without allocating 10 GiB.
        path = Path(self.tmp.name)/'originals'/result['sha256']
        with path.open('r+b') as stream:
            stream.truncate(MAX_FILE); stream.seek(MAX_FILE-4); stream.write(b'TAIL')
        status, body = self.request('GET', '/api/v1/photos/'+result['sha256'], headers={'Range':f'bytes={MAX_FILE-4}-'})
        self.assertEqual((status,body),(206,b'TAIL'))

    def test_range_and_heic_preservation(self):
        photo = self.finish(PNG,'photo.png'); route='/api/v1/photos/'+photo
        self.assertEqual(self.request('GET',route,headers={'Range':'bytes=2-8'}),(206,PNG[2:9]))
        self.assertEqual(self.request('GET',route,headers={'Range':'bytes=-4'}),(206,PNG[-4:]))
        self.assertEqual(self.request('GET',route,headers={'Range':'bytes=9999-'} )[0],416)
        self.assertEqual(self.request('HEAD',route),(200,b''))
        heic=b'\x00\x00\x00\x18ftypheic'+b'\0'*50
        digest=self.finish(heic,'photo.heic')
        self.assertEqual(self.request('GET','/api/v1/photos/'+digest)[1],heic)

    def test_real_video_preview_when_ffmpeg_available(self):
        if not shutil.which('ffmpeg'): self.skipTest('FFmpeg not installed')
        video = Path(self.tmp.name)/'sample.mov'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:d=0.2','-c:v','libx264',str(video)],check=True)
        digest=self.finish(video.read_bytes(),'sample.mov')
        route='/api/v1/previews/'+digest
        for _ in range(100):
            state=json.loads(self.request('POST',route)[1])['state']
            if state in ('ready','failed'):break
            time.sleep(.1)
        self.assertEqual(state,'ready')
        self.assertEqual(self.request('GET',route,headers={'Range':'bytes=0-31'})[0],206)
