from pathlib import Path
import json,sys,os,uuid,shutil
sys.path.insert(0,'scripts/validate')
import phase4_guest as guest
import phase4_proton as proton
prior=json.load(open('out/remediation/local-proton-normal-control.json'));work=Path(prior['work']);root=work.parent
case=work/'original-direct';case.mkdir();nonce=uuid.uuid4().hex
exe=work/'windows-smoke.exe'
env={**os.environ,'STEAM_COMPAT_DATA_PATH':str(work/'compat'),'STEAM_COMPAT_CLIENT_INSTALL_PATH':str(work/'steam'),'STEAM_COMPAT_INSTALL_PATH':str(work),'SteamAppId':'0','SteamGameId':'0','PROTON_LOG':'1','PROTON_LOG_DIR':str(case),'WINEDEBUG':'+timestamp,+pid,+tid,+process,+steam,+win'}
reply=guest.execute([str(root/'SteamLinuxRuntime_4/_v2-entry-point'),'--verb=waitforexitandrun','--',str(root/'GE-Proton11-7-x86_64/proton'),'run',str(exe),nonce],timeout=180,env=env)
log=(case/'steam-0.log').read_text();child=proton.completion(log,0)
result=dict(nonce=nonce,reply=reply,child=child,window=proton.window_lifecycle(log,child['pid']),marker_in_captured_output=('PHASE4_WINDOWS_OK '+nonce) in (log+reply['output']).splitlines(),proton_log=log)
Path('out/remediation/local-proton-direct.json').write_text(json.dumps(result,indent=2));print({k:v for k,v in result.items() if k not in ['proton_log','reply']})
for name,value in prior['checks'].items():
 log=Path(value['log_path']).read_text();value['proton_log']=log;value['window']=proton.window_lifecycle(log,value['child']['pid'])
Path('out/remediation/local-proton-normal-control.json').write_text(json.dumps(prior,indent=2))
