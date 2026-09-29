# SPDX-License-Identifier: MIT
"""SIM transport for the shared Realtime call agent. Call IDs, never screen OCR,
confirm connection and hang-up. A failed session returns the call to the user;
no reconnect path places another call.
"""
import base64
import threading
import time
import uuid

from call_proxy import CallProxy
from cellular_audio import PCMPlayer, request


class CellularCall(CallProxy):
    def __init__(self, emit, tell_owner, *, number, account='', request_id=None, **kwargs):
        super().__init__(emit, tell_owner, app='cellular', **kwargs)
        self.number, self.account = number, account
        self.request_id = request_id or uuid.uuid4().hex
        self.call_id = None
        self.private_voice_instructions = False
        self.independent_monitor = False
        self.monitor_wanted = False
        self._audio_opened = False
        self._handover_lock = threading.Lock()

    def _start_media(self):
        status = request('status')
        if not status.get('audioCapable'):
            raise RuntimeError('本机尚不支持系统通话音频接口')
        if status.get('phoneState') or status.get('calls'):
            raise RuntimeError('手机已有通话，请先结束当前通话')
        self.player = PCMPlayer()

    def _capture_remote(self):
        pass                              # audio opens only for a confirmed active Call

    def dial(self):
        if not (self.active and self.ready.is_set()):
            raise RuntimeError('Realtime 尚未就绪，未拨号')
        self.emit({'type': 'call-state', 'state': 'dialing'}, keep=False)
        result = request('dial', number=self.number, account=self.account, requestId=self.request_id)
        if not result.get('accepted'):
            raise RuntimeError('重复的拨号请求已被阻止')
        threading.Thread(target=self._watch, daemon=True).start()
        return {'dialed': True, 'requestId': self.request_id, 'confirmed_by': 'Android Telecom accepted'}

    def _remote(self, data):
        if self.active and not self.ending:
            self._send({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(data).decode()})

    def _watch(self):
        deadline = time.monotonic() + 20
        misses = 0
        try:
            while self.phase == 'agent':
                status = request('status')
                calls = status.get('calls', [])
                if self.call_id is None:
                    candidates = [c for c in calls if c.get('number') == self.number and not c.get('emergency')]
                    if len(candidates) == 1:
                        self.call_id = candidates[0]['id']
                        self.emit({'type': 'call-state', 'state': 'ringing'}, keep=False)
                    elif time.monotonic() > deadline:
                        raise RuntimeError('未能识别已拨出的电话，请在系统电话中查看')
                call = next((c for c in calls if c['id'] == self.call_id), None)
                if self.call_id:
                    # A transient bridge failure is not proof that the phone hung up.
                    if status.get('available') is False:
                        raise RuntimeError('系统通话服务失去连接')
                    misses = misses + 1 if call is None else 0
                    if (call and call['state'] == 7) or misses >= 2:
                        super().stop('ended')
                        return
                    if call and call['state'] == 4 and self.phase == 'agent' and not self._audio_opened:
                        self.player.open(self.call_id, self._remote, self._audio_failed)
                        self._audio_opened = True
                        self.answered = self.connected = True
                        self.emit({'type': 'call-state', 'state': 'connected'}, keep=False)
                        # A single return from Android's outgoing call screen. Never a focus loop.
                        try:
                            request('show-linux', id=self.call_id)
                        except Exception:
                            self.emit({'type': 'call-note', 'text': '电话继续中，可手动返回 Rungic 查看通话条。'})
                        threading.Thread(target=self._answered, daemon=True).start()
                time.sleep(.5)
        except Exception as error:
            self.emit({'type': 'call-error', 'text': str(error)})
            if self.call_id:
                self.take_over()
            else:
                super().stop('dial failed; check system dialer')

    def _audio_failed(self):
        if self.active and not self.hanging:
            self.emit({'type': 'call-error', 'text': '通话音频已断开，已交回系统电话；不会自动重拨。'})
            self.take_over()

    def _closed(self):
        if self.active:
            # Do not wait for a summary on the websocket receiver itself.
            threading.Thread(target=self.take_over if self.call_id else super()._closed, daemon=True).start()

    def take_over(self):
        with self._handover_lock:
            if not self.active:
                return
            self.active = False
            self.player.close()            # root releases audio and restores the physical mic
            self.phase = 'user'
            self.emit({'type': 'call-phase', 'phase': 'user', 'summary': self.summary})
            if self.ws:
                self.ws.close()
            threading.Thread(target=self._watch_user_call, daemon=True).start()

    def _watch_user_call(self):
        while self.phase == 'user':
            try:
                status = request('status')
                if status.get('available') is not False and not any(
                        c['id'] == self.call_id and c['state'] != 7 for c in status.get('calls', [])):
                    self._end('ended')
                    return
            except (OSError, RuntimeError):
                pass  # Lost state is not a confirmed hang-up. Keep the call controls visible.
            time.sleep(1)

    def set_monitor(self, on):
        self.emit({'type': 'call-note', 'text': '本机通话使用系统听筒；尚未提供独立旁听开关。'})

    def hang_up(self):
        if self.hanging or self.phase == 'ended':
            return
        self.hanging = True
        self.ending = 'end'
        self.player.flush()
        self.emit({'type': 'call-state', 'state': 'hanging-up'}, keep=False)
        def finish():
            try:
                # A very early tap can precede InCallService.onCallAdded.
                until = time.monotonic() + 12
                while not self.call_id and self.phase != 'ended' and time.monotonic() < until:
                    time.sleep(.1)
                if self.phase == 'ended':
                    return
                if not self.call_id:
                    raise RuntimeError('电话状态尚不可用，请从系统电话挂断')
                request('hangup', id=self.call_id)
                while time.monotonic() < until:
                    status = request('status')
                    if status.get('available') is not False and not any(
                            c['id'] == self.call_id and c['state'] != 7 for c in status.get('calls', [])):
                        super(CellularCall, self).stop('hung up')
                        return
                    time.sleep(.25)
                raise RuntimeError('系统尚未确认挂断，请从系统电话检查')
            except Exception as error:
                self.emit({'type': 'call-error', 'text': str(error)})
                self.emit({'type': 'call-state', 'state': 'hangup-failed'}, keep=False)
                self.take_over()
            finally:
                self.hanging = False
        threading.Thread(target=finish, daemon=True).start()

    def dtmf(self, digit):
        if not self.call_id:
            raise RuntimeError('电话尚未接通')
        return request('dtmf', id=self.call_id, digit=digit)
