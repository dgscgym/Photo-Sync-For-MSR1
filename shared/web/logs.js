const $=id=>document.getElementById(id);
async function api(path,options={}){const response=await fetch(path,options),data=await response.json();if(!response.ok)throw new Error(data.error||'读取日志失败');return data;}
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
  const result = await api((location.pathname.startsWith('/client')?'/api/v1/client/logs?':'/api/v1/logs?') + query);
  logRows = append ? logRows.concat(result.items) : result.items;
  logBefore = result.next_before;
  renderLogs($('events'), logRows); $('more-logs').hidden = !logBefore;
}
for (const id of ['log-category','log-level']) $(id).onchange = () => loadLogs().catch(error => { $('log-message').textContent = error.message; });
$('refresh-logs').onclick = () => loadLogs().catch(error => { $('log-message').textContent = error.message; });
$('more-logs').onclick = () => loadLogs(true).catch(error => { $('log-message').textContent = error.message; });
$('export-logs').onclick = () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(logRows, null, 2)], {type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'photosync-logs.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

loadLogs().catch(error=>{$('log-message').textContent=error.message;});
