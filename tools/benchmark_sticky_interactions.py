"""Isolated interaction-path measurements for Orbitz Sticky Notes.

Run: python3 tools/benchmark_sticky_interactions.py [path/to/orbitz-sticky-notes]
No user data or application installation is used.
"""
import math
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

repo=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(repo/'sticky-notes'))
os.environ.setdefault('GSETTINGS_BACKEND','memory')
from storage import Store
from card import Card, Gtk, GLib, GdkPixbuf

SAMPLES=40

def stats(values):
    ordered=sorted(values)
    p95=ordered[math.ceil(.95*len(ordered))-1]
    return f'p50={statistics.median(values):.3f}ms p95={p95:.3f}ms max={max(values):.3f}ms'

def make_editor(store,note_id,initial):
    buffer=Gtk.TextBuffer()
    buffer.set_text(initial)
    tags={}
    for name in ('bold','italic','underline'):
        tag=Gtk.TextTag.new(name)
        buffer.get_tag_table().add(tag)
        tags[name]=tag
    host=SimpleNamespace(
        buffer=buffer,style_tags=tags,code_mode=False,loading=False,
        secret_locked=False,dirty=False,title_dirty=False,saved=initial,
        saved_title='',saved_plain=initial,revision=store.get(note_id)['revision'],
        history_timer=0,record=lambda:False,
        note={'id':note_id,'title':''},app=SimpleNamespace(store=store),
        title_entry=SimpleNamespace(get_text=lambda:''),status=SimpleNamespace(hide=lambda:None),
        clear_link_hover=None,link_tag=None,text=SimpleNamespace(get_window=lambda *_:None),edit_cursor=None,hover_link=None,
        history=[initial],index=0,value=None,document_value=None,
        flush=None,document_changed=None,changed=None)
    host.value=MethodType(Card.value,host)
    host.document_value=MethodType(Card.document_value,host)
    host.flush=MethodType(Card.flush,host)
    host.document_changed=MethodType(Card.document_changed,host)
    host.changed=MethodType(Card.changed,host)
    host.link_tag=Gtk.TextTag.new('link');buffer.get_tag_table().add(host.link_tag)
    host.clear_link_hover=MethodType(Card.clear_link_hover,host)
    host.record=MethodType(Card.record,host)
    buffer.connect('changed',host.changed)
    return host

def main():
    with tempfile.TemporaryDirectory(prefix='orbitz-interaction-bench-') as directory:
        root=Path(directory)
        store=Store(root/'data')
        note=store.all()[0]
        print(f'GTK TextBuffer changed signal -> Card.changed/document_changed/flush -> SQLite Store.text; '
              f'n={SAMPLES}, warmup=4; path={root}; DB pragmas: journal_mode={store.db.execute("PRAGMA journal_mode").fetchone()[0]}, '
              f'synchronous={store.db.execute("PRAGMA synchronous").fetchone()[0]}')
        for size,label in ((1024,'1 KiB'),(10240,'10 KiB'),(100000,'100,000 chars')):
            base='x'*(size-1)
            store_text=store.text(note['id'],base,store.get(note['id'])['revision'])
            host=make_editor(store,note['id'],base)
            host.revision=store_text
            end=host.buffer.get_end_iter()
            for _ in range(4):
                host.buffer.insert(host.buffer.get_end_iter(),'y')
                host.loading=True
                host.buffer.delete(host.buffer.get_iter_at_offset(size-1),host.buffer.get_end_iter())
                host.loading=False
                host.saved=host.value();host.dirty=False
            e2e=[];serial=[];commits=[];history=[]
            for _ in range(SAMPLES):
                start=time.perf_counter_ns()
                host.buffer.insert(host.buffer.get_end_iter(),'y')
                e2e.append((time.perf_counter_ns()-start)/1e6)
                start=time.perf_counter_ns();host.record()
                history.append((time.perf_counter_ns()-start)/1e6)
                encoded=host.document_value()
                start=time.perf_counter_ns();Card.document_value(host)
                serial.append((time.perf_counter_ns()-start)/1e6)
                current=store.get(note['id'])
                start=time.perf_counter_ns()
                host.revision=store.text(note['id'],encoded,current['revision'])
                commits.append((time.perf_counter_ns()-start)/1e6)
                host.loading=True
                host.buffer.delete(host.buffer.get_iter_at_offset(size-1),host.buffer.get_end_iter())
                host.loading=False
                host.saved=host.value();host.dirty=False
                host.history=[host.document_value()];host.index=0
                host.revision=store.get(note['id'])['revision']
            print(f'{label} input ({size} bytes after insertion): '
                  f'changed callback e2e={stats(e2e)}; undo-history checkpoint={stats(history)}; '
                  f'document serialization={stats(serial)}; SQLite commit={stats(commits)}')
        store.close()

        # First image preview: app cache is cleared per sample; file/page cache is warm.
        from PIL import Image
        rng=random.Random(20261030)
        width,height=1024,768
        raw=bytes(rng.randrange(256) for _ in range(width*height*3))
        image_path=root/'synthetic.jpg'
        Image.frombytes('RGB',(width,height),raw).save(image_path,'JPEG',quality=85)
        attachment={'path':str(image_path)}
        preview_host=SimpleNamespace(attachment_preview_cache={},render_image_preview=None,render_pdf_preview=None)
        preview_host.render_image_preview=MethodType(Card.render_image_preview,preview_host)
        preview_host.render_pdf_preview=MethodType(Card.render_pdf_preview,preview_host)
        times=[];size_bytes=image_path.stat().st_size
        for _ in range(SAMPLES):
            preview_host.attachment_preview_cache.clear()
            start=time.perf_counter_ns();pixbuf=Card.attachment_preview_pixbuf(preview_host,attachment)
            times.append((time.perf_counter_ns()-start)/1e6)
            if pixbuf is None:raise RuntimeError('Synthetic image preview failed.')
        print(f'First image preview cache-miss (synthetic {width}x{height}, {size_bytes} bytes, '
              f'280x180 decode cap, file cache warm, n={SAMPLES}): {stats(times)}')
        print(f'PDF preview Poppler GI binding available in host: {__import__("card").Poppler is not None}')

if __name__=='__main__':main()
