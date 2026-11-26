"""Bounded image EXIF / ffprobe detail inspection without modifying originals."""
import json
from pathlib import Path
import shutil
import subprocess
from PIL import Image


def display(value):
    if value is None:return None
    if isinstance(value,bytes):return None
    if isinstance(value,(str,int,float)):return value
    try:return float(value)
    except (ValueError,TypeError):return str(value)[:300]


def inspect(store,digest,audience='client'):
    with store.connect() as db:row=db.execute('SELECT * FROM photos WHERE sha256=?',(digest,)).fetchone()
    if row is None:raise ValueError('媒体不存在')
    source=store.resolve(digest)
    result={'name':row['name'],'sha256':digest,'size':row['size'],'media_type':row['media_type'],'format':row['media_type'].split('/')[-1].upper(),
            'resolution':None,'width':None,'height':None,'camera':{},'duration':None,'locations':[],'available':source is not None}
    if (store.originals/digest).is_file():
        result['locations'].append({'label':'上传原片','path':str(store.originals/digest) if audience=='admin' else 'originals/'+digest})
    with store.connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='file_locations'").fetchone():
            for location in db.execute('SELECT l.relative_path,s.name,s.path FROM file_locations l JOIN library_sources s ON s.id=l.source_id WHERE l.sha256=? AND l.available=1',(digest,)):
                result['locations'].append({'label':location['name'],'path':str(Path(location['path'])/location['relative_path']) if audience=='admin' else location['name']+'/'+location['relative_path']})
    if source is None:return result
    if row['media_type'].startswith('image/'):
        try:
            with Image.open(source) as image:
                result.update(width=image.width,height=image.height,format=image.format or result['format'])
                tags=dict(image.getexif())
                try:tags.update(image.getexif().get_ifd(34665))
                except (AttributeError,ValueError,TypeError):pass
                mapping={271:'make',272:'model',42036:'lens',33434:'exposure_seconds',33437:'f_number',34855:'iso',37386:'focal_length_mm',36867:'taken_at'}
                result['camera']={name:display(tags[tag]) for tag,name in mapping.items() if tag in tags and display(tags[tag]) is not None}
        except (OSError,ValueError,TypeError,SyntaxError,KeyError,Image.DecompressionBombError):result['inspection_note']='当前解码器无法读取图片元数据，原片仍保留'
    elif shutil.which('ffprobe'):
        try:
            process=subprocess.run(['ffprobe','-v','error','-show_entries','stream=width,height,codec_name:format=duration,format_name:format_tags=make,model,creation_time','-of','json',str(source)],capture_output=True,text=True,timeout=15,check=True)
            data=json.loads(process.stdout)
            stream=next((s for s in data.get('streams',[]) if s.get('width')), {})
            result.update(width=stream.get('width'),height=stream.get('height'),codec=stream.get('codec_name'),duration=float(data.get('format',{}).get('duration',0)))
            result['camera']={key:value for key,value in data.get('format',{}).get('tags',{}).items()}
        except (subprocess.SubprocessError,ValueError):result['inspection_note']='视频元数据读取失败或超时'
    else:result['inspection_note']='未安装 ffprobe，暂无法读取视频分辨率与时长'
    if result['width'] and result['height']:result['resolution']=f"{result['width']} × {result['height']}"
    return result
