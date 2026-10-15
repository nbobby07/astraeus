from pathlib import Path
import sys,os,json,hashlib,shutil,uuid
sys.path.insert(0,'scripts/validate')
import phase4_proton as proton
root=Path.home()/'astraeus-phase41-local'
work=root/('test-'+uuid.uuid4().hex);work.mkdir()
exe=work/'windows-smoke.exe';shutil.copyfile('/mnt/d/Astraeus-Phase4-Integration-Evidence/public/gaming-plain/share/fixtures/windows-smoke.exe',exe)
assert hashlib.sha256(exe.read_bytes()).hexdigest()=='5cee03d79ce1a46be0fb9e731d2ab5ce10cba1a46de86430e6afa6553c6e1347'
compat=work/'compat';compat.mkdir();steam=work/'steam';steam.mkdir()
results={}
for negative in [False,True]:
 key='exit-control' if negative else 'normal'
 results[key]=proton.run_case([],root/'GE-Proton11-7-x86_64/proton',root/'SteamLinuxRuntime_4/_v2-entry-point',exe,compat,steam,work,negative)
 print(key,results[key]['status'],results[key]['code'],results[key].get('child'),results[key].get('evidence_error'),flush=True)
Path('out/remediation/local-proton-normal-control.json').write_text(json.dumps(dict(work=str(work),checks=results),indent=2))
