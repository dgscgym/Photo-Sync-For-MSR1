(() => {
 const get=id=>document.getElementById(id);
 async function call(path,options={}){const response=await fetch(path,options),data=await response.json();if(response.status===401){location.replace(location.pathname.startsWith('/client')?'/client/login':'/login');throw new Error('请登录');}if(!response.ok)throw new Error(data.error||'操作失败');return data;}
 const post=(path,data)=>call(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 function text(parent,value,tag='p'){const el=document.createElement(tag);el.textContent=value;parent.append(el);return el;}
 function tab(key){for(const name of ['albums','snapraid','backup']){get(name==='albums'?'album-settings':name+'-settings').hidden=name!==key;get(name+'-tab').setAttribute('aria-pressed',String(name===key));}}
 for(const key of ['albums','snapraid','backup'])get(key+'-tab').onclick=()=>{tab(key);history.replaceState(null,'','#'+key);};
 tab(['snapraid','backup'].includes(location.hash.slice(1))?location.hash.slice(1):'albums');
 async function albums(){
  const state=await call('/api/v1/library');get('album-bases').textContent='已授权范围：'+(state.bases.join('、')||'暂无，请在部署时授权媒体目录');get('album-sources').replaceChildren();
  for(const source of state.sources){const row=document.createElement('div');row.className='source';text(row,`${source.name} · ${source.path}`,'strong');text(row,`${source.state} · ${source.message}`);const bind=document.createElement('button');bind.textContent='修改挂载路径';bind.onclick=()=>window.PhotoSyncDirectoryPicker.open({sourceId:source.id,onSaved:albums});row.append(bind);get('album-sources').append(row);}
 }
 get('album-save').onclick=()=>window.PhotoSyncDirectoryPicker.open({onSaved:async()=>{await albums();get('album-message').textContent='目录已确认添加。';}});
 get('album-scan').onclick=async()=>{try{await post('/api/v1/library/scan',{});get('album-message').textContent='已请求重新扫描。';}catch(error){get('album-message').textContent=error.message;}};
 let files=[];
 get('local-pick').onclick=()=>get('local-files').click();
 get('local-files').onchange=()=>{
  files=Array.from(get('local-files').files).filter(file=>file.type.startsWith('image/')||file.type.startsWith('video/')||/\.(heic|heif|mov|mp4|mkv|jpe?g|png|gif|webp)$/i.test(file.name));
  get('local-upload').disabled=!files.length;get('local-state').textContent=`已选择 ${files.length} 个媒体文件，点击上传后开始。关闭页面后需重新选择文件夹。`;
 };
 get('local-upload').onclick=async()=>{
  get('local-upload').disabled=true;get('local-pick').disabled=true;let added=0,duplicates=0,failed=[];
  try{for(const [i,file] of files.entries()){try{const result=await window.PhotoSyncUpload(file,(offset,hashing)=>{get('local-state').textContent=`${i+1}/${files.length} ${file.webkitRelativePath||file.name} · ${Math.round(offset/file.size*100)}%${hashing?' · 校验中':''}`;});result.duplicate?duplicates++:added++;}catch(error){failed.push(file.name+'：'+error.message);}}get('local-state').textContent=`新增 ${added}，重复 ${duplicates}，失败 ${failed.length}。`+failed.join('；');}
  finally{get('local-pick').disabled=false;get('local-upload').disabled=false;}
 };
 albums().catch(error=>{get('album-message').textContent=error.message;});
})();
