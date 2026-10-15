#!/usr/bin/env python3
"""Test adapter for the existing Phase 3 harness, never installed in the product."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent))
import phase3_guest as faults

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def provision():
    faults.guard()
    assert run('findmnt', '-rn', '-M', '/', '-o', 'FSTYPE,FSROOT') == 'btrfs /@'
    assert not Path('/run/archiso').exists()
    policy = Path('/etc/astraeus/secure-boot/policy.json')
    assert not policy.exists() and not Path('/etc/astraeus/boot-generations').exists()
    share = Path('/mnt/astraeus-validation')
    public = share / 'owner'
    certificate = public / 'db.crt'
    expected = json.loads((public/'manifest.json').read_text())['public_fingerprints']['db']
    actual = hashlib.sha256(subprocess.check_output(['openssl','x509','-in',str(certificate),'-outform','DER'])).hexdigest()
    assert actual == expected
    state = Path('/var/lib/astraeus/secure-boot')
    assert not state.exists()
    state.mkdir(mode=0o700, parents=True)
    keys = Path('/var/lib/astraeus/keys')
    keys.mkdir(mode=0o700)
    subprocess.run(['install','-m600',str(share/'private/db.key'),str(keys/'db.key')],check=True)
    policy.parent.mkdir(mode=0o755, parents=True)
    subprocess.run(['install','-m644',str(certificate),str(policy.parent/'db.crt')],check=True)
    policy.write_text(json.dumps(dict(schema_version=1,purpose='disposable-ovmf',certificate=str(policy.parent/'db.crt'),
        private_key=str(keys/'db.key'),certificate_sha256=expected,revoked_certificate_sha256=[]))+'\n')
    receipts = {}
    for kind, source in [('bootloader','/usr/lib/systemd/boot/efi/systemd-bootx64.efi'),
                         ('uki','/efi/EFI/Linux/astraeus-dev-linux.efi')]:
        run('astraeus-secure-boot','stage',kind,source)
        receipts[kind] = json.loads(run('astraeus-secure-boot','verify-candidate',kind))
    for kind, destinations in [('bootloader',['/efi/EFI/systemd/systemd-bootx64.efi','/efi/EFI/BOOT/BOOTX64.EFI']),
                               ('uki',['/efi/EFI/Linux/astraeus-dev-linux.efi'])]:
        candidate = state / (kind+'.ready')
        for destination in destinations:
            subprocess.run(['install','-m600',str(candidate/'artifact.efi'),destination],check=True)
            assert hashlib.sha256(Path(destination).read_bytes()).hexdigest() == receipts[kind]['artifact_sha256']
        candidate.rename(state/(kind+'.consumed.initial'))
    subprocess.run(['sync'],check=True)
    print(json.dumps({'public_certificate_sha256':expected,'receipts':receipts,'firmware_enforcement':'not-yet-tested'}))

def generation_uki(path):
    """Extend the original fault guard to immutable generation paths only."""
    path = path.resolve(strict=True)
    if path.parent == Path('/efi/EFI/Linux'):
        return original_path_guard(path)
    assert path.parent == Path('/efi/EFI/Astraeus') and re.fullmatch(r'[0-9]+-[0-9]+-[0-9]+\.efi',path.name)
    assert path.is_file()
    mount = json.loads(run('findmnt','--json','--target',str(path),'-o','TARGET,SOURCE,FSTYPE'))['filesystems']
    assert len(mount)==1 and mount[0]['target']=='/efi' and mount[0]['fstype']=='vfat' and mount[0]['source']=='/dev/vda1'
    return path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['provision','fault'])
    parser.add_argument('--kind')
    parser.add_argument('--uki',type=Path)
    parser.add_argument('--replacement',type=Path)
    parser.add_argument('--sha256')
    args=parser.parse_args()
    faults.guard()
    if args.action=='provision':
        provision()
    else:
        assert args.uki and args.kind
        faults.uki_path=generation_uki
        faults.fault(args.kind,args.uki,args.replacement,args.sha256)

original_path_guard=faults.uki_path
if __name__=='__main__': main()
