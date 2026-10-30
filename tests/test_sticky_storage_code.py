"""Sticky Code persistence and schema migration use isolated databases."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

os.environ.setdefault('GSETTINGS_BACKEND','memory')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sticky-notes'))
SPEC=importlib.util.spec_from_file_location('code_note_storage',ROOT/'sticky-notes/storage.py')
storage=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(storage)


class StickyCodeStorageTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        self.notes=storage.Store(self.root)
        self.addCleanup(self.notes.close)

    def test_atomic_mode_transition_preserves_content_and_geometry(self):
        note=self.notes.all()[0]
        revision=self.notes.transition_code_mode(note['id'],True,0,text='print(42)',title='Example',width=900,height=620)
        saved=self.notes.get(note['id'])
        self.assertEqual(revision,1)
        self.assertEqual((saved['text'],saved['title'],saved['code_mode'],saved['width'],saved['height']),
                         ('print(42)','Example',1,900,620))

        with self.assertRaises(ValueError):
            self.notes.transition_code_mode(note['id'],False,0,text='stale',title='Stale',width=310,height=300)
        self.assertEqual(self.notes.get(note['id']),saved)

    def test_transition_rejects_invalid_data_before_mutation(self):
        note=self.notes.all()[0]
        cases=(
            dict(text=None,title='Valid',width=310,height=300),
            dict(text='Valid',title='x'*201,width=310,height=300),
            dict(text='x'*100001,title='Valid',width=310,height=300),
            dict(text='Valid',title='Valid',width=True,height=300),
            dict(text='Valid',title='Valid',width=310,height=0),
        )
        for values in cases:
            with self.subTest(values=values),self.assertRaises(ValueError):
                self.notes.transition_code_mode(note['id'],True,0,**values)
            self.assertEqual(self.notes.get(note['id']),note)

    def test_language_update_is_allowlisted_and_revision_checked(self):
        note=self.notes.all()[0]
        self.assertEqual(self.notes.set_code_language(note['id'],'rust',0),1)
        saved=self.notes.get(note['id'])
        self.assertEqual((saved['code_language'],saved['revision']),('rust',1))
        for invalid in ('Python','bash','javascript; DROP TABLE notes',None):
            with self.subTest(language=invalid),self.assertRaises(ValueError):
                self.notes.set_code_language(note['id'],invalid,1)
        with self.assertRaises(ValueError):self.notes.set_code_language(note['id'],'python',0)
        self.assertEqual(self.notes.get(note['id']),saved)

    def test_opacity_is_a_boolean_note_property(self):
        note=self.notes.all()[0]
        self.notes.properties(note['id'],reduced_opacity=1)
        self.assertEqual(self.notes.get(note['id'])['reduced_opacity'],1)
        for invalid in (-1,2,True,'1'):
            with self.subTest(value=invalid),self.assertRaises(ValueError):
                self.notes.properties(note['id'],reduced_opacity=invalid)
        self.assertEqual(self.notes.get(note['id'])['reduced_opacity'],1)

    def test_legacy_schema_receives_sticky_code_defaults(self):
        self.notes.close()
        old=self.root/'legacy';old.mkdir();path=old/'notes.sqlite3'
        with sqlite3.connect(path) as db:
            db.executescript("""
                CREATE TABLE notes(id TEXT PRIMARY KEY,text TEXT NOT NULL,color TEXT NOT NULL,
                    x INTEGER DEFAULT 100,y INTEGER DEFAULT 100,width INTEGER DEFAULT 310,
                    height INTEGER DEFAULT 300,above INTEGER DEFAULT 0,revision INTEGER DEFAULT 0,
                    archived INTEGER DEFAULT 0);
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT INTO metadata VALUES('imported','1');
                INSERT INTO notes(id,text,color) VALUES('legacy','existing','#ffe293');
            """)
        self.notes=storage.Store(old)
        self.assertEqual(self.notes.get('legacy')['code_mode'],0)
        self.assertEqual(self.notes.get('legacy')['reduced_opacity'],0)
        self.assertEqual(self.notes.get('legacy')['code_language'],'python')
        self.assertEqual(self.notes.get('legacy')['text'],'existing')


if __name__=='__main__':unittest.main()
