"""Bounded power cut using the original Phase 3 correlated-barrier harness."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time
ROOT=Path('/home/ubuntu/p3i/final')
SRC=ROOT.parent/'candidate-r3'
sys.path.insert(0,str(SRC/'scripts/validate'))
import phase2 as p2
import phase3 as p3
spec=importlib.util.spec_from_file_location('checks',ROOT/'integrated-run.py')
checks=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
base=ROOT/'base-plain'
out=ROOT/'k-plain'
manifest=p2.verify_baseline(base)
out.mkdir(mode=0o700)
p2.clone(base,out)
share=out/'share'
share.mkdir()
shutil.copyfile(ROOT/'powercut-sync.py',share/'powercut-sync.py')
vm=p2.VM(out,Path('/usr/share/OVMF/OVMF_CODE_4M.secboot.fd'),share,240,secure_boot=True)
result=dict(passed=False,integrated_acceptance=False,checkpoint='generation-activation',started=p2.now(),source_commit=manifest['source_commit'])
p2.save(out/'harness.json',{str(p):p2.digest(p) for p in [Path(__file__),ROOT/'powercut-sync.py',ROOT/'integrated-run.py',SRC/'scripts/validate/phase3.py']})
try:
    checks.boot(vm,manifest,'before-cut')
    before,_=checks.inventory(vm,'before-cut')
    p2.healthy(before,'none')
    vm.command('''test ! -e /var/lib/astraeus-validation/sync-real
test ! -e /var/log/astraeus-validation-phase3-barrier.json
cp --preserve=mode /usr/bin/sync /var/lib/astraeus-validation/sync-real
install -m755 /mnt/astraeus-validation/powercut-sync.py /usr/bin/sync
python3 - <<'PY'
from pathlib import Path
import json
p=Path('/var/lib/astraeus-validation/powercut.json')
p.write_text(json.dumps(dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),checkpoint='generation-activation')))
PY
systemd-run --unit=astraeus-powercut-update --property=RuntimeMaxSec=900 /usr/bin/distroctl update''',label='arm-real-sync-boundary')
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        reply=vm.command('cat /var/log/astraeus-validation-phase3-barrier.json',timeout=5,check=False,label='wait-boundary')
        if reply['code']==0:
            receipt=json.loads(reply['output']); break
        p2.require(reply['code']==1,'unexpected barrier read failure')
        time.sleep(1)
    else: raise TimeoutError('native activation did not reach the bounded sync checkpoint')
    ident=receipt['generation']
    metadata=checks.data(vm,'cat /.snapshots/astraeus/generations/'+ident+'/metadata.json','independent-generation')
    actual=checks.data(vm,'astraeus-boot-artifact verify /efi/EFI/Astraeus/'+ident+'.efi','independent-artifact')
    p2.require(actual['sha256']==metadata['uki_sha256'] and actual['firmware_trusted'] is True,'candidate is not independently trusted')
    root=vm.command('btrfs subvolume show /',label='independent-root')['output']
    p2.require('UUID:\t\t\t'+metadata['root']['uuid'] in root or metadata['root']['uuid'] in root,'running root identity differs')
    previous=receipt['journal']['selection']['previous']
    prior=checks.data(vm,'cat /.snapshots/astraeus/generations/'+previous+'/metadata.json','prior-pair')
    history=checks.data(vm,'distroctl history --json','history-at-cut')[0]
    p2.require(history['state']=='awaiting_boot' and history['post_snapshot']==ident,'cut did not occur after durable candidate eligibility')
    p3.cut_at_barrier(vm,'generation-activation',ident,metadata['root']['uuid'],actual['sha256'])
    vm.start(); vm.ready()
    checks.trusted_boot(vm,manifest,'after-cut')
    vm.command('systemctl start astraeus-confirm-boot.service',check=False,label='confirmation-after-cut')
    after=checks.data(vm,'distroctl history --json','history-after-cut')[0]
    p2.require(after['state']!='succeeded' and after['confirmation'] is None,'interrupted activation produced false success')
    journal=checks.data(vm,'cat /.snapshots/astraeus/pending.json','preserved-journal')
    p2.require(journal==receipt['journal'],'interruption journal lost its exact intent')
    selected=vm.command('bootctl --print-stub-path',label='retained-path')['output'].strip()
    p2.require(selected=='/efi/EFI/Astraeus/'+previous+'.efi','prior trusted entry was not selected')
    verdict=checks.data(vm,'astraeus-boot-artifact verify '+selected,'retained-signature')
    p2.require(verdict['sha256']==prior['uki_sha256'] and verdict['firmware_trusted'] is True,'prior UKI trust lost')
    root=vm.command('btrfs subvolume show /; cat /etc/astraeus-test-state',label='retained-root')['output']
    p2.require(prior['root']['uuid'] in root and 'version-A' in root,'retained root differs')
    for command in ['distroctl update','distroctl boot set-default '+ident]:
        rejected=vm.command(command,check=False,label='unsafe-continuation')
        p2.require(rejected['code']==1,'unresolved activation allowed unsafe continuation')
    checks.inventory(vm,'recovery-required')
    vm.shutdown()
    result.update(passed=True,integrated_acceptance=True,recoverable_path='trusted retained root',journal_reconciled=False,
                  limitation='One cut after a completed sync before the loader configuration rename. No arbitrary power-loss guarantee.')
except BaseException as error:
    result['error']=f'{type(error).__name__}: {error}'
    if vm.boot_id and vm.child.poll() is None:
        try: checks.inventory(vm,'failure')
        except Exception as extra: result['diagnostics_error']=str(extra)
    raise
finally:
    try:
        vm.stop(); p2.verify_baseline(base)
    except BaseException as error:
        result.update(passed=False,integrated_acceptance=False,cleanup_error=str(error)); raise
    finally:
        result['finished']=p2.now(); p2.save(out/'result.json',result)
