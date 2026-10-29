"""GTK sticky card editing, interaction and geometry."""
from pathlib import Path
import json
import os
import stat
import gi
try:
    import cairo
except ImportError:
    cairo=None
gi.require_version('GdkPixbuf','2.0')
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib,Gdk,Gio,GdkPixbuf,Pango
try:
    gi.require_version('Poppler','0.18')
    from gi.repository import Poppler
except (ImportError,ValueError):
    Poppler=None
from storage import COLORS
from ui_language import ui
from link_targets import target_at,link_at
from email_compose import compose_email,purge_note_email_drafts

NAMES=[ui.msg('sticky.yellow'),ui.msg('sticky.pink'),ui.msg('sticky.green'),ui.msg('sticky.blue'),ui.msg('sticky.purple'),ui.msg('sticky.peach')]
RICH_TEXT_PREFIX='\x1eORBITZ-RICH-TEXT-1\n'
RICH_STYLES=('bold','italic','underline')
PREVIEW_IMAGE_SUFFIXES={'.png','.jpg','.jpeg','.gif','.webp','.bmp','.tif','.tiff','.heic','.avif'}
PREVIEW_PDF_SUFFIXES={'.pdf'}
PREVIEW_MAX_BYTES=20*1024*1024
PREVIEW_WIDTH=280
PREVIEW_HEIGHT=180
NOTE_CORNER_RADIUS=10


def rounded_note_region(width,height,radius=NOTE_CORNER_RADIUS):
    """Build one stable native window shape for the note's rounded corners."""
    if cairo is None or width<1 or height<1:return None
    radius=min(float(radius),width/2,height/2)
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,width,height)
    context=cairo.Context(surface)
    context.set_antialias(cairo.ANTIALIAS_BEST)
    context.new_path()
    context.move_to(radius,0)
    context.line_to(width-radius,0)
    context.arc(width-radius,radius,radius,-1.5707963267948966,0)
    context.line_to(width,height-radius)
    context.arc(width-radius,height-radius,radius,0,1.5707963267948966)
    context.line_to(radius,height)
    context.arc(radius,height-radius,radius,1.5707963267948966,3.141592653589793)
    context.line_to(0,radius)
    context.arc(radius,radius,radius,3.141592653589793,4.71238898038469)
    context.close_path()
    context.set_source_rgba(1,1,1,1)
    context.fill()
    surface.flush()
    region=Gdk.cairo_region_create_from_surface(surface)
    surface.finish()
    return region


def decode_document(value):
    """Decode persisted rich text; legacy note bodies remain plain strings."""
    if not isinstance(value,str) or not value.startswith(RICH_TEXT_PREFIX):return value,[]
    try:
        document=json.loads(value[len(RICH_TEXT_PREFIX):])
        text=document['text'];spans=document['spans']
        if not isinstance(text,str) or not isinstance(spans,list):raise ValueError('invalid rich text')
        valid=[]
        for span in spans:
            if not isinstance(span,dict):continue
            style,start,end=span.get('style'),span.get('start'),span.get('end')
            if style in RICH_STYLES and type(start) is int and type(end) is int and 0<=start<end<=len(text):
                valid.append((style,start,end))
        return text,valid
    except (KeyError,TypeError,ValueError,json.JSONDecodeError):return value,[]


def encode_document(text,spans):
    """Use the old plain-text representation unless the note has formatting."""
    spans=list(spans)
    if not spans:return text
    return RICH_TEXT_PREFIX+json.dumps({'text':text,'spans':spans},ensure_ascii=False,separators=(',',':'))


def editor_scroll(text):
    scroll=Gtk.ScrolledWindow();scroll.set_name('sticky-note-scroll')
    # Show the translucent scrollbar only when the content needs scrolling.
    scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
    scroll.set_overlay_scrolling(False)
    scroll.set_propagate_natural_height(False);scroll.set_propagate_natural_width(False)
    scroll.set_min_content_width(1);scroll.set_min_content_height(1)
    scroll.set_shadow_type(Gtk.ShadowType.NONE)
    scrollbar=scroll.get_vscrollbar();scrollbar.set_opacity(1.0)
    text.set_vscroll_policy(Gtk.ScrollablePolicy.MINIMUM)
    scroll.add(text)
    return scroll,scrollbar


def resize_grip(callback):
    grip=Gtk.EventBox();grip.set_visible_window(True);grip.set_above_child(True)
    grip.set_size_request(28,28)
    grip.set_halign(Gtk.Align.END);grip.set_valign(Gtk.Align.END)
    grip.set_margin_end(2);grip.set_margin_bottom(2)
    icon=ui.widget(Gtk.Label,label='◢');icon.set_halign(Gtk.Align.END);icon.set_valign(Gtk.Align.END)
    icon.set_margin_end(4);icon.set_margin_bottom(4);grip.add(icon)
    ui.call(grip.get_accessible(),'set_name',ui.msg('sticky.resize'))
    grip.connect('button-press-event',callback)
    grip.connect('realize',lambda widget:widget.get_window().set_cursor(
        Gdk.Cursor.new_from_name(widget.get_display(),'se-resize')))
    return grip


def secret_lock_icon():
    """Load the bundled, fixed-color PIN keypad and touch icon."""
    return Gtk.Image.new_from_file(str(Path(__file__).with_name('secret-pin.png')))


def sync_title_placeholder(entry,placeholder):
    """Keep the title hint visible over GTK's focused empty entry."""
    placeholder.set_visible(not bool(entry.get_text()))


class Card(Gtk.ApplicationWindow):
    def __init__(self,app,note):
        super().__init__(application=app,title=ui.tr('sticky.window_title'))
        ui.set(self,'title',ui.msg('sticky.window_title'))
        note=dict(note)
        display=Gdk.Display.get_default()
        for index in range(display.get_n_monitors()):
            monitor=display.get_monitor(index)
            for rect in [monitor.get_geometry(),monitor.get_workarea()]:
                if abs(note['width']-rect.width)<=2 and abs(note['height']-rect.height)<=2:
                    note.update(width=310,height=300)
        self.app=app;self.note=note;self.revision=note['revision'];self.saved=note['text']
        self.saved_plain=decode_document(self.saved)[0]
        self.saved_title=note.get('title') or '';self.title_dirty=False
        self.secret_locked=bool(note.get('secret'));self.secret_timer=0;self.secret_deadline=0
        self.typing_styles=set()
        self.attachment_preview_cache={}
        self.secret_counting=False;self.auth_dialog=None;self.settings_dialog=None;self.secret_items=[];self.secret_edit_menu_items=[];self.secret_syncing=False
        self.dirty=False;self.loading=False;self.history=[self.saved];self.index=0
        self.history_timer=0;self.geometry_timer=0;self.alive=True;self.pending_restore=False
        self._rounded_shape_size=None
        self.set_decorated(False);self.set_skip_taskbar_hint(True)
        self.set_default_size(note['width'],note['height']);self.set_size_request(220,160)
        self.set_focus_on_map(False);self.set_keep_above(bool(note['above']));self.stick()
        visual=self.get_screen().get_rgba_visual()
        if visual:self.set_visual(visual)
        self.css=Gtk.CssProvider()
        self.get_style_context().add_class('postit')
        self.get_style_context().add_provider(self.css,Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.connect('realize',self.update_rounded_shape)
        self.connect('size-allocate',self.update_rounded_shape)
        outer=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12,margin=18)
        outer.set_margin_top(0)
        outer.set_margin_bottom(30)  # Keep the corner hit target clear of editable text.
        overlay=Gtk.Overlay();overlay.add(outer);self.add(overlay)
        self.move_handle=Gtk.EventBox();self.move_handle.set_name('sticky-note-move-handle')
        self.move_handle.set_size_request(-1,24);self.move_handle.set_visible_window(True)
        ui.call(self.move_handle.get_accessible(),'set_name',ui.msg('sticky.move_note'))
        self.move_handle.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.move_handle.connect('realize',lambda widget:widget.get_window().set_cursor(
            Gdk.Cursor.new_from_name(widget.get_display(),'move')))
        self.move_handle.connect('button-press-event',self.header_drag_press)
        header_area=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0)
        header_area.pack_start(self.move_handle,False,False,0)
        transfer_target=Gtk.TargetEntry.new('application/vnd.portal.filetransfer',Gtk.TargetFlags.OTHER_APP,1)
        uri_target=Gtk.TargetEntry.new('text/uri-list',Gtk.TargetFlags.OTHER_APP,0)
        file_targets=[transfer_target,uri_target]
        header=Gtk.EventBox();header.set_visible_window(False)
        self.menu_button=ui.widget(Gtk.MenuButton)
        self.menu_button.set_direction(Gtk.ArrowType.DOWN)
        self.menu_button.set_size_request(22,22)
        self.menu_button.get_style_context().add_class('sticky-menu-button')
        ui.call(self.menu_button.get_accessible(),'set_name',ui.msg('sticky.note_menu'))
        heading_row=Gtk.Box(spacing=8)
        heading_row.pack_start(header,False,False,0)
        self.title_entry=Gtk.Entry()
        self.title_entry.set_name('sticky-note-title')
        self.title_entry.set_text(self.saved_title)
        self.title_entry.set_max_length(200)
        self.title_entry.set_has_frame(False)
        self.title_entry.get_style_context().add_class('heading')
        ui.call(self.title_entry.get_accessible(),'set_name',ui.msg('sticky.title'))
        title_field=Gtk.Overlay();self.title_field=title_field;title_field.add(self.title_entry)
        self.title_placeholder=ui.widget(Gtk.Label,label=ui.msg('sticky.title'),xalign=0)
        self.title_placeholder.set_name('sticky-note-title-placeholder')
        self.title_placeholder.set_no_show_all(True)
        title_field.add_overlay(self.title_placeholder)
        title_field.set_overlay_pass_through(self.title_placeholder,True)
        sync_title_placeholder(self.title_entry,self.title_placeholder)
        self.title_entry.connect('changed',self.title_changed)
        self.title_entry.connect('activate',lambda *_:self.flush())
        self.title_entry.connect('focus-out-event',self.focus_out)
        heading_row.pack_start(title_field,True,True,0)
        self.close_button=Gtk.Button.new_from_icon_name('window-close-symbolic',Gtk.IconSize.MENU)
        self.close_button.set_relief(Gtk.ReliefStyle.NONE)
        ui.call(self.close_button.get_accessible(),'set_name',ui.msg('sticky.close'))
        self.close_button.connect('clicked',lambda *_:self.close_requested())
        heading_row.pack_end(self.close_button,False,False,0)
        header_area.pack_start(heading_row,False,False,0)
        outer.pack_start(header_area,False,False,0)
        header.add(self.menu_button)
        # Keep right-click access on the header, but the header no longer starts
        # a custom drag; GNOME's Super+drag remains available everywhere.
        header.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        header.connect('button-press-event',self.context_menu_press)
        self.text=Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.text.set_name('sticky-note-text')
        # External file drops attach files without replacing editable text.
        self.text.drag_dest_set(Gtk.DestDefaults.ALL,file_targets,Gdk.DragAction.COPY)
        self.text.connect('drag-data-received',self.file_drop_received)
        self.buffer=self.text.get_buffer()
        self.style_tags={
            'bold':self.buffer.create_tag('text-bold',weight=Pango.Weight.BOLD),
            'italic':self.buffer.create_tag('text-italic',style=Pango.Style.ITALIC),
            'underline':self.buffer.create_tag('text-underline',underline=Pango.Underline.SINGLE),
        }
        self.restore_document(self.saved)
        self.link_tag=self.buffer.create_tag('ctrl-link',weight=Pango.Weight.BOLD)
        self.hover_link=None
        self.link_cursor=Gdk.Cursor.new_from_name(display,'pointer')
        self.edit_cursor=Gdk.Cursor.new_from_name(display,'text')
        self.scroll,self.scrollbar=editor_scroll(self.text);scroll=self.scroll
        self.secret_stack=Gtk.Stack();self.secret_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.secret_stack.set_hhomogeneous(False);self.secret_stack.set_vhomogeneous(False)
        self.secret_stack.add_named(scroll,'editor')
        locked=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6)
        locked.set_halign(Gtk.Align.CENTER);locked.set_valign(Gtk.Align.CENTER)
        lock_image=secret_lock_icon()
        # An EventBox avoids the theme-provided GtkButton hover/focus frame.
        # It is deliberately not focusable: the only hover cue is the pointer.
        self.unlock_button=Gtk.EventBox();self.unlock_button.set_visible_window(False)
        self.unlock_button.set_can_focus(False);self.unlock_button.set_size_request(88,88)
        self.unlock_button.add(lock_image)
        ui.call(self.unlock_button.get_accessible(),'set_name',ui.msg('sticky.secret_unlock_accessible'))
        self.unlock_button.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK|Gdk.EventMask.LEAVE_NOTIFY_MASK|Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.unlock_button.connect('enter-notify-event',self.unlock_pointer_enter)
        self.unlock_button.connect('leave-notify-event',self.unlock_pointer_leave)
        self.unlock_button.connect('button-release-event',self.unlock_pointer_click)
        locked.pack_start(self.unlock_button,False,False,0)
        self.secret_stack.add_named(locked,'locked');outer.pack_start(self.secret_stack,True,True,0)
        self.attachments_box=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=3)
        outer.pack_start(self.attachments_box,False,False,0)
        self.refresh_attachments()
        self.status=ui.widget(Gtk.Label,xalign=0,wrap=True);self.status.set_no_show_all(True)
        outer.pack_start(self.status,False,False,0)
        grip=resize_grip(self.resize_press)
        overlay.add_overlay(grip);overlay.set_overlay_pass_through(grip,False)
        self.apply_color()
        self.buffer.connect('changed',self.changed)
        self.buffer.connect_after('insert-text',self.apply_typing_styles)
        self.emoji_dialog=None
        self.text.connect('insert-emoji',self.insert_emoji)
        self.text.connect('populate-popup',self.populate_popup)
        self.text.connect('button-press-event',self.text_press)
        self.text.connect('key-press-event',self.text_format_key_press)
        self.text.add_events(Gdk.EventMask.POINTER_MOTION_MASK|Gdk.EventMask.ENTER_NOTIFY_MASK|Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.text.connect('motion-notify-event',self.link_motion)
        self.text.connect('enter-notify-event',self.link_motion)
        self.text.connect('leave-notify-event',lambda *_:self.clear_link_hover())
        self.connect('key-release-event',self.link_key_release)
        self.options_menu=Gtk.Menu()
        self.add_options(self.options_menu)
        self.options_menu.show_all()
        self.options_menu.connect('show',lambda *_:self.menu_opened())
        self.menu_button.set_popup(self.options_menu)
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK|Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect('enter-notify-event',self.secret_enter)
        self.connect('leave-notify-event',self.secret_leave)
        self.connect('focus-in-event',self.secret_activity)
        self.connect('button-press-event',self.secret_activity)
        self.connect('unmap',lambda *_:self.lock_secret())
        self.connect('key-press-event',self.key_press)
        self.connect('focus-out-event',self.focus_out)
        self.connect('configure-event',self.configured)
        self.connect('window-state-event',self.state_changed)
        self.connect('delete-event',self.close_requested)
        self.connect('destroy',self.destroyed)
        self.move(note['x'],note['y'])
        # Prepare every stack page before mapping the window. A hidden editor
        # page cannot later be selected by GtkStack, even after PIN succeeds.
        overlay.show_all()
        if self.secret_locked:
            self.secret_stack.set_visible_child_name('locked')
            self.title_field.set_no_show_all(True);self.title_field.hide()
            self.text.set_sensitive(False);self.title_entry.set_sensitive(False)
            self.attachments_box.set_no_show_all(True);self.attachments_box.hide()
        self.show()
        # One normal GTK placement, outside the Shell process, after mapping.
        self.move(note['x'],note['y'])
        for widget in [outer,self.move_handle,header_area,heading_row,header,self.menu_button,title_field,self.title_entry,self.title_placeholder,self.close_button,self.text,scroll,self.scrollbar,self.status,grip,*grip.get_children()]:
            widget.get_style_context().add_provider(self.css,Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def value(self):return self.buffer.get_text(self.buffer.get_start_iter(),self.buffer.get_end_iter(),True)

    def document_value(self):
        text=self.value();spans=[]
        for style,tag in self.style_tags.items():
            cursor=self.buffer.get_start_iter()
            while cursor.get_offset()<len(text):
                if cursor.has_tag(tag):
                    start=cursor.copy();end=cursor.copy()
                    if not end.forward_to_tag_toggle(tag):end=self.buffer.get_end_iter()
                    spans.append({'style':style,'start':start.get_offset(),'end':end.get_offset()})
                    cursor=end
                elif not cursor.forward_to_tag_toggle(tag):break
        spans.sort(key=lambda span:(span['start'],span['end'],span['style']))
        return encode_document(text,spans)

    def restore_document(self,document):
        text,spans=decode_document(document)
        self.buffer.set_text(text)
        for style,start,end in spans:
            self.buffer.apply_tag(self.style_tags[style],self.buffer.get_iter_at_offset(start),self.buffer.get_iter_at_offset(end))

    def apply_typing_styles(self,_buffer,end_iter,_text,length):
        if self.loading or self.secret_locked or not self.typing_styles:return
        end=end_iter.copy();start=end.copy()
        if not start.backward_chars(len(_text)):start=self.buffer.get_start_iter()
        for style in self.typing_styles:self.buffer.apply_tag(self.style_tags[style],start,end)
        self.document_changed()

    def toggle_format(self,style):
        if self.secret_locked or style not in self.style_tags:return False
        bounds=self.buffer.get_selection_bounds()
        if bounds:
            start,end=bounds
            cursor=start.copy();all_styled=True
            while cursor.compare(end)<0:
                if not cursor.has_tag(self.style_tags[style]):all_styled=False;break
                cursor.forward_char()
            if all_styled:self.buffer.remove_tag(self.style_tags[style],start,end)
            else:self.buffer.apply_tag(self.style_tags[style],start,end)
            if all_styled:self.typing_styles.discard(style)
            else:self.typing_styles.add(style)
            self.document_changed()
        else:
            if style in self.typing_styles:self.typing_styles.remove(style)
            else:self.typing_styles.add(style)
        return True

    def text_format_key_press(self,_widget,event):
        if self.secret_locked or not event.state&Gdk.ModifierType.CONTROL_MASK:return False
        key=(Gdk.keyval_name(event.keyval) or '').lower()
        style={'b':'bold','i':'italic','u':'underline'}.get(key)
        if style:return self.toggle_format(style)
        if key=='e':self.text.emit('insert-emoji');return True
        return False

    def document_changed(self):
        if self.loading:return
        if self.secret_locked:
            self.loading=True;self.restore_document(self.saved);self.loading=False
            self.dirty=False
            return
        self.clear_link_hover()
        self.dirty=self.document_value()!=self.saved
        self.flush()
        if self.history_timer:GLib.source_remove(self.history_timer)
        self.history_timer=GLib.timeout_add(300,self.record)

    def apply_color(self):
        color=self.note['color']
        self.css.load_from_data(f'''
        window.postit {{background-color:{color};border-radius:{NOTE_CORNER_RADIUS}px;}}
        textview, textview text, label, eventbox, scrolledwindow, viewport {{background-color:transparent;color:#161616;}}
        scrolledwindow#sticky-note-scroll, scrolledwindow#sticky-note-scroll viewport, scrolledwindow#sticky-note-scroll undershoot, scrolledwindow#sticky-note-scroll overshoot, scrolledwindow#sticky-note-scroll junction {{border:none;border-width:0;border-style:none;background-color:transparent;background-image:none;box-shadow:none;}}
        textview#sticky-note-text, textview#sticky-note-text.view, textview#sticky-note-text:focus, textview#sticky-note-text.view:focus, textview#sticky-note-text text {{border:none;border-width:0;border-style:none;border-color:transparent;background-color:transparent;background-image:none;box-shadow:none;outline:none;padding:0;}}
        scrolledwindow#sticky-note-scroll scrollbar, scrolledwindow#sticky-note-scroll scrollbar * {{opacity:1;background-color:transparent;background-image:none;border-color:transparent;box-shadow:none;}}
        scrolledwindow#sticky-note-scroll scrollbar slider {{background-color:rgba(22,22,22,0.20);border-radius:8px;}}
        scrolledwindow#sticky-note-scroll scrollbar slider:hover, scrolledwindow#sticky-note-scroll scrollbar slider:focus {{background-color:rgba(22,22,22,0.30);}}
        scrolledwindow#sticky-note-scroll scrollbar slider:active {{background-color:rgba(22,22,22,0.40);}}
        textview#sticky-note-text {{font:15px Sans;caret-color:#161616;}}
        entry#sticky-note-title {{font:bold 12px Sans;color:#161616;background:transparent;border:0;box-shadow:none;padding:0;}}
        label#sticky-note-title-placeholder {{font:bold 12px Sans;color:rgba(22,22,22,0.62);}}
        label.heading {{font:bold 12px Sans;}}
        button.sticky-menu-button {{background:transparent;border:0;box-shadow:none;color:rgba(22,22,22,0.62);padding:0;min-width:20px;min-height:20px;}}
        button.sticky-menu-button:hover, button.sticky-menu-button:checked {{background-color:rgba(0,0,0,0.08);border-radius:4px;}}
        eventbox#sticky-note-move-handle {{background-color:transparent;border:none;}}
        button {{background:transparent;border:0;box-shadow:none;color:#161616;padding:0;min-width:18px;min-height:18px;}}
        button:hover {{background-color:rgba(0,0,0,0.08);border-radius:4px;}}
        label {{font:11px Sans;}}
        '''.encode())

    def update_rounded_shape(self,*_):
        """Keep the X11 window mask synchronized with every note resize."""
        if not self.get_realized():return
        window=self.get_window()
        if window is None:return
        width,height=self.get_size()
        size=(width,height)
        if size==self._rounded_shape_size:return
        region=rounded_note_region(width,height)
        if region is None:return
        window.shape_combine_region(region,0,0)
        self._rounded_shape_size=size

    def error(self,error):ui.call(self.status,'set_text',ui.msg('sticky.save_error',error=ui.error_message(error)));self.status.show()

    def changed(self,*_):
        # A committed transaction per text or formatting change survives a crash.
        self.document_changed()

    def flush(self):
        if getattr(self,'secret_locked',False):return not (self.dirty or self.title_dirty)
        saved_any=False
        if self.dirty:
            try:
                value=self.document_value();self.revision=self.app.store.text(self.note['id'],value,self.revision)
            except Exception as error:
                self.error(error);return False
            self.saved=value;self.saved_plain=self.value();self.dirty=False;saved_any=True
        title=self.title_entry.get_text().strip()
        self.title_dirty=title!=self.saved_title
        if self.title_dirty:
            try:
                self.revision=self.app.store.title(self.note['id'],title,self.revision)
            except Exception as error:
                self.error(error);return False
            self.saved_title=title;self.note['title']=title;self.title_dirty=False;saved_any=True
        if saved_any:self.status.hide()
        return True

    def title_changed(self,*_):
        if getattr(self,'secret_locked',False):
            self.title_entry.set_text(self.saved_title)
            self.title_dirty=False
            sync_title_placeholder(self.title_entry,self.title_placeholder)
            return
        sync_title_placeholder(self.title_entry,self.title_placeholder)
        self.title_dirty=self.title_entry.get_text().strip()!=self.saved_title

    def record(self):
        if self.history_timer:GLib.source_remove(self.history_timer);self.history_timer=0
        value=self.document_value()
        if value!=self.history[self.index]:
            self.history=(self.history[:self.index+1]+[value])[-60:];self.index=len(self.history)-1
        return False

    def undo(self,redo=False):
        if getattr(self,'secret_locked',False):return
        self.record();index=self.index+(1 if redo else -1)
        if not 0<=index<len(self.history):return
        self.index=index;self.loading=True;self.restore_document(self.history[index]);self.loading=False
        self.dirty=self.document_value()!=self.saved;self.flush()

    def key_press(self,_widget,event):
        if hasattr(self,'secret_activity'):self.secret_activity()
        if getattr(self,'secret_locked',False):return False
        if Gdk.keyval_name(event.keyval) in ('Control_L','Control_R'):self.refresh_link_hover()
        if event.state&Gdk.ModifierType.CONTROL_MASK:
            key=(Gdk.keyval_name(event.keyval) or '').lower()
            if key in ('z','y'):self.undo(key=='y' or bool(event.state&Gdk.ModifierType.SHIFT_MASK));return True
            if key=='s':self.flush();return True
            if key=='0':self.restore_size();return True
            if key=='n':self.app.new_card(self);return True
            if key=='h':
                self.hide_note()
                return True
        return False

    def clear_link_hover(self):
        self.buffer.remove_tag(self.link_tag,self.buffer.get_start_iter(),self.buffer.get_end_iter())
        self.hover_link=None
        window=self.text.get_window(Gtk.TextWindowType.TEXT)
        if window:window.set_cursor(self.edit_cursor)
        return False

    def update_link_hover(self,window,x,y,control):
        if getattr(self,'secret_locked',False):return False
        link=None
        if control:
            kind=self.text.get_window_type(window)
            bx,by=self.text.window_to_buffer_coords(kind,int(x),int(y))
            found,where=self.text.get_iter_at_location(bx,by)
            if found:link=link_at(self.value(),where.get_offset())
        if link==self.hover_link:return False
        self.clear_link_hover()
        if link:
            self.buffer.apply_tag(self.link_tag,self.buffer.get_iter_at_offset(link[0]),self.buffer.get_iter_at_offset(link[1]))
            self.hover_link=link
            self.text.get_window(Gtk.TextWindowType.TEXT).set_cursor(self.link_cursor)
        return False

    def link_motion(self,_widget,event):
        return self.update_link_hover(event.window,event.x,event.y,bool(event.state&Gdk.ModifierType.CONTROL_MASK))

    def refresh_link_hover(self):
        window=self.text.get_window(Gtk.TextWindowType.TEXT)
        if window:
            pointer=self.get_display().get_default_seat().get_pointer()
            _child,x,y,_state=window.get_device_position(pointer)
            self.update_link_hover(window,x,y,True)

    def link_key_release(self,_widget,event):
        if Gdk.keyval_name(event.keyval) in ('Control_L','Control_R'):self.clear_link_hover()
        return False

    def focus_out(self,*_):
        self.clear_link_hover();self.flush()
        return False

    def text_press(self,_widget,event):
        if getattr(self,'secret_locked',False):return True
        if event.button!=1 or not event.state&Gdk.ModifierType.CONTROL_MASK:return False
        kind=self.text.get_window_type(event.window)
        x,y=self.text.window_to_buffer_coords(kind,int(event.x),int(event.y))
        found,where=self.text.get_iter_at_location(x,y)
        if not found:return False
        uri=target_at(self.value(),where.get_offset())
        if not uri:return False
        try:
            context=self.get_display().get_app_launch_context();context.set_timestamp(event.time)
            Gio.AppInfo.launch_default_for_uri(uri,context)
        except Exception:
            ui.call(self.status,'set_text',ui.msg('sticky.open_failed'));self.status.show()
        return True

    def menu_opened(self):
        self.sync_secret_menu_actions()
        self.refresh_note_menus()

    def refresh_note_menus(self):
        hidden=self.app.hidden_notes()
        archived=self.app.store.all(archived=True)
        self.hidden_notes_item.set_sensitive(bool(hidden))
        self.archived_notes_item.set_sensitive(bool(archived))
        for menu,notes,empty_key,callback in (
            (self.hidden_notes_menu,hidden,'sticky.no_hidden_notes',self.app.show_hidden_note),
            (self.archived_notes_menu,archived,'sticky.no_archived_notes',self.app.restore_archived_note)):
            for child in menu.get_children():
                menu.remove(child);child.destroy()
            if not notes:
                empty=ui.widget(Gtk.MenuItem,label=ui.msg(empty_key));empty.set_sensitive(False);menu.append(empty)
            else:
                for note in notes:
                    label=self.app.note_menu_title(note)
                    entry=ui.widget(Gtk.MenuItem,label=label)
                    entry.connect('activate',lambda _item,identity=note['id']:callback(identity))
                    menu.append(entry)
            menu.show_all()

    def sync_secret_menu_actions(self):
        enabled=not self.secret_locked
        for item in getattr(self,'secret_edit_menu_items',[]):item.set_sensitive(enabled)
        for name in ('attach_menu_item','email_menu_item'):
            item=getattr(self,name,None)
            if item:item.set_sensitive(enabled)

    def context_menu_press(self,_widget,event):
        if event.button==3:
            self.options_menu.popup_at_pointer(event);return True
        return False

    def header_drag_press(self,_widget,event):
        if event.button!=1:return False
        self.secret_activity()
        if not self.authorize_secret_edit():return True
        self.begin_move_drag(1,int(event.x_root),int(event.y_root),event.time)
        return True

    def resize_press(self,_widget,event):
        if event.button==1:
            if not self.authorize_secret_edit():return True
            self.begin_resize_drag(Gdk.WindowEdge.SOUTH_EAST,1,int(event.x_root),int(event.y_root),event.time);return True
        return False

    def authorize_secret_edit(self):
        if not self.note.get('secret') or not self.secret_locked:return True
        self.unlock_secret()
        return not self.secret_locked

    def set_property_value(self,**values):
        if not self.authorize_secret_edit():return False
        try:self.app.store.properties(self.note['id'],**values)
        except Exception as error:self.error(error);return False
        self.note.update(values);self.apply_color();self.set_keep_above(bool(self.note['above']))
        return True

    def populate_popup(self,_text,menu):
        menu.append(Gtk.SeparatorMenuItem());self.add_options(menu);menu.show_all()

    def refresh_attachments(self):
        for child in self.attachments_box.get_children():self.attachments_box.remove(child)
        try:attachments=self.app.store.attachments(self.note['id'])
        except Exception as error:self.error(error);attachments=[]
        icons={'.pdf':'application-pdf','.zip':'package-x-generic','.rar':'package-x-generic',
               '.7z':'package-x-generic','.doc':'x-office-document','.docx':'x-office-document',
               '.xls':'x-office-spreadsheet','.xlsx':'x-office-spreadsheet',
               '.ppt':'x-office-presentation','.pptx':'x-office-presentation'}
        for attachment in attachments:
            path=attachment['path'];suffix=Path(path).suffix.lower()
            icon=icons.get(suffix)
            if not icon:icon='image-x-generic' if suffix in {'.png','.jpg','.jpeg','.gif','.webp','.bmp','.tif','.tiff','.svg','.heic','.avif'} else 'text-x-generic'
            image=Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.MENU)
            button=Gtk.Button();button.set_relief(Gtk.ReliefStyle.NONE);button.add(image)
            # Only image/PDF attachments provide a visual thumbnail on hover;
            # no filename or instructional text tooltip is shown.
            button.set_has_tooltip(True)
            button.connect('query-tooltip',lambda widget,x,y,keyboard,tooltip,item=attachment:
                           self.attachment_query_tooltip(widget,x,y,keyboard,tooltip,item))
            ui.call(button.get_accessible(),'set_name',attachment['name'])
            button.connect('clicked',lambda _button,item=attachment:self.open_attachment(item))
            button.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            button.connect('button-press-event',lambda _button,event,item=attachment:self.attachment_context(event,item))
            self.attachments_box.pack_start(button,False,False,0)
        self.attachments_box.set_visible(bool(attachments) and not self.secret_locked)
        self.attachments_box.show_all()
        if self.secret_locked:self.attachments_box.hide()

    def attachment_preview_pixbuf(self,attachment):
        """Read a bounded image/PDF and create its visual-only hover preview."""
        path=Path(attachment['path']);suffix=path.suffix.lower()
        if suffix not in PREVIEW_IMAGE_SUFFIXES|PREVIEW_PDF_SUFFIXES:return None
        fd=None
        try:
            before=path.lstat()
            if not stat.S_ISREG(before.st_mode) or before.st_size>PREVIEW_MAX_BYTES:return None
            fd=os.open(str(path),os.O_RDONLY|getattr(os,'O_CLOEXEC',0))
            opened=os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or (before.st_dev,before.st_ino)!=(opened.st_dev,opened.st_ino)
                or opened.st_size>PREVIEW_MAX_BYTES):return None
            key=(str(path),opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns)
            if key in self.attachment_preview_cache:return self.attachment_preview_cache[key]
            chunks=[];remaining=PREVIEW_MAX_BYTES+1
            while remaining:
                chunk=os.read(fd,min(65536,remaining))
                if not chunk:break
                chunks.append(chunk);remaining-=len(chunk)
            data=b''.join(chunks);after=os.fstat(fd)
            if len(data)>PREVIEW_MAX_BYTES or (opened.st_size,opened.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):return None
        except (OSError,ValueError,TypeError):return None
        finally:
            if fd is not None:
                try:os.close(fd)
                except OSError:pass
        pixbuf=self.render_pdf_preview(data) if suffix in PREVIEW_PDF_SUFFIXES else self.render_image_preview(data)
        if pixbuf is None:return None
        if len(self.attachment_preview_cache)>=10:self.attachment_preview_cache.pop(next(iter(self.attachment_preview_cache)))
        self.attachment_preview_cache[key]=pixbuf
        return pixbuf

    def render_image_preview(self,data):
        loader=GdkPixbuf.PixbufLoader.new()
        def prepared(loader,width,height):
            if width<=0 or height<=0:return
            scale=min(PREVIEW_WIDTH/width,PREVIEW_HEIGHT/height,1.0)
            loader.set_size(max(1,int(width*scale)),max(1,int(height*scale)))
        try:
            loader.connect('size-prepared',prepared);loader.write(data);loader.close()
            return loader.get_pixbuf()
        except Exception:return None

    def render_pdf_preview(self,data):
        """Render only page one onto an opaque white surface."""
        if Poppler is None or cairo is None:return None
        try:
            document=Poppler.Document.new_from_bytes(GLib.Bytes.new(data),None)
            if document is None or document.get_n_pages()<1:return None
            page=document.get_page(0)
            if page is None:return None
            width,height=page.get_size()
            if width<=0 or height<=0 or width>20000 or height>20000:return None
            scale=min(PREVIEW_WIDTH/width,PREVIEW_HEIGHT/height,1.0)
            pixel_width=max(1,int(width*scale));pixel_height=max(1,int(height*scale))
            surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,pixel_width,pixel_height)
            context=cairo.Context(surface);context.set_source_rgb(1,1,1);context.paint()
            context.scale(scale,scale);page.render(context);surface.flush()
            return Gdk.pixbuf_get_from_surface(surface,0,0,pixel_width,pixel_height)
        except Exception:return None

    def attachment_query_tooltip(self,_widget,_x,_y,_keyboard,tooltip,attachment):
        if self.secret_locked:return False
        pixbuf=self.attachment_preview_pixbuf(attachment)
        if pixbuf is None:return False
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=5)
        image=Gtk.Image.new_from_pixbuf(pixbuf);image.set_halign(Gtk.Align.CENTER)
        box.pack_start(image,False,False,0);box.show_all();tooltip.set_custom(box)
        return True

    def open_attachment(self,attachment):
        try:
            context=self.get_display().get_app_launch_context()
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(attachment['path']).get_uri(),context)
        except Exception:
            ui.call(self.status,'set_text',ui.msg('sticky.open_failed'));self.status.show()

    def attachment_context(self,event,attachment):
        if event.button!=3:return False
        menu=Gtk.Menu()
        for key,callback in (('sticky.show_in_folder',lambda:self.open_attachment_folder(attachment)),
                             ('sticky.remove_attachment',lambda:self.remove_attachment(attachment))):
            item=ui.widget(Gtk.MenuItem,label=ui.msg(key));item.connect('activate',lambda *_args,fn=callback:fn());menu.append(item)
        menu.show_all();menu.popup_at_pointer(event);return True

    def open_attachment_folder(self,attachment):
        try:
            parent=Gio.File.new_for_path(attachment['path']).get_parent()
            if parent is None:raise ValueError('Attachment has no parent folder')
            Gio.AppInfo.launch_default_for_uri(parent.get_uri(),self.get_display().get_app_launch_context())
        except Exception:
            ui.call(self.status,'set_text',ui.msg('sticky.open_failed'));self.status.show()

    def attach_files(self,initial_folder=None):
        if not self.authorize_secret_edit():return False
        if getattr(self,'file_chooser',None):
            self.file_chooser.show();return False
        if getattr(self,'file_chooser_pending',False):return False
        # Let GTK release the menu's pointer/keyboard grab before asking the
        # native portal to present a separate modal dialog.
        self.file_chooser_pending=True
        self.pending_attachment_folder=initial_folder
        GLib.idle_add(self.show_attachment_picker)
        return False

    def show_attachment_picker(self):
        self.file_chooser_pending=False
        if not getattr(self,'alive',True) or not self.authorize_secret_edit():return False
        # GtkFileChooserNative routes sandboxed Flatpak apps through the
        # desktop FileChooser portal and still behaves natively outside Flatpak.
        try:
            chooser=Gtk.FileChooserNative.new(ui.tr('sticky.attach_files'),self,
                Gtk.FileChooserAction.OPEN,ui.tr('sticky.attach'),ui.tr('sticky.cancel'))
            chooser.set_modal(True)
            chooser.set_select_multiple(True)
            file_filter=Gtk.FileFilter();file_filter.set_name(ui.tr('sticky.supported_attachments'))
            for pattern in ('*.png','*.jpg','*.jpeg','*.gif','*.webp','*.bmp','*.tif','*.tiff','*.svg','*.heic','*.avif',
                            '*.txt','*.md','*.rst','*.csv','*.tsv','*.rtf','*.html','*.htm','*.xml','*.json','*.log',
                            '*.pdf','*.doc','*.docx','*.xls','*.xlsx','*.ppt','*.pptx','*.odt','*.ott','*.ods','*.ots',
                            '*.odp','*.otp','*.odg','*.otg','*.odf','*.odc','*.odi','*.odb','*.fodt','*.fods','*.fodp','*.fodg',
                            '*.sxw','*.sxc','*.sxi','*.sxd','*.sxg','*.sxm','*.zip','*.rar','*.7z','*.tar','*.gz','*.bz2',
                            '*.xz','*.zst','*.tgz','*.tbz','*.tbz2','*.txz','*.lz','*.lzma','*.lz4','*.z','*.cab','*.arj','*.ace','*.lha'):
                file_filter.add_pattern(pattern)
            chooser.add_filter(file_filter)
            folder=getattr(self,'pending_attachment_folder',None)
            self.pending_attachment_folder=None
            if folder:
                try:chooser.set_current_folder(Gio.File.new_for_path(folder))
                except Exception:pass
            self.file_chooser=chooser
            chooser.connect('response',self.files_chosen)
            chooser.show()
        except Exception as error:
            self.file_chooser=None
            self.error(error)
        return False

    def files_chosen(self,chooser,response):
        self.file_chooser=None
        try:
            if response==Gtk.ResponseType.ACCEPT and not self.secret_locked:
                uris=chooser.get_uris()
                if not uris:uris=[Gio.File.new_for_path(path).get_uri() for path in chooser.get_filenames()]
                for uri in uris:
                    path=Gio.File.new_for_uri(uri).get_path()
                    if not path:raise ValueError(ui.msg('sticky.local_files_only'))
                    self.app.store.add_attachment(self.note['id'],path)
                self.refresh_attachments();self.status.hide()
        except Exception as error:self.error(error)
        finally:chooser.destroy()

    def file_drop_received(self,_widget,context,_x,_y,selection_data,info,time):
        success=False
        if self.secret_locked:
            ui.call(self.status,'set_text',ui.msg('sticky.attach_secret_unlocked'));self.status.show()
        else:
            try:
                if info==1:
                    # Flatpak file drops carry a short-lived transfer key, not
                    # host paths. RetrieveFiles exports them through Documents
                    # and grants this app access to the returned paths.
                    raw=selection_data.get_data()
                    key=bytes(raw).decode('utf-8').rstrip('\x00')
                    if not key:raise ValueError(ui.msg('sticky.local_files_only'))
                    connection=Gio.bus_get_sync(Gio.BusType.SESSION,None)
                    parameters=GLib.Variant('(sa{sv})',(key,{}))
                    def retrieved(bus,result,_user_data):
                        attached=False
                        try:
                            paths=bus.call_finish(result).unpack()[0]
                            for path in paths:self.app.store.add_attachment(self.note['id'],path)
                            attached=bool(paths)
                            if attached:self.refresh_attachments();self.status.hide()
                            else:ui.call(self.status,'set_text',ui.msg('sticky.local_files_only'));self.status.show()
                        except Exception as error:self.error(error)
                        Gtk.drag_finish(context,attached,False,time)
                    connection.call('org.freedesktop.portal.Documents','/org/freedesktop/portal/documents',
                        'org.freedesktop.portal.FileTransfer','RetrieveFiles',parameters,
                        GLib.VariantType.new('(as)'),Gio.DBusCallFlags.NONE,10000,None,retrieved,None)
                    return True
                uris=selection_data.get_uris() or []
                added=0
                for uri in uris:
                    path=Gio.File.new_for_uri(uri).get_path()
                    if not path:raise ValueError(ui.msg('sticky.local_files_only'))
                    try:self.app.store.add_attachment(self.note['id'],path);added+=1
                    except FileNotFoundError:
                        # Some file managers still send plain host file URIs
                        # instead of the portal transfer key. Ask the chooser
                        # portal to grant access, opening at the dropped file's
                        # folder, rather than persisting an unusable host path.
                        Gtk.drag_finish(context,False,False,time)
                        ui.call(self.status,'set_text',ui.msg('sticky.drop_select_file'));self.status.show()
                        self.attach_files(str(Path(path).parent))
                        return True
                success=added>0
                if success:self.refresh_attachments();self.status.hide()
                else:ui.call(self.status,'set_text',ui.msg('sticky.local_files_only'));self.status.show()
            except Exception as error:self.error(error)
        Gtk.drag_finish(context,success,False,time)
        return True

    def remove_attachment(self,attachment):
        if not self.authorize_secret_edit():return False
        try:
            self.app.store.remove_attachment(self.note['id'],attachment['id']);self.refresh_attachments()
            ui.call(self.status,'set_text',ui.msg('sticky.attachment_removed'));self.status.show()
        except Exception as error:self.error(error)

    def email_note(self):
        if not self.authorize_secret_edit():return False
        if not self.flush():return False
        dialog=ui.widget(Gtk.Dialog,transient_for=self,modal=True,title=ui.msg('sticky.email_note'))
        box=dialog.get_content_area();box.set_spacing(8);box.set_border_width(16)
        recipient=Gtk.Entry();recipient.set_max_length(254);recipient.set_placeholder_text(ui.tr('sticky.email_recipient'))
        subject=Gtk.Entry();subject.set_max_length(200);subject.set_text(self.saved_title)
        box.pack_start(ui.widget(Gtk.Label,label=ui.msg('sticky.email_recipient'),xalign=0),False,False,0)
        box.pack_start(recipient,False,False,0)
        box.pack_start(ui.widget(Gtk.Label,label=ui.msg('sticky.email_subject'),xalign=0),False,False,0)
        box.pack_start(subject,False,False,0)
        feedback=ui.widget(Gtk.Label,wrap=True,xalign=0);box.pack_start(feedback,False,False,0)
        dialog.add_button(ui.tr('sticky.cancel'),Gtk.ResponseType.CANCEL)
        dialog.add_button(ui.tr('sticky.email_continue'),Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT);dialog.show_all();recipient.grab_focus()
        try:
            while dialog.run()==Gtk.ResponseType.ACCEPT:
                try:
                    if self.secret_locked:
                        ui.call(feedback,'set_text',ui.msg('sticky.email_locked'));continue
                    attachments=self.app.store.attachments(self.note['id'])
                    compose_email(recipient.get_text(),subject.get_text(),self.value(),[item['path'] for item in attachments],note_id=self.note['id'])
                    break
                except Exception as error:
                    message=ui.msg('sticky.email_invalid') if str(error).startswith('invalid-') else ui.msg('sticky.email_failed',error=ui.error_message(error))
                    ui.call(feedback,'set_text',message)
        finally:dialog.destroy()
        return False

    def add_options(self,menu):
        def item(title,callback):
            widget=ui.widget(Gtk.MenuItem,label=title);widget.connect('activate',lambda *_:callback());menu.append(widget);return widget
        item(ui.msg('sticky.settings'),self.show_secret_settings)
        attach_item=ui.widget(Gtk.MenuItem,label=ui.msg('sticky.attach_files'))
        attach_item.set_sensitive(not self.secret_locked);attach_item.connect('activate',lambda *_:self.attach_files());menu.append(attach_item)
        email_item=ui.widget(Gtk.MenuItem,label=ui.msg('sticky.email_note'))
        email_item.set_sensitive(not self.secret_locked);email_item.connect('activate',lambda *_:self.email_note());menu.append(email_item)
        if menu is getattr(self,'options_menu',None):
            self.attach_menu_item=attach_item;self.email_menu_item=email_item
        secret=ui.widget(Gtk.CheckMenuItem,label=ui.msg('sticky.secret_note'))
        secret.set_active(bool(self.note.get('secret')))
        secret.connect('toggled',self.toggle_secret)
        self.secret_items.append(secret);menu.append(secret)
        menu.append(Gtk.SeparatorMenuItem())
        item(ui.msg('sticky.new_note'),lambda:self.app.new_card(self))
        restore=item(ui.msg('sticky.restore_size'),self.restore_size)
        restore.set_sensitive(not self.secret_locked)
        colors=Gtk.Menu();parent=ui.widget(Gtk.MenuItem,label=ui.msg('sticky.color'));parent.set_submenu(colors);parent.set_sensitive(not self.secret_locked);menu.append(parent)
        for name,color in zip(NAMES,COLORS):
            entry=ui.widget(Gtk.MenuItem,label=name);entry.connect('activate',lambda _,c=color:self.set_property_value(color=c));colors.append(entry)
        above=ui.widget(Gtk.CheckMenuItem,label=ui.msg('sticky.above'));above.set_active(bool(self.note['above']))
        above.set_sensitive(not self.secret_locked)
        above.connect('toggled',lambda widget:self.set_property_value(above=int(widget.get_active())));menu.append(above)
        item(ui.msg('sticky.hide'),self.hide_note)
        archive=item(ui.msg('sticky.archive'),self.archive_note)
        archive.set_sensitive(not self.secret_locked)
        hidden_menu=Gtk.Menu();hidden_item=ui.widget(Gtk.MenuItem,label=ui.msg('sticky.show_hidden_notes'))
        hidden_item.set_submenu(hidden_menu);menu.append(hidden_item)
        archived_menu=Gtk.Menu();archived_item=ui.widget(Gtk.MenuItem,label=ui.msg('sticky.archived_notes'))
        archived_item.set_submenu(archived_menu);menu.append(archived_item)
        item(ui.msg('sticky.delete_note'),self.delete_note)
        if menu is getattr(self,'options_menu',None):
            self.archive_menu_item=archive
            self.hidden_notes_menu=hidden_menu;self.hidden_notes_item=hidden_item
            self.archived_notes_menu=archived_menu;self.archived_notes_item=archived_item
        item(ui.msg('sticky.quit'),self.app.safe_quit)
        if menu is getattr(self,'options_menu',None):
            self.secret_edit_menu_items=[attach_item,email_item,restore,parent,above,archive]
            self.sync_secret_menu_actions()

    def archive_note(self):
        if not self.alive or not self.authorize_secret_edit() or not self.flush():return False
        self.save_geometry()
        try:self.app.store.properties(self.note['id'],archived=1)
        except Exception as error:
            self.error(error);return False
        self.note['archived']=1
        self.destroy()
        return True

    def delete_note(self):
        if not self.alive:return False
        if self.note.get('secret') and not self.authenticate_secret():return False
        if not self.alive or not self.flush():return False
        try:self.app.store.delete(self.note['id'],self.revision)
        except Exception as error:
            self.error(error);self.text.grab_focus();return False
        if hasattr(self,'attachment_preview_cache'):self.attachment_preview_cache.clear()
        try:purge_note_email_drafts([self.note['id']])
        except Exception as error:
            dialog=ui.widget(Gtk.MessageDialog,transient_for=self,modal=True,message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.CLOSE,text=ui.msg('sticky.email_cache_cleanup_failed',error=ui.error_message(error)))
            dialog.run();dialog.destroy()
        self.destroy();return True

    def insert_emoji(self,editor):
        editor.stop_emission_by_name('insert-emoji')
        if getattr(self,'secret_locked',False):return
        if self.emoji_dialog:
            self.emoji_dialog.present();return
        mark=self.buffer.create_mark(None,self.buffer.get_iter_at_mark(self.buffer.get_insert()),False)
        # Gtk3's chooser is private. Invoke its public TextView action in a roomy
        # transient root rather than letting the tiny sticky window clip the popup.
        dialog=ui.widget(Gtk.Dialog,transient_for=self,modal=True,title=ui.msg('sticky.insert_emoji'))
        dialog.set_default_size(480,440);dialog.set_resizable(False)
        self.emoji_dialog=dialog
        anchor=Gtk.TextView()
        anchor.set_halign(Gtk.Align.CENTER);anchor.set_valign(Gtk.Align.CENTER)
        anchor.set_size_request(1,1)
        dialog.get_content_area().pack_start(anchor,True,True,0)
        dialog.add_button(ui.tr('sticky.cancel'),Gtk.ResponseType.CANCEL)
        def finish(*_):
            if self.emoji_dialog is not dialog:return
            self.emoji_dialog=None
            if self.alive and not getattr(self,'secret_locked',False):
                self.buffer.place_cursor(self.buffer.get_iter_at_mark(mark))
                self.present();self.text.grab_focus()
            self.buffer.delete_mark(mark)
        dialog.connect('destroy',finish)
        dialog.connect('response',lambda *_:dialog.destroy())
        dialog.connect('key-press-event',lambda _w,event: (dialog.destroy() or True) if Gdk.keyval_name(event.keyval)=='Escape' else False)
        def chosen(buffer):
            value=buffer.get_text(buffer.get_start_iter(),buffer.get_end_iter(),True)
            if value and self.alive and not getattr(self,'secret_locked',False):
                self.buffer.insert(self.buffer.get_iter_at_mark(mark),value)
                GLib.idle_add(lambda:dialog.destroy() or False)
        anchor.get_buffer().connect('changed',chosen)
        def open_picker():
            if self.alive and self.emoji_dialog is dialog:
                anchor.grab_focus();anchor.emit('insert-emoji')
            return False
        dialog.show_all();dialog.present();GLib.idle_add(open_picker)

    def cancel_secret_timer(self):
        if self.secret_timer:GLib.source_remove(self.secret_timer);self.secret_timer=0
        self.secret_deadline=0
        if self.secret_counting:self.status.hide();self.secret_counting=False

    def secret_activity(self,*_):
        self.cancel_secret_timer()
        return False

    def unlock_pointer_enter(self,*_):
        window=self.get_window()
        if window:window.set_cursor(Gdk.Cursor.new_from_name(self.get_display(),'pointer'))
        return False

    def unlock_pointer_leave(self,*_):
        window=self.get_window()
        if window:window.set_cursor(None)
        return False

    def unlock_pointer_click(self,_widget,event):
        if event.button==1:self.unlock_secret()
        return True

    def secret_enter(self,_widget,event):
        if event.mode==Gdk.CrossingMode.NORMAL and event.detail!=Gdk.NotifyType.INFERIOR:
            self.secret_activity()
        return False

    def secret_leave(self,_widget,event):
        if event.mode!=Gdk.CrossingMode.NORMAL or event.detail==Gdk.NotifyType.INFERIOR:return False
        # Child crossings can bubble with coordinates relative to their own window.
        if event.window!=self.get_window():return False
        if 0<=event.x<self.get_allocated_width() and 0<=event.y<self.get_allocated_height():return False
        if not self.note.get('secret') or self.secret_locked or self.secret_timer:return False
        self.secret_deadline=GLib.get_monotonic_time()+15_000_000
        self.secret_counting=True;self.secret_tick()
        self.secret_timer=GLib.timeout_add(250,self.secret_tick)
        return False

    def secret_tick(self):
        if not self.alive or self.secret_locked or not self.note.get('secret'):
            self.secret_timer=0;self.secret_counting=False;return False
        seconds=max(0,(self.secret_deadline-GLib.get_monotonic_time()+999999)//1000000)
        if not seconds:
            self.secret_timer=0;self.lock_secret();return False
        ui.call(self.status,'set_text',ui.msg('sticky.secret_countdown',seconds=seconds));self.status.show()
        return True

    def lock_secret(self,*_):
        self.cancel_secret_timer()
        if not self.alive or not self.note.get('secret'):return
        saved=self.flush()
        self.secret_locked=True
        self.status.set_text('');self.status.hide()
        self.sync_secret_menu_actions()
        if self.emoji_dialog:self.emoji_dialog.destroy()
        self.clear_link_hover()
        self.attachment_preview_cache.clear()
        self.secret_stack.set_visible_child_name('locked')
        self.title_field.set_no_show_all(True);self.title_field.hide()
        self.text.set_sensitive(False);self.title_entry.set_sensitive(False)
        if hasattr(self,'attachments_box'):
            self.attachments_box.set_no_show_all(True);self.attachments_box.hide()
        if not saved:
            ui.call(self.status,'set_text',ui.msg('sticky.secret_save_failed'));self.status.show()

    def unlock_secret(self):
        if not self.note.get('secret') or not self.secret_locked:return
        if not self.authenticate_secret() or not self.alive:return
        self.secret_locked=False;self.secret_activity()
        self.sync_secret_menu_actions()
        self.secret_stack.set_visible_child_name('editor')
        self.scroll.show_all()
        self.title_field.set_no_show_all(False);self.title_field.show_all();sync_title_placeholder(self.title_entry,self.title_placeholder)
        self.text.set_sensitive(True);self.title_entry.set_sensitive(True)
        if hasattr(self,'attachments_box'):self.attachments_box.set_no_show_all(False)
        if hasattr(self,'refresh_attachments'):self.refresh_attachments()
        self.text.grab_focus()

    def pin_entry(self,box,message):
        label=ui.widget(Gtk.Label,label=message,xalign=0)
        entry=Gtk.Entry();entry.set_visibility(False);entry.set_max_length(4)
        entry.set_input_purpose(Gtk.InputPurpose.PIN);entry.set_activates_default(True)
        ui.call(entry.get_accessible(),'set_name',message)
        box.pack_start(label,False,False,0);box.pack_start(entry,False,False,0)
        return entry

    def authenticate_secret(self):
        if self.auth_dialog:return False
        self.lock_secret();self.secret_activity()
        dialog=ui.widget(Gtk.Dialog,transient_for=self,modal=True,title=ui.msg('sticky.secret_auth'))
        self.auth_dialog=dialog
        box=dialog.get_content_area();box.set_spacing(8);box.set_border_width(16)
        entry=self.pin_entry(box,ui.msg('sticky.pin'))
        feedback=ui.widget(Gtk.Label,wrap=True,xalign=0);box.pack_start(feedback,False,False,0)
        dialog.add_button(ui.tr('sticky.cancel'),Gtk.ResponseType.CANCEL)
        dialog.add_button(ui.tr('sticky.unlock'),Gtk.ResponseType.ACCEPT);dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        dialog.show_all();entry.grab_focus();accepted=False
        try:
            while self.alive and dialog.run()==Gtk.ResponseType.ACCEPT:
                if not self.alive:break
                pin=entry.get_text();entry.set_text('')
                try:
                    if self.app.store.verify_pin(pin):accepted=True;break
                    ui.call(feedback,'set_text',ui.msg('sticky.pin_incorrect'))
                except Exception as error:
                    retry=getattr(error,'retry_after',None)
                    ui.call(feedback,'set_text',ui.msg('sticky.pin_retry',seconds=retry) if type(retry) is int and retry>0 else ui.error_message(error))
                finally:pin=None
                entry.grab_focus()
        finally:
            self.auth_dialog=None;dialog.destroy();self.secret_activity()
            if self.alive:
                if not self.secret_locked:self.text.grab_focus()
        return accepted

    def show_secret_settings(self):
        if self.settings_dialog:self.settings_dialog.present();return False
        self.secret_activity()
        self.lock_secret()
        try:configured=self.app.store.has_pin()
        except Exception as error:self.error(error);return False
        dialog=ui.widget(Gtk.Dialog,transient_for=self,modal=True,title=ui.msg('sticky.settings'))
        self.settings_dialog=dialog
        box=dialog.get_content_area();box.set_spacing(8);box.set_border_width(16)
        language_row=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=12)
        language_label=ui.widget(Gtk.Label,label=ui.msg('sticky.language'),xalign=0)
        language=Gtk.ComboBoxText()
        language.append('pt-BR',ui.tr('sticky.language_pt_br'))
        language.append('en-US',ui.tr('sticky.language_en_us'))
        language.set_active_id(ui.get_locale())
        language.connect('changed',lambda combo:ui.set_locale(combo.get_active_id()) if combo.get_active_id() else None)
        language_row.pack_start(language_label,True,True,0);language_row.pack_start(language,False,False,0)
        box.pack_start(language_row,False,False,0)
        warning=ui.widget(Gtk.Label,label=ui.msg('sticky.pin_limitation'),wrap=True,xalign=0)
        warning.set_max_width_chars(48);box.pack_start(warning,False,False,0)
        current_group=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
        old=self.pin_entry(current_group,ui.msg('sticky.pin_current')) if configured else None
        if configured:
            forgot_row=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            forgot=ui.widget(Gtk.Button,label=ui.msg('sticky.pin_forgot'))
            forgot.set_relief(Gtk.ReliefStyle.NONE);forgot.get_style_context().add_class('link')
            forgot_row.pack_end(forgot,False,False,0)
            current_group.pack_start(forgot_row,False,False,0)
        if configured:box.pack_start(current_group,False,False,0)
        new=self.pin_entry(box,ui.msg('sticky.pin_new'));confirm=self.pin_entry(box,ui.msg('sticky.pin_confirm'))
        feedback=ui.widget(Gtk.Label,wrap=True,xalign=0);box.pack_start(feedback,False,False,0)
        ui.button(dialog,ui.msg('sticky.cancel'),Gtk.ResponseType.CANCEL)
        ui.button(dialog,ui.msg('sticky.pin_save'),Gtk.ResponseType.ACCEPT);dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        reset_state={'self_deleted':False}
        if configured:
            def forgot_clicked(*_):
                nonlocal configured,old
                try:deleted=self.reset_pin_from_settings(dialog,feedback,old,current_group,new)
                except Exception as error:
                    ui.call(feedback,'set_text',ui.msg('sticky.pin_reset_failed',error=ui.error_message(error)))
                    return
                if deleted is None:return
                configured=False;old=None
                reset_state['self_deleted']=self.note['id'] in deleted
        if configured:forgot.connect('clicked',forgot_clicked)
        dialog.show_all();(old or new).grab_focus();saved=False
        try:
            while self.alive and dialog.run()==Gtk.ResponseType.ACCEPT:
                if not self.alive:break
                previous=old.get_text() if old else None;value=new.get_text();repeated=confirm.get_text()
                if old:old.set_text('')
                new.set_text('');confirm.set_text('')
                try:
                    if len(value)!=4 or any(c not in '0123456789' for c in value) or value!=repeated:
                        ui.call(feedback,'set_text',ui.msg('sticky.pin_format'));continue
                    if configured:self.app.store.change_pin(previous,value)
                    else:self.app.store.set_pin(value)
                    saved=True;break
                except Exception as error:
                    retry=getattr(error,'retry_after',None)
                    ui.call(feedback,'set_text',ui.msg('sticky.pin_retry',seconds=retry) if type(retry) is int and retry>0 else ui.error_message(error))
                finally:previous=value=repeated=None
        finally:
            self.settings_dialog=None;dialog.destroy();self.secret_activity()
            if reset_state['self_deleted'] and self.alive:self.destroy()
        if saved:
            for card in self.app.get_windows():
                if hasattr(card,'lock_secret'):card.lock_secret()
        return saved

    def reset_pin_from_settings(self,settings_dialog,feedback,old,current_group,new):
        confirm=ui.widget(Gtk.MessageDialog,transient_for=settings_dialog,modal=True,
            message_type=Gtk.MessageType.WARNING,buttons=Gtk.ButtonsType.NONE,
            text=ui.msg('sticky.pin_forgot_title'))
        ui.call(confirm,'format_secondary_text',ui.msg('sticky.pin_forgot_warning'))
        confirm.add_button(ui.tr('sticky.cancel'),Gtk.ResponseType.CANCEL)
        confirm.add_button(ui.tr('sticky.pin_forgot_confirm'),Gtk.ResponseType.ACCEPT)
        confirm.set_default_response(Gtk.ResponseType.CANCEL)
        confirm.show_all()
        try:accepted=confirm.run()==Gtk.ResponseType.ACCEPT
        finally:confirm.destroy()
        if not accepted:return None
        try:result=self.app.store.reset_pin_and_delete_secret_notes()
        except Exception as error:
            ui.call(feedback,'set_text',ui.msg('sticky.pin_reset_failed',error=ui.error_message(error)))
            return None
        identities=result['note_ids'];cache_error=None
        try:purge_note_email_drafts(identities)
        except Exception as error:cache_error=ui.error_message(error)
        ids=set(identities)
        for card in self.app.get_windows():
            if not hasattr(card,'note') or card.note.get('id') not in ids:continue
            if hasattr(card,'attachment_preview_cache'):card.attachment_preview_cache.clear()
            if card is self:card.hide()
            else:card.destroy()
        old.set_text('');current_group.hide()
        if cache_error:
            message=ui.msg('sticky.pin_reset_cache_warning',error=cache_error)
        elif not result['wal_cleaned']:
            message=ui.msg('sticky.pin_reset_storage_warning')
        else:message=ui.msg('sticky.pin_reset_complete')
        ui.call(feedback,'set_text',message);new.grab_focus()
        return identities

    def toggle_secret(self,widget):
        if self.secret_syncing:return
        selected=widget.get_active();current=bool(self.note.get('secret'))
        if selected==current:return
        try:
            if selected and not self.app.store.has_pin():
                if not self.show_secret_settings():return
            if not selected and not self.authenticate_secret():return
            if not self.alive or not self.flush():return
            self.revision=self.app.store.set_secret(self.note['id'],selected,self.revision)
            self.note['secret']=int(selected)
            if selected:self.lock_secret()
            else:
                self.secret_locked=False;self.secret_activity();self.secret_stack.set_visible_child_name('editor')
                self.scroll.show_all()
                self.sync_secret_menu_actions()
                self.title_field.set_no_show_all(False);self.title_field.show_all();sync_title_placeholder(self.title_entry,self.title_placeholder)
                self.text.set_sensitive(True);self.title_entry.set_sensitive(True)
                if hasattr(self,'attachments_box'):self.attachments_box.set_no_show_all(False)
                if hasattr(self,'refresh_attachments'):self.refresh_attachments()
                self.text.grab_focus()
        except Exception as error:self.error(error)
        finally:
            self.secret_syncing=True
            for item in self.secret_items:item.set_active(bool(self.note.get('secret')))
            self.secret_syncing=False

    def close_requested(self,*_):
        self.hide_note()
        return True

    def hide_note(self):
        if not self.flush():return False
        # A window can be hidden or closed before the debounced configure
        # callback runs. Persist its final native position while it is still
        # visible and before locking a secret note.
        self.save_geometry()
        # Do not rely solely on Gtk's unmap signal: hiding the native window
        # must synchronously put secret notes back behind the PIN screen.
        self.lock_secret()
        self.hide()
        return True

    def expanded(self):
        window=self.get_window()
        return bool(window and window.get_state()&(Gdk.WindowState.MAXIMIZED|Gdk.WindowState.FULLSCREEN))

    def restore_size(self):
        if not self.authorize_secret_edit():return False
        self.pending_restore=True
        self.unmaximize();self.unfullscreen()
        if not self.expanded():
            self.pending_restore=False;self.resize(310,300)

    def state_changed(self,_window,event):
        expanded=event.new_window_state&(Gdk.WindowState.MAXIMIZED|Gdk.WindowState.FULLSCREEN)
        if self.pending_restore and not expanded:
            self.pending_restore=False;self.resize(310,300)
        return False

    def configured(self,*_):
        if self.secret_locked:return False
        if self.geometry_timer:GLib.source_remove(self.geometry_timer)
        self.geometry_timer=GLib.timeout_add(400,self.save_geometry)
        return False

    def save_geometry(self):
        if self.geometry_timer:GLib.source_remove(self.geometry_timer);self.geometry_timer=0
        if self.secret_locked or self.expanded():return False
        x,y=self.get_position();width,height=self.get_size()
        self.note.update(x=x,y=y,width=width,height=height)
        try:self.app.store.properties(self.note['id'],x=x,y=y,width=width,height=height)
        except Exception as error:self.error(error)
        return False

    def destroyed(self,*_):
        self.alive=False
        if hasattr(self,'cancel_secret_timer'):self.cancel_secret_timer()
        for dialog in [getattr(self,'auth_dialog',None),getattr(self,'settings_dialog',None)]:
            if dialog:dialog.destroy()
        if self.emoji_dialog:self.emoji_dialog.destroy()
        for timer in [self.history_timer,self.geometry_timer]:
            if timer:GLib.source_remove(timer)
        self.history_timer=0;self.geometry_timer=0

