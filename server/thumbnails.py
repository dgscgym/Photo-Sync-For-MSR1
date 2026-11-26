"""Small bounded JPEG derivatives for native gallery browsing; originals stay intact."""
from pathlib import Path
import threading
from PIL import Image, ImageOps


class Thumbnails:
    def __init__(self, store):
        self.store = store
        self.directory = store.directory / 'thumbnails'
        self.directory.mkdir(exist_ok=True)
        self.lock = threading.Lock()

    def get(self, digest):
        target = self.directory / (digest + '.jpg')
        with self.lock:
            if target.is_file():
                return target
            source = self.store.resolve(digest)
            if source is None:
                raise ValueError('原片离线或不存在')
            temporary = target.with_suffix('.tmp')
            try:
                with Image.open(source) as image:
                    if image.width * image.height > 60_000_000:
                        raise ValueError('图片像素过大，请使用兼容预览')
                    image.draft('RGB', (512, 512))
                    image = ImageOps.exif_transpose(image)
                    image.thumbnail((512, 512))
                    image.convert('RGB').save(temporary, format='JPEG', quality=80)
                temporary.replace(target)
            except (OSError, SyntaxError, Image.DecompressionBombError) as error:
                raise ValueError('当前解码器不支持此图片缩略图') from error
            finally:
                temporary.unlink(missing_ok=True)
        return target
