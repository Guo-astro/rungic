#!/usr/bin/python3
"""One-time root bootstrap, invoked only by the Magisk-authorized APK via stdin.

Uses Ubuntu shadow/PAM tools. Never accepts passwords in argv or logs them.
The UID stays stable so existing shared files survive; the home follows the chosen login
(/home/<name>, docs/70), moved with its contents and the paths in the user's settings.
"""
import json
import grp
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import time

# Shared with the Android side through state/host (docs/61 §7); the old location is read once.
STATE = Path('/var/lib/rungic-host/account.json')
LEGACY_STATE = Path('/etc/moto-plasma/account.json')
OWNER_UID = 1000

class SetupError(Exception):
    pass

def validate(data, current):
    if not isinstance(data, dict):
        raise SetupError('无效的账户信息')
    name, password = data.get('username'), data.get('password')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', name):
        raise SetupError('用户名须以小写字母开头，最多32位，可包含数字、下划线和短横线')
    if not isinstance(password, str) or not 8 <= len(password) or len(password.encode()) > 256 or any(c in password for c in '\r\n\0'):
        raise SetupError('密码至少8个字符，且不能包含换行')
    try:
        existing = pwd.getpwnam(name)
    except KeyError:
        existing = None
    if existing is not None and existing.pw_uid != OWNER_UID:
        raise SetupError('这个用户名已被使用')
    if current.pw_uid != OWNER_UID or not re.fullmatch(r'/home/[a-z][a-z0-9_-]*', current.pw_dir):
        raise SetupError('账户布局与当前安装不匹配')
    if home_of(name) != current.pw_dir and os.path.lexists(home_of(name)):
        raise SetupError('这个用户名的主目录已存在')
    return name, password

def home_of(name):
    return '/home/' + name

def call(argv, payload=None, check=True):
    result = subprocess.run(argv, input=payload, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=35)
    if check and result.returncode:
        raise SetupError('账户配置失败，请重试；现有文件不会被删除')
    return result.returncode

def shadow_entry(name):
    for line in Path('/etc/shadow').read_text().splitlines():
        fields = line.split(':')
        if fields[0] == name:
            return fields[1]
    raise SetupError('无法读取当前账户状态')

def configure(data):
    if not STATE.exists() and LEGACY_STATE.exists():
        STATE.write_text(LEGACY_STATE.read_text())
    if STATE.exists():
        raise SetupError('初始账户已设置，请在系统账户设置中修改密码')
    current = pwd.getpwuid(OWNER_UID)
    name, password = validate(data, current)
    old_hash = shadow_entry(current.pw_name)
    old_groups = ','.join(grp.getgrgid(gid).gr_name
                          for gid in os.getgrouplist(current.pw_name, current.pw_gid)
                          if gid != current.pw_gid)
    if old_hash and old_hash[0] not in '!*':
        raise SetupError('此账户已有密码，请使用系统账户设置')
    # Stop the user session before usermod: renaming a logged-in account is
    # deliberately refused by shadow-utils. The root attach process survives.
    call(['systemctl', 'stop', 'rungic-plasma-session.service'])
    # The shared storage is mounted inside the home, which moves with the login.
    call(['systemctl', 'stop', 'rungic-plasma-shared.service'], check=False)
    call(['loginctl', 'terminate-user', str(OWNER_UID)], check=False)
    call(['systemctl', 'stop', 'user@1000.service'], check=False)
    # logind tears down session scopes asynchronously; wait for the UID to exit.
    for _ in range(50):
        if call(['pgrep', '-u', str(OWNER_UID)], check=False) != 0:
            break
        time.sleep(.1)
    else:
        raise SetupError('桌面仍在退出，请稍后重试')
    renamed = False
    try:
        if name != current.pw_name:
            call(['usermod', '--login', name, '--home', home_of(name), '--move-home', current.pw_name])
            renamed = True
        # Standard administrative identity for Ubuntu's normal polkit policy.
        call(['usermod', '--append', '--groups', 'sudo,systemd-journal', name])
        call(['chpasswd'], (name + ':' + password + '\n').encode())
        STATE.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        temporary = STATE.with_suffix('.tmp')
        with open(temporary, 'w', opener=lambda path, flags: os.open(path, flags, 0o600)) as f:
            json.dump({'configured': True, 'username': name, 'uid': OWNER_UID, 'version': 1}, f)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, STATE)
    except Exception:
        # Restore locked-password state on failure, then restore the original
        # login name. Neither the password nor a password hash is printed.
        call(['chpasswd', '--encrypted'], (name + ':' + old_hash + '\n').encode(), check=False)
        call(['usermod', '--groups', old_groups, name], check=False)
        if renamed:
            call(['usermod', '--login', current.pw_name, '--home', current.pw_dir, '--move-home', name], check=False)
        raise
    # Any legacy linger marker is a login name, unlike file ownership (UID).
    old_linger = Path('/var/lib/systemd/linger') / current.pw_name
    if renamed and old_linger.exists():
        old_linger.rename(old_linger.with_name(name))
    if renamed and home_of(name) != current.pw_dir:
        # Paths into the old home in the user's settings; /home/linux, the link kept since the
        # Rungic rename (rungic-rebrand-system), follows the home.
        call(['runuser', '-u', name, '--', 'env', 'HOME=' + home_of(name), '/usr/libexec/rungic-rebrand-user',
              'rehome', current.pw_dir, home_of(name)], check=False)
        if os.path.islink('/home/linux'):
            os.unlink('/home/linux')
            os.symlink(name, '/home/linux')
    call(['systemctl', 'try-restart', 'accounts-daemon.service'], check=False)
    return {'configured': True, 'username': name}

def main():
    if os.geteuid() != 0:
        raise SetupError('需要安装程序的管理员权限')
    raw = sys.stdin.buffer.read(4097)
    if len(raw) > 4096:
        raise SetupError('账户信息过长')
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise SetupError('无效的账户信息') from None
    print(json.dumps(configure(data), ensure_ascii=False))

if __name__ == '__main__':
    try:
        main()
    except SetupError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('账户配置失败，请重试', file=sys.stderr)
        sys.exit(1)
