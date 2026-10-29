"""Attachment picker and URI drop callbacks; no real desktop files are opened."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,call
import ast
import os
import stat
import sys
import gi
gi.require_version('GdkPixbuf','2.0')
from gi.repository import GdkPixbuf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sticky-notes'))
from ui_language import ui

def methods(file,cls,names,namespace):
    tree=ast.parse((ROOT/'sticky-notes'/file).read_text())
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
    exec(compile(ast.Module(body=[n for n in node.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),file,'exec'),namespace)
    return namespace


class AttachmentUiTests(TestCase):
    def test_image_attachment_preview_is_bounded_and_cached(self):
        ns=methods('card.py','Card',['attachment_preview_pixbuf','render_image_preview'],dict(
            Path=Path,os=os,stat=stat,GdkPixbuf=GdkPixbuf,
            PREVIEW_IMAGE_SUFFIXES={'.png'},PREVIEW_PDF_SUFFIXES={'.pdf'},PREVIEW_MAX_BYTES=20*1024*1024,
            PREVIEW_WIDTH=280,PREVIEW_HEIGHT=180))
        host=SimpleNamespace(attachment_preview_cache={})
        host.render_image_preview=ns['render_image_preview'].__get__(host)
        item={'path':str(ROOT/'sticky-notes/secret-pin.png')}
        pixbuf=ns['attachment_preview_pixbuf'](host,item)
        self.assertIsNotNone(pixbuf)
        self.assertLessEqual(pixbuf.get_width(),280);self.assertLessEqual(pixbuf.get_height(),180)
        self.assertIs(pixbuf,ns['attachment_preview_pixbuf'](host,item))
        self.assertEqual(len(host.attachment_preview_cache),1)

    def test_pdf_hover_reads_bounded_file_and_requests_page_preview(self):
        ns=methods('card.py','Card',['attachment_preview_pixbuf'],dict(
            Path=Path,os=os,stat=stat,GdkPixbuf=GdkPixbuf,
            PREVIEW_IMAGE_SUFFIXES={'.png'},PREVIEW_PDF_SUFFIXES={'.pdf'},PREVIEW_MAX_BYTES=20*1024*1024,
            PREVIEW_WIDTH=280,PREVIEW_HEIGHT=180))
        host=SimpleNamespace(attachment_preview_cache={},render_pdf_preview=Mock(return_value=object()))
        with __import__('tempfile').TemporaryDirectory() as directory:
            path=Path(directory)/'invoice.pdf';path.write_bytes(b'%PDF-1.4 test')
            preview=ns['attachment_preview_pixbuf'](host,{'path':str(path)})
        self.assertIsNotNone(preview)
        host.render_pdf_preview.assert_called_once_with(b'%PDF-1.4 test')

    def test_locked_secret_never_generates_attachment_preview(self):
        ns=methods('card.py','Card',['attachment_query_tooltip'],dict(Gtk=SimpleNamespace()))
        host=SimpleNamespace(secret_locked=True,attachment_preview_pixbuf=Mock())
        self.assertFalse(ns['attachment_query_tooltip'](host,None,0,0,False,Mock(),{'name':'secret.png'}))
        host.attachment_preview_pixbuf.assert_not_called()

    def test_attachment_preview_tooltip_contains_image_without_text(self):
        image=Mock();box=Mock()
        gtk=SimpleNamespace(Box=Mock(return_value=box),Image=SimpleNamespace(new_from_pixbuf=Mock(return_value=image)),
            Orientation=SimpleNamespace(VERTICAL=1),Align=SimpleNamespace(CENTER=2))
        ns=methods('card.py','Card',['attachment_query_tooltip'],dict(Gtk=gtk))
        pixbuf=object();host=SimpleNamespace(secret_locked=False,attachment_preview_pixbuf=Mock(return_value=pixbuf))
        tooltip=Mock();item={'path':'/tmp/photo.png','name':'photo.png'}
        self.assertTrue(ns['attachment_query_tooltip'](host,None,0,0,False,tooltip,item))
        gtk.Image.new_from_pixbuf.assert_called_once_with(pixbuf)
        box.pack_start.assert_called_once_with(image,False,False,0)
        box.show_all.assert_called_once_with();tooltip.set_custom.assert_called_once_with(box)

    def test_text_tooltips_are_absent_and_visual_preview_remains(self):
        source=(ROOT/'sticky-notes/card.py').read_text()
        self.assertNotIn('set_tooltip_text',source)
        self.assertIn('set_has_tooltip(True)',source)
        self.assertIn("button.connect('query-tooltip'",source)

    def test_pdf_preview_renders_first_page_to_bounded_surface(self):
        context=Mock();surface=Mock()
        class Cairo:
            FORMAT_ARGB32=0
            ImageSurface=Mock(return_value=surface)
            Context=Mock(return_value=context)
        page=Mock();page.get_size.return_value=(612,792)
        document=Mock();document.get_n_pages.return_value=2;document.get_page.return_value=page
        poppler=SimpleNamespace(Document=SimpleNamespace(new_from_bytes=Mock(return_value=document)))
        glib=SimpleNamespace(Bytes=SimpleNamespace(new=Mock(return_value='bounded-pdf-bytes')))
        gdk=SimpleNamespace(pixbuf_get_from_surface=Mock(return_value='thumbnail'))
        ns=methods('card.py','Card',['render_pdf_preview'],dict(Poppler=poppler,cairo=Cairo,GLib=glib,Gdk=gdk,
            PREVIEW_WIDTH=280,PREVIEW_HEIGHT=180))
        self.assertEqual(ns['render_pdf_preview'](SimpleNamespace(),b'pdf'),'thumbnail')
        glib.Bytes.new.assert_called_once_with(b'pdf');document.get_page.assert_called_once_with(0)
        self.assertEqual(context.method_calls[:2],[call.set_source_rgb(1,1,1),call.paint()])
        context.scale.assert_called_once_with(180/792,180/792);page.render.assert_called_once_with(context)
        gdk.pixbuf_get_from_surface.assert_called_once_with(surface,0,0,139,180)

    def test_reused_menu_resynchronizes_attachment_actions_after_secret_unlock(self):
        ns=methods('card.py','Card',['menu_opened','sync_secret_menu_actions'],{})
        attach=Mock();email=Mock()
        host=SimpleNamespace(secret_locked=True,attach_menu_item=attach,email_menu_item=email,menu_tooltips=[])
        host.sync_secret_menu_actions=lambda:ns['sync_secret_menu_actions'](host)
        ns['menu_opened'](host)
        attach.set_sensitive.assert_called_with(False);email.set_sensitive.assert_called_with(False)
        host.secret_locked=False
        ns['menu_opened'](host)
        attach.set_sensitive.assert_called_with(True);email.set_sensitive.assert_called_with(True)

    def test_email_menu_opens_recipient_dialog_with_plain_gtk_strings(self):
        dialog=Mock();box=Mock();dialog.get_content_area.return_value=box
        dialog.run.return_value=0
        entries=[Mock(),Mock()]
        gtk=SimpleNamespace(Dialog=Mock(return_value=dialog),Entry=Mock(side_effect=entries),
            Label=Mock(return_value=Mock()),ResponseType=SimpleNamespace(CANCEL=0,ACCEPT=1))
        ns=methods('card.py','Card',['email_note'],dict(Gtk=gtk,ui=ui,compose_email=Mock()))
        host=SimpleNamespace(secret_locked=False,flush=Mock(return_value=True),saved_title='Nota título',
                             alive=True,authorize_secret_edit=Mock(return_value=True))
        self.assertFalse(ns['email_note'](host))
        self.assertEqual(entries[0].set_placeholder_text.call_args.args[0],ui.tr('sticky.email_recipient'))
        labels=[call.args[0] for call in dialog.add_button.call_args_list]
        self.assertEqual(labels,[ui.tr('sticky.cancel'),ui.tr('sticky.email_continue')])
        self.assertTrue(all(isinstance(label,str) for label in labels))
        dialog.show_all.assert_called_once()
        dialog.run.assert_called_once()
        dialog.destroy.assert_called_once()

    def test_menu_action_opens_native_file_chooser_for_portal(self):
        chooser=Mock();file_filter=Mock()
        gtk=SimpleNamespace(FileChooserNative=SimpleNamespace(new=Mock(return_value=chooser)),
            FileChooserAction=SimpleNamespace(OPEN=1),FileFilter=Mock(return_value=file_filter))
        glib=SimpleNamespace(idle_add=Mock(return_value=1))
        ns=methods('card.py','Card',['attach_files','show_attachment_picker','files_chosen'],dict(Gtk=gtk,GLib=glib,ui=ui))
        host=SimpleNamespace(secret_locked=False,file_chooser=None,files_chosen=Mock(),alive=True,
                             authorize_secret_edit=Mock(return_value=True))
        host.show_attachment_picker=lambda:ns['show_attachment_picker'](host)
        self.assertFalse(ns['attach_files'](host))
        glib.idle_add.assert_called_once_with(host.show_attachment_picker)
        gtk.FileChooserNative.new.assert_not_called()
        host.show_attachment_picker()
        gtk.FileChooserNative.new.assert_called_once()
        args=gtk.FileChooserNative.new.call_args.args
        self.assertTrue(all(isinstance(args[index],str) for index in (0,3,4)))
        chooser.set_select_multiple.assert_called_once_with(True)
        self.assertEqual(chooser.connect.call_args.args[0],'response')
        self.assertTrue(callable(chooser.connect.call_args.args[1]))
        chooser.show.assert_called_once()
        chooser.run.assert_not_called()

    def test_file_uri_drop_attaches_file_without_inserting_path(self):
        path='/run/user/1000/doc/mock/image.png'
        gio=SimpleNamespace(File=SimpleNamespace(new_for_uri=lambda uri:SimpleNamespace(get_path=lambda:path)))
        gtk=SimpleNamespace(drag_finish=Mock())
        ns=methods('card.py','Card',['file_drop_received'],dict(Gio=gio,Gtk=gtk,ui=ui))
        store=Mock();store.add_attachment.return_value={'id':'a'}
        context=Mock();selection=SimpleNamespace(get_uris=lambda:['file:///image.png'])
        host=SimpleNamespace(secret_locked=False,app=SimpleNamespace(store=store),note={'id':'n'},
                             refresh_attachments=Mock(),status=Mock(),error=Mock())
        self.assertTrue(ns['file_drop_received'](host,None,context,0,0,selection,0,50))
        store.add_attachment.assert_called_once_with('n',path)
        host.refresh_attachments.assert_called_once()
        gtk.drag_finish.assert_called_once_with(context,True,False,50)

    def test_host_uri_drop_falls_back_to_picker_in_dropped_folder(self):
        path='/home/felipe/Downloads/image.png'
        gio=SimpleNamespace(File=SimpleNamespace(new_for_uri=lambda uri:SimpleNamespace(get_path=lambda:path)))
        gtk=SimpleNamespace(drag_finish=Mock())
        ns=methods('card.py','Card',['file_drop_received'],dict(Gio=gio,Gtk=gtk,Path=Path,ui=ui))
        store=Mock();store.add_attachment.side_effect=FileNotFoundError(path)
        context=Mock();selection=SimpleNamespace(get_uris=lambda:['file:///home/felipe/Downloads/image.png'])
        host=SimpleNamespace(secret_locked=False,app=SimpleNamespace(store=store),note={'id':'n'},
            refresh_attachments=Mock(),status=Mock(),error=Mock(),attach_files=Mock())
        self.assertTrue(ns['file_drop_received'](host,None,context,0,0,selection,0,51))
        host.attach_files.assert_called_once_with('/home/felipe/Downloads')
        gtk.drag_finish.assert_called_once_with(context,False,False,51)

    def test_portal_transfer_drop_retrieves_sandbox_accessible_paths(self):
        context=Mock();connection=Mock();connection.call_finish.return_value=SimpleNamespace(
            unpack=lambda:(['/run/user/1000/doc/portal-id/image.png'],))
        gio=SimpleNamespace(bus_get_sync=Mock(return_value=connection),BusType=SimpleNamespace(SESSION=1),
            DBusCallFlags=SimpleNamespace(NONE=0))
        glib=SimpleNamespace(Variant=lambda *_args:object(),VariantType=SimpleNamespace(new=lambda *_:object()))
        gtk=SimpleNamespace(drag_finish=Mock())
        ns=methods('card.py','Card',['file_drop_received'],dict(Gio=gio,GLib=glib,Gtk=gtk,ui=ui))
        store=Mock();store.add_attachment.return_value={'id':'a'}
        host=SimpleNamespace(secret_locked=False,app=SimpleNamespace(store=store),note={'id':'n'},
                             refresh_attachments=Mock(),status=Mock(),error=Mock())
        selection=SimpleNamespace(get_data=lambda:b'short-lived-key')
        self.assertTrue(ns['file_drop_received'](host,None,context,0,0,selection,1,55))
        args=connection.call.call_args.args
        self.assertEqual(args[0],'org.freedesktop.portal.Documents')
        self.assertEqual(args[3],'RetrieveFiles')
        self.assertEqual(args[4].__class__,object)
        callback=args[9]
        callback(connection,Mock(),None)
        store.add_attachment.assert_called_once_with('n','/run/user/1000/doc/portal-id/image.png')
        gtk.drag_finish.assert_called_once_with(context,True,False,55)

    def test_locked_note_rejects_drop_and_finishes_without_adding(self):
        gtk=SimpleNamespace(drag_finish=Mock())
        ns=methods('card.py','Card',['file_drop_received'],dict(Gtk=gtk,ui=ui))
        store=Mock();context=Mock()
        host=SimpleNamespace(secret_locked=True,app=SimpleNamespace(store=store),status=Mock())
        ns['file_drop_received'](host,None,context,0,0,Mock(),0,70)
        store.add_attachment.assert_not_called()
        gtk.drag_finish.assert_called_once_with(context,False,False,70)

    def test_file_drop_is_registered_on_text_without_inserting_uri_text(self):
        source=(ROOT/'sticky-notes/card.py').read_text()
        self.assertIn('self.text.drag_dest_set(Gtk.DestDefaults.ALL,file_targets,Gdk.DragAction.COPY)',source)
        self.assertIn("Gtk.TargetEntry.new('application/vnd.portal.filetransfer'",source)
        self.assertIn("Gtk.TargetEntry.new('text/uri-list'",source)
        self.assertIn("self.text.connect('drag-data-received',self.file_drop_received)",source)
        self.assertNotIn('self.drop_zone',source)

    def test_blank_handle_above_title_only_moves_the_note(self):
        source=(ROOT/'sticky-notes/card.py').read_text()
        self.assertIn('outer.set_margin_top(0)',source)
        self.assertIn('header_area.pack_start(self.move_handle,False,False,0)',source)
        self.assertIn('header_area.pack_start(heading_row,False,False,0)',source)
        self.assertIn('outer.pack_start(header_area,False,False,0)',source)
        self.assertIn("self.move_handle.connect('button-press-event',self.header_drag_press)",source)
        self.assertIn('self.begin_move_drag(1,int(event.x_root),int(event.y_root),event.time)',source)
        self.assertNotIn('Arraste arquivos aqui para anexar',source)


if __name__=='__main__':import unittest;unittest.main()
