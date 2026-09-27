#!/usr/bin/python3
"""Android-owned device capabilities for the Plasma session (private Unix IPC)."""
import configparser
import json
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SOCKET = '/mnt/android-wayland/platform.sock'

def request(data):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(4)
        conn.connect(SOCKET)
        conn.sendall(json.dumps(data, ensure_ascii=False).encode() + b'\n')
        with conn.makefile('rb') as stream:
            raw = stream.readline(65537)
        if len(raw) > 65536:
            raise ValueError('宿主响应过大')
        result = json.loads(raw)
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result

if len(sys.argv) > 1 and sys.argv[1] == '--request':
    print(json.dumps(request(json.loads(sys.argv[2])), ensure_ascii=False, indent=2))
    raise SystemExit()

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk, GLib

class DeviceApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.rungic.Platform')
        self.connect('activate', self.activate)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.rows = {}
        self.window = None
        self.busy = False
        self.changing = False
        self.brightness_pending = 0

    def activate(self, app):
        if self.window:
            self.window.present()
            return
        self.window = Adw.PreferencesWindow(application=self, title='Android 设备', default_width=360, default_height=700)
        self.window.connect('close-request', self.closed)
        self.window.set_search_enabled(False)
        self.page = Adw.PreferencesPage(title='设备', icon_name='phone-symbolic')
        self.window.add(self.page)
        g = self.group('手机与 Linux')
        self.row(g, 'model', '手机型号')
        self.row(g, 'system', 'Android / Linux')
        self.row(g, 'timezone', '时区')
        g = self.group('网络', '网络连接由 Android 管理')
        for key, title in [('network','连接状态'),('address','IP 地址'),('dns','DNS'),('wifi','Wi-Fi 链路')]:
            self.row(g, key, title)
        self.button(g, '管理网络', 'network')
        g = self.group('显示', 'Android 的刷新率请求受系统省电与温控策略约束')
        self.row(g, 'refresh', '支持的刷新率')
        self.row(g, 'frames', '当前显示与画面提交')
        self.orientation = Adw.ComboRow(title='屏幕方向', model=Gtk.StringList.new(['跟随 Android','竖屏','横屏']))
        self.orientation.connect('notify::selected', self.orientation_changed)
        g.add(self.orientation)
        self.follow = Adw.SwitchRow(title='亮度跟随 Android', active=True)
        g.add(self.follow)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.02, 1.0, 0.01)
        self.scale.set_value(0.5)
        self.scale.set_hexpand(True)
        self.scale.set_draw_value(False)
        row = Adw.ActionRow(title='桌面窗口亮度')
        row.add_suffix(self.scale); g.add(row)
        self.follow.connect('notify::active', self.follow_changed)
        self.scale.connect('value-changed', self.brightness_changed)
        self.button(g, 'Android 显示设置', 'display')
        g = self.group('电池')
        self.row(g, 'battery', '电量与温度')
        self.row(g, 'charging', '充电状态')
        g = self.group('内存', '限制 Linux 桌面可用的内存。超出时由 Linux 自己回收或关闭程序，不会挤掉 Android 的 VPN 和其他应用；上限太低时大型程序可能被关闭。')
        self.row(g, 'memory', 'Linux 已用内存')
        self.memory_presets = ['2048', '3072', '4096', '5120', '6144', 'unlimited']
        self.memory = Adw.ComboRow(title='内存上限', model=Gtk.StringList.new(
            ['最低 · 2 GB', '3 GB', '4 GB（默认）', '5 GB', '6 GB', '无上限']))
        self.memory.connect('notify::selected', self.memory_changed)
        g.add(self.memory)
        g = self.group('系统设置')
        for title, target in [('声音与输出设备','sound'),('蓝牙设备','bluetooth'),('日期与时区','datetime'),('定位设置','location')]:
            self.button(g, title, target)
        self.button(g, '测试震动', None, {'op':'vibrate'})
        self.message = Adw.PreferencesGroup(description='正在连接 Android…')
        self.page.add(self.message)
        self.window.present()
        self.timer = GLib.timeout_add_seconds(2, self.refresh)
        self.refresh()

    def closed(self, *_):
        GLib.source_remove(self.timer)
        if self.brightness_pending: GLib.source_remove(self.brightness_pending); self.brightness_pending=0
        self.window = None
        return False

    def group(self, title, description=None):
        g = Adw.PreferencesGroup(title=title)
        if description: g.set_description(description)
        self.page.add(g)
        return g

    def row(self, group, key, title):
        row = Adw.ActionRow(title=title, subtitle='读取中…')
        row.set_subtitle_selectable(True)
        group.add(row); self.rows[key]=row

    def button(self, group, title, target, data=None):
        row = Adw.ActionRow(title=title, activatable=True)
        row.add_suffix(Gtk.Image.new_from_icon_name('go-next-symbolic'))
        row.connect('activated', lambda *_: self.send(data or {'op':'settings','target':target}))
        group.add(row)

    def send(self, data):
        future=self.pool.submit(request, data)
        def done(f):
            try: f.result(); message=''
            except Exception as e: message=str(e)
            GLib.idle_add(self.show_message, message)
        future.add_done_callback(done)

    def show_message(self, message):
        if self.window: self.message.set_description(message)
        return False

    def orientation_changed(self, *_):
        if not self.changing:
            self.send({'op':'orientation','mode':['system','portrait','landscape'][self.orientation.get_selected()]})

    def memory_changed(self, *_):
        if not self.changing:
            self.send({'op':'container-memory','limit':self.memory_presets[self.memory.get_selected()]})

    def follow_changed(self, *_):
        if self.changing:return
        follow=self.follow.get_active()
        self.scale.set_sensitive(not follow)
        self.send({'op':'brightness','value':-1 if follow else self.scale.get_value()})

    def brightness_changed(self, *_):
        if self.changing or self.follow.get_active():return
        if self.brightness_pending:GLib.source_remove(self.brightness_pending)
        def update():
            self.brightness_pending=0
            self.send({'op':'brightness','value':self.scale.get_value()})
            return False
        self.brightness_pending=GLib.timeout_add(120,update)

    def refresh(self):
        if not self.window:return False
        if self.busy:return True
        self.busy=True
        def read():
            data=request({'op':'status'})
            # Same cached Android identity as the NetworkManager bridge.
            detail=request({'op':'network-get'})
            current=data.get('network',{})
            for net in detail.get('networks',[]):
                if net.get('interface') == current.get('interface'):
                    current.update({k:net[k] for k in ('ssid','rssi','frequency','linkMbps') if k in net})
            try: data['memory']=request({'op':'container-memory'})
            except Exception: data['memory']=None
            return data
        future=self.pool.submit(read)
        def done(f):
            try:data,error=f.result(),None
            except Exception as e:data,error=None,str(e)
            GLib.idle_add(self.update, data, error)
        future.add_done_callback(done)
        return True

    def update(self, data, error):
        self.busy=False
        if not self.window:return False
        if error:self.message.set_description(error);return False
        self.message.set_description('')
        self.changing=True
        self.orientation.set_selected(['system','portrait','landscape'].index(data.get('orientation','portrait')))
        self.changing=False
        r=self.rows
        r['model'].set_subtitle(f"{data['manufacturer']} {data['model']}")
        import platform
        version=platform.freedesktop_os_release().get('PRETTY_NAME', 'Linux')
        r['system'].set_subtitle(f"Android {data['android']} / {version}")
        r['timezone'].set_subtitle(data['timezone'])
        net=data.get('network',{})
        r['network'].set_subtitle((net.get('transport','未连接') + (' · 已联网' if net.get('validated') else ' · 未验证互联网')) if net.get('connected') else '未连接')
        r['address'].set_subtitle('\n'.join(net.get('addresses',[])) or '无')
        r['dns'].set_subtitle('\n'.join(net.get('dns',[])) or '无')
        if net.get('transport')=='Wi-Fi':
            ssid=net.get('ssid','')
            if ssid in ('<unknown ssid>','"<unknown ssid>"',''):ssid='网络名称请在 Android 中查看'
            r['wifi'].set_subtitle(f"{ssid}\n{net.get('rssi','?')} dBm · {net.get('frequency','?')} MHz\n协商速率 {net.get('linkMbps','?')} Mbps")
        else:r['wifi'].set_subtitle('未连接 Wi-Fi')
        battery=data.get('battery',{})
        r['battery'].set_subtitle(f"{battery.get('percent','?')}% · {battery.get('temperature','?')}°C")
        states={1:'状态未知',2:'充电中',3:'正在放电',4:'暂停充电',5:'电量已满'}
        r['charging'].set_subtitle(states.get(battery.get('status'),'未知')+(' · 已连接电源' if battery.get('plugged') else ' · 未连接电源'))
        c=configparser.ConfigParser()
        c.read('/mnt/android-wayland/android-refresh.ini')
        if c.has_section('refresh'):
            v=c['refresh'];r['refresh'].set_subtitle(f"{float(v.get('minimum-hz',0)):.0f}–{float(v.get('maximum-hz',0)):.0f} Hz")
            r['frames'].set_subtitle(f"Android 报告 {float(v.get('android-reported-hz',0)):.0f} Hz\n桌面提交 {float(v.get('submitted-fps',0)):.1f} 帧/秒")
        memory=data.get('memory')
        if memory:
            limit=f"{memory['limit_mib']} MB" if memory.get('limit_mib') else '无上限'
            r['memory'].set_subtitle(f"{memory['usage_mib']} MB · 上限 {limit} · 峰值 {memory['peak_mib']} MB（共 {memory['total_mib']} MB）")
            if memory.get('choice') in self.memory_presets:
                self.changing=True
                self.memory.set_selected(self.memory_presets.index(memory['choice']))
                self.changing=False
        else:r['memory'].set_subtitle('需要更新 Android 端（Rungic APK 2.5）')
        self.changing=True
        value=data.get('windowBrightness',-1)
        self.follow.set_active(value<0);self.scale.set_sensitive(value>=0)
        if value>=0 and not self.brightness_pending:self.scale.set_value(value)
        self.changing=False
        return False

DeviceApp().run(sys.argv)
