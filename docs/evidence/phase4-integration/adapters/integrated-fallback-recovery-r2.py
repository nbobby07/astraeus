"""Native failed-candidate fallback followed by trusted offline restoration and finalization."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
ROOT=Path('/home/ubuntu/p4i/r2')
spec=importlib.util.spec_from_file_location('regression',ROOT/'integrated-regression-r2.py')
regression=importlib.util.module_from_spec(spec)
spec.loader.exec_module(regression)
p2,checks=regression.p2,regression.checks
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
args.base,args.output=map(p2.safe_path,[args.base,args.output])
p2.require(args.base.is_relative_to(ROOT) and args.output.is_relative_to(ROOT),'test path escaped workspace')
manifest=p2.verify_baseline(args.base)
p2.require(manifest['source_commit']=='cac8998ad7730e69ae354c3162ef4a0677cfc162','wrong runtime revision')
args.encryption=manifest['encryption']
args.timeout=600
args.iso=ROOT/'build/evidence/A/astraeus-dev-0.1.0-dev-x86_64.iso'
args.output.mkdir(mode=0o700)
p2.clone(args.base,args.output)
share=args.output/'share'
share.mkdir()
for name in ['phase2-guest.py','phase3_guest.py']:
    shutil.copyfile(regression.SRC/'scripts/validate'/name,share/name)
shutil.copyfile(ROOT/'integrated-guest.py',share/'integrated-guest.py')
shutil.copytree(ROOT/'fixtures',share/'fixtures')
(share/'owner').mkdir()
shutil.copyfile(ROOT/'owner-firmware/db.crt',share/'owner/db.crt')
vm=regression.TrustedVM(args.output,Path('/usr/share/OVMF/OVMF_CODE_4M.secboot.fd'),share,args.timeout,secure_boot=True,manifest=manifest)
result=dict(passed=False,integrated_acceptance=False,encryption=args.encryption,started=p2.now(),source_commit=manifest['source_commit'])
p2.save(args.output/'harness.json',{str(p):p2.digest(p) for p in [Path(__file__),ROOT/'integrated-regression-r2.py',ROOT/'integrated-run.py',ROOT/'integrated-guest.py']})
try:
    reply,record,marker=checks.stage_update(vm,manifest)
    p2.require(reply['code']==0 and record['state']=='awaiting_boot','candidate update did not stage')
    checks.pair(vm,record)
    checks.fallback(vm,manifest,record,marker)
    p2.recover(vm,args,record['snapshot'])
    vm.command('systemctl start astraeus-confirm-boot.service',check=False,label='observe-restored-confirmation')
    restored=p2.observe(vm,'before-explicit-finalization')
    p2.healthy(restored,args.encryption)
    saved=p2.value(restored,'history',True)[0]
    p2.require(saved['state']!='rolled_back','rollback finalized without explicit request')
    p2.require(p2.value(restored,'root')=='version-A' and p2.value(restored,'persistent')==marker,'restoration lost root or user state')
    expected=record['plan']['current']['packages']
    actual=dict(line.split(maxsplit=1) for line in p2.value(restored,'packages').splitlines())
    p2.require(actual==expected,'restored package map differs from generation A')
    final=json.loads(vm.command('distroctl finalize-rollback '+str(record['id']),label='explicit-finalization')['output'])
    p2.require(final['state']=='rolled_back' and final['confirmation']['rollback'] is True and final['confirmation']['error'] is None,'rollback was not verified and finalized')
    again=json.loads(vm.command('distroctl finalize-rollback '+str(record['id']),label='repeat-finalization')['output'])
    p2.require(again==final,'repeated finalization changed the confirmed result')
    p2.healthy(p2.observe(vm,'restored-known-good'),args.encryption)
    vm.shutdown()
    result.update(passed=True,integrated_acceptance=True,fallback='retained-root recovery',restoration='trusted live recovery then explicit finalize-rollback')
except BaseException as error:
    result['error']=f'{type(error).__name__}: {error}'
    if vm.boot_id and vm.child.poll() is None:
        try: checks.inventory(vm,'failure')
        except Exception as extra: result['diagnostics_error']=str(extra)
    raise
finally:
    try:
        vm.stop(); p2.verify_baseline(args.base)
    except BaseException as error:
        result.update(passed=False,integrated_acceptance=False,cleanup_error=str(error)); raise
    finally:
        result['finished']=p2.now(); p2.save(args.output/'result.json',result)
