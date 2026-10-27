"""Resolve explicit note links without executing text or opening local files."""
from pathlib import Path
import re
from urllib.parse import urlsplit, unquote, quote

EMAIL=r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}'
LINKS=re.compile(r'https?://[^\s<>"\x27]+|www\.[^\s<>"\x27]+',re.IGNORECASE)
MAX_EMAIL_LENGTH=254
_EMAIL_CHARS=r'A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~@-'
# Bound the candidate and forbid retries from the middle of an overlong run.
# Thus a long non-email line is scanned once, never with an unbounded local part.
_EMAIL_CANDIDATES=re.compile(r'(?<!['+_EMAIL_CHARS+r'])(?:mailto:)?['+_EMAIL_CHARS+r']{1,255}(?!['+_EMAIL_CHARS+r'])',re.IGNORECASE)
PATHS=re.compile(r'"([^"\n]+)"|\x27([^\x27\n]+)\x27|(?:file://|~/|/)[^\s<>"\x27]+')


def directory_uri(value):
    try:
        if value.startswith('file://'):
            parsed=urlsplit(value)
            if parsed.netloc not in ('','localhost') or parsed.query or parsed.fragment:return None
            value=unquote(parsed.path)
        if not value.startswith(('/','~/')):return None
        path=Path(value).expanduser()
        if path.is_dir():return path.resolve().as_uri()
        if path.is_file():return path.resolve().parent.as_uri()
    except (OSError,ValueError,RuntimeError):pass
    return None


def link_at(text, offset):
    if not 0<=offset<len(text):return None
    start=text.rfind('\n',0,offset)+1;end=text.find('\n',offset)
    if end<0:end=len(text)
    line=text[start:end];point=offset-start
    # A logical line may contain a path with spaces; visual wrapping is irrelevant.
    stripped=line.strip();left=len(line)-len(line.lstrip())
    if left<=point<left+len(stripped):
        uri=directory_uri(stripped)
        if uri:return (start+left,start+left+len(stripped),uri)
    for match in PATHS.finditer(line):
        group=1 if match.group(1) is not None else 2 if match.group(2) is not None else 0
        value=match.group(group)
        if match.start(group)<=point<match.end(group):
            uri=directory_uri(value) or directory_uri(value.rstrip('.,;:!?)'))
            if uri:return (start+match.start(group),start+match.end(group),uri)
    for match in LINKS.finditer(line):
        value=match.group().rstrip('.,;:!?')
        while value.endswith(')') and value.count(')')>value.count('('):value=value[:-1]
        if not match.start()<=point<match.start()+len(value):continue
        span=(start+match.start(),start+match.start()+len(value))
        url='https://'+value if value.lower().startswith('www.') else value
        try:
            parts=urlsplit(url)
            if parts.scheme.lower() in ('http','https') and parts.hostname and not parts.username and not parts.password:
                return (*span,url)
        except ValueError:pass
        return None  # An invalid URL under the pointer must not become an email.
    for match in _EMAIL_CANDIDATES.finditer(line):
        value=match.group().rstrip('.,;:!?')
        if not match.start()<=point<match.start()+len(value):continue
        address=value[7:] if value.lower().startswith('mailto:') else value
        if len(address)<=MAX_EMAIL_LENGTH and re.fullmatch(EMAIL,address):
            return (start+match.start(),start+match.start()+len(value),'mailto:'+quote(address,safe='@'))
        return None
    return None


def target_at(text, offset):
    link=link_at(text,offset)
    return link[2] if link else None
