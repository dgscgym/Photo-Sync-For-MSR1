import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from PIL import Image,TiffImagePlugin
from server.app import make_server,Store

class PrototypeMetadataTests(unittest.TestCase):
    def test_preview_upload_and_real_image_details_without_login(self):
        with tempfile.TemporaryDirectory() as directory:
            server=make_server(directory,port=0,prototype=True)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def request(path,data=None,body=None,method=None,headers=None):
                c=http.client.HTTPConnection('127.0.0.1',server.server_port)
                if data is not None:body=json.dumps(data).encode()
                c.request(method or ('POST' if body is not None else 'GET'),path,body,headers or {})
                r=c.getresponse();raw=r.read();status=r.status;c.close()
                try:return status,json.loads(raw)
                except (ValueError,UnicodeError):return status,raw
            try:
                state=request('/api/v1/auth/status?audience=client')[1]
                self.assertTrue(state['demo']);self.assertFalse(state['mfa_enabled'])
                self.assertEqual(request('/api/v1/auth/login',data={'username':'anything','password':'anything'})[0],409)
                self.assertEqual(request('/admin')[0],200)
                self.assertEqual(request('/client/logs')[0],302)
                image=Image.new('RGB',(12,8),'blue');exif=Image.Exif();exif[271]='Example Camera';exif[272]='Unit Model';exif[33437]=TiffImagePlugin.IFDRational(28,10);exif[34855]=200
                stream=io.BytesIO();image.save(stream,format='JPEG',exif=exif);content=stream.getvalue()
                _,upload=request('/api/v1/uploads?app=admin',data={'name':'photo.jpg','size':len(content)})
                route='/api/v1/uploads/'+upload['id']
                self.assertEqual(request(route+'?app=admin',body=content,method='PATCH',headers={'Upload-Offset':'0'})[0],200)
                _,saved=request(route+'/complete?app=admin',data={})
                status,details=request('/api/v1/media-details/'+saved['sha256']+'?app=admin')
                self.assertEqual(status,200);self.assertEqual(details['resolution'],'12 × 8');self.assertEqual(details['size'],len(content))
                self.assertEqual(details['camera']['model'],'Unit Model');self.assertEqual(details['camera']['iso'],200)
                self.assertEqual(details['format'],'JPEG');self.assertTrue(details['locations'])
                self.assertEqual(request('/api/v1/media-details/'+saved['sha256']+'?app=client')[0],200)
                with server.library.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0],0)
            finally:server.shutdown();server.server_close();thread.join()
            with self.assertRaises(ValueError):make_server(directory,port=0)

    def test_preview_cannot_expose_real_accounts_or_public_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):make_server(directory,host='0.0.0.0',port=0,prototype=True)
            server=make_server(directory,port=0);server.server_close()
            with server.library.store.connect() as db:db.execute("INSERT INTO users(username,salt,password_hash,server_access,is_owner) VALUES('real','salt','hash',1,1)")
            with self.assertRaises(ValueError):make_server(directory,port=0,prototype=True)
