(() => {
 const button=document.getElementById('user-toggle'),menu=document.getElementById('user-menu');
 if(!button||!menu)return;
 const client=location.pathname.startsWith('/client');
 const login=client?'/client/login':'/login';
 document.getElementById('user-settings').href=client?'/client/settings':'/admin/settings';
 const close=()=>{menu.hidden=true;button.setAttribute('aria-expanded','false');};
 button.onclick=()=>{menu.hidden=!menu.hidden;button.setAttribute('aria-expanded',String(!menu.hidden));};
 document.addEventListener('click',event=>{if(!event.target.closest('.user-profile'))close();});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!menu.hidden){close();button.focus();}});
 document.getElementById('logout').onclick=async()=>{
  try{const response=await fetch('/api/v1/auth/logout',{method:'POST'});if(!response.ok)throw new Error('退出失败，请重试');location.replace(login);}
  catch(error){document.getElementById('profile-error').textContent=error.message;}
 };
 fetch('/api/v1/auth/status').then(r=>r.json()).then(state=>{
  if(!state.authenticated){location.replace(login);return;}
  const username=state.username||'用户';document.getElementById('user-name').textContent=username;document.getElementById('profile-name').textContent=username;
  document.getElementById('user-avatar').textContent=Array.from(username)[0].toUpperCase();
 }).catch(()=>{document.getElementById('user-name').textContent='用户信息';});
})();
