# SPDX-License-Identifier: MIT
"""Resolve the user's chosen transport and inspect prerequisites without placing a call.

Availability never changes the requested transport. Device identity, last-used
app, and SIM data subscription are not routing rules.
"""
import re
import shutil


def resolve(params):
    backend = params.get('backend')
    app = params.get('app')
    if backend is None:
        # Existing explicit app=cellular/app=<binary> clients remain compatible.
        backend = 'cellular' if app == 'cellular' or (params.get('number') and not app) else 'app' if app else None
    if backend == 'cellular':
        if app and app != 'cellular':
            raise ValueError('手机电话与应用通话参数冲突，请按用户指定的方式选择')
        number = params.get('number', '')
        if not isinstance(number, str) or not re.fullmatch(r'\+?[0-9]{3,15}', number):
            raise ValueError('手机电话需要已核实的电话号码 number')
        return backend, 'cellular'
    if backend == 'app':
        if not isinstance(app, str) or app == 'cellular' or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.+-]*', app):
            raise ValueError('应用通话需要明确指定 app 的进程名称')
        if params.get('number'):
            raise ValueError('应用通话请使用 contact，不能把电话号码当成手机拨号请求')
        return backend, app
    raise ValueError('请明确指定 backend=cellular（手机电话）或 backend=app（应用通话）')


def capabilities(*, key_configured=False, probe=None, router_available=None):
    if probe is None:
        from cellular_audio import request
        probe = lambda: request('status')
    if router_available is None:
        router_available = shutil.which('rungic-audio-route') is not None
    cellular = {'reachable': False, 'audioInterfaceAvailable': None, 'accounts': [],
                'privateVoiceInstructions': False, 'independentMonitor': False,
                'endToEndVerified': False}
    try:
        status = probe()
        if status.get('protocol') != 1:
            raise RuntimeError('unsupported cellular backend protocol')
        cellular.update(reachable=True, audioInterfaceAvailable=bool(status.get('audioCapable')),
                        accounts=status.get('accounts', []), busy=status.get('phoneState') != 0,
                        privateVoiceInstructions=bool(status.get('privateVoiceInstructions')),
                        independentMonitor=bool(status.get('independentMonitor')),
                        endToEndVerified=bool(status.get('endToEndVerified')))
    except (OSError, RuntimeError, ValueError) as error:
        cellular['reason'] = str(error)
    return {'protocol': 1, 'keyConfigured': key_configured,
            'backends': {'cellular': cellular,
                         'app': {'routerAvailable': router_available, 'requiresExplicitApp': True,
                                 'requiresAppVerification': True}},
            'selection': 'user-request-only'}
