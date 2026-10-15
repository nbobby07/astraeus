"""Seal an actual ISO installation using the existing Phase 2/3 acceptance harness."""
import argparse
import base64
import json
from pathlib import Path
import shutil
import sys

ROOT=Path('/home/ubuntu/p4i/r2')
SRC=ROOT/'harness'
sys.path.insert(0,str(SRC/'scripts/validate'))
import phase2 as p2
import importlib.util
spec=importlib.util.spec_from_file_location('integrated_run',ROOT/'integrated-run.py')
checks=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('encryption',choices=['none','LUKS2'])
    args=parser.parse_args()
    label='plain' if args.encryption=='none' else 'luks'
    source=ROOT/('install-'+label)
    out=ROOT/('base-'+label)
    p2.require(json.loads((source/'result.json').read_text())['passed'],'installer run did not finish')
    out.mkdir(mode=0o700)
    result=dict(passed=False,accepted=False,integrated_acceptance=False,started=p2.now())
    vm=None
    try:
        p2.host(['qemu-img','convert','-O','qcow2',source/'disk.qcow2',out/'disk.qcow2'],timeout=3600)
        shutil.copyfile(source/'vars.fd',out/'vars.fd')
        p2.save(out/'source-installation.json',dict(path=str(source),sha256={n:p2.digest(source/n) for n in ['disk.qcow2','vars.fd']},inputs=json.loads((source/'inputs.json').read_text())))
        share=out/'share'
        share.mkdir(mode=0o755)
        for name in ['phase2-guest.py','phase3_guest.py']:
            shutil.copyfile(SRC/'scripts/validate'/name,share/name)
        for name in ['integrated-guest.py']:
            shutil.copyfile(ROOT/name,share/name)
        shutil.copyfile(SRC/'tests/boot/installed-smoke.sh',share/'installed-smoke.sh')
        shutil.copytree(ROOT/'fixtures',share/'fixtures')
        owner=share/'owner'
        owner.mkdir()
        for name in ['manifest.json','db.crt']:
            shutil.copyfile(ROOT/'owner-firmware'/name,owner/name)
        (share/'private').mkdir(mode=0o700)
        shutil.copyfile('/root/astraeus-p3i-keys/db.key',share/'private/db.key')
        (share/'private/db.key').chmod(0o600)
        vm=p2.VM(out,Path('/usr/share/OVMF/OVMF_CODE_4M.fd'),share,1800)
        vm.start()
        print('Run original installed-smoke.sh in the actual desktop session, then phase2-guest.py setup using its log.',flush=True)
        vm.ready()
        acceptance=vm.command('cat /var/lib/astraeus-validation/installed-acceptance.log',label='installed-acceptance')['output']
        p2.require(p2.marker_present(acceptance,f'DISTRO_INSTALL_OK: uefi uki {args.encryption} btrfs sddm plasma wayland network audio status'),'installed desktop acceptance missing')
        p2.healthy(p2.observe(vm,'installed-first',product=False),args.encryption)
        vm.command('bash /mnt/astraeus-validation/fixtures/prepare-baseline.sh',timeout=300,label='prepare-signed-fixtures')
        vm.command('python3 /mnt/astraeus-validation/integrated-guest.py provision',timeout=300,label='owner-provisioning')
        artifacts=out/'public-artifacts'
        artifacts.mkdir()
        public_hashes={}
        for name,path in [('loader','/usr/lib/systemd/boot/efi/systemd-bootx64.efi'),
                          ('uki','/var/lib/astraeus/secure-boot/uki.consumed.initial/input.efi')]:
            metadata=vm.command('stat -c %s '+path+'; sha256sum '+path,label='export-'+name+'-identity')['output'].split()
            size,expected=int(metadata[0]),metadata[1]
            with (artifacts/(name+'.efi')).open('wb') as stream:
                for offset in range(0,size,2*1024*1024):
                    part=vm.command(f'dd if={path} bs=2097152 skip={offset//2097152} count=1 status=none | base64 -w0',label='export-'+name)['output']
                    stream.write(base64.b64decode(part,validate=True))
            p2.require((artifacts/(name+'.efi')).stat().st_size==size and p2.digest(artifacts/(name+'.efi'))==expected,'exported public artifact differs')
            public_hashes[name]=dict(path=path,sha256=expected,bytes=size)
        p2.save(artifacts/'provenance.json',public_hashes)
        vm.shutdown()
        # Only this disposable VARS copy is enrolled. Installation was compatibility setup.
        shutil.copyfile(ROOT/'owner-firmware/vars.fd',out/'vars.fd')
        p2.save(out/'enrolled-vars-input.json',dict(sha256=p2.digest(out/'vars.fd')))
        vm.code=Path('/usr/share/OVMF/OVMF_CODE_4M.secboot.fd')
        vm.secure_boot=True
        public=json.loads((ROOT/'owner-firmware/manifest.json').read_text())
        manifest=dict(kind='phase3-integrated',source_commit='cac8998ad7730e69ae354c3162ef4a0677cfc162',
                      encryption=args.encryption,signer_sha256=public['public_fingerprints']['db'],
                      installed_binaries=json.loads((ROOT/'installed-binaries.json').read_text()),
                      iso=json.loads((source/'inputs.json').read_text())['iso'])
        # Capture two actual cold boots with the exact packaged binaries and enrolled identities.
        for index in range(2):
            checks.boot(vm,manifest,'enforced-'+str(index+1))
            vm.command('systemctl start NetworkManager-wait-online.service',timeout=120,label='wait-online')
            state,_=checks.inventory(vm,'enforced-'+str(index+1))
            p2.healthy(state,args.encryption)
            print('Log in to the enforced Plasma session now; desktop acceptance is waiting.',flush=True)
            vm.command('''for attempt in $(seq 1 300); do
  if pgrep -u tester -x plasmashell >/dev/null && test -S /run/user/1000/bus; then break; fi
  sleep 1
done
loginctl list-sessions --no-legend
pid=$(pgrep -u tester -x plasmashell | head -n1)
test -n "$pid"
python3 - "$pid" <<'PY'
import os,subprocess,sys
from pathlib import Path
env=dict(x.decode().split('=',1) for x in Path('/proc/'+sys.argv[1]+'/environ').read_bytes().split(b'\\0') if b'=' in x)
assert env['USER']=='tester' and env['XDG_SESSION_TYPE']=='wayland' and 'KDE' in env['XDG_CURRENT_DESKTOP']
args=['runuser','-u','tester','--','env']+[k+'='+env[k] for k in ['XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS']]
subprocess.run(args+['bash','-s','''+repr(args.encryption)+'''],input=Path('/mnt/astraeus-validation/installed-smoke.sh').read_bytes(),check=True)
PY''',timeout=360,label='enforced-desktop-'+str(index+1))
            if index==0:
                vm.command('astraeus-boot-artifact ready /efi',label='provider-ready')
                vm.command('distroctl boot enable',label='enable-generations')
            vm.shutdown()
        manifest.update(accepted=True,created=p2.now(),sha256={n:p2.digest(out/n) for n in ['disk.qcow2','vars.fd']},
                        inputs=dict(ovmf_code=dict(path=str(vm.code),sha256=p2.digest(vm.code))))
        p2.save(out/'baseline.json',manifest)
        for n in ['disk.qcow2','vars.fd']: (out/n).chmod(0o444)
        result.update(passed=True,accepted=True,integrated_acceptance=True)
    except BaseException as error:
        result['error']=f'{type(error).__name__}: {error}'
        if vm and vm.boot_id and vm.child.poll() is None:
            try: checks.inventory(vm,'failure')
            except Exception as extra: result['diagnostics_error']=str(extra)
        raise
    finally:
        if vm: vm.stop()
        result['finished']=p2.now()
        p2.save(out/'result.json',result)

if __name__=='__main__': main()
