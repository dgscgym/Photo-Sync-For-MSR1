(() => {
 let dialog,view,preview,options,renderId=0,selectionId=0,existing=[];const selected=new Map(),pending=new Map();
 const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 async function api(path,settings={}){const response=await fetch(path,settings),data=await response.json();if(!response.ok)throw new Error(data.error||'读取失败');return data;}
 function update(){const button=document.getElementById('picker-confirm');button.disabled=!selected.size||pending.size>0;button.textContent=options.sourceId?'确认重新绑定目录':`确认添加选中的目录（${selected.size}）`;}
 function create(){
  dialog=el('dialog');dialog.className='directory-picker';dialog.setAttribute('aria-label','选择相册目录并确认内容');
  const heading=el('div');heading.className='picker-heading';heading.append(el('h2','选择相册目录'));const close=el('button','关闭 ×');close.onclick=()=>dialog.close();heading.append(close);
  view=el('div');preview=el('div');preview.className='picker-selection-preview';const footer=el('div');footer.className='picker-footer';const add=el('button','确认添加选中的目录（0）');add.id='picker-confirm';add.className='primary';add.onclick=confirm;
  footer.append(add);dialog.append(heading,view,preview,footer);document.body.append(dialog);
 }
 async function choose(path,checked){
  const version=++selectionId;
  if(!checked){pending.delete(path);selected.delete(path);preview.replaceChildren();syncChecks();update();return;}
  if(options.sourceId){selected.clear();pending.clear();}
  pending.set(path,version);update();
  preview.replaceChildren(el('p','读取所选目录内容…'));
  try{const data=await api('/api/v1/library/browse?'+new URLSearchParams({path}));
   if(pending.get(path)!==version)return;
   pending.delete(path);
   if(options.sourceId)selected.clear();
   selected.set(path,{path,review_token:data.review_token,existing:existing.some(source=>source.path===path&&source.id!==options.sourceId)});update();
   preview.replaceChildren(el('h3','已选目录内容预览'),el('p',path),el('p',`共 ${data.total} 项，已选 ${selected.size} 个目录。`));
   if(selected.get(path).existing)preview.append(el('p','此目录已经添加，将保留原有记录。'));
   const list=el('ul');for(const item of data.entries.slice(0,8))list.append(el('li',(item.directory?'📁 ':'▧ ')+item.name));preview.append(list);
  }catch(error){if(pending.get(path)!==version)return;pending.delete(path);preview.replaceChildren(el('p',error.message));}
  syncChecks();update();
 }
 function syncChecks(){for(const input of dialog.querySelectorAll('input[data-path]'))input.checked=selected.has(input.dataset.path)||pending.has(input.dataset.path);}
 function directoryRow(path,name){
  const row=el('div');row.className='picker-directory-row';const label=el('label');label.className='picker-check';const input=el('input');input.type='checkbox';input.dataset.path=path;input.checked=selected.has(path)||pending.has(path);input.setAttribute('aria-label','选择目录 '+name);
  input.onchange=()=>choose(path,input.checked);label.append(input,el('span','📁 '+name));const open=el('button','打开查看');open.onclick=()=>browse(path);row.append(label,open);return row;
 }
 async function browse(path='',offset=0){
  const generation=++renderId;view.replaceChildren(el('p','读取目录中…'));update();
  try{const data=await api('/api/v1/library/browse?'+new URLSearchParams({path,offset}));if(generation!==renderId)return;view.replaceChildren();
   const tools=el('div');tools.className='picker-tools';const roots=el('button','全部授权位置');roots.onclick=()=>browse();tools.append(roots);
   if(data.parent){const up=el('button','上一级');up.onclick=()=>browse(data.parent);tools.append(up);}view.append(tools,el('p',data.path||'勾选需要添加的目录，也可打开查看内容。'));
   if(!data.path){if(!data.roots.length)view.append(el('p','暂无授权位置，请在部署时映射媒体目录。'));for(const root of data.roots)view.append(directoryRow(root,root));return;}
   view.append(directoryRow(data.path,'选择当前目录'),el('p',`目录内共 ${data.total} 项`));const list=el('div');list.className='picker-list';
   for(const item of data.entries){
    if(item.directory){list.append(directoryRow(item.path,item.name));continue;}
    const row=el('div');row.className='picker-item';row.append(el('span',(item.media_type?'▧ ':'▤ ')+item.name));
    if(item.media_type?.startsWith('image/')&&list.children.length<12){const image=el('img');image.alt=item.name;image.loading='lazy';image.src='/api/v1/library/browse-preview?'+new URLSearchParams({path:item.path});row.append(image);}
    if(item.media_type?.startsWith('video/')){const button=el('button','预览视频');button.onclick=()=>{const video=el('video');video.controls=true;video.preload='metadata';video.src='/api/v1/library/browse-preview?'+new URLSearchParams({path:item.path});row.append(video);button.remove();};row.append(button);}
    if(item.unavailable)row.append(el('small','不可读取'));list.append(row);
   }view.append(list);
   const pages=el('div');if(data.offset){const prev=el('button','上一页');prev.onclick=()=>browse(data.path,Math.max(0,data.offset-100));pages.append(prev);}if(data.next_offset){const next=el('button','下一页');next.onclick=()=>browse(data.path,data.next_offset);pages.append(next);}view.append(pages);
  }catch(error){if(generation===renderId)view.replaceChildren(el('p',error.message));}
 }
 async function confirm(){
  if(!selected.size||pending.size)return;const button=document.getElementById('picker-confirm');button.disabled=true;
  try{const entries=Array.from(selected.values());
   if(options.sourceId)await api('/api/v1/library/sources',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...entries[0],source_id:options.sourceId})});
   else{const sources=entries.filter(entry=>!entry.existing).map(({path,review_token})=>({path,review_token}));if(sources.length)await api('/api/v1/library/sources/batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sources})});}
   dialog.close();if(options.onSaved)await options.onSaved();
  }catch(error){preview.prepend(el('p',error.message));update();}
 }
 window.PhotoSyncDirectoryPicker={async open(settings={}){if(!dialog)create();options=settings;selected.clear();pending.clear();renderId++;selectionId++;preview.replaceChildren();dialog.showModal();update();try{existing=(await api('/api/v1/library')).sources;}catch(_){existing=[];}browse();}};
})();
