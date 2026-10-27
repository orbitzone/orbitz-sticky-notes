"""Bounded startup serialization and failed-constructor cleanup, temporary DBs."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sticky-notes'))
os.environ.setdefault('GSETTINGS_BACKEND','memory')
SPEC=importlib.util.spec_from_file_location('startup_storage',ROOT/'sticky-notes/storage.py')
storage=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(storage)


class StartupTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)

    def test_second_process_cannot_open_sqlite_until_first_startup_finishes(self):
        child='''
import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'sticky-notes'))
import storage
root=Path(sys.argv[2]); role=sys.argv[3]
if role=='first':
    original=storage._enable_wal
    def pause(db):
        (root/'first-connected').write_text('ready')
        deadline=time.monotonic()+10
        while not (root/'release').exists():
            if time.monotonic()>deadline:raise TimeoutError('startup release timed out')
            time.sleep(.01)
        original(db)
    storage._enable_wal=pause
else:
    flock=storage.fcntl.flock
    def tracked_lock(*args,**kwargs):
        try:return flock(*args,**kwargs)
        except BlockingIOError:
            (root/'second-contended').write_text('busy')
            raise
    storage.fcntl.flock=tracked_lock
    connect=storage.sqlite3.connect
    def tracked(*args,**kwargs):
        (root/'second-connected').write_text('opened')
        return connect(*args,**kwargs)
    storage.sqlite3.connect=tracked
    (root/'second-attempting').write_text('ready')
store=storage.Store(root,root/'legacy.json')
assert len(store.all())==1 and store.all()[0]['text']=='legacy text'
assert store.db.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
store.close()
'''
        (self.root/'legacy.json').write_text('{"notes":"legacy text"}')
        env={**os.environ,'GSETTINGS_BACKEND':'memory'};processes=[]
        def wait_file(name):
            deadline=time.monotonic()+10
            while not (self.root/name).exists():
                for process in processes:
                    if process.poll() is not None:self.fail(str(process.communicate(timeout=1)))
                if time.monotonic()>deadline:self.fail('startup barrier timed out: '+name)
                time.sleep(.01)
        try:
            for role,marker in (('first','first-connected'),('second','second-attempting')):
                processes.append(subprocess.Popen([sys.executable,'-c',child,str(ROOT),str(self.root),role],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
                wait_file(marker)
            wait_file('second-contended')
            self.assertFalse((self.root/'second-connected').exists(),'second initializer opened SQLite before first completed')
            (self.root/'release').touch()
            for process in processes:
                stdout,stderr=process.communicate(timeout=15)
                self.assertEqual(process.returncode,0,stdout+'\n'+stderr)
            self.assertTrue((self.root/'second-connected').exists())
            with sqlite3.connect(self.root/'notes.sqlite3') as db:
                self.assertEqual(db.execute('SELECT text,revision,title,secret FROM notes').fetchall(),[('legacy text',0,'',0)])
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        finally:
            (self.root/'release').touch()
            for process in processes:
                if process.poll() is None:process.kill()
                process.communicate()

    def test_busy_startup_lock_times_out_before_opening_sqlite_then_recovers(self):
        lock=storage._startup_lock
        with lock(self.root),patch.object(storage,'_startup_lock',side_effect=lambda directory:lock(directory,timeout=.08)),patch.object(storage.sqlite3,'connect') as connect:
            started=time.monotonic()
            with self.assertRaises(sqlite3.OperationalError):storage.Store(self.root)
            self.assertLess(time.monotonic()-started,1)
            connect.assert_not_called()
            self.assertFalse((self.root/'notes.sqlite3').exists())
        store=storage.Store(self.root)
        try:self.assertEqual(len(store.all()),1)
        finally:store.close()
        self.assertEqual((self.root/'.startup.lock').stat().st_mode&0o777,0o600)

    def test_constructor_failure_closes_connection_and_releases_startup_lock(self):
        connect=sqlite3.connect;connections=[]
        class Tracked(sqlite3.Connection):
            closed=False
            def close(self):self.closed=True;super().close()
        def tracked(*args,**kwargs):
            db=connect(*args,factory=Tracked,**kwargs);connections.append(db);return db
        for stage in ('_enable_wal','backup'):
            directory=self.root/stage
            with self.subTest(stage=stage),patch.object(storage.sqlite3,'connect',side_effect=tracked):
                target=storage if stage=='_enable_wal' else storage.Store
                with patch.object(target,stage,side_effect=RuntimeError('injected startup failure')):
                    with self.assertRaisesRegex(RuntimeError,'injected'):storage.Store(directory)
                self.assertTrue(connections[-1].closed)
                store=storage.Store(directory)
                try:
                    self.assertEqual(len(store.all()),1)
                    self.assertEqual(store.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                finally:store.close()

    def test_startup_lock_rejects_symlink_without_touching_target(self):
        outside=self.root/'outside';outside.write_text('preserved')
        (self.root/'.startup.lock').symlink_to(outside)
        with patch.object(storage.sqlite3,'connect') as connect:
            with self.assertRaises(OSError):storage.Store(self.root)
            connect.assert_not_called()
        self.assertEqual(outside.read_text(),'preserved')
