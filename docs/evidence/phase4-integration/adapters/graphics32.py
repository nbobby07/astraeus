"""Close the ELF32 presentation evidence gap on a separate disposable overlay."""
from pathlib import Path
import importlib.util,json,shutil,subprocess,time
r=Path('/home/ubuntu/p4i/r2')
deadline=time.monotonic()+7200
while True:
    p=r/'recovery-r2-queue-results.json'
    results=json.loads(p.read_text()) if p.exists() else []
    assert all(x['exit_code']==0 and x['result']['passed'] for x in results),'recovery failed'
    if len(results)==6:break
    assert time.monotonic()<deadline,'recovery did not finish'
    time.sleep(3)
assert shutil.disk_usage(r).free>3*1024**3
assert subprocess.run(['pgrep','-x','qemu-system-x86'],capture_output=True).returncode==1
spec=importlib.util.spec_from_file_location('reg',r/'integrated-regression-r2.py')
reg=importlib.util.module_from_spec(spec);spec.loader.exec_module(reg)
p2=reg.p2;base=r/'base-plain';out=r/'graphics32'
manifest=p2.verify_baseline(base);out.mkdir(mode=0o700);p2.clone(base,out)
share=out/'share';share.mkdir(mode=0o755)
for name in ['phase2-guest.py','phase4_guest.py']:
    shutil.copyfile(r/'harness-validation/scripts/validate'/name,share/name)
shutil.copyfile(r/'graphics32-guest.py',share/'graphics32-guest.py')
vm=reg.TrustedVM(out,Path('/usr/share/OVMF/OVMF_CODE_4M.secboot.fd'),share,240,secure_boot=True,manifest=manifest)
result={'completed':False,'source_commit':manifest['source_commit'],'started':p2.now(),'physical_qualified':False}
p2.save(out/'harness.json',{str(p):p2.digest(p) for p in [Path(__file__),r/'graphics32-guest.py',r/'integrated-regression-r2.py',r/'harness-validation/scripts/validate/phase2.py',r/'harness-validation/scripts/validate/phase4_guest.py']})
try:
    vm.start();vm.ready()
    vm.command("test -e /dev/virtio-ports/org.astraeus.validation; mkdir -p /etc/sddm.conf.d; printf '[Autologin]\\nUser=tester\\nSession=plasma.desktop\\n' > /etc/sddm.conf.d/99-phase4-validation.conf; systemctl restart sddm; for attempt in $(seq 1 60); do if pgrep -u tester -x plasmashell >/dev/null; then exit 0; fi; sleep 1; done; exit 1",timeout=75,label='disposable-autologin')
    before=p2.observe(vm,'before');p2.healthy(before,'none')
    inspected=json.loads(vm.command('python3 /mnt/astraeus-validation/graphics32-guest.py inspect',timeout=60,label='inspect-elf32')['output'])
    p2.save(out/'inspection.json',inspected)
    if inspected['gears']:
        print('ELF32 window workload is running; capture two frames, then close its window normally.',flush=True)
        reply=vm.command('python3 /mnt/astraeus-validation/graphics32-guest.py run',timeout=210,label='elf32-window')
        p2.save(out/'workload.json',json.loads(reply['output']))
    else:result['presentation']='NOT RUN: installed package has no ELF32 window workload'
    after=p2.observe(vm,'after');p2.healthy(after,'none')
    for name in ['packages','history','snapshots']:
        assert p2.value(before,name)==p2.value(after,name),name
    vm.shutdown();result['completed']=True
except BaseException as error:
    result['error']=f'{type(error).__name__}: {error}';raise
finally:
    vm.stop();p2.verify_baseline(base)
    result['finished']=p2.now();p2.save(out/'result.json',result)
