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

class PinLockedError(ValueError):
    """Temporary UI PIN cooldown; retry_after is the remaining whole seconds."""

class BackupPurgeError(OSError):
    """A snapshot could not be safely purged; the active note was retained."""

@contextmanager
def _startup_lock(directory, timeout=3):
    """Serialize startup before opening SQLite; waiting is bounded, not blocking."""
    deadline=time.monotonic()+timeout
    flags=os.O_CREAT|os.O_RDWR|os.O_NONBLOCK|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(Path(directory)/'.startup.lock',flags,0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise OSError('Sticky startup lock is not a regular file.')
        os.fchmod(fd,0o600)
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
    fd=os.open(lock_path,flags,0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise OSError('Sticky backup lock is not a regular file.')
        os.fchmod(fd,0o600)
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
            try:self._initialize(legacy)
            except BaseException:
                self.db.close()
                raise

    def _initialize(self,legacy):
        os.chmod(self.path,0o600)
        _enable_wal(self.db);self.db.execute('PRAGMA synchronous=FULL')
        self.db.row_factory=sqlite3.Row
        if self.db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise _i18n.exception(ValueError, 'domain.sticky_storage.invalid_database')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS notes(
          id TEXT PRIMARY KEY, text TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', color TEXT NOT NULL,
          x INTEGER NOT NULL DEFAULT 100, y INTEGER NOT NULL DEFAULT 100,
          width INTEGER NOT NULL DEFAULT 310, height INTEGER NOT NULL DEFAULT 300,
          above INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
          archived INTEGER NOT NULL DEFAULT 0,
          secret INTEGER NOT NULL DEFAULT 0 CHECK(secret IN (0,1)));
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
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

    def _purge_backups(self,identity,directory):
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
                        if source.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                            raise sqlite3.DatabaseError('Invalid SQLite backup snapshot.')
                        table=source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notes'").fetchone()
                        columns={row[1] for row in source.execute('PRAGMA table_info(notes)')} if table else set()
                        if 'id' not in columns:
                            raise sqlite3.DatabaseError('Backup snapshot has no verifiable note identity column.')
                        source.backup(destination)
                        count=destination.execute('SELECT count(*) FROM notes WHERE id=?',(identity,)).fetchone()[0]
                        if count:
                            destination.execute('DELETE FROM notes WHERE id=?',(identity,))
                            destination.commit()
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
                    if count:
                        with temporary.open('rb') as staged_file:os.fsync(staged_file.fileno())
                        staged_fd=os.open(temporary,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
                        staged_stat=os.fstat(staged_fd)
                        if not stat.S_ISREG(staged_stat.st_mode):
                            os.close(staged_fd)
                            raise OSError('Purged backup staging file is not regular.')
                        staged.append((temporary,snapshot,staged_fd,staged_stat,self._digest_fd(staged_fd)))
                    else:temporary.unlink()
                except BaseException:
                    self._remove_sqlite_artifacts(temporary)
                    raise
            for temporary,snapshot,staged_fd,staged_stat,digest in staged:
                self._verify_file_identity(temporary,staged_fd,staged_stat,digest,identity)
                os.replace(temporary,snapshot)
                self._verify_file_identity(snapshot,staged_fd,staged_stat,digest,identity)
                self._sync_directory(directory)
            # Verify every destination again after all promotions, before the
            # active database transaction is allowed to commit the deletion.
            for _temporary,snapshot,staged_fd,staged_stat,digest in staged:
                self._verify_file_identity(snapshot,staged_fd,staged_stat,digest,identity)
        except BaseException:
            for temporary,snapshot,staged_fd,staged_stat,digest in staged:
                if not temporary.exists():
                    try:self._restore_promoted(snapshot,staged_fd,directory)
                    except OSError:pass
                self._remove_sqlite_artifacts(temporary)
            raise
        finally:
            for _temporary,_snapshot,staged_fd,_staged_stat,_digest in staged:
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

    def _verify_file_identity(self,path,staged_fd,staged_stat,digest,identity):
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
                if check.execute('SELECT count(*) FROM notes WHERE id=?',(identity,)).fetchone()[0]:
                    raise OSError('Promoted backup still contains the deleted note.')
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
        # Archived legacy rows remain visible when the archive UI is removed.
        if archived is None:
            return [dict(row) for row in self.db.execute('SELECT * FROM notes ORDER BY rowid')]
        return [dict(row) for row in self.db.execute('SELECT * FROM notes WHERE archived=? ORDER BY rowid',(int(archived),))]

    def get(self,identity):
        row=self.db.execute('SELECT * FROM notes WHERE id=?',(identity,)).fetchone()
        if row is None:raise _i18n.exception(ValueError, 'domain.sticky_storage.note_not_found')
        return dict(row)

    def create(self,x=100,y=100):
        identity=str(uuid.uuid4())
        with self.db:self.db.execute('INSERT INTO notes(id,text,color,x,y) VALUES(?,?,?,?,?)',(identity,'',COLORS[0],x,y))
        return self.get(identity)

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
                try:self._purge_backups(identity,directory)
                except Exception as error:
                    raise _i18n.exception(BackupPurgeError,'domain.sticky_storage.backup_purge_failed') from error
                cursor=self.db.execute('DELETE FROM notes WHERE id=?',(identity,))
                if cursor.rowcount!=1:
                    raise OSError('The note could not be removed from active storage; retry the deletion.')
                self.db.commit()
                return True
            except BaseException:
                if self.db.in_transaction:self.db.rollback()
                raise

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
        if not values or not set(values)<={'color','x','y','width','height','above','archived'}:raise _i18n.exception(ValueError, 'domain.sticky_storage.invalid_property')
        if 'color' in values and values['color'] not in COLORS:raise _i18n.exception(ValueError, 'domain.sticky_storage.invalid_color')
        for key,value in values.items():
            if key!='color' and (type(value) is not int or abs(value)>100000):raise _i18n.exception(ValueError, 'domain.sticky_storage.invalid_dimension')
        with self.db:self.db.execute('UPDATE notes SET '+','.join(key+'=?' for key in values)+' WHERE id=?',(*values.values(),identity))

    def close(self):self.db.close()
