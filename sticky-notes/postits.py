#!/usr/bin/python3
"""Independent sticky notes with GNOME desktop launcher actions."""
import signal
import sys
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,Gio,GLib,Gdk
from storage import DATA,InstanceAlreadyRunningError,InstanceLock,Store

from card import Card
from ui_language import ui


class Postits(Gtk.Application):
    def __init__(self,store=None):
        super().__init__(application_id='io.orbitz.Postits',flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.store=store;self.instance_lock=None;self.monitor_timer=0
        self.connect('activate',self.activate_cards)
        self.connect('command-line',self.command_line)
        self.connect('startup',self.startup_cards)
        self.connect('shutdown',self.shutdown_cards)

    def command_line(self,application,command_line):
        """Route desktop-file actions to the already-running application."""
        args=command_line.get_arguments()
        if self.store is None:return 1
        if '--new-note' in args:
            self.new_card()
        elif '--open-hidden-notes' in args:
            identities=[window.note['id'] for window in self.hidden_notes()]
            if identities:
                for identity in identities:self.show_hidden_note(identity)
            else:
                # A desktop action can reach this process after a session or
                # application restart, when hidden Gtk windows are no longer
                # represented in get_windows(). Reuse normal activation as the
                # recovery path instead of silently doing nothing.
                self.activate_cards()
        elif '--close-notes' in args:
            for window in self.get_windows():
                if hasattr(window,'hide_note') and window.get_visible():window.hide_note()
        else:
            self.activate_cards()
        return 0

    def startup_cards(self,*_):
        self.hold()
        quit_action=Gio.SimpleAction.new('quit',None)
        quit_action.connect('activate',lambda *_:self.safe_quit())
        self.add_action(quit_action)
        try:
            data_directory=getattr(self.store,'directory',DATA)
            self.instance_lock=InstanceLock(data_directory)
            if self.store is None:self.store=Store(data_directory)
        except InstanceAlreadyRunningError:
            dialog=ui.widget(Gtk.MessageDialog,message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.CLOSE,text=ui.msg('sticky.already_running_title'))
            ui.call(dialog,'format_secondary_text',ui.msg('sticky.already_running_body'))
            dialog.run();dialog.destroy();self.quit();return
        except Exception as error:
            dialog=ui.widget(Gtk.MessageDialog,message_type=Gtk.MessageType.ERROR,buttons=Gtk.ButtonsType.CLOSE,text=ui.msg('sticky.start_failed'))
            ui.call(dialog,'format_secondary_text',ui.join('\n',[ui.error_message(error),ui.msg('sticky.files_preserved')]));dialog.run();dialog.destroy();self.quit();return
        self.screen=Gdk.Screen.get_default()
        self.monitor_signal=self.screen.connect('monitors-changed',self.monitors_changed)
        self.backup_timer=GLib.timeout_add_seconds(3600,self.backup_store)
        self.term_signal=GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,self.terminate_signal)

    def terminate_signal(self):
        # GLib removes a signal source when its callback returns False. Clear
        # the ID before safe_quit emits the application's shutdown signal so
        # shutdown_cards does not try to remove the same source a second time.
        self.term_signal=0
        self.safe_quit()
        return False

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
            notes=self.store.all(archived=False)
            if not notes:notes=[self.store.create()]
            for note in notes:
                card=Card(self,note);self.fit_monitor(card,saved=True)
        else:
            visible=[window for window in windows if window.get_visible()]
            # Keep intentionally hidden notes hidden while another note is
            # available for their dropdown; if every note is hidden, launcher
            # activation is the recovery path and restores the set.
            for window in visible or windows:
                if not window.get_visible():
                    if window.note.get('secret'):window.lock_secret()
                    self.fit_monitor(window,saved=True)
                window.show();window.present()

    def new_card(self,previous=None):
        x,y=previous.get_position() if previous else (100,100)
        card=Card(self,self.store.create(x+30,y+30));self.fit_monitor(card,saved=True);card.present()
        return card


    def hidden_notes(self):
        return [window for window in self.get_windows()
            if hasattr(window,'note') and getattr(window,'alive',False)
            and not window.get_visible() and not window.note.get('archived')]

    def note_menu_title(self,note):
        if note.get('secret'):return ui.msg('sticky.secret_note')
        title=(note.get('title') or '').strip()
        if title:return title
        return f"undefined-{self.store.note_number(note['id'])}"

    def show_hidden_note(self,identity):
        for window in self.hidden_notes():
            if window.note['id']!=identity:continue
            if window.note.get('secret'):window.lock_secret()
            self.fit_monitor(window,saved=True)
            window.show();window.present()
            return True
        return False

    def restore_archived_note(self,identity):
        try:
            note=self.store.get(identity)
            if not note.get('archived'):return False
            self.store.properties(identity,archived=0)
            card=Card(self,self.store.get(identity));self.fit_monitor(card,saved=True);card.present()
            return card
        except Exception as error:
            for window in self.get_windows():
                if hasattr(window,'status') and window.get_visible():
                    window.error(error);break
            return False

    def fit_monitor(self,card,saved=False):
        display=Gdk.Display.get_default();rectangles=[display.get_monitor(i).get_geometry() for i in range(display.get_n_monitors())]
        if not rectangles:return
        # Immediately after mapping, the window manager may not have delivered
        # its first ConfigureNotify yet. get_position() can then report a
        # transient (often primary-monitor) location. On restore, use the
        # persisted note coordinates to select and clamp against the right
        # monitor instead of treating that transient location as authoritative.
        if saved:
            x,y=card.note['x'],card.note['y']
            width,height=card.note['width'],card.note['height']
        else:
            x,y=card.get_position();width,height=card.get_size()
        def overlap(rect):return max(0,min(x+width,rect.x+rect.width)-max(x,rect.x))*max(0,min(y+height,rect.y+rect.height)-max(y,rect.y))
        rect=max(rectangles,key=overlap)
        width=min(width,rect.width);height=min(height,rect.height)
        nx=max(rect.x,min(x,rect.x+rect.width-width));ny=max(rect.y,min(y,rect.y+rect.height-height))
        current_width,current_height=card.get_size()
        if (nx,ny)!=(x,y) or (width,height)!=(current_width,current_height):
            card.resize(width,height)
        # A window manager may choose a fresh placement when a hidden window
        # is mapped again. Reapply saved coordinates on every restoration,
        # even when they are already within monitor bounds.
        if saved or (nx,ny)!=(x,y):card.move(nx,ny)
        if saved:card.note.update(x=nx,y=ny,width=width,height=height)

    def monitors_changed(self,*_):
        if self.monitor_timer:GLib.source_remove(self.monitor_timer)
        self.monitor_timer=GLib.timeout_add(500,self.fit_all)

    def fit_all(self):
        self.monitor_timer=0
        for card in self.get_windows():self.fit_monitor(card)
        return False

    def safe_quit(self):
        for card in self.get_windows():
            if not hasattr(card,'flush'):continue
            if not card.flush() and not card.resolve_close_conflict():return
            if not card.alive:continue
            card.save_geometry()
        self.quit()

    def shutdown_cards(self,*_):
        if hasattr(self,'screen'):self.screen.disconnect(self.monitor_signal)
        if self.monitor_timer:GLib.source_remove(self.monitor_timer)
        if getattr(self,'term_signal',0):GLib.source_remove(self.term_signal)
        self.term_signal=0
        if hasattr(self,'backup_timer'):GLib.source_remove(self.backup_timer)
        for card in list(self.get_windows()):
            if hasattr(card,'save_geometry'):card.save_geometry()
            card.destroy()
        if self.store:self.store.close()
        if self.instance_lock:self.instance_lock.close();self.instance_lock=None

if __name__=='__main__':
    # Gtk.Application owns single-instance routing and forwards desktop
    # activation to activate_cards(). A separate filesystem lock could make
    # a fresh launch exit silently instead of opening a note.
    sys.exit(Postits().run(sys.argv))
