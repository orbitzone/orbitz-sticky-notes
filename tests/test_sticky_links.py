"""Synthetic note destinations and Ctrl+click routing, without real app launches."""
import ast
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace,MethodType
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sticky-notes'))
import link_targets
from link_targets import target_at,link_at
from ui_language import ui

class StickyLinkTests(unittest.TestCase):
    def test_web_email_and_exact_clicked_destination(self):
        text='Abrir https://example.org/test?q=1 e pessoa@example.org.'
        self.assertEqual(target_at(text,text.index('example.org')),'https://example.org/test?q=1')
        self.assertEqual(target_at(text,text.index('pessoa')),'mailto:pessoa@example.org')
        self.assertIsNone(target_at(text,0))
        self.assertEqual(target_at('www.example.org',3),'https://www.example.org')
        self.assertEqual(target_at('mailto:pessoa@example.org',9),'mailto:pessoa@example.org')
        self.assertEqual(target_at('name?tag@example.org',2),'mailto:name%3Ftag@example.org')

    def test_existing_directory_spaces_unicode_and_file_opens_parent(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'pasta de ação';folder.mkdir()
            text='\n'+str(folder)+'\nOutra linha'
            self.assertEqual(target_at(text,text.index('ação')),folder.as_uri())
            file=folder/'executavel.sh';file.write_text('not executed')
            self.assertEqual(target_at(str(file),2),folder.as_uri())
            quoted='Pasta: "'+str(folder)+'" ao lado'
            self.assertEqual(target_at(quoted,quoted.index('ação')),folder.as_uri())
            self.assertIsNone(target_at(quoted,len(quoted)-1))
            self.assertEqual(target_at(folder.as_uri(),3),folder.as_uri())

    def test_path_priority_over_embedded_email_or_domain(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'pessoa@example.org';folder.mkdir()
            self.assertEqual(target_at(str(folder),str(folder).index('@')),folder.as_uri())

    def test_unsupported_missing_or_empty_destinations_do_not_launch(self):
        for text in ('javascript:alert(1)','ftp://example.org/file','file://remote.invalid/tmp',
                '/not-an-existing-test-path-239823','plain text',''):
            self.assertIsNone(target_at(text,0),text)
        self.assertIsNone(target_at('https://user:password@example.org',12))
        self.assertIsNone(target_at('https://example.org',999))

    def test_email_candidates_have_bounded_validation_work_on_long_lines(self):
        # No wall-clock assertion: the expensive validator only sees a single
        # clicked candidate, bounded independently of the note's line length.
        fullmatch=link_targets.re.fullmatch
        for size in (4000,16000,100000):
            for text in ('a'*size,('a@'*(size//2)),('a.'*(size//2))):
                with patch.object(link_targets.re,'fullmatch',wraps=fullmatch) as validate:
                    self.assertIsNone(target_at(text,len(text)//2))
                    validate.assert_not_called()
            text=('a@b.com '*(size//8))+'last@example.org'
            with patch.object(link_targets.re,'fullmatch',wraps=fullmatch) as validate:
                self.assertEqual(target_at(text,len(text)-2),'mailto:last@example.org')
                self.assertEqual(validate.call_count,1)
                self.assertLessEqual(len(validate.call_args.args[1]),254)

    def test_email_limits_reject_overlong_runs_without_matching_a_suffix(self):
        valid='a'*64+'@example.org'
        self.assertEqual(target_at(valid,63),'mailto:'+valid)
        for invalid in ('a'*65+'@example.org','a'*100000+'@example.org'):
            self.assertIsNone(target_at(invalid,len(invalid)-3))
        domain='b'*63+'.'+'c'*63+'.'+'d'*57+'.com'
        at_limit='a'*64+'@'+domain
        self.assertEqual(len(at_limit),254)
        self.assertEqual(target_at(at_limit,100),'mailto:'+at_limit)
        too_long=at_limit+'.x'
        self.assertIsNone(target_at(too_long,100))
        email='mailto:pessoa+tag@example.org'
        self.assertEqual(target_at(email,2),'mailto:pessoa%2Btag@example.org')

    def test_malformed_file_uri_and_ipv6_authorities_have_no_destination(self):
        for value in ('file://[bad','file://[::1/tmp','file://[bad]/tmp',
                'file://[vXYZ]/tmp','file://[::1]/tmp','file:///tmp/%00'):
            with self.subTest(value=value):
                self.assertIsNone(link_targets.directory_uri(value))
                self.assertIsNone(target_at(value,0))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'pasta com espaços';path.mkdir()
            self.assertEqual(target_at(path.as_uri(),0),path.as_uri())

    def handler(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'sticky-notes/card.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef))
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='text_press')
        launch=Mock();namespace=dict(ui=ui,Gdk=SimpleNamespace(ModifierType=SimpleNamespace(CONTROL_MASK=4)),
            Gio=SimpleNamespace(AppInfo=SimpleNamespace(launch_default_for_uri=launch)),target_at=target_at)
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'card.py','exec'),namespace)
        view=Mock();view.window_to_buffer_coords.return_value=(50,100)
        view.get_iter_at_location.return_value=(True,SimpleNamespace(get_offset=lambda:8))
        context=Mock();host=SimpleNamespace(text=view,value=lambda:'https://example.org',
            get_display=lambda:SimpleNamespace(get_app_launch_context=lambda:context),status=Mock())
        event=SimpleNamespace(button=1,state=4,window=object(),x=3,y=5,time=123)
        return namespace['text_press'],host,event,launch,context

    def test_ctrl_left_click_routes_default_app_with_event_timestamp(self):
        handler,host,event,launch,context=self.handler()
        self.assertTrue(handler(host,None,event))
        launch.assert_called_once_with('https://example.org',context)
        context.set_timestamp.assert_called_once_with(123)
        host.text.window_to_buffer_coords.assert_called_once_with(host.text.get_window_type.return_value,3,5)

    def test_normal_click_and_outside_text_preserve_editing(self):
        handler,host,event,launch,_=self.handler()
        event.state=0;self.assertFalse(handler(host,None,event))
        host.text.get_iter_at_location.assert_not_called()
        event.state=4;event.button=3;self.assertFalse(handler(host,None,event))
        event.button=1;host.text.get_iter_at_location.return_value=(False,None)
        self.assertFalse(handler(host,None,event));launch.assert_not_called()

    def test_ctrl_click_malformed_file_uri_preserves_editing_without_launch(self):
        handler,host,event,launch,context=self.handler()
        text='file://[bad';host.value=lambda:text
        self.assertFalse(handler(host,None,event))
        launch.assert_not_called();context.set_timestamp.assert_not_called()
        host.text.get_buffer.assert_not_called();host.status.show.assert_not_called()
        self.assertEqual(host.value(),text)

    def test_failed_default_app_shows_error_without_editing_note(self):
        handler,host,event,launch,_=self.handler();launch.side_effect=RuntimeError('synthetic')
        self.assertTrue(handler(host,None,event));host.status.show.assert_called_once()

class StickyHoverTests(unittest.TestCase):
    def host(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'sticky-notes/card.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef))
        names=('clear_link_hover','update_link_hover','refresh_link_hover','link_key_release')
        funcs=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names]
        namespace=dict(link_at=link_at,Gtk=SimpleNamespace(TextWindowType=SimpleNamespace(TEXT=1)),
            Gdk=SimpleNamespace(keyval_name=lambda key:key))
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'card.py','exec'),namespace)
        window=Mock();window.get_device_position.return_value=(None,3,5,0)
        view=Mock();view.get_window.return_value=window;view.window_to_buffer_coords.return_value=(3,5)
        view.get_iter_at_location.return_value=(True,SimpleNamespace(get_offset=lambda:8))
        buffer=Mock();buffer.get_iter_at_offset.side_effect=lambda value:value
        host=SimpleNamespace(text=view,buffer=buffer,link_tag=object(),hover_link=None,
            link_cursor='pointer',edit_cursor='text',value=lambda:'https://example.org',
            get_display=lambda:Mock())
        for name in names:setattr(host,name,MethodType(namespace[name],host))
        return host,window

    def test_ctrl_hover_bolds_only_target_and_restores_on_release(self):
        host,window=self.host()
        host.update_link_hover(window,3,5,True)
        host.buffer.apply_tag.assert_called_once_with(host.link_tag,0,len(host.value()))
        window.set_cursor.assert_called_with('pointer')
        host.link_key_release(None,SimpleNamespace(keyval='Control_L'))
        self.assertIsNone(host.hover_link);window.set_cursor.assert_called_with('text')
        host.buffer.remove_tag.assert_called()
        host.buffer.set_text.assert_not_called()

    def test_ctrl_hover_malformed_uri_clears_old_highlight_without_editing(self):
        host,window=self.host();host.value=lambda:'file://[bad'
        host.hover_link=(0,5,'https://example.org')
        self.assertFalse(host.update_link_hover(window,3,5,True))
        self.assertIsNone(host.hover_link)
        host.buffer.apply_tag.assert_not_called();host.buffer.set_text.assert_not_called()
        window.set_cursor.assert_called_with('text')

    def test_press_ctrl_without_moving_mouse_refreshes_hover(self):
        host,window=self.host();host.refresh_link_hover()
        self.assertIsNotNone(host.hover_link);window.set_cursor.assert_called_with('pointer')
        host.update_link_hover(window,3,5,False)
        self.assertIsNone(host.hover_link);window.set_cursor.assert_called_with('text')

    def test_spans_exclude_surrounding_text_and_wrap_does_not_split_target(self):
        text='Texto: https://example.org. fim'
        self.assertEqual(link_at(text,12),(7,26,'https://example.org'))
        self.assertIsNone(link_at(text,0))
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'pasta com espaços';path.mkdir();text='"'+str(path)+'"'
            self.assertEqual(link_at(text,5),(1,len(text)-1,path.as_uri()))

if __name__=='__main__':unittest.main()
