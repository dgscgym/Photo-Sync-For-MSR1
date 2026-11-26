let pendingPlan=null;
const $ = id => document.getElementById(id);
const step = location.pathname.split('/').pop();
const current = ['welcome','library','snapraid','review'].includes(step) ? step : 'welcome';
$(current).hidden = false;
document.querySelector(`nav a[href="/setup/${current}"]`).classList.add('active');
async function api(path, options={}) {
  const response=await fetch(path,options),data=await response.json();
  if(!response.ok)throw new Error(data.error || '操作失败');return data;
}
async function post(path,data) { return api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); }
function display(parent,text,tag='p') {const el=document.createElement(tag);el.textContent=text;parent.append(el);return el;}
let state;
async function refresh() {
  state=await api('/api/v1/setup');
  $('environment').textContent='服务端连接正常 · 媒体索引与配置持久化已就绪';
  const paths=state.library.bases.join('、') || '尚未授权，请启动服务时设置 --library-base';
  $('authorized').textContent='已授权媒体范围：'+paths;$('library-permissions').textContent='允许登记：'+paths;
  $('sources').replaceChildren();
  for(const source of state.library.sources) display($('sources'),`${source.name} · ${source.path} · ${source.state}`,'div').className='source';
  $('snap-state').textContent=state.disk_plan ? state.disk_plan.message : `${state.snapraid.state} · ${state.snapraid.message}`;if(state.disk_plan)renderPlan(state.disk_plan);
  $('preview-plan').disabled=state.snapraid_locked || !!state.disk_plan || state.snapraid.configured;$('save-plan').disabled=!pendingPlan || !!state.disk_plan || state.snapraid_locked;
  $('skip-snap').disabled=state.snapraid.configured || !!state.disk_plan;
  $('summary').replaceChildren();
  display($('summary'),`已登记 ${state.library.sources.length} 个媒体目录`,'h2');
  for(const source of state.library.sources)display($('summary'),source.path);
  display($('summary'),`SnapRAID：${state.snapraid_mode} · ${state.disk_plan ? state.disk_plan.message : state.snapraid.message}`);
  $('finish').disabled=state.snapraid_mode==='pending';
  if(state.snapraid_mode==='pending')display($('summary'),'请返回 SnapRAID 步骤，接入已有配置或明确选择暂不启用。');
}
async function action(button,work) {button.disabled=true;$('message').textContent='';try{await work();await refresh();}catch(error){$('message').textContent=error.message;}finally{button.disabled=false;if(state){$('preview-plan').disabled=state.snapraid_locked||!!state.disk_plan||state.snapraid.configured;$('save-plan').disabled=!pendingPlan||!!state.disk_plan||state.snapraid_locked;$('skip-snap').disabled=state.snapraid.configured || !!state.disk_plan;$('finish').disabled=state.snapraid_mode==='pending';}}}
$('add-paths').onclick=()=>window.PhotoSyncDirectoryPicker.open({onSaved:async()=>{await refresh();$('message').textContent='目录已确认添加，可继续添加其他目录。';}});
// Disk planner handlers are registered below.
$('skip-snap').onclick=()=>action($('skip-snap'),()=>post('/api/v1/setup/snapraid',{skip:true}));
$('finish').onclick=()=>action($('finish'),async()=>{await post('/api/v1/setup/finish',{});location.replace('/login');});
async function initialize(){
 const auth=await api('/api/v1/auth/status');
 if(!auth.admin_exists){if(current!=='welcome'){location.replace('/setup/welcome');return;}$('admin-form').hidden=false;$('environment').textContent='请先创建管理员，之后配置目录与 SnapRAID。';return;}
 if(!auth.authenticated){location.replace('/login');return;}
 $('admin-form').hidden=true;await refresh();if(current==='snapraid')await loadDisks();
}
$('admin-form').onsubmit=event=>{event.preventDefault();action($('admin-form').querySelector('button'),async()=>{await post('/api/v1/auth/bootstrap',{username:$('admin-name').value,password:$('admin-password').value});$('admin-password').value='';$('admin-form').hidden=true;});};
initialize().catch(error=>{$('message').textContent=error.message;});
setInterval(()=>{if(!state)return;refresh().catch(error=>{$('message').textContent=error.message;});},10000);
const diskChoices=new Map();
const size=n=>(n/1024**3).toFixed(1)+' GiB';
function invalidate(){pendingPlan=null;$('save-plan').disabled=true;$('plan-summary').replaceChildren();}
function renderPlan(plan){
 $('plan-summary').replaceChildren();display($('plan-summary'),`${plan.parity_level} 级校验`,'h3');
 for(const d of plan.disks)display($('plan-summary'),`${d.role==='data'?'数据盘':'校验盘'} · ${d.path} · ${size(d.total)} · Content ${d.content?'保留':'不保留'}`);
 display($('plan-summary'),plan.message);
}
async function loadDisks(){
 invalidate();const result=await api('/api/v1/setup/disks');diskChoices.clear();$('disk-list').replaceChildren();
 if(!result.disks.length){display($('disk-list'),'未发现授权的 Linux 挂载磁盘。请在容器中映射磁盘，并使用 --storage-base 授权。普通文件夹不会被当作独立磁盘。');return;}
 for(const disk of result.disks){
  const row=document.createElement('div');row.className='disk-row';
  display(row,`${disk.device} · ${disk.path}`,'strong');display(row,`${disk.filesystem} · 总容量 ${size(disk.total)} · 可用 ${size(disk.free)}`);
  const role=document.createElement('select');for(const [value,text] of [['unused','不使用'],['data','数据盘'],['parity','校验盘']]){const option=document.createElement('option');option.value=value;option.textContent=text;role.append(option);}
  role.setAttribute('aria-label',disk.path+' 的角色');role.disabled=!disk.selectable;
  const label=document.createElement('label'),content=document.createElement('input');content.type='checkbox';content.checked=true;content.disabled=!disk.selectable;label.append(content,document.createTextNode('保留 Content 副本'));
  role.onchange=content.onchange=()=>{diskChoices.set(disk.id,{id:disk.id,role:role.value,content:content.checked});invalidate();};
  row.append(role,label);if(disk.reason)display(row,disk.reason);$('disk-list').append(row);
 }
}
function planRequest(){return {mode:$('raid-mode').value,disks:Array.from(diskChoices.values()).filter(d=>d.role!=='unused'),interval_seconds:Number($('interval').value)};}
$('raid-mode').onchange=$('interval').onchange=invalidate;
$('refresh-disks').onclick=()=>action($('refresh-disks'),loadDisks);
$('preview-plan').onclick=()=>action($('preview-plan'),async()=>{pendingPlan=await post('/api/v1/setup/snapraid',{...planRequest(),preview:true});renderPlan(pendingPlan);});
$('save-plan').onclick=()=>action($('save-plan'),async()=>{
 if(!pendingPlan)throw new Error('请先检查方案');
 if(!confirm('保存所选磁盘方案？只生成配置，不格式化或开始同步。'))return;
 await post('/api/v1/setup/snapraid',{...planRequest(),confirmed:true});pendingPlan=null;
});
