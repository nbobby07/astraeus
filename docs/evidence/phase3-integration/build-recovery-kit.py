"""Disposable signed recovery companion for the exact integrated installation ISO."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path('/home/ubuntu/p3i/final')
SRC=ROOT.parent/'candidate-r3'
sys.path.insert(0,str(SRC/'scripts/validate'))
import phase2 as p2
import phase3 as p3
out=ROOT/'recovery-kit'
iso=ROOT/'build-r3/evidence/A/astraeus-dev-0.1.0-dev-x86_64.iso'
expected=json.loads((ROOT/'iso-input.json').read_text())['sha256']
assert p2.digest(iso)==expected
assert not (out/'disk.qcow2').exists()
def run(*command,timeout=180):
    return p3.execute(out,list(command),timeout=timeout)
cache=ROOT/'build-r3/package-cache'
package_inputs={}
for package,member,name in [('systemd-ukify','usr/bin/ukify','ukify'),
                          ('systemd','usr/lib/systemd/boot/efi/linuxx64.efi.stub','linuxx64.efi.stub'),
                          ('systemd','usr/lib/systemd/boot/efi/systemd-bootx64.efi','loader.efi')]:
    archive=cache/(package+'-262-1-x86_64.pkg.tar.zst')
    package_inputs[archive.name]=p2.digest(archive)
    with (out/name).open('wb') as stream:
        subprocess.run(['tar','--zstd','-xOf',str(archive),member],stdout=stream,check=True)
assert '262' in run('/usr/bin/python3',out/'ukify','--version').stdout
for name,member in [('vmlinuz','/arch/boot/x86_64/vmlinuz-linux'),
                    ('initrd','/arch/boot/x86_64/initramfs-linux.img'),
                    ('live.conf','/loader/entries/01-live.conf')]:
    run('xorriso','-osirrox','on','-indev',iso,'-extract',member,out/name)
options=[line.split(None,1)[1] for line in (out/'live.conf').read_text().splitlines() if line.startswith('options ')]
assert len(options)==1 and 'archisosearchuuid=' in options[0]
(out/'cmdline').write_text(options[0]+' astraeus.recovery_iso_sha256='+expected+'\n')
(out/'os-release').write_text('ID=astraeus-recovery-test\nPRETTY_NAME="Astraeus disposable trusted recovery"\nVERSION_ID=fdb784c\n')
run('/usr/bin/python3',out/'ukify','--config=/dev/null','--stub',out/'linuxx64.efi.stub',
    '--linux',out/'vmlinuz','--initrd',out/'initrd','--cmdline','@'+str(out/'cmdline'),
    '--os-release','@'+str(out/'os-release'),'--uname','7.2.7-arch1-1',
    '--output',out/'recovery-unsigned.efi','build')
public=ROOT/'owner-firmware'
for source,name in [('loader.efi','loader-signed.efi'),('recovery-unsigned.efi','recovery.efi')]:
    run('sbsign','--key','/root/astraeus-p3i-keys/db.key','--cert',public/'db.crt',
        '--output',out/name,out/source)
    run('sbverify','--cert',public/'db.crt',out/name)
    inspected=run('/usr/bin/python3',out/'ukify','--config=/dev/null','--json=short','--all','inspect',out/name)
    (out/(name+'.sections.json')).write_text(inspected.stdout)
raw=out/'recovery.fat'
with raw.open('wb') as stream: stream.truncate(512*1024*1024)
run('mkfs.vfat',raw)
run('mmd','-i',raw,'::/EFI','::/EFI/BOOT','::/EFI/Linux','::/loader')
(out/'loader.conf').write_text('default recovery.efi\ntimeout 0\neditor no\n')
for source,target in [('loader-signed.efi','/EFI/BOOT/BOOTX64.EFI'),('recovery.efi','/EFI/Linux/recovery.efi'),('loader.conf','/loader/loader.conf')]:
    run('mcopy','-i',raw,out/source,'::'+target)
run('qemu-img','convert','-f','raw','-O','qcow2',raw,out/'disk.qcow2')
raw.unlink()
manifest=dict(kind='disposable-trusted-recovery-companion',source_commit='fdb784c8539fb7679f7ab6e350583f523a80728d',
              iso_sha256=expected,disk_sha256=p2.digest(out/'disk.qcow2'),package_inputs=package_inputs,
              owner_db_sha256=json.loads((public/'manifest.json').read_text())['public_fingerprints']['db'],
              files={name:p2.digest(out/name) for name in ['ukify','linuxx64.efi.stub','vmlinuz','initrd','loader.efi','loader-signed.efi','recovery.efi','cmdline']},
              limitations=['Companion and ISO are test recovery media, not a release artifact.','Secure Boot authenticates loader and UKI. The live SquashFS is not covered by that signature.'],
              boot_qualified=False)
p2.save(out/'manifest.json',manifest)
print(json.dumps(manifest,indent=2))
