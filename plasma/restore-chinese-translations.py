#!/usr/bin/python3
"""Recover only Chinese .mo files removed by Ubuntu minimal's dpkg filter.

Input must be the authenticated, installed-version apt archive directory.
The resulting staging tree can be archived and extracted into the container.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,subprocess,tarfile
parser=argparse.ArgumentParser()
parser.add_argument('archives',type=Path);parser.add_argument('stage',type=Path)
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
print('Chinese translation files recovered:',count)
