"""Reuse the Phase 2 destructive suite with enforcing boot and signed recovery media."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import shlex
import sys
ROOT=Path('/home/ubuntu/p4i/r2')
SRC=ROOT/'harness'
sys.path.insert(0,str(SRC/'scripts/validate'))
import phase2 as p2
import phase3 as p3
spec=importlib.util.spec_from_file_location('checks',ROOT/'integrated-run.py')
checks=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
original_observe=p2.observe

def observe(vm,label,product=True):
    result=original_observe(vm,label,product)
    # The Phase 2 assertion is unchanged; the active UKI now has an immutable path.
    if product:
        result['uki-sha256']=vm.command('p=$(bootctl --print-stub-path); if test ! -f "$p"; then p=/efi/EFI/Astraeus/maintenance.efi; fi; sha256sum "$p"',check=False,label=label+'-generation-uki')
        p2.save(vm.out/(label+'.json'),result)
    return result
p2.observe=observe
original_adapter=p2.adapter

def adapter(vm,action,*args,check=True):
    if action!='reconcile':
        return original_adapter(vm,action,*args,check=check)
    reply=vm.command('systemctl start astraeus-confirm-boot.service',check=False,label='wait-recovery-confirmation')
    p2.require(reply['code']==1,'interruption must boot the retained recovery root')
    records=json.loads(vm.command('distroctl history --json',label='interrupted-history')['output'])
    p2.require(len(records)==1,'unexpected interruption history')
    record=records[0]
    p2.require(record['state']=='rollback_required' and record['failure']['interrupted'] is True and record['confirmation'] is None,'interrupted update was not safely reconciled')
    p2.require(any(a.get('boot_id')==vm.boot_id and a.get('snapshot')==record['snapshot'] and a.get('error')=='Booted retained known-good recovery root; offline restoration and finalize-rollback still required' for a in record['boot_attempts']),'confirmation failed for an unrelated reason')
    verified=json.loads(vm.command('distroctl boot verify '+record['snapshot']+' --json',label='interruption-retained-pair')['output'])
    p2.require(verified['generations'][0]['artifact_verified_now'],'retained recovery pair is not valid')
    return vm.command(shlex.join(['bash','/mnt/astraeus-validation/fixtures/adapter.sh',action,*args]),label=action,check=check)
p2.adapter=adapter

class TrustedVM(p2.VM):
    def __init__(self,*args,manifest,**kwargs):
        super().__init__(*args,**kwargs)
        self.manifest=manifest
        self.recovery=False
    def start(self,iso=None):
        self.recovery=iso is not None
        original=p2.install.qemu_command
        if iso:
            kit=json.loads((ROOT/'recovery-kit/manifest.json').read_text())
            p2.require(p2.digest(iso)==kit['iso_sha256'],'recovery ISO changed')
            p2.require(p2.digest(ROOT/'recovery-kit/disk.qcow2')==kit['disk_sha256'],'recovery companion changed')
            def with_recovery(*a,**kw):
                cmd=original(*a,**kw)
                cmd[cmd.index('ide-cd,drive=installiso,bootindex=1')]='ide-cd,drive=installiso,bootindex=3'
                return cmd+['-drive','if=none,id=recovery,format=qcow2,readonly=on,file='+str(ROOT/'recovery-kit/disk.qcow2'),
                            '-device','virtio-blk-pci,drive=recovery,bootindex=1,serial=P3_RECOVERY_TEST']
            p2.install.qemu_command=with_recovery
        try: super().start(iso)
        finally: p2.install.qemu_command=original
        print('Unlock/login or start the live test agent through private QMP if required: '+str(self.monitor),flush=True)
    def ready(self):
        super().ready()
        if not self.recovery:
            checks.trusted_boot(self,self.manifest,'regression-boot')
            return
        kit=json.loads((ROOT/'recovery-kit/manifest.json').read_text())
        state=json.loads(self.command('distroctl security status --json',label='recovery-firmware')['output'])
        p2.require(state['firmware']['SecureBoot'] is True and state['firmware']['SetupMode'] is False,'recovery is not enforcing')
        facts=json.loads(self.command('''python3 - <<'PY'
from pathlib import Path
import json
p=Path('/sys/firmware/efi/efivars')
print(json.dumps({n:next(p.glob(n+'-*')).read_bytes()[4:].hex() for n in ['PK','KEK','db','LoaderInfo','StubInfo','StubImageIdentifier','LoaderImageIdentifier']}))
PY''',label='recovery-efi-identities')['output'])
        for name in ['PK','KEK','db']:
            p2.require(p3.signature_certificates(bytes.fromhex(facts[name]))==[(ROOT/'owner-firmware'/(name+'.cer')).read_bytes()],'wrong recovery '+name)
        decoded={n:bytes.fromhex(facts[n]).decode('utf-16-le').rstrip('\0') for n in ['LoaderInfo','StubInfo','StubImageIdentifier','LoaderImageIdentifier']}
        p2.require(decoded['LoaderInfo'].startswith('systemd-boot 262') and decoded['StubInfo'].startswith('systemd-stub 262'),'recovery firmware components differ')
        p2.require(decoded['StubImageIdentifier'].replace('\\','/')=='/EFI/Linux/recovery.efi','unsigned ISO path was selected')
        p2.require(decoded['LoaderImageIdentifier'].replace('\\','/').lower()=='/efi/boot/bootx64.efi','wrong recovery loader')
        self.command('test -d /run/archiso; grep -F astraeus.recovery_iso_sha256='+kit['iso_sha256']+' /proc/cmdline',label='recovery-root-input')
        actual=self.command('''test "$(lsblk -dn -o SERIAL /dev/vdb)" = P3_RECOVERY_TEST
mkdir -p /run/astraeus-recovery-esp
mount -o ro /dev/vdb /run/astraeus-recovery-esp
sha256sum /run/astraeus-recovery-esp/EFI/Linux/recovery.efi /run/astraeus-recovery-esp/EFI/BOOT/BOOTX64.EFI
sbverify --cert /mnt/astraeus-validation/owner/db.crt /run/astraeus-recovery-esp/EFI/Linux/recovery.efi
sbverify --cert /mnt/astraeus-validation/owner/db.crt /run/astraeus-recovery-esp/EFI/BOOT/BOOTX64.EFI
umount /run/astraeus-recovery-esp''',label='recovery-loaded-artifacts')['output']
        p2.require(kit['files']['recovery.efi'] in actual and kit['files']['loader-signed.efi'] in actual,'recovery bytes differ')
        for path,expected in self.manifest['installed_binaries'].items():
            p2.require(self.command('sha256sum '+path,label='recovery-native-'+Path(path).name)['output'].split()[0]==expected,'live recovery binary differs from final package')
        p2.save(self.session/'recovery-trust.json',dict(passed=True,firmware=state['firmware'],efi=decoded,kit=kit,boot_id=self.boot_id))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--scenario',choices=['update-success','update-failure','rejected-update','rollback','interruption'],required=True)
    parser.add_argument('--fault',choices=p2.FAULTS,default='package')
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    args.base,args.output=map(p2.safe_path,[args.base,args.output])
    p2.require(args.base.is_relative_to(ROOT) and args.output.is_relative_to(ROOT),'invalid test directory')
    manifest=p2.verify_baseline(args.base)
    p2.require(manifest['source_commit']=='cac8998ad7730e69ae354c3162ef4a0677cfc162','wrong source')
    args.encryption=manifest['encryption']
    args.iso=ROOT/'build/evidence/A/astraeus-dev-0.1.0-dev-x86_64.iso'
    args.output.mkdir(mode=0o700)
    p2.clone(args.base,args.output)
    share=args.output/'share'
    share.mkdir()
    shutil.copyfile(SRC/'scripts/validate/phase2-guest.py',share/'phase2-guest.py')
    shutil.copytree(ROOT/'fixtures',share/'fixtures')
    (share/'owner').mkdir()
    shutil.copyfile(ROOT/'owner-firmware/db.crt',share/'owner/db.crt')
    vm=TrustedVM(args.output,Path('/usr/share/OVMF/OVMF_CODE_4M.secboot.fd'),share,args.timeout,secure_boot=True,manifest=manifest)
    result=dict(passed=False,integrated_acceptance=False,started=p2.now(),scenario=args.scenario,fault=args.fault,encryption=args.encryption,source_commit=manifest['source_commit'])
    p2.save(args.output/'harness.json',{str(p):p2.digest(p) for p in [Path(__file__),ROOT/'integrated-run.py',SRC/'scripts/validate/phase2.py',SRC/'scripts/validate/phase2-guest.py',SRC/'tests/fixtures/phase2/adapter.sh']})
    try:
        p2.scenario(vm,args)
        result.update(passed=True,integrated_acceptance=True)
    except BaseException as error:
        result['error']=f'{type(error).__name__}: {error}'
        if vm.boot_id and vm.child.poll() is None:
            try: observe(vm,'failure')
            except Exception as extra: result['diagnostics_error']=str(extra)
        raise
    finally:
        try:
            vm.stop()
            p2.verify_baseline(args.base)
        except BaseException as error:
            result.update(passed=False,integrated_acceptance=False,cleanup_error=str(error))
            raise
        finally:
            result['finished']=p2.now()
            p2.save(args.output/'result.json',result)
if __name__=='__main__': main()
