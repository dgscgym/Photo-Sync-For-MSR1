import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from server.app import make_server

class SetupAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.media=root/'media';self.media.mkdir();self.configs=root/'configs';self.configs.mkdir()
        (self.configs/'snapraid.conf').write_text('# test config')
        for name in ['one','two','three']:(self.media/name).mkdir()
        self.server=make_server(root/'data',port=0,library_bases=[self.media],storage_bases=[self.media],snapraid_config_bases=[self.configs])
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.cookie='';self.cookies={}

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def call(self,path,data=None,method=None,cookie=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        body=json.dumps(data).encode() if data is not None else None
        c.request(method or ('POST' if data is not None else 'GET'),path,body,{'Content-Type':'application/json','Cookie':self.cookie if cookie is None else cookie})
        r=c.getresponse();raw=r.read();status=r.status
        if r.getheader('Set-Cookie') is not None:
            key,value=r.getheader('Set-Cookie').split(';')[0].split('=',1);self.cookies[key]=value;self.cookie='; '.join(k+'='+v for k,v in self.cookies.items())
        headers=dict(r.getheaders());c.close()
        try:result=json.loads(raw)
        except (ValueError,UnicodeError):result=raw
        if isinstance(result,dict) and result.get('mfa_required'):
            from tests.test_api import finish_mfa
            response=finish_mfa(self.server,result,lambda path,data:self.call(path,data))
            return status,response[1],response[2]
        return status,result,headers

    def bootstrap(self):
        credentials={'username':'owner','password':'correct-password-123'}
        self.assertEqual(self.call('/api/v1/auth/bootstrap',credentials)[0],201)
        return credentials

    def test_independent_setup_multi_directory_then_login(self):
        self.assertEqual(self.call('/')[2]['Location'],'/setup/welcome')
        self.assertEqual(self.call('/api/v1/photos/'+'a'*64)[0],401)
        self.assertEqual(self.call('/setup/welcome')[0],200)
        credentials=self.bootstrap()
        for path in ['welcome','library','snapraid','review']:self.assertEqual(self.call('/setup/'+path)[0],200)
        self.assertEqual(self.call('/api/v1/uploads',{'name':'x','size':1})[0],401)
        sources=[{'path':str(self.media/name)} for name in ['one','two']]
        self.assertEqual(self.call('/api/v1/library/sources/batch',{'sources':sources})[0],201)
        bad=[{'path':str(self.media/'three')},{'path':str(self.media/'one')}]
        self.assertEqual(self.call('/api/v1/library/sources/batch',{'sources':bad})[0],400)
        self.assertEqual(len(self.server.library.sources()),2)
        self.assertEqual(self.call('/api/v1/setup/finish',{})[0],400)
        self.assertEqual(self.call('/api/v1/setup/snapraid',{'skip':True})[0],200)
        self.assertEqual(self.call('/api/v1/setup/finish',{})[0],200)
        self.assertEqual(self.call('/api/v1/status')[0],401)
        self.assertEqual(self.call('/')[2]['Location'],'/login')
        self.assertEqual(self.call('/api/v1/auth/login',credentials)[0],200)
        self.assertEqual(self.call('/api/v1/status')[0],200)
        self.assertEqual(self.call('/api/v1/auth/bootstrap',credentials)[0],409)
        self.assertEqual(self.call('/api/v1/auth/logout',{})[0],200)
        self.assertEqual(self.call('/api/v1/logs')[0],401)

    def test_snapraid_setup_persisted_and_path_restricted(self):
        self.bootstrap()
        data={'snapraid_config':str(self.configs/'snapraid.conf'),'mounts':[{'path':str(self.media/'one'),'identity':'one'}],'interval_seconds':60}
        with patch('server.monitor.Monitor.check'):
            self.assertEqual(self.call('/api/v1/setup/snapraid',data)[0],200)
            persisted=Path(self.tmp.name)/'data'/'snapraid-monitor.json'
            self.assertEqual(json.loads(persisted.read_text())['mounts'][0]['identity'],'one')
        data['snapraid_config']=str(Path(self.tmp.name)/'outside.conf')
        self.assertEqual(self.call('/api/v1/setup/snapraid',data)[0],400)
        self.assertEqual(self.call('/api/v1/setup/snapraid',{'skip':True})[0],400)

    def test_password_hash_and_login_rate_limit(self):
        credentials=self.bootstrap()
        row=self.server.auth.account();self.assertNotIn(credentials['password'],row['password_hash'])
        self.assertEqual(len(row['password_hash']),64)
        for _ in range(5):self.assertEqual(self.call('/api/v1/auth/login',{'username':'owner','password':'wrong'})[0],401)
        self.assertEqual(self.call('/api/v1/auth/login',credentials)[0],429)
        self.assertEqual(self.call('/api/v1/auth/logout',{})[0],200)
        self.assertEqual(self.call('/api/v1/library')[0],401)
