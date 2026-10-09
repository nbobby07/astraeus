#!/usr/bin/env python3
"""Integrated acceptance adapter using the unchanged Phase 2/3 VM and fault harness."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import sys
import time
import uuid

ROOT=Path('/home/ubuntu/p4i/r2')
SRC=ROOT/'harness'
sys.path.insert(0,str(SRC/'scripts/validate'))
import phase2 as p2
import phase3 as p3

def command(vm, text, label, check=True, timeout=180):
    return vm.command(text,label=label,check=check,timeout=timeout)

def data(vm, text, label):
    return json.loads(command(vm,text,label)['output'])

def inventory(vm,label):
    observed=p2.observe(vm,label)
    extra={name:command(vm,text,label+'-'+name,check=False) for name,text in {
        'security':'distroctl security status --json', 'generations':'distroctl boot status --json',
        'running-uki':'bootctl --print-stub-path',
        'kernel':'uname -r', 'root-identity':'btrfs subvolume show /',
        'confirm-service':'systemctl show astraeus-confirm-boot.service -p Result -p ExecMainStatus',
        'bless-service':'systemctl show systemd-bless-boot.service -p Result -p ExecMainStatus',
        'esp':'find /efi/EFI /efi/loader -type f -exec sha256sum {} +',
        'generation-files':'find /.snapshots/astraeus/generations -maxdepth 2 -type f -print',
    }.items()}
    p2.save(vm.out/(label+'-phase3.json'),extra)
    return observed,extra

def trusted_boot(vm,manifest,label):
    state=data(vm,'distroctl security status --json',label+'-trust')
    p2.require(state['firmware']['SecureBoot'] is True and state['firmware']['SetupMode'] is False,
               'firmware is not enforcing')
    p2.require(state['certificate_sha256']==manifest['signer_sha256'] and state['identity']=='valid',
               'unexpected owner signing policy')
    for name in ['bootloader','fallback_bootloader']:
        p2.require(state['artifacts'][name]['signature']=='valid-for-configured-certificate','loader signature unavailable')
    code='''python3 - <<'PY'
import json
from pathlib import Path
p=Path('/sys/firmware/efi/efivars')
print(json.dumps({n:next(p.glob(n+'-*')).read_bytes()[4:].hex() for n in ['PK','KEK','db']}))
PY'''
    enrolled=data(vm,code,label+'-enrolled-keys')
    public=ROOT/'owner-firmware'
    for name in ['PK','KEK','db']:
        p2.require(p3.signature_certificates(bytes.fromhex(enrolled[name]))==[(public/(name+'.cer')).read_bytes()],
                   'firmware identity differs: '+name)
    for name,expected in manifest['installed_binaries'].items():
        result=command(vm,'sha256sum '+shlex.quote(name),label+'-binary-'+Path(name).name)
        p2.require(result['output'].split()[0]==expected,'installed binary differs from final package')
    return state

def boot(vm,manifest,label,allow_unconfirmed=False):
    vm.start()
    print('Boot requires normal LUKS unlock if encrypted: '+str(vm.monitor),flush=True)
    vm.ready()
    waited=command(vm,'systemctl start astraeus-confirm-boot.service',label+'-confirmation-job',check=False)
    if not allow_unconfirmed:
        p2.require(waited['code']==0,'boot confirmation service failed')
    return trusted_boot(vm,manifest,label)

def stage_update(vm,manifest):
    boot(vm,manifest,'initial')
    before=data(vm,'distroctl history --json','history-before')
    p2.require(not before,'baseline must have no completed test transaction')
    marker=uuid.uuid4().hex
    command(vm,f'mkdir -p /home/astraeus-validation; printf %s {marker} > {p2.PERSISTENT}','persistent-before')
    plan=data(vm,'distroctl update --dry-run --json','signed-plan')
    p2.require(any(p.get('name')=='astraeus-validation-fixture' and p.get('to')=='2-1'
                   for p in plan['packages']['changes']),'missing intended fixture upgrade')
    reply=command(vm,'distroctl update','signed-update',check=False,timeout=300)
    inventory(vm,'after-update')
    records=data(vm,'distroctl history --json','history-after')
    p2.require(len(records)==1 and records[0]['snapshot'],'update did not preserve its prior snapshot')
    record=records[0]
    marker+='-after-snapshot'
    command(vm,f'printf %s {marker} > {p2.PERSISTENT}; sync','persistent-after')
    return reply,record,marker

def pair(vm,record):
    result=data(vm,'distroctl boot list --json','staged-pair')
    selection=result['selection']
    p2.require(selection and selection['current']==record['post_snapshot']
               and selection['previous']==record['snapshot'] and not result['pending'],'wrong staged pair')
    for ident in [selection['previous'],selection['current']]:
        verified=data(vm,f'distroctl boot verify {ident} --json','verify-'+ident)
        p2.require(len(verified['generations'])==1 and verified['generations'][0]['artifact_verified_now'],
                   'generation verification unavailable')
    return result

def confirmed(vm,manifest,record,marker):
    vm.shutdown()
    boot(vm,manifest,'candidate')
    saved=data(vm,f'distroctl confirm-boot {record["id"]}','confirm-candidate')
    p2.require(saved['state']=='succeeded' and saved['confirmation']['error'] is None,'candidate was not confirmed')
    observed=data(vm,'distroctl boot list --json','known-good-pair')
    target=next(g for g in observed['generations'] if g['generation']['id']==record['post_snapshot'])
    p2.require(target['health']=='known-good' and target['boot_counter'][1]['state']=='uncounted',
               'health evidence did not produce upstream blessing')
    path=command(vm,'bootctl --print-stub-path','booted-candidate')['output'].strip()
    p2.require(path==f'/efi/EFI/Astraeus/{record["post_snapshot"]}.efi','wrong running immutable UKI')
    p2.require(command(vm,'cat '+p2.PERSISTENT,'persistent-final')['output'].strip()==marker,'persistent data changed')
    inventory(vm,'confirmed')

def fallback(vm,manifest,record,marker):
    ident=record['post_snapshot']
    path=f'/efi/EFI/Astraeus/{ident}.efi'
    injection=data(vm,f'python3 /mnt/astraeus-validation/integrated-guest.py fault --kind tampered --uki {path}',
                   'tamper-candidate')
    p2.require(injection['injected'] and injection['before_sha256']!=injection['after_sha256'],'fault was not injected')
    vm.shutdown()
    failures=[]
    for attempt in range(4):
        vm.start()
        print('Failure/fallback boot: '+str(vm.monitor),flush=True)
        try:
            vm.ready()
        except (TimeoutError,p2.QemuExited) as error:
            if isinstance(error,p2.QemuExited): p2.require(error.returncode==0,'QEMU crashed instead of rejecting the candidate')
            text=(vm.session/'serial.log').read_text(errors='replace')
            failures.append({'attempt':attempt+1,'error':str(error),'serial_sha256':p2.digest(vm.session/'serial.log')})
            p2.save(vm.session/'unbooted-candidate.json',failures[-1])
            vm.stop()
            continue
        trusted_boot(vm,manifest,'fallback')
        refused=command(vm,'systemctl start astraeus-confirm-boot.service','record-fallback',check=False)
        p2.require(refused['code']==1,'retained recovery root must require explicit restoration')
        selected=command(vm,'bootctl --print-stub-path','selected-recovery')['output'].strip()
        p2.require(selected==f'/efi/EFI/Astraeus/{record["snapshot"]}.efi','failed candidate unexpectedly reached userspace')
        checked=data(vm,f'distroctl boot verify {record["snapshot"]} --json','verify-recovery')
        p2.require(checked['generations'][0]['artifact_verified_now'],'retained pair was not verified')
        state=data(vm,'distroctl boot list --json','fallback-counts')
        candidate=next(g for g in state['generations'] if g['generation']['id']==ident)
        p2.require(candidate['health']!='known-good','failed candidate was promoted')
        count=candidate['boot_counter'][1]
        p2.require(count['state']=='counted' and count['done']==3 and count['left']==0,'candidate did not exhaust its actual attempt budget')
        p2.require(command(vm,'cat /etc/astraeus-test-state','recovery-root-state')['output'].strip()=='version-A',
                   'fallback root is not the retained package generation')
        p2.require(command(vm,'cat '+p2.PERSISTENT,'recovery-persistent')['output'].strip()==marker,'user data lost')
        inventory(vm,'recovery-boot')
        saved=data(vm,'distroctl history --json','fallback-history')[0]
        p2.require(saved['state']!='succeeded' and saved['confirmation'] is None,'fallback falsely finalized the update')
        p2.require(any(a.get('boot_id')==vm.boot_id and a.get('snapshot')==record['snapshot'] and
                       a.get('error')=='Booted retained known-good recovery root; offline restoration and finalize-rollback still required'
                       for a in saved['boot_attempts']),'confirmation failed for an unrelated reason')
        services=command(vm,'systemctl is-active NetworkManager.service sddm.service','fallback-required-services')
        p2.require(services['output'].split()==['active','active'],'recovery services are not active')
        failed=command(vm,'systemctl --failed --no-legend --plain','fallback-failed-units')['output'].splitlines()
        p2.require(len(failed)==1 and failed[0].lstrip().startswith('astraeus-confirm-boot.service'),'unrelated failure in retained-root boot')
        p2.save(vm.out/'fallback-verdict.json',dict(passed=True,failures=failures,count=count,
                    selection='systemd-boot retained root',restoration='not performed'))
        return
    raise RuntimeError('no trusted recovery root booted within the attempt budget')

def corrupt_metadata(vm,record):
    ident=record['post_snapshot']
    path=f'/.snapshots/astraeus/generations/{ident}/metadata.json'
    original=command(vm,'cat '+path,'metadata-original')['output']
    original_hash=command(vm,'sha256sum /efi/loader/loader.conf','selection-before')['output'].split()[0]
    for fault in ['unknown-field','wrong-root','wrong-uki']:
        changed=json.loads(original)
        if fault=='unknown-field': changed['unexpected']=True
        elif fault=='wrong-root': changed['root']['uuid']='00000000-0000-4000-8000-000000000001'
        else: changed['uki_sha256']='0'*64
        payload=json.dumps(changed)
        command(vm,f'printf %s {shlex.quote(payload)} > {path}; sync','inject-'+fault)
        for operation in ['verify','set-default']:
            reply=command(vm,f'distroctl boot {operation} {ident}'+(' --json' if operation=='verify' else ''),
                          fault+'-'+operation,check=False)
            p2.require(reply['code']==1,'corrupt generation was accepted or the refusal crashed')
        after=command(vm,'sha256sum /efi/loader/loader.conf','selection-after-'+fault)['output'].split()[0]
        p2.require(after==original_hash,'refused mutation changed loader selection')
        command(vm,f'printf %s {shlex.quote(original)} > {path}; sync','restore-fixture-'+fault)
    for fault in ['stale-transaction-reference','corrupt-transaction']:
        command(vm,"""python3 - <<'PY'
import json,sqlite3
from pathlib import Path
p=Path('/var/log/astraeus/private/transactions.sqlite')
db=sqlite3.connect(p)
rows=db.execute('SELECT id,record FROM transactions').fetchall()
assert len(rows)==1
ident,text=rows[0]
Path('/var/lib/astraeus-validation/transaction-original.json').write_text(text)
record=json.loads(text)
record['post_snapshot']=None
replacement=json.dumps(record) if """+repr(fault)+"""=='stale-transaction-reference' else '{invalid-json'
db.execute('UPDATE transactions SET record=? WHERE id=?',(replacement,ident)); db.commit()
PY""",'inject-'+fault)
        for operation in ['verify','set-default']:
            reply=command(vm,f'distroctl boot {operation} {ident}'+(' --json' if operation=='verify' else ''),fault+'-'+operation,check=False)
            p2.require(reply['code']==1,'unreferenced/corrupt authoritative transaction was accepted')
        after=command(vm,'sha256sum /efi/loader/loader.conf','selection-after-'+fault)['output'].split()[0]
        p2.require(after==original_hash,'refused transaction mutation changed loader selection')
        command(vm,"""python3 - <<'PY'
import sqlite3
from pathlib import Path
db=sqlite3.connect('/var/log/astraeus/private/transactions.sqlite')
text=Path('/var/lib/astraeus-validation/transaction-original.json').read_text()
assert db.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]==1
db.execute('UPDATE transactions SET record=?',(text,)); db.commit()
PY""",'restore-fixture-'+fault)
    pair(vm,record)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',choices=['update','fallback','metadata'])
    parser.add_argument('--base',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=180)
    args=parser.parse_args()
    base,out=map(p2.safe_path,[args.base,args.output])
    p2.require(base.is_relative_to(ROOT) and out.is_relative_to(ROOT),'test path escaped integration workspace')
    manifest=p2.verify_baseline(base)
    p2.require(manifest['kind']=='phase3-integrated' and manifest['source_commit']==json.loads((ROOT/'source.json').read_text())['source_commit'],
               'baseline is not the final integrated image')
    out.mkdir(mode=0o700)
    p2.clone(base,out)
    share=out/'share'
    share.mkdir()
    for name in ['phase2-guest.py','phase3_guest.py']:
        shutil.copyfile(SRC/'scripts/validate'/name,share/name)
    shutil.copyfile(ROOT/'integrated-guest.py',share/'integrated-guest.py')
    vm=p2.VM(out,Path('/usr/share/OVMF/OVMF_CODE_4M.secboot.fd'),share,args.timeout,secure_boot=True)
    result={'passed':False,'case':args.case,'scope':'integrated-image','integrated_acceptance':False,
            'source_commit':manifest['source_commit'],'started':p2.now()}
    p2.save(out/'harness.json', {str(path):p2.digest(path) for path in [Path(__file__),ROOT/'integrated-guest.py',
        SRC/'scripts/validate/phase2.py',SRC/'scripts/validate/phase3.py',SRC/'scripts/validate/phase3_guest.py',
        SRC/'scripts/validate/phase2-guest.py',SRC/'scripts/validate/qmp.py',SRC/'scripts/install-smoke.py']})
    try:
        reply,record,marker=stage_update(vm,manifest)
        p2.require(reply['code']==0 and record['state']=='awaiting_boot','signed update did not stage an unconfirmed candidate')
        pair(vm,record)
        if args.case=='update': confirmed(vm,manifest,record,marker)
        elif args.case=='fallback': fallback(vm,manifest,record,marker)
        else: corrupt_metadata(vm,record)
        vm.shutdown()
        result.update(passed=True,integrated_acceptance=True)
    except BaseException as error:
        result['error']=f'{type(error).__name__}: {error}'
        if vm.boot_id and vm.child.poll() is None:
            try: inventory(vm,'failure')
            except Exception as extra: result['diagnostics_error']=str(extra)
        raise
    finally:
        try:
            vm.stop()
            p2.verify_baseline(base)
        except BaseException as error:
            result.update(passed=False,integrated_acceptance=False,cleanup_error=str(error))
            raise
        finally:
            result['finished']=p2.now()
            p2.save(out/'result.json',result)

if __name__=='__main__': main()
