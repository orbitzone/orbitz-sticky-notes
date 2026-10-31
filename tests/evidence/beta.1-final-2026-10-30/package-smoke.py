"""Run with the release Flatpak Python, private D-Bus and synthetic app data."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
sys.path.insert(0,'/app/share/orbitz-sticky-notes/sticky-notes')
from storage import Store
from postits import Postits
from gi.repository import Gtk

with tempfile.TemporaryDirectory(prefix='orbitz-beta-qa-') as temporary:
    root=Path(temporary)
    store=Store(root/'notes')
    note=store.all()[0]
    revision=store.title(note['id'],'Final beta synthetic QA',note['revision'])
    store.text(note['id'],'Persistent synthetic note body\n'*30,revision)
    store.properties(note['id'],x=180,y=140,width=390,height=340)
    source=root/'synthetic.txt';source.write_text('durable attachment after original removal')
    attachment=store.add_attachment(note['id'],source)
    source.unlink();store.close()
    store=Store(root/'notes')
    assert Path(store.attachments(note['id'])[0]['path']).read_text()=='durable attachment after original removal'
    assert store.get(note['id'])['x']==180
    assert store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    app=Postits(store)
    assert app.register(None)
    app.activate_cards()
    def pump():
        while Gtk.events_pending():Gtk.main_iteration_do(False)
    pump()
    windows=app.get_windows();assert len(windows)==1
    card=windows[0];assert card.get_visible()
    command=lambda action:app.command_line(app,SimpleNamespace(get_arguments=lambda:['postits',action]))
    command('--close-notes');pump();assert not card.get_visible()
    command('--open-hidden-notes');pump();assert card.get_visible()
    print(json.dumps({'attachment_after_original_removal':'passed','database_integrity':'ok','gtk_note_mapping':'passed','close_and_open_hidden':'passed','runtime':Gtk.get_major_version()}),flush=True)
    if os.environ.get('ORBITZ_QA_HOLD'):
        import time
        until=time.monotonic()+15
        while time.monotonic()<until:pump();time.sleep(.05)
    for window in list(app.get_windows()):window.destroy()
    app.shutdown_cards()
