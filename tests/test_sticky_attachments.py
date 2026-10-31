"""Attachment metadata and validation use isolated files and temporary SQLite stores."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('GSETTINGS_BACKEND','memory')
sys.path.insert(0,str(ROOT/'sticky-notes'))
SPEC=importlib.util.spec_from_file_location('attachment_note_storage',ROOT/'sticky-notes/storage.py')
storage=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(storage)


class StickyAttachmentTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.store=storage.Store(self.root);self.addCleanup(self.store.close)
        self.note=self.store.all()[0]

    def file(self,name,data=b'attachment'):
        path=self.root/name;path.write_bytes(data);return path

    def test_add_copies_to_private_persistent_storage_and_remove_keeps_original(self):
        source=self.file('report.pdf')
        item=self.store.add_attachment(self.note['id'],source)
        self.assertEqual(item['name'],'report.pdf');self.assertEqual(item['size'],len(b'attachment'))
        self.assertEqual(Path(item['source_path']),source)
        self.assertEqual(Path(item['path']).parent,self.store.attachments_directory)
        self.assertEqual(Path(item['path']).read_bytes(),source.read_bytes())
        self.assertEqual(Path(item['path']).stat().st_mode & 0o777,0o600)
        self.assertEqual(item['managed'],1)
        self.assertEqual(self.store.attachments(self.note['id']),[item])
        self.assertTrue(self.store.remove_attachment(self.note['id'],item['id']))
        self.assertEqual(self.store.attachments(self.note['id']),[])
        self.assertFalse(Path(item['path']).exists());self.assertTrue(source.exists())

    def test_managed_copy_remains_available_after_reopening_the_store(self):
        source=self.file('after-restart.txt',b'persistent test payload')
        item=self.store.add_attachment(self.note['id'],source)
        source.unlink()
        reopened=storage.Store(self.root);self.addCleanup(reopened.close)
        saved=reopened.attachments(self.note['id'])[0]
        self.assertEqual(saved['path'],item['path'])
        self.assertEqual(Path(saved['path']).read_bytes(),b'persistent test payload')

    def test_remove_unlinks_a_replaced_managed_symlink_without_following_it(self):
        source=self.file('source.txt');item=self.store.add_attachment(self.note['id'],source)
        managed=Path(item['path']);managed.unlink();managed.symlink_to(source)
        self.assertTrue(self.store.remove_attachment(self.note['id'],item['id']))
        self.assertFalse(os.path.lexists(managed));self.assertTrue(source.exists())

    def test_type_symlink_size_and_duplicate_checks_fail_closed(self):
        with self.assertRaises(ValueError):self.store.add_attachment(self.note['id'],self.file('run.sh'))
        source=self.file('source.txt');link=self.root/'linked.txt';link.symlink_to(source)
        with self.assertRaises(ValueError):self.store.add_attachment(self.note['id'],link)
        with self.assertRaises(ValueError):self.store.add_attachment(self.note['id'],self.file('large.zip',b'x'*(storage.ATTACHMENT_MAX_FILE_BYTES+1)))
        item=self.store.add_attachment(self.note['id'],source)
        with self.assertRaises(ValueError):self.store.add_attachment(self.note['id'],source)
        self.assertEqual(self.store.attachments(self.note['id']),[item])

    def test_count_and_total_size_limits_and_note_delete_cascade(self):
        for index in range(storage.ATTACHMENT_MAX_COUNT):
            self.store.add_attachment(self.note['id'],self.file(f'{index}.txt'))
        with self.assertRaises(ValueError):self.store.add_attachment(self.note['id'],self.file('extra.txt'))
        self.assertTrue(self.store.delete(self.note['id'],self.note['revision']))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM attachments WHERE note_id=?',(self.note['id'],)).fetchone()[0],0)
        self.assertEqual(self.store.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertFalse(any(self.store.attachments_directory.glob('????????-????-????-????-????????????.*')))

    def test_total_size_limit_is_independent_from_file_and_count_limits(self):
        with patch.object(storage,'ATTACHMENT_MAX_TOTAL_BYTES',10):
            self.store.add_attachment(self.note['id'],self.file('first.txt',b'123456'))
            with self.assertRaises(ValueError):self.store.add_attachment(self.note['id'],self.file('second.txt',b'12345'))
            self.assertEqual(len(self.store.attachments(self.note['id'])),1)

    def test_deletion_purges_attachment_rows_from_retained_backup(self):
        item=self.store.add_attachment(self.note['id'],self.file('keep.pdf'))
        snapshot=self.root/'backups'/'2099-12-31.sqlite3'
        copy=sqlite3.connect(snapshot)
        try:self.store.db.backup(copy)
        finally:copy.close()
        self.assertTrue(self.store.delete(self.note['id'],self.note['revision']))
        check=sqlite3.connect(snapshot)
        try:
            self.assertEqual(check.execute('SELECT count(*) FROM notes WHERE id=?',(self.note['id'],)).fetchone()[0],0)
            self.assertEqual(check.execute('SELECT count(*) FROM attachments WHERE note_id=?',(self.note['id'],)).fetchone()[0],0)
        finally:check.close()
        self.assertFalse(Path(item['path']).exists())

    def test_legacy_backup_purge_remains_compatible_with_attachment_schema(self):
        source=self.file('report.docx');item=self.store.add_attachment(self.note['id'],source)
        snapshot=self.root/'backups'/'2020-01-01.sqlite3'
        db=sqlite3.connect(snapshot)
        try:
            db.execute('CREATE TABLE notes(id TEXT PRIMARY KEY,text TEXT NOT NULL)')
            db.execute('INSERT INTO notes VALUES(?,?)',(self.note['id'],'legacy'))
            db.commit()
        finally:db.close()
        self.assertTrue(self.store.delete(self.note['id'],self.note['revision']))
        db=sqlite3.connect(snapshot)
        try:self.assertEqual(db.execute('SELECT count(*) FROM notes').fetchone()[0],0)
        finally:db.close()
        self.assertTrue(source.exists())
        self.assertFalse(Path(item['path']).exists())

    def test_legacy_copy_failure_keeps_notes_available_and_retries(self):
        source=self.file('retry.txt',b'retry migration')
        item=self.store.add_attachment(self.note['id'],source)
        with self.store.db:
            self.store.db.execute('UPDATE attachments SET path=?,source_path=?,managed=0 WHERE id=?',
                                  (str(source),'',item['id']))
        with patch.object(storage.Store,'_copy_attachment',side_effect=OSError('portal unavailable')):
            reopened=storage.Store(self.root)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.attachments(self.note['id'])[0]['managed'],0)
        self.assertEqual(reopened.get(self.note['id'])['text'],self.note['text'])
        retried=storage.Store(self.root);self.addCleanup(retried.close)
        self.assertEqual(retried.attachments(self.note['id'])[0]['managed'],1)

    def test_legacy_attachment_rows_migrate_without_taking_ownership_of_source(self):
        old=self.root/'old';old.mkdir()
        db=sqlite3.connect(old/'notes.sqlite3')
        try:
            db.executescript('''CREATE TABLE notes(id TEXT PRIMARY KEY,text TEXT NOT NULL,title TEXT NOT NULL DEFAULT '',color TEXT NOT NULL,x INTEGER NOT NULL DEFAULT 100,y INTEGER NOT NULL DEFAULT 100,width INTEGER NOT NULL DEFAULT 310,height INTEGER NOT NULL DEFAULT 300,above INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0,archived INTEGER NOT NULL DEFAULT 0,secret INTEGER NOT NULL DEFAULT 0,code_mode INTEGER NOT NULL DEFAULT 0,reduced_opacity INTEGER NOT NULL DEFAULT 0,code_language TEXT NOT NULL DEFAULT 'python');
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE attachments(id TEXT PRIMARY KEY,note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,path TEXT NOT NULL,name TEXT NOT NULL,size INTEGER NOT NULL,added_at INTEGER NOT NULL);
            INSERT INTO notes(id,text,color) VALUES('legacy','body','#ffe293');
            INSERT INTO attachments VALUES('legacy-attachment','legacy','/tmp/legacy.txt','legacy.txt',4,1);
            INSERT INTO metadata VALUES('imported','1');''');db.commit()
        finally:db.close()
        migrated=storage.Store(old);self.addCleanup(migrated.close)
        row=migrated.attachments('legacy')[0]
        self.assertEqual(row['path'],'/tmp/legacy.txt');self.assertEqual(row['source_path'],'');self.assertEqual(row['managed'],0)
        self.assertFalse((old/'attachments').exists())

    def test_accessible_legacy_source_is_migrated_to_a_durable_copy(self):
        source=self.file('legacy-source.txt',b'old portal grant still works')
        old=self.root/'old-accessible';old.mkdir();identity='a8d5408e-6b45-4916-9d39-06bb3118ccbf'
        db=sqlite3.connect(old/'notes.sqlite3')
        try:
            db.executescript('''CREATE TABLE notes(id TEXT PRIMARY KEY,text TEXT NOT NULL,title TEXT NOT NULL DEFAULT '',color TEXT NOT NULL,x INTEGER NOT NULL DEFAULT 100,y INTEGER NOT NULL DEFAULT 100,width INTEGER NOT NULL DEFAULT 310,height INTEGER NOT NULL DEFAULT 300,above INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0,archived INTEGER NOT NULL DEFAULT 0,secret INTEGER NOT NULL DEFAULT 0,code_mode INTEGER NOT NULL DEFAULT 0,reduced_opacity INTEGER NOT NULL DEFAULT 0,code_language TEXT NOT NULL DEFAULT 'python');
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE attachments(id TEXT PRIMARY KEY,note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,path TEXT NOT NULL,name TEXT NOT NULL,size INTEGER NOT NULL,added_at INTEGER NOT NULL);
            INSERT INTO notes(id,text,color) VALUES('legacy','body','#ffe293');
            INSERT INTO metadata VALUES('imported','1');'''.format(source=str(source).replace("'", "''")));db.commit()
            db.execute('INSERT INTO attachments VALUES(?,?,?,?,?,?)',
                       ('a8d5408e-6b45-4916-9d39-06bb3118ccbf','legacy',str(source),'legacy-source.txt',28,1));db.commit()
        finally:db.close()
        migrated=storage.Store(old);self.addCleanup(migrated.close)
        row=migrated.attachments('legacy')[0]
        self.assertEqual(row['managed'],1);self.assertEqual(row['source_path'],str(source))
        self.assertEqual(Path(row['path']).read_bytes(),b'old portal grant still works')
        self.assertTrue(source.exists())


if __name__=='__main__':unittest.main()
