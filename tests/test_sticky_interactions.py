"""Synthetic GTK callbacks: no personal store, windows or destructive operations."""
import ast
from pathlib import Path
from types import SimpleNamespace,MethodType
from unittest import TestCase,main
from unittest.mock import Mock,call
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sticky-notes'))
from ui_language import ui

def methods(file,cls,names,namespace):
    tree=ast.parse((ROOT/'sticky-notes'/file).read_text())
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
    exec(compile(ast.Module(body=[n for n in node.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),file,'exec'),namespace)
    return namespace

class InteractionTests(TestCase):
    def test_formatted_document_round_trips_and_legacy_text_stays_plain(self):
        import json
        from card import RICH_TEXT_PREFIX
        tree=ast.parse((ROOT/'sticky-notes/card.py').read_text())
        functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in {'decode_document','encode_document'}]
        ns={'json':json,'RICH_TEXT_PREFIX':RICH_TEXT_PREFIX,'RICH_STYLES':('bold','italic','underline')}
        exec(compile(ast.Module(body=functions,type_ignores=[]),'card.py','exec'),ns)
        plain='legacy note';self.assertEqual(ns['encode_document'](plain,[]),plain)
        encoded=ns['encode_document']('Hello',[
            {'style':'bold','start':0,'end':5},{'style':'underline','start':1,'end':4}])
        self.assertEqual(ns['decode_document'](encoded),('Hello',[('bold',0,5),('underline',1,4)]))

    def test_format_shortcuts_are_handled_only_by_text_editor(self):
        key_names={98:'b',105:'i',117:'u',101:'e'}
        gdk=SimpleNamespace(ModifierType=SimpleNamespace(CONTROL_MASK=1),keyval_name=lambda key:key_names.get(key))
        ns=methods('card.py','Card',['text_format_key_press','key_press'],dict(Gdk=gdk))
        text=Mock();host=SimpleNamespace(secret_locked=False,text=text,toggle_format=Mock(return_value=True))
        for key,style in ((98,'bold'),(105,'italic'),(117,'underline')):
            self.assertTrue(ns['text_format_key_press'](host,text,SimpleNamespace(state=1,keyval=key)))
            host.toggle_format.assert_called_with(style)
        self.assertTrue(ns['text_format_key_press'](host,text,SimpleNamespace(state=1,keyval=101)))
        text.emit.assert_called_once_with('insert-emoji')
        app_host=SimpleNamespace(secret_locked=False,secret_activity=Mock(),app=Mock())
        self.assertFalse(ns['key_press'](app_host,None,SimpleNamespace(keyval=98,state=1)))

    def deletion(self,response=1):
        ns=methods('card.py','Card',['delete_note'],dict())
        host=SimpleNamespace(alive=True,flush=Mock(return_value=True),app=SimpleNamespace(store=Mock()),note={'id':'synthetic'},revision=7,destroy=Mock(),text=Mock(),error=Mock())
        return ns['delete_note'],host,None

    def test_delete_menu_action_deletes_immediately_after_save(self):
        fn,host,_=self.deletion();self.assertTrue(fn(host))
        self.assertEqual(host.flush.call_count,1);host.app.store.delete.assert_called_once_with('synthetic',7);host.destroy.assert_called_once()

    def test_delete_failed_cas_or_flush_preserves_window(self):
        fn,host,_=self.deletion();host.app.store.delete.side_effect=ValueError('conflict')
        self.assertFalse(fn(host));host.destroy.assert_not_called();host.error.assert_called_once()
        fn,host,_=self.deletion();host.flush.return_value=False
        self.assertFalse(fn(host));host.app.store.delete.assert_not_called()

    def test_title_and_text_save_in_revision_order_and_title_is_per_note(self):
        ns=methods('card.py','Card',['flush','title_changed'],dict())
        store=Mock();store.text.return_value=8;store.title.return_value=9
        host=SimpleNamespace(dirty=True,document_value=Mock(return_value='body'),value=Mock(return_value='body'),saved='old',revision=7,
            title_entry=Mock(),saved_title='',title_dirty=False,note={'id':'synthetic'},
            app=SimpleNamespace(store=store),status=Mock())
        host.title_entry.get_text.return_value='  Personal  '
        self.assertTrue(ns['flush'](host))
        self.assertEqual(store.mock_calls, [
            __import__('unittest').mock.call.text('synthetic','body',7),
            __import__('unittest').mock.call.title('synthetic','Personal',8)])
        self.assertEqual((host.revision,host.saved,host.saved_title,host.note['title']),(9,'body','Personal','Personal'))
        self.assertFalse(host.dirty);self.assertFalse(host.title_dirty);host.status.hide.assert_called_once()

    def test_title_persistence_error_keeps_unsaved_value_and_error_visible(self):
        ns=methods('card.py','Card',['flush'],dict())
        store=Mock();store.title.side_effect=OSError('purge-independent title failure')
        host=SimpleNamespace(dirty=False,saved_title='',title_dirty=False,title_entry=Mock(),revision=3,
            note={'id':'synthetic'},app=SimpleNamespace(store=store),status=Mock(),error=Mock())
        host.title_entry.get_text.return_value='Project'
        self.assertFalse(ns['flush'](host));self.assertTrue(host.title_dirty)
        host.error.assert_called_once();host.status.hide.assert_not_called()

    def test_menu_exposes_hide_archive_lists_and_direct_delete(self):
        ns=methods('card.py','Card',['add_options'],dict(ui=ui,Gtk=SimpleNamespace(Menu=lambda:Mock(),MenuItem=lambda **kw:Mock(),CheckMenuItem=lambda **kw:Mock(),SeparatorMenuItem=lambda:Mock()),NAMES=[],COLORS=[]))
        menu=Mock();host=Mock();host.note={'above':0}
        ns['add_options'](host,menu)
        source=(ROOT/'sticky-notes/card.py').read_text()
        self.assertIn("item(ui.msg('sticky.archive'),self.archive_note)",source)
        self.assertIn("ui.msg('sticky.show_hidden_notes')",source)
        self.assertIn("ui.msg('sticky.archived_notes')",source)
        self.assertNotIn("sticky.confirm_delete_permanent",source)
        self.assertIn("item(ui.msg('sticky.delete_note'),self.delete_note)",source)

    def test_header_menu_preserves_right_click(self):
        ns=methods('card.py','Card',['context_menu_press'],dict())
        source=(ROOT/'sticky-notes/card.py').read_text()
        self.assertIn('self.menu_button.set_popup(self.options_menu)',source)
        context=ast.get_source_segment(source,next(n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.FunctionDef) and n.name=='context_menu_press'))
        self.assertNotIn('self.begin_move_drag(',context)
        host=SimpleNamespace(options_menu=Mock())
        self.assertFalse(ns['context_menu_press'](host,None,SimpleNamespace(button=1)))
        host.options_menu.popup_at_pointer.assert_not_called()
        self.assertTrue(ns['context_menu_press'](host,None,SimpleNamespace(button=3)))
        host.options_menu.popup_at_pointer.assert_called_once()

    def test_top_handle_only_moves_note_with_window_manager(self):
        ns=methods('card.py','Card',['header_drag_press'],dict())
        app=Mock();host=SimpleNamespace(secret_activity=Mock(),authorize_secret_edit=Mock(return_value=True),
            app=app,begin_move_drag=Mock())
        event=SimpleNamespace(button=1,x_root=240,y_root=180,time=73)
        self.assertTrue(ns['header_drag_press'](host,None,event))
        host.secret_activity.assert_called_once_with()
        host.begin_move_drag.assert_called_once_with(1,240,180,73)
        host.authorize_secret_edit.return_value=False;host.begin_move_drag.reset_mock()
        self.assertTrue(ns['header_drag_press'](host,None,event));host.begin_move_drag.assert_not_called()

    def test_menu_has_no_drag_delete_help_item(self):
        source=(ROOT/'sticky-notes/card.py').read_text()
        self.assertNotIn('Shift+arraste',source)
        self.assertNotIn('Shift+drag',source)
        self.assertIn("item(ui.msg('sticky.delete_note'),self.delete_note)",source)

    def test_text_tooltips_are_removed_but_attachment_preview_is_kept(self):
        source=(ROOT/'sticky-notes/card.py').read_text()
        self.assertNotIn('set_tooltip_text',source)
        self.assertIn("button.connect('query-tooltip'",source)

    def test_desktop_activation_uses_gtk_application_routing_without_a_filesystem_lock(self):
        source=(ROOT/'sticky-notes/postits.py').read_text()
        self.assertIn("self.connect('activate',self.activate_cards)",source)
        self.assertIn('if not notes:notes=[self.store.create()]',source)
        self.assertNotIn('acquire_instance_lock',source)

    def test_escape_and_destroy_do_not_run_drag_cleanup(self):
        gdk=SimpleNamespace(keyval_name=lambda key:key,ModifierType=SimpleNamespace(CONTROL_MASK=4))
        glib=SimpleNamespace(source_remove=Mock())
        ns=methods('card.py','Card',['key_press','destroyed'],dict(Gdk=gdk,GLib=glib))
        host=SimpleNamespace(app=Mock(),alive=True,emoji_dialog=Mock(),history_timer=3,geometry_timer=4)
        self.assertFalse(ns['key_press'](host,None,SimpleNamespace(keyval='Escape',state=0)))
        ns['destroyed'](host)
        self.assertFalse(host.alive);host.emoji_dialog.destroy.assert_called_once()
        self.assertEqual([call.args[0] for call in glib.source_remove.call_args_list],[3,4])
        self.assertEqual((host.history_timer,host.geometry_timer),(0,0))

    def test_native_emoji_uses_roomy_transient_root_and_restores_saved_cursor(self):
        dialog=Mock();signals={};dialog.connect.side_effect=lambda name,fn:signals.update({name:fn})
        anchor=Mock();buffer_signals={};anchor.get_buffer.return_value.connect.side_effect=lambda name,fn:buffer_signals.update({name:fn})
        callbacks=[]
        gtk=SimpleNamespace(Dialog=lambda **kw:dialog,TextView=lambda:anchor,Align=SimpleNamespace(CENTER=1),ResponseType=SimpleNamespace(CANCEL=0))
        ns=methods('card.py','Card',['insert_emoji'],dict(Gtk=gtk,ui=ui,GLib=SimpleNamespace(idle_add=lambda fn:callbacks.append(fn)),Gdk=SimpleNamespace(keyval_name=lambda key:key)))
        host=SimpleNamespace(emoji_dialog=None,alive=True,buffer=Mock(),text=Mock(),present=Mock())
        editor=Mock();ns['insert_emoji'](host,editor)
        editor.stop_emission_by_name.assert_called_once_with('insert-emoji');dialog.set_default_size.assert_called_once_with(480,440)
        callbacks.pop(0)();anchor.grab_focus.assert_called_once();anchor.emit.assert_called_once_with('insert-emoji')
        chosen=Mock();chosen.get_text.return_value='😀';buffer_signals['changed'](chosen)
        host.buffer.insert.assert_called_once();signals['destroy'](dialog)
        host.buffer.place_cursor.assert_called_once();host.text.grab_focus.assert_called_once();host.buffer.delete_mark.assert_called_once()
        self.assertIsNone(host.emoji_dialog)

try:
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import Gtk,GLib,Gdk
    GTK_READY=Gtk.init_check()[0]
except (ImportError,ValueError):GTK_READY=False

from unittest import skipUnless
class NativeEmojiSmoke(TestCase):
    @skipUnless(GTK_READY,'GTK display unavailable; emoji focus/geometry requires local GTK3 session')
    def test_native_picker_maps_and_selection_returns_saved_cursor(self):
        ns=methods('card.py','Card',['insert_emoji'],dict(Gtk=Gtk,GLib=GLib,Gdk=Gdk,ui=ui))
        host=Gtk.Window();host.text=Gtk.TextView();host.add(host.text)
        host.buffer=host.text.get_buffer();host.buffer.set_text('AB')
        host.buffer.place_cursor(host.buffer.get_iter_at_offset(1));host.alive=True;host.emoji_dialog=None
        host.show_all()
        def drain():
            for _ in range(200):
                if not Gtk.events_pending():break
                Gtk.main_iteration_do(False)
        try:
            host.text.connect('insert-emoji',lambda editor:ns['insert_emoji'](host,editor))
            host.text.emit('insert-emoji');drain()
            dialog=host.emoji_dialog;self.assertTrue(dialog.get_mapped())
            self.assertGreaterEqual(dialog.get_allocated_width(),480)
            anchor=dialog.get_content_area().get_children()[0]
            self.assertTrue(anchor.get_mapped());self.assertEqual(anchor.get_opacity(),1)
            anchor.get_buffer().insert_at_cursor('😀');drain()
            self.assertIsNone(host.emoji_dialog)
            self.assertEqual(host.buffer.get_text(host.buffer.get_start_iter(),host.buffer.get_end_iter(),True),'A😀B')
            self.assertEqual(host.buffer.get_iter_at_mark(host.buffer.get_insert()).get_offset(),2)
            self.assertIs(host.get_focus(),host.text)
        finally:
            host.alive=False
            if host.emoji_dialog:host.emoji_dialog.destroy()
            host.destroy()

if __name__=='__main__':main()
