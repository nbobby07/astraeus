"""Attempt a real signed package mutation outside the native transaction coordinator."""
import importlib.util
import json
from pathlib import Path
import shutil
ROOT=Path('/home/ubuntu/p4i/r2')
spec=importlib.util.spec_from_file_location('regression',ROOT/'integrated-regression.py')
reg=importlib.util.module_from_spec(spec);spec.loader.exec_module(reg)
p2=reg.p2
base=ROOT/'base-plain';out=ROOT/'security-direct-package'
manifest=p2.verify_baseline(base)
out.mkdir(mode=0o700);p2.clone(base,out)
share=out/'share';share.mkdir()
shutil.copytree(ROOT/'fixtures',share/'fixtures')
vm=reg.TrustedVM(out,Path('/usr/share/OVMF/OVMF_CODE_4M.secboot.fd'),share,240,secure_boot=True,manifest=manifest)
result=dict(passed=False,integrated_acceptance=False,started=p2.now(),source_commit=manifest['source_commit'])
p2.save(out/'harness.json',{str(p):p2.digest(p) for p in [Path(__file__),ROOT/'integrated-regression.py',ROOT/'integrated-run.py']})
try:
    vm.start();vm.ready()
    before=p2.observe(vm,'before');p2.healthy(before,'none')
    reply=vm.command('pacman -U --noconfirm /mnt/astraeus-validation/fixtures/fixture-repo-2/astraeus-validation-fixture-2-1-any.pkg.tar.zst',check=False,label='unguarded-signed-package')
    p2.require(reply['code']==1 and 'astraeus-secure-boot:' in reply['output'],'not a native coordinator refusal')
    after=p2.observe(vm,'after');p2.healthy(after,'none')
    for name in ['packages','history','snapshots','root','uki-sha256']:
        p2.require(p2.value(before,name)==p2.value(after,name),'refused operation changed '+name)
    vm.shutdown();result.update(passed=True,integrated_acceptance=True)
except BaseException as error:
    result['error']=f'{type(error).__name__}: {error}';raise
finally:
    try:
        vm.stop();p2.verify_baseline(base)
    except BaseException as error:
        result.update(passed=False,integrated_acceptance=False,cleanup_error=str(error));raise
    finally:
        result['finished']=p2.now();p2.save(out/'result.json',result)
