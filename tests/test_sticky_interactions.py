"""Synthetic GTK callbacks: no personal store, windows or destructive operations."""
import ast
from pathlib import Path
from types import SimpleNamespace,MethodType
from unittest import TestCase,main
from unittest.mock import Mock
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
    def deletion(self,response=1):
        dialog=Mock();dialog.run.return_value=response
        gtk=SimpleNamespace(MessageDialog=lambda **kw:dialog,MessageType=SimpleNamespace(WARNING=0),ButtonsType=SimpleNamespace(NONE=0),ResponseType=SimpleNamespace(CANCEL=0,ACCEPT=1))
        ns=methods('card.py','Card',['delete_note'],dict(Gtk=gtk,ui=ui))
        host=SimpleNamespace(alive=True,flush=Mock(return_value=True),app=SimpleNamespace(store=Mock()),note={'id':'synthetic'},revision=7,destroy=Mock(),present=Mock(),text=Mock(),error=Mock())
        return ns['delete_note'],host,dialog

    def test_delete_ack_removes_window_only_after_cas_success(self):
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
        host=SimpleNamespace(dirty=True,value=Mock(return_value='body'),saved='old',revision=7,
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

    def test_menu_exposes_delete_without_archive_or_restore(self):
        ns=methods('card.py','Card',['add_options'],dict(ui=ui,Gtk=SimpleNamespace(Menu=lambda:Mock(),MenuItem=lambda **kw:Mock(),CheckMenuItem=lambda **kw:Mock(),SeparatorMenuItem=lambda:Mock()),NAMES=[],COLORS=[]))
        menu=Mock();host=Mock();host.note={'above':0}
        ns['add_options'](host,menu)
        host.app.store.all.assert_not_called()
        source=(ROOT/'sticky-notes/card.py').read_text()
        self.assertNotIn("ui.msg('sticky.archive')",source);self.assertNotIn("ui.msg('sticky.restore_archive')",source)
        self.assertIn("item(ui.msg('sticky.delete_note'),self.delete_note)",source)

    def test_header_menu_replaces_custom_drag_and_preserves_right_click(self):
        ns=methods('card.py','Card',['context_menu_press'],dict())
        source=(ROOT/'sticky-notes/card.py').read_text()
        self.assertIn('self.menu_button.set_popup(self.options_menu)',source)
        context=ast.get_source_segment(source,next(n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.FunctionDef) and n.name=='context_menu_press'))
        self.assertNotIn('self.begin_move_drag(',context)
        self.assertNotIn('self.app.begin_note_drag(self)',context)
        host=SimpleNamespace(options_menu=Mock())
        self.assertFalse(ns['context_menu_press'](host,None,SimpleNamespace(button=1)))
        host.options_menu.popup_at_pointer.assert_not_called()
        self.assertTrue(ns['context_menu_press'](host,None,SimpleNamespace(button=3)))
        host.options_menu.popup_at_pointer.assert_called_once()

    def test_trash_gesture_is_shift_drag_from_empty_bottom_margin_only(self):
        ns=methods('card.py','Card',['trash_drag_press','trash_drag_region'],
            dict(Gdk=SimpleNamespace(ModifierType=SimpleNamespace(SHIFT_MASK=1))))
        host=SimpleNamespace(get_position=lambda:(100,200),get_size=lambda:(310,300))
        region=ns['trash_drag_region']
        self.assertTrue(region(host,SimpleNamespace(x_root=220,y_root=470)))
        self.assertFalse(region(host,SimpleNamespace(x_root=220,y_root=450)))
        self.assertFalse(region(host,SimpleNamespace(x_root=390,y_root=470)))
        host.trash_drag_region=Mock(return_value=True);host.app=Mock();host.app.begin_note_drag.return_value=True
        host.begin_move_drag=Mock();event=SimpleNamespace(button=1,state=1,x_root=220,y_root=470,time=42)
        self.assertTrue(ns['trash_drag_press'](host,None,event))
        host.app.begin_note_drag.assert_called_once_with(host)
        host.begin_move_drag.assert_called_once_with(1,220,470,42)
        event.state=0
        self.assertFalse(ns['trash_drag_press'](host,None,event))
        self.assertEqual(host.app.begin_note_drag.call_count,1)

    def test_menu_describes_drag_gesture_and_delete_fallback(self):
        source=(ROOT/'sticky-notes/card.py').read_text()
        self.assertIn("ui.msg('sticky.trash_drag_hint')",source)
        self.assertIn("item(ui.msg('sticky.delete_note'),self.delete_note)",source)

    def test_menu_hides_note_tooltips_until_popup_closes(self):
        ns=methods('card.py','Card',['menu_opened','menu_closed'],dict())
        title=Mock();body=Mock();grip=Mock()
        host=SimpleNamespace(menu_tooltips=[(title,'Edit title'),(body,'Open link'),(grip,None)])
        ns['menu_opened'](host)
        for widget in (title,body,grip):widget.set_tooltip_text.assert_called_once_with(None)
        ns['menu_closed'](host)
        title.set_tooltip_text.assert_called_with('Edit title')
        body.set_tooltip_text.assert_called_with('Open link')
        self.assertEqual(grip.set_tooltip_text.call_count,1)

    def test_drag_release_inside_deletes_once_and_failure_restores_position(self):
        callbacks=[];glib=SimpleNamespace(source_remove=Mock(),idle_add=lambda fn:callbacks.append(fn))
        ns=methods('postits.py','Postits',['end_note_drag'],dict(GLib=glib))
        card=SimpleNamespace(alive=True,delete_note=Mock(return_value=False),move=Mock())
        popup=Mock();host=SimpleNamespace(drag_card=card,drag_origin=(40,60),drag_timer=9,trash_window=popup)
        ns['end_note_drag'](host,True);popup.destroy.assert_called_once();glib.source_remove.assert_called_once_with(9)
        popup.get_window.return_value.set_cursor.assert_called_once_with(None)
        card.delete_note.assert_not_called();self.assertIsNone(host.drag_card)
        self.assertFalse(callbacks[0]());card.delete_note.assert_called_once();card.move.assert_called_once_with(40,60)

    def test_cancel_or_other_card_destruction_never_deletes(self):
        glib=SimpleNamespace(source_remove=Mock(),idle_add=Mock())
        ns=methods('postits.py','Postits',['end_note_drag'],dict(GLib=glib))
        card=Mock();host=SimpleNamespace(drag_card=card,drag_timer=0,trash_window=Mock())
        ns['end_note_drag'](host,False,Mock());self.assertIs(host.drag_card,card)
        ns['end_note_drag'](host,False);card.delete_note.assert_not_called();glib.idle_add.assert_not_called()

    def test_drag_hit_target_matches_popup_geometry_and_release_state(self):
        pointer=Mock();pointer.get_position.return_value=(Mock(),500,650)
        pointer.get_position.return_value[0].get_root_window.return_value.get_device_position.return_value=(None,500,650,0)
        display=Mock();display.get_default_seat.return_value.get_pointer.return_value=pointer
        display.get_monitor_at_point.return_value.get_workarea.return_value=SimpleNamespace(x=0,y=0,width=1000,height=720)
        gdk=SimpleNamespace(Display=SimpleNamespace(get_default=lambda:display),ModifierType=SimpleNamespace(BUTTON1_MASK=1))
        ns=methods('postits.py','Postits',['track_note_drag'],dict(Gdk=gdk))
        popup=Mock();popup.get_size.return_value=(200,90);popup.get_position.return_value=(400,606)
        host=SimpleNamespace(drag_card=SimpleNamespace(alive=True),trash_window=popup,end_note_drag=Mock())
        host.trash_cursor=object()
        self.assertFalse(ns['track_note_drag'](host));popup.move.assert_called_once_with(400,606);host.end_note_drag.assert_called_once_with(True)
        popup.get_window.return_value.set_cursor.assert_called_once_with(host.trash_cursor)
        pointer.get_position.return_value=(pointer.get_position.return_value[0],10,10)
        self.assertFalse(ns['track_note_drag'](host));self.assertEqual(host.end_note_drag.call_args.args,(False,))
        self.assertEqual(popup.get_window.return_value.set_cursor.call_args.args,(None,))

    def test_escape_and_destroy_cancel_drag_and_clean_timers(self):
        gdk=SimpleNamespace(keyval_name=lambda key:key,ModifierType=SimpleNamespace(CONTROL_MASK=4))
        glib=SimpleNamespace(source_remove=Mock())
        ns=methods('card.py','Card',['key_press','destroyed'],dict(Gdk=gdk,GLib=glib))
        host=SimpleNamespace(app=Mock(),alive=True,emoji_dialog=Mock(),history_timer=3,geometry_timer=4)
        self.assertFalse(ns['key_press'](host,None,SimpleNamespace(keyval='Escape',state=0)))
        host.app.end_note_drag.assert_called_once_with(False)
        ns['destroyed'](host)
        self.assertFalse(host.alive);host.emoji_dialog.destroy.assert_called_once()
        host.app.end_note_drag.assert_called_with(False,host)
        self.assertEqual([call.args[0] for call in glib.source_remove.call_args_list],[3,4])
        self.assertEqual((host.history_timer,host.geometry_timer),(0,0))

    def test_native_wayland_does_not_poll_unsupported_root_coordinates(self):
        display=SimpleNamespace(__gtype__=SimpleNamespace(name='GdkWaylandDisplay'))
        gdk=SimpleNamespace(Display=SimpleNamespace(get_default=lambda:display))
        ns=methods('postits.py','Postits',['begin_note_drag'],dict(Gdk=gdk,ui=ui))
        host=SimpleNamespace(end_note_drag=Mock());card=SimpleNamespace(status=Mock())
        self.assertFalse(ns['begin_note_drag'](host,card))
        host.end_note_drag.assert_called_once_with(False);card.status.show.assert_called_once()
        self.assertFalse(hasattr(host,'drag_timer'))

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
