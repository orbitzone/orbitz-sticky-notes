"""Transactional local notes. UI PINs do not encrypt note text or backups.

Legacy content is preserved; secret flags only instruct the UI to hide content.
"""
from ui_language import ui as _i18n
from contextlib import contextmanager
from pathlib import Path
from datetime import date
import fcntl
import hashlib
import hmac
import json
import math
import os
import sqlite3
import stat
import re
import tempfile
import time
import uuid

COLORS=['#ffe293','#ffd6df','#d9edb5','#cce7ff','#e5d7fa','#ffdbb5']
DATA=Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'orbitz-postits'
PIN_ITERATIONS=600000
PIN_FAILURE_LIMIT=5
PIN_COOLDOWN_SECONDS=30
PIN_METADATA_KEY='secret_pin_v1'
CODE_LANGUAGES={'python','javascript','typescript','json','html','css','c','cpp','rust','go','java','sql','sh','markdown','plain'}
ATTACHMENT_EXTENSIONS={
    # Images and text documents
    'png','jpg','jpeg','gif','webp','bmp','tif','tiff','svg','heic','avif',
    'txt','md','rst','csv','tsv','rtf','html','htm','xml','json','log',
    'pdf','doc','docx','xls','xlsx','ppt','pptx',
    # OpenDocument / OpenOffice formats
    'odt','ott','ods','ots','odp','otp','odg','otg','odf','odc','odi','odb',
    'fodt','fods','fodp','fodg','sxw','sxc','sxi','sxd','sxg','sxm',
    # Common archives and compressed files
    'zip','rar','7z','tar','gz','bz2','xz','zst','tgz','tbz','tbz2','txz','lz','lzma','lz4','z','cab','arj','ace','lha'
}
ATTACHMENT_MAX_COUNT=10
ATTACHMENT_MAX_FILE_BYTES=50*1024*1024
ATTACHMENT_MAX_TOTAL_BYTES=100*1024*1024

class PinLockedError(ValueError):
    """Temporary UI PIN cooldown; retry_after is the remaining whole seconds."""

class BackupPurgeError(OSError):
    """A snapshot could not be safely purged; the active note was retained."""

class InstanceAlreadyRunningError(RuntimeError):
    """Another process already owns this Sticky Notes data directory."""

class InstanceLock:
    """Hold one process-wide lock for an application's data directory."""
    def __init__(self,directory):
        directory=Path(directory)
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.fd=None
        path=directory/'.app-instance.lock'
        flags=os.O_CREAT|os.O_RDWR|os.O_NONBLOCK|getattr(os,'O_NOFOLLOW',0)
        fd=_open_private_lock(path,flags)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise InstanceAlreadyRunningError('Sticky Notes is already running for this data directory.') from None
            self.fd=fd
        except BaseException:
            os.close(fd)
            raise

    def close(self):
        if self.fd is None:return
        fd,self.fd=self.fd,None
        try:fcntl.flock(fd,fcntl.LOCK_UN)
        finally:os.close(fd)

def _open_private_lock(path,flags):
    """Open a lock file without changing permissions on a shared inode."""
    fd=os.open(path,flags,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError('Sticky lock is not a regular file.')
        if info.st_uid!=os.geteuid():
            raise OSError('Sticky lock is not owned by the current user.')
        if info.st_nlink!=1:
            raise OSError('Sticky lock has unexpected hard links.')
        # Only chmod an inode after confirming it is private to this pathname.
        os.fchmod(fd,0o600)
        return fd
    except BaseException:
        os.close(fd)
        raise

@contextmanager
def _startup_lock(directory, timeout=3):
    """Serialize startup before opening SQLite; waiting is bounded, not blocking."""
    deadline=time.monotonic()+timeout
    flags=os.O_CREAT|os.O_RDWR|os.O_NONBLOCK|getattr(os,'O_NOFOLLOW',0)
    fd=_open_private_lock(Path(directory)/'.startup.lock',flags)
    try:
        while True:
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise sqlite3.OperationalError('Database startup is locked; retry opening notes.') from None
                time.sleep(min(.05,remaining))
        yield
    finally:
        try:fcntl.flock(fd,fcntl.LOCK_UN)
        finally:os.close(fd)

def _enable_wal(db):
    """Set WAL mode with a short bounded retry for concurrent startup locks."""
    db.execute('PRAGMA busy_timeout=0')
    try:
        for attempt in range(24):
            try:
                # Keep SQLite's existing PRAGMA result semantics; malformed
                # databases are rejected by the following quick_check.
                cursor=db.execute('PRAGMA journal_mode=WAL')
                try:cursor.fetchone()
                finally:cursor.close()
                return
            except sqlite3.OperationalError as error:
                code=getattr(error,'sqlite_errorcode',None)
                locked=(code is not None and code & 0xff in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED))
                if code is None:
                    message=str(error).lower()
                    locked='locked' in message or 'busy' in message
                if not locked or attempt==23:raise
                time.sleep(min(.02*(2**attempt),.15))
    finally:
        db.execute('PRAGMA busy_timeout=3000')

@contextmanager
def _backup_lock(directory):
    """Serialize backup creation, retention, and note purges across processes."""
    directory=Path(directory)
    if directory.is_symlink():raise OSError('Sticky backup directory cannot be a symbolic link.')
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock_path=directory/'.lock'
    flags=os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)
    fd=_open_private_lock(lock_path,flags)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield
    finally:
        try:fcntl.flock(fd,fcntl.LOCK_UN)
        finally:os.close(fd)

class Store:
    def __init__(self, directory=DATA, legacy=None):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.directory/'notes.sqlite3'
        # No SQLite connection may enter PRAGMA/schema/import/first backup
        # concurrently with another initializer for this same directory.
        with _startup_lock(self.directory):
            self.db=sqlite3.connect(self.path,timeout=3)
            try:
                self.db.execute('PRAGMA secure_delete=ON')
                self._initialize(legacy)
            except BaseException:
                self.db.close()
                raise

    def _initialize(self,legacy):
        os.chmod(self.path,0o600)
        _enable_wal(self.db);self.db.execute('PRAGMA synchronous=FULL');self.db.execute('PRAGMA foreign_keys=ON')
        self.db.row_factory=sqlite3.Row
        if self.db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise _i18n.exception(ValueError, 'domain.sticky_storage.invalid_database')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS notes(
          id TEXT PRIMARY KEY, text TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', color TEXT NOT NULL,
          x INTEGER NOT NULL DEFAULT 100, y INTEGER NOT NULL DEFAULT 100,
          width INTEGER NOT NULL DEFAULT 310, height INTEGER NOT NULL DEFAULT 300,
          above INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
          archived INTEGER NOT NULL DEFAULT 0,
          secret INTEGER NOT NULL DEFAULT 0 CHECK(secret IN (0,1)),
          code_mode INTEGER NOT NULL DEFAULT 0 CHECK(code_mode IN (0,1)),
          reduced_opacity INTEGER NOT NULL DEFAULT 0 CHECK(reduced_opacity IN (0,1)),
          code_language TEXT NOT NULL DEFAULT 'python');
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attachments(
          id TEXT PRIMARY KEY, note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
          path TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL, added_at INTEGER NOT NULL,
          source_path TEXT NOT NULL DEFAULT '', managed INTEGER NOT NULL DEFAULT 0 CHECK(managed IN (0,1)));
        ''')
        # Add display title/privacy metadata without changing existing text,
        # IDs/revisions or retained snapshots. Secrets remain plaintext on disk.
        # Serialize schema upgrades across processes. Recheck after acquiring
        # the write lock so concurrent initializers do not both ALTER the table.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            columns={row[1] for row in self.db.execute('PRAGMA table_info(notes)')}
            if 'title' not in columns:
                self.db.execute("ALTER TABLE notes ADD COLUMN title TEXT NOT NULL DEFAULT ''")
            if 'secret' not in columns:
                self.db.execute('ALTER TABLE notes ADD COLUMN secret INTEGER NOT NULL DEFAULT 0 CHECK(secret IN (0,1))')
            if 'code_mode' not in columns:
                self.db.execute('ALTER TABLE notes ADD COLUMN code_mode INTEGER NOT NULL DEFAULT 0 CHECK(code_mode IN (0,1))')
            if 'reduced_opacity' not in columns:
                self.db.execute('ALTER TABLE notes ADD COLUMN reduced_opacity INTEGER NOT NULL DEFAULT 0 CHECK(reduced_opacity IN (0,1))')
            if 'code_language' not in columns:
                self.db.execute("ALTER TABLE notes ADD COLUMN code_language TEXT NOT NULL DEFAULT 'python'")
            self.db.commit()
        except BaseException:
            if self.db.in_transaction:self.db.rollback()
            raise
        attachment_columns={row[1] for row in self.db.execute('PRAGMA table_info(attachments)')}
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if 'source_path' not in attachment_columns:
                self.db.execute("ALTER TABLE attachments ADD COLUMN source_path TEXT NOT NULL DEFAULT ''")
            if 'managed' not in attachment_columns:
                self.db.execute('ALTER TABLE attachments ADD COLUMN managed INTEGER NOT NULL DEFAULT 0 CHECK(managed IN (0,1))')
            self.db.commit()
        except BaseException:
            if self.db.in_transaction:self.db.rollback()
            raise
        if not self.db.execute("SELECT 1 FROM metadata WHERE key='imported'").fetchone():
            raw={'notes':'','note_color':COLORS[0]}
            if legacy and Path(legacy).exists():
                raw=json.loads(Path(legacy).read_text())
                if not isinstance(raw,dict) or not isinstance(raw.get('notes'),str):raise _i18n.exception(ValueError, 'domain.sticky_storage.invalid_legacy_note')
            with self.db:
                self.db.execute('INSERT INTO notes(id,text,color) VALUES(?,?,?)',(str(uuid.uuid4()),raw['notes'],raw.get('note_color') if raw.get('note_color') in COLORS else COLORS[0]))
                self.db.execute("INSERT INTO metadata VALUES('imported','1')")
        self._migrate_accessible_legacy_attachments()
        self.backup()

    def backup(self):
        directory=self.directory/'backups'
        with _backup_lock(directory):
            path=directory/(date.today().isoformat()+'.sqlite3')
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise OSError('Sticky backup snapshot is not a regular file.')
            if not path.exists():
                fd,tmp_name=tempfile.mkstemp(prefix='.'+path.name+'.',suffix='.tmp',dir=directory)
                os.close(fd);tmp=Path(tmp_name)
                try:
                    destination=sqlite3.connect(tmp)
                    try:
                        self.db.backup(destination)
                        if destination.execute('PRAGMA journal_mode').fetchone()[0].lower()=='wal':
                            checkpoint=destination.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                            if checkpoint[0]:raise sqlite3.DatabaseError('Could not checkpoint daily note backup.')
                            destination.execute('PRAGMA journal_mode=DELETE')
                    finally:destination.close()
                    with tmp.open('rb') as staged_file:os.fsync(staged_file.fileno())
                    os.chmod(tmp,0o600);tmp.replace(path);self._sync_directory(directory)
                finally:
                    self._remove_sqlite_artifacts(tmp)
            snapshots=self._snapshot_files(directory)
            for old in snapshots[:-14]:old.unlink()
            if snapshots[:-14]:self._sync_directory(directory)

    @staticmethod
    def _sync_directory(directory):
        fd=os.open(directory,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try:os.fsync(fd)
        finally:os.close(fd)

    @staticmethod
    def _snapshot_files(directory):
        paths=sorted(directory.glob('*.sqlite3'))
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise OSError('Sticky backup snapshot is not a regular file.')
        return paths

    def _purge_backups(self,identity,directory,reset_pin=False):
        """Prepare every purged snapshot before atomically replacing any one.

        A failure during the replacement sequence can leave a subset purged;
        the active DB transaction is still rolled back. Repeating the delete is
        safe and completes the purge because already-clean snapshots are skipped.
        """
        staged=[]
        try:
            for snapshot in self._snapshot_files(directory):
                self._normalize_snapshot_sidecars(snapshot,identity)
                fd,temp_name=tempfile.mkstemp(prefix='.'+snapshot.name+'.purge-',suffix='.tmp',dir=directory)
                try:os.fchmod(fd,0o600)
                finally:os.close(fd)
                temporary=Path(temp_name)
                try:
                    source=sqlite3.connect(snapshot.as_uri()+'?mode=ro&immutable=1',uri=True,timeout=3)
                    destination=None
                    try:
                        destination=sqlite3.connect(temporary,timeout=3)
                        destination.execute('PRAGMA foreign_keys=ON')
                        destination.execute('PRAGMA secure_delete=ON')
                        if source.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                            raise sqlite3.DatabaseError('Invalid SQLite backup snapshot.')
                        table=source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notes'").fetchone()
                        columns={row[1] for row in source.execute('PRAGMA table_info(notes)')} if table else set()
                        if 'id' not in columns:
                            raise sqlite3.DatabaseError('Backup snapshot has no verifiable note identity column.')
                        source.backup(destination)
                        count=(destination.execute('SELECT count(*) FROM notes WHERE id=?',(identity,)).fetchone()[0]
                               if identity is not None else 0)
                        metadata_exists=destination.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone()
                        pin_count=(destination.execute('SELECT count(*) FROM metadata WHERE key=?',(PIN_METADATA_KEY,)).fetchone()[0]
                                   if reset_pin and metadata_exists else 0)
                        if count:
                            destination.execute('DELETE FROM notes WHERE id=?',(identity,))
                        if pin_count:
                            destination.execute('DELETE FROM metadata WHERE key=?',(PIN_METADATA_KEY,))
                        if count or pin_count:destination.commit()
                        if destination.execute('PRAGMA journal_mode').fetchone()[0].lower()=='wal':
                            checkpoint=destination.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                            if checkpoint[0]:raise sqlite3.DatabaseError('Could not checkpoint staged backup snapshot.')
                            destination.execute('PRAGMA journal_mode=DELETE')
                        destination.commit()
                        if count:
                            if destination.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                                raise sqlite3.DatabaseError('Purged backup snapshot failed integrity check.')
                    finally:
                        if destination is not None:destination.close()
                        source.close()
                    if count or pin_count:
                        with temporary.open('rb') as staged_file:os.fsync(staged_file.fileno())
                        staged_fd=os.open(temporary,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
                        staged_stat=os.fstat(staged_fd)
                        if not stat.S_ISREG(staged_stat.st_mode):
                            os.close(staged_fd)
                            raise OSError('Purged backup staging file is not regular.')
                        staged.append((temporary,snapshot,staged_fd,staged_stat,self._digest_fd(staged_fd),identity,reset_pin))
                    else:temporary.unlink()
                except BaseException:
                    self._remove_sqlite_artifacts(temporary)
                    raise
            for temporary,snapshot,staged_fd,staged_stat,digest,deleted_identity,pin_removed in staged:
                self._verify_file_identity(temporary,staged_fd,staged_stat,digest,deleted_identity,pin_removed)
                os.replace(temporary,snapshot)
                self._verify_file_identity(snapshot,staged_fd,staged_stat,digest,deleted_identity,pin_removed)
                self._sync_directory(directory)
            # Verify every destination again after all promotions, before the
            # active database transaction is allowed to commit the deletion.
            for _temporary,snapshot,staged_fd,staged_stat,digest,deleted_identity,pin_removed in staged:
                self._verify_file_identity(snapshot,staged_fd,staged_stat,digest,deleted_identity,pin_removed)
        except BaseException:
            for temporary,snapshot,staged_fd,staged_stat,digest,_deleted_identity,_pin_removed in staged:
                if not temporary.exists():
                    try:self._restore_promoted(snapshot,staged_fd,directory)
                    except OSError:pass
                self._remove_sqlite_artifacts(temporary)
            raise
        finally:
            for _temporary,_snapshot,staged_fd,_staged_stat,_digest,_deleted_identity,_pin_removed in staged:
                os.close(staged_fd)

    @staticmethod
    def _normalize_snapshot_sidecars(snapshot,identity):
        """Fold a regular legacy WAL/journal into its snapshot before staging.

        This is intentionally a read/write SQLite open: immutable mode ignores
        WAL content. Locks, busy checkpoints, links, and unexpected journal
        modes fail closed. Only sidecars left after successful checkpoint,
        DELETE-mode confirmation, validation, and connection close are removed.
        """
        sidecar_paths=[Path(str(snapshot)+suffix) for suffix in ('-wal','-shm','-journal')]
        original={}
        for path in sidecar_paths:
            if os.path.lexists(path):
                info=os.lstat(path)
                if not stat.S_ISREG(info.st_mode):
                    raise OSError('Sticky backup sidecar is not a regular file.')
                original[path]=(info.st_dev,info.st_ino)
        uri=snapshot.as_uri()+'?mode=rw'
        db=sqlite3.connect(uri,uri=True,timeout=0)
        try:
            db.execute('PRAGMA busy_timeout=0')
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                raise sqlite3.DatabaseError('Invalid SQLite backup snapshot.')
            table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notes'").fetchone()
            columns={row[1] for row in db.execute('PRAGMA table_info(notes)')} if table else set()
            if 'id' not in columns:
                raise sqlite3.DatabaseError('Backup snapshot has no verifiable note identity column.')
            journal_mode=db.execute('PRAGMA journal_mode').fetchone()[0].lower()
            if journal_mode!='wal' and any(path in original for path in sidecar_paths[:2]):
                raise sqlite3.DatabaseError('SQLite WAL sidecars do not match the snapshot journal mode.')
            if journal_mode=='wal':
                checkpoint=db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                if checkpoint[0]!=0 or (checkpoint[1]>=0 and checkpoint[1]!=checkpoint[2]):
                    raise sqlite3.OperationalError('Legacy backup WAL is busy and could not be checkpointed.')
            mode=db.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower()
            if mode!='delete':
                raise sqlite3.OperationalError('Legacy backup journal mode could not be normalized.')
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                raise sqlite3.DatabaseError('Normalized SQLite backup failed integrity check.')
            # Read the logical identity result while the normalized database is
            # still open; this also rejects malformed legacy row schemas.
            db.execute('SELECT count(*) FROM notes WHERE id=?',(identity,)).fetchone()
        finally:
            db.close()
        for path in sidecar_paths:
            if not os.path.lexists(path):continue
            info=os.lstat(path)
            if not stat.S_ISREG(info.st_mode):
                raise OSError('Sticky backup sidecar changed during normalization.')
            prior=original.get(path)
            if prior is not None and (info.st_dev,info.st_ino)!=prior:
                raise OSError('Sticky backup sidecar identity changed during normalization.')
            path.unlink()

    @staticmethod
    def _digest_fd(fd):
        digest=hashlib.sha256();offset=0
        while True:
            chunk=os.pread(fd,1024*1024,offset)
            if not chunk:break
            digest.update(chunk);offset+=len(chunk)
        return digest.digest()

    def _verify_file_identity(self,path,staged_fd,staged_stat,digest,identity,reset_pin=False):
        current=os.lstat(path)
        if (not stat.S_ISREG(current.st_mode) or current.st_dev!=staged_stat.st_dev or
                current.st_ino!=staged_stat.st_ino):
            raise OSError('Promoted backup identity changed during deletion.')
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        try:
            opened=os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_dev!=staged_stat.st_dev or
                    opened.st_ino!=staged_stat.st_ino or self._digest_fd(fd)!=digest):
                raise OSError('Promoted backup content changed during deletion.')
            if self._digest_fd(staged_fd)!=digest:
                raise OSError('Purged backup staging content changed during deletion.')
            check=sqlite3.connect(Path(path).as_uri()+'?mode=ro&immutable=1',uri=True,timeout=3)
            try:
                if check.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                    raise OSError('Promoted backup failed its integrity check.')
                if identity is not None and check.execute('SELECT count(*) FROM notes WHERE id=?',(identity,)).fetchone()[0]:
                    raise OSError('Promoted backup still contains the deleted note.')
                if reset_pin and check.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone():
                    if check.execute('SELECT count(*) FROM metadata WHERE key=?',(PIN_METADATA_KEY,)).fetchone()[0]:
                        raise OSError('Promoted backup still contains the reset PIN metadata.')
            finally:check.close()
        finally:os.close(fd)
        final=os.lstat(path)
        if not stat.S_ISREG(final.st_mode) or final.st_dev!=staged_stat.st_dev or final.st_ino!=staged_stat.st_ino:
            raise OSError('Promoted backup identity changed during verification.')

    @staticmethod
    def _restore_promoted(snapshot,staged_fd,directory):
        """Restore a verified purged snapshot over a raced path without following it."""
        fd,temp_name=tempfile.mkstemp(prefix='.'+snapshot.name+'.restore-',suffix='.tmp',dir=directory)
        temporary=Path(temp_name)
        try:
            with os.fdopen(fd,'wb') as destination:
                offset=0
                while True:
                    chunk=os.pread(staged_fd,1024*1024,offset)
                    if not chunk:break
                    destination.write(chunk);offset+=len(chunk)
                destination.flush();os.fsync(destination.fileno())
            os.chmod(temporary,0o600)
            os.rename(temporary,snapshot)
            Store._sync_directory(directory)
        finally:
            Store._remove_sqlite_artifacts(temporary)

    @staticmethod
    def _remove_sqlite_artifacts(path):
        for suffix in ('','-wal','-shm','-journal'):
            artifact=Path(str(path)+suffix)
            if os.path.lexists(artifact):artifact.unlink()

    def all(self,archived=None):
        # Preserve the unfiltered store API; the UI requests active or archived rows explicitly.
        if archived is None:
            return [dict(row) for row in self.db.execute('SELECT * FROM notes ORDER BY rowid')]
        return [dict(row) for row in self.db.execute('SELECT * FROM notes WHERE archived=? ORDER BY rowid',(int(archived),))]

    def get(self,identity):
        row=self.db.execute('SELECT * FROM notes WHERE id=?',(identity,)).fetchone()
        if row is None:raise _i18n.exception(ValueError, 'domain.sticky_storage.note_not_found')
        return dict(row)

    def note_number(self,identity):
        row=self.db.execute('SELECT rowid FROM notes WHERE id=?',(identity,)).fetchone()
        if row is None:raise _i18n.exception(ValueError, 'domain.sticky_storage.note_not_found')
        return int(row[0])

    def create(self,x=100,y=100):
        identity=str(uuid.uuid4())
        with self.db:self.db.execute('INSERT INTO notes(id,text,color,x,y) VALUES(?,?,?,?,?)',(identity,'',COLORS[0],x,y))
        return self.get(identity)

    @staticmethod
    def _attachment_path(path):
        path=Path(path)
        info=os.lstat(path)
        if not stat.S_ISREG(info.st_mode):raise _i18n.exception(ValueError,'domain.sticky_storage.attachment_invalid')
        if info.st_size>ATTACHMENT_MAX_FILE_BYTES:raise _i18n.exception(ValueError,'domain.sticky_storage.attachment_too_large')
        if path.suffix.lower().lstrip('.') not in ATTACHMENT_EXTENSIONS:
            raise _i18n.exception(ValueError,'domain.sticky_storage.attachment_type')
        return path.resolve(strict=True),info.st_size

    @property
    def attachments_directory(self):
        return self.directory/'attachments'

    def _ensure_attachments_directory(self):
        directory=self.attachments_directory
        if os.path.lexists(directory):
            info=os.lstat(directory)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid():
                raise OSError('Attachment storage must be a real directory owned by this user.')
        else:
            directory.mkdir(mode=0o700)
        os.chmod(directory,0o700)
        return directory

    def _copy_attachment(self,source,identity):
        """Copy a selected file into durable private app data and check races."""
        if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',identity):
            raise OSError('Attachment identity is invalid; refusing to create a file.')
        directory=self._ensure_attachments_directory()
        before=os.lstat(source)
        if not stat.S_ISREG(before.st_mode):
            raise _i18n.exception(ValueError,'domain.sticky_storage.attachment_invalid')
        source_fd=os.open(source,os.O_RDONLY|getattr(os,'O_CLOEXEC',0))
        temporary=None;destination_fd=None
        try:
            opened=os.fstat(source_fd);after=os.lstat(source)
            if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(after.st_mode)
                    or (before.st_dev,before.st_ino)!=(opened.st_dev,opened.st_ino)
                    or (after.st_dev,after.st_ino)!=(opened.st_dev,opened.st_ino)):
                raise OSError('Attachment changed while it was being opened.')
            if opened.st_size>ATTACHMENT_MAX_FILE_BYTES:
                raise _i18n.exception(ValueError,'domain.sticky_storage.attachment_too_large')
            suffix=source.suffix.lower()
            target=directory/f'{identity}{suffix}'
            destination_fd,temp_name=tempfile.mkstemp(prefix='.pending-',dir=directory)
            temporary=Path(temp_name)
            os.fchmod(destination_fd,0o600)
            copied=0
            while True:
                chunk=os.read(source_fd,1024*1024)
                if not chunk:break
                copied+=len(chunk)
                if copied>ATTACHMENT_MAX_FILE_BYTES:
                    raise _i18n.exception(ValueError,'domain.sticky_storage.attachment_too_large')
                view=memoryview(chunk)
                while view:
                    count=os.write(destination_fd,view);view=view[count:]
            final_source=os.fstat(source_fd)
            if (copied!=opened.st_size or
                    (final_source.st_dev,final_source.st_ino,final_source.st_size,final_source.st_mtime_ns,final_source.st_ctime_ns)
                    !=(opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns,opened.st_ctime_ns)):
                raise OSError('Attachment changed while it was being copied.')
            os.fsync(destination_fd);os.close(destination_fd);destination_fd=None
            os.replace(temporary,target);temporary=None
            directory_fd=os.open(directory,os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0))
            try:os.fsync(directory_fd)
            finally:os.close(directory_fd)
            return target,copied
        finally:
            os.close(source_fd)
            if destination_fd is not None:os.close(destination_fd)
            if temporary is not None:
                try:temporary.unlink()
                except FileNotFoundError:pass

    def _migrate_accessible_legacy_attachments(self):
        """Persist legacy portal/source paths when their files are still readable."""
        rows=[dict(row) for row in self.db.execute('SELECT * FROM attachments WHERE managed=0')]
        for row in rows:
            source=Path(row['path'])
            if not source.exists():continue
            try:source,size=self._attachment_path(source)
            except (OSError,ValueError):continue
            if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',row['id']):continue
            # A stale portal grant or a full disk must not prevent opening
            # every note. Keep the legacy reference and retry on next startup.
            try:managed_path,copied_size=self._copy_attachment(source,row['id'])
            except OSError:continue
            try:
                with self.db:
                    updated=self.db.execute('UPDATE attachments SET path=?,source_path=?,size=?,managed=1 WHERE id=? AND managed=0',
                        (str(managed_path),str(source),copied_size,row['id'])).rowcount
                if updated!=1:
                    self._remove_managed_attachment_file({'id':row['id'],'path':str(managed_path),
                        'source_path':str(source),'name':row['name'],'managed':1})
            except BaseException:
                self._remove_managed_attachment_file({'id':row['id'],'path':str(managed_path),
                    'source_path':str(source),'name':row['name'],'managed':1})
                raise

    def _remove_managed_attachment_file(self,attachment):
        if not attachment or not attachment.get('managed'):return
        identity=attachment.get('id','')
        if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',identity):
            raise OSError('Attachment identity is invalid; refusing to remove a file.')
        path=Path(attachment['path']);directory=self.attachments_directory
        if path.parent!=directory or path.name!=identity+Path(attachment.get('source_path') or attachment['name']).suffix.lower():
            raise OSError('Attachment path is outside managed storage; refusing to remove it.')
        try:directory_info=os.lstat(directory)
        except FileNotFoundError:return
        if not stat.S_ISDIR(directory_info.st_mode) or directory_info.st_uid!=os.geteuid():
            raise OSError('Attachment storage directory is not safe to modify.')
        directory_fd=os.open(directory,os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0))
        try:
            try:info=os.stat(path.name,dir_fd=directory_fd,follow_symlinks=False)
            except FileNotFoundError:return
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                raise OSError('Managed attachment is not a removable file.')
            os.unlink(path.name,dir_fd=directory_fd);os.fsync(directory_fd)
        finally:os.close(directory_fd)

    def attachments(self,identity):
        if not self.db.execute('SELECT 1 FROM notes WHERE id=?',(identity,)).fetchone():
            raise _i18n.exception(ValueError,'domain.sticky_storage.note_not_found')
        return [dict(row) for row in self.db.execute('SELECT * FROM attachments WHERE note_id=? ORDER BY rowid',(identity,))]

    def add_attachment(self,identity,path):
        source,size=self._attachment_path(path)
        row=self.db.execute('SELECT 1 FROM notes WHERE id=?',(identity,)).fetchone()
        if not row:raise _i18n.exception(ValueError,'domain.sticky_storage.note_not_found')
        current=self.attachments(identity)
        if len(current)>=ATTACHMENT_MAX_COUNT:raise _i18n.exception(ValueError,'domain.sticky_storage.attachment_count')
        if sum(item['size'] for item in current)+size>ATTACHMENT_MAX_TOTAL_BYTES:
            raise _i18n.exception(ValueError,'domain.sticky_storage.attachment_total_size')
        if any(item.get('source_path')==str(source) or item['path']==str(source) for item in current):
            raise _i18n.exception(ValueError,'domain.sticky_storage.attachment_duplicate')
        identity_id=str(uuid.uuid4())
        managed_path,copied_size=self._copy_attachment(source,identity_id)
        try:
            with self.db:
                self.db.execute('INSERT INTO attachments(id,note_id,path,name,size,added_at,source_path,managed) VALUES(?,?,?,?,?,?,?,1)',
                                (identity_id,identity,str(managed_path),source.name,copied_size,int(time.time()),str(source)))
        except BaseException:
            self._remove_managed_attachment_file({'id':identity_id,'path':str(managed_path),
                'source_path':str(source),'name':source.name,'managed':1})
            raise
        return dict(self.db.execute('SELECT * FROM attachments WHERE id=?',(identity_id,)).fetchone())

    def remove_attachment(self,identity,attachment_id):
        row=self.db.execute('SELECT * FROM attachments WHERE id=? AND note_id=?',(attachment_id,identity)).fetchone()
        if row is None:return False
        with self.db:
            removed=self.db.execute('DELETE FROM attachments WHERE id=? AND note_id=?',(attachment_id,identity)).rowcount==1
        if removed:self._remove_managed_attachment_file(dict(row))
        return removed

    @staticmethod
    def _validate_pin(pin):
        if not isinstance(pin,str) or re.fullmatch('[0-9]{4}',pin) is None:
            raise _i18n.exception(ValueError,'domain.sticky_storage.pin_format')

    def _pin_record(self):
        row=self.db.execute('SELECT value FROM metadata WHERE key=?',(PIN_METADATA_KEY,)).fetchone()
        if row is None:return None
        try:
            if not isinstance(row[0],str) or len(row[0])>2048:raise ValueError()
            record=json.loads(row[0])
            if set(record)!={'version','salt','digest','iterations','failures','blocked_until'}:raise ValueError()
            if type(record['version']) is not int or record['version']!=1:raise ValueError()
            if type(record['iterations']) is not int or record['iterations']!=PIN_ITERATIONS:raise ValueError()
            for key,length in (('salt',32),('digest',64)):
                if not isinstance(record[key],str) or re.fullmatch('[0-9a-f]{'+str(length)+'}',record[key]) is None:raise ValueError()
            if type(record['failures']) is not int or not 0<=record['failures']<PIN_FAILURE_LIMIT:raise ValueError()
            until=record['blocked_until']
            if type(until) not in (int,float) or not math.isfinite(until) or not 0<=until<2**53:raise ValueError()
            return record
        except (ValueError,TypeError,RecursionError):
            raise _i18n.exception(ValueError,'domain.sticky_storage.pin_metadata_invalid') from None

    @staticmethod
    def _new_pin_record(pin):
        salt=os.urandom(16)
        digest=hashlib.pbkdf2_hmac('sha256',pin.encode('ascii'),salt,PIN_ITERATIONS)
        return dict(version=1,salt=salt.hex(),digest=digest.hex(),iterations=PIN_ITERATIONS,failures=0,blocked_until=0)

    def _save_pin_record(self,record):
        self.db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)',
                        (PIN_METADATA_KEY,json.dumps(record,separators=(',',':'),allow_nan=False)))

    @contextmanager
    def _pin_transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except BaseException:
            if self.db.in_transaction:self.db.rollback()
            raise

    def has_pin(self):
        return self._pin_record() is not None

    def set_pin(self,pin):
        """Configure the global UI PIN once. Content/backups remain plaintext."""
        self._validate_pin(pin)
        with self._pin_transaction():
            if self._pin_record() is not None:
                raise _i18n.exception(ValueError,'domain.sticky_storage.pin_already_set')
            self._save_pin_record(self._new_pin_record(pin))

    def _authenticate_pin(self,pin,new_pin=None):
        self._validate_pin(pin)
        retry_after=0;matched=False
        with self._pin_transaction():
            record=self._pin_record()
            if record is None:raise _i18n.exception(ValueError,'domain.sticky_storage.pin_not_set')
            now=time.time()
            if record['blocked_until']>now:
                # Clock rollback must not turn a short cooldown into a long lockout.
                record['blocked_until']=min(record['blocked_until'],now+PIN_COOLDOWN_SECONDS)
                retry_after=max(1,math.ceil(record['blocked_until']-now))
            else:
                record['blocked_until']=0
                digest=hashlib.pbkdf2_hmac('sha256',pin.encode('ascii'),bytes.fromhex(record['salt']),record['iterations'])
                matched=hmac.compare_digest(digest,bytes.fromhex(record['digest']))
                if matched:
                    record=self._new_pin_record(new_pin) if new_pin is not None else {**record,'failures':0}
                else:
                    record['failures']+=1
                    if record['failures']>=PIN_FAILURE_LIMIT:
                        record.update(failures=0,blocked_until=now+PIN_COOLDOWN_SECONDS)
                        retry_after=PIN_COOLDOWN_SECONDS
            self._save_pin_record(record)
        # Failed attempts/cooldown must commit before reporting an auth failure.
        if retry_after:
            error=_i18n.exception(PinLockedError,'domain.sticky_storage.pin_locked')
            error.retry_after=retry_after
            raise error
        return matched

    def verify_pin(self,pin):
        """UI gate only: False for a wrong PIN; cooldown raises PinLockedError."""
        return self._authenticate_pin(pin)

    def change_pin(self,old,new):
        self._validate_pin(new)
        if not self._authenticate_pin(old,new):
            raise _i18n.exception(ValueError,'domain.sticky_storage.pin_incorrect')

    def set_secret(self,identity,value,revision):
        """CAS UI privacy flag; deliberately does not encrypt or filter text."""
        if type(value) is not bool or type(revision) is not int or revision<0:
            raise _i18n.exception(ValueError,'domain.sticky_storage.invalid_property')
        with self._pin_transaction():
            if value and not self.has_pin():
                raise _i18n.exception(ValueError,'domain.sticky_storage.pin_not_set')
            cursor=self.db.execute('UPDATE notes SET secret=?,revision=revision+1 WHERE id=? AND revision=?',(int(value),identity,revision))
            if cursor.rowcount!=1:raise _i18n.exception(ValueError,'domain.sticky_storage.concurrent_edit')
        return revision+1

    def set_code_mode(self,identity,value,revision):
        if type(value) is not bool or type(revision) is not int or revision<0:
            raise _i18n.exception(ValueError,'domain.sticky_storage.invalid_property')
        with self.db:
            cursor=self.db.execute('UPDATE notes SET code_mode=?,revision=revision+1 WHERE id=? AND revision=?',(int(value),identity,revision))
            if cursor.rowcount!=1:raise _i18n.exception(ValueError,'domain.sticky_storage.concurrent_edit')
        return revision+1

    def transition_code_mode(self,identity,value,revision,*,text,title,width,height):
        """Atomically save note contents and switch its editor mode."""
        if (type(value) is not bool or type(revision) is not int or revision<0
                or not isinstance(text,str) or len(text)>100000
                or not isinstance(title,str) or len(title)>200
                or any(type(number) is not int or not 1<=number<=100000 for number in (width,height))):
            raise _i18n.exception(ValueError,'domain.sticky_storage.invalid_property')
        with self.db:
            cursor=self.db.execute(
                'UPDATE notes SET text=?,title=?,code_mode=?,width=?,height=?,revision=revision+1 WHERE id=? AND revision=?',
                (text,title,int(value),width,height,identity,revision))
            if cursor.rowcount!=1:raise _i18n.exception(ValueError,'domain.sticky_storage.concurrent_edit')
        return revision+1

    def resolve_note_conflict(self,identity,revision,text,title,*,code_mode,secret):
        """Commit an explicitly chosen editor version without racing mode/privacy changes."""
        if (type(revision) is not int or revision<0 or not isinstance(text,str) or len(text)>100000
                or not isinstance(title,str) or len(title)>200 or type(code_mode) is not bool
                or type(secret) is not bool):
            raise _i18n.exception(ValueError,'domain.sticky_storage.invalid_property')
        with self.db:
            cursor=self.db.execute(
                'UPDATE notes SET text=?,title=?,revision=revision+1 WHERE id=? AND revision=? AND code_mode=? AND secret=?',
                (text,title,identity,revision,int(code_mode),int(secret)))
            if cursor.rowcount!=1:raise _i18n.exception(ValueError,'domain.sticky_storage.concurrent_edit')
        return revision+1

    def set_code_language(self,identity,value,revision):
        if not isinstance(value,str) or value not in CODE_LANGUAGES or type(revision) is not int or revision<0:
            raise _i18n.exception(ValueError,'domain.sticky_storage.invalid_property')
        with self.db:
            cursor=self.db.execute('UPDATE notes SET code_language=?,revision=revision+1 WHERE id=? AND revision=?',(value,identity,revision))
            if cursor.rowcount!=1:raise _i18n.exception(ValueError,'domain.sticky_storage.concurrent_edit')
        return revision+1

    secret=set_secret

    def delete(self,identity,expected_revision=None):
        """Permanently delete a note and purge its ID from retained snapshots.

        An optional revision protects concurrent edits, using the same conflict
        error as text(). Backup files are prepared and replaced before the active
        row is deleted. Cross-file replacement is not atomic: if promotion fails,
        the active row remains and retry safely completes any partial purge.
        """
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise _i18n.exception(ValueError, 'domain.sticky_storage.invalid_property')
        directory=self.directory/'backups'
        with _backup_lock(directory):
            self.db.execute('BEGIN IMMEDIATE')
            try:
                row=self.db.execute('SELECT revision FROM notes WHERE id=?',(identity,)).fetchone()
                if row is None:
                    self.db.rollback();return False
                if expected_revision is not None and row['revision']!=expected_revision:
                    raise _i18n.exception(ValueError, 'domain.sticky_storage.concurrent_edit')
                attachments=[dict(item) for item in self.db.execute('SELECT * FROM attachments WHERE note_id=?',(identity,))]
                try:self._purge_backups(identity,directory)
                except Exception as error:
                    raise _i18n.exception(BackupPurgeError,'domain.sticky_storage.backup_purge_failed') from error
                cursor=self.db.execute('DELETE FROM notes WHERE id=?',(identity,))
                if cursor.rowcount!=1:
                    raise OSError('The note could not be removed from active storage; retry the deletion.')
                self.db.commit()
                self._checkpoint_after_deletion()
                for attachment in attachments:self._remove_managed_attachment_file(attachment)
                return True
            except BaseException:
                if self.db.in_transaction:self.db.rollback()
                raise

    def reset_pin_and_delete_secret_notes(self):
        """Remove secret notes and the global PIN from active data and snapshots."""
        directory=self.directory/'backups'
        with _backup_lock(directory):
            self.db.execute('BEGIN IMMEDIATE')
            try:
                identities=[row[0] for row in self.db.execute('SELECT id FROM notes WHERE secret=1 ORDER BY rowid')]
                attachments=[]
                for identity in identities:
                    attachments.extend(dict(row) for row in self.db.execute('SELECT * FROM attachments WHERE note_id=?',(identity,)))
                for identity in identities:
                    self._purge_backups(identity,directory)
                self._purge_backups(None,directory,reset_pin=True)
                cursor=self.db.execute('DELETE FROM notes WHERE secret=1')
                if cursor.rowcount!=len(identities):
                    raise OSError('The secret notes changed during PIN reset; retry the operation.')
                self.db.execute('DELETE FROM metadata WHERE key=?',(PIN_METADATA_KEY,))
                self.db.commit()
            except BaseException:
                if self.db.in_transaction:self.db.rollback()
                raise
        for attachment in attachments:self._remove_managed_attachment_file(attachment)
        checkpoint_clean=self._checkpoint_after_deletion()
        return {'note_ids':identities,'wal_cleaned':checkpoint_clean}

    def _checkpoint_after_deletion(self):
        """Try to remove old WAL page images after secure_delete has wiped rows."""
        try:
            result=self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            return bool(result is not None and result[0]==0 and (result[1]<0 or result[1]==result[2]))
        except sqlite3.Error:
            return False

    def text(self,identity,value,revision):
        if not isinstance(value,str) or len(value)>100000:raise _i18n.exception(ValueError, 'domain.sticky_storage.note_length_limit')
        with self.db:
            cursor=self.db.execute('UPDATE notes SET text=?,revision=revision+1 WHERE id=? AND revision=?',(value,identity,revision))
            if cursor.rowcount!=1:raise _i18n.exception(ValueError, 'domain.sticky_storage.concurrent_edit')
        return revision+1

    def title(self,identity,value,revision):
        if not isinstance(value,str) or len(value)>200:raise _i18n.exception(ValueError, 'domain.sticky_storage.invalid_property')
        with self.db:
            cursor=self.db.execute('UPDATE notes SET title=?,revision=revision+1 WHERE id=? AND revision=?',(value,identity,revision))
            if cursor.rowcount!=1:raise _i18n.exception(ValueError, 'domain.sticky_storage.concurrent_edit')
        return revision+1

    def properties(self,identity,**values):
        if not values or not set(values)<={'color','x','y','width','height','above','archived','reduced_opacity'}:raise _i18n.exception(ValueError, 'domain.sticky_storage.invalid_property')
        if 'color' in values and values['color'] not in COLORS:raise _i18n.exception(ValueError, 'domain.sticky_storage.invalid_color')
        for key,value in values.items():
            if key in ('above','archived','reduced_opacity') and (type(value) is not int or value not in (0,1)):
                raise _i18n.exception(ValueError, 'domain.sticky_storage.invalid_property')
            if key!='color' and (type(value) is not int or abs(value)>100000):raise _i18n.exception(ValueError, 'domain.sticky_storage.invalid_dimension')
        with self.db:self.db.execute('UPDATE notes SET '+','.join(key+'=?' for key in values)+' WHERE id=?',(*values.values(),identity))

    def close(self):self.db.close()
