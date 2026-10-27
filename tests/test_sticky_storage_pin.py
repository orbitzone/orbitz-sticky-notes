"""UI-only PIN/privacy state: temporary databases and memory GSettings."""
import importlib.util
from datetime import date,timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('GSETTINGS_BACKEND','memory')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'sticky-notes'))
SPEC=importlib.util.spec_from_file_location('pin_note_storage',ROOT/'sticky-notes/storage.py')
storage=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(storage)


class StickyPinTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        self.notes=storage.Store(self.root)
        self.addCleanup(lambda:self.notes.close())

    def record(self):
        return self.notes.db.execute('SELECT value FROM metadata WHERE key=?',(storage.PIN_METADATA_KEY,)).fetchone()[0]

    def key(self,error):return error.orbitz_message.key

    def test_ascii_pin_validation_including_leading_zero_without_mutation(self):
        self.assertFalse(self.notes.has_pin())
        for pin in (None,1234,True,'','123','12345','１２３４','١٢٣٤','123\n',' 123','1234\n'):
            for call in (lambda:self.notes.set_pin(pin),lambda:self.notes.verify_pin(pin)):
                with self.subTest(pin=pin),self.assertRaises(ValueError) as caught:call()
                self.assertEqual(self.key(caught.exception),'domain.sticky_storage.pin_format')
                self.assertFalse(self.notes.has_pin())
        self.notes.set_pin('0007');self.assertTrue(self.notes.has_pin())
        self.assertTrue(self.notes.verify_pin('0007'))

    def test_initial_pin_hash_salt_change_and_reopen(self):
        self.notes.set_pin('0012');before=self.record();parsed=json.loads(before)
        self.assertEqual(parsed['iterations'],600000)
        self.assertEqual(len(parsed['salt']),32);self.assertEqual(len(parsed['digest']),64)
        self.assertNotIn('pin',parsed);self.assertNotEqual(parsed['digest'],'0012')
        with self.assertRaises(ValueError) as caught:self.notes.set_pin('5678')
        self.assertEqual(self.key(caught.exception),'domain.sticky_storage.pin_already_set')
        self.assertEqual(before,self.record())
        with self.assertRaises(ValueError) as caught:self.notes.change_pin('7777','5678')
        self.assertEqual(self.key(caught.exception),'domain.sticky_storage.pin_incorrect')
        self.assertTrue(self.notes.verify_pin('0012'))
        self.notes.change_pin('0012','5678');after=json.loads(self.record())
        self.assertNotEqual(parsed['salt'],after['salt']);self.assertNotEqual(parsed['digest'],after['digest'])
        self.notes.close();self.notes=storage.Store(self.root)
        self.assertFalse(self.notes.verify_pin('0012'));self.assertTrue(self.notes.verify_pin('5678'))

    def test_missing_pin_and_invalid_new_pin_never_configure_or_mutate(self):
        for call in (lambda:self.notes.verify_pin('1234'),lambda:self.notes.change_pin('1234','5678')):
            with self.assertRaises(ValueError) as caught:call()
            self.assertEqual(self.key(caught.exception),'domain.sticky_storage.pin_not_set')
        self.assertFalse(self.notes.has_pin())
        self.notes.set_pin('1234');before=self.record()
        with self.assertRaises(ValueError):self.notes.change_pin('0000','not a PIN')
        self.assertEqual(self.record(),before)

    def test_global_attempt_limit_persists_across_connections_and_expires(self):
        self.notes.set_pin('1234')
        other=storage.Store(self.root)
        try:
            with patch.object(storage.time,'time',return_value=1000):
                for index in range(4):self.assertFalse((self.notes if index%2 else other).verify_pin('0000'))
                with self.assertRaises(storage.PinLockedError) as caught:other.verify_pin('0000')
                self.assertEqual(caught.exception.retry_after,30)
                with self.assertRaises(storage.PinLockedError):self.notes.verify_pin('1234')
                with self.assertRaises(storage.PinLockedError):self.notes.change_pin('1234','5555')
            with patch.object(storage.time,'time',return_value=1029):
                with self.assertRaises(storage.PinLockedError) as caught:self.notes.verify_pin('1234')
                self.assertEqual(caught.exception.retry_after,1)
            with patch.object(storage.time,'time',return_value=1030):self.assertTrue(self.notes.verify_pin('1234'))
            self.assertEqual(json.loads(self.record())['failures'],0)
        finally:other.close()

    def test_clock_rollback_caps_cooldown_and_success_resets_attempts(self):
        self.notes.set_pin('1234')
        with patch.object(storage.time,'time',return_value=1000):
            for _ in range(4):self.assertFalse(self.notes.verify_pin('0000'))
            with self.assertRaises(storage.PinLockedError):self.notes.verify_pin('0000')
        with patch.object(storage.time,'time',return_value=10):
            with self.assertRaises(storage.PinLockedError) as caught:self.notes.verify_pin('1234')
            self.assertEqual(caught.exception.retry_after,30)
        with patch.object(storage.time,'time',return_value=40):self.assertTrue(self.notes.verify_pin('1234'))
        self.assertFalse(self.notes.verify_pin('0000'));self.assertTrue(self.notes.verify_pin('1234'))
        self.assertEqual(json.loads(self.record())['failures'],0)

    def test_secret_cas_requires_pin_and_preserves_plaintext_and_other_notes(self):
        note=self.notes.all()[0];other=self.notes.create()
        self.assertEqual(note['secret'],0)
        with self.assertRaises(ValueError) as caught:self.notes.set_secret(note['id'],True,0)
        self.assertEqual(self.key(caught.exception),'domain.sticky_storage.pin_not_set')
        self.notes.set_pin('1234')
        revision=self.notes.text(note['id'],'plain text stays on disk',0)
        revision=self.notes.set_secret(note['id'],True,revision)
        self.assertEqual(revision,2)
        secret=self.notes.get(note['id']);self.assertEqual(secret['secret'],1)
        self.assertEqual(secret['text'],'plain text stays on disk')
        with self.assertRaises(ValueError) as caught:self.notes.set_secret(note['id'],False,1)
        self.assertEqual(self.key(caught.exception),'domain.sticky_storage.concurrent_edit')
        for value,rev in ((1,2),('yes',2),(True,False),(False,-1)):
            with self.assertRaises(ValueError):self.notes.set_secret(note['id'],value,rev)
        self.assertEqual(self.notes.get(note['id']),secret)
        self.assertEqual(self.notes.get(other['id']),other)
        self.notes.close();self.notes=storage.Store(self.root)
        self.assertEqual(self.notes.get(note['id']),secret)
        self.assertEqual(self.notes.set_secret(note['id'],False,2),3)

    def test_secret_backup_stays_plaintext_and_delete_purges_row_not_global_pin(self):
        note=self.notes.all()[0];other=self.notes.create();self.notes.set_pin('1234')
        self.notes.text(note['id'],'explicitly unencrypted secret content',0)
        self.assertEqual(self.notes.secret(note['id'],True,1),2)
        with patch.object(storage,'date') as clock:
            clock.today.return_value=date.today()+timedelta(days=1)
            self.notes.backup()
        snapshot=self.root/'backups'/((date.today()+timedelta(days=1)).isoformat()+'.sqlite3')
        with sqlite3.connect(snapshot) as db:
            self.assertEqual(db.execute('SELECT text,secret FROM notes WHERE id=?',(note['id'],)).fetchone(),('explicitly unencrypted secret content',1))
            self.assertEqual(db.execute('SELECT value FROM metadata WHERE key=?',(storage.PIN_METADATA_KEY,)).fetchone()[0],self.record())
        self.assertTrue(self.notes.delete(note['id'],2))
        for snapshot in (self.root/'backups').glob('*.sqlite3'):
            with sqlite3.connect(snapshot) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM notes WHERE id=?',(note['id'],)).fetchone()[0],0)
        self.assertEqual(self.notes.get(other['id']),other)
        self.assertTrue(self.notes.has_pin());self.assertTrue(self.notes.verify_pin('1234'))

    def test_corrupt_pin_metadata_fails_closed_without_replacing_it(self):
        self.notes.set_pin('1234');valid=json.loads(self.record())
        for raw in ('{bad','null','[]',json.dumps({**valid,'iterations':10**10}),json.dumps({**valid,'failures':True}),json.dumps({**valid,'salt':'xyz'})):
            with self.notes.db:self.notes.db.execute('UPDATE metadata SET value=? WHERE key=?',(raw,storage.PIN_METADATA_KEY))
            for call in (self.notes.has_pin,lambda:self.notes.set_pin('2222'),lambda:self.notes.verify_pin('1234')):
                with self.assertRaises(ValueError) as caught:call()
                self.assertEqual(self.key(caught.exception),'domain.sticky_storage.pin_metadata_invalid')
                self.assertEqual(self.record(),raw)

    def test_pin_write_failure_rolls_back_and_does_not_reset_existing_pin(self):
        self.notes.set_pin('1234');before=self.record()
        self.notes.db.execute("CREATE TRIGGER fail_pin BEFORE INSERT ON metadata WHEN NEW.key='secret_pin_v1' BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.notes.change_pin('1234','5678')
        self.assertEqual(self.record(),before)
        self.notes.db.execute('DROP TRIGGER fail_pin')
        self.assertTrue(self.notes.verify_pin('1234'))

    def test_old_schema_migrates_without_rewriting_snapshot_or_notes(self):
        self.notes.close()
        old=self.root/'old';old.mkdir();path=old/'notes.sqlite3'
        with sqlite3.connect(path) as db:
            db.executescript("""CREATE TABLE notes(id TEXT PRIMARY KEY,text TEXT NOT NULL,color TEXT NOT NULL,x INTEGER DEFAULT 100,y INTEGER DEFAULT 100,width INTEGER DEFAULT 310,height INTEGER DEFAULT 300,above INTEGER DEFAULT 0,revision INTEGER DEFAULT 0,archived INTEGER DEFAULT 0);
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT INTO metadata VALUES('imported','1');
            INSERT INTO notes(id,text,color,revision,archived) VALUES('old-note','legacy plaintext','#ffe293',7,1);""")
            backups=old/'backups';backups.mkdir();snapshot=backups/(storage.date.today().isoformat()+'.sqlite3')
            with sqlite3.connect(snapshot) as copy:db.backup(copy)
        original=snapshot.read_bytes()
        self.notes=storage.Store(old)
        note=self.notes.get('old-note')
        self.assertEqual((note['text'],note['revision'],note['archived'],note['secret']),('legacy plaintext',7,1,0))
        self.assertFalse(self.notes.has_pin());self.assertEqual(snapshot.read_bytes(),original)
        self.notes.set_pin('1234');self.notes.set_secret('old-note',True,7)
        self.assertEqual(snapshot.read_bytes(),original)
