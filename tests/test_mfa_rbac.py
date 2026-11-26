import base64
import hashlib
import http.client
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import cbor2
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from server.app import make_server
from server.auth import totp
from webauthn.helpers import bytes_to_base64url as b64

class MfaRbacTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.server=make_server(self.tmp.name,port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.owner={}
        self.creds={'username':'owner','password':'correct-password-123'}

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def request(self,path,data=None,jar=None,method=None,body=None,headers=None):
        jar=self.owner if jar is None else jar
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        extra={'Cookie':'; '.join(k+'='+v for k,v in jar.items())};extra.update(headers or {})
        if data is not None:body=json.dumps(data).encode();extra['Content-Type']='application/json'
        c.request(method or ('POST' if data is not None or body is not None else 'GET'),path,body,extra)
        r=c.getresponse();raw=r.read();cookie=r.getheader('Set-Cookie');status=r.status
        if cookie:k,v=cookie.split(';')[0].split('=',1);jar[k]=v
        c.close()
        try:result=json.loads(raw)
        except (ValueError,UnicodeError):result=raw
        return status,result

    def factor(self,challenge,jar=None):
        with self.server.library.store.connect() as db:
            pending=db.execute('SELECT * FROM auth_challenges WHERE token_hash=?',(hashlib.sha256(challenge['ticket'].encode()).hexdigest(),)).fetchone()
            user=db.execute('SELECT * FROM users WHERE id=?',(pending['user_id'],)).fetchone()
        secret=challenge.get('secret') or self.server.auth.cipher.decrypt(user['totp_secret'].encode()).decode()
        timestamp=max(time.time(),(user['totp_last_step']+1)*30)
        with patch('server.auth.time.time',return_value=timestamp):return self.request('/api/v1/auth/mfa/verify',{'ticket':challenge['ticket'],'code':totp(secret,timestamp)},jar)

    def login(self,creds,audience,jar):
        status,start=self.request('/api/v1/auth/login',dict(creds,audience=audience),jar)
        self.assertEqual(status,200);self.assertTrue(start['mfa_required'])
        status,result=self.factor(start,jar);self.assertEqual(status,200);return result

    def ready(self):
        status,start=self.request('/api/v1/auth/bootstrap',self.creds);self.assertEqual(status,201)
        result=self.factor(start)[1]
        self.request('/api/v1/setup/snapraid',{'skip':True});self.request('/api/v1/setup/finish',{})
        self.login(self.creds,'admin',self.owner)
        return result

    def test_totp_is_mandatory_and_challenge_one_time(self):
        self.assertEqual(totp(base64.b32encode(b'12345678901234567890').decode(),59),'287082')
        _,start=self.request('/api/v1/auth/bootstrap',self.creds)
        self.assertFalse(self.owner)
        self.assertEqual(self.request('/api/v1/status')[0],401)
        status,result=self.factor(start);self.assertEqual(status,200);self.assertEqual(len(result['recovery_codes']),10)
        self.assertEqual(self.request('/api/v1/auth/mfa/verify',{'ticket':start['ticket'],'code':'000000'})[0],400)
        row=self.server.auth.account();self.assertNotEqual(row['totp_secret'],start['secret'])
        self.assertEqual(self.server.auth.cipher.decrypt(row['totp_secret'].encode()).decode(),start['secret'])
        self.request('/api/v1/setup/snapraid',{'skip':True});self.request('/api/v1/setup/finish',{})
        _,pending=self.request('/api/v1/auth/login',self.creds)
        self.assertEqual(self.request('/api/v1/status')[0],401)
        code=result['recovery_codes'][0]
        self.assertEqual(self.request('/api/v1/auth/mfa/verify',{'ticket':pending['ticket'],'code':code})[0],200)
        _,pending=self.request('/api/v1/auth/login',self.creds)
        self.assertEqual(self.request('/api/v1/auth/mfa/verify',{'ticket':pending['ticket'],'code':code})[0],401)

    def test_role_media_and_upload_session_isolation(self):
        self.ready()
        alice={'username':'alice','password':'alice-password-123'};bob={'username':'bob','password':'bob-password-123'}
        self.assertEqual(self.request('/api/v1/admin/users',dict(alice,server_access=False))[0],200)
        self.assertEqual(self.request('/api/v1/admin/users',bob)[0],200)
        a={};b={};self.login(alice,'client',a);self.login(bob,'client',b)
        self.assertEqual(self.request('/api/v1/admin/users',jar=a)[0],401)
        self.assertEqual(self.request('/api/v1/library',jar=a)[0],401)
        self.assertEqual(self.request('/api/v1/auth/login',dict(alice,audience='admin'),a)[0],403)
        png=b'\x89PNG\r\n\x1a\nphoto'
        _,upload=self.request('/api/v1/uploads',{'name':'a.png','size':len(png)},a)
        route='/api/v1/uploads/'+upload['id']
        self.assertEqual(self.request(route,jar=b)[0],404)
        self.assertEqual(self.request(route,jar=a,method='PATCH',body=png,headers={'Upload-Offset':'0'})[0],200)
        _,done=self.request(route+'/complete',{},a);digest=done['sha256']
        self.assertEqual(self.request('/api/v1/photos/'+digest+'?app=client',jar=a)[0],200)
        self.assertEqual(self.request('/api/v1/photos/'+digest+'?app=client',jar=b)[0],404)
        self.assertEqual(len(self.request('/api/v1/client/status',jar=a)[1]['photos']),1)
        self.assertEqual(len(self.request('/api/v1/client/status',jar=b)[1]['photos']),0)
        self.assertTrue(self.request('/api/v1/client/logs',jar=a)[1]['items'])
        self.assertFalse(self.request('/api/v1/client/logs',jar=b)[1]['items'])
        users=self.request('/api/v1/admin/users')[1]['users'];aid=next(u['id'] for u in users if u['username']=='alice')
        self.request('/api/v1/admin/users',{'id':aid,'server_access':True,'active':True})
        self.assertEqual(self.request('/api/v1/client/status',jar=a)[0],401)
        self.login(alice,'admin',a);self.assertEqual(self.request('/api/v1/admin/users',jar=a)[0],200)

    def test_real_webauthn_signature_and_periodic_mfa(self):
        self.ready();client={};client_creds={'username':'device-user','password':'device-password-123'}
        self.request('/api/v1/admin/users',dict(client_creds,server_access=True))
        self.login(client_creds,'client',client)
        _,start=self.request('/api/v1/auth/passkey/register/options',{'audience':'client'},client)
        options=start['options'];origin=self.server.auth.origin;rp=self.server.auth.rp_id
        private=ec.generate_private_key(ec.SECP256R1());public=private.public_key().public_numbers();credential_id=b'physical-device-test-credential'
        cose=cbor2.dumps({1:2,3:-7,-1:1,-2:public.x.to_bytes(32,'big'),-3:public.y.to_bytes(32,'big')})
        auth_data=hashlib.sha256(rp.encode()).digest()+b'\x45'+struct.pack('>I',0)+b'\x00'*16+struct.pack('>H',len(credential_id))+credential_id+cose
        client_data=json.dumps({'type':'webauthn.create','challenge':options['challenge'],'origin':origin}).encode()
        credential={'id':b64(credential_id),'rawId':b64(credential_id),'type':'public-key','response':{'clientDataJSON':b64(client_data),'attestationObject':b64(cbor2.dumps({'fmt':'none','authData':auth_data,'attStmt':{}}))}}
        self.assertEqual(self.request('/api/v1/auth/passkey/register/verify',{'ticket':start['ticket'],'credential':credential,'audience':'client'},client)[0],200)
        _,login=self.request('/api/v1/auth/login',dict(client_creds,audience='client'),client)
        self.assertIn('passkey_options',login)
        raw=json.dumps({'type':'webauthn.get','challenge':login['passkey_options']['challenge'],'origin':origin}).encode()
        data=hashlib.sha256(rp.encode()).digest()+b'\x05'+struct.pack('>I',1)
        signature=private.sign(data+hashlib.sha256(raw).digest(),ec.ECDSA(hashes.SHA256()))
        assertion={'id':b64(credential_id),'rawId':b64(credential_id),'type':'public-key','response':{'clientDataJSON':b64(raw),'authenticatorData':b64(data),'signature':b64(signature)}}
        invalid=json.loads(json.dumps(assertion));invalid['response']['signature']=b64(b'invalid-signature')
        self.assertEqual(self.request('/api/v1/auth/passkey/login',{'ticket':login['ticket'],'credential':invalid},client)[0],401)
        self.assertEqual(self.request('/api/v1/auth/passkey/login',{'ticket':login['ticket'],'credential':assertion},client)[0],200)
        self.assertEqual(self.request('/api/v1/auth/passkey/login',{'ticket':login['ticket'],'credential':assertion},client)[0],400)
        with self.server.library.store.connect() as db:db.execute('UPDATE passkeys SET trusted_until=0')
        _,expired=self.request('/api/v1/auth/login',dict(client_creds,audience='client'),client)
        self.assertNotIn('passkey_options',expired)
        self.assertEqual(self.request('/api/v1/auth/passkey/login',{'ticket':expired['ticket'],'credential':assertion},client)[0],400)
        _,admin=self.request('/api/v1/auth/login',dict(client_creds,audience='admin'))
        self.assertNotIn('passkey_options',admin)
        self.assertEqual(self.request('/api/v1/auth/passkey/login',{'ticket':admin['ticket'],'credential':assertion},client)[0],400)
