"""Read-only directory review inside explicitly authorized media roots."""
import hashlib
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .media import media_type, serve_file


def review_token(path):
    stat=path.stat()
    return hashlib.sha256(f'{path}|{stat.st_dev}|{stat.st_ino}|{stat.st_mtime_ns}'.encode()).hexdigest()


def route(library,h):
    path=urlsplit(h.path).path
    if h.command!='GET' or path not in ('/api/v1/library/browse','/api/v1/library/browse-preview'):return False
    try:
        query=parse_qs(urlsplit(h.path).query);value=query.get('path',[''])[0]
        if path.endswith('browse-preview'):
            candidate=Path(value)
            if candidate.is_symlink():raise ValueError()
            root=library.allowed(str(candidate.parent));candidate=root/candidate.name
            if not candidate.is_file():raise ValueError()
            with candidate.open('rb') as stream:kind=media_type(stream.read(64))
            if not kind:raise ValueError()
            serve_file(h,candidate,kind,h.command=='HEAD');return True
        if not value:
            h.send(200,{'roots':[str(base) for base in library.bases],'path':None,'entries':[]});return True
        directory=library.allowed(value)
        offset=int(query.get('offset',['0'])[0])
        if offset<0:raise ValueError()
        token=review_token(directory)
        children=sorted([p for p in directory.iterdir() if not p.is_symlink()],key=lambda p:(not p.is_dir(),p.name.casefold()))
        entries=[]
        for child in children[offset:offset+100]:
            try:
                folder=child.is_dir();kind=None
                if child.is_file():
                    with child.open('rb') as stream:kind=media_type(stream.read(64))
                entries.append({'name':child.name,'path':str(child),'directory':folder,'size':0 if folder else child.stat().st_size,'media_type':kind})
            except OSError:
                entries.append({'name':child.name,'path':str(child),'unavailable':True})
        if review_token(directory)!=token:
            h.send(409,{'error':'目录内容已变化，请刷新后确认'});return True
        parent=str(directory.parent) if any(directory.parent==base or base in directory.parent.parents for base in library.bases) else None
        h.send(200,{'roots':[str(base) for base in library.bases],'path':str(directory),'parent':parent,'entries':entries,'total':len(children),'offset':offset,'next_offset':offset+100 if offset+100<len(children) else None,'review_token':token});return True
    except (ValueError,OSError):h.send(400,{'error':'目录不存在、不可读取或不在授权范围内'});return True
