const $=id=>document.getElementById(id);
const names={overview:'服务概览',backup:'加密备份',snapraid:'多盘保护',activity:'日志中心',directories:'目录管理'};
for(const button of document.querySelectorAll('nav button'))button.onclick=()=>{for(const key of Object.keys(names))$(key).hidden=key!==button.dataset.view;document.querySelector('nav .active').classList.remove('active');button.classList.add('active');$('breadcrumb').textContent=names[button.dataset.view];};
const bytes=n=>n>=1024**3?(n/1024**3).toFixed(2)+' GiB':(n/1024**2).toFixed(1)+' MiB';
async function api(path,options={}){const response=await fetch(path,options),data=await response.json();if(response.status===401){location.replace('/login');throw new Error('请先登录');}if(!response.ok)throw new Error(data.error||'请求失败');return data;}
async function refresh(){const state=await api('/api/v1/status');$('version').textContent='v'+state.version+' · 服务端';$('count').textContent=state.stats.photos;$('size').textContent=bytes(state.stats.bytes);$('duplicates').textContent=state.stats.duplicates;await loadLogs();await refreshStorage();}
const stateNames = {unknown:'状态未知', warning:'需要关注', critical:'严重异常', healthy:'正常'};
let logRows = [], logBefore = null;
function renderLogs(target, rows) {
  target.replaceChildren();
  if (!rows.length) { target.textContent = '暂无日志记录。'; return; }
  for (const log of rows) {
    const details = document.createElement('details'); details.className = 'log-row ' + log.level;
    const summary = document.createElement('summary');
    summary.textContent = `${new Date(log.created_at).toLocaleString()} · ${({upload:'上传',snapraid:'SnapRAID',library:'目录导入'})[log.category] || log.category} · ${log.level.toUpperCase()} · ${log.message}`;
    const meta = document.createElement('p'); meta.textContent = `#${log.id} · ${log.action} · 任务 ${log.task_id || '—'}`;
    const pre = document.createElement('pre'); pre.textContent = JSON.stringify(log.details, null, 2);
    details.append(summary, meta, pre); target.append(details);
  }
}
async function loadLogs(append = false) {
  const query = new URLSearchParams({category:$('log-category').value, level:$('log-level').value});
  if (append && logBefore) query.set('before', logBefore);
  const result = await api('/api/v1/logs?' + query);
  logRows = append ? logRows.concat(result.items) : result.items;
  logBefore = result.next_before;
  renderLogs($('events'), logRows); $('more-logs').hidden = !logBefore;
}
async function refreshStorage() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const state = await api('/api/v1/snapraid', {signal:controller.signal});
    const label = stateNames[state.state] || '状态未知';
    $('storage-alert').className = 'storage-alert ' + state.state;
    $('storage-configure').textContent = state.configured ? '查看 SnapRAID 配置 →' : '配置 SnapRAID →';
    $('storage-alert-message').textContent = `⚠ SnapRAID · ${label}：${state.message}` + (state.acknowledged ? '（已知晓，异常仍未解除）' : '');
    $('storage-title').textContent = label + (state.running ? ' · 检查中' : '');
    $('storage-message').textContent = state.message;
    $('storage-time').textContent = `最近检查：${state.checked_at ? new Date(state.checked_at).toLocaleString() : '尚未检查'} · 周期 ${state.interval_seconds} 秒`;
    $('check-storage').disabled = state.running;
    $('ack-storage').disabled = !!state.acknowledged;
    const result = await api('/api/v1/logs?category=snapraid', {signal:controller.signal}); renderLogs($('storage-logs'), result.items);
  } catch (error) {
    $('storage-alert').className = 'storage-alert unknown';
    $('storage-alert-message').textContent = '⚠ 无法获取多盘保护状态，请检查服务连接；上次状态不能视为当前状态。';
  } finally { clearTimeout(timer); }
}
$('check-storage').onclick = async () => {
  try { await api('/api/v1/snapraid/check', {method:'POST'}); await refreshStorage(); }
  catch (error) { $('notice').textContent = '检查请求失败：' + error.message; }
};
$('ack-storage').onclick = async () => {
  try { await api('/api/v1/snapraid/acknowledge', {method:'POST'}); await refreshStorage(); }
  catch (error) { $('notice').textContent = error.message; }
};
for (const id of ['log-category','log-level']) $(id).onchange = () => loadLogs().catch(error => { $('notice').textContent = error.message; });
$('refresh-logs').onclick = () => loadLogs().catch(error => { $('notice').textContent = error.message; });
$('more-logs').onclick = () => loadLogs(true).catch(error => { $('notice').textContent = error.message; });
$('export-logs').onclick = () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(logRows, null, 2)], {type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'photosync-logs.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
setInterval(refreshStorage, 15000);

let libraryStamp = '';
async function refreshLibrary(first = false) {
  try {
    const state = await api('/api/v1/library');
    $('library-bases').textContent = state.bases.length ? '服务端已授权目录：' + state.bases.join('、') : '尚无授权目录。请启动服务时添加 --library-base /容器内媒体路径；也可先直接上传。';
    $('source-list').replaceChildren();
    for (const source of state.sources) {
      const card = document.createElement('div'); card.className = 'monitor-card';
      const title = document.createElement('h3'); title.textContent = source.name;
      const path = document.createElement('p'); path.textContent = source.path;
      const status = document.createElement('p'); status.textContent = `${source.state} · ${source.message} · 最近扫描 ${source.last_scan ? new Date(source.last_scan).toLocaleString() : '尚无'}`;
      const bind = document.createElement('button'); bind.textContent = '磁盘路径变了？重新绑定';
      bind.onclick = () => { $('source-id').value = source.id; $('source-path').value = source.path; $('source-name').value = source.name; $('source-path').focus(); };
      card.append(title,path,status,bind); $('source-list').append(card);
    }
    $('library-scan').disabled = state.scanning;
    const stamp = JSON.stringify(state.sources.map(s => [s.id,s.last_scan,s.state]));
    if (libraryStamp && stamp !== libraryStamp) await refresh();
    libraryStamp = stamp;
    if (first && !state.setup_complete) location.replace('/setup/welcome');
  } catch (error) { $('library-message').textContent = '目录状态读取失败：' + error.message; }
}
$('source-add').onclick = async () => {
  $('source-add').disabled = true;
  try {
    const paths=$('source-path').value.split('\n').map(s=>s.trim()).filter(Boolean);
    if(!paths.length)throw new Error('请输入目录');
    const rebind=$('source-id').value;
    if(rebind && paths.length!==1)throw new Error('重新绑定仅能指定一个目录');
    await api(rebind?'/api/v1/library/sources':'/api/v1/library/sources/batch', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(rebind?{path:paths[0],source_id:rebind}:{sources:paths.map(path=>({path}))})});
    $('source-id').value = ''; $('source-path').value = ''; $('source-name').value = '';
    $('library-message').textContent = '目录已登记，正在后台扫描；不会复制、移动或删除原文件。';
    await refreshLibrary(); setTimeout(refreshLibrary, 1500);
  } catch (error) { $('library-message').textContent = error.message; }
  finally { $('source-add').disabled = false; }
};
$('library-scan').onclick = async () => {
  try { await api('/api/v1/library/scan',{method:'POST'}); $('library-message').textContent = '扫描已请求，请稍候。'; setTimeout(refreshLibrary,1500); }
  catch (error) { $('library-message').textContent = error.message; }
};
$('library-export').onclick = async () => {
  try {
    const data = await api('/api/v1/library/manifest');
    const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='photosync-library-v1.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  } catch(error) { $('library-message').textContent=error.message; }
};
refreshLibrary(true); setInterval(() => refreshLibrary(),15000);

$('logout').onclick=async()=>{await api('/api/v1/auth/logout',{method:'POST'});location.replace('/login');};

refresh().catch(error=>{$('notice').textContent=error.message;});
