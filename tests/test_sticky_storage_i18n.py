"""Localized note errors with temporary SQLite only; no GTK or installed data."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sticky-notes'))
SPEC=importlib.util.spec_from_file_location('localized_note_storage',ROOT/'sticky-notes/storage.py')
storage=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(storage)
from ui_language import ui


class StickyStorageLocaleTests(unittest.TestCase):
    def setUp(self):
        previous=ui.get_locale();self.addCleanup(ui.refresh,previous);ui.refresh('en-US')
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)

    def failure(self,callback,text):
        with self.assertRaises(ValueError) as result:callback()
        self.assertIs(type(result.exception),ValueError)
        self.assertEqual(result.exception.args,(text,))

    def test_validation_and_conflict_preserve_note_text_revision_and_properties(self):
        notes=storage.Store(self.root/'notes');self.addCleanup(notes.close)
        note=notes.all()[0];identity=note['id']
        text='Cor inválida. {name} Conteúdo do usuário'
        self.assertEqual(notes.text(identity,text,0),1)
        before=notes.get(identity)
        cases=[(lambda:notes.text(identity,'overwrite',0),'The note was changed by another process. Copy the text before reloading.'),
               (lambda:notes.text(identity,'x'*100001,1),'Limit of 100,000 characters per note.'),
               (lambda:notes.properties(identity,invalid=1),'Invalid property.'),
               (lambda:notes.properties(identity,color='invalid'),'Invalid color.'),
               (lambda:notes.properties(identity,width='wide'),'Invalid dimension.')]
        for callback,message in cases:
            self.failure(callback,message)
            self.assertEqual(notes.get(identity),before)
        self.assertEqual(notes.get(identity)['text'],text)
        self.assertEqual(notes.get(identity)['revision'],1)

    def test_missing_note_switches_language_without_database_mutation(self):
        notes=storage.Store(self.root/'notes');self.addCleanup(notes.close)
        before=notes.all()
        self.failure(lambda:notes.get('missing'),'Note not found.')
        ui.refresh('pt-BR')
        self.failure(lambda:notes.get('missing'),'Nota não encontrada.')
        self.assertEqual(notes.all(),before)

    def test_existing_error_has_live_metadata_and_builtin_string_args(self):
        notes=storage.Store(self.root/'notes');self.addCleanup(notes.close)
        with self.assertRaises(ValueError) as result:notes.get('missing')
        error=result.exception;args=error.args;display=ui.error_message(error)
        self.assertIs(type(error),ValueError)
        self.assertIs(type(args[0]),str)
        ui.refresh('pt-BR')
        self.assertEqual(str(display),'Nota não encontrada.')
        self.assertEqual(error.args,args)
        self.assertEqual(str(error),'Note not found.')
        ui.refresh('en-US')
        self.assertEqual(str(display),'Note not found.')

    def test_invalid_database_check_preserves_error_type_and_stops_before_schema(self):
        db=Mock();db.execute.return_value.fetchone.return_value=('broken',)
        with patch.object(storage.sqlite3,'connect',return_value=db),patch.object(storage.os,'chmod'):
            self.failure(lambda:storage.Store(self.root/'notes'),'Invalid notes database. The files were preserved.')
        db.executescript.assert_not_called()

    def test_invalid_legacy_note_preserves_original_and_inserts_no_note(self):
        legacy=self.root/'legacy.json';legacy.write_text(json.dumps({'notes':None}));before=legacy.read_bytes()
        connections=[];connect=sqlite3.connect
        def track(*args,**kwargs):
            db=connect(*args,**kwargs);connections.append(db);return db
        try:
            with patch.object(storage.sqlite3,'connect',side_effect=track):
                self.failure(lambda:storage.Store(self.root/'notes',legacy),'Invalid legacy note. The original was preserved.')
            self.assertEqual(legacy.read_bytes(),before)
            self.assertEqual(connections[0].execute('SELECT count(*) FROM notes').fetchone()[0],0)
        finally:
            for db in connections:db.close()
