"""Run on the target MS-R1: python3 tools/check_media.py. No hardware acceleration claim."""
import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

report = {'architecture': platform.machine(), 'system': platform.platform(), 'ffmpeg': shutil.which('ffmpeg'),
          'software_h264_test': False, 'hardware_acceleration': 'not_verified', 'heic_decode': 'requires_real_sample'}
if report['ffmpeg']:
    try:
        version = subprocess.run(['ffmpeg','-version'],capture_output=True,text=True,check=True).stdout
        report['version'] = version.splitlines()[0]
        report['available_hwaccels'] = subprocess.run(['ffmpeg','-hide_banner','-hwaccels'],capture_output=True,text=True).stdout
        with tempfile.TemporaryDirectory(prefix='photosync-media-check-') as directory:
            output = Path(directory)/'test.mp4'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=blue:s=128x72:d=1',
                            '-c:v','libx264','-pix_fmt','yuv420p','-threads','2','-movflags','+faststart',str(output)],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120)
            subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(output),'-f','null','-'],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120)
            report['software_h264_test'] = output.stat().st_size > 0
    except (subprocess.SubprocessError, OSError):
        report['error'] = '软件编码或解码自检失败，请检查 FFmpeg 的 libx264 支持'
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['software_h264_test'] else 1)
