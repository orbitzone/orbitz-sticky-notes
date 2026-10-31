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
    gi.require_version('GtkSource','4')
    from gi.repository import GtkSource
except (ImportError,ValueError):
    GtkSource=None
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
CODE_LANGUAGES=(
    ('python','Python'),('javascript','JavaScript'),('typescript','TypeScript'),
    ('json','JSON'),('html','HTML'),('css','CSS'),('c','C'),('cpp','C++'),
    ('rust','Rust'),('go','Go'),('java','Java'),('sql','SQL'),('sh','Shell'),
    ('markdown','Markdown'),('plain','Plain text'),
)
CODE_SOURCE_IDS={'javascript':'js'}


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


def resize_grip(callback,label=None):
    grip=Gtk.Button();grip.set_relief(Gtk.ReliefStyle.NONE);grip.set_focus_on_click(False)
    grip.set_can_focus(True)
    grip.set_size_request(28,28)
    grip.set_halign(Gtk.Align.END);grip.set_valign(Gtk.Align.END)
    grip.set_margin_end(2);grip.set_margin_bottom(2)
    icon=ui.widget(Gtk.Label,label='◢');icon.set_halign(Gtk.Align.END);icon.set_valign(Gtk.Align.END)
    icon.set_margin_end(4);icon.set_margin_bottom(4);grip.add(icon)
    ui.call(grip.get_accessible(),'set_name',label or ui.msg('sticky.resize'))
    grip.connect('button-press-event',callback)
    grip.connect('realize',lambda widget:widget.get_window().set_cursor(
        Gdk.Cursor.new_from_name(widget.get_display(),'se-resize')))
    return grip


def resize_edge(callback,edge,cursor_name,*,width=-1,height=-1,halign=Gtk.Align.FILL,valign=Gtk.Align.FILL):
    """Add an invisible native resize target along an undecorated window edge."""
    handle=Gtk.EventBox();handle.set_visible_window(False);handle.set_above_child(True)
    handle.set_size_request(width,height);handle.set_halign(halign);handle.set_valign(valign)
    handle.connect('button-press-event',callback,edge)
    handle.connect('realize',lambda widget:widget.get_window().set_cursor(
        Gdk.Cursor.new_from_name(widget.get_display(),cursor_name)))
    return handle


def secret_lock_icon():
    """Load the bundled, fixed-color PIN keypad and touch icon."""
    return Gtk.Image.new_from_file(str(Path(__file__).with_name('secret-pin.png')))


def sync_title_placeholder(entry,placeholder):
    """Keep the title hint visible over GTK's focused empty entry."""
    placeholder.set_visible(not bool(entry.get_text()))


class Card(Gtk.ApplicationWindow):
    def __init__(self,app,note):
        super().__init__(application=app,title=ui.tr('sticky.window_title'))
        note=dict(note)
        self.code_mode=bool(note.get('code_mode',0))
        self.code_language=note.get('code_language') or 'python'
        safe_code_title=ui.msg('sticky.sticky_code') if note.get('secret') else (note.get('title') or ui.msg('sticky.sticky_code'))
        ui.set(self,'title',ui.msg('sticky.code_window_title',title=safe_code_title) if self.code_mode else ui.msg('sticky.window_title'))
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
        self.history_timer=0;self.geometry_timer=0;self.menu_pointer_timer=0;self.menu_buttons_down=0;self.alive=True;self.pending_restore=False
        self.keyboard_geometry_mode=None;self.keyboard_geometry_previous_status=None
        self._rounded_shape_size=None
        # Keep the note grouped under the app icon in GNOME Dash so the
        # launcher shows its running indicator whenever a note is visible.
        # Both note types use their own header. In code mode this avoids
        # stacking a native titlebar over the custom editor header.
        self.set_decorated(False);self.set_skip_taskbar_hint(False)
        self.set_default_size(note['width'],note['height'])
        minimum_width,minimum_height=(320,220) if self.code_mode else (180,120)
        self.set_size_request(minimum_width,minimum_height)
        # Tell the window manager the actual minimum explicitly. A child's
        # natural requisition can otherwise leak into WM resize hints even
        # when it lives inside a ScrolledWindow.
        geometry=Gdk.Geometry();geometry.min_width=minimum_width;geometry.min_height=minimum_height
        self.set_geometry_hints(None,geometry,Gdk.WindowHints.MIN_SIZE)
        self.set_focus_on_map(False);self.set_keep_above(bool(note['above']));self.stick()
        visual=self.get_screen().get_rgba_visual()
        if visual and not self.code_mode:self.set_visual(visual)
        self.css=Gtk.CssProvider()
        self.get_style_context().add_class('postit')
        self.get_style_context().add_provider(self.css,Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.connect('realize',self.update_rounded_shape)
        self.connect('size-allocate',self.update_rounded_shape)
        outer=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0 if self.code_mode else 12,margin=0 if self.code_mode else 18)
        if self.code_mode:outer.set_name('sticky-code-frame')
        outer.set_margin_top(0)
        outer.set_margin_bottom(0 if self.code_mode else 30)  # Keep the corner hit target clear of editable text.
        overlay=Gtk.Overlay();overlay.add(outer);self.add(overlay)
        self.move_handle=Gtk.Button();self.move_handle.set_name('sticky-note-move-handle')
        self.move_handle.set_relief(Gtk.ReliefStyle.NONE);self.move_handle.set_focus_on_click(False)
        self.move_handle.set_can_focus(True);self.move_handle.set_size_request(-1,16 if self.code_mode else 24)
        ui.call(self.move_handle.get_accessible(),'set_name',ui.msg('sticky.move_window' if self.code_mode else 'sticky.move_note'))
        ui.call(self.move_handle.get_accessible(),'set_description',ui.msg('sticky.keyboard_move_help'))
        self.move_handle.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.move_handle.connect('realize',lambda widget:widget.get_window().set_cursor(
            Gdk.Cursor.new_from_name(widget.get_display(),'move')))
        self.move_handle.connect('button-press-event',self.header_drag_press)
        self.move_handle.connect('key-press-event',self.keyboard_geometry_key_press,'move')
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
        if self.code_mode:self.menu_button.get_style_context().add_class('sticky-code-menu')
        ui.call(self.menu_button.get_accessible(),'set_name',ui.msg('sticky.note_menu'))
        heading_row=Gtk.Box(spacing=8)
        if self.code_mode:heading_row.set_name('sticky-code-header')
        heading_row.pack_start(header,False,False,0)
        self.secret_badge=Gtk.DrawingArea()
        self.secret_badge.set_name('sticky-secret-lock')
        self.secret_badge.set_no_show_all(True)
        self.secret_badge.set_can_focus(False);self.secret_badge.set_size_request(16,18)
        self.secret_badge.connect('draw',self.draw_secret_badge)
        ui.call(self.secret_badge.get_accessible(),'set_name',ui.msg('sticky.secret_note'))
        heading_row.pack_start(self.secret_badge,False,False,0)
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
        self.title_entry.connect('key-press-event',self.secret_escape_press)
        self.title_entry.connect('activate',lambda *_:self.flush())
        self.title_entry.connect('focus-out-event',self.focus_out)
        heading_row.pack_start(title_field,True,True,0)
        self.close_button=Gtk.Button.new_from_icon_name('window-close-symbolic',Gtk.IconSize.MENU)
        self.close_button.set_name('sticky-code-close' if self.code_mode else 'sticky-note-close')
        self.close_button.set_relief(Gtk.ReliefStyle.NONE)
        ui.call(self.close_button.get_accessible(),'set_name',ui.msg('sticky.close'))
        self.close_button.connect('clicked',lambda *_:self.close_requested())
        heading_row.pack_end(self.close_button,False,False,0)
        heading_region=heading_row
        if self.code_mode:heading_region=self.wrap_code_drag_region(heading_row)
        header_area.pack_start(heading_region,False,False,0)
        outer.pack_start(header_area,False,False,0)
        header.add(self.menu_button)
        # Keep right-click access on the header, but the header no longer starts
        # a custom drag; GNOME's Super+drag remains available everywhere.
        header.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        header.connect('button-press-event',self.context_menu_press)
        self.text=GtkSource.View.new() if self.code_mode and GtkSource else Gtk.TextView(wrap_mode=Gtk.WrapMode.NONE if self.code_mode else Gtk.WrapMode.WORD_CHAR)
        self.text.set_name('sticky-note-text')
        ui.call(self.text.get_accessible(),'set_name',ui.msg('sticky.code_editor' if self.code_mode else 'sticky.note_content'))
        # Keep editor natural content size from imposing a window minimum.
        # Long text/code stays in the scroll view while the note can shrink.
        self.text.set_size_request(1,1);self.text.set_hexpand(True);self.text.set_vexpand(True)
        if self.code_mode:
            self.text.set_monospace(True)
            self.text.set_left_margin(8);self.text.set_right_margin(8);self.text.set_top_margin(8);self.text.set_bottom_margin(8)
            if GtkSource and isinstance(self.text,GtkSource.View):
                self.text.set_show_line_numbers(True);self.text.set_auto_indent(True)
                self.text.set_indent_width(4);self.text.set_tab_width(4);self.text.set_insert_spaces_instead_of_tabs(True)
                self.text.set_highlight_current_line(True);self.text.set_show_right_margin(False)
        # External file drops attach files without replacing editable text.
        self.text.drag_dest_set(Gtk.DestDefaults.ALL,file_targets,Gdk.DragAction.COPY)
        self.text.connect('drag-data-received',self.file_drop_received)
        self.buffer=GtkSource.Buffer() if self.code_mode and GtkSource else self.text.get_buffer()
        if self.code_mode and GtkSource:
            self.text.set_buffer(self.buffer)
            self.configure_code_buffer()
        self.style_tags={
            'bold':self.buffer.create_tag('text-bold',weight=Pango.Weight.BOLD),
            'italic':self.buffer.create_tag('text-italic',style=Pango.Style.ITALIC),
            'underline':self.buffer.create_tag('text-underline',underline=Pango.Underline.SINGLE),
        }
        if self.code_mode:self.buffer.set_text(self.saved_plain)
        else:self.restore_document(self.saved)
        self.link_tag=self.buffer.create_tag('ctrl-link',weight=Pango.Weight.BOLD)
        self.hover_link=None
        self.link_cursor=Gdk.Cursor.new_from_name(display,'pointer')
        self.edit_cursor=Gdk.Cursor.new_from_name(display,'text')
        self.scroll,self.scrollbar=editor_scroll(self.text);scroll=self.scroll
        if self.code_mode:scroll.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC)
        self.code_toolbar=None;self.code_status=None;self.code_language_combo=None
        editor_content=scroll
        if self.code_mode:
            editor_content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0)
            self.code_toolbar=self.build_code_toolbar()
            editor_content.pack_start(self.wrap_code_drag_region(self.code_toolbar),False,False,0)
            editor_content.pack_start(scroll,True,True,0)
        self.secret_stack=Gtk.Stack();self.secret_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.secret_stack.set_hhomogeneous(False);self.secret_stack.set_vhomogeneous(False)
        self.secret_stack.add_named(editor_content,'editor')
        locked=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6)
        locked.set_halign(Gtk.Align.CENTER);locked.set_valign(Gtk.Align.CENTER)
        lock_image=secret_lock_icon()
        # A real button exposes the native push-button role and keyboard
        # activation; focus styling is distinct from transparent mouse hover.
        self.unlock_button=Gtk.Button();self.unlock_button.set_name('sticky-secret-unlock-control')
        self.unlock_button.set_relief(Gtk.ReliefStyle.NONE);self.unlock_button.set_focus_on_click(False)
        self.unlock_button.set_can_focus(True);self.unlock_button.set_size_request(88,88)
        self.unlock_button.add(lock_image)
        ui.call(self.unlock_button.get_accessible(),'set_name',ui.msg('sticky.secret_unlock_accessible'))
        ui.call(self.unlock_button.get_accessible(),'set_description',ui.msg('sticky.secret_unlock_keyboard_help'))
        self.unlock_button.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK|Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.unlock_button.connect('enter-notify-event',self.unlock_pointer_enter)
        self.unlock_button.connect('leave-notify-event',self.unlock_pointer_leave)
        self.unlock_button.connect('clicked',self.unlock_pointer_click)
        locked.pack_start(self.unlock_button,False,False,0)
        self.secret_stack.add_named(locked,'locked');outer.pack_start(self.secret_stack,True,True,0)
        self.attachments_box=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=3)
        outer.pack_start(self.attachments_box,False,False,0)
        self.refresh_attachments()
        self.status=ui.widget(Gtk.Label,xalign=0,wrap=True);self.status.set_no_show_all(True)
        outer.pack_start(self.status,False,False,0)
        # Undecorated windows have no compositor-provided resize border.
        # Give both note templates resize targets on every side and corner.
        handles=(
            resize_edge(self.resize_edge_press,Gdk.WindowEdge.NORTH,'n-resize',height=5,valign=Gtk.Align.START),
            resize_edge(self.resize_edge_press,Gdk.WindowEdge.SOUTH,'s-resize',height=5,valign=Gtk.Align.END),
            resize_edge(self.resize_edge_press,Gdk.WindowEdge.WEST,'w-resize',width=5,halign=Gtk.Align.START),
            resize_edge(self.resize_edge_press,Gdk.WindowEdge.EAST,'e-resize',width=5,halign=Gtk.Align.END),
            resize_edge(self.resize_edge_press,Gdk.WindowEdge.NORTH_WEST,'nw-resize',width=12,height=12,halign=Gtk.Align.START,valign=Gtk.Align.START),
            resize_edge(self.resize_edge_press,Gdk.WindowEdge.NORTH_EAST,'ne-resize',width=12,height=12,halign=Gtk.Align.END,valign=Gtk.Align.START),
            resize_edge(self.resize_edge_press,Gdk.WindowEdge.SOUTH_WEST,'sw-resize',width=12,height=12,halign=Gtk.Align.START,valign=Gtk.Align.END),
        )
        for handle in handles:
            overlay.add_overlay(handle);overlay.set_overlay_pass_through(handle,False)
        grip=resize_grip(self.resize_press,ui.msg('sticky.resize_window' if self.code_mode else 'sticky.resize'))
        grip.set_name('sticky-note-resize-grip')
        grip.connect('key-press-event',self.keyboard_geometry_key_press,'resize')
        ui.call(grip.get_accessible(),'set_description',ui.msg('sticky.keyboard_resize_help'))
        overlay.add_overlay(grip);overlay.set_overlay_pass_through(grip,False)
        self.apply_color()
        self.buffer.connect('changed',self.changed)
        self.buffer.connect_after('insert-text',self.apply_typing_styles)
        self.emoji_dialog=None
        self.text.connect('insert-emoji',self.insert_emoji)
        self.text.connect('populate-popup',self.populate_popup)
        if not self.code_mode:self.text.connect('button-press-event',self.text_press)
        self.text.connect('key-press-event',self.text_format_key_press)
        self.text.connect('key-press-event',self.secret_escape_press)
        if not self.code_mode:
            self.text.add_events(Gdk.EventMask.POINTER_MOTION_MASK|Gdk.EventMask.ENTER_NOTIFY_MASK|Gdk.EventMask.LEAVE_NOTIFY_MASK)
            self.text.connect('motion-notify-event',self.link_motion)
            self.text.connect('enter-notify-event',self.link_motion)
            self.text.connect('leave-notify-event',lambda *_:self.clear_link_hover())
        self.connect('key-release-event',self.link_key_release)
        self.options_menu=Gtk.Menu()
        self.add_options(self.options_menu)
        self.options_menu.show_all()
        self.options_menu.connect('show',lambda *_:self.menu_opened())
        self.options_menu.connect('hide',self.menu_closed)
        self.options_menu.connect('key-press-event',self.menu_escape_press)
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
        self.sync_secret_badge()
        self.show()
        # One normal GTK placement, outside the Shell process, after mapping.
        self.move(note['x'],note['y'])
        for widget in [outer,self.move_handle,header_area,heading_row,header,self.menu_button,title_field,self.title_entry,self.title_placeholder,self.close_button,self.text,scroll,self.scrollbar,self.status,grip,*grip.get_children()]:
            widget.get_style_context().add_provider(self.css,Gtk.STYLE_PROVIDER_PRIORITY_USER)
        if self.code_mode:self.update_code_status()

    def configure_code_buffer(self):
        self.buffer.set_highlight_syntax(True)
        self.buffer.set_highlight_matching_brackets(True)
        self.code_language_manager=GtkSource.LanguageManager.get_default()
        language_id=None if self.code_language=='plain' else CODE_SOURCE_IDS.get(self.code_language,self.code_language)
        language=self.code_language_manager.get_language(language_id) if language_id else None
        self.buffer.set_language(language)

    def update_code_window_title(self):
        if not self.code_mode:return
        title=ui.msg('sticky.sticky_code') if self.secret_locked else (self.title_entry.get_text().strip() or ui.msg('sticky.sticky_code'))
        ui.set(self,'title',ui.msg('sticky.code_window_title',title=title))

    def build_code_toolbar(self):
        toolbar=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=8)
        toolbar.get_style_context().add_class('sticky-code-toolbar')
        language_label=ui.widget(Gtk.Label,label=ui.msg('sticky.code_language'),xalign=0)
        self.code_language_combo=Gtk.ComboBoxText()
        ui.call(self.code_language_combo.get_accessible(),'set_name',ui.msg('sticky.code_language'))
        language_label.set_mnemonic_widget(self.code_language_combo)
        for identity,label in CODE_LANGUAGES:self.code_language_combo.append(identity,label)
        if self.code_language not in dict(CODE_LANGUAGES):self.code_language='python'
        self.code_language_combo.set_active_id(self.code_language)
        self.code_language_combo.connect('changed',self.code_language_changed)
        copy=ui.widget(Gtk.Button,label=ui.msg('sticky.copy_code'))
        copy.connect('clicked',self.copy_code)
        toolbar.pack_start(language_label,False,False,0)
        toolbar.pack_start(self.code_language_combo,False,False,0)
        toolbar.pack_end(copy,False,False,0)
        self.code_status=ui.widget(Gtk.Label,xalign=1)
        self.code_status.set_hexpand(True)
        toolbar.pack_start(self.code_status,True,True,8)
        self.buffer.connect('mark-set',lambda *_:self.update_code_status())
        return toolbar

    def code_language_changed(self,combo):
        if not self.code_mode or self.secret_locked:return
        language=combo.get_active_id()
        if not language or language==self.code_language:return
        if not self.authorize_secret_edit():return
        try:
            self.revision=self.app.store.set_code_language(self.note['id'],language,self.revision)
        except Exception as error:
            self.error(error);return
        self.code_language=language;self.note['code_language']=language
        if GtkSource and isinstance(self.text,GtkSource.View):
            language_id=None if language=='plain' else CODE_SOURCE_IDS.get(language,language)
            source_language=self.code_language_manager.get_language(language_id) if language_id else None
            self.buffer.set_language(source_language)
        self.update_code_status()

    def update_code_status(self):
        if not self.code_mode or not self.code_status:return
        cursor=self.buffer.get_iter_at_mark(self.buffer.get_insert())
        label=dict(CODE_LANGUAGES).get(self.code_language,'Python')
        ui.call(self.code_status,'set_text',ui.msg('sticky.code_position',language=label,line=cursor.get_line()+1,column=cursor.get_line_offset()+1))

    def copy_code(self,*_):
        if self.secret_locked:return
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.value(),-1)
        ui.call(self.code_status,'set_text',ui.msg('sticky.code_copied'))
        GLib.timeout_add_seconds(2,lambda:self.update_code_status() or False)

    def reconcile_latest_note(self):
        """Refresh harmless external changes before switching editor mode."""
        latest=self.app.store.get(self.note['id'])
        if (bool(latest.get('code_mode'))!=self.code_mode
                or bool(latest.get('secret'))!=bool(self.note.get('secret'))):
            return False,latest
        if self.dirty and latest['text']!=self.saved:return False,latest
        if self.title_dirty and (latest.get('title') or '')!=self.saved_title:return False,latest
        if not self.dirty and latest['text']!=self.saved:
            self.loading=True
            try:
                if self.code_mode:self.buffer.set_text(decode_document(latest['text'])[0])
                else:self.restore_document(latest['text'])
            finally:self.loading=False
            self.saved=latest['text'];self.saved_plain=self.value();self.dirty=False
            self.history=[self.document_value()];self.index=0
        if not self.title_dirty and (latest.get('title') or '')!=self.saved_title:
            self.saved_title=latest.get('title') or ''
            self.title_entry.set_text(self.saved_title);self.title_dirty=False
            sync_title_placeholder(self.title_entry,self.title_placeholder)
        self.revision=latest['revision'];self.note=latest
        if latest.get('code_language')!=self.code_language:
            self.code_language=latest.get('code_language') or 'python'
            if self.code_language_combo:self.code_language_combo.set_active_id(self.code_language)
            if self.code_mode and GtkSource and isinstance(self.text,GtkSource.View):
                language_id=None if self.code_language=='plain' else CODE_SOURCE_IDS.get(self.code_language,self.code_language)
                self.buffer.set_language(self.code_language_manager.get_language(language_id) if language_id else None)
        self.update_code_window_title()
        return True,latest

    def code_conflict_choice(self,latest):
        dialog=ui.widget(Gtk.MessageDialog,transient_for=self,modal=True,
            message_type=Gtk.MessageType.WARNING,buttons=Gtk.ButtonsType.NONE,
            text=ui.msg('sticky.code_conflict_title'))
        ui.call(dialog,'format_secondary_text',ui.msg('sticky.code_conflict_body'))
        ui.button(dialog,ui.msg('sticky.cancel'),Gtk.ResponseType.CANCEL)
        ui.button(dialog,ui.msg('sticky.code_use_saved'),Gtk.ResponseType.NO)
        ui.button(dialog,ui.msg('sticky.code_keep_mine'),Gtk.ResponseType.YES)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response=dialog.run();dialog.destroy()
        if response==Gtk.ResponseType.NO:return latest['text'],latest.get('title') or ''
        if response==Gtk.ResponseType.YES:return self.value(),self.title_entry.get_text().strip()
        return None

    def discard_duplicate_windows(self,identity):
        for window in list(self.app.get_windows()):
            note=getattr(window,'note',None)
            if window is not self and isinstance(note,dict) and note.get('id')==identity:
                window.destroy()

    def resolve_close_conflict(self):
        """Resolve a stale edit before a close/hide/quit can proceed."""
        try:
            latest=self.app.store.get(self.note['id'])
            if latest['revision']==self.revision:return False
            rebased,latest=self.reconcile_latest_note()
            if rebased and self.flush():return True
            latest=self.app.store.get(self.note['id'])
            can_keep=(not self.secret_locked and bool(latest.get('code_mode'))==self.code_mode
                and bool(latest.get('secret'))==bool(self.note.get('secret')))
            dialog=ui.widget(Gtk.MessageDialog,transient_for=self,modal=True,
                message_type=Gtk.MessageType.WARNING,buttons=Gtk.ButtonsType.NONE,
                text=ui.msg('sticky.close_conflict_title'))
            ui.call(dialog,'format_secondary_text',ui.msg('sticky.close_conflict_body'))
            ui.button(dialog,ui.msg('sticky.cancel'),Gtk.ResponseType.CANCEL)
            ui.button(dialog,ui.msg('sticky.close_use_saved'),Gtk.ResponseType.NO)
            if can_keep:ui.button(dialog,ui.msg('sticky.close_keep_mine'),Gtk.ResponseType.YES)
            dialog.set_default_response(Gtk.ResponseType.CANCEL)
            response=dialog.run();dialog.destroy()
            if response==Gtk.ResponseType.CANCEL:return False
            if response==Gtk.ResponseType.YES and can_keep:
                value=self.document_value();title=self.title_entry.get_text().strip()
                self.revision=self.app.store.resolve_note_conflict(self.note['id'],latest['revision'],
                    value,title,code_mode=self.code_mode,secret=bool(latest.get('secret')))
                self.note.update(text=value,title=title,revision=self.revision)
                self.saved=value;self.saved_plain=self.value();self.saved_title=title
                self.dirty=False;self.title_dirty=False;self.status.hide()
                return True
            if response!=Gtk.ResponseType.NO:return False
            replace=(bool(latest.get('code_mode'))!=self.code_mode
                or bool(latest.get('secret'))!=bool(self.note.get('secret'))
                or latest.get('code_language')!=self.code_language)
            if replace:
                replacement=Card(self.app,latest)
                self.app.fit_monitor(replacement,saved=True)
                replacement.hide()
                self.destroy()
                return True
            self.loading=True
            try:
                if self.code_mode:self.buffer.set_text(decode_document(latest['text'])[0])
                else:self.restore_document(latest['text'])
                self.saved=latest['text'];self.saved_plain=self.value()
                self.saved_title=latest.get('title') or '';self.title_entry.set_text(self.saved_title)
            finally:self.loading=False
            self.revision=latest['revision'];self.note=latest
            self.dirty=False;self.title_dirty=False
            sync_title_placeholder(self.title_entry,self.title_placeholder)
            self.update_code_window_title();self.apply_color()
            if latest.get('secret'):self.lock_secret()
            return True
        except Exception as error:
            self.error(error)
            return False

    def toggle_code_mode(self,widget):
        if getattr(self,'code_syncing',False):return
        selected=bool(widget.get_active())
        if selected==self.code_mode:return
        if not self.authorize_secret_edit():
            self.code_syncing=True;widget.set_active(self.code_mode);self.code_syncing=False
            return
        identity=self.note['id'];old_mode=self.code_mode
        if not self.dirty and not self.title_dirty:
            try:
                rebased,latest=self.reconcile_latest_note()
                if not rebased:
                    ui.call(self.status,'set_text',ui.msg('sticky.code_mode_conflict_state'));self.status.show()
                    self.code_syncing=True;widget.set_active(old_mode);self.code_syncing=False
                    return
            except Exception as error:
                self.error(error)
                self.code_syncing=True;widget.set_active(old_mode);self.code_syncing=False
                return
        if not self.flush():
            try:
                latest=self.app.store.get(identity)
                if latest['revision']==self.revision:
                    self.code_syncing=True;widget.set_active(old_mode);self.code_syncing=False
                    return
                rebased,latest=self.reconcile_latest_note()
                if rebased and self.flush():
                    pass
                else:
                    # If both processes edited the contents, make the choice
                    # explicit instead of silently dropping either version.
                    latest=self.app.store.get(identity)
                    if (bool(latest.get('secret'))!=bool(self.note.get('secret'))
                            or bool(latest.get('code_mode'))!=old_mode):
                        ui.call(self.status,'set_text',ui.msg('sticky.code_mode_conflict_state'));self.status.show()
                        self.code_syncing=True;widget.set_active(old_mode);self.code_syncing=False
                        return
                    choice=self.code_conflict_choice(latest)
                    if choice is None:
                        self.code_syncing=True;widget.set_active(old_mode);self.code_syncing=False
                        return
                    next_text,next_title=choice
                    self.save_geometry()
                    width,height=(900,620) if selected else (310,300)
                    self.revision=self.app.store.transition_code_mode(identity,selected,latest['revision'],
                        text=next_text,title=next_title,width=width,height=height)
                    self.hide()
                    try:
                        replacement=Card(self.app,self.app.store.get(identity))
                        self.app.fit_monitor(replacement,saved=True)
                    except Exception:
                        self.discard_duplicate_windows(identity)
                        current=self.app.store.get(identity)
                        self.revision=self.app.store.set_code_mode(identity,old_mode,current['revision'])
                        self.show();self.present()
                        raise
                    self.destroy();replacement.present();return
            except Exception as error:
                self.error(error)
                self.code_syncing=True;widget.set_active(old_mode);self.code_syncing=False
                return
        try:
            if selected and self.document_value()!=self.value():
                self.revision=self.app.store.text(identity,self.value(),self.revision)
                self.saved=self.value();self.saved_plain=self.saved;self.dirty=False
            self.save_geometry()
            width,height=(900,620) if selected else (310,300)
            next_text=self.value() if selected else self.saved
            next_title=self.title_entry.get_text().strip()
            self.revision=self.app.store.transition_code_mode(identity,selected,self.revision,
                text=next_text,title=next_title,width=width,height=height)
            self.hide()
            replacement=Card(self.app,self.app.store.get(identity))
            self.app.fit_monitor(replacement,saved=True)
        except Exception as error:
            self.discard_duplicate_windows(identity)
            try:
                current=self.app.store.get(identity)
                if bool(current.get('code_mode'))!=old_mode:
                    revision=self.app.store.set_code_mode(identity,old_mode,current['revision'])
                    self.app.store.properties(identity,width=self.note['width'],height=self.note['height'])
                    self.revision=revision
            except Exception:pass
            if self.alive and not self.get_visible():self.show();self.present()
            self.error(error)
            self.code_syncing=True;widget.set_active(old_mode);self.code_syncing=False
            return
        self.destroy()
        replacement.present()

    def value(self):return self.buffer.get_text(self.buffer.get_start_iter(),self.buffer.get_end_iter(),True)

    def document_value(self):
        if self.code_mode:return self.value()
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
        if self.code_mode or self.loading or self.secret_locked or not self.typing_styles:return
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
        if key=='e':self.text.emit('insert-emoji');return True
        if self.code_mode:return False
        style={'b':'bold','i':'italic','u':'underline'}.get(key)
        if style:return self.toggle_format(style)
        return False

    def secret_escape_press(self,_widget,event):
        if (Gdk.keyval_name(event.keyval)=='Escape' and self.note.get('secret')
                and not self.secret_locked):
            self.lock_secret()
            return True
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
        self.set_opacity(0.85 if self.note.get('reduced_opacity') else 1.0)
        if self.code_mode:
            self.get_style_context().add_class('sticky-code-window')
            self.css.load_from_data(b'''
            window.sticky-code-window {background-color:#101113;color:#e4e7ef;}
            box#sticky-code-frame {background-color:#101113;color:#e4e7ef;border:0;border-radius:0;padding:0;}
            box#sticky-code-header {background-color:#191a1d;border:0;padding:8px 12px;}
            eventbox#sticky-note-move-handle {background-color:#191a1d;border:0;}
            textview, textview text, label, eventbox, scrolledwindow, viewport {background-color:#101113;color:#e4e7ef;}
            scrolledwindow#sticky-note-scroll, scrolledwindow#sticky-note-scroll viewport, scrolledwindow#sticky-note-scroll undershoot, scrolledwindow#sticky-note-scroll overshoot, scrolledwindow#sticky-note-scroll junction {border:0;background-color:#101113;background-image:none;box-shadow:none;}
            textview#sticky-note-text, textview#sticky-note-text.view, textview#sticky-note-text:focus, textview#sticky-note-text.view:focus, textview#sticky-note-text text {border:none;background-color:#101113;background-image:none;box-shadow:none;outline:none;padding:0;}
            textview#sticky-note-text {font:12px Monospace;caret-color:#f8f8f2;}
            entry#sticky-note-title {font:bold 14px Sans;color:#f8f8f2;background:transparent;border:0;box-shadow:none;padding:0;}
            button {background:#25272b;border:0;border-radius:4px;color:#e4e7ef;padding:6px 12px;}
            button:hover {background:#303237;}
            button#sticky-code-close, button.sticky-code-menu {background:transparent;border:0;box-shadow:none;color:#c7c9cc;padding:0;min-width:28px;min-height:28px;}
            button#sticky-code-close:hover {background:#c42b1c;color:#ffffff;}
            button.sticky-code-menu:hover {background:#292b2f;color:#ffffff;}
            button#sticky-note-move-handle, button#sticky-note-resize-grip, button#sticky-secret-unlock-control {background:transparent;background-image:none;border:0;box-shadow:none;padding:0;}
            button#sticky-note-move-handle:hover, button#sticky-note-resize-grip:hover, button#sticky-secret-unlock-control:hover, button#sticky-secret-unlock-control:active {background:transparent;background-image:none;border:0;box-shadow:none;}
            button#sticky-note-move-handle:focus, button#sticky-note-resize-grip:focus, button#sticky-secret-unlock-control:focus {background:transparent;background-image:none;border:2px solid #586b78;box-shadow:none;outline:none;border-radius:3px;}
            combobox, combobox button {color:#e4e7ef;}
            label {font:11px Sans;color:#aab0bf;}
            box.sticky-code-toolbar {background-color:#151619;border:0;padding:8px 12px;}
            ''' )
            if GtkSource and isinstance(self.text,GtkSource.View):
                manager=GtkSource.StyleSchemeManager.get_default()
                scheme=manager.get_scheme('oblivion') or manager.get_scheme('classic')
                if scheme:self.buffer.set_style_scheme(scheme)
            return
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
        button#sticky-note-move-handle, button#sticky-note-resize-grip, button#sticky-secret-unlock-control {{background:transparent;background-image:none;border:0;box-shadow:none;padding:0;}}
        button#sticky-note-move-handle:hover, button#sticky-note-resize-grip:hover, button#sticky-secret-unlock-control:hover, button#sticky-secret-unlock-control:active {{background:transparent;background-image:none;border:0;box-shadow:none;}}
        button#sticky-note-move-handle:focus, button#sticky-note-resize-grip:focus, button#sticky-secret-unlock-control:focus {{background:transparent;background-image:none;border:2px solid #46545e;box-shadow:none;outline:none;border-radius:3px;}}
        label {{font:11px Sans;}}
        '''.encode())

    def update_rounded_shape(self,*_):
        """Keep the X11 window mask synchronized with every note resize."""
        if self.code_mode:return
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
        if self.code_mode:self.update_code_window_title()

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
        key_name=Gdk.keyval_name(event.keyval)
        if (event.state&Gdk.ModifierType.CONTROL_MASK and
                (key_name or '').lower()=='h'):
            self.hide_note()
            return True
        if getattr(self,'secret_locked',False):return False
        if key_name=='Escape' and self.note.get('secret'):
            geometry_mode=getattr(self,'keyboard_geometry_mode',None)
            if geometry_mode:
                return self.keyboard_geometry_key_press(_widget,event,geometry_mode)
            self.lock_secret();return True
        geometry_mode=getattr(self,'keyboard_geometry_mode',None)
        if geometry_mode:
            return self.keyboard_geometry_key_press(_widget,event,geometry_mode)
        if key_name in ('Control_L','Control_R'):self.refresh_link_hover()
        if event.state&Gdk.ModifierType.CONTROL_MASK:
            key=(Gdk.keyval_name(event.keyval) or '').lower()
            if key in ('z','y'):self.undo(key=='y' or bool(event.state&Gdk.ModifierType.SHIFT_MASK));return True
            if key=='s':self.flush();return True
            if key=='0':self.restore_size();return True
            if key=='n':self.app.new_card(self);return True
        return False

    def keyboard_geometry_key_press(self,_widget,event,mode):
        """Expose move and resize through focused keyboard-operable controls."""
        key=Gdk.keyval_name(event.keyval)
        if self.keyboard_geometry_mode is None:
            if key not in ('Return','KP_Enter','space'):return False
            if not self.authorize_secret_edit():return True
            self.keyboard_geometry_mode=mode
            self.keyboard_geometry_previous_status=(self.status.get_text(),self.status.get_visible())
            message='sticky.keyboard_move_mode' if mode=='move' else 'sticky.keyboard_resize_mode'
            ui.call(self.status,'set_text',ui.msg(message));self.status.show()
            return True
        if self.keyboard_geometry_mode!=mode:return False
        if key in ('Escape','Return','KP_Enter'):
            self.keyboard_geometry_mode=None
            self.save_geometry()
            previous=self.keyboard_geometry_previous_status or ('',False)
            self.keyboard_geometry_previous_status=None
            self.status.set_text(previous[0])
            if previous[1]:self.status.show()
            else:self.status.hide()
            if key=='Escape' and self.note.get('secret') and not self.secret_locked:self.lock_secret()
            return True
        delta=10 if event.state&Gdk.ModifierType.SHIFT_MASK else 1
        directions={'Left':(-1,0),'Right':(1,0),'Up':(0,-1),'Down':(0,1)}
        if key not in directions:return False
        dx,dy=directions[key]
        if mode=='move':
            x,y=self.get_position();self.move(x+dx*delta,y+dy*delta)
        else:
            width,height=self.get_size()
            minimum_width,minimum_height=(320,220) if self.code_mode else (180,120)
            width=max(minimum_width,min(10000,width+dx*delta))
            height=max(minimum_height,min(10000,height+dy*delta))
            self.resize(width,height)
        return True

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
        pointer_state=self.menu_pointer_state()
        self.menu_buttons_down=pointer_state[2]&self.menu_button_mask() if pointer_state else 0
        if not self.menu_pointer_timer:
            self.menu_pointer_timer=GLib.timeout_add(10,self.watch_menu_outside_click)

    @staticmethod
    def menu_button_mask():
        return int(Gdk.ModifierType.BUTTON1_MASK|Gdk.ModifierType.BUTTON2_MASK|
            Gdk.ModifierType.BUTTON3_MASK)

    def menu_pointer_state(self):
        try:
            pointer=self.get_display().get_default_seat().get_pointer()
            screen,_,_=pointer.get_position()
            _,x,y,state=screen.get_root_window().get_device_position(pointer)
            return int(x),int(y),int(state)
        except Exception:
            return None

    def menu_windows(self):
        pending=[self.options_menu];seen=set()
        while pending:
            menu=pending.pop()
            if id(menu) in seen:continue
            seen.add(id(menu))
            window=menu.get_window()
            if window:
                try:
                    _ok,x,y=window.get_origin()
                    geometry=window.get_geometry()
                    yield int(x),int(y),int(geometry[2]),int(geometry[3])
                except Exception:pass
            for item in menu.get_children():
                submenu=item.get_submenu()
                if submenu and submenu.get_visible():pending.append(submenu)

    def pointer_over_menu(self,x,y):
        windows=list(self.menu_windows())
        if not windows:return None
        return any(left<=x<left+width and top<=y<top+height
            for left,top,width,height in windows)

    def watch_menu_outside_click(self):
        if not self.options_menu.get_visible():
            self.menu_pointer_timer=0
            return False
        pointer_state=self.menu_pointer_state()
        if pointer_state:
            x,y,state=pointer_state
            buttons_down=state&self.menu_button_mask()
            newly_pressed=buttons_down&~self.menu_buttons_down
            self.menu_buttons_down=buttons_down
            inside_menu=self.pointer_over_menu(x,y) if newly_pressed else None
            if newly_pressed and inside_menu is False:
                self.menu_pointer_timer=0
                self.options_menu.popdown()
                return False
        return True

    def menu_closed(self,*_):
        if self.menu_pointer_timer:
            GLib.source_remove(self.menu_pointer_timer);self.menu_pointer_timer=0

    def menu_escape_press(self,_menu,event):
        if Gdk.keyval_name(event.keyval)=='Escape':
            self.options_menu.popdown()
            return True
        return False

    def draw_secret_badge(self,_widget,context):
        if cairo is None:return False
        context.set_source_rgb(0,0,0)
        context.set_line_width(1.8);context.set_line_cap(cairo.LINE_CAP_ROUND)
        context.arc(8,8,4.2,3.141592653589793,6.283185307179586);context.stroke()
        context.rectangle(3,7.5,10,9);context.fill()
        context.set_source_rgba(1,1,1,0.9)
        context.arc(8,11.3,1,0,6.283185307179586);context.fill()
        context.rectangle(7.5,11.3,1,2.6);context.fill()
        return False

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
                    details=note.note if hasattr(note,'note') else note
                    label=self.app.note_menu_title(details)
                    entry=ui.widget(Gtk.MenuItem,label=label)
                    entry.connect('activate',lambda _item,identity=details['id'],action=callback:action(identity))
                    menu.append(entry)
            menu.show_all()

    def sync_secret_menu_actions(self):
        enabled=not self.secret_locked
        for item in getattr(self,'secret_edit_menu_items',[]):item.set_sensitive(enabled)
        for name in ('attach_menu_item','email_menu_item'):
            item=getattr(self,name,None)
            if item:item.set_sensitive(enabled)

    def sync_secret_badge(self):
        badge=getattr(self,'secret_badge',None)
        if badge:badge.set_visible(bool(self.note.get('secret') and not self.secret_locked))

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

    def code_drag_region_press(self,region,event):
        """Move the code window from non-interactive header/toolbar space."""
        if not self.code_mode or event.button!=1:return False
        target=Gtk.get_event_widget(event)
        if target is None:return False
        interactive=(Gtk.Button,Gtk.Entry,Gtk.ComboBox,Gtk.TextView)
        current=target
        while current is not None and current is not region:
            if isinstance(current,interactive):return False
            current=current.get_parent()
        if current is not region:return False
        if not self.authorize_secret_edit():return True
        self.begin_move_drag(1,int(event.x_root),int(event.y_root),event.time)
        return True

    def wrap_code_drag_region(self,child):
        region=Gtk.EventBox();region.set_visible_window(False)
        region.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        region.add(child)
        region.connect('button-press-event',self.code_drag_region_press)
        return region

    def resize_press(self,_widget,event):
        if event.button==1:
            if not self.authorize_secret_edit():return True
            self.begin_resize_drag(Gdk.WindowEdge.SOUTH_EAST,1,int(event.x_root),int(event.y_root),event.time);return True
        return False

    def resize_edge_press(self,_widget,event,edge):
        if event.button!=1:return False
        if not self.authorize_secret_edit():return True
        self.begin_resize_drag(edge,1,int(event.x_root),int(event.y_root),event.time)
        return True

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
            source_path=attachment.get('source_path')
            candidate=source_path if source_path and os.path.exists(source_path) else attachment['path']
            parent=Gio.File.new_for_path(candidate).get_parent()
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
        recipient.set_activates_default(True)
        subject=Gtk.Entry();subject.set_max_length(200);subject.set_text(self.saved_title)
        subject.set_activates_default(True)
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
        item(ui.msg('sticky.shortcuts'),self.show_shortcuts)
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
        code_mode=ui.widget(Gtk.CheckMenuItem,label=ui.msg('sticky.sticky_code'))
        self.code_syncing=True;code_mode.set_active(self.code_mode);self.code_syncing=False
        code_mode.connect('toggled',self.toggle_code_mode);menu.append(code_mode)
        if menu is getattr(self,'options_menu',None):self.code_mode_item=code_mode
        if self.note.get('secret') and self.secret_locked:code_mode.set_sensitive(False)
        menu.append(Gtk.SeparatorMenuItem())
        item(ui.msg('sticky.new_note'),lambda:self.app.new_card(self))
        restore=item(ui.msg('sticky.restore_size'),self.restore_size)
        restore.set_sensitive(not self.secret_locked)
        colors=Gtk.Menu();colors.connect('key-press-event',self.menu_escape_press)
        parent=ui.widget(Gtk.MenuItem,label=ui.msg('sticky.color'));parent.set_submenu(colors);parent.set_sensitive(not self.secret_locked);menu.append(parent)
        for name,color in zip(NAMES,COLORS):
            entry=ui.widget(Gtk.MenuItem,label=name);entry.connect('activate',lambda _,c=color:self.set_property_value(color=c));colors.append(entry)
        above=ui.widget(Gtk.CheckMenuItem,label=ui.msg('sticky.above'));above.set_active(bool(self.note['above']))
        above.set_sensitive(not self.secret_locked)
        above.connect('toggled',lambda widget:self.set_property_value(above=int(widget.get_active())));menu.append(above)
        opacity=ui.widget(Gtk.CheckMenuItem,label=ui.msg('sticky.reduce_opacity'))
        opacity.set_active(bool(self.note.get('reduced_opacity',0)))
        opacity.set_sensitive(not self.secret_locked)
        opacity.connect('toggled',lambda widget:self.set_property_value(reduced_opacity=int(widget.get_active())))
        menu.append(opacity)
        item(ui.msg('sticky.hide'),self.hide_note)
        archive=item(ui.msg('sticky.archive'),self.archive_note)
        archive.set_sensitive(not self.secret_locked)
        hidden_menu=Gtk.Menu();hidden_menu.connect('key-press-event',self.menu_escape_press)
        hidden_item=ui.widget(Gtk.MenuItem,label=ui.msg('sticky.show_hidden_notes'))
        hidden_item.set_submenu(hidden_menu);menu.append(hidden_item)
        archived_menu=Gtk.Menu();archived_menu.connect('key-press-event',self.menu_escape_press)
        archived_item=ui.widget(Gtk.MenuItem,label=ui.msg('sticky.archived_notes'))
        archived_item.set_submenu(archived_menu);menu.append(archived_item)
        item(ui.msg('sticky.delete_note'),self.delete_note)
        if menu is getattr(self,'options_menu',None):
            self.archive_menu_item=archive
            self.hidden_notes_menu=hidden_menu;self.hidden_notes_item=hidden_item
            self.archived_notes_menu=archived_menu;self.archived_notes_item=archived_item
        item(ui.msg('sticky.quit'),self.app.safe_quit)
        if menu is getattr(self,'options_menu',None):
            self.secret_edit_menu_items=[attach_item,email_item,restore,parent,above,opacity,archive,code_mode]
            self.sync_secret_menu_actions()

    def show_shortcuts(self):
        dialog=ui.widget(Gtk.Dialog,transient_for=self,modal=True,title=ui.msg('sticky.shortcuts_title'))
        dialog.set_resizable(False)
        box=dialog.get_content_area();box.set_border_width(18)
        grid=Gtk.Grid(column_spacing=22,row_spacing=8)
        shortcuts=(
            ('Ctrl+N','sticky.shortcut_new_note'),
            ('Ctrl+H','sticky.shortcut_hide_note'),
            ('Ctrl+0','sticky.shortcut_restore_size'),
            ('Ctrl+S','sticky.shortcut_save'),
            ('Ctrl+Z','sticky.shortcut_undo'),
            ('Ctrl+Y / Ctrl+Shift+Z','sticky.shortcut_redo'),
            ('Ctrl+B','sticky.shortcut_bold'),
            ('Ctrl+I','sticky.shortcut_italic'),
            ('Ctrl+U','sticky.shortcut_underline'),
            ('Ctrl+E','sticky.shortcut_emoji'),
            ('Esc','sticky.shortcut_lock_secret'),
            ('Ctrl+clique','sticky.shortcut_open_link'),
        )
        for row,(shortcut,description) in enumerate(shortcuts):
            key=Gtk.Label(label=shortcut,xalign=1);key.set_selectable(True)
            key.get_style_context().add_class('dim-label')
            action=ui.widget(Gtk.Label,label=ui.msg(description),xalign=0)
            grid.attach(key,0,row,1,1);grid.attach(action,1,row,1,1)
        box.pack_start(grid,False,False,0)
        dialog.add_button(ui.tr('sticky.shortcuts_close'),Gtk.ResponseType.CLOSE)
        dialog.set_default_response(Gtk.ResponseType.CLOSE)
        dialog.show_all();dialog.run();dialog.destroy()
        return False

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
        # Remove private email drafts before committing deletion. If cleanup
        # fails, keep the note and its window so the user can resolve the
        # cleanup problem instead of leaving a sensitive draft behind.
        try:purge_note_email_drafts([self.note['id']])
        except Exception as error:
            self.error(error);self.text.grab_focus();return False
        try:self.app.store.delete(self.note['id'],self.revision)
        except Exception as error:
            # The draft may already be gone, but the note remains authoritative
            # and visible if SQLite rejects deletion or detects a revision race.
            self.error(error);self.text.grab_focus();return False
        if hasattr(self,'attachment_preview_cache'):self.attachment_preview_cache.clear()
        self.destroy();return True

    def insert_emoji(self,editor):
        editor.stop_emission_by_name('insert-emoji')
        if getattr(self,'secret_locked',False):return
        if self.emoji_dialog:
            self.emoji_dialog.present();return
        mark=self.buffer.create_mark(None,self.buffer.get_iter_at_mark(self.buffer.get_insert()),False)
        # Use its own undecorated toplevel instead of Gtk.Popover: native
        # popovers stay in the note's stacking/geometry context and can be cut
        # off by a small note or by an overlapping Sticky Code window.
        popup=Gtk.Window.new(Gtk.WindowType.TOPLEVEL)
        popup.set_title('');popup.set_decorated(False);popup.set_resizable(False)
        popup.set_skip_taskbar_hint(True);popup.set_keep_above(True);popup.set_accept_focus(True)
        popup.set_transient_for(self);popup.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        popup.set_opacity(1.0);popup.set_position(Gtk.WindowPosition.NONE)
        popup.set_border_width(6);popup.set_name('sticky-emoji-popup')
        popup.get_style_context().add_class('sticky-emoji-popup')
        self.emoji_dialog=popup
        provider=Gtk.CssProvider()
        provider.load_from_data(b'''
        window.sticky-emoji-popup {background-color:#292a2d;color:#f3f4f6;border:1px solid rgba(255,255,255,0.16);border-radius:8px;}
        button.sticky-emoji-choice {background:transparent;background-image:none;border:0;box-shadow:none;border-radius:5px;padding:0;min-width:34px;min-height:34px;font:20px Sans;}
        button.sticky-emoji-choice:hover {background-color:rgba(255,255,255,0.13);}
        ''' )
        popup.get_style_context().add_provider(provider,Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.emoji_css=provider
        grid=Gtk.Grid(column_spacing=2,row_spacing=2)
        grid.set_border_width(1)
        emojis=(
            '😀','😃','😄','😁','😆','😅','😂','🤣',
            '🙂','🙃','😉','😊','😇','😍','🥰','😘',
            '😗','😙','😚','😋','😛','😜','🤪','😝',
            '🤗','🤔','😴','😎','🥳','😭','😤','😡',
            '👍','👎','👏','🙏','🤝','💪','🙌','🤷',
            '❤️','💔','💖','🔥','🎉','✨','🌟','💯',
        )
        columns=8
        for index,value in enumerate(emojis):
            button=Gtk.Button();button.set_relief(Gtk.ReliefStyle.NONE)
            button.get_style_context().add_class('sticky-emoji-choice')
            button.add(Gtk.Label(label=value))
            button.connect('clicked',lambda _button,emoji=value:choose(emoji))
            grid.attach(button,index%columns,index//columns,1,1)
        popup.add(grid);grid.show_all()
        point=Gdk.Rectangle();cursor=self.buffer.get_iter_at_mark(self.buffer.get_insert())
        rect=self.text.get_iter_location(cursor)
        point.x,point.y=self.text.buffer_to_window_coords(Gtk.TextWindowType.WIDGET,rect.x,rect.y)
        point.width=max(1,rect.width);point.height=max(1,rect.height)
        text_window=self.text.get_window(Gtk.TextWindowType.WIDGET)
        origin=text_window.get_origin() if text_window else (False,0,0)
        anchor_x=origin[-2]+point.x;anchor_y=origin[-1]+point.y+max(point.height,18)
        min_width,natural_width=popup.get_preferred_width()
        min_height,natural_height=popup.get_preferred_height()
        # GTK 3 themes can allocate the last grid column a few pixels past the
        # popup's preferred outer width. Keep a small content safety margin so
        # the final emoji column stays inside the window on real displays.
        width=max(min_width,natural_width)+8;height=max(min_height,natural_height)+8
        display=Gdk.Display.get_default()
        monitor=display.get_monitor_at_point(anchor_x,anchor_y) if display else None
        if monitor is None and display:monitor=display.get_primary_monitor()
        workarea=monitor.get_workarea() if monitor else Gdk.Rectangle()
        if monitor is None:workarea.x=0;workarea.y=0;workarea.width=width;workarea.height=height
        left=workarea.x+8;top=workarea.y+8
        right=workarea.x+workarea.width-8;bottom=workarea.y+workarea.height-8
        x=min(max(anchor_x,left),max(left,right-width))
        y=anchor_y
        if y+height>bottom:y=point.y+origin[-1]-height-6
        y=min(max(y,top),max(top,bottom-height))
        popup.set_default_size(width,height);popup.move(x,y)
        def finish(*_):
            if self.emoji_dialog is not popup:return
            self.emoji_dialog=None
            if self.alive and not getattr(self,'secret_locked',False):
                self.buffer.place_cursor(self.buffer.get_iter_at_mark(mark))
                self.text.grab_focus()
            self.buffer.delete_mark(mark)
        def choose(value):
            if not self.alive or getattr(self,'secret_locked',False):return
            self.buffer.insert(self.buffer.get_iter_at_mark(mark),value)
            popup.destroy()
        def key_press(_widget,event):
            if Gdk.keyval_name(event.keyval)=='Escape':
                popup.destroy();return True
            return False
        def focus_out(*_):
            if self.emoji_dialog is popup:GLib.idle_add(lambda:popup.destroy() if self.emoji_dialog is popup else False)
            return False
        popup.connect('destroy',finish)
        popup.connect('key-press-event',key_press)
        popup.connect('focus-out-event',focus_out)
        popup.show_all();popup.present();popup.set_focus(grid.get_child_at(0,0))

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

    def unlock_pointer_click(self,_widget):
        # GtkButton's clicked signal is emitted for both pointer and keyboard
        # activation, so no pointer-event argument should be required here.
        self.unlock_secret()
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
        self.keyboard_geometry_mode=None;self.keyboard_geometry_previous_status=None
        self.update_code_window_title()
        self.sync_secret_badge()
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
        self.secret_locked=False;self.update_code_window_title();self.secret_activity()
        self.sync_secret_badge()
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
                self.secret_locked=False;self.update_code_window_title();self.secret_activity();self.secret_stack.set_visible_child_name('editor')
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
            self.sync_secret_badge()

    def close_requested(self,*_):
        self.hide_note()
        return True

    def hide_note(self):
        if not self.flush() and not self.resolve_close_conflict():return False
        if not self.alive:return True
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
            self.pending_restore=False;self.resize(*( (900,620) if self.code_mode else (310,300) ))

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
        emoji_dialog=getattr(self,'emoji_dialog',None)
        if emoji_dialog:emoji_dialog.destroy()
        for timer in [getattr(self,'history_timer',0),getattr(self,'geometry_timer',0),getattr(self,'menu_pointer_timer',0)]:
            if timer:GLib.source_remove(timer)
        self.history_timer=0;self.geometry_timer=0;self.menu_pointer_timer=0

