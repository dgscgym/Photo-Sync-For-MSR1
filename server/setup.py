"""Independent onboarding endpoints. Never formats disks or starts parity sync."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from .disks import inventory, build_plan

class Setup:
    def __init__(self,store,library,monitor,storage_bases=(),config_bases=(),locked=False):
        self.store,self.library,self.monitor=store,library,monitor
        self.storage=[Path(p).resolve(strict=True) for p in storage_bases]+library.bases
        self.configs=[Path(p).resolve(strict=True) for p in config_bases]
        self.locked=locked

    def inside(self,value,bases,directory):
        path=Path(value)
        if not path.is_absolute():raise ValueError('需要绝对路径')
        path=path.resolve(strict=True)
        if not any(path==base or base in path.parents for base in bases):raise ValueError('路径未授权')
        if directory and not path.is_dir():raise ValueError('目录不存在')
        if not directory and not path.is_file():raise ValueError('配置文件不存在')
        return path

    def snapshot(self):
        with self.store.connect() as db:
            row=db.execute("SELECT value FROM app_settings WHERE key='snapraid_setup_mode'").fetchone()
            plan=db.execute("SELECT value FROM app_settings WHERE key='snapraid_plan'").fetchone()
        return {'library':self.library.snapshot(),'snapraid':self.monitor.snapshot(),
                'snapraid_mode':row['value'] if row else ('connected' if self.monitor.config else 'pending'),
                'storage_bases':[str(p) for p in self.storage], 'config_bases':[str(p) for p in self.configs],
                'snapraid_locked':self.locked,'disk_plan':json.loads(plan['value']) if plan else None}

    def route(self,h):
        path=urlsplit(h.path).path
        if not path.startswith('/api/v1/setup'):return False
        try:
            if h.command=='GET' and path=='/api/v1/setup/disks':h.send(200,{'disks':inventory(self.storage)});return True
            if h.command=='GET' and path=='/api/v1/setup':h.send(200,self.snapshot());return True
            if h.command=='POST' and path=='/api/v1/setup/finish':
                if h.headers.get('Sec-Fetch-Site')=='cross-site':h.send(403,{'error':'不允许跨站请求'});return True
                if self.snapshot()['snapraid_mode']=='pending':raise ValueError('请先完成 SnapRAID 选择')
                with self.store.connect() as db:
                    db.execute("INSERT OR REPLACE INTO app_settings VALUES('setup_complete','true')")
                    db.execute('DELETE FROM sessions')
                cookie=h.server.auth.clear(h)
                h.send(200,{'setup_complete':True},Set_Cookie=cookie);return True
            if h.command=='POST' and path=='/api/v1/setup/snapraid':
                if h.headers.get('Sec-Fetch-Site')=='cross-site':h.send(403,{'error':'不允许跨站请求'});return True
                length=int(h.headers.get('Content-Length','0'))
                if not 0<length<=32768:raise ValueError('请求过大')
                data=json.loads(h.rfile.read(length))
                if data.get('skip') is True:
                    if self.monitor.config or self.snapshot()['disk_plan']:raise ValueError('已有方案不能作为未启用跳过')
                    mode='skipped'
                elif 'mode' in data:
                    if self.locked or self.monitor.config:raise ValueError('已有受管理配置不能直接更换阵列，请先完成迁移设计')
                    plan=build_plan(data,inventory(self.storage))
                    if data.get('preview') is True:
                        h.send(200,plan);return True
                    if data.get('confirmed') is not True:raise ValueError('请先预览并确认磁盘方案')
                    with self.store.connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        previous=db.execute("SELECT value FROM app_settings WHERE key='snapraid_plan'").fetchone()
                        if previous:raise ValueError('已有阵列方案，请勿覆盖；后续提供受控变更流程')
                        directory=self.store.directory/'snapraid'
                        directory.mkdir(exist_ok=True)
                        target=directory/'snapraid.conf'
                        if target.exists():raise ValueError('已有配置文件，拒绝覆盖')
                        temporary=directory/'snapraid.conf.tmp'
                        temporary.write_text(plan['configuration'])
                        temporary.replace(target)
                        db.execute("INSERT INTO app_settings VALUES('snapraid_plan',?)",(json.dumps(plan,ensure_ascii=False),))
                        db.execute("INSERT OR REPLACE INTO app_settings VALUES('snapraid_setup_mode','planned')")
                    self.store.log('snapraid','warning','disk_plan_saved','','磁盘方案已保存，等待首次同步',{'mode':plan['mode'],'disks':len(plan['disks'])})
                    h.send(200,self.snapshot());return True
                else:
                    if self.locked:raise ValueError('配置由服务端启动参数管理')
                    cfg=self.inside(data['snapraid_config'],self.configs,False)
                    entries=data.get('mounts',[])
                    if not isinstance(entries,list) or not 1<=len(entries)<=64:raise ValueError('请配置数据盘及校验盘')
                    mounts=[]
                    for entry in entries:
                        path_=self.inside(entry['path'],self.storage,True)
                        identity=entry['identity']
                        if not isinstance(identity,str) or not identity.strip() or len(identity)>200:raise ValueError('磁盘身份无效')
                        mounts.append({'path':str(path_),'identity':identity.strip()})
                    if len({m['path'] for m in mounts})!=len(mounts):raise ValueError('磁盘目录重复')
                    settings={'executable':'snapraid','snapraid_config':str(cfg),'mounts':mounts,
                              'interval_seconds':max(30,min(86400,int(data.get('interval_seconds',3600)))),
                              'timeout_seconds':30}
                    self.monitor.configure(settings)
                    mode='connected'
                with self.store.connect() as db:db.execute("INSERT OR REPLACE INTO app_settings VALUES('snapraid_setup_mode',?)",(mode,))
                self.store.log('snapraid','info','setup_saved','','SnapRAID 初始化选择已保存',{'mode':mode})
                h.send(200,self.snapshot());return True
            h.send(404,{'error':'接口不存在'});return True
        except (ValueError,OSError,KeyError,TypeError):
            h.send(400,{'error':'配置无效：请检查授权路径、现有配置文件、磁盘身份或检查任务是否仍在运行'});return True
