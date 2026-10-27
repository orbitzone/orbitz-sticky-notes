#!/usr/bin/python3
"""Independent sticky cards: no GNOME Shell imports, grabs or window manipulation."""
import signal
import sys
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,Gio,GLib,Gdk
from storage import Store,DATA

from card import Card
from ui_language import ui

class Postits(Gtk.Application):
    def __init__(self,store=None):
        super().__init__(application_id='io.orbitz.Postits',flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.store=store;self.monitor_timer=0;self.drag_timer=0;self.drag_card=None;self.trash_window=None
        self.connect('activate',self.activate_cards)
        self.connect('startup',self.startup_cards)
        self.connect('shutdown',self.shutdown_cards)

    def startup_cards(self,*_):
        self.hold()
        quit_action=Gio.SimpleAction.new('quit',None)
        quit_action.connect('activate',lambda *_:self.safe_quit())
        self.add_action(quit_action)
        if self.store is None:
            try:self.store=Store()
            except Exception as error:
                dialog=ui.widget(Gtk.MessageDialog,message_type=Gtk.MessageType.ERROR,buttons=Gtk.ButtonsType.CLOSE,text=ui.msg('sticky.start_failed'))
                ui.call(dialog,'format_secondary_text',ui.join('\n',[ui.error_message(error),ui.msg('sticky.files_preserved')]));dialog.run();dialog.destroy();self.quit();return
        self.screen=Gdk.Screen.get_default()
        self.monitor_signal=self.screen.connect('monitors-changed',self.monitors_changed)
        self.backup_timer=GLib.timeout_add_seconds(3600,self.backup_store)
        self.term_signal=GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,lambda:self.safe_quit() or False)

    def backup_store(self):
        try:self.store.backup()
        except Exception as error:
            for card in self.get_windows():
                if not hasattr(card,'status'):continue
                ui.call(card.status,'set_text',ui.msg('sticky.backup_error',error=ui.error_message(error)));card.status.show()
        return True

    def activate_cards(self,*_):
        if not self.store:return
        windows=self.get_windows()
        if not windows:
            notes=self.store.all()
            if not notes:notes=[self.store.create()]
            for note in notes:
                card=Card(self,note);self.fit_monitor(card)
        else:
            for window in windows:window.show();window.present()

    def new_card(self,previous=None):
        x,y=previous.get_position() if previous else (100,100)
        card=Card(self,self.store.create(x+30,y+30));self.fit_monitor(card);card.present()
        return card

    def begin_note_drag(self,card):
        self.end_note_drag(False)
        # Product launchers explicitly use X11/XWayland: native Wayland has no
        # global pointer/root coordinates. Keep menu deletion usable there.
        if Gdk.Display.get_default().__gtype__.name=='GdkWaylandDisplay':
            ui.call(card.status,'set_text',ui.msg('sticky.drag_unavailable'));card.status.show();return False
        self.drag_card=card;self.drag_origin=card.get_position()
        popup=Gtk.Window(type=Gtk.WindowType.POPUP)
        popup.set_type_hint(Gdk.WindowTypeHint.DND);popup.set_accept_focus(False)
        popup.set_focus_on_map(False);popup.set_keep_above(True)
        popup.set_default_size(200,90)
        box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6,margin=12)
        box.pack_start(Gtk.Image.new_from_icon_name('user-trash-symbolic',Gtk.IconSize.DIALOG),False,False,0)
        box.pack_start(ui.widget(Gtk.Label,label=ui.msg('sticky.drop_delete')),False,False,0)
        popup.add(box);self.trash_window=popup
        popup.show_all();self.drag_bounds=None;self.drag_hover=False
        self.trash_cursor=Gdk.Cursor.new_from_name(popup.get_display(),'pointer')
        self.drag_timer=GLib.timeout_add(30,self.track_note_drag)
        self.track_note_drag()
        return True

    def track_note_drag(self):
        card=self.drag_card
        if not card or not card.alive:
            self.end_note_drag(False);return False
        pointer=Gdk.Display.get_default().get_default_seat().get_pointer()
        screen,x,y=pointer.get_position()
        _,_,_,state=screen.get_root_window().get_device_position(pointer)
        monitor=Gdk.Display.get_default().get_monitor_at_point(x,y)
        rect=monitor.get_workarea()
        width,height=self.trash_window.get_size()
        left=rect.x+(rect.width-width)//2;top=rect.y+rect.height-height-24
        self.trash_window.move(left,top)
        # Hit-test the actual popup position, even if the WM adjusts the request.
        left,top=self.trash_window.get_position()
        self.drag_bounds=(left,top,width,height)
        self.drag_hover=left<=x<left+width and top<=y<top+height
        context=self.trash_window.get_style_context()
        if self.drag_hover:context.add_class('destructive-action')
        else:context.remove_class('destructive-action')
        popup_window=self.trash_window.get_window()
        if popup_window:popup_window.set_cursor(self.trash_cursor if self.drag_hover else None)
        self.trash_window.set_opacity(1.0 if self.drag_hover else 0.8)
        if not state&Gdk.ModifierType.BUTTON1_MASK:
            self.end_note_drag(self.drag_hover);return False
        return True

    def end_note_drag(self,drop=False,card=None):
        if card is not None and self.drag_card is not card:return
        dragged=self.drag_card;origin=getattr(self,'drag_origin',None);self.drag_card=None
        if self.drag_timer:GLib.source_remove(self.drag_timer);self.drag_timer=0
        if self.trash_window:
            popup_window=self.trash_window.get_window()
            if popup_window:popup_window.set_cursor(None)
            self.trash_window.destroy();self.trash_window=None
        if drop and dragged and dragged.alive:
            # Leave the WM move loop before deleting the window.
            def delete_drop():
                if dragged.alive and not dragged.delete_note() and origin:
                    dragged.move(*origin)
                return False
            GLib.idle_add(delete_drop)

    def fit_monitor(self,card):
        display=Gdk.Display.get_default();rectangles=[display.get_monitor(i).get_geometry() for i in range(display.get_n_monitors())]
        if not rectangles:return
        x,y=card.get_position();width,height=card.get_size()
        def overlap(rect):return max(0,min(x+width,rect.x+rect.width)-max(x,rect.x))*max(0,min(y+height,rect.y+rect.height)-max(y,rect.y))
        rect=max(rectangles,key=overlap)
        width=min(width,rect.width);height=min(height,rect.height)
        nx=max(rect.x,min(x,rect.x+rect.width-width));ny=max(rect.y,min(y,rect.y+rect.height-height))
        if (nx,ny,width,height)!=(x,y,*card.get_size()):card.resize(width,height);card.move(nx,ny)

    def monitors_changed(self,*_):
        if self.monitor_timer:GLib.source_remove(self.monitor_timer)
        self.monitor_timer=GLib.timeout_add(500,self.fit_all)

    def fit_all(self):
        self.monitor_timer=0
        for card in self.get_windows():self.fit_monitor(card)
        return False

    def safe_quit(self):
        self.end_note_drag(False)
        for card in self.get_windows():
            if not hasattr(card,'flush'):continue
            if not card.flush():return
            card.save_geometry()
        self.quit()

    def shutdown_cards(self,*_):
        self.end_note_drag(False)
        if hasattr(self,'screen'):self.screen.disconnect(self.monitor_signal)
        if self.monitor_timer:GLib.source_remove(self.monitor_timer)
        if hasattr(self,'term_signal'):GLib.source_remove(self.term_signal)
        if hasattr(self,'backup_timer'):GLib.source_remove(self.backup_timer)
        for card in list(self.get_windows()):card.destroy()
        if self.store:self.store.close()

if __name__=='__main__':sys.exit(Postits().run(sys.argv))
