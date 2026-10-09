"""Run the unchanged Phase 4 assertions with inspected runtimes and extra evidence."""
from pathlib import Path
import json,os,shutil,sys,time
from types import SimpleNamespace
ROOT=Path('/home/ubuntu/p4i/r2')
sys.path.insert(0,str(ROOT/'harness/scripts/validate'))
import phase4
p2=phase4.p2
class VM(p2.VM):
 def start(self,*args,**kwargs):
  runtime=self.share/'runtime-inputs';runtime.mkdir()
  for name in ['GE-Proton11-7-x86_64.tar.gz','SteamLinuxRuntime_4.tar.xz']:
   os.link(ROOT.parent/'runtime-inputs'/name,runtime/name)
  for name in ['gaming-runtime-setup.py','gaming-negatives.py','gaming-session.py']:
   shutil.copyfile(ROOT/name,self.share/name)
  p2.save(self.out/'additional-inputs.json',dict(guest_memory_mib=8192,
   adapters={name:p2.digest(ROOT/name) for name in ['integrated-gaming.py','gaming-runtime-setup.py','gaming-negatives.py','gaming-session.py']},
   runtimes={path.name:p2.digest(path) for path in runtime.iterdir()}))
  original=p2.install.qemu_command
  def gaming_command(*a,**kw):
   command=original(*a,**kw);assert command.count('-m')==1
   command[command.index('-m')+1]='8192';return command
  p2.install.qemu_command=gaming_command
  try:super().start(*args,**kwargs)
  finally:p2.install.qemu_command=original
 def command(self,command,timeout=None,check=True,label='command'):
  if label!='graphics-suite':return super().command(command,timeout,check,label)
  super().command('runuser -u tester -- python3 /mnt/astraeus-validation/gaming-runtime-setup.py',timeout=600,label='extract-inspected-runtimes')
  result=super().command(command,timeout,check,label)
  p2.save(self.out/'original-guest.json',json.loads(result['output']))
  extra=super().command('python3 /mnt/astraeus-validation/gaming-negatives.py',timeout=600,label='production-negatives')
  p2.save(self.out/'production-negatives.json',json.loads(extra['output']))
  extra=super().command('python3 /mnt/astraeus-validation/gaming-session.py diagnostics',timeout=180,label='production-diagnostics')
  p2.save(self.out/'production-diagnostics.json',json.loads(extra['output']))
  p2.save(self.out/'inspection-ready.json',dict(qmp=str(self.monitor),channel=str(self.channel)))
  print('Supplemental Steam and visible-overlay inspection ready: '+str(self.out),flush=True)
  deadline=time.monotonic()+1800
  while not (self.out/'inspection-complete.json').is_file():
   self.alive()
   if time.monotonic()>deadline:raise TimeoutError('supplemental inspection not completed')
   time.sleep(1)
  receipt=json.loads((self.out/'inspection-complete.json').read_text())
  assert receipt['evidence_reviewed'] is True
  return result
p2.VM=VM
for proc in Path('/proc').glob('[0-9]*/cmdline'):
 try:command=proc.read_bytes()
 except OSError:continue
 assert b'qemu-system' not in command.split(b'\0')[0],str(proc)
phase4.run(SimpleNamespace(base=ROOT/'base-plain',output=ROOT/'gaming-plain',
 ovmf_code=Path('/usr/share/OVMF/OVMF_CODE_4M.secboot.fd'),
 source_commit='cac8998ad7730e69ae354c3162ef4a0677cfc162',user='tester',autologin=True,
 proton='/home/tester/.local/share/Steam/compatibilitytools.d/GE-Proton11-7-x86_64/proton',
 runtime='/home/tester/phase4-runtimes/SteamLinuxRuntime_4/_v2-entry-point',
 hooks=None,fixture_binaries=ROOT.parent/'prebuilt',timeout=300))
