"""Sticky editor layout contracts and optional GTK smoke; never opens personal notes."""
import ast
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'i18n'))
import ui_i18n as ui

SOURCE=Path(__file__).resolve().parents[1]/'sticky-notes/card.py'
TREE=ast.parse(SOURCE.read_text())
EDITOR=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='editor_scroll')
TITLE_PLACEHOLDER=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='sync_title_placeholder')
CARD=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=='Card')
COLOR=next(n for n in CARD.body if isinstance(n,ast.FunctionDef) and n.name=='apply_color')

def functions(gtk):
    namespace={'Gtk':gtk,'ui':ui,'NOTE_CORNER_RADIUS':10}
    exec(compile(ast.Module(body=[EDITOR,TITLE_PLACEHOLDER,COLOR],type_ignores=[]),str(SOURCE),'exec'),namespace)
    return namespace

try:
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import Gtk
except (ImportError,ValueError):
    Gtk=None

class StickyLayoutTests(unittest.TestCase):
    def test_note_and_code_editors_and_language_picker_have_accessible_names(self):
        source=SOURCE.read_text()
        self.assertIn("ui.call(self.text.get_accessible(),'set_name',ui.msg('sticky.code_editor' if self.code_mode else 'sticky.note_content'))",source)
        self.assertIn("ui.call(self.code_language_combo.get_accessible(),'set_name',ui.msg('sticky.code_language'))",source)
        self.assertIn('language_label.set_mnemonic_widget(self.code_language_combo)',source)
        previous=ui.get_locale();self.addCleanup(ui.refresh,previous);ui.refresh('pt-BR')
        self.assertEqual(ui.tr('sticky.code_editor'),'Editor de código')
        self.assertEqual(ui.tr('sticky.note_content'),'Conteúdo da nota')

    def test_title_placeholder_stays_visible_until_first_character(self):
        entry=Mock();placeholder=Mock();entry.get_text.side_effect=['','Orbitz','']
        sync=functions(None)['sync_title_placeholder']
        sync(entry,placeholder);placeholder.set_visible.assert_called_with(True)
        sync(entry,placeholder);placeholder.set_visible.assert_called_with(False)
        sync(entry,placeholder);placeholder.set_visible.assert_called_with(True)

    def test_title_placeholder_is_translated_overlay_that_passes_input_through(self):
        calls=[node for node in ast.walk(CARD) if isinstance(node,ast.Call)
            and isinstance(node.func,ast.Attribute) and node.func.attr=='widget'
            and isinstance(node.func.value,ast.Name) and node.func.value.id=='ui'
            and node.args and isinstance(node.args[0],ast.Attribute)
            and node.args[0].attr=='Label']
        translated=[node for node in calls if any(keyword.arg=='label' and isinstance(keyword.value,ast.Call)
            and isinstance(keyword.value.func,ast.Attribute) and keyword.value.func.attr=='msg'
            and keyword.value.args and isinstance(keyword.value.args[0],ast.Constant)
            and keyword.value.args[0].value=='sticky.title' for keyword in node.keywords)]
        self.assertEqual(len(translated),1)
        wired=any(isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
            and node.func.attr=='set_overlay_pass_through' and node.args
            and isinstance(node.args[0],ast.Attribute) and node.args[0].attr=='title_placeholder'
            for node in ast.walk(CARD))
        self.assertTrue(wired)
        changed=next(node for node in CARD.body if isinstance(node,ast.FunctionDef) and node.name=='title_changed')
        self.assertTrue(any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
            and node.func.id=='sync_title_placeholder' for node in ast.walk(changed)))

    def test_editor_uses_overflow_scrollbar_without_requesting_content_height(self):
        scroll=Mock();bar=scroll.get_vscrollbar.return_value;text=Mock()
        gtk=SimpleNamespace(ScrolledWindow=lambda:scroll,PolicyType=SimpleNamespace(NEVER=0,AUTOMATIC=1),
            ScrollablePolicy=SimpleNamespace(MINIMUM=0),ShadowType=SimpleNamespace(NONE=0))
        result=functions(gtk)['editor_scroll'](text)
        self.assertEqual(result,(scroll,bar))
        scroll.set_policy.assert_called_once_with(0,1)
        scroll.set_overlay_scrolling.assert_called_once_with(False)
        scroll.set_propagate_natural_height.assert_called_once_with(False)
        bar.set_opacity.assert_called_once_with(1.0)
        bar.hide.assert_not_called();bar.set_size_request.assert_not_called()
        scroll.add.assert_called_once_with(text)

    def test_resize_grip_has_large_edge_target_and_uses_resize_cursor(self):
        node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='resize_grip')
        grip=Mock();icon=Mock();cursor=Mock();callback=Mock();signals={}
        grip.connect.side_effect=lambda name,handler:signals.update({name:handler})
        gtk=SimpleNamespace(Button=lambda:grip,ReliefStyle=SimpleNamespace(NONE=0),Label=lambda **kw:icon,Align=SimpleNamespace(END=1))
        namespace=dict(ui=ui,Gtk=gtk,Gdk=SimpleNamespace(Cursor=SimpleNamespace(new_from_name=cursor)))
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),namespace)
        self.assertIs(namespace['resize_grip'](callback),grip)
        grip.set_relief.assert_called_once_with(0);grip.set_focus_on_click.assert_called_once_with(False)
        grip.set_can_focus.assert_called_once_with(True)
        grip.set_size_request.assert_called_once_with(28,28)
        grip.set_margin_end.assert_called_once_with(2);grip.set_margin_bottom.assert_called_once_with(2)
        grip.set_above_child.assert_not_called()
        source=SOURCE.read_text()
        self.assertIn('overlay.add_overlay(grip);overlay.set_overlay_pass_through(grip,False)',source)
        self.assertIs(signals['button-press-event'],callback)
        signals['realize'](grip)
        cursor.assert_called_once_with(grip.get_display.return_value,'se-resize')
        grip.get_window.return_value.set_cursor.assert_called_once_with(cursor.return_value)

    def test_keyboard_geometry_controls_have_accessible_names_descriptions_and_keyboard_only_focus_style(self):
        source=SOURCE.read_text()
        self.assertIn("self.move_handle.connect('key-press-event',self.keyboard_geometry_key_press,'move')",source)
        self.assertIn("grip.connect('key-press-event',self.keyboard_geometry_key_press,'resize')",source)
        self.assertIn("set_description',ui.msg('sticky.keyboard_move_help')",source)
        self.assertIn("set_description',ui.msg('sticky.keyboard_resize_help')",source)
        self.assertIn("button#sticky-note-move-handle:hover, button#sticky-note-resize-grip:hover, button#sticky-secret-unlock-control:hover",source)
        self.assertIn("button#sticky-note-move-handle:focus, button#sticky-note-resize-grip:focus, button#sticky-secret-unlock-control:focus",source)
        self.assertIn('outline:none;border-radius:3px',source)

    def test_resize_drag_uses_pointer_position_and_preserves_other_buttons(self):
        node=next(n for n in CARD.body if isinstance(n,ast.FunctionDef) and n.name=='resize_press')
        namespace=dict(Gdk=SimpleNamespace(WindowEdge=SimpleNamespace(SOUTH_EAST=8)))
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),namespace)
        host=Mock();event=SimpleNamespace(button=1,x_root=123.7,y_root=456.8,time=99)
        self.assertTrue(namespace['resize_press'](host,None,event))
        host.begin_resize_drag.assert_called_once_with(8,1,123,456,99)
        event.button=3;self.assertFalse(namespace['resize_press'](host,None,event))
        self.assertEqual(host.begin_resize_drag.call_count,1)

    @unittest.skipIf(Gtk is None,'GTK3 unavailable')
    def test_css_parses_in_gtk_without_theme_errors(self):
        provider=Gtk.CssProvider();errors=[]
        provider.connect('parsing-error',lambda _,section,error:errors.append(str(error)))
        host=SimpleNamespace(note={'color':'#ffdda8'},css=provider,code_mode=False,set_opacity=Mock())
        functions(Gtk)['apply_color'](host)
        host.set_opacity.assert_called_once_with(1.0)
        self.assertEqual(errors,[])

    @unittest.skipUnless(Gtk and Gtk.init_check()[0],'GTK display unavailable; run locally for geometry smoke')
    def test_long_text_scrolls_without_growing_card_or_removing_bar(self):
        helper=functions(Gtk);host=Gtk.OffscreenWindow();host.set_default_size(310,300)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12,margin=18);host.add(box)
        box.pack_start(Gtk.Label(label='STICKY NOTES'),False,False,0)
        text=Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR);text.set_name('sticky-note-text')
        scroll,bar=helper['editor_scroll'](text);box.pack_start(scroll,True,True,0)
        box.pack_end(Gtk.Label(label='◢'),False,False,0)
        css=Gtk.CssProvider();helper['apply_color'](SimpleNamespace(note={'color':'#ffdda8'},css=css,set_opacity=Mock(),code_mode=False))
        for widget in (host,box,text,scroll,bar):
            widget.get_style_context().add_provider(css,Gtk.STYLE_PROVIDER_PRIORITY_USER)
        def drain():
            # Layout/scrollbar unmapping is scheduled by GTK's frame clock.
            # An empty event queue does not mean the next frame has run yet.
            from gi.repository import GLib
            loop=GLib.MainLoop()
            GLib.timeout_add(200,lambda:loop.quit() or False)
            loop.run()
        try:
            text.get_buffer().set_text('Texto curto');host.show_all();drain()
            initial=host.get_size();self.assertFalse(bar.get_mapped())
            text.get_buffer().set_text(('Linha longa de teste com conteúdo sintético.\n')*1000);drain()
            self.assertEqual(host.get_size(),initial)
            self.assertTrue(bar.get_mapped());self.assertEqual(bar.get_opacity(),1)
            self.assertGreater(bar.get_allocated_width(),0)
            adjustment=scroll.get_vadjustment()
            self.assertGreater(adjustment.get_upper(),adjustment.get_page_size())
            adjustment.set_value(adjustment.get_upper()-adjustment.get_page_size());drain()
            self.assertGreater(adjustment.get_value(),0)
            adjustment.set_value(0);self.assertEqual(adjustment.get_value(),0)
            text.get_buffer().set_text('test 2');drain()
            self.assertFalse(bar.get_mapped());self.assertEqual(host.get_size(),initial)
        finally:host.destroy()

if __name__=='__main__':unittest.main()
