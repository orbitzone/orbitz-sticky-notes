"""Secret note UI state, crossings and PIN modals; no real windows or personal data."""
import ast
from pathlib import Path
from types import SimpleNamespace,MethodType
from unittest import TestCase,main
from unittest.mock import Mock
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'sticky-notes'))
from ui_language import ui

class SecretUiTests(TestCase):
    def host(self,secret=True):
        self.now=0;self.callbacks={};self.next_id=0
        def timeout(_ms,fn):
            self.next_id+=1;self.callbacks[self.next_id]=fn;return self.next_id
        self.glib=SimpleNamespace(get_monotonic_time=lambda:self.now,timeout_add=timeout,source_remove=lambda ident:self.callbacks.pop(ident,None))
        self.gdk=SimpleNamespace(CrossingMode=SimpleNamespace(NORMAL=0),NotifyType=SimpleNamespace(INFERIOR=2))
        tree=ast.parse((ROOT/'sticky-notes/card.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Card')
        names={'cancel_secret_timer','secret_activity','secret_enter','secret_leave','secret_tick','lock_secret','unlock_secret','toggle_secret','delete_note','authenticate_secret','show_secret_settings'}
        ns=dict(GLib=self.glib,Gdk=self.gdk,ui=ui,sync_title_placeholder=Mock())
        exec(compile(ast.Module(body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'card.py','exec'),ns)
        host=SimpleNamespace(alive=True,note={'id':'synthetic','secret':int(secret)},revision=4,secret_locked=False,secret_timer=0,secret_counting=False,secret_deadline=0,
            status=Mock(),secret_stack=Mock(),title_field=Mock(),title_entry=Mock(),title_placeholder=Mock(),text=Mock(),unlock_button=Mock(),flush=Mock(return_value=True),clear_link_hover=Mock(),emoji_dialog=None,
            auth_dialog=None,settings_dialog=None,secret_items=[],secret_syncing=False,app=SimpleNamespace(store=Mock(),get_windows=lambda:[]),get_visible=lambda:True,
            error=Mock(),destroy=Mock(),get_allocated_width=lambda:310,get_allocated_height=lambda:300)
        self.window=object();host.get_window=lambda:self.window
        for key in names:setattr(host,key,MethodType(ns[key],host))
        self.ns=ns
        return host

    def leave(self,host,**kw):
        event=SimpleNamespace(mode=0,detail=0,window=self.window,x=-1,y=100)
        for key,value in kw.items():setattr(event,key,value)
        host.secret_leave(None,event)

    def test_real_leave_counts_fifteen_seconds_and_locks_title_body_without_losing_edits(self):
        host=self.host();host.emoji_dialog=Mock();host.flush.return_value=False
        self.leave(host);self.assertEqual(host.secret_timer,1);self.assertEqual(host.secret_deadline,15000000)
        self.assertEqual(host.status.set_text.call_args.args,('Bloqueando em 15s',))
        self.now=14000000;self.assertTrue(host.secret_tick());self.assertEqual(host.status.set_text.call_args.args,('Bloqueando em 1s',))
        self.now=15000000;self.assertFalse(host.secret_tick());self.assertTrue(host.secret_locked)
        host.secret_stack.set_visible_child_name.assert_called_with('locked');host.title_field.hide.assert_called_once()
        host.text.set_sensitive.assert_called_with(False);host.title_entry.set_sensitive.assert_called_with(False)
        host.emoji_dialog.destroy.assert_called_once();host.destroy.assert_not_called();self.assertFalse(host.secret_counting)

    def test_child_crossings_and_grab_events_never_arm_a_timer(self):
        host=self.host()
        for kw in ({'detail':2},{'mode':1},{'window':object()},{'x':10,'y':10}):self.leave(host,**kw)
        self.assertEqual(host.secret_timer,0);self.assertEqual(self.callbacks,{})
        host.secret_locked=True;self.leave(host);self.assertEqual(host.secret_timer,0)

    def test_timer_is_single_and_enter_or_activity_cancels_it(self):
        host=self.host();self.leave(host);self.leave(host);self.assertEqual(len(self.callbacks),1)
        host.secret_enter(None,SimpleNamespace(mode=0,detail=0));self.assertEqual(host.secret_timer,0);self.assertEqual(self.callbacks,{})
        self.leave(host);host.secret_activity();self.assertEqual(self.callbacks,{})

    def test_expired_or_destroyed_callback_never_reveals_or_changes_storage(self):
        host=self.host();self.leave(host);host.alive=False;self.now=20000000
        self.assertFalse(host.secret_tick());host.app.store.text.assert_not_called();host.secret_stack.set_visible_child_name.assert_not_called()

    def test_unlock_requires_success_and_restores_editor_only_after_pin(self):
        host=self.host();host.lock_secret();host.authenticate_secret=Mock(return_value=False)
        host.unlock_secret();self.assertTrue(host.secret_locked)
        host.authenticate_secret.return_value=True;host.unlock_secret();self.assertFalse(host.secret_locked)
        host.secret_stack.set_visible_child_name.assert_called_with('editor');host.title_field.show_all.assert_called_once();host.text.grab_focus.assert_called_once()

    def test_every_delete_of_secret_requires_fresh_pin_even_when_revealed(self):
        host=self.host();host.authenticate_secret=Mock(return_value=False)
        self.assertFalse(host.delete_note());host.app.store.delete.assert_not_called()
        host.authenticate_secret.return_value=True;self.assertTrue(host.delete_note())
        host.app.store.delete.assert_called_once_with('synthetic',4);self.assertEqual(host.authenticate_secret.call_count,2)

    def test_secret_without_pin_routes_settings_and_cancel_does_not_change_note(self):
        host=self.host(False);host.app.store.has_pin.return_value=False;host.show_secret_settings=Mock(return_value=False)
        check=Mock();check.get_active.return_value=True;host.secret_items=[check]
        host.toggle_secret(check);host.app.store.set_secret.assert_not_called();check.set_active.assert_called_with(False)
        host.show_secret_settings.return_value=True;host.app.store.set_secret.return_value=5
        host.toggle_secret(check);host.app.store.set_secret.assert_called_once_with('synthetic',True,4)
        self.assertTrue(host.secret_locked);self.assertEqual(host.revision,5)

    def test_remove_secret_requires_pin_and_cas_failure_preserves_flag(self):
        host=self.host();host.authenticate_secret=Mock(return_value=False)
        check=Mock();check.get_active.return_value=False;host.secret_items=[check]
        host.toggle_secret(check);host.app.store.set_secret.assert_not_called();check.set_active.assert_called_with(True)
        host.authenticate_secret.return_value=True;host.app.store.set_secret.side_effect=ValueError('CAS')
        host.toggle_secret(check);self.assertEqual(host.note['secret'],1);host.error.assert_called_once()

    def modal(self,host,responses,values):
        dialog=Mock();dialog.run.side_effect=responses;entries=[]
        def pin_entry(_box,_label):
            entry=Mock();entry.get_text.side_effect=values[len(entries)];entries.append(entry);return entry
        host.pin_entry=pin_entry
        class LanguageCombo:
            def append(self,*_args):pass
            def set_active_id(self,value):self.active_id=value
            def get_active_id(self):return self.active_id
            def connect(self,*_args):pass
        gtk=SimpleNamespace(Dialog=lambda **kw:dialog,Label=lambda **kw:Mock(),Box=lambda **kw:Mock(),
            ComboBoxText=LanguageCombo,Orientation=SimpleNamespace(HORIZONTAL=0),
            ResponseType=SimpleNamespace(CANCEL=0,ACCEPT=1))
        self.ns['Gtk']=gtk
        return dialog,entries

    def test_auth_modal_locks_background_retries_wrong_pin_and_clears_entry(self):
        host=self.host();dialog,entries=self.modal(host,[1,1],[['1111','1234']])
        host.app.store.verify_pin.side_effect=[False,True]
        self.assertTrue(host.authenticate_secret());self.assertTrue(host.secret_locked)
        self.assertEqual([c.args[0] for c in host.app.store.verify_pin.call_args_list],['1111','1234'])
        self.assertEqual(entries[0].set_text.call_count,2);self.assertIsNone(host.auth_dialog);dialog.destroy.assert_called_once()

    def test_settings_initial_and_change_use_distinct_backend_contracts(self):
        host=self.host(False);host.app.store.has_pin.return_value=False
        dialog,entries=self.modal(host,[1],[['0000'],['0000']]);self.assertTrue(host.show_secret_settings())
        host.app.store.set_pin.assert_called_once_with('0000');host.app.store.change_pin.assert_not_called()
        host=self.host();host.app.store.has_pin.return_value=True
        dialog,entries=self.modal(host,[1],[['0000'],['1234'],['1234']]);self.assertTrue(host.show_secret_settings())
        host.app.store.change_pin.assert_called_once_with('0000','1234');host.app.store.set_pin.assert_not_called();self.assertTrue(host.secret_locked)

    def test_cancel_and_mismatch_never_write_a_pin(self):
        host=self.host(False);host.app.store.has_pin.return_value=False
        self.modal(host,[1,0],[['1234'],['9999']]);self.assertFalse(host.show_secret_settings());host.app.store.set_pin.assert_not_called()
        self.assertIsNone(host.settings_dialog)

    def test_cooldown_is_localized_and_auth_cancel_never_grants_access(self):
        host=self.host();dialog,entries=self.modal(host,[1,0],[['1111']])
        error=ValueError('not shown raw');error.retry_after=23
        host.app.store.verify_pin.side_effect=error
        self.assertFalse(host.authenticate_secret());self.assertTrue(host.secret_locked)
        self.assertIsNone(host.auth_dialog);host.app.store.delete.assert_not_called()
        self.assertEqual(ui.tr('sticky.pin_retry',seconds=23),'Muitas tentativas. Aguarde 23s antes de tentar novamente.')
        try:
            ui.refresh('en-US')
            self.assertEqual(ui.tr('sticky.secret_countdown',seconds=15),'Locking in 15s')
            self.assertIn('unencrypted',ui.tr('sticky.pin_limitation'))
        finally:ui.refresh('pt-BR')

    def test_destruction_removes_timer_and_closes_auth_and_settings(self):
        host=self.host();self.leave(host)
        host.auth_dialog=Mock();host.settings_dialog=Mock();host.app.end_note_drag=Mock()
        host.history_timer=0;host.geometry_timer=0
        tree=ast.parse((ROOT/'sticky-notes/card.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Card')
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='destroyed')
        ns=dict(GLib=self.glib);exec(compile(ast.Module(body=[node],type_ignores=[]),'card.py','exec'),ns)
        ns['destroyed'](host)
        self.assertFalse(host.alive);self.assertEqual(self.callbacks,{})
        host.auth_dialog.destroy.assert_called_once();host.settings_dialog.destroy.assert_called_once()

if __name__=='__main__':main()
