#!/usr/bin/python3
# SPDX-License-Identifier: MIT
import configparser
from pathlib import Path
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
from gi.repository import Adw, Gtk
PATH=Path.home()/'.config/moto-screen-recording.ini'
class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id='dev.moto.RecordingSettings')
        self.connect('activate',self.activate)
        self.window=None
    def activate(self,*_):
        if self.window:
            self.window.present(); return
        self.window=Adw.PreferencesWindow(application=self,title='录屏设置',default_width=360,default_height=650)
        self.window.connect('close-request',self.close)
        page=Adw.PreferencesPage(title='录屏')
        group=Adw.PreferencesGroup(title='画面',description='录制 Linux 桌面的原始分辨率，使用硬件 H.264 编码。更高质量会增大文件。帧率受设备负载影响。')
        page.add(group)
        c=configparser.ConfigParser();c.read(PATH)
        self.values=dict(c['Recording']) if c.has_section('Recording') else {}
        self.combo(group,'清晰度','quality',['standard','high','smooth'],['标准 · 4 Mbps / 30 帧','高清 · 8 Mbps / 30 帧','流畅 · 12 Mbps / 60 帧'],'high')
        group=Adw.PreferencesGroup(title='声音',description='系统声音指 Linux 应用的声音。混合模式为两路各留一半音量，建议佩戴耳机避免扬声器声音再次进入麦克风。')
        page.add(group)
        self.combo(group,'声音来源','audio',['system','microphone','both','none'],['系统声音','麦克风','系统声音与麦克风','无声'],'system')
        page.add(Adw.PreferencesGroup(description='自动保存；下次开始录屏时生效。视频保存在“视频”文件夹，可从 Android 的 Plasma/Videos 查看。'))
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
