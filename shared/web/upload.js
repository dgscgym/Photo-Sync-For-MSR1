(()=>{
async function api(path,options={}){const response=await fetch(path,options),data=await response.json();if(!response.ok)throw new Error(data.error||'上传请求失败');return data;}
async function uploadOne(file, progress) {
  // Metadata is only a resume hint; server hashes the completed bytes for deduplication.
  const key = 'photosync-upload:' + JSON.stringify([file.name, file.size, file.lastModified]);
  let session;
  const id = localStorage.getItem(key);
  if (id) { try { session = await api('/api/v1/uploads/' + id); } catch (_) { localStorage.removeItem(key); } }
  if (!session) {
    session = await api('/api/v1/uploads', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:file.name, size:file.size})});
    localStorage.setItem(key, session.id);
  }
  while (session.offset < file.size) {
    const end = Math.min(session.offset + 8 * 1024 ** 2, file.size);
    try {
      const data = await api('/api/v1/uploads/' + session.id, {method:'PATCH', headers:{'Upload-Offset':String(session.offset)}, body:file.slice(session.offset, end)});
      session.offset = data.offset; progress(session.offset);
    } catch (error) {
      // Query persisted offset before retrying an ambiguous response.
      const current = await api('/api/v1/uploads/' + session.id);
      if (current.offset <= session.offset) throw error;
      session.offset = current.offset;
    }
  }
  progress(file.size, true);
  const result = await api('/api/v1/uploads/' + session.id + '/complete', {method:'POST'});
  localStorage.removeItem(key); return result;
}
window.PhotoSyncUpload=uploadOne;
})();
