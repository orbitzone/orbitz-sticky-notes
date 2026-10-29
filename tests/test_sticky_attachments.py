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

    def test_add_list_remove_and_delete_only_metadata_not_source_file(self):
        source=self.file('report.pdf')
        item=self.store.add_attachment(self.note['id'],source)
        self.assertEqual(item['name'],'report.pdf');self.assertEqual(item['size'],len(b'attachment'))
        self.assertEqual(self.store.attachments(self.note['id']),[item])
        self.assertTrue(self.store.remove_attachment(self.note['id'],item['id']))
        self.assertEqual(self.store.attachments(self.note['id']),[]);self.assertTrue(source.exists())

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

    def test_total_size_limit_is_independent_from_file_and_count_limits(self):
        with patch.object(storage,'ATTACHMENT_MAX_TOTAL_BYTES',10):
            self.store.add_attachment(self.note['id'],self.file('first.txt',b'123456'))
            with self.assertRaises(ValueError):self.store.add_attachment(self.note['id'],self.file('second.txt',b'12345'))
            self.assertEqual(len(self.store.attachments(self.note['id'])),1)

    def test_deletion_purges_attachment_rows_from_retained_backup(self):
        self.store.add_attachment(self.note['id'],self.file('keep.pdf'))
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

    def test_legacy_backup_purge_remains_compatible_with_attachment_schema(self):
        source=self.file('report.docx');self.store.add_attachment(self.note['id'],source)
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


if __name__=='__main__':unittest.main()
