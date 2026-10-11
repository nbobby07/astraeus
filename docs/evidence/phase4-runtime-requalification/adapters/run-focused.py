"""TEST ONLY: restore an unchanged trusted baseline and run focused guest checks."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, re, shlex, shutil, sys, time
from PIL import Image

ROOT=Path('/home/ubuntu/p41')
sys.path.insert(0,str(ROOT/'harness/scripts/validate'))
import phase2 as p2

base=ROOT/'base'; out=ROOT/'guest-r1'; code=Path('/usr/share/OVMF/OVMF_CODE_4M.secboot.fd')
manifest=p2.verify_baseline(base)
assert manifest['source_commit']=='cac8998ad7730e69ae354c3162ef4a0677cfc162'
assert p2.digest(code)==manifest['inputs']['ovmf_code']['sha256']
info=json.loads(p2.host(['qemu-img','info','--output=json',base/'disk.qcow2']))
assert not info.get('backing-filename'), 'restored baseline must be standalone'
assert int(Path('/proc/meminfo').read_text().split('MemAvailable:')[1].split()[0])>11*1024*1024
out.mkdir(mode=0o700)
p2.clone(base,out)
share=out/'share';share.mkdir(mode=0o755)
for name in ['phase2-guest.py','phase4_guest.py','phase4_proton.py','phase4_gamescope.py','phase4_negatives.py']:
    shutil.copyfile(ROOT/'harness/scripts/validate'/name,share/name)
for name in ['gaming-runtime-setup.py','gaming-session.py']:
    shutil.copyfile(ROOT/'harness/docs/evidence/phase4-integration/gaming-plain/share'/name,share/name)
shutil.copyfile(ROOT/'guest-focused.py',share/'guest-focused.py')
shutil.copyfile(ROOT/'harness/tests/boot/installed-smoke.sh',share/'installed-smoke.sh')
shutil.copytree(ROOT/'harness/tests/fixtures/phase4',share/'fixtures')
for path in (ROOT/'fixtures').iterdir():
    shutil.copyfile(path,share/'fixtures'/path.name)
    (share/'fixtures'/path.name).chmod(0o755 if path.name!='prebuilt.json' else 0o644)
(share/'runtime-inputs').mkdir()
for path in (ROOT/'inputs').iterdir():
    path.chmod(0o644);os.link(path,share/'runtime-inputs'/path.name)
original=p2.install.qemu_command
def command(*args,**kwargs):
    value=original(*args,**kwargs);assert value.count('-m')==1
    value[value.index('-m')+1]='8192';return value
p2.install.qemu_command=command
vm=p2.VM(out,code,share,180,secure_boot=True)
receipt=dict(started=p2.now(),validation_source='09b8e9e0beaa433b27a74c5b01ec84c695a3d899',
    production_source=manifest['source_commit'],completed=False,physical_gpu_qualified=False,gaming_validated=False)
p2.save(out/'inputs.json',dict(baseline=manifest,qcow2=info,firmware_sha256=p2.digest(code),
    controller_sha256=p2.digest(__file__),guest_memory_mib=8192,
    share_files={str(p.relative_to(share)):p2.digest(p) for p in share.rglob('*') if p.is_file()},
    runtime_inputs=json.loads((ROOT/'runtime-inputs.json').read_text())))
def stage(name,command,timeout=180):
    reply=vm.command(command,timeout=timeout,check=False,label=name)
    try: parsed=json.loads(reply['output']) if reply['code']==0 else None
    except ValueError: parsed=None
    p2.save(out/(name+'.json'),dict(reply=reply,parsed=parsed))
    print(name+': command exit '+str(reply['code']),flush=True)
    return reply

try:
    vm.start();vm.ready()
    security=vm.command('distroctl security status --json',label='enforcing-trust')
    trust=json.loads(security['output'])
    assert trust['firmware']['SecureBoot'] is True and trust['firmware']['SetupMode'] is False
    assert trust['identity']=='valid' and trust['certificate_sha256']==manifest['signer_sha256']
    assert all(trust['artifacts'][key]['signature']=='valid-for-configured-certificate' for key in ['bootloader','fallback_bootloader'])
    hashes=vm.command('sha256sum '+shlex.join(list(manifest['installed_binaries'])),label='installed-binaries')
    actual={line.split()[1]:line.split()[0] for line in hashes['output'].splitlines()}
    assert actual==manifest['installed_binaries']
    vm.command('test ! -e /run/archiso; cat /etc/os-release; uname -a; cat /proc/cmdline',label='installed-identity')
    vm.command('test ! -e /etc/sddm.conf.d/99-phase41-validation.conf; mkdir -p /etc/sddm.conf.d; '
        'printf "[Autologin]\\nUser=tester\\nSession=plasma.desktop\\n" > /etc/sddm.conf.d/99-phase41-validation.conf; '
        'systemctl restart sddm; for attempt in $(seq 1 75); do if pgrep -u tester -x plasmashell >/dev/null; then exit 0; fi; sleep 1; done; exit 1',
        timeout=90,label='disposable-autologin')
    before=p2.observe(vm,'before');p2.healthy(before,'none')
    stage('steam-start','python3 /mnt/astraeus-validation/gaming-session.py steam-start')
    vm.command('runuser -u tester -- python3 /mnt/astraeus-validation/gaming-runtime-setup.py',timeout=600,label='restore-inspected-runtimes')
    stage('proton','python3 /mnt/astraeus-validation/guest-focused.py proton',timeout=420)
    stage('core','python3 /mnt/astraeus-validation/guest-focused.py core',timeout=360)
    stage('gamemode','python3 /mnt/astraeus-validation/guest-focused.py gamemode',timeout=150)
    stage('negatives','python3 /mnt/astraeus-validation/phase4_negatives.py',timeout=600)
    p2.save(out/'inspection-ready.json',dict(time=p2.now(),qmp=str(vm.monitor),boot_id=vm.boot_id))
    print('FOCUSED_INSPECTION_READY',flush=True)
    deadline=min(time.time()+1800,datetime.fromisoformat('2026-10-11T05:24:05+00:00').timestamp())
    (out/'manual').mkdir()
    while not (ROOT/'finish.json').exists():
        vm.alive()
        if time.time()>deadline: raise TimeoutError('inspection/budget deadline reached')
        for request in sorted(ROOT.glob('request-*.json')):
            target=out/'manual'/request.name
            if target.exists():continue
            assert request.stat().st_size<65536
            item=json.loads(request.read_text());label=item['label'];assert re.fullmatch('[a-z0-9-]+',label)
            result=dict(started=p2.now(),request=item)
            try:
                if item['action']=='command':
                    assert 1<=item.get('timeout',60)<=420
                    result['reply']=vm.command(item['command'],timeout=item.get('timeout',60),check=False,label=label)
                elif item['action']=='screen':
                    ppm=out/'manual'/(label+'.ppm');png=out/'manual'/(label+'.png')
                    result['qmp']=p2.qmp.execute(str(vm.monitor),{'execute':'screendump','arguments':{'filename':str(ppm)}})
                    Image.open(ppm).save(png);result['path']=str(png);result['sha256']=p2.digest(png)
                elif item['action']=='close-window':
                    result['qmp']=p2.qmp.execute(str(vm.monitor),{'execute':'send-key','arguments':{'keys':[{'type':'qcode','data':'alt'},{'type':'qcode','data':'f4'}],'hold-time':50}})
                else:raise ValueError('unknown inspection action')
            except Exception as error:result['error']=str(error)
            result['finished']=p2.now();p2.save(target,result)
        time.sleep(0.5)
    final_request=json.loads((ROOT/'finish.json').read_text());assert final_request['evidence_reviewed'] is True
    vm.command('rm /etc/sddm.conf.d/99-phase41-validation.conf',label='restore-autologin')
    after=p2.observe(vm,'after');p2.healthy(after,'none')
    for name in ['packages','history','snapshots']:
        assert p2.value(before,name)==p2.value(after,name),name+' changed'
    final_hashes=vm.command('sha256sum '+shlex.join(list(manifest['installed_binaries'])),label='final-installed-binaries')
    assert final_hashes['output']==hashes['output']
    vm.shutdown();receipt['completed']=True
except BaseException as error:
    receipt['error']=type(error).__name__+': '+str(error)
    raise
finally:
    vm.stop();receipt['finished']=p2.now();receipt['qemu_returncode']=vm.child.returncode if vm.child else None
    p2.verify_baseline(base);receipt['baseline_unchanged']=True
    p2.save(out/'result.json',receipt)
    p2.save(out/'disk-hashes.json',{name:p2.digest(out/name) for name in ['disk.qcow2','vars.fd']})
