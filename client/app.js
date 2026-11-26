const $ = id => document.getElementById(id);
let busy = false;
const bytes = n => n >= 1024 ** 3 ? (n / 1024 ** 3).toFixed(2) + ' GiB' : n < 1048576 ? (n / 1024).toFixed(1) + ' KiB' : (n / 1048576).toFixed(1) + ' MiB';
const names = {library:"照片库",people:"人物相册"};
const titles = {library:"你的照片，井然有序。",people:"熟悉的面孔，珍藏的回忆。"};
for (const button of document.querySelectorAll('nav button')) button.onclick = () => {
  for (const key of Object.keys(names)) $(key).hidden = key !== button.dataset.view;
  document.querySelector('nav .active').classList.remove('active'); button.classList.add('active');
  $('breadcrumb').textContent = names[button.dataset.view]; $('title').textContent = titles[button.dataset.view];
};
async function refresh() {
  const response = await fetch('/api/v1/client/status');
  if (!response.ok) throw new Error('无法读取照片库');
  const state = await response.json();
  $('version').textContent = 'v' + state.version + ' · 本地服务';
  $('empty').hidden = state.photos.length > 0; $('grid').replaceChildren();
  for (const photo of state.photos) {
    const card = document.createElement('button'); card.className = 'photo';
    const isVideo = photo.media_type.startsWith('video/');
    const image = document.createElement(isVideo ? 'div' : 'img');
    if (isVideo) { image.className = 'video-cover'; image.textContent = '▷ 视频'; }
    else { image.src = '/api/v1/photos/' + photo.sha256 + '?app=client'; image.alt = photo.name; image.loading = 'lazy'; image.onerror = () => { image.alt = '此图片需生成兼容预览'; }; }
    const detail = document.createElement('div'), name = document.createElement('strong'), meta = document.createElement('small');
    name.textContent = (photo.available === false ? '离线 · ' : '') + (photo.live_video ? '◎ LIVE · ' : '') + photo.name; meta.textContent = bytes(photo.size) + ' · ' + new Date(photo.created_at).toLocaleDateString();
    detail.append(name, meta); card.append(image, detail); card.onclick = () => openMedia(photo); $('grid').append(card);
  }

}
async function api(path, options = {}) {
  const response = await fetch(path, options), data = await response.json();
  if (response.status === 401) { location.replace('/client/login'); throw new Error('登录已过期'); }
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}
const uploadOne=window.PhotoSyncUpload;
async function upload(files) {
  if (busy || !files.length) return;
  busy = true; $('pick').disabled = true;
  let added = 0, duplicates = 0; const failed = [], uploaded = [];
  try {
    for (const [index, file] of Array.from(files).entries()) {
      try {
        if (file.size > 10 * 1024 ** 3) throw new Error('文件超过 10 GiB');
        const result = await uploadOne(file, (offset, hashing) => {
          $('notice').textContent = `${index + 1}/${files.length} ${file.name} · ${Math.round(offset / file.size * 100)}%` + (hashing ? ' · 服务端校验中，大文件请稍候' : '');
        });
        result.duplicate ? duplicates++ : added++; uploaded.push({file, ...result});
      } catch (error) { failed.push(file.name + '：' + error.message); }
    }
    // Explicit confirmation: matching names are candidates, not proof of Apple asset identity.
    const stem = name => name.replace(/\.[^.]+$/, '').toLowerCase();
    for (const item of uploaded.filter(x => /\.(jpe?g|heic|heif|png)$/i.test(x.file.name))) {
      const candidates = uploaded.filter(x => /\.(mov|mp4)$/i.test(x.file.name) && stem(x.file.name) === stem(item.file.name));
      if (candidates.length === 1 && confirm(`将 ${item.file.name} 与 ${candidates[0].file.name} 配对为 Live Photo？请确认它们是同一张实况照片。`)) {
        try { await api('/api/v1/live-pairs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({photo:item.sha256, video:candidates[0].sha256})}); }
        catch (error) { failed.push('Live 配对：' + error.message); }
      }
    }
    await refresh();
    $('notice').textContent = `新增 ${added} 个，重复 ${duplicates} 个，失败 ${failed.length} 项。` + failed.join('；') + (failed.length ? ' 重新选择原文件可继续上传。' : '');
  } catch (error) { $('notice').textContent = error.message; }
  finally { busy = false; $('pick').disabled = false; $('files').value = ''; }
}
let previewGeneration = 0;
function openMedia(photo) {
  previewGeneration++; $('player').pause(); $('player').removeAttribute('src');
  const videoHash = photo.live_video || (photo.media_type.startsWith('video/') ? photo.sha256 : null);
  $('player').hidden = !videoHash; $('full').hidden = !!videoHash;
  $('playback').textContent = photo.live_video ? 'Live Photo · 播放配对动态片段' : '';
  $('original').href = '/api/v1/photos/' + photo.sha256 + '?app=client';
  $('caption').textContent = photo.name;
  window.PhotoSyncDetails.show(photo.sha256,'client');
  const digest = videoHash || photo.sha256;
  $('convert').hidden = false;
  const convert = async () => {
    const generation = previewGeneration;
    $('convert').disabled = true;
    try {
      for (;;) {
        const result = await api('/api/v1/previews/' + digest + '?app=client', {method:'POST'});
        if (generation !== previewGeneration || !$('preview').open) return;
        if (result.state === 'ready') {
          if (videoHash) $('player').src = '/api/v1/previews/' + digest + '?app=client';
          else $('full').src = '/api/v1/previews/' + digest + '?app=client';
          $('playback').textContent = '兼容预览已就绪'; break;
        }
        if (!['queued', 'processing'].includes(result.state)) throw new Error(result.error || '预览生成失败，请检查 FFmpeg 格式支持');
        $('playback').textContent = '正在生成兼容预览，可关闭窗口稍后重试…';
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    } catch (error) { if (generation === previewGeneration) $('playback').textContent = error.message; }
    finally { if (generation === previewGeneration) $('convert').disabled = false; }
  };
  $('convert').disabled = false; $('convert').onclick = convert;
  $('player').onerror = () => { $('playback').textContent = '浏览器不支持原片编码，请生成兼容预览。'; };
  if (videoHash) $('player').src = '/api/v1/photos/' + videoHash + '?app=client';
  else $('full').src = '/api/v1/photos/' + photo.sha256 + '?app=client';
  $('preview').showModal();
}
$('preview').addEventListener('close', () => { previewGeneration++; $('player').pause(); $('player').removeAttribute('src'); $('player').load(); });
$('pick').onclick = () => $('files').click(); $('drop').onclick = () => $('files').click();
$('drop').onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); $('files').click(); } };
$('files').onchange = event => upload(event.target.files);
for (const type of ['dragover', 'dragleave', 'drop']) $('drop').addEventListener(type, event => {
  event.preventDefault(); $('drop').classList.toggle('over', type === 'dragover');
  if (type === 'drop') upload(event.dataTransfer.files);
});
$('close').onclick = () => $('preview').close();
refresh().catch(error => { $('notice').textContent = error.message + '，请刷新重试。'; });
