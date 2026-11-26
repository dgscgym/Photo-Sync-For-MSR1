(() => {
 let dialog,view,preview,options,renderId=0,selectionId=0,submitting=false,existing=[];const selected=new Map(),pending=new Map();
 const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 async function api(path,settings={}){const response=await fetch(path,settings),data=await response.json();if(!response.ok)throw new Error(data.error||'读取失败');return data;}
 const within=(path,parent)=>path===parent||path.startsWith(parent.replace(/\/$/,'')+'/');
 function coverage(path){
  if([...selected.keys(),...pending.keys()].some(parent=>parent!==path&&within(path,parent)))return '父目录已包含';
  return '';
 }
 function refreshCheck(input){const reason=coverage(input.dataset.path);input.checked=!!reason||selected.has(input.dataset.path)||pending.has(input.dataset.path);input.disabled=submitting||!!reason;input.title=reason;}
 function update(){const button=document.getElementById('picker-confirm');button.disabled=submitting||!selected.size||pending.size>0;button.textContent=options.sourceId?'确认重新绑定目录':`确认添加选中的目录（${selected.size}）`;}
 function create(){
  dialog=el('dialog');dialog.className='directory-picker';dialog.setAttribute('aria-label','选择相册目录并确认内容');
  const heading=el('div');heading.className='picker-heading';heading.append(el('h2','选择相册目录'));const close=el('button','关闭 ×');close.onclick=()=>dialog.close();heading.append(close);
  view=el('div');preview=el('div');preview.className='picker-message';preview.setAttribute('role','status');const footer=el('div');footer.className='picker-footer';const add=el('button','确认添加选中的目录（0）');add.id='picker-confirm';add.className='primary';add.onclick=confirm;
  footer.append(add);dialog.append(heading,view,preview,footer);document.body.append(dialog);
 }
 async function choose(path,checked){
  if(checked&&coverage(path)){syncChecks();return;}
  const version=++selectionId;
  if(!checked){pending.delete(path);selected.delete(path);preview.replaceChildren();syncChecks();update();return;}
  if(options.sourceId){selected.clear();pending.clear();}
  for(const child of selected.keys())if(within(child,path))selected.delete(child);
  for(const child of pending.keys())if(within(child,path))pending.delete(child);
  pending.set(path,version);syncChecks();update();
  preview.replaceChildren();
  try{const data=await api('/api/v1/library/browse?'+new URLSearchParams({path,directories_only:1}));
   if(pending.get(path)!==version)return;
   pending.delete(path);
   if(options.sourceId)selected.clear();
   selected.set(path,{path,review_token:data.review_token,existing:existing.some(source=>within(path,source.path)&&source.id!==options.sourceId)});update();

  }catch(error){if(pending.get(path)!==version)return;pending.delete(path);preview.replaceChildren(el('p',error.message));}
  syncChecks();update();
 }
 function syncChecks(){for(const input of dialog.querySelectorAll('input[data-path]'))refreshCheck(input);}
 function directoryRow(path,name){
  const row=el('div');row.className='picker-directory-row';const input=el('input');input.type='checkbox';input.dataset.path=path;refreshCheck(input);input.setAttribute('aria-label','选择目录 '+name);
  input.onchange=()=>choose(path,input.checked);const open=el('button','📁 '+name);open.className='picker-directory-name';open.onclick=()=>browse(path);row.append(input,open);return row;
 }
 async function browse(path='',offset=0){
  const generation=++renderId;preview.replaceChildren();view.replaceChildren(el('p','读取目录中…'));update();
  try{const data=await api('/api/v1/library/browse?'+new URLSearchParams({path,offset,directories_only:1}));if(generation!==renderId)return;view.replaceChildren();
   const tools=el('div');tools.className='picker-tools';const roots=el('button','全部授权位置');roots.onclick=()=>browse();tools.append(roots);
   if(data.path){const up=el('button','上一级');up.onclick=()=>browse(data.parent||'');tools.append(up);}view.append(tools,el('p',data.path||'勾选目录以添加，点击目录名称进入下一级。'));
   if(!data.path){if(!data.roots.length)view.append(el('p','暂无授权位置，请在部署时映射媒体目录。'));for(const root of data.roots)view.append(directoryRow(root,root));return;}
   view.append(el('p',`子目录 ${data.total} 个`));const list=el('div');list.className='picker-list';
   for(const item of data.entries){if(item.directory)list.append(directoryRow(item.path,item.name));}
   if(!data.total)list.append(el('p','没有子目录'));view.append(list);
   const pages=el('div');if(data.offset){const prev=el('button','上一页');prev.onclick=()=>browse(data.path,Math.max(0,data.offset-100));pages.append(prev);}if(data.next_offset){const next=el('button','下一页');next.onclick=()=>browse(data.path,data.next_offset);pages.append(next);}view.append(pages);
  }catch(error){if(generation===renderId)view.replaceChildren(el('p',error.message));}
 }
 async function confirm(){
  if(submitting||!selected.size||pending.size)return;submitting=true;preview.replaceChildren();syncChecks();update();
  try{const entries=Array.from(selected.values());
   if(options.sourceId)await api('/api/v1/library/sources',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...entries[0],source_id:options.sourceId})});
   else{const sources=entries.filter(entry=>!entry.existing).map(({path,review_token})=>({path,review_token}));if(sources.length)await api('/api/v1/library/sources/batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sources})});}
   dialog.close();if(options.onSaved)await options.onSaved();
  }catch(error){preview.replaceChildren(el('p',error.message));}
  finally{submitting=false;syncChecks();update();}
 }
 window.PhotoSyncDirectoryPicker={async open(settings={}){if(!dialog)create();options=settings;selected.clear();pending.clear();renderId++;selectionId++;preview.replaceChildren();dialog.showModal();update();try{existing=(await api('/api/v1/library')).sources;}catch(_){existing=[];}browse();}};
})();
