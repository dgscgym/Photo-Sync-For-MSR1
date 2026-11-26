(() => {
 const get=id=>document.getElementById(id);
 async function call(path,options={}){const response=await fetch(path,options),data=await response.json();if(response.status===401){location.replace(location.pathname.startsWith('/client')?'/client/login':'/login');throw new Error('请登录');}if(!response.ok)throw new Error(data.error||'操作失败');return data;}
 const post=(path,data)=>call(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 function text(parent,value,tag='p'){const el=document.createElement(tag);el.textContent=value;parent.append(el);return el;}
 function tab(key){for(const name of ['albums','snapraid','backup','users']){get(name==='albums'?'album-settings':name+'-settings').hidden=name!==key;get(name+'-tab').setAttribute('aria-pressed',String(name===key));}}
 for(const key of ['albums','snapraid','backup','users'])get(key+'-tab').onclick=()=>{tab(key);history.replaceState(null,'','#'+key);};
 tab(['snapraid','backup','users'].includes(location.hash.slice(1))?location.hash.slice(1):'albums');
 async function albums(){
  const state=await call('/api/v1/library');get('album-bases').textContent='已授权范围：'+(state.bases.join('、')||'暂无，请在部署时授权媒体目录');get('album-sources').replaceChildren();
  for(const source of state.sources){const row=document.createElement('div');row.className='source';text(row,`${source.name} · ${source.path}`,'strong');text(row,`${source.state} · ${source.message}`);const bind=document.createElement('button');bind.textContent='修改挂载路径';bind.onclick=()=>window.PhotoSyncDirectoryPicker.open({sourceId:source.id,onSaved:albums});row.append(bind);get('album-sources').append(row);}
 }
 get('album-save').onclick=()=>window.PhotoSyncDirectoryPicker.open({onSaved:async()=>{await albums();get('album-message').textContent='目录已确认添加。';}});
 get('album-scan').onclick=async()=>{try{await post('/api/v1/library/scan',{});get('album-message').textContent='已请求重新扫描。';}catch(error){get('album-message').textContent=error.message;}};
 async function users(){const result=await call('/api/v1/admin/users');get('user-list').replaceChildren();for(const user of result.users){const row=document.createElement('div');row.className='source';text(row,user.username+(user.is_owner?' · 初始管理员':''),'strong');text(row,user.totp_enabled?'2FA 已绑定':'首次登录待绑定 2FA');if(!user.is_owner){const label=document.createElement('label'),access=document.createElement('input');access.type='checkbox';access.checked=!!user.server_access;label.append(access,document.createTextNode('服务端权限'));const enabled=document.createElement('input');enabled.type='checkbox';enabled.checked=!!user.active;const activeLabel=document.createElement('label');activeLabel.append(enabled,document.createTextNode('账户启用'));const save=document.createElement('button');save.textContent='保存权限';save.onclick=async()=>{try{await post('/api/v1/admin/users',{id:user.id,server_access:access.checked,active:enabled.checked});await users();get('user-message').textContent='权限已更新，该用户原会话已撤销。';}catch(error){get('user-message').textContent=error.message;}};row.append(label,activeLabel,save);}get('user-list').append(row);}}
 get('create-user').onclick=async()=>{try{await post('/api/v1/admin/users',{username:get('new-user').value,password:get('new-password').value,server_access:get('new-server-access').checked});get('new-password').value='';get('new-user').value='';get('new-server-access').checked=false;await users();get('user-message').textContent='用户已创建，首次登录需绑定验证器。';}catch(error){get('user-message').textContent=error.message;}};
 users().catch(error=>{get('user-message').textContent=error.message;});
 albums().catch(error=>{get('album-message').textContent=error.message;});
})();
