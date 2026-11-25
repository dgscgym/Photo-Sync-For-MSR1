import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest
import sqlite3
from server.app import make_server, Store

PNG=b'\x89PNG\r\n\x1a\n'+b'original'

class LibraryTests(unittest.TestCase):
    def write(self,path,data=PNG):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        os.utime(path,(time.time()-10,time.time()-10))

    def settled(self,library):
        for job in library.jobs:job.join()
        # The startup scan is also protected by the scan lock.
        with library.lock:pass

    def test_readonly_nested_import_move_and_rebind(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)/'media';base.mkdir();data=Path(directory)/'app'
            root=base/'old-disk';root.mkdir()
            first=root/'2020'/'concert'/'no-extension'
            self.write(first);self.write(root/'.old-format'/'copy.jpeg')
            server=make_server(data,port=0,library_bases=[base]);lib=server.library
            try:
                sid=lib.add(str(root),'旧相册');self.settled(lib);lib.scan()
                store=lib.store;snapshot=store.snapshot()
                self.assertEqual(len(snapshot['photos']),1)
                sha=hashlib.sha256(PNG).hexdigest()
                self.assertIsNotNone(store.resolve(sha))
                self.assertFalse(list(store.originals.iterdir()))
                self.assertEqual(first.read_bytes(),PNG)
                with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM file_locations WHERE available=1').fetchone()[0],2)
                target=root/'new'/'renamed.png';target.parent.mkdir();first.rename(target);lib.scan()
                self.assertEqual(len(store.snapshot()['photos']),1)
                moved=base/'new-mount';root.rename(moved)
                lib.scan();self.assertIsNone(store.resolve(sha));self.assertEqual(len(store.snapshot()['photos']),1)
                lib.add(str(moved),source_id=sid);self.settled(lib);lib.scan()
                self.assertIsNotNone(store.resolve(sha))
                self.write(moved/'manually-added.mov',b'\x00\x00\x00\x18ftypqt  '+b'video')
                lib.scan();self.assertEqual(len(store.snapshot()['photos']),2)
                self.assertFalse(list(store.originals.iterdir()))
            finally:server.server_close()
            restarted=make_server(data,port=0,library_bases=[base])
            try:self.assertEqual(len(restarted.library.store.snapshot()['photos']),2)
            finally:restarted.server_close()

    def test_unstable_file_and_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)/'allowed';base.mkdir();(base/'writing.png').write_bytes(PNG)
            outside=Path(directory)/'outside';outside.mkdir();self.write(outside/'secret.png')
            (base/'escape').symlink_to(outside,target_is_directory=True)
            server=make_server(Path(directory)/'app',port=0,library_bases=[base])
            try:
                lib=server.library
                with self.assertRaises(ValueError):lib.add(str(outside))
                lib.add(str(base));self.settled(lib);lib.scan()
                self.assertEqual(len(lib.store.snapshot()['photos']),0)
                os.utime(base/'writing.png',(time.time()-10,time.time()-10));lib.scan()
                self.assertEqual(len(lib.store.snapshot()['photos']),1)
                (base/'writing.png').unlink();lib.scan()
                self.assertFalse(lib.store.snapshot()['photos'][0]['available'])
            finally:server.server_close()

    def test_future_schema_refused_and_upgrade_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with store.connect() as db:db.execute('UPDATE schema_version SET version=99')
            with self.assertRaises(ValueError):Store(directory)
            with sqlite3.connect(Path(directory)/'photosync.sqlite3') as db:self.assertEqual(db.execute('SELECT version FROM schema_version').fetchone()[0],99)
            with sqlite3.connect(Path(directory)/'photosync.sqlite3') as db:db.execute('UPDATE schema_version SET version=3')
            server=make_server(directory,port=0);server.server_close()
            backups=list((Path(directory)/'metadata-backups').glob('*.sqlite3'))
            self.assertEqual(len(backups),1)
            with sqlite3.connect(backups[0]) as db:self.assertEqual(db.execute('SELECT version FROM schema_version').fetchone()[0],3)
