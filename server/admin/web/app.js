const $=id=>document.getElementById(id);
const names={overview:'服务概览',library:'照片库'};
for(const button of document.querySelectorAll('nav button'))button.onclick=()=>{for(const key of Object.keys(names))$(key).hidden=key!==button.dataset.view;document.querySelector('nav .active').classList.remove('active');button.classList.add('active');$('breadcrumb').textContent=names[button.dataset.view];$('title').textContent=button.dataset.view==='library'?'照片与视频':'服务端状态，一目了然。';$('subtitle').textContent=button.dataset.view==='library'?'浏览媒体原片、查看拍摄信息，或上传新的照片与视频。':'管理媒体目录、多盘保护、备份与运行状态。';$('overview-stats').hidden=button.dataset.view!=='overview';};
const bytes=n=>n>=1024**3?(n/1024**3).toFixed(2)+' GiB':(n/1024**2).toFixed(1)+' MiB';
async function api(path,options={}){const response=await fetch(path,options),data=await response.json();if(response.status===401){location.replace('/login');throw new Error('请先登录');}if(!response.ok)throw new Error(data.error||'请求失败');return data;}
async function refresh(){const state=await api('/api/v1/status');$('version').textContent='v'+state.version+' · 服务端';$('count').textContent=state.stats.photos;$('size').textContent=bytes(state.stats.bytes);renderPhotos(state.photos);await refreshStorage();}
const stateNames = {unknown:'状态未知', warning:'需要关注', critical:'严重异常', healthy:'正常'};
async function refreshStorage() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const state = await api('/api/v1/snapraid', {signal:controller.signal});
    const label = stateNames[state.state] || '状态未知';
    $('snapraid-card').textContent=label;$('snapraid-card').title=state.message;
    $('storage-alert').className = 'storage-alert ' + state.state;
    $('storage-configure').textContent = state.configured ? '查看 SnapRAID 配置 →' : '配置 SnapRAID →';
    $('storage-alert-message').textContent = `⚠ SnapRAID · ${label}：${state.message}` + (state.acknowledged ? '（已知晓，异常仍未解除）' : '');
  } catch (error) {
    $('storage-alert').className = 'storage-alert unknown';
    $('snapraid-card').textContent='状态未知';
    $('storage-alert-message').textContent = '⚠ 无法获取多盘保护状态，请检查服务连接；上次状态不能视为当前状态。';
  } finally { clearTimeout(timer); }
}
setInterval(refreshStorage,15000);

refresh().catch(error=>{$('notice').textContent=error.message;});

function renderPhotos(photos){
  $('empty').hidden = photos.length > 0; $('grid').replaceChildren();
  for (const photo of photos) {
    const card = document.createElement('button'); card.className = 'photo';
    const isVideo = photo.media_type.startsWith('video/');
    const image = document.createElement(isVideo ? 'div' : 'img');
    if (isVideo) { image.className = 'video-cover'; image.textContent = '▷ 视频'; }
    else { image.src = '/api/v1/photos/' + photo.sha256 + '?app=admin'; image.alt = photo.name; image.loading = 'lazy'; image.onerror = () => { image.alt = '此图片需生成兼容预览'; }; }
    const detail = document.createElement('div'), name = document.createElement('strong'), meta = document.createElement('small');
    name.textContent = (photo.available === false ? '离线 · ' : '') + (photo.live_video ? '◎ LIVE · ' : '') + photo.name; meta.textContent = bytes(photo.size) + ' · ' + new Date(photo.created_at).toLocaleDateString();
    detail.append(name, meta); card.append(image, detail); card.onclick = () => openMedia(photo); $('grid').append(card);
  }

}
let previewGeneration = 0;
function openMedia(photo) {
  previewGeneration++; $('player').pause(); $('player').removeAttribute('src');
  const videoHash = photo.live_video || (photo.media_type.startsWith('video/') ? photo.sha256 : null);
  $('player').hidden = !videoHash; $('full').hidden = !!videoHash;
  $('playback').textContent = photo.live_video ? 'Live Photo · 播放配对动态片段' : '';
  $('original').href = '/api/v1/photos/' + photo.sha256 + '?app=admin';
  $('caption').textContent = photo.name;
  window.PhotoSyncDetails.show(photo.sha256,'admin');
  const digest = videoHash || photo.sha256;
  $('convert').hidden = false;
  const convert = async () => {
    const generation = previewGeneration;
    $('convert').disabled = true;
    try {
      for (;;) {
        const result = await api('/api/v1/previews/' + digest + '?app=admin', {method:'POST'});
        if (generation !== previewGeneration || !$('preview').open) return;
        if (result.state === 'ready') {
          if (videoHash) $('player').src = '/api/v1/previews/' + digest + '?app=admin';
          else $('full').src = '/api/v1/previews/' + digest + '?app=admin';
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
  if (videoHash) $('player').src = '/api/v1/photos/' + videoHash + '?app=admin';
  else $('full').src = '/api/v1/photos/' + photo.sha256 + '?app=admin';
  $('preview').showModal();
}
$('preview').addEventListener('close', () => { previewGeneration++; $('player').pause(); $('player').removeAttribute('src'); $('player').load(); });

$('close').onclick=()=>$('preview').close();

let busy=false;const uploadOne=window.PhotoSyncUpload;
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

$('pick').onclick=()=>$('files').click();$('files').onchange=event=>upload(event.target.files);
