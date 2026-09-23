import subprocess,shlex,pathlib
ADB=['/home/kevinzhow/Android/Sdk/platform-tools/adb','-s','ZY32MVJS25']
ROOT='/data/adb/moto-lxc/runtime/var/lib/lxc/plasma/rootfs'
def root(cmd,**kwargs):
 return subprocess.run(ADB+['shell','su -c '+shlex.quote(cmd)],check=True,**kwargs)
def put(src,dest,mode='644',owner='0:0'):
 tmp='/data/local/tmp/moto-feature-upload'
 subprocess.run(ADB+['push',str(src),tmp],check=True,stdout=subprocess.DEVNULL)
 root('mkdir -p '+shlex.quote(str(pathlib.PurePosixPath(dest).parent))+' && cp '+tmp+' '+shlex.quote(dest)+' && chown '+owner+' '+shlex.quote(dest)+' && chmod '+mode+' '+shlex.quote(dest))
def linux(*args,user=False,**kwargs):
 return subprocess.run(['python3','tools/moto_plasma.py','user-exec' if user else 'exec',*args],check=True,**kwargs)
def termux(cmd,**kwargs):
 p='/data/data/com.termux/files/usr'
 return root('su 10348 -c '+shlex.quote('env PATH='+p+'/bin:/system/bin PREFIX='+p+' TMPDIR='+p+'/tmp /system/bin/sh -c '+shlex.quote(cmd)),**kwargs)
