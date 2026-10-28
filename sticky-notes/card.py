"""GTK sticky card editing, interaction and geometry."""
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib,Gdk,Gio,Pango
from storage import COLORS
from ui_language import ui
from link_targets import target_at,link_at

NAMES=[ui.msg('sticky.yellow'),ui.msg('sticky.pink'),ui.msg('sticky.green'),ui.msg('sticky.blue'),ui.msg('sticky.purple'),ui.msg('sticky.peach')]


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
    ui.call(grip,'set_tooltip_text',ui.msg('sticky.resize_tooltip'))
    ui.call(grip.get_accessible(),'set_name',ui.msg('sticky.resize'))
    grip.connect('button-press-event',callback)
    grip.connect('realize',lambda widget:widget.get_window().set_cursor(
        Gdk.Cursor.new_from_name(widget.get_display(),'se-resize')))
    return grip


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
        self.saved_title=note.get('title') or '';self.title_dirty=False
        self.secret_locked=bool(note.get('secret'));self.secret_timer=0;self.secret_deadline=0
        self.secret_counting=False;self.auth_dialog=None;self.settings_dialog=None;self.secret_items=[];self.secret_syncing=False
        self.dirty=False;self.loading=False;self.history=[self.saved];self.index=0
        self.history_timer=0;self.geometry_timer=0;self.alive=True;self.pending_restore=False
        self.set_decorated(False);self.set_skip_taskbar_hint(True)
        self.set_default_size(note['width'],note['height']);self.set_size_request(220,160)
        self.set_focus_on_map(False);self.set_keep_above(bool(note['above']));self.stick()
        visual=self.get_screen().get_rgba_visual()
        if visual:self.set_visual(visual)
        self.css=Gtk.CssProvider()
        self.get_style_context().add_class('postit')
        self.get_style_context().add_provider(self.css,Gtk.STYLE_PROVIDER_PRIORITY_USER)
        outer=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12,margin=18)
        outer.set_margin_bottom(30)  # Keep the corner hit target clear of editable text.
        overlay=Gtk.Overlay();overlay.add(outer);self.add(overlay)
        header=Gtk.EventBox();header.set_visible_window(False)
        self.menu_button=ui.widget(Gtk.MenuButton)
        self.menu_button.set_direction(Gtk.ArrowType.DOWN)
        self.menu_button.set_size_request(22,22)
        self.menu_button.get_style_context().add_class('sticky-menu-button')
        ui.call(self.menu_button.get_accessible(),'set_name',ui.msg('sticky.note_menu'))
        ui.call(self.menu_button.get_accessible(),'set_description',ui.msg('sticky.trash_drag_hint'))
        ui.call(self.menu_button,'set_tooltip_text',ui.msg('sticky.trash_drag_hint'))
        heading_row=Gtk.Box(spacing=8)
        heading_row.pack_start(header,False,False,0)
        self.title_entry=Gtk.Entry()
        self.title_entry.set_name('sticky-note-title')
        self.title_entry.set_text(self.saved_title)
        self.title_entry.set_max_length(200)
        self.title_entry.set_has_frame(False)
        self.title_entry.get_style_context().add_class('heading')
        ui.call(self.title_entry,'set_tooltip_text',ui.msg('sticky.edit_title'))
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
        ui.call(self.close_button,'set_tooltip_text',ui.msg('sticky.close_tooltip'))
        ui.call(self.close_button.get_accessible(),'set_name',ui.msg('sticky.close'))
        self.close_button.connect('clicked',lambda *_:self.close_requested())
        heading_row.pack_end(self.close_button,False,False,0)
        outer.pack_start(heading_row,False,False,0)
        header.add(self.menu_button)
        # Keep right-click access on the header, but the header no longer starts
        # a custom drag; GNOME's Super+drag remains available everywhere.
        header.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        header.connect('button-press-event',self.context_menu_press)
        self.text=Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.text.set_name('sticky-note-text')
        self.buffer=self.text.get_buffer();self.buffer.set_text(self.saved)
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
        locked.pack_start(Gtk.Image.new_from_icon_name('changes-prevent-symbolic',Gtk.IconSize.LARGE_TOOLBAR),False,False,0)
        locked.pack_start(ui.widget(Gtk.Label,label=ui.msg('sticky.secret_note')),False,False,0)
        self.unlock_button=ui.widget(Gtk.Button,label=ui.msg('sticky.unlock'))
        self.unlock_button.connect('clicked',lambda *_:self.unlock_secret())
        locked.pack_start(self.unlock_button,False,False,0)
        self.secret_stack.add_named(locked,'locked');outer.pack_start(self.secret_stack,True,True,0)
        if self.secret_locked:
            self.secret_stack.set_visible_child_name('locked');self.title_field.set_no_show_all(True);self.title_field.hide()
            self.text.set_sensitive(False);self.title_entry.set_sensitive(False)
        self.status=ui.widget(Gtk.Label,xalign=0,wrap=True);self.status.set_no_show_all(True)
        outer.pack_start(self.status,False,False,0)
        grip=resize_grip(self.resize_press)
        overlay.add_overlay(grip);overlay.set_overlay_pass_through(grip,False)
        self.apply_color()
        self.buffer.connect('changed',self.changed)
        self.emoji_dialog=None
        self.text.connect('insert-emoji',self.insert_emoji)
        self.text.connect('populate-popup',self.populate_popup)
        self.text.connect('button-press-event',self.text_press)
        self.text.add_events(Gdk.EventMask.POINTER_MOTION_MASK|Gdk.EventMask.ENTER_NOTIFY_MASK|Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.text.connect('motion-notify-event',self.link_motion)
        self.text.connect('enter-notify-event',self.link_motion)
        self.text.connect('leave-notify-event',lambda *_:self.clear_link_hover())
        self.connect('key-release-event',self.link_key_release)
        ui.call(self.text,'set_tooltip_text',ui.msg('sticky.link_hint'))
        self.menu_tooltips=[(self.menu_button,self.menu_button.get_tooltip_text()),
                            (self.title_entry,self.title_entry.get_tooltip_text()),
                            (self.close_button,self.close_button.get_tooltip_text()),
                            (self.text,self.text.get_tooltip_text())]
        self.options_menu=Gtk.Menu()
        self.add_options(self.options_menu)
        self.options_menu.show_all()
        self.options_menu.connect('show',lambda *_:self.menu_opened())
        self.options_menu.connect('hide',lambda *_:self.menu_closed())
        self.menu_button.set_popup(self.options_menu)
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK|Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect('enter-notify-event',self.secret_enter)
        self.connect('leave-notify-event',self.secret_leave)
        self.connect('focus-in-event',self.secret_activity)
        self.connect('button-press-event',self.secret_activity)
        self.connect('unmap',lambda *_:self.lock_secret())
        self.connect('key-press-event',self.key_press)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect('button-press-event',self.trash_drag_press)
        self.connect('focus-out-event',self.focus_out)
        self.connect('configure-event',self.configured)
        self.connect('window-state-event',self.state_changed)
        self.connect('delete-event',self.close_requested)
        self.connect('destroy',self.destroyed)
        self.move(note['x'],note['y']);self.show_all()
        # One normal GTK placement, outside the Shell process, after mapping.
        self.move(note['x'],note['y'])
        self.menu_tooltips.append((grip,grip.get_tooltip_text()))
        for widget in [outer,heading_row,header,self.menu_button,title_field,self.title_entry,self.title_placeholder,self.close_button,self.text,scroll,self.scrollbar,self.status,grip,*grip.get_children()]:
            widget.get_style_context().add_provider(self.css,Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def value(self):return self.buffer.get_text(self.buffer.get_start_iter(),self.buffer.get_end_iter(),True)

    def apply_color(self):
        color=self.note['color']
        self.css.load_from_data(f'''
        window.postit {{background-color:{color};border-radius:10px;}}
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
        button {{background:transparent;border:0;box-shadow:none;color:#161616;padding:0;min-width:18px;min-height:18px;}}
        button:hover {{background-color:rgba(0,0,0,0.08);border-radius:4px;}}
        label {{font:11px Sans;}}
        '''.encode())

    def error(self,error):ui.call(self.status,'set_text',ui.msg('sticky.save_error',error=ui.error_message(error)));self.status.show()

    def changed(self,*_):
        if self.loading:return
        self.clear_link_hover()
        self.dirty=self.value()!=self.saved
        # A committed transaction per text change survives an application crash.
        self.flush()
        if self.history_timer:GLib.source_remove(self.history_timer)
        self.history_timer=GLib.timeout_add(300,self.record)

    def flush(self):
        saved_any=False
        if self.dirty:
            try:
                value=self.value();self.revision=self.app.store.text(self.note['id'],value,self.revision)
            except Exception as error:
                self.error(error);return False
            self.saved=value;self.dirty=False;saved_any=True
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
        sync_title_placeholder(self.title_entry,self.title_placeholder)
        self.title_dirty=self.title_entry.get_text().strip()!=self.saved_title

    def record(self):
        if self.history_timer:GLib.source_remove(self.history_timer);self.history_timer=0
        value=self.value()
        if value!=self.history[self.index]:
            self.history=(self.history[:self.index+1]+[value])[-60:];self.index=len(self.history)-1
        return False

    def undo(self,redo=False):
        if getattr(self,'secret_locked',False):return
        self.record();index=self.index+(1 if redo else -1)
        if not 0<=index<len(self.history):return
        self.index=index;self.loading=True;self.buffer.set_text(self.history[index]);self.loading=False
        self.dirty=self.value()!=self.saved;self.flush()

    def key_press(self,_widget,event):
        if hasattr(self,'secret_activity'):self.secret_activity()
        if getattr(self,'secret_locked',False):return False
        if Gdk.keyval_name(event.keyval)=='Escape':
            if getattr(self.app,'drag_card',None) is self:
                origin=getattr(self.app,'drag_origin',None)
                self.app.end_note_drag(False,self)
                if origin:self.move(*origin)
            else:self.app.end_note_drag(False)
        if Gdk.keyval_name(event.keyval) in ('Control_L','Control_R'):self.refresh_link_hover()
        if event.state&Gdk.ModifierType.CONTROL_MASK:
            key=(Gdk.keyval_name(event.keyval) or '').lower()
            if key in ('z','y'):self.undo(key=='y' or bool(event.state&Gdk.ModifierType.SHIFT_MASK));return True
            if key=='s':self.flush();return True
            if key=='0':self.restore_size();return True
            if key=='n':self.app.new_card(self);return True
            if key=='h':
                if self.flush():self.hide()
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
        # Hide this note's hover/focus tooltips before mapping the popup, so a
        # tooltip cannot cover menu entries. Restore them once the menu closes.
        for widget,_tooltip in self.menu_tooltips:widget.set_tooltip_text(None)

    def menu_closed(self):
        for widget,tooltip in self.menu_tooltips:
            if tooltip:widget.set_tooltip_text(tooltip)

    def context_menu_press(self,_widget,event):
        if event.button==3:
            self.options_menu.popup_at_pointer(event);return True
        return False

    def trash_drag_press(self,_widget,event):
        # Shift+drag from the empty bottom margin preserves trash deletion
        # without stealing text selection, links, buttons or the resize grip.
        if event.button!=1 or not event.state&Gdk.ModifierType.SHIFT_MASK:return False
        if not self.trash_drag_region(event):return False
        if not self.app.begin_note_drag(self):return True
        self.begin_move_drag(1,int(event.x_root),int(event.y_root),event.time)
        return True

    def trash_drag_region(self,event):
        x,y=self.get_position();width,height=self.get_size()
        local_x=int(event.x_root)-x;local_y=int(event.y_root)-y
        # outer's 30px bottom margin remains empty; leave the resize grip alone.
        return height-42<=local_y<height and 0<=local_x<width-34

    def resize_press(self,_widget,event):
        if event.button==1:
            self.begin_resize_drag(Gdk.WindowEdge.SOUTH_EAST,1,int(event.x_root),int(event.y_root),event.time);return True
        return False

    def set_property_value(self,**values):
        try:self.app.store.properties(self.note['id'],**values)
        except Exception as error:self.error(error);return
        self.note.update(values);self.apply_color();self.set_keep_above(bool(self.note['above']))

    def populate_popup(self,_text,menu):
        menu.append(Gtk.SeparatorMenuItem());self.add_options(menu);menu.show_all()

    def add_options(self,menu):
        def item(title,callback):
            widget=ui.widget(Gtk.MenuItem,label=title);widget.connect('activate',lambda *_:callback());menu.append(widget)
        item(ui.msg('sticky.settings'),self.show_secret_settings)
        secret=ui.widget(Gtk.CheckMenuItem,label=ui.msg('sticky.secret_note'))
        secret.set_active(bool(self.note.get('secret')))
        secret.connect('toggled',self.toggle_secret)
        self.secret_items.append(secret);menu.append(secret)
        menu.append(Gtk.SeparatorMenuItem())
        item(ui.msg('sticky.new_note'),lambda:self.app.new_card(self))
        item(ui.msg('sticky.restore_size'),self.restore_size)
        colors=Gtk.Menu();parent=ui.widget(Gtk.MenuItem,label=ui.msg('sticky.color'));parent.set_submenu(colors);menu.append(parent)
        for name,color in zip(NAMES,COLORS):
            entry=ui.widget(Gtk.MenuItem,label=name);entry.connect('activate',lambda _,c=color:self.set_property_value(color=c));colors.append(entry)
        above=ui.widget(Gtk.CheckMenuItem,label=ui.msg('sticky.above'));above.set_active(bool(self.note['above']))
        above.connect('toggled',lambda widget:self.set_property_value(above=int(widget.get_active())));menu.append(above)
        item(ui.msg('sticky.hide'),lambda:self.hide() if self.flush() else None)
        item(ui.msg('sticky.delete_note'),self.delete_note)
        menu.append(Gtk.SeparatorMenuItem())
        hint=ui.widget(Gtk.MenuItem,label=ui.msg('sticky.trash_drag_hint'));hint.set_sensitive(False);menu.append(hint)
        item(ui.msg('sticky.quit'),self.app.safe_quit)

    def delete_note(self):
        if not self.alive:return False
        if self.note.get('secret') and not self.authenticate_secret():return False
        if not self.alive or not self.flush():return False
        try:self.app.store.delete(self.note['id'],self.revision)
        except Exception as error:
            self.error(error);self.text.grab_focus();return False
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
        if self.emoji_dialog:self.emoji_dialog.destroy()
        self.clear_link_hover()
        self.secret_stack.set_visible_child_name('locked')
        self.title_field.set_no_show_all(True);self.title_field.hide()
        self.text.set_sensitive(False);self.title_entry.set_sensitive(False)
        if self.get_visible():self.unlock_button.grab_focus()
        if not saved:
            ui.call(self.status,'set_text',ui.msg('sticky.secret_save_failed'));self.status.show()

    def unlock_secret(self):
        if not self.note.get('secret') or not self.secret_locked:return
        if not self.authenticate_secret() or not self.alive:return
        self.secret_locked=False;self.secret_activity()
        self.secret_stack.set_visible_child_name('editor')
        self.title_field.set_no_show_all(False);self.title_field.show_all();sync_title_placeholder(self.title_entry,self.title_placeholder)
        self.text.set_sensitive(True);self.title_entry.set_sensitive(True);self.text.grab_focus()

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
                if self.secret_locked:self.unlock_button.grab_focus()
                else:self.text.grab_focus()
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
        old=self.pin_entry(box,ui.msg('sticky.pin_current')) if configured else None
        new=self.pin_entry(box,ui.msg('sticky.pin_new'));confirm=self.pin_entry(box,ui.msg('sticky.pin_confirm'))
        feedback=ui.widget(Gtk.Label,wrap=True,xalign=0);box.pack_start(feedback,False,False,0)
        ui.button(dialog,ui.msg('sticky.cancel'),Gtk.ResponseType.CANCEL)
        ui.button(dialog,ui.msg('sticky.pin_save'),Gtk.ResponseType.ACCEPT);dialog.set_default_response(Gtk.ResponseType.ACCEPT)
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
        if saved:
            for card in self.app.get_windows():
                if hasattr(card,'lock_secret'):card.lock_secret()
        return saved

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
                self.title_field.set_no_show_all(False);self.title_field.show_all();sync_title_placeholder(self.title_entry,self.title_placeholder)
                self.text.set_sensitive(True);self.title_entry.set_sensitive(True);self.text.grab_focus()
        except Exception as error:self.error(error)
        finally:
            self.secret_syncing=True
            for item in self.secret_items:item.set_active(bool(self.note.get('secret')))
            self.secret_syncing=False

    def close_requested(self,*_):
        if self.flush():self.hide()
        return True

    def expanded(self):
        window=self.get_window()
        return bool(window and window.get_state()&(Gdk.WindowState.MAXIMIZED|Gdk.WindowState.FULLSCREEN))

    def restore_size(self):
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
        if self.geometry_timer:GLib.source_remove(self.geometry_timer)
        self.geometry_timer=GLib.timeout_add(400,self.save_geometry)
        return False

    def save_geometry(self):
        if self.geometry_timer:GLib.source_remove(self.geometry_timer);self.geometry_timer=0
        if self.expanded():return False
        x,y=self.get_position();width,height=self.get_size()
        try:self.app.store.properties(self.note['id'],x=x,y=y,width=width,height=height)
        except Exception as error:self.error(error)
        return False

    def destroyed(self,*_):
        self.alive=False
        if hasattr(self,'cancel_secret_timer'):self.cancel_secret_timer()
        for dialog in [getattr(self,'auth_dialog',None),getattr(self,'settings_dialog',None)]:
            if dialog:dialog.destroy()
        self.app.end_note_drag(False,self)
        if self.emoji_dialog:self.emoji_dialog.destroy()
        for timer in [self.history_timer,self.geometry_timer]:
            if timer:GLib.source_remove(timer)
        self.history_timer=0;self.geometry_timer=0

