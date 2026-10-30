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
        names={'cancel_secret_timer','secret_activity','secret_enter','secret_leave','secret_tick','lock_secret','unlock_secret','toggle_secret','delete_note','authenticate_secret','show_secret_settings','sync_secret_menu_actions','authorize_secret_edit','set_property_value','restore_size','hide_note','close_requested'}
        ns=dict(GLib=self.glib,Gdk=self.gdk,ui=ui,sync_title_placeholder=Mock(),Gtk=SimpleNamespace(),
            purge_note_email_drafts=Mock())
        exec(compile(ast.Module(body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'card.py','exec'),ns)
        host=SimpleNamespace(alive=True,note={'id':'synthetic','secret':int(secret)},revision=4,secret_locked=False,secret_timer=0,secret_counting=False,secret_deadline=0,
            status=Mock(),secret_stack=Mock(),scroll=Mock(),title_field=Mock(),title_entry=Mock(),title_placeholder=Mock(),text=Mock(),unlock_button=Mock(),flush=Mock(return_value=True),clear_link_hover=Mock(),apply_color=Mock(),set_keep_above=Mock(),update_code_window_title=Mock(),sync_secret_badge=Mock(),save_geometry=Mock(),emoji_dialog=None,attachment_preview_cache={},
            auth_dialog=None,settings_dialog=None,secret_items=[],secret_syncing=False,app=SimpleNamespace(store=Mock(),get_windows=lambda:[]),get_visible=lambda:True,
            error=Mock(),destroy=Mock(),get_allocated_width=lambda:310,get_allocated_height=lambda:300)
        host.resolve_close_conflict=Mock(return_value=False)
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

    def test_locked_secret_rejects_property_change_when_pin_is_cancelled(self):
        host=self.host();host.secret_locked=True;host.authenticate_secret=Mock(return_value=False)
        self.assertFalse(host.set_property_value(color='#abcdef'))
        host.authenticate_secret.assert_called_once();host.app.store.properties.assert_not_called()

    def test_locked_secret_authenticates_before_changing_color_or_window_order(self):
        host=self.host();host.secret_locked=True;host.note['above']=0
        host.authenticate_secret=Mock(return_value=True);host.app.store.properties.return_value=None
        self.assertTrue(host.set_property_value(color='#abcdef'))
        host.authenticate_secret.assert_called_once()
        host.app.store.properties.assert_called_once_with('synthetic',color='#abcdef')
        host.apply_color.assert_called_once();host.set_keep_above.assert_called_once_with(False)
        second=self.host();second.secret_locked=True;second.note['above']=0;second.authenticate_secret=Mock(return_value=True)
        second.set_property_value(above=1)
        second.app.store.properties.assert_called_once_with('synthetic',above=1)
        second.authenticate_secret.assert_called_once()

    def test_locked_secret_menu_controls_are_disabled(self):
        host=self.host();host.secret_locked=True
        actions=[Mock() for _ in range(5)];host.secret_edit_menu_items=actions
        host.sync_secret_menu_actions()
        for action in actions:action.set_sensitive.assert_called_once_with(False)

    def test_locked_secret_editor_callbacks_cannot_save_body_or_title(self):
        host=self.host()
        tree=ast.parse((ROOT/'sticky-notes/card.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Card')
        names={'changed','document_changed','title_changed','flush'}
        namespace=dict(GLib=self.glib,sync_title_placeholder=Mock(),decode_document=lambda value:(value,[]))
        exec(compile(ast.Module(body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'card.py','exec'),namespace)
        host.secret_locked=True;host.loading=False;host.buffer=Mock();host.saved='original';host.saved_title='original title'
        host.dirty=True;host.title_dirty=True;host.title_entry=Mock();host.title_placeholder=Mock();host.value=Mock(return_value='tampered')
        host.restore_document=Mock();host.document_changed=MethodType(namespace['document_changed'],host)
        namespace['changed'](host)
        host.restore_document.assert_called_once_with('original');self.assertFalse(host.dirty)
        host.title_entry.get_text.return_value='tampered title';namespace['title_changed'](host)
        host.title_entry.set_text.assert_called_once_with('original title');self.assertFalse(host.title_dirty)
        self.assertTrue(namespace['flush'](host));host.app.store.text.assert_not_called();host.app.store.title.assert_not_called()

    def test_lock_clears_old_status_before_showing_lock_save_error(self):
        host=self.host();host.status.reset_mock();host.get_visible=lambda:False
        host.lock_secret()
        host.status.set_text.assert_any_call('')
        host.status.hide.assert_called()

    def test_hiding_secret_note_locks_synchronously_before_it_is_hidden(self):
        host=self.host();host.hide=Mock()
        calls=[]
        host.lock_secret=Mock(side_effect=lambda:calls.append('lock'))
        host.flush=Mock(side_effect=lambda:calls.append('flush') or True)
        host.hide.side_effect=lambda:calls.append('hide')
        self.assertTrue(host.hide_note())
        self.assertEqual(calls,['flush','lock','hide'])
        host.flush.side_effect=None;host.flush.return_value=False;calls.clear();host.lock_secret.reset_mock();host.hide.reset_mock()
        self.assertFalse(host.hide_note());self.assertEqual(calls,[])
        host.lock_secret.assert_not_called();host.hide.assert_not_called()

    def test_window_close_uses_the_same_secret_lock_path(self):
        host=self.host();host.hide_note=Mock(return_value=True)
        self.assertTrue(host.close_requested())
        host.hide_note.assert_called_once_with()

    def test_launcher_keeps_hidden_secret_hidden_while_another_note_is_visible(self):
        tree=ast.parse((ROOT/'sticky-notes/postits.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Postits')
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='activate_cards')
        namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),'postits.py','exec'),namespace)
        events=[]
        hidden=SimpleNamespace(note={'secret':1},get_visible=lambda:False,
            lock_secret=lambda:events.append('lock'),show=lambda:events.append('show'),present=lambda:events.append('present'))
        visible=SimpleNamespace(note={'secret':1},get_visible=lambda:True,
            lock_secret=Mock(),show=Mock(),present=Mock())
        app=SimpleNamespace(store=Mock(),get_windows=lambda:[hidden,visible])
        namespace['activate_cards'](app)
        # A hidden note stays hidden while another note is visible; the dropdown
        # remains its intentional reopen path. The launcher restores notes only
        # when all windows are hidden.
        self.assertEqual(events,[])
        visible.lock_secret.assert_not_called()
        visible.show.assert_called_once();visible.present.assert_called_once()

    def test_launcher_restores_all_hidden_notes_and_locks_secret_before_showing(self):
        tree=ast.parse((ROOT/'sticky-notes/postits.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Postits')
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='activate_cards')
        namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),'postits.py','exec'),namespace)
        events=[]
        hidden=SimpleNamespace(note={'secret':1},get_visible=lambda:False,
            lock_secret=lambda:events.append('lock'),show=lambda:events.append('show'),present=lambda:events.append('present'))
        app=SimpleNamespace(store=Mock(),get_windows=lambda:[hidden],fit_monitor=lambda _card,saved=False:events.append(('fit',saved)))
        namespace['activate_cards'](app)
        self.assertEqual(events,['lock',('fit',True),'show','present'])

    def test_locked_secret_screen_has_only_an_icon_unlock_control(self):
        source=(ROOT/'sticky-notes/card.py').read_text()
        self.assertIn("lock_image=secret_lock_icon()",source)
        self.assertIn("self.unlock_button=Gtk.Button()",source)
        self.assertIn("self.unlock_button.set_can_focus(True)",source)
        self.assertIn("self.unlock_button.add(lock_image)",source)
        self.assertIn("secret-pin.png",source)
        self.assertIn("install -m644 sticky-notes/*.png",(ROOT/'Makefile').read_text())
        self.assertNotIn("locked.pack_start(ui.widget(Gtk.Label,label=ui.msg('sticky.secret_note'))",source)
        self.assertNotIn("Gtk.Button,label=ui.msg('sticky.unlock')",source)

    def test_initial_secret_lock_survives_recursive_window_show_all(self):
        source=(ROOT/'sticky-notes/card.py').read_text()
        init=source[source.index('class Card(Gtk.ApplicationWindow):'):source.index('    def value(self):')]
        outer_show=init.index('overlay.show_all()')
        lock_select=init.index("self.secret_stack.set_visible_child_name('locked')")
        map_window=init.index('self.show()')
        self.assertLess(outer_show,lock_select);self.assertLess(lock_select,map_window)
        self.assertNotIn('outer.show_all()',init)
        self.assertNotIn('self.scroll.set_no_show_all',init)
        self.assertIn('self.attachments_box.set_no_show_all(True);self.attachments_box.hide()',init)
        unlock=source[source.index('    def unlock_secret(self):'):source.index('    def pin_entry(')]
        self.assertIn("self.secret_stack.set_visible_child_name('editor')",unlock)
        self.assertIn('self.scroll.show_all()',unlock)
        self.assertIn('self.attachments_box.set_no_show_all(False)',unlock)

    def test_disabling_secret_restores_stack_page_and_attachments_after_auth(self):
        source=(ROOT/'sticky-notes/card.py').read_text()
        cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='Card')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='toggle_secret')
        namespace={'sync_title_placeholder':Mock()};exec(compile(ast.Module(body=[method],type_ignores=[]),'card.py','exec'),namespace)
        host=self.host();host.secret_locked=True;host.note['secret']=1
        host.authenticate_secret=Mock(return_value=True);host.secret_activity=Mock()
        host.sync_secret_menu_actions=Mock();host.refresh_attachments=Mock();host.secret_items=[]
        host.attachments_box=Mock();host.app.store.set_secret.return_value=5
        check=Mock();check.get_active.return_value=False
        namespace['toggle_secret'](host,check)
        self.assertEqual(host.note['secret'],0);self.assertFalse(host.secret_locked)
        host.scroll.set_no_show_all.assert_not_called()
        host.secret_stack.set_visible_child_name.assert_called_with('editor')
        host.scroll.show_all.assert_called_once_with()
        host.attachments_box.set_no_show_all.assert_called_once_with(False)
        host.refresh_attachments.assert_called_once_with()

    def test_secret_pin_icon_loads_bundled_image(self):
        tree=ast.parse((ROOT/'sticky-notes/card.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='secret_lock_icon')
        gtk=SimpleNamespace(Image=SimpleNamespace(new_from_file=Mock(return_value='image')))
        namespace=dict(Gtk=gtk,Path=Path,__file__=str(ROOT/'sticky-notes/card.py'))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'card.py','exec'),namespace)
        namespace['secret_lock_icon']()
        gtk.Image.new_from_file.assert_called_once_with(str(ROOT/'sticky-notes/secret-pin.png'))
        import struct
        icon=(ROOT/'sticky-notes/secret-pin.png').read_bytes()
        self.assertEqual(icon[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II',icon[16:24]),(64,64))
        self.assertEqual(icon[25],6)  # RGBA transparency, with no baked background.

    def test_unlock_control_is_keyboard_focusable_without_mouse_hover_decoration(self):
        source=(ROOT/'sticky-notes/card.py').read_text()
        self.assertIn("self.unlock_button=Gtk.Button();self.unlock_button.set_name('sticky-secret-unlock-control')",source)
        self.assertIn('self.unlock_button.set_focus_on_click(False)',source)
        self.assertIn('self.unlock_button.set_can_focus(True)',source)
        self.assertIn("set_name',ui.msg('sticky.secret_unlock_accessible')",source)
        self.assertIn("set_description',ui.msg('sticky.secret_unlock_keyboard_help')",source)
        self.assertIn('button#sticky-secret-unlock-control:hover',source)
        self.assertIn('button#sticky-secret-unlock-control:focus',source)
        self.assertNotIn('unlock_button.grab_focus()',source)

    def test_unlock_control_sets_pointer_only_while_hovered_and_click_opens_pin(self):
        tree=ast.parse((ROOT/'sticky-notes/card.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Card')
        names={'unlock_pointer_enter','unlock_pointer_leave','unlock_pointer_click'}
        namespace=dict(Gdk=SimpleNamespace(Cursor=SimpleNamespace(new_from_name=Mock(return_value='pointer'))))
        exec(compile(ast.Module(body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'card.py','exec'),namespace)
        window=Mock();host=SimpleNamespace(get_window=Mock(return_value=window),get_display=Mock(return_value='display'))
        self.assertFalse(namespace['unlock_pointer_enter'](host));window.set_cursor.assert_called_once_with('pointer')
        window.set_cursor.reset_mock()
        self.assertFalse(namespace['unlock_pointer_leave'](host));window.set_cursor.assert_called_once_with(None)
        host.unlock_secret=Mock()
        self.assertTrue(namespace['unlock_pointer_click'](host,None));host.unlock_secret.assert_called_once_with()

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
        gtk=SimpleNamespace(Dialog=lambda **kw:dialog,Label=lambda **kw:Mock(),Box=lambda **kw:Mock(),Button=Mock(),
            ComboBoxText=LanguageCombo,Orientation=SimpleNamespace(HORIZONTAL=0,VERTICAL=1),ReliefStyle=SimpleNamespace(NONE=0),
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
        host.auth_dialog=Mock();host.settings_dialog=Mock()
        host.history_timer=0;host.geometry_timer=0
        tree=ast.parse((ROOT/'sticky-notes/card.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Card')
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='destroyed')
        ns=dict(GLib=self.glib);exec(compile(ast.Module(body=[node],type_ignores=[]),'card.py','exec'),ns)
        ns['destroyed'](host)
        self.assertFalse(host.alive);self.assertEqual(self.callbacks,{})
        host.auth_dialog.destroy.assert_called_once();host.settings_dialog.destroy.assert_called_once()

if __name__=='__main__':main()
