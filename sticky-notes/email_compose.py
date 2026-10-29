"""Open the desktop's default email composer with note text and file attachments."""
import os
import re
import stat
import subprocess
import mimetypes
import tempfile
import time
import hashlib
from pathlib import Path
from email.message import EmailMessage
from email import policy

import gi
gi.require_version('Gio','2.0')
from gi.repository import Gio,GLib


def compose_email(recipient,subject,body,paths,note_id=None):
    """Open a message draft through XDG portals or the native email helper.

    Attachment file descriptors are passed to the portal instead of granting the
    host mail client unrestricted access to the application's data directory.
    Flatpak attachments are placed in a private MIME draft because Thunderbird's
    mailto handler ignores attachment query parameters. This only opens a draft;
    the user remains responsible for sending it.
    """
    recipient=recipient.strip()
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',recipient):
        raise ValueError('invalid-recipient')
    if not isinstance(subject,str) or len(subject)>200 or '\r' in subject or '\n' in subject:
        raise ValueError('invalid-subject')
    if not isinstance(body,str) or len(body)>100000:
        raise ValueError('invalid-body')
    paths=list(paths)
    if len(paths)>10:raise ValueError('too-many-attachments')
    opened=[]
    try:
        fd_list=Gio.UnixFDList.new();handles=[]
        attachment_fds=[]
        total=0
        for path in paths:
            # The Flatpak document portal is a FUSE mount. Its entries report
            # as regular files, but O_NOFOLLOW can incorrectly fail with
            # ELOOP on valid portal paths. Check the entry before opening, then
            # compare the opened descriptor to detect a symlink/path swap.
            before=os.stat(path,follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode):raise ValueError('invalid-attachment')
            fd=os.open(path,os.O_RDONLY)
            opened.append(fd)
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or
                (info.st_dev,info.st_ino)!=(before.st_dev,before.st_ino)):
                raise ValueError('invalid-attachment')
            if info.st_size>50*1024*1024:raise ValueError('attachment-too-large')
            total+=info.st_size
            if total>100*1024*1024:raise ValueError('attachments-too-large')
            handles.append(fd_list.append(fd))
            attachment_fds.append((os.fspath(path),fd))

        # Thunderbird's mailto handler ignores attachment query fields. In a
        # Flatpak, open a MIME draft via OpenFile instead; X-Unsent makes
        # Thunderbird 91+ open the message directly in compose mode.
        if paths and os.path.exists('/.flatpak-info'):
            _open_eml_draft(recipient,subject,body,attachment_fds,note_id)
            return

        options={
            'address':GLib.Variant('s',recipient),
            'subject':GLib.Variant('s',subject),
            'body':GLib.Variant('s',body),
            'attachment_fds':GLib.Variant('ah',handles),
        }
        connection=Gio.bus_get_sync(Gio.BusType.SESSION,None)
        connection.call_with_unix_fd_list_sync(
            'org.freedesktop.portal.Desktop','/org/freedesktop/portal/desktop',
            'org.freedesktop.portal.Email','ComposeEmail',
            GLib.Variant('(sa{sv})',('',options)),GLib.VariantType.new('(o)'),
            Gio.DBusCallFlags.NONE,5000,fd_list,None)
    except GLib.Error:
        if paths and os.path.exists('/.flatpak-info'):
            # A failed OpenFile request must not silently fall back to a mailto
            # URI that Thunderbird cannot use to attach files.
            raise
        command=['xdg-email','--utf8','--subject',subject,'--body',body]
        for path in paths:command.extend(['--attach',os.fspath(path)])
        command.append(recipient)
        subprocess.Popen(command,close_fds=True)
    finally:
        for fd in opened:
            try:os.close(fd)
            except OSError:pass


def _email_draft_dir():
    cache=Path(GLib.get_user_cache_dir())
    if not stat.S_ISDIR(os.lstat(cache).st_mode):raise OSError('Orbitz cache root is not a real directory.')
    app_cache=cache/'orbitz-postits';directory=app_cache/'email-drafts'
    for path in (app_cache,directory):
        try:path.mkdir(mode=0o700)
        except FileExistsError:pass
        info=os.lstat(path)
        if not stat.S_ISDIR(info.st_mode):raise OSError('Orbitz email draft cache is not a real directory.')
    os.chmod(directory,0o700)
    cutoff=time.time()-24*60*60
    for entry in os.scandir(directory):
        if not entry.name.startswith('orbitz-note-') or not entry.name.endswith('.eml'):
            continue
        try:
            if entry.is_file(follow_symlinks=False) and entry.stat(follow_symlinks=False).st_mtime<cutoff:
                os.unlink(entry.path)
        except OSError:
            pass
    return directory


def _note_draft_prefix(note_id):
    if not isinstance(note_id,str) or not note_id:return None
    digest=hashlib.sha256(note_id.encode('utf-8')).hexdigest()
    return 'orbitz-note-'+digest+'-'


def _wipe_unlink_draft(dir_fd,name,expected):
    """Overwrite a private regular draft before unlinking; unlink links only."""
    current=os.stat(name,dir_fd=dir_fd,follow_symlinks=False)
    if (current.st_dev,current.st_ino)!=(expected.st_dev,expected.st_ino):
        raise OSError('Orbitz draft changed during cache cleanup.')
    if stat.S_ISLNK(current.st_mode):
        os.unlink(name,dir_fd=dir_fd)
        return
    if not stat.S_ISREG(current.st_mode):return
    flags=os.O_WRONLY|getattr(os,'O_NOFOLLOW',0)
    file_fd=os.open(name,flags,dir_fd=dir_fd)
    try:
        opened=os.fstat(file_fd)
        if (not stat.S_ISREG(opened.st_mode) or (opened.st_dev,opened.st_ino)!=(expected.st_dev,expected.st_ino)):
            raise OSError('Orbitz draft changed during cache cleanup.')
        if opened.st_nlink!=1:
            os.unlink(name,dir_fd=dir_fd)
            raise OSError('Orbitz draft has an external hard link; only its cache entry was removed.')
        remaining=opened.st_size;os.lseek(file_fd,0,os.SEEK_SET);zeroes=b'\0'*(1024*1024)
        while remaining:
            written=os.write(file_fd,zeroes[:min(remaining,len(zeroes))])
            if written<=0:raise OSError('Could not overwrite an Orbitz draft before removal.')
            remaining-=written
        os.fsync(file_fd);os.ftruncate(file_fd,0);os.fsync(file_fd)
    finally:os.close(file_fd)
    final=os.stat(name,dir_fd=dir_fd,follow_symlinks=False)
    if (final.st_dev,final.st_ino)!=(expected.st_dev,expected.st_ino):
        raise OSError('Orbitz draft changed during cache cleanup.')
    os.unlink(name,dir_fd=dir_fd)


def purge_note_email_drafts(note_ids):
    """Unlink only this app's cached drafts for the supplied note IDs.

    Symlinks are unlinked as directory entries; their targets are never opened
    or removed. The cache directory itself must not be a symlink.
    """
    prefixes={_note_draft_prefix(identity) for identity in note_ids}
    prefixes.discard(None)
    if not prefixes:return 0
    cache=Path(GLib.get_user_cache_dir())
    app_cache=cache/'orbitz-postits';directory=app_cache/'email-drafts'
    try:
        if not stat.S_ISDIR(os.lstat(cache).st_mode):raise OSError('Orbitz cache root is not a real directory.')
        if not stat.S_ISDIR(os.lstat(app_cache).st_mode):raise OSError('Orbitz app cache is not a real directory.')
        fd=os.open(directory,os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0))
    except FileNotFoundError:return 0
    removed=0
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('Orbitz email draft cache is not a real directory.')
        with os.scandir(fd) as entries:
            for entry in entries:
                if not entry.name.endswith('.eml') or not any(entry.name.startswith(prefix) for prefix in prefixes):continue
                info=os.stat(entry.name,dir_fd=fd,follow_symlinks=False)
                if not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):continue
                _wipe_unlink_draft(fd,entry.name,info);removed+=1
        if removed:os.fsync(fd)
    finally:os.close(fd)
    return removed


def _open_eml_draft(recipient,subject,body,attachments,note_id=None):
    message=EmailMessage(policy=policy.SMTP)
    message['To']=recipient
    message['Subject']=subject
    message['X-Unsent']='1'
    message.set_content(body)
    for path,fd in attachments:
        os.lseek(fd,0,os.SEEK_SET)
        with os.fdopen(os.dup(fd),'rb') as source:
            data=source.read(50*1024*1024+1)
        if len(data)>50*1024*1024:raise ValueError('attachment-too-large')
        mime_type,_encoding=mimetypes.guess_type(path)
        maintype,_,subtype=(mime_type or 'application/octet-stream').partition('/')
        if not subtype:maintype,subtype='application','octet-stream'
        message.add_attachment(data,maintype=maintype,subtype=subtype,
                               filename=os.path.basename(path))

    draft_path=None
    try:
        prefix=_note_draft_prefix(note_id) or 'orbitz-note-'
        fd,draft_path=tempfile.mkstemp(prefix=prefix,suffix='.eml',dir=_email_draft_dir())
        with os.fdopen(fd,'wb') as draft:draft.write(message.as_bytes())
        portal_fd=os.open(draft_path,os.O_RDONLY)
        try:
            fd_list=Gio.UnixFDList.new();handle=fd_list.append(portal_fd)
            connection=Gio.bus_get_sync(Gio.BusType.SESSION,None)
            connection.call_with_unix_fd_list_sync(
                'org.freedesktop.portal.Desktop','/org/freedesktop/portal/desktop',
                'org.freedesktop.portal.OpenURI','OpenFile',
                GLib.Variant('(sha{sv})',('',handle,{})),GLib.VariantType.new('(o)'),
                Gio.DBusCallFlags.NONE,5000,fd_list,None)
        finally:
            os.close(portal_fd)
    except Exception:
        if draft_path:
            try:os.unlink(draft_path)
            except OSError:pass
        raise
