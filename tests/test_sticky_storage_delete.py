"""Permanent note deletion using temporary SQLite databases, never user data."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import subprocess
import tempfile
import time
import unittest
import shutil
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('GSETTINGS_BACKEND','memory')
sys.path.insert(0,str(ROOT/'sticky-notes'))
SPEC=importlib.util.spec_from_file_location('deleting_note_storage',ROOT/'sticky-notes/storage.py')
storage=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(storage)


class StickyDeleteTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        self.notes=storage.Store(self.root)
        self.addCleanup(lambda:self.notes.close())

    def snapshot(self,name,rows):
        path=self.root/'backups'/name
        db=sqlite3.connect(path)
        try:
            db.execute('CREATE TABLE notes (id TEXT PRIMARY KEY, text TEXT NOT NULL)')
            db.executemany('INSERT INTO notes(id,text) VALUES(?,?)',rows)
            db.commit()
        finally:db.close()
        return path

    @staticmethod
    def snapshot_query(path,sql,args=()):
        db=sqlite3.connect(path)
        try:return db.execute(sql,args).fetchall()
        finally:db.close()

    def test_delete_purges_snapshots_survives_reopen_and_preserves_other_notes(self):
        removed=self.notes.all()[0];other=self.notes.create()
        self.notes.text(removed['id'],'temporary note',0)
        self.notes.text(other['id'],'keep this note',0)
        kept=self.notes.get(other['id'])
        later=self.snapshot('2020-01-01.sqlite3',[(removed['id'],'temporary note'),(other['id'],'keep this note')])
        metadata=list(self.notes.db.execute('SELECT * FROM metadata'))
        backup_names={p.name for p in (self.root/'backups').glob('*.sqlite3')}
        self.assertIs(self.notes.delete(removed['id'],1),True)
        self.assertEqual(self.notes.db.execute('SELECT count(*) FROM notes WHERE id=?',(removed['id'],)).fetchone()[0],0)
        with self.assertRaises(ValueError):self.notes.get(removed['id'])
        for path in (self.root/'backups').glob('*.sqlite3'):
            self.assertEqual(self.snapshot_query(path,'SELECT count(*) FROM notes WHERE id=?',(removed['id'],)),[(0,)])
        self.assertEqual(self.snapshot_query(later,'SELECT count(*) FROM notes WHERE id=?',(other['id'],)),[(1,)])
        self.notes.close();self.notes=storage.Store(self.root)
        self.assertEqual(self.notes.all(),[kept])
        self.assertEqual(list(self.notes.db.execute('SELECT * FROM metadata')),metadata)
        self.assertEqual({p.name for p in (self.root/'backups').glob('*.sqlite3')},backup_names)
        self.assertEqual(self.notes.db.execute('PRAGMA journal_mode').fetchone()[0],'wal')
        self.assertEqual(self.notes.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_purges_legacy_snapshot_schema_and_keeps_other_records(self):
        note=self.notes.all()[0];other=self.notes.create()
        legacy=[self.snapshot(f'2020-01-{day:02d}.sqlite3',[(note['id'],'deleted'),(other['id'],'keep')])
                for day in range(1,15)]
        self.assertTrue(self.notes.delete(note['id'],0))
        for path in legacy:
            self.assertEqual(self.snapshot_query(path,'SELECT id,text FROM notes'),[(other['id'],'keep')])

    def test_unreadable_legacy_snapshot_fails_closed_before_replacing_any_snapshot(self):
        note=self.notes.all()[0]
        valid=self.snapshot('2020-01-01.sqlite3',[(note['id'],'deleted')])
        invalid=self.root/'backups'/'2020-01-02.sqlite3';invalid.write_bytes(b'not a sqlite database')
        before={path.name:path.read_bytes() for path in (self.root/'backups').glob('*.sqlite3')}
        with self.assertRaises(storage.BackupPurgeError) as caught:self.notes.delete(note['id'],0)
        self.assertEqual(caught.exception.orbitz_message.key,'domain.sticky_storage.backup_purge_failed')
        self.assertEqual(self.notes.get(note['id']),note)
        self.assertEqual({path.name:path.read_bytes() for path in (self.root/'backups').glob('*.sqlite3')},before)
        self.assertTrue(valid.exists())

    def test_partial_snapshot_promotion_keeps_active_note_and_retry_completes_purge(self):
        note=self.notes.all()[0]
        first=self.snapshot('2020-01-01.sqlite3',[(note['id'],'deleted')])
        second=self.snapshot('2020-01-02.sqlite3',[(note['id'],'deleted')])
        replace=storage.os.replace;calls=[]
        def fail_second(source,target):
            calls.append((source,target))
            if len(calls)==2:raise OSError('injected promotion failure')
            return replace(source,target)
        with patch.object(storage.os,'replace',side_effect=fail_second):
            with self.assertRaises(storage.BackupPurgeError) as caught:self.notes.delete(note['id'],0)
        self.assertEqual(caught.exception.orbitz_message.key,'domain.sticky_storage.backup_purge_failed')
        self.assertEqual(self.notes.get(note['id']),note)
        self.assertTrue(any(self.snapshot_query(path,'SELECT 1 FROM notes WHERE id=?',(note['id'],))
                            for path in (first,second)))
        self.assertTrue(self.notes.delete(note['id'],0))
        for path in (first,second):
            self.assertEqual(self.snapshot_query(path,'SELECT count(*) FROM notes WHERE id=?',(note['id'],)),[(0,)])

    def test_promotion_symlink_swap_fails_closed_and_does_not_touch_external_database(self):
        note=self.notes.all()[0]
        snapshot=self.snapshot('2020-01-01.sqlite3',[(note['id'],'deleted')])
        outside=self.root/'outside.sqlite3'
        db=sqlite3.connect(outside)
        try:
            db.execute('CREATE TABLE notes (id TEXT PRIMARY KEY, text TEXT NOT NULL)')
            db.execute('INSERT INTO notes(id,text) VALUES(?,?)',(note['id'],'outside record'))
            db.commit()
        finally:db.close()
        replace=storage.os.replace
        def swap_source_for_symlink(source,target):
            if Path(target)==snapshot:
                Path(source).unlink()
                Path(source).symlink_to(outside)
            return replace(source,target)
        with patch.object(storage.os,'replace',side_effect=swap_source_for_symlink):
            with self.assertRaises(storage.BackupPurgeError):self.notes.delete(note['id'],0)
        self.assertEqual(self.notes.get(note['id']),note)
        self.assertFalse(snapshot.is_symlink())
        self.assertEqual(self.snapshot_query(snapshot,'SELECT count(*) FROM notes WHERE id=?',(note['id'],)),[(0,)])
        self.assertEqual(self.snapshot_query(outside,'SELECT text FROM notes WHERE id=?',(note['id'],)),[('outside record',)])

    def test_dangling_sqlite_sidecar_symlink_fails_closed(self):
        note=self.notes.all()[0]
        snapshot=self.snapshot('2020-01-01.sqlite3',[(note['id'],'deleted')])
        dangling=Path(str(snapshot)+'-wal')
        dangling.symlink_to(self.root/'missing-wal-target')
        before=snapshot.read_bytes()
        with self.assertRaises(storage.BackupPurgeError) as caught:self.notes.delete(note['id'],0)
        self.assertEqual(caught.exception.orbitz_message.key,'domain.sticky_storage.backup_purge_failed')
        self.assertEqual(self.notes.get(note['id']),note)
        self.assertEqual(snapshot.read_bytes(),before)
        self.assertTrue(dangling.is_symlink())

    def test_orphan_regular_wal_sidecar_is_normalized_before_archived_note_purge(self):
        note=self.notes.all()[0];other=self.notes.create();self.notes.properties(note['id'],archived=1)
        snapshot=self.snapshot('2020-01-01.sqlite3',[(note['id'],'archived'),(other['id'],'keep')])
        wal=Path(str(snapshot)+'-wal');wal.write_bytes(b'leftover WAL data')
        self.assertTrue(self.notes.delete(note['id'],0))
        self.assertEqual(self.snapshot_query(snapshot,'SELECT id FROM notes'),[(other['id'],)])
        self.assertFalse(wal.exists())

    def test_legacy_wal_snapshot_is_checkpointed_then_purged_without_losing_other_rows(self):
        note=self.notes.all()[0];other=self.notes.create()
        self.notes.properties(note['id'],archived=1)
        snapshot=self._create_wal_snapshot('2020-01-01.sqlite3',[
            (note['id'],'archived target in WAL'),(other['id'],'keep from WAL')])
        self.assertTrue(Path(str(snapshot)+'-wal').exists())
        self.assertTrue(self.notes.delete(note['id'],0))
        self.assertEqual(self.snapshot_query(snapshot,'SELECT id,text FROM notes'),[(other['id'],'keep from WAL')])
        self.assertFalse(Path(str(snapshot)+'-wal').exists())
        self.assertFalse(Path(str(snapshot)+'-shm').exists())

    def test_busy_legacy_wal_fails_closed_then_retry_purges_archived_note(self):
        note=self.notes.all()[0];other=self.notes.create()
        self.notes.properties(note['id'],archived=1)
        snapshot=self._create_wal_snapshot('2020-01-01.sqlite3',[
            (note['id'],'archived target'),(other['id'],'preserve')])
        reader=sqlite3.connect(snapshot,timeout=0)
        try:
            reader.execute('BEGIN')
            reader.execute('SELECT * FROM notes').fetchall()
            with self.assertRaises(storage.BackupPurgeError):self.notes.delete(note['id'],0)
            self.assertEqual(self.notes.get(note['id'])['archived'],1)
            self.assertEqual(reader.execute('SELECT count(*) FROM notes WHERE id=?',(note['id'],)).fetchone()[0],1)
            reader.rollback()
        finally:reader.close()
        self.assertTrue(self.notes.delete(note['id'],0))
        self.assertEqual(self.snapshot_query(snapshot,'SELECT id FROM notes'),[(other['id'],)])

    def _create_wal_snapshot(self,name,rows):
        source=self.root/'wal-source.sqlite3';snapshot=self.root/'backups'/name
        writer=sqlite3.connect(source)
        try:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower(),'wal')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('CREATE TABLE notes (id TEXT PRIMARY KEY, text TEXT NOT NULL)')
            writer.executemany('INSERT INTO notes(id,text) VALUES(?,?)',rows);writer.commit()
            wal=Path(str(source)+'-wal')
            self.assertTrue(wal.exists())
            shutil.copyfile(source,snapshot);shutil.copyfile(wal,Path(str(snapshot)+'-wal'))
        finally:writer.close()
        return snapshot

    def test_unknown_and_repeated_delete_are_idempotent_and_parameterized(self):
        note=self.notes.all()[0];before=self.notes.all()
        self.assertIs(self.notes.delete("' OR 1=1 --",0),False)
        self.assertEqual(self.notes.all(),before)
        self.assertTrue(self.notes.delete(note['id']))
        self.assertIs(self.notes.delete(note['id'],0),False)
        self.notes.close();self.notes=storage.Store(self.root)
        self.assertEqual(self.notes.all(),[])  # No reimport or restoration.

    def test_revision_conflict_from_other_connection_preserves_latest_edit(self):
        note=self.notes.all()[0]
        backups={p.name:p.read_bytes() for p in (self.root/'backups').glob('*.sqlite3')}
        second=storage.Store(self.root)
        try:
            second.text(note['id'],'another process edit',0)
            with self.assertRaises(ValueError) as caught:self.notes.delete(note['id'],0)
            self.assertEqual(caught.exception.orbitz_message.key,'domain.sticky_storage.concurrent_edit')
            self.assertEqual(self.notes.get(note['id'])['text'],'another process edit')
            self.assertEqual({p.name:p.read_bytes() for p in (self.root/'backups').glob('*.sqlite3')},backups)
            self.assertTrue(self.notes.delete(note['id'],1))
            with self.assertRaises(ValueError):second.get(note['id'])
        finally:second.close()

    def test_trigger_failure_rolls_back_delete_and_associated_changes(self):
        note=self.notes.all()[0];other=self.notes.create();before=self.notes.all()
        self.notes.db.execute('''CREATE TRIGGER fail_delete AFTER DELETE ON notes BEGIN
          UPDATE notes SET text='should roll back';
          SELECT RAISE(ABORT,'injected failure');
        END''')
        with self.assertRaises(sqlite3.IntegrityError):self.notes.delete(note['id'],0)
        self.assertEqual(self.notes.all(),before)
        for path in (self.root/'backups').glob('*.sqlite3'):
            self.assertEqual(self.snapshot_query(path,'SELECT count(*) FROM notes WHERE id=?',(note['id'],)),[(0,)])
        self.notes.close();self.notes=storage.Store(self.root)
        self.assertEqual(self.notes.all(),before)
        self.notes.db.execute('DROP TRIGGER fail_delete')
        self.assertTrue(self.notes.delete(note['id'],0))
        self.assertEqual(self.notes.all(),[other])

    def test_invalid_revision_does_not_mutate_note(self):
        note=self.notes.all()[0]
        for revision in (True,-1,1.5,'0'):
            with self.subTest(revision=revision),self.assertRaises(ValueError):self.notes.delete(note['id'],revision)
            self.assertEqual(self.notes.all(),[note])

    def test_existing_writer_lock_blocks_delete_without_partial_changes(self):
        note=self.notes.all()[0]
        backups={p.name:p.read_bytes() for p in (self.root/'backups').glob('*.sqlite3')}
        writer=sqlite3.connect(self.notes.path)
        try:
            writer.execute('BEGIN IMMEDIATE')
            self.notes.db.execute('PRAGMA busy_timeout=0')
            with self.assertRaises(sqlite3.OperationalError):self.notes.delete(note['id'],0)
            self.assertEqual(self.notes.all(),[note])
            self.assertEqual({p.name:p.read_bytes() for p in (self.root/'backups').glob('*.sqlite3')},backups)
            writer.rollback()
            self.assertTrue(self.notes.delete(note['id'],0))
        finally:writer.close()

    def test_archived_notes_remain_visible_without_migration_or_restore(self):
        note=self.notes.all()[0];other=self.notes.create()
        self.notes.properties(note['id'],archived=1)
        archived=self.notes.get(note['id'])
        self.assertEqual(self.notes.all(),[archived,other])
        self.assertEqual(self.notes.all(archived=True),[archived])
        self.assertEqual(self.notes.all(archived=False),[other])
        self.notes.close();self.notes=storage.Store(self.root)
        self.assertEqual(self.notes.get(note['id']),archived)
        self.assertTrue(self.notes.delete(note['id'],0))
        self.assertEqual(self.notes.all(),[other])

    def test_archived_note_deletion_purges_diverse_legacy_and_current_snapshots(self):
        note=self.notes.all()[0];other=self.notes.create()
        self.notes.properties(note['id'],archived=1)
        legacy=self.snapshot('2020-01-01.sqlite3',[(note['id'],'old archived text'),(other['id'],'keep')])
        current=self.root/'backups'/'2020-01-02.sqlite3'
        db=sqlite3.connect(current)
        try:
            db.execute('''CREATE TABLE notes (
              id TEXT PRIMARY KEY, text TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
              color TEXT NOT NULL DEFAULT '#ffe293', archived INTEGER NOT NULL DEFAULT 0)''')
            db.executemany('INSERT INTO notes(id,text,title,archived) VALUES(?,?,?,?)',[
                (note['id'],'archived snapshot text','Old title',1),(other['id'],'keep','Keep title',0)])
            db.commit()
        finally:db.close()
        self.assertTrue(self.notes.delete(note['id'],0))
        for path in (legacy,current):
            self.assertEqual(self.snapshot_query(path,'SELECT count(*) FROM notes WHERE id=?',(note['id'],)),[(0,)])
            self.assertEqual(self.snapshot_query(path,'SELECT id FROM notes WHERE id=?',(other['id'],)),[(other['id'],)])
        self.assertEqual(self.notes.all(),[other])

    def test_title_schema_migration_is_idempotent_and_preserves_legacy_records(self):
        root=self.root/'legacy-install';root.mkdir()
        path=root/'notes.sqlite3';identity='legacy-note-id'
        db=sqlite3.connect(path)
        try:
            db.execute('''CREATE TABLE notes (
              id TEXT PRIMARY KEY, text TEXT NOT NULL, color TEXT NOT NULL,
              x INTEGER NOT NULL DEFAULT 100, y INTEGER NOT NULL DEFAULT 100,
              width INTEGER NOT NULL DEFAULT 310, height INTEGER NOT NULL DEFAULT 300,
              above INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
              archived INTEGER NOT NULL DEFAULT 0)''')
            db.execute('INSERT INTO notes(id,text,color,revision,archived) VALUES(?,?,?,?,?)',
                       (identity,'preserve this text','#ffe293',7,1))
            db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute("INSERT INTO metadata VALUES('imported','1')");db.commit()
        finally:db.close()
        backup_dir=root/'backups';backup_dir.mkdir()
        old_snapshot=backup_dir/'2019-12-31.sqlite3';self.snapshot_at(old_snapshot,[(identity,'historical text')])
        snapshot_bytes=old_snapshot.read_bytes()
        first=storage.Store(root)
        try:
            row=first.get(identity)
            self.assertEqual((row['id'],row['text'],row['title'],row['revision'],row['archived']),
                             (identity,'preserve this text','',7,1))
            self.assertEqual(first.title(identity,'Project Alpha',7),8)
            self.assertEqual(first.get(identity)['title'],'Project Alpha')
            self.assertEqual(old_snapshot.read_bytes(),snapshot_bytes)
        finally:first.close()
        second=storage.Store(root)
        try:
            self.assertEqual(second.get(identity)['title'],'Project Alpha')
            self.assertEqual(second.title(identity,'',8),9)
            created=second.create()
            self.assertEqual(created['title'],'')
            self.assertEqual(second.all()[0]['title'],'')
        finally:second.close()

    def test_concurrent_legacy_title_migrations_are_serialized_across_processes(self):
        for iteration in range(4):
            with self.subTest(iteration=iteration):
                self._run_concurrent_legacy_title_migration(iteration)

    def _run_concurrent_legacy_title_migration(self,iteration):
        root=self.root/f'concurrent-legacy-{iteration}';root.mkdir()
        identity='race-legacy-id';path=root/'notes.sqlite3'
        db=sqlite3.connect(path)
        try:
            db.execute('''CREATE TABLE notes (
              id TEXT PRIMARY KEY, text TEXT NOT NULL, color TEXT NOT NULL,
              x INTEGER NOT NULL DEFAULT 100, y INTEGER NOT NULL DEFAULT 100,
              width INTEGER NOT NULL DEFAULT 310, height INTEGER NOT NULL DEFAULT 300,
              above INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
              archived INTEGER NOT NULL DEFAULT 0)''')
            db.execute('INSERT INTO notes(id,text,color,revision,archived) VALUES(?,?,?,?,?)',
                       (identity,'unchanged legacy text','#ffe293',4,1))
            db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute("INSERT INTO metadata VALUES('imported','1')");db.commit()
        finally:db.close()

        go=root/'go';processes=[];ready_paths=[root/'ready-0',root/'ready-1']
        child_code='''
import sys,time
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'sticky-notes'))
import storage
root=Path(sys.argv[2]); ready=Path(sys.argv[3]); go=Path(sys.argv[4])
ready.write_text('ready')
deadline=time.monotonic()+15
while not go.exists():
    if time.monotonic()>deadline: raise TimeoutError('migration barrier timed out')
    time.sleep(.01)
store=storage.Store(root); row=store.get('race-legacy-id')
assert row['title']=='' and row['text']=='unchanged legacy text' and row['revision']==4 and row['archived']==1
store.close()
'''
        env=os.environ.copy();env['GSETTINGS_BACKEND']='memory'
        try:
            for ready in ready_paths:
                processes.append(subprocess.Popen(
                    [sys.executable,'-c',child_code,str(ROOT),str(root),str(ready),str(go)],
                    cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
            deadline=time.monotonic()+15
            while not all(ready.exists() for ready in ready_paths):
                if any(process.poll() is not None for process in processes):
                    details=[process.communicate(timeout=1) for process in processes if process.poll() is not None]
                    self.fail(f'initializer exited before barrier: {details}')
                if time.monotonic()>deadline:self.fail('initializers did not reach migration barrier')
                time.sleep(.01)
            go.write_text('start')
            for process in processes:
                stdout,stderr=process.communicate(timeout=20)
                self.assertEqual(process.returncode,0,f'initializer failed: {stdout}\n{stderr}')
        finally:
            if not go.exists():go.write_text('release')
            for process in processes:
                if process.poll() is None:process.kill();process.communicate()

        verify=sqlite3.connect(path)
        try:
            titles=[row[1] for row in verify.execute('PRAGMA table_info(notes)') if row[1]=='title']
            self.assertEqual(titles,['title'])
            self.assertEqual(verify.execute('SELECT id,text,revision,archived,title FROM notes').fetchall(),
                             [(identity,'unchanged legacy text',4,1,'')])
        finally:verify.close()

    @staticmethod
    def snapshot_at(path,rows):
        db=sqlite3.connect(path)
        try:
            db.execute('CREATE TABLE notes (id TEXT PRIMARY KEY, text TEXT NOT NULL)')
            db.executemany('INSERT INTO notes(id,text) VALUES(?,?)',rows);db.commit()
        finally:db.close()
