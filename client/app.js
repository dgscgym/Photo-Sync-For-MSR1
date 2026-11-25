const $ = id => document.getElementById(id);
let busy = false;
const bytes = n => n < 1048576 ? (n / 1024).toFixed(1) + ' KiB' : (n / 1048576).toFixed(1) + ' MiB';
const names = {library: '照片库', people: '人物相册', backup: '加密备份', activity: '活动记录'};
const titles = {library: '你的照片，井然有序。', people: '熟悉的面孔，珍藏的回忆。', backup: '每一份回忆，都值得保护。', activity: '每一次收藏，都有迹可循。'};
for (const button of document.querySelectorAll('nav button')) button.onclick = () => {
  for (const key of Object.keys(names)) $(key).hidden = key !== button.dataset.view;
  document.querySelector('nav .active').classList.remove('active'); button.classList.add('active');
  $('breadcrumb').textContent = names[button.dataset.view]; $('title').textContent = titles[button.dataset.view];
};
async function refresh() {
  const response = await fetch('/api/v1/status');
  if (!response.ok) throw new Error('无法读取照片库');
  const state = await response.json();
  $('version').textContent = 'v' + state.version + ' · 本地服务';
  $('count').textContent = state.stats.photos; $('size').textContent = bytes(state.stats.bytes); $('duplicates').textContent = state.stats.duplicates;
  $('empty').hidden = state.photos.length > 0; $('grid').replaceChildren();
  for (const photo of state.photos) {
    const card = document.createElement('button'); card.className = 'photo';
    const image = document.createElement('img'); image.src = '/api/v1/photos/' + photo.sha256; image.alt = photo.name; image.loading = 'lazy';
    const detail = document.createElement('div'), name = document.createElement('strong'), meta = document.createElement('small');
    name.textContent = photo.name; meta.textContent = bytes(photo.size) + ' · ' + new Date(photo.created_at).toLocaleDateString();
    detail.append(name, meta); card.append(image, detail); card.onclick = () => {
      $('full').src = image.src; $('caption').textContent = photo.name + ' · SHA256 ' + photo.sha256; $('preview').showModal();
    }; $('grid').append(card);
  }
  $('events').replaceChildren();
  for (const event of state.events) {
    const row = document.createElement('div'); row.className = 'event';
    const label = document.createElement('strong'), time = document.createElement('span');
    label.textContent = (event.kind === 'duplicate' ? '重复文件已拦截' : '原片已保存') + ' · ' + event.sha256.slice(0, 12);
    time.textContent = new Date(event.created_at).toLocaleString(); row.append(label, time); $('events').append(row);
  }
  if (!state.events.length) $('events').textContent = '还没有上传活动。';
}
async function upload(files) {
  if (busy || !files.length) return;
  busy = true; $('pick').disabled = true;
  let added = 0, duplicates = 0, failures = 0;
  try {
    for (const [index, file] of Array.from(files).entries()) {
      $('notice').textContent = `正在上传 ${index + 1}/${files.length}：${file.name}`;
      try {
        if (file.size > 50 * 1024 * 1024) throw new Error('文件超过 50 MiB');
        const response = await fetch('/api/v1/photos', {method: 'POST', headers: {'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name)}, body: file});
        const result = await response.json(); if (!response.ok) throw new Error(result.error);
        result.duplicate ? duplicates++ : added++;
      } catch (error) { failures++; console.warn('上传失败', file.name, error.message); }
    }
    await refresh();
    $('notice').textContent = `处理完成：新增 ${added} 张，重复 ${duplicates} 张，失败 ${failures} 张。` + (failures ? ' 请检查格式、大小及网络后重试。' : '');
  } catch (error) { $('notice').textContent = error.message; }
  finally { busy = false; $('pick').disabled = false; $('files').value = ''; }
}
$('pick').onclick = () => $('files').click(); $('drop').onclick = () => $('files').click();
$('drop').onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); $('files').click(); } };
$('files').onchange = event => upload(event.target.files);
for (const type of ['dragover', 'dragleave', 'drop']) $('drop').addEventListener(type, event => {
  event.preventDefault(); $('drop').classList.toggle('over', type === 'dragover');
  if (type === 'drop') upload(event.dataTransfer.files);
});
$('close').onclick = () => $('preview').close();
refresh().catch(error => { $('notice').textContent = error.message + '，请刷新重试。'; });
