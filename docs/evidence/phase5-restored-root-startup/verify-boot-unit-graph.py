"""Static verification only. Never install or start the proposed units."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,tempfile
assert os.geteuid()==0 and Path('/dev/virtio-ports/org.astraeus.validation').exists()
source=Path('/mnt/astraeus-validation/unit-verify')
original=Path('/usr/lib/systemd/system/astraeus-confirm-boot.service').read_text()
guards=lambda s:[x for x in s.splitlines() if x.startswith('ConditionPathExists=')]
assert guards(source.joinpath('astraeus-confirm-boot.service').read_text())==guards(original)
assert guards(source.joinpath('astraeus-bless-boot.conf').read_text())==guards(original)
rows=[]
with tempfile.TemporaryDirectory(prefix='astraeus-unit-verify-',dir='/run') as tmp:
 root=Path(tmp);assert root.parent==Path('/run')
 shutil.copyfile(source/'astraeus-confirm-boot.service',root/'astraeus-confirm-boot.service')
 shutil.copyfile('/usr/lib/systemd/system/systemd-bless-boot.service',root/'systemd-bless-boot.service')
 drop=root/'systemd-bless-boot.service.d';drop.mkdir();shutil.copyfile(source/'astraeus-bless-boot.conf',drop/'astraeus.conf')
 for checker in [False,True]:
  if checker:
   required=root/'boot-complete.target.requires';required.mkdir()
   (required/'systemd-boot-check-no-failures.service').symlink_to('/usr/lib/systemd/system/systemd-boot-check-no-failures.service')
  env=dict(os.environ,SYSTEMD_UNIT_PATH=str(root)+':/etc/systemd/system:/run/systemd/system:/usr/lib/systemd/system')
  result=subprocess.run(['systemd-analyze','verify','--man=no',str(root/'astraeus-confirm-boot.service'),str(root/'systemd-bless-boot.service'),'graphical.target'],env=env,text=True,capture_output=True,timeout=60)
  rows.append({'optional_boot_checker_enabled':checker,'code':result.returncode,'diagnostics':result.stdout+result.stderr})
  assert result.returncode==0,rows[-1]
print(json.dumps({'passed':True,'units_installed_or_started':False,'original_history_and_live_guards_preserved':True,'cases':rows,'hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}}))
