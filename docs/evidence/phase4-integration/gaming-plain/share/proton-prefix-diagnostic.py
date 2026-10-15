from pathlib import Path
import hashlib,json,uuid
import phase4_guest as guest
guest.p2guest.guard();prefix,desktop=guest.session('tester');assert prefix
work=Path('/var/tmp/phase4-proton-r2-45vcq118');exe=work/'windows-smoke.exe'
assert hashlib.sha256(exe.read_bytes()).hexdigest()=='5cee03d79ce1a46be0fb9e731d2ab5ce10cba1a46de86430e6afa6553c6e1347'
nonce=uuid.uuid4().hex
command=prefix+['env',f'STEAM_COMPAT_DATA_PATH={work}/compatdata',f'STEAM_COMPAT_INSTALL_PATH={work}',
 'STEAM_COMPAT_CLIENT_INSTALL_PATH=/home/tester/phase4-session/steam-home/.local/share/Steam',
 'SteamAppId=0','SteamGameId=0','PROTON_LOG=0',
 '/home/tester/phase4-runtimes/SteamLinuxRuntime_4/_v2-entry-point','--verb=waitforexitandrun','--',
 '/home/tester/.local/share/Steam/compatibilitytools.d/GE-Proton11-7-x86_64/proton','runinprefix',str(exe),nonce]
reply=guest.execute(command,timeout=120)
print(json.dumps(dict(scope='Diagnostic through genuine Proton runinprefix in the initialized test prefix, not Steam game acceptance',nonce=nonce,reply=reply,marker_observed='PHASE4_WINDOWS_OK '+nonce in reply['output'].splitlines())))
