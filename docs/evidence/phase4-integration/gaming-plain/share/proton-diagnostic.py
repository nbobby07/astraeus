"""Inspect container visibility and run the same hash-bound Win32 test."""
from pathlib import Path
import hashlib,json,os,pwd,shutil,tempfile,uuid
import phase4_guest as guest
guest.p2guest.guard();prefix,desktop=guest.session('tester');assert prefix
user=pwd.getpwnam('tester')
work=Path(tempfile.mkdtemp(prefix='phase4-proton-r2-',dir='/var/tmp'));os.chown(work,user.pw_uid,user.pw_gid)
exe=work/'windows-smoke.exe';shutil.copyfile(guest.FIXTURES/'windows-smoke.exe',exe);exe.chmod(0o755)
assert hashlib.sha256(exe.read_bytes()).hexdigest()=='5cee03d79ce1a46be0fb9e731d2ab5ce10cba1a46de86430e6afa6553c6e1347'
runtime=Path('/home/tester/phase4-runtimes/SteamLinuxRuntime_4/_v2-entry-point')
proton=Path('/home/tester/.local/share/Steam/compatibilitytools.d/GE-Proton11-7-x86_64/proton')
compat=work/'compatdata';compat.mkdir();os.chown(compat,user.pw_uid,user.pw_gid)
env=['env',f'STEAM_COMPAT_DATA_PATH={compat}','STEAM_COMPAT_CLIENT_INSTALL_PATH=/home/tester/phase4-session/steam-home/.local/share/Steam','SteamAppId=0','SteamGameId=0','PROTON_LOG=1',f'PROTON_LOG_DIR={work}']
check=[str(runtime),'--verb=waitforexitandrun','--','/usr/bin/test','-r',str(exe)]
before=guest.execute(prefix+env+check,timeout=60)
after=guest.execute(prefix+env+[f'STEAM_COMPAT_INSTALL_PATH={work}']+check,timeout=60)
nonce=uuid.uuid4().hex
reply=guest.execute(prefix+env+[f'STEAM_COMPAT_INSTALL_PATH={work}',str(runtime),'--verb=waitforexitandrun','--',str(proton),'run',str(exe),nonce],timeout=180)
log=work/'steam-0.log';log_text=log.read_text(errors='replace') if log.exists() else ''
marker='PHASE4_WINDOWS_OK '+nonce
observed=marker in reply['output'].splitlines() or marker in log_text.splitlines()
print(json.dumps(dict(work=str(work),desktop=desktop,visibility_before=before,visibility_after=after,reply=reply,nonce=nonce,marker_observed=observed,status='PASS' if reply['code']==0 and reply['error'] is None and observed else 'FAIL',log_tail=log_text[-512*1024:],log_bytes=log.stat().st_size if log.exists() else 0)))
