const $=id=>document.getElementById(id);
let state,proposal=null;const choices=new Map();
async function api(path,options={}){const response=await fetch(path,options),data=await response.json();if(response.status===401){location.replace(location.pathname.startsWith('/client')?'/client/login':'/login');throw new Error('请登录');}if(!response.ok)throw new Error(data.error||'操作失败');return data;}
const post=data=>api('/api/v1/snapraid/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function text(parent,value,tag='p'){const el=document.createElement(tag);el.textContent=value;parent.append(el);return el;}
function invalidate(){proposal=null;$('save').disabled=true;$('proposal').replaceChildren();}
function request(){return {mode:$('mode').value,interval_seconds:Number($('interval').value),disks:Array.from(choices.values()).filter(d=>d.role!=='unused'),expected_revision:state.plan_revision};}
function summary(target,plan){target.replaceChildren();if(!plan)return;text(target,`${plan.parity_level} 级校验 · ${plan.message}`,'h3');for(const d of plan.disks)text(target,`${d.role==='data'?'数据盘':'校验盘'} · ${d.path} · Content ${d.content?'保留':'不保留'}`);}
async function load(){
 state=await api('/api/v1/snapraid/settings');const result=await api('/api/v1/snapraid/settings/disks');
 choices.clear();invalidate();$('disks').replaceChildren();
 renderHealth(state.snapraid);summary($('current'),state.disk_plan);
 const plan=state.disk_plan;if(plan){$('mode').value=plan.mode;$('interval').value=plan.interval_seconds||3600;}
 const locked=state.snapraid_locked||state.snapraid.configured;$('preview').disabled=locked;
 if(locked)text($('disks'),'运行中的阵列配置由服务端管理，本版仅可查看。');
 if(!result.disks.length)text($('disks'),'没有发现已授权的 Linux 挂载磁盘，请先配置容器存储映射。');
 for(const disk of result.disks){
  const row=document.createElement('div');row.className='disk-row';text(row,`${disk.device} · ${disk.path} · ${(disk.total/1024**3).toFixed(1)} GiB`,'strong');
  const old=plan&&plan.disks.find(d=>d.id===disk.id);
  const role=document.createElement('select');for(const [value,label] of [['unused','不使用'],['data','数据盘'],['parity','校验盘']]){const option=document.createElement('option');option.value=value;option.textContent=label;role.append(option);}
  role.value=old?old.role:'unused';role.disabled=locked||!disk.selectable;role.setAttribute('aria-label',disk.path+' 角色');
  const label=document.createElement('label'),content=document.createElement('input');content.type='checkbox';content.checked=old?old.content:true;content.disabled=role.disabled;label.append(content,document.createTextNode('保留 Content 副本'));
  const update=()=>{choices.set(disk.id,{id:disk.id,role:role.value,content:content.checked});invalidate();};role.onchange=content.onchange=update;update();
  row.append(role,label);if(disk.reason)text(row,disk.reason);$('disks').append(row);
 }
}
async function action(work){$('message').textContent='';try{await work();}catch(error){$('message').textContent=error.message;}}
$('mode').onchange=$('interval').onchange=invalidate;
$('reload').onclick=()=>action(load);
$('preview').onclick=()=>action(async()=>{proposal=await post({...request(),preview:true});summary($('proposal'),proposal);$('save').disabled=false;});
$('save').onclick=()=>action(async()=>{if(!proposal)return;if(!confirm('仅保存 SnapRAID 设置，不改变照片目录或重新初始化。继续？'))return;$('save').disabled=true;await post({...request(),confirmed:true});await load();$('message').textContent='SnapRAID 设置已保存。';});
$('check').onclick=()=>action(async()=>{await api('/api/v1/snapraid/check',{method:'POST'});$('message').textContent='检查已请求，结果稍后更新。';await refreshHealth();});
load().catch(error=>{$('message').textContent=error.message;});

function renderHealth(value){$('status').textContent=value.message;$('status').className='health-state '+value.state;$('health-time').textContent='最近检查：'+(value.checked_at?new Date(value.checked_at).toLocaleString():'尚未检查')+' · 周期 '+value.interval_seconds+' 秒'+(value.acknowledged?' · 已知晓（状态未解除）':'');$('ack-snap').disabled=!!value.acknowledged;}
async function refreshHealth(){try{renderHealth(await api('/api/v1/snapraid'));}catch(error){$('status').textContent='无法获取保护状态，请检查连接';$('status').className='health-state unknown';}}
$('ack-snap').onclick=()=>action(async()=>{await api('/api/v1/snapraid/acknowledge',{method:'POST'});await refreshHealth();});
setInterval(refreshHealth,15000);
