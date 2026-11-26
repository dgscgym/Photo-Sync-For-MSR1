(() => {
 let generation=0;
 const sizes=value=>value>=1024**3?(value/1024**3).toFixed(2)+' GiB':value>=1024**2?(value/1024**2).toFixed(2)+' MiB':(value/1024).toFixed(1)+' KiB';
 window.PhotoSyncDetails={async show(digest,app){
  const id=++generation,root=document.getElementById('media-details');root.replaceChildren();root.textContent='读取媒体详情…';
  try{const response=await fetch('/api/v1/media-details/'+digest+'?app='+app),data=await response.json();if(!response.ok)throw new Error(data.error);if(id!==generation)return;root.replaceChildren();
   const title=document.createElement('h3');title.textContent='媒体详情';const list=document.createElement('dl');
   function item(name,value){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value===null||value===undefined||value===''?'未提供':String(value);list.append(dt,dd);}
   item('存储位置',data.locations.length?data.locations.map(x=>x.label+' · '+x.path).join('\n'):'原片当前离线');
   item('分辨率',data.resolution);item('文件大小',sizes(data.size)+'（'+data.size.toLocaleString()+' 字节）');item('文件格式',data.format+' · '+data.media_type);
   if(data.duration)item('视频时长',data.duration.toFixed(1)+' 秒');if(data.codec)item('视频编码',data.codec);
   const camera=data.camera;item('相机', [camera.make,camera.model].filter(Boolean).join(' '));item('镜头',camera.lens);item('光圈',camera.f_number?'f/'+camera.f_number:null);item('快门',camera.exposure_seconds?(camera.exposure_seconds<1?'1/'+Math.round(1/camera.exposure_seconds):camera.exposure_seconds)+' 秒':null);item('ISO',camera.iso);item('焦距',camera.focal_length_mm?camera.focal_length_mm+' mm':null);item('拍摄时间',camera.taken_at||camera.creation_time);item('SHA256',data.sha256);
   root.append(title,list);if(data.inspection_note){const note=document.createElement('p');note.textContent=data.inspection_note;root.append(note);}
  }catch(error){if(id===generation)root.textContent='媒体详情暂不可用：'+error.message;}
 }};
})();
