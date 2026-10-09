import hashlib
import json
from pathlib import Path
import shutil
import subprocess

root=Path('/home/ubuntu/p3i/final')
build=root/'build-r3'
source=root/'candidate-r3'
fixtures=root/'fixtures'
assert not fixtures.exists()
fixtures.mkdir(mode=0o755)
for name in ['fixture-repo-1','fixture-repo-2']:
    shutil.copytree(build/name,fixtures/name)
shutil.copyfile(source/'tests/fixtures/phase2/adapter.sh',fixtures/'adapter.sh')
shutil.copyfile('/home/ubuntu/p2sec/prepare-baseline.sh',fixtures/'prepare-baseline.sh')
shutil.copyfile(build/'repository-fingerprint.txt',fixtures/'repository-fingerprint.txt')
shutil.copyfile(build/'repo/repository-key.asc',fixtures/'repository-key.asc')
pin=(fixtures/'repository-fingerprint.txt').read_text().strip()
assert len(pin)==40 and all(c in '0123456789ABCDEF' for c in pin)
keyring=root/'repository-keyring'
keyring.mkdir(mode=0o700)
subprocess.run(['gpg','--homedir',str(keyring),'--batch','--import',str(fixtures/'repository-key.asc')],check=True)
receipts=[]
for directory in [build/'repo',fixtures/'fixture-repo-1',fixtures/'fixture-repo-2']:
    subprocess.run(['sha256sum','-c','SHA256SUMS'],cwd=directory,check=True)
    for package in [*directory.glob('*.pkg.tar.zst'),directory/'distro.db.tar.gz']:
        result=subprocess.run(['gpg','--homedir',str(keyring),'--batch','--status-fd','1','--verify',str(package)+'.sig',str(package)],capture_output=True,text=True)
        receipts.append({'file':str(package),'exit_code':result.returncode,'output':result.stdout+result.stderr})
        assert result.returncode==0 and pin in result.stdout
(root/'repository-verification.json').write_text(json.dumps(receipts,indent=2)+'\n')
package,=build.joinpath('repo').glob('distroctl-0*.pkg.tar.zst')
expected={}
for name in ['usr/bin/distroctl','usr/bin/astraeus-secure-boot','usr/bin/astraeus-boot-artifact']:
    payload=subprocess.check_output(['tar','--zstd','-xOf',str(package),name])
    expected['/'+name]=hashlib.sha256(payload).hexdigest()
assert expected['/usr/bin/astraeus-secure-boot']==expected['/usr/bin/astraeus-boot-artifact']
assert expected['/usr/bin/astraeus-secure-boot']==hashlib.sha256((source/'scripts/secure_boot.py').read_bytes()).hexdigest()
(root/'installed-binaries.json').write_text(json.dumps(expected,indent=2)+'\n')
print(json.dumps({'repository_fingerprint':pin,'installed_binaries':expected},indent=2))
