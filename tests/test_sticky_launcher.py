"""Desktop launcher actions route to the current app instance predictably."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]


def command_line_method():
    source=(ROOT/'sticky-notes/postits.py').read_text()
    tree=ast.parse(source)
    app=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='Postits')
    method=next(node for node in app.body if isinstance(node,ast.FunctionDef) and node.name=='command_line')
    namespace={}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'postits.py','exec'),namespace)
    return namespace['command_line']


class LauncherTests(unittest.TestCase):
    def call(self,host,*args):
        command=SimpleNamespace(get_arguments=lambda:['postits',*args])
        return command_line_method()(host,host,command)

    def test_open_hidden_restores_current_hidden_windows(self):
        host=SimpleNamespace(store=object(),hidden_notes=Mock(return_value=[SimpleNamespace(note={'id':'hidden'})]),
            show_hidden_note=Mock(),activate_cards=Mock(),new_card=Mock(),get_windows=Mock(return_value=[]))
        self.assertEqual(self.call(host,'--open-hidden-notes'),0)
        host.show_hidden_note.assert_called_once_with('hidden')
        host.activate_cards.assert_not_called()

    def test_open_hidden_falls_back_to_activation_if_no_hidden_window_exists(self):
        host=SimpleNamespace(store=object(),hidden_notes=Mock(return_value=[]),
            show_hidden_note=Mock(),activate_cards=Mock(),new_card=Mock(),get_windows=Mock(return_value=[]))
        self.assertEqual(self.call(host,'--open-hidden-notes'),0)
        host.activate_cards.assert_called_once_with()

    def test_close_notes_hides_only_visible_note_windows(self):
        note=SimpleNamespace(hide_note=Mock(),get_visible=lambda:True)
        hidden=SimpleNamespace(hide_note=Mock(),get_visible=lambda:False)
        non_note=SimpleNamespace(get_visible=lambda:True)
        host=SimpleNamespace(store=object(),hidden_notes=Mock(),show_hidden_note=Mock(),activate_cards=Mock(),
            new_card=Mock(),get_windows=lambda:[note,hidden,non_note])
        self.assertEqual(self.call(host,'--close-notes'),0)
        note.hide_note.assert_called_once_with()
        hidden.hide_note.assert_not_called()


if __name__=='__main__':unittest.main()
