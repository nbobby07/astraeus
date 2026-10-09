"""Check the exact built live and installed payloads without boot-time provisioning."""
from pathlib import Path
import hashlib,json,subprocess
r=Path('/home/ubuntu/p3i/final')
identity=json.loads((r/'iso-input.json').read_text())
iso=Path(identity['path'])
with iso.open('rb') as stream: assert hashlib.file_digest(stream,'sha256').hexdigest()==identity['sha256']
out=r/'iso-audit';out.mkdir(mode=0o700)
live=out/'live.sfs';installed=out/'installed.sfs'
with (out/'extract.log').open('wb') as log:
 subprocess.run(['xorriso','-osirrox','on','-indev',str(iso),'-extract','/arch/x86_64/airootfs.sfs',str(live)],stdout=log,stderr=subprocess.STDOUT,check=True)
with installed.open('wb') as stream:
 subprocess.run(['unsquashfs','-cat',str(live),'opt/distro/install-root.sfs'],stdout=stream,check=True)
expected=json.loads((r/'installed-binaries.json').read_text())
result=dict(iso=identity,source_commit=json.loads((r/'source-r3.json').read_text())['source_commit'],payloads={},passed=False)
for kind,image in [('live',live),('installed',installed)]:
 listing=subprocess.check_output(['unsquashfs','-ll',str(image)],text=True)
 (out/(kind+'-files.txt')).write_text(listing)
 forbidden=['var/lib/astraeus/keys','var/lib/astraeus/secure-boot','etc/astraeus/secure-boot/policy.json','var/lib/astraeus-validation','mnt/astraeus-validation','private-keys-v1.d','db.key','PK.key','KEK.key','phase2-guest.py','integrated-guest.py']
 for path in forbidden:
  assert 'squashfs-root/'+path not in listing,(kind,path)
  if '/' not in path: assert not any(line.rstrip().endswith('/'+path) for line in listing.splitlines()),(kind,path)
 observed={}
 for path,sha in expected.items():
  content=subprocess.check_output(['unsquashfs','-cat',str(image),path.lstrip('/')])
  observed[path]=hashlib.sha256(content).hexdigest()
  assert observed[path]==sha,(kind,path)
 with image.open('rb') as stream: sha=hashlib.file_digest(stream,'sha256').hexdigest()
 result['payloads'][kind]=dict(sha256=sha,bytes=image.stat().st_size,files_sha256=hashlib.sha256(listing.encode()).hexdigest(),binaries=observed,absent_paths=forbidden)
passwd=subprocess.check_output(['unsquashfs','-cat',str(installed),'etc/passwd'],text=True)
assert not any(line.split(':')[0] in ['live','tester'] for line in passwd.splitlines())
result['installed_test_accounts_absent']=True
result['passed']=True
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
# These are exact decompressions of the retained ISO; keep their hashes and inventories.
for p in [live,installed]:
 assert p.resolve(strict=True).parent==out.resolve(strict=True)
 p.unlink()
print(json.dumps(result,indent=2))
