(() => {
 let dialog,view,current,options,renderId=0;
 const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 async function api(path,settings={}){const response=await fetch(path,settings),data=await response.json();if(!response.ok)throw new Error(data.error||'读取失败');return data;}
 function create(){
  dialog=el('dialog');dialog.className='directory-picker';dialog.setAttribute('aria-label','选择相册目录并确认内容');
  const heading=el('div');heading.className='picker-heading';heading.append(el('h2','选择相册目录'));const close=el('button','关闭 ×');close.onclick=()=>dialog.close();heading.append(close);
  view=el('div');const footer=el('div');footer.className='picker-footer';const add=el('button','确认添加此目录');add.id='picker-confirm';add.className='primary';add.onclick=confirm;
  footer.append(add);dialog.append(heading,view,footer);document.body.append(dialog);
 }
 async function browse(path='',offset=0){
  const generation=++renderId;view.replaceChildren(el('p','读取目录中…'));document.getElementById('picker-confirm').disabled=true;
  try{
   const data=await api('/api/v1/library/browse?'+new URLSearchParams({path,offset}));if(generation!==renderId)return;current=data;view.replaceChildren();
   const tools=el('div');tools.className='picker-tools';const roots=el('button','全部授权位置');roots.onclick=()=>browse();tools.append(roots);
   if(data.parent){const up=el('button','上一级');up.onclick=()=>browse(data.parent);tools.append(up);}view.append(tools,el('p',data.path||'请选择一个授权的存储位置'));
   if(!data.path){
    if(!data.roots.length)view.append(el('p','尚未授权媒体位置。请在部署时映射媒体盘并设置 --library-base；网页不能自行扩大服务器文件访问范围。'));
    for(const root of data.roots){const button=el('button','📁 '+root);button.className='picker-directory';button.onclick=()=>browse(root);view.append(button);}return;
   }
   view.append(el('p',`目录内共 ${data.total} 项 · 当前展示 ${data.offset+1}–${Math.min(data.offset+data.entries.length,data.total)} 项。请确认内容后添加。`));
   const list=el('div');list.className='picker-list';
   for(const item of data.entries){
    const row=el('div');row.className='picker-item';
    if(item.directory){const button=el('button','📁 '+item.name);button.onclick=()=>browse(item.path);row.append(button);}
    else{row.append(el('span',(item.media_type?'▧ ':'▤ ')+item.name));
     if(item.media_type&&item.media_type.startsWith('image/')&&list.children.length<12){const image=el('img');image.alt=item.name;image.loading='lazy';image.src='/api/v1/library/browse-preview?'+new URLSearchParams({path:item.path});row.append(image);}
     if(item.media_type&&item.media_type.startsWith('video/')){const button=el('button','预览视频');button.onclick=()=>{const video=el('video');video.controls=true;video.preload='metadata';video.src='/api/v1/library/browse-preview?'+new URLSearchParams({path:item.path});row.append(video);button.remove();};row.append(button);}
     if(item.unavailable)row.append(el('small','不可读取'));
    }list.append(row);
   }view.append(list);
   const pages=el('div');if(data.offset){const prev=el('button','上一页');prev.onclick=()=>browse(data.path,Math.max(0,data.offset-100));pages.append(prev);}if(data.next_offset){const next=el('button','下一页');next.onclick=()=>browse(data.path,data.next_offset);pages.append(next);}view.append(pages);
   document.getElementById('picker-confirm').textContent=options.sourceId?'确认重新绑定此目录':'确认添加此目录';document.getElementById('picker-confirm').disabled=false;
  }catch(error){if(generation===renderId)view.replaceChildren(el('p',error.message));}
 }
 async function confirm(){
  if(!current||!current.path)return;const button=document.getElementById('picker-confirm');button.disabled=true;
  try{await api('/api/v1/library/sources',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:current.path,source_id:options.sourceId||null,review_token:current.review_token})});dialog.close();if(options.onSaved)await options.onSaved();}
  catch(error){view.prepend(el('p',error.message));button.disabled=false;}
 }
 window.PhotoSyncDirectoryPicker={open(settings={}){if(!dialog)create();options=settings;current=null;dialog.showModal();browse();}};
})();
