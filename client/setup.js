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
  $('snap-permissions').textContent=`配置文件授权范围：${state.config_bases.join('、') || '未配置 --snapraid-config-base'}；磁盘范围：${state.storage_bases.join('、') || '未配置 --storage-base / --library-base'}`;
  $('snap-state').textContent=`${state.snapraid.state} · ${state.snapraid.message}`;
  $('save-snap').disabled=state.snapraid_locked || state.snapraid.running;
  $('skip-snap').disabled=state.snapraid.configured;
  $('summary').replaceChildren();
  display($('summary'),`已登记 ${state.library.sources.length} 个媒体目录`,'h2');
  for(const source of state.library.sources)display($('summary'),source.path);
  display($('summary'),`SnapRAID：${state.snapraid_mode} · ${state.snapraid.message}`);
  $('finish').disabled=state.snapraid_mode==='pending';
  if(state.snapraid_mode==='pending')display($('summary'),'请返回 SnapRAID 步骤，接入已有配置或明确选择暂不启用。');
}
async function action(button,work) {button.disabled=true;$('message').textContent='';try{await work();await refresh();}catch(error){$('message').textContent=error.message;}finally{button.disabled=false;if(state){$('save-snap').disabled=state.snapraid_locked||state.snapraid.running;$('skip-snap').disabled=state.snapraid.configured;$('finish').disabled=state.snapraid_mode==='pending';}}}
$('add-paths').onclick=()=>action($('add-paths'),async()=>{
  const paths=$('paths').value.split('\n').map(s=>s.trim()).filter(Boolean);
  if(!paths.length)throw new Error('请输入至少一个目录');
  await post('/api/v1/library/sources/batch',{sources:paths.map(path=>({path}))});$('paths').value='';$('message').textContent=`已登记 ${paths.length} 个目录，后台扫描中。`;
});
$('save-snap').onclick=()=>action($('save-snap'),async()=>{
  const mounts=$('mounts').value.split('\n').map(s=>s.trim()).filter(Boolean).map(line=>{
    const parts=line.split('|').map(s=>s.trim());if(parts.length!==2)throw new Error('每行磁盘配置请使用 路径 | 身份标记');return {path:parts[0],identity:parts[1]};
  });
  await post('/api/v1/setup/snapraid',{snapraid_config:$('snap-config').value.trim(),mounts,interval_seconds:Number($('interval').value)});
  $('message').textContent='已保存并开始检查。请查看真实检查结果，保存不代表数据已受保护。';
});
$('skip-snap').onclick=()=>action($('skip-snap'),()=>post('/api/v1/setup/snapraid',{skip:true}));
$('check-snap').onclick=()=>action($('check-snap'),()=>post('/api/v1/snapraid/check',{}));
$('finish').onclick=()=>action($('finish'),async()=>{await post('/api/v1/setup/finish',{});location.replace('/login');});
async function initialize(){
 const auth=await api('/api/v1/auth/status');
 if(!auth.admin_exists){if(current!=='welcome'){location.replace('/setup/welcome');return;}$('admin-form').hidden=false;$('environment').textContent='请先创建管理员，之后配置目录与 SnapRAID。';return;}
 if(!auth.authenticated){location.replace('/login');return;}
 $('admin-form').hidden=true;await refresh();
}
$('admin-form').onsubmit=event=>{event.preventDefault();action($('admin-form').querySelector('button'),async()=>{await post('/api/v1/auth/bootstrap',{username:$('admin-name').value,password:$('admin-password').value});$('admin-password').value='';$('admin-form').hidden=true;});};
initialize().catch(error=>{$('message').textContent=error.message;});
setInterval(()=>{if(!state)return;refresh().catch(error=>{$('message').textContent=error.message;});},10000);
