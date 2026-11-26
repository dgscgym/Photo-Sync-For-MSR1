(() => {
 const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 async function post(path,data){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}),result=await response.json();if(!response.ok)throw new Error(result.error||'验证失败');return result;}
 window.PhotoSyncMFA={begin(challenge,done,form){
  if(form)form.hidden=true;
  document.getElementById('mfa-panel')?.remove();const panel=el('section');panel.id='mfa-panel';panel.className='panel';
  panel.append(el('h2',challenge.enroll?'绑定 Google Authenticator / 验证器':'双因素认证'));
  if(challenge.enroll){panel.append(el('p','请使用验证器扫描二维码或手动输入密钥。此步骤完成前不能访问照片或管理接口。'));const image=el('img');image.src='data:image/svg+xml;base64,'+challenge.qr_svg;image.alt='验证器绑定二维码';image.style.width='200px';panel.append(image);const secret=el('code',challenge.secret);secret.style.overflowWrap='anywhere';panel.append(secret);}
  const label=el('label','验证码（已绑定用户也可输入一次性恢复码）'),input=el('input');input.autocomplete='one-time-code';input.maxLength=64;label.append(input);const verify=el('button','验证并继续');verify.type='button';verify.className='primary';const message=el('p');message.setAttribute('role','status');panel.append(label,verify,message);
  const finish=result=>{
   if(result.recovery_codes?.length){panel.replaceChildren(el('h2','保存一次性恢复码'),el('p','恢复码仅显示这一次。设备丢失时可配合密码登录，每个码只能使用一次。'));const pre=el('pre',result.recovery_codes.join('\n'));panel.append(pre);const download=el('button','下载恢复码');download.onclick=()=>{const url=URL.createObjectURL(new Blob([result.recovery_codes.join('\n')],{type:'text/plain'}));const a=el('a');a.href=url;a.download='photosync-recovery-codes.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};const next=el('button','我已保存，继续');next.className='primary';next.onclick=()=>{panel.remove();done(result);};panel.append(download,next);}
   else{panel.remove();done(result);}
  };
  verify.onclick=async()=>{verify.disabled=true;try{finish(await post('/api/v1/auth/mfa/verify',{ticket:challenge.ticket,code:input.value.trim()}));}catch(error){message.textContent=error.message;}finally{verify.disabled=false;}};
  if(challenge.passkey_options){const device=el('button','使用设备认证（指纹 / 面容 / PIN）');device.onclick=async()=>{device.disabled=true;try{const credential=await window.PhotoSyncDevice.get(challenge.passkey_options);finish(await post('/api/v1/auth/passkey/login',{ticket:challenge.ticket,credential}));}catch(error){message.textContent=error.message;}finally{device.disabled=false;}};panel.append(device,el('p','设备认证替代验证码最长 7 天，之后必须重新输入验证码。'));}
  const restart=el('button','重新开始登录');restart.onclick=()=>location.reload();panel.append(restart);
  document.querySelector('main').append(panel);input.focus();
 }};
})();
