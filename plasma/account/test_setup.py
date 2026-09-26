import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('setup',Path(__file__).with_name('setup.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
current=SimpleNamespace(pw_uid=1000,pw_gid=1000,pw_name='rungic',pw_dir='/home/rungic')

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.state=Path(self.tmp.name)/'account.json'
  for p in [patch.object(m,'STATE',self.state),patch.object(m.pwd,'getpwuid',return_value=current),
            patch.object(m.pwd,'getpwnam',side_effect=KeyError),patch.object(m,'shadow_entry',return_value='!'),
            patch.object(m.os,'getgrouplist',return_value=[1000,29]),
            patch.object(m.grp,'getgrgid',return_value=SimpleNamespace(gr_name='audio'))]:
   p.start();self.addCleanup(p.stop)
 def test_validation(self):
  for name,password in [('root;id','abcdefgh'),('../name','abcdefgh'),('Alice','abcdefgh'),('alice','short'),('alice','abcde\nfgh'),('alice','密'*100)]:
   with self.assertRaises(m.SetupError):m.validate({'username':name,'password':password},current)
  with patch.object(m.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=0)):
   with self.assertRaises(m.SetupError):m.validate({'username':'root','password':'abcdefgh'},current)
 def test_success_uses_stdin_and_writes_once(self):
  calls=[]
  def call(argv,payload=None,check=True):
   calls.append((argv,payload));return 1 if argv[0]=='pgrep' else 0
  with patch.object(m,'call',side_effect=call):
   result=m.configure({'username':'alice','password':'test-only-pass'})
   self.assertEqual(result['username'],'alice')
   self.assertEqual(self.state.stat().st_mode & 0o777,0o600)
   self.assertNotIn('test-only-pass',self.state.read_text())
   self.assertTrue(any(a==['usermod','--login','alice','rungic'] for a,_ in calls))
   self.assertTrue(any(a==['chpasswd'] and b==b'alice:test-only-pass\n' for a,b in calls))
   self.assertFalse(any('test-only-pass' in ' '.join(a) for a,_ in calls))
   with self.assertRaises(m.SetupError):m.configure({'username':'alice','password':'another-test-pass'})
 def test_failure_rolls_back(self):
  calls=[]
  def call(argv,payload=None,check=True):
   calls.append((argv,payload))
   if argv==['chpasswd']:raise m.SetupError('simulated')
   return 1 if argv[0]=='pgrep' else 0
  with patch.object(m,'call',side_effect=call):
   with self.assertRaises(m.SetupError):m.configure({'username':'alice','password':'test-only-pass'})
  self.assertFalse(self.state.exists())
  self.assertIn((['chpasswd','--encrypted'],b'alice:!\n'),calls)
  self.assertIn((['usermod','--groups','audio','alice'],None),calls)
  self.assertIn((['usermod','--login','rungic','alice'],None),calls)
 def test_existing_password_cannot_be_bootstrapped(self):
  with patch.object(m,'shadow_entry',return_value='$y$existing'),patch.object(m,'call') as c:
   with self.assertRaises(m.SetupError):m.configure({'username':'alice','password':'test-only-pass'})
   c.assert_not_called()

unittest.main()
