const form=document.getElementById('login'),message=document.getElementById('message');
const audience=location.pathname.startsWith('/client')?'client':'admin';
form.onsubmit=async event=>{
 event.preventDefault();const button=form.querySelector('button');button.disabled=true;message.textContent='';
 try{const response=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value,password:document.getElementById('password').value,audience})});const data=await response.json();if(!response.ok)throw new Error(data.error);document.getElementById('password').value='';window.PhotoSyncMFA.begin(data,result=>location.replace(result.setup_complete?(audience==='client'?'/client':'/admin'):(audience==='client'?'/client/login':'/setup/library')),form);}
 catch(error){message.textContent=error.message;}finally{button.disabled=false;}
};
fetch('/api/v1/auth/status?audience='+audience).then(r=>r.json()).then(s=>{if(audience==='client'&&(!s.admin_exists||!s.setup_complete)){message.textContent='服务端尚未完成初始化，请联系管理员。';form.querySelector('button').disabled=true;}else if(!s.admin_exists)location.replace('/setup/welcome');}).catch(()=>{message.textContent='无法连接服务';});
