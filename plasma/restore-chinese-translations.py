#!/usr/bin/python3
"""Recover only Chinese .mo files removed by Ubuntu minimal's dpkg filter.

Input must be the authenticated, installed-version apt archive directory.
Writes the staging tree and ARCHIVE: regular files only, owned by root, so
`tar -xf ARCHIVE -C /` inside the container cannot change the owner or mode of
/, /usr or other existing directories. (An earlier tree archived with the
builder's UID made / and /usr owned by the desktop user.)
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,subprocess,tarfile
parser=argparse.ArgumentParser()
parser.add_argument('archives',type=Path);parser.add_argument('stage',type=Path);parser.add_argument('archive',type=Path)
args=parser.parse_args();args.stage.mkdir(parents=True,exist_ok=True)
prefixes=('usr/share/locale/zh_CN/LC_MESSAGES/', 'usr/share/locale/zh_Hans/LC_MESSAGES/')
def extract(deb):
 count=0
 process=subprocess.Popen(['dpkg-deb','--fsys-tarfile',str(deb)],stdout=subprocess.PIPE)
 with tarfile.open(fileobj=process.stdout,mode='r|') as stream:
  for member in stream:
   name=member.name.removeprefix('./')
   if not (member.isfile() and name.startswith(prefixes) and name.endswith('.mo')):continue
   relative=Path(name)
   if '..' in relative.parts:raise ValueError(name)
   target=args.stage/relative;target.parent.mkdir(parents=True,exist_ok=True)
   target.write_bytes(stream.extractfile(member).read());target.chmod(0o644);count+=1
 if process.wait()!=0:raise RuntimeError(str(deb))
 return count
with ThreadPoolExecutor(4) as pool:count=sum(pool.map(extract,sorted(args.archives.glob('*.deb'))))
def owned_by_root(info):
 info.uid=info.gid=0;info.uname=info.gname='root';info.mode=0o644;return info
with tarfile.open(args.archive,'w') as out:
 for path in sorted(p for p in args.stage.rglob('*.mo') if p.is_file()):
  out.add(path,arcname=str(path.relative_to(args.stage)),filter=owned_by_root)
print('Chinese translation files recovered:',count)
