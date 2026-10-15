"""TEST ONLY: one new overlay, preserving the prior guest and original baseline."""
from pathlib import Path
import json,shlex,shutil,sys
ROOT=Path('/home/ubuntu/p41')
sys.path.insert(0,str(ROOT/'harness/scripts/validate'))
import phase2 as p2
out=ROOT/'fixture-refresh';share=out/'share';base=ROOT/'base'
assert not (out/'disk.qcow2').exists(), 'refuse to overwrite prior evidence'
out.mkdir(exist_ok=True,mode=0o700);share.mkdir(exist_ok=True,mode=0o755)
manifest=p2.clone(base,out)
assert manifest['source_commit']=='cac8998ad7730e69ae354c3162ef4a0677cfc162'
code=Path('/usr/share/OVMF/OVMF_CODE_4M.secboot.fd')
assert p2.digest(code)==manifest['inputs']['ovmf_code']['sha256']
for name in ['phase2-guest.py','phase4_guest.py']:
    shutil.copyfile(ROOT/'harness/scripts/validate'/name,share/name)
vm=p2.VM(out,code,share,180,secure_boot=True)
receipt=dict(started=p2.now(),completed=False,production_source=manifest['source_commit'],validation_source='3163c86f75c8cd226456dd6b30b1c5b683f830cc')
def command(name,cmd,timeout=90,check=True):
    reply=vm.command(cmd,timeout=timeout,check=check,label=name)
    p2.save(out/(name+'.json'),reply)
    print(name+': '+str(reply['code']),flush=True)
    return reply
try:
    vm.start();vm.ready()
    trust=json.loads(command('trust-before','distroctl security status --json')['output'])
    assert trust['firmware']['SecureBoot'] is True and trust['firmware']['SetupMode'] is False
    assert trust['identity']=='valid' and trust['certificate_sha256']==manifest['signer_sha256']
    hashes=command('binaries-before','sha256sum '+shlex.join(list(manifest['installed_binaries'])))
    assert {line.split()[1]:line.split()[0] for line in hashes['output'].splitlines()}==manifest['installed_binaries']
    command('autologin','test ! -e /etc/sddm.conf.d/99-phase41-validation.conf; mkdir -p /etc/sddm.conf.d; '
        'printf "[Autologin]\\nUser=tester\\nSession=plasma.desktop\\n" > /etc/sddm.conf.d/99-phase41-validation.conf; '
        'systemctl restart sddm; for attempt in $(seq 1 75); do if pgrep -u tester -x plasmashell >/dev/null; then exit 0; fi; sleep 1; done; exit 1')
    before=p2.observe(vm,'before');p2.healthy(before,'none')
    state_before=command('state-before','python3 /mnt/astraeus-validation/guest-state.py')
    reply=command('signed-fixture-test','unshare --mount --propagation private python3 /mnt/astraeus-validation/guest-refresh.py',timeout=600,check=False)
    state_after=command('state-after','python3 /mnt/astraeus-validation/guest-state.py')
    assert json.loads(state_before['output'])==json.loads(state_after['output']), 'parent trust/package state changed'
    receipt['parent_state_unchanged']=True
    command('restore-autologin','rm /etc/sddm.conf.d/99-phase41-validation.conf')
    after=p2.observe(vm,'after');p2.healthy(after,'none')
    for name in ['packages','history','snapshots']:
        assert p2.value(before,name)==p2.value(after,name),name+' changed'
    assert command('binaries-after','sha256sum '+shlex.join(list(manifest['installed_binaries'])))['output']==hashes['output']
    final=json.loads(command('trust-after','distroctl security status --json')['output'])
    assert final['firmware']==trust['firmware'] and final['certificate_sha256']==trust['certificate_sha256']
    assert final['identity']=='valid'
    vm.shutdown();receipt['completed']=True
    parsed=json.loads(reply['output']);p2.save(out/'fixture-result.json',parsed)
    receipt['test_status']=parsed['status'];receipt['test_exit']=reply['code']
    if parsed['status']=='PASS':
        import base64
        fixture=out/'signed-database';fixture.mkdir()
        for name,key in [('distro.db','database_base64'),('distro.db.sig','signature_base64')]:
            (fixture/name).write_bytes(base64.b64decode(parsed['fixture'][key]))
        (fixture/'repository-key.asc').write_text(parsed['fixture']['public_key_ascii'])
        p2.save(fixture/'provenance.json',{k:v for k,v in parsed['fixture'].items() if not k.endswith('_base64') and k!='public_key_ascii'})
except BaseException as error:
    receipt['error']=type(error).__name__+': '+str(error)
    raise
finally:
    vm.stop();p2.verify_baseline(base)
    receipt.update(finished=p2.now(),qemu_returncode=vm.child.returncode if vm.child else None,baseline_unchanged=True)
    p2.save(out/'result.json',receipt)
