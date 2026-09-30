#!/usr/bin/python3
# SPDX-License-Identifier: MIT
import configparser
import gettext
from pathlib import Path
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
from gi.repository import Adw, Gtk
PATH=Path.home()/'.config/rungic-screen-recording.ini'
# Follows the desktop language (LANGUAGE/LANG of the Plasma session).
_=gettext.translation('rungic-recording-settings',localedir='/usr/share/locale',fallback=True).gettext
class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.rungic.RecordingSettings')
        self.connect('activate',self.activate)
        self.window=None
    def activate(self,*_):
        if self.window:
            self.window.present(); return
        self.window=Adw.PreferencesWindow(application=self,title=_('Screen Recording Settings'),default_width=360,default_height=650)
        self.window.connect('close-request',self.close)
        page=Adw.PreferencesPage(title=_('Screen Recording'))
        group=Adw.PreferencesGroup(title=_('Video'),description=_('Records the Linux desktop at its native resolution with hardware H.264 encoding. Higher quality makes larger files. The frame rate depends on the device load.'))
        page.add(group)
        c=configparser.ConfigParser();c.read(PATH)
        self.values=dict(c['Recording']) if c.has_section('Recording') else {}
        self.combo(group,_('Quality'),'quality',['standard','high','smooth'],[_('Standard · 4 Mbps / 30 fps'),_('High · 8 Mbps / 30 fps'),_('Smooth · 12 Mbps / 60 fps')],'high')
        group=Adw.PreferencesGroup(title=_('Sound'),description=_('System sound is the sound of Linux apps. Mixing keeps each source at half volume; use headphones so the speaker doesn\'t feed back into the microphone.'))
        page.add(group)
        self.combo(group,_('Sound source'),'audio',['system','microphone','both','none'],[_('System sound'),_('Microphone'),_('System sound and microphone'),_('No sound')],'system')
        page.add(Adw.PreferencesGroup(description=_('Saved automatically; takes effect the next time you start recording. Videos go to the Videos folder, which you can open on Android under Plasma/Videos.')))
        self.window.add(page);self.window.present()
    def combo(self,group,title,key,keys,labels,default):
        value=self.values.get(key,default)
        row=Adw.ComboRow(title=title,model=Gtk.StringList.new(labels),selected=keys.index(value) if value in keys else keys.index(default))
        row.connect('notify::selected',lambda r,_:self.save(key,keys[r.get_selected()]))
        group.add(row)
    def save(self,key,value):
        self.values[key]=value
        c=configparser.ConfigParser();c['Recording']=self.values
        PATH.parent.mkdir(parents=True,exist_ok=True)
        temp=PATH.with_suffix('.tmp')
        with temp.open('w') as f:c.write(f)
        temp.replace(PATH)
    def close(self,*_):
        self.window=None
        return False
App().run()
