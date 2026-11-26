"""Separate administrator/client sessions, mandatory TOTP, and verified WebAuthn."""
import base64
import hashlib
import hmac
from http.cookies import SimpleCookie
import io
import json
import os
from pathlib import Path
import secrets
import struct
import threading
import time
from urllib.parse import urlsplit, parse_qs, quote
from cryptography.fernet import Fernet
import qrcode
import qrcode.image.svg
from webauthn import generate_registration_options, verify_registration_response, generate_authentication_options, verify_authentication_response, options_to_json
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.structs import AuthenticatorSelectionCriteria, AuthenticatorAttachment, UserVerificationRequirement, PublicKeyCredentialDescriptor


def totp(secret, timestamp=None):
    counter=int((time.time() if timestamp is None else timestamp)//30)
    raw=hmac.new(base64.b32decode(secret+'='*((8-len(secret)%8)%8)),struct.pack('>Q',counter),hashlib.sha1).digest()
    offset=raw[-1]&15
    return str((struct.unpack('>I',raw[offset:offset+4])[0]&0x7fffffff)%1000000).zfill(6)


class Auth:
    def __init__(self,store,secure_cookies=False):
        self.store=store;self.secure_cookies=secure_cookies;self.lock=threading.RLock();self.origin=None;self.rp_id=None
        key=store.directory/'auth.key'
        if not key.exists():
            with store.connect() as db:
                existing=db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()
                if existing and db.execute('SELECT 1 FROM users WHERE totp_enabled=1').fetchone():raise RuntimeError('2FA 加密密钥丢失，请恢复 data/auth.key 备份')
            try:
                fd=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as stream:stream.write(Fernet.generate_key())
            except FileExistsError:pass
        self.cipher=Fernet(key.read_bytes())
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE COLLATE NOCASE NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL,server_access INTEGER NOT NULL,is_owner INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,totp_secret TEXT,totp_enabled INTEGER NOT NULL DEFAULT 0,totp_last_step INTEGER NOT NULL DEFAULT -1);
                CREATE UNIQUE INDEX IF NOT EXISTS users_single_owner ON users(is_owner) WHERE is_owner=1;
                CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,audience TEXT NOT NULL,expires INTEGER NOT NULL,full_mfa_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS auth_challenges(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,audience TEXT NOT NULL,kind TEXT NOT NULL,expires INTEGER NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,secret TEXT,challenge TEXT,client_key TEXT);
                CREATE TABLE IF NOT EXISTS recovery_codes(user_id INTEGER NOT NULL,code_hash TEXT NOT NULL,PRIMARY KEY(user_id,code_hash));
                CREATE TABLE IF NOT EXISTS login_attempts(client TEXT PRIMARY KEY,failures INTEGER NOT NULL,until INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS passkeys(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,public_key BLOB NOT NULL,sign_count INTEGER NOT NULL,trusted_until INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS photo_access(user_id INTEGER NOT NULL,sha256 TEXT NOT NULL,PRIMARY KEY(user_id,sha256));
            ''')
            if not db.execute('SELECT 1 FROM users').fetchone() and db.execute("SELECT 1 FROM sqlite_master WHERE name='accounts'").fetchone():
                old=db.execute('SELECT * FROM accounts WHERE id=1').fetchone()
                if old:db.execute('INSERT INTO users(id,username,salt,password_hash,server_access,is_owner) VALUES(1,?,?,?,1,1)',(old['username'],old['salt'],old['password_hash']))
        os.chmod(store.directory/'photosync.sqlite3',0o600)

    def configure_origin(self,origin):
        parsed=urlsplit(origin)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.path not in ('','/') or parsed.query or parsed.fragment:raise ValueError('WebAuthn origin 无效')
        if parsed.scheme!='https' and parsed.hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('远程设备认证必须使用 HTTPS')
        self.origin=origin.rstrip('/');self.rp_id=parsed.hostname

    def account(self,username=None):
        with self.store.connect() as db:
            return db.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE',(username,)).fetchone() if username is not None else db.execute('SELECT * FROM users WHERE is_owner=1').fetchone()

    def complete(self):
        with self.store.connect() as db:return db.execute("SELECT 1 FROM app_settings WHERE key='setup_complete'").fetchone() is not None

    def cookie(self,h,audience):
        cookie=SimpleCookie()
        try:cookie.load(h.headers.get('Cookie',''));return cookie['photosync_'+audience+'_session'].value
        except (KeyError,ValueError):return ''

    def current(self,h,audience=None):
        audience=audience or ('client' if urlsplit(h.path).path.startswith(('/client','/api/v1/client','/api/v1/uploads')) else 'admin')
        token=self.cookie(h,audience)
        with self.store.connect() as db:
            row=db.execute('SELECT u.*,s.audience,s.full_mfa_at FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.audience=? AND s.expires>? AND u.active=1 AND u.totp_enabled=1',(hashlib.sha256(token.encode()).hexdigest(),audience,int(time.time()))).fetchone()
        if row and audience=='admin' and not row['server_access']:return None
        return row

    def authenticated(self,h):return self.current(h) is not None

    def session(self,user,audience,full_mfa_at,deadline=None):
        token=secrets.token_urlsafe(32)
        expiry=min(int(time.time())+43200,deadline) if deadline else int(time.time())+43200
        with self.store.connect() as db:
            db.execute('DELETE FROM auth_sessions WHERE expires<?',(int(time.time()),))
            db.execute('INSERT INTO auth_sessions VALUES(?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],audience,expiry,full_mfa_at))
        return f'photosync_{audience}_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max(0,expiry-int(time.time()))}'+('; Secure' if self.secure_cookies else '')

    def clear(self,h,audience=None):
        audience=audience or getattr(h,'auth_audience','admin')
        with self.store.connect() as db:db.execute('DELETE FROM auth_sessions WHERE token_hash=?',(hashlib.sha256(self.cookie(h,audience).encode()).hexdigest(),))
        return f'photosync_{audience}_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'+('; Secure' if self.secure_cookies else '')

    def body(self,h):
        length=int(h.headers.get('Content-Length','0'))
        if not 0<length<=65536:raise ValueError('请求过大或为空')
        data=json.loads(h.rfile.read(length))
        if not isinstance(data,dict):raise ValueError('请求格式无效')
        return data

    def password_hash(self,password,salt):return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()

    def credentials(self,data):
        username,password=data.get('username'),data.get('password')
        if not isinstance(username,str) or not username.strip() or len(username)>100 or any(ord(c)<32 for c in username) or not isinstance(password,str) or not 1<=len(password)<=1024:raise ValueError('用户名或密码无效')
        return username.strip(),password

    def client_key(self,h,username):return hashlib.sha256((h.client_address[0]+'|'+username.casefold()).encode()).hexdigest()

    def blocked(self,key):
        with self.store.connect() as db:row=db.execute('SELECT * FROM login_attempts WHERE client=?',(key,)).fetchone()
        return row and row['failures']>=5 and row['until']>time.time()

    def failure(self,key):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM login_attempts WHERE client=?',(key,)).fetchone()
            failures=row['failures']+1 if row and row['until']>time.time() else 1
            db.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)',(key,failures,int(time.time())+300))

    def challenge(self,user,audience,kind,key='',secret=None,challenge=None):
        token=secrets.token_urlsafe(32)
        with self.store.connect() as db:
            db.execute('DELETE FROM auth_challenges WHERE expires<? OR (user_id=? AND audience=? AND kind=?)',(int(time.time()),user['id'],audience,kind))
            db.execute('INSERT INTO auth_challenges VALUES(?,?,?,?,?,0,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],audience,kind,int(time.time())+300,secret,challenge,key))
        return token

    def pending(self,token):
        with self.store.connect() as db:row=db.execute('SELECT * FROM auth_challenges WHERE token_hash=? AND expires>? AND attempts<5',(hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
        if not row:raise ValueError('验证已过期，请重新登录')
        with self.store.connect() as db:user=db.execute('SELECT * FROM users WHERE id=? AND active=1',(row['user_id'],)).fetchone()
        if not user or (row['audience']=='admin' and not user['server_access']):raise ValueError('账户不可用')
        return row,user

    def mfa_start(self,user,audience,key):
        enroll=not user['totp_enabled'];secret=base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=') if enroll else None
        cipher=self.cipher.encrypt(secret.encode()).decode() if secret else None
        token=self.challenge(user,audience,'enroll' if enroll else 'login',key,cipher)
        result={'mfa_required':True,'enroll':enroll,'ticket':token,'audience':audience}
        if enroll:
            uri=f'otpauth://totp/PhotoSync:{quote(user["username"],safe="")}?secret={secret}&issuer=PhotoSync&algorithm=SHA1&digits=6&period=30'
            image=qrcode.make(uri,image_factory=qrcode.image.svg.SvgPathImage);output=io.BytesIO();image.save(output)
            result.update(secret=secret,otpauth_uri=uri,qr_svg=base64.b64encode(output.getvalue()).decode())
        elif audience=='client' and self.origin:
            with self.store.connect() as db:keys=db.execute('SELECT id FROM passkeys WHERE user_id=? AND trusted_until>?',(user['id'],int(time.time()))).fetchall()
            if keys:
                challenge=secrets.token_bytes(32)
                with self.store.connect() as db:db.execute('UPDATE auth_challenges SET challenge=? WHERE token_hash=?',(bytes_to_base64url(challenge),hashlib.sha256(token.encode()).hexdigest()))
                options=generate_authentication_options(rp_id=self.rp_id,challenge=challenge,allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(k['id'])) for k in keys],user_verification=UserVerificationRequirement.REQUIRED)
                result['passkey_options']=json.loads(options_to_json(options))
        return result

    def consume_factor(self,pending,user,code):
        secret=self.cipher.decrypt((pending['secret'] if pending['kind']=='enroll' else user['totp_secret']).encode()).decode()
        current=int(time.time()//30)
        step=next((n for n in (current,current-1,current+1) if n>user['totp_last_step'] and hmac.compare_digest(totp(secret,n*30),code)),None)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if step is not None:
                updated=db.execute('UPDATE users SET totp_last_step=? WHERE id=? AND totp_last_step<?',(step,user['id'],step)).rowcount
                if not updated:return False
            elif pending['kind']=='login':
                digest=hashlib.sha256(code.replace('-','').upper().encode()).hexdigest()
                if db.execute('DELETE FROM recovery_codes WHERE user_id=? AND code_hash=?',(user['id'],digest)).rowcount!=1:return False
            else:return False
            if db.execute('DELETE FROM auth_challenges WHERE token_hash=?',(pending['token_hash'],)).rowcount!=1:raise ValueError('验证挑战已使用')
        return True

    def can_media(self,user,digest,audience='client'):
        if user['is_owner'] or audience=='admin':return True
        with self.store.connect() as db:return db.execute('SELECT 1 FROM photo_access WHERE user_id=? AND sha256=?',(user['id'],digest)).fetchone() is not None

    def auth_route(self,h,path):
        query=parse_qs(urlsplit(h.path).query);audience=query.get('audience',['admin'])[0]
        if h.command=='GET' and path=='/api/v1/auth/status':
            if audience not in ('admin','client'):raise ValueError('登录入口无效')
            user=self.current(h,audience)
            h.send(200,{'admin_exists':bool(self.account()),'authenticated':bool(user),'setup_complete':self.complete(),'username':user['username'] if user else None,'server_access':bool(user and user['server_access']),'audience':audience,'mfa_enabled':bool(user and user['totp_enabled'])});return
        if h.command!='POST':h.send(405,{'error':'方法不支持'});return
        if h.headers.get('Sec-Fetch-Site')=='cross-site':h.send(403,{'error':'不允许跨站请求'});return
        data=self.body(h);audience=data.get('audience','admin')
        if audience not in ('admin','client'):raise ValueError('登录入口无效')
        if path=='/api/v1/auth/logout':h.send(200,{'ok':True},Set_Cookie=self.clear(h,audience));return
        if path=='/api/v1/auth/bootstrap':
            if self.account():h.send(409,{'error':'管理员已创建，请登录'});return
            username,password=self.credentials(data)
            if len(password)<12:raise ValueError('密码至少 12 个字符')
            salt=secrets.token_hex(16)
            with self.store.connect() as db:
                if db.execute('SELECT 1 FROM users WHERE is_owner=1').fetchone():raise ValueError('管理员已创建')
                db.execute('INSERT INTO users(username,salt,password_hash,server_access,is_owner) VALUES(?,?,?,1,1)',(username,salt,self.password_hash(password,salt)))
                db.execute("DELETE FROM app_settings WHERE key='setup_complete'")
            self.store.log('auth','INFO','admin_created','','管理员已创建，等待绑定 2FA',{})
            h.send(201,self.mfa_start(self.account(),'admin',self.client_key(h,username)));return
        if path=='/api/v1/auth/login':
            username,password=self.credentials(data);key=self.client_key(h,username)
            if self.blocked(key):h.send(429,{'error':'登录尝试过多，请 5 分钟后重试'});return
            user=self.account(username);salt=user['salt'] if user else '00'*16
            calculated=self.password_hash(password,salt)
            if not user or not hmac.compare_digest(calculated,user['password_hash']) or not user['active']:
                self.failure(key);self.store.log('auth','WARN','login_failed','','登录失败',{});h.send(401,{'error':'用户名或密码错误'});return
            if audience=='client' and user['is_owner']:
                h.send(403,{'error':'初始管理账户仅用于服务端，请在用户管理中创建客户端用户'});return
            if audience=='admin' and not user['server_access']:h.send(403,{'error':'此账户没有服务端权限'});return
            h.send(200,self.mfa_start(user,audience,key));return
        if path in ('/api/v1/auth/mfa/verify','/api/v1/auth/passkey/login'):
            token=data.get('ticket','');pending,user=self.pending(token)
            if self.blocked(pending['client_key']):h.send(429,{'error':'认证尝试过多，请稍后重试'});return
            if pending['kind'] not in ('enroll','login'):raise ValueError('验证流程无效')
            valid=False
            if path.endswith('passkey/login'):
                if pending['audience']!='client' or pending['kind']!='login' or not pending['challenge'] or not self.origin:raise ValueError('设备认证不可用')
                credential=data.get('credential',{})
                with self.store.connect() as db:key=db.execute('SELECT * FROM passkeys WHERE id=? AND user_id=? AND trusted_until>?',(credential.get('id'),user['id'],int(time.time()))).fetchone()
                if key:
                    try:
                        verified=verify_authentication_response(credential=credential,expected_challenge=base64url_to_bytes(pending['challenge']),expected_rp_id=self.rp_id,expected_origin=self.origin,credential_public_key=key['public_key'],credential_current_sign_count=key['sign_count'],require_user_verification=True)
                        with self.store.connect() as db:
                            if db.execute('DELETE FROM auth_challenges WHERE token_hash=?',(pending['token_hash'],)).rowcount!=1:raise ValueError('验证挑战已使用')
                            if db.execute('UPDATE passkeys SET sign_count=? WHERE id=? AND sign_count=?',(verified.new_sign_count,key['id'],key['sign_count'])).rowcount!=1:raise ValueError('凭证状态已变化')
                        valid=True
                    except Exception:valid=False
            else:
                code=data.get('code','')
                if not isinstance(code,str) or len(code)>64:raise ValueError('验证码无效')
                valid=self.consume_factor(pending,user,code.strip())
            if not valid:
                self.failure(pending['client_key'])
                with self.store.connect() as db:db.execute('UPDATE auth_challenges SET attempts=attempts+1 WHERE token_hash=?',(pending['token_hash'],))
                self.store.log('auth','WARN','mfa_failed',str(user['id']),'双因素认证失败',{})
                h.send(401,{'error':'验证码或设备认证失败；验证码已使用时请等待下一组'});return
            recovery=[]
            if pending['kind']=='enroll':
                recovery=[secrets.token_hex(10).upper() for _ in range(10)]
                with self.store.connect() as db:
                    db.execute('UPDATE users SET totp_secret=?,totp_enabled=1 WHERE id=?',(pending['secret'],user['id']))
                    db.executemany('INSERT INTO recovery_codes VALUES(?,?)',[(user['id'],hashlib.sha256(code.encode()).hexdigest()) for code in recovery])
            full=int(time.time()) if not path.endswith('passkey/login') else 0
            with self.store.connect() as db:
                db.execute('DELETE FROM login_attempts WHERE client=?',(pending['client_key'],))
                if full:db.execute('UPDATE passkeys SET trusted_until=? WHERE user_id=?',(full+7*86400,user['id']))
            self.store.log('auth','INFO','login_succeeded',str(user['id']),'双因素登录成功',{'audience':pending['audience'],'method':'device' if not full else 'totp_or_recovery'})
            h.send(200,{'ok':True,'setup_complete':self.complete(),'audience':pending['audience'],'recovery_codes':recovery},Set_Cookie=self.session(user,pending['audience'],full,key['trusted_until'] if not full else None));return
        if path in ('/api/v1/auth/passkey/register/options','/api/v1/auth/passkey/register/verify'):
            user=self.current(h,'client')
            if not user or not user['full_mfa_at'] or time.time()-user['full_mfa_at']>300:raise ValueError('请先使用密码和 2FA 登录客户端，再登记设备')
            if not self.origin:raise ValueError('尚未配置可信 WebAuthn origin')
            if path.endswith('options'):
                challenge=secrets.token_bytes(32)
                token=self.challenge(user,'client','register',challenge=bytes_to_base64url(challenge))
                opts=generate_registration_options(rp_id=self.rp_id,rp_name='PhotoSync',user_id=str(user['id']).encode(),user_name=user['username'],challenge=challenge,authenticator_selection=AuthenticatorSelectionCriteria(authenticator_attachment=AuthenticatorAttachment.PLATFORM,user_verification=UserVerificationRequirement.REQUIRED))
                h.send(200,{'ticket':token,'options':json.loads(options_to_json(opts))});return
            pending,owner=self.pending(data.get('ticket',''))
            if pending['kind']!='register' or owner['id']!=user['id']:raise ValueError('设备绑定请求无效')
            try:verified=verify_registration_response(credential=data['credential'],expected_challenge=base64url_to_bytes(pending['challenge']),expected_rp_id=self.rp_id,expected_origin=self.origin,require_user_verification=True)
            except Exception:raise ValueError('设备凭证校验失败')
            with self.store.connect() as db:
                if db.execute('DELETE FROM auth_challenges WHERE token_hash=?',(pending['token_hash'],)).rowcount!=1:raise ValueError('验证挑战已使用')
                db.execute('INSERT INTO passkeys VALUES(?,?,?,?,?)',(bytes_to_base64url(verified.credential_id),user['id'],verified.credential_public_key,verified.sign_count,int(time.time())+7*86400))
            h.send(200,{'registered':True,'reconfirm_days':7});return
        h.send(404,{'error':'接口不存在'})

    def users_route(self,h,path):
        if h.command=='GET':
            with self.store.connect() as db:rows=[dict(r) for r in db.execute('SELECT id,username,server_access,is_owner,active,totp_enabled FROM users ORDER BY id')]
            h.send(200,{'users':rows});return
        if h.command!='POST':h.send(405,{'error':'方法不支持'});return
        if h.headers.get('Sec-Fetch-Site')=='cross-site':h.send(403,{'error':'不允许跨站请求'});return
        data=self.body(h)
        with self.store.connect() as db:
            if data.get('id'):
                user=db.execute('SELECT * FROM users WHERE id=?',(data['id'],)).fetchone()
                if not user or user['is_owner']:raise ValueError('不能修改初始管理账户的权限')
                access=data.get('server_access',False);active=data.get('active',True)
                if type(access) is not bool or type(active) is not bool:raise ValueError('权限字段无效')
                db.execute('UPDATE users SET server_access=?,active=? WHERE id=?',(access,active,user['id']))
                db.execute('DELETE FROM auth_sessions WHERE user_id=?',(user['id'],))
            else:
                username,password=self.credentials(data)
                if len(password)<12:raise ValueError('密码至少 12 个字符')
                access=data.get('server_access',False)
                if type(access) is not bool:raise ValueError('权限字段无效')
                salt=secrets.token_hex(16)
                db.execute('INSERT INTO users(username,salt,password_hash,server_access) VALUES(?,?,?,?)',(username,salt,self.password_hash(password,salt),access))
        self.store.log('auth','INFO','user_updated','','管理员更新客户端用户',{})
        h.send(200,{'saved':True})

    def gate(self,h):
        path=urlsplit(h.path).path
        if path.startswith('/api/v1/auth/'):
            try:
                with self.lock:self.auth_route(h,path)
            except (ValueError,TypeError,KeyError):h.send(400,{'error':'认证请求无效或已过期，请重新验证'})
            except Exception:h.send(409,{'error':'认证操作失败，请重试'})
            return True
        public=('/login','/login.js','/setup.js','/setup.css','/app.js','/style.css','/client/login')
        if path in public or path.startswith(('/admin/assets/','/client/assets/','/shared/assets/')):return False
        if not self.account() and path in ('/setup','/setup/welcome'):return False
        client_paths=path.startswith(('/client','/api/v1/client','/api/v1/uploads'))
        if path.startswith(('/api/v1/photos','/api/v1/previews','/api/v1/live-pairs')):
            selected=parse_qs(urlsplit(h.path).query).get('app',[None])[0]
            audience=selected if selected in ('admin','client') else ('client' if self.cookie(h,'client') else 'admin')
        else:audience='client' if client_paths else 'admin'
        user=self.current(h,audience);h.auth_audience=audience;h.auth_user=user
        if not user:
            if path.startswith('/api/'):h.send(401,{'error':'请在对应入口登录并完成双因素认证'});return True
            h.send(302,b'',Location='/client/login' if path.startswith('/client') else ('/login' if self.account() else '/setup/welcome'));return True
        if path.startswith('/api/v1/admin/users'):
            try:
                with self.lock:self.users_route(h,path)
            except Exception:h.send(400,{'error':'用户配置无效或用户名已存在'})
            return True
        if not self.complete() and (path in ('/','/admin','/client','/api/v1/status','/api/v1/client/status') or path.startswith(('/api/v1/photos','/api/v1/uploads','/api/v1/previews'))):
            if path in ('/','/admin','/client'):h.send(302,b'',Location='/client/login' if path=='/client' else '/setup/library')
            else:h.send(403,{'error':'请先完成初始化'})
            return True
        if path.startswith(('/api/v1/photos/','/api/v1/previews/')):
            digest=path.rsplit('/',1)[-1]
            if not self.can_media(user,digest,audience):h.send(404,{'error':'媒体不存在'});return True
        return False
