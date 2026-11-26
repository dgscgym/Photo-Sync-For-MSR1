"""Exercise native-client wire contracts against real authenticated HTTP handlers."""
import io
import unittest
import json
import http.client
from PIL import Image
from tests import test_admin_client as fixtures


class AndroidContractTests(unittest.TestCase):
    setUp=fixtures.AdminClientTests.setUp
    tearDown=fixtures.AdminClientTests.tearDown
    call=fixtures.AdminClientTests.call
    bootstrap=fixtures.AdminClientTests.bootstrap
    ready=fixtures.AdminClientTests.ready
    def test_authenticated_thumbnail_and_original_integrity(self):
        self.ready()
        output=io.BytesIO()
        Image.new('RGB',(1000,800),(20,100,60)).save(output,'JPEG')
        original=output.getvalue()
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        connection.request('POST','/api/v1/photos?app=client',original,{'X-Filename':'camera.jpg','Cookie':self.cookie})
        response=connection.getresponse();self.assertEqual(response.status,201)
        photo=json.loads(response.read());connection.close()
        digest=photo['sha256']
        status,content,headers=self.call('/api/v1/thumbnails/'+digest+'?app=client')
        self.assertEqual(status,200)
        self.assertEqual(headers['Content-Type'],'image/jpeg')
        with Image.open(io.BytesIO(content)) as image:
            self.assertLessEqual(max(image.size),512)
        self.assertEqual(self.call('/api/v1/photos/'+digest+'?app=client')[1],original)
        self.call('/api/v1/auth/logout',{'audience':'client'})
        self.assertEqual(self.call('/api/v1/thumbnails/'+digest+'?app=client')[0],401)

    def test_directory_only_pagination_excludes_files(self):
        from urllib.parse import quote
        self.ready()
        root=self.media/'one'
        for i in range(105):(root/('file-%03d.txt'%i)).write_text('file')
        (root/'child').mkdir()
        status,data,_=self.call('/api/v1/library/browse?directories_only=1&path='+quote(str(root)))
        self.assertEqual(status,200)
        self.assertEqual(data['total'],1)
        self.assertIsNone(data['next_offset'])
        self.assertTrue(data['entries'][0]['directory'])
