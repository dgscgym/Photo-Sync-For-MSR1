const form=document.getElementById('login'),message=document.getElementById('message');
form.onsubmit=async event=>{
 event.preventDefault();const button=form.querySelector('button');button.disabled=true;message.textContent='';
 try{const response=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value,password:document.getElementById('password').value})});const data=await response.json();if(!response.ok)throw new Error(data.error);location.replace(data.setup_complete?(location.pathname.startsWith('/client')?'/client':'/admin'):'/setup/library');}
 catch(error){message.textContent=error.message;}finally{button.disabled=false;}
};
fetch('/api/v1/auth/status').then(r=>r.json()).then(s=>{if(!s.admin_exists)location.replace('/setup/welcome');}).catch(()=>{message.textContent='无法连接服务';});
