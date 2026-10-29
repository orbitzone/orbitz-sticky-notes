"""Email drafts pass bounded attachments to the desktop portal, never a shell."""
from pathlib import Path
import sys
import tempfile
import unittest
import os
from email import policy
from email.parser import BytesParser
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sticky-notes'))
import email_compose as compose


class EmailComposeTests(unittest.TestCase):
    def test_valid_draft_uses_email_portal_with_fd_attachments(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'note.txt';path.write_text('file')
            connection=Mock()
            connection.call_with_unix_fd_list_sync.return_value=(None,None)
            fd_list=Mock();fd_list.append.side_effect=[0]
            with patch.object(compose.Gio.UnixFDList,'new',return_value=fd_list),\
                 patch.object(compose.Gio,'bus_get_sync',return_value=connection):
                compose.compose_email('person@example.com','A subject','Body text',[path])
            args=connection.call_with_unix_fd_list_sync.call_args.args
            self.assertEqual(args[:4],('org.freedesktop.portal.Desktop','/org/freedesktop/portal/desktop',
                                       'org.freedesktop.portal.Email','ComposeEmail'))
            parameters=args[4]
            self.assertEqual(parameters.get_child_value(0).get_string(),'')
            options=parameters.get_child_value(1)
            self.assertEqual(options.lookup_value('address',None).get_string(),'person@example.com')
            self.assertEqual(options.lookup_value('subject',None).get_string(),'A subject')
            self.assertEqual(options.lookup_value('body',None).get_string(),'Body text')
            self.assertEqual(options.lookup_value('attachment_fds',None).unpack(),[0])
            fd_list.append.assert_called_once()

    def test_invalid_recipient_and_subject_never_call_portal(self):
        connection=Mock()
        with patch.object(compose.Gio,'bus_get_sync',return_value=connection):
            with self.assertRaises(ValueError):compose.compose_email('not-an-email','subject','body',[])
            with self.assertRaises(ValueError):compose.compose_email('a@example.com','bad\nsubject','body',[])
        connection.call_with_unix_fd_list_sync.assert_not_called()

    def test_portal_fuse_attachment_opens_without_nofollow_and_checks_inode(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'portal-image.jpg';path.write_bytes(b'image')
            connection=Mock();connection.call_with_unix_fd_list_sync.return_value=(None,None)
            fd_list=Mock();fd_list.append.return_value=0
            native_open=os.open
            def fuse_open(file_path,flags):
                self.assertFalse(flags & getattr(os,'O_NOFOLLOW',0))
                return native_open(file_path,flags)
            with patch.object(compose.Gio.UnixFDList,'new',return_value=fd_list),\
                 patch.object(compose.Gio,'bus_get_sync',return_value=connection),\
                 patch.object(compose.os,'open',side_effect=fuse_open):
                compose.compose_email('person@example.com','A subject','Body',[path])
            fd_list.append.assert_called_once()
            connection.call_with_unix_fd_list_sync.assert_called_once()

    def test_attachment_symlink_is_rejected_before_opening(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'target.jpg';target.write_bytes(b'image')
            link=Path(folder)/'linked.jpg';link.symlink_to(target)
            connection=Mock()
            with patch.object(compose.Gio,'bus_get_sync',return_value=connection):
                with self.assertRaises(ValueError):
                    compose.compose_email('person@example.com','A subject','Body',[link])
            connection.call_with_unix_fd_list_sync.assert_not_called()

    def test_flatpak_opens_x_unsent_mime_draft_with_real_attachments(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'portal-image.jpg';path.write_bytes(b'image bytes')
            connection=Mock()
            connection.call_with_unix_fd_list_sync.return_value=('/org/freedesktop/portal/request/1',None)
            fd_list=Mock();fd_list.append.side_effect=[0,0]
            real_exists=os.path.exists
            with patch.object(compose.Gio.UnixFDList,'new',return_value=fd_list),\
                 patch.object(compose.Gio,'bus_get_sync',return_value=connection),\
                 patch.object(compose.os.path,'exists',side_effect=lambda value: value=='/.flatpak-info' or real_exists(value)),\
                 patch.object(compose.GLib,'get_user_cache_dir',return_value=folder):
                compose.compose_email('person@example.com','A subject','Body text',[path])
            args=connection.call_with_unix_fd_list_sync.call_args.args
            self.assertEqual(args[:3],('org.freedesktop.portal.Desktop','/org/freedesktop/portal/desktop',
                                       'org.freedesktop.portal.OpenURI'))
            self.assertEqual(args[3],'OpenFile')
            parameters=args[4]
            self.assertEqual(parameters.unpack()[1],0)
            draft_files=list((root/'orbitz-postits'/'email-drafts').glob('orbitz-note-*.eml'))
            self.assertEqual(len(draft_files),1)
            message=BytesParser(policy=policy.default).parsebytes(draft_files[0].read_bytes())
            self.assertEqual(message['To'],'person@example.com')
            self.assertEqual(message['Subject'],'A subject')
            self.assertEqual(message['X-Unsent'],'1')
            self.assertIn('Body text',message.get_body(preferencelist=('plain',)).get_content())
            attachments=list(message.iter_attachments())
            self.assertEqual(len(attachments),1)
            self.assertEqual(attachments[0].get_filename(),'portal-image.jpg')
            self.assertEqual(attachments[0].get_payload(decode=True),b'image bytes')
            self.assertEqual(draft_files[0].stat().st_mode & 0o777,0o600)

    def test_flatpak_openfile_error_does_not_silently_drop_attachments(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'portal-image.jpg';path.write_bytes(b'image')
            connection=Mock()
            connection.call_with_unix_fd_list_sync.side_effect=compose.GLib.Error.new_literal(
                compose.GLib.quark_from_string('org.freedesktop.DBus.Error.Failed'),
                'OpenFile unavailable',0)
            fd_list=Mock();fd_list.append.side_effect=[0,0]
            real_exists=os.path.exists
            with patch.object(compose.Gio.UnixFDList,'new',return_value=fd_list),\
                 patch.object(compose.Gio,'bus_get_sync',return_value=connection),\
                 patch.object(compose.os.path,'exists',side_effect=lambda value: value=='/.flatpak-info' or real_exists(value)),\
                 patch.object(compose.GLib,'get_user_cache_dir',return_value=folder),\
                 patch.object(compose.subprocess,'Popen') as popen:
                with self.assertRaises(compose.GLib.Error):
                    compose.compose_email('person@example.com','A subject','Body text',[path])
            popen.assert_not_called()


if __name__=='__main__':unittest.main()
