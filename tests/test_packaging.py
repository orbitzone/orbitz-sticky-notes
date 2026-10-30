"""Exercise the installed tree without opening real notes or a display."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_installed_tree_is_self_contained_and_locale_override_works(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            subprocess.run(['make', 'install', 'PREFIX=/app', f'DESTDIR={stage}'],
                           cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            app = stage/'app/share/orbitz-sticky-notes'
            env = dict(os.environ, HOME=str(stage), XDG_DATA_HOME=str(stage/'data'),
                       GSETTINGS_BACKEND='memory', GSETTINGS_SCHEMA_DIR=str(stage/'app/share/glib-2.0/schemas'),
                       ORBITZ_LOCALE='en-US')
            env.pop('ORBITZ_I18N_DIR', None)
            code = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ui_language import ui
from storage import Store
assert ui.get_locale() == 'en-US'
assert ui.tr('sticky.title') != 'sticky.title'
store = Store(Path(sys.argv[2]))
try:
    assert store.create()['id']
finally:
    store.close()
'''
            subprocess.run(['/usr/bin/python3', '-c', code, str(app/'sticky-notes'), str(stage/'fixture')],
                           cwd=stage, env=env, check=True, capture_output=True)
            self.assertFalse((stage/'data/orbitz-postits').exists())
            env.pop('DISPLAY', None)
            result = subprocess.run([str(stage/'app/bin/orbitz-sticky-notes')],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('X11 or XWayland', result.stderr)

    def test_catalogs_cover_used_messages_and_have_matching_fields(self):
        import ast
        import string
        catalogs = [json.loads((ROOT/'i18n'/f'{locale}.json').read_text()) for locale in ('pt-BR', 'en-US')]
        self.assertEqual(set(catalogs[0]), set(catalogs[1]))
        for path in (ROOT/'sticky-notes').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    key = node.value
                    if key.startswith(('sticky.', 'domain.sticky_storage.')):
                        self.assertIn(key, catalogs[0], f'{path.name}: {key}')
        for key in catalogs[0]:
            fields = [set(field for _, field, _, _ in string.Formatter().parse(catalog[key]) if field)
                      for catalog in catalogs]
            self.assertEqual(*fields, key)

    def test_email_draft_cleanup_error_says_the_note_was_not_deleted(self):
        catalogs = {locale: json.loads((ROOT/'i18n'/f'{locale}.json').read_text())
                    for locale in ('pt-BR', 'en-US')}
        portuguese = catalogs['pt-BR']['sticky.email_cache_cleanup_failed'].format(error='cache unavailable')
        english = catalogs['en-US']['sticky.email_cache_cleanup_failed'].format(error='cache unavailable')
        self.assertIn('não foi excluída', portuguese)
        self.assertIn('cache unavailable', portuguese)
        self.assertNotIn('excluída, mas', portuguese)
        self.assertIn('was not deleted', english)
        self.assertIn('cache unavailable', english)
        self.assertNotIn('deleted, but', english)
