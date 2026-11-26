"""Single-admin authentication with hashed passwords and opaque server sessions."""
import hashlib
import hmac
from http.cookies import SimpleCookie
import json
import secrets
import time
from urllib.parse import urlsplit

class Auth:
    def __init__(self,store,secure_cookies=False):
        self.store=store
        self.secure_cookies=secure_cookies
        with store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY CHECK(id=1),username TEXT UNIQUE NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS login_attempts(client TEXT PRIMARY KEY,failures INTEGER NOT NULL,until INTEGER NOT NULL);''')

    def account(self):
        with self.store.connect() as db:return db.execute('SELECT * FROM accounts WHERE id=1').fetchone()

    def complete(self):
        with self.store.connect() as db:return db.execute("SELECT 1 FROM app_settings WHERE key='setup_complete'").fetchone() is not None

    def token(self,h):
        cookie=SimpleCookie()
        try:cookie.load(h.headers.get('Cookie',''));return cookie['photosync_session'].value
        except (KeyError,ValueError):return ''

    def authenticated(self,h):
        digest=hashlib.sha256(self.token(h).encode()).hexdigest()
        with self.store.connect() as db:
            return db.execute('SELECT 1 FROM sessions WHERE token_hash=? AND expires>?',(digest,int(time.time()))).fetchone() is not None

    def session(self):
        token=secrets.token_urlsafe(32)
        with self.store.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires<?',(int(time.time()),))
            db.execute('INSERT INTO sessions VALUES(?,?)',(hashlib.sha256(token.encode()).hexdigest(),int(time.time())+43200))
        return f'photosync_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200' + ('; Secure' if self.secure_cookies else '')

    def clear(self,h):
        with self.store.connect() as db:db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(self.token(h).encode()).hexdigest(),))
        return 'photosync_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0' + ('; Secure' if self.secure_cookies else '')

    def body(self,h):
        length=int(h.headers.get('Content-Length','0'))
        if not 0<length<=8192:raise ValueError()
        return json.loads(h.rfile.read(length))

    def gate(self,h):
        path=urlsplit(h.path).path
        if path.startswith('/api/v1/auth/'):
            if h.command=='GET' and path=='/api/v1/auth/status':
                h.send(200,{'admin_exists':bool(self.account()),'authenticated':self.authenticated(h),'setup_complete':self.complete()});return True
            if h.command!='POST':h.send(405,{'error':'方法不支持'});return True
            if h.headers.get('Sec-Fetch-Site')=='cross-site':h.send(403,{'error':'不允许跨站请求'});return True
            try:
                if path=='/api/v1/auth/logout':h.send(200,{'ok':True},Set_Cookie=self.clear(h));return True
                data=self.body(h);username=data.get('username');password=data.get('password')
                if not isinstance(username,str) or not isinstance(password,str) or len(username)>100 or len(password)>1024:raise ValueError()
                if path=='/api/v1/auth/bootstrap':
                    if self.account():h.send(409,{'error':'管理员已创建，请登录'});return True
                    if not username.strip() or len(password)<12:h.send(400,{'error':'用户名不能为空，密码至少 12 个字符'});return True
                    salt=secrets.token_hex(16)
                    hashed=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
                    with self.store.connect() as db:
                        db.execute('INSERT INTO accounts VALUES(1,?,?,?)',(username.strip(),salt,hashed))
                        db.execute("DELETE FROM app_settings WHERE key='setup_complete'")
                    self.store.log('auth','info','admin_created','','管理员已创建',{})
                    h.send(201,{'ok':True},Set_Cookie=self.session());return True
                if path=='/api/v1/auth/login':
                    client=h.client_address[0]
                    with self.store.connect() as db:attempt=db.execute('SELECT * FROM login_attempts WHERE client=?',(client,)).fetchone()
                    if attempt and attempt['failures']>=5 and attempt['until']>time.time():h.send(429,{'error':'登录尝试过多，请 5 分钟后重试'});return True
                    account=self.account();salt=account['salt'] if account else '00'*16
                    hashed=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
                    if not account or not hmac.compare_digest(hashed,account['password_hash']) or username!=account['username']:
                        failures=attempt['failures']+1 if attempt and attempt['until']>time.time() else 1
                        with self.store.connect() as db:db.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)',(client,failures,int(time.time())+300))
                        self.store.log('auth','warning','login_failed','','登录失败',{})
                        h.send(401,{'error':'用户名或密码错误'});return True
                    with self.store.connect() as db:db.execute('DELETE FROM login_attempts WHERE client=?',(client,))
                    self.store.log('auth','info','login_succeeded','','登录成功',{})
                    h.send(200,{'ok':True,'setup_complete':self.complete()},Set_Cookie=self.session());return True
                h.send(404,{'error':'接口不存在'});return True
            except (ValueError,TypeError):h.send(400,{'error':'无效的登录请求'});return True
            except Exception:h.send(409,{'error':'账户创建失败或请求冲突，请重试'});return True
        public=('/login','/login.js','/setup.js','/setup.css','/app.js','/style.css')
        if path in public or path.startswith(('/admin/assets/','/client/assets/')) or path=='/client/login':return False
        if not self.account() and path in ('/setup','/setup/welcome'):return False
        if not self.authenticated(h):
            if path.startswith('/api/'):
                h.send(401,{'error':'请先登录'});return True
            h.send(302,b'',Location=('/client/login' if path.startswith('/client') else '/login') if self.account() else '/setup/welcome');return True
        if not self.complete() and (path in ('/','/admin','/client','/api/v1/status','/api/v1/client/status') or path.startswith('/api/v1/photos') or path.startswith('/api/v1/uploads') or path.startswith('/api/v1/previews')):
            if path in ('/','/admin','/client'):h.send(302,b'',Location='/setup/library')
            else:h.send(403,{'error':'请先完成初始化'})
            return True
        return False
