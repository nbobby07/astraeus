from pathlib import Path
import sys,os,json,hashlib,shutil,pwd,tempfile
sys.path.insert(0,'scripts/validate')
import phase4_proton as proton
os.umask(0o077)
account=pwd.getpwnam('noel')
root=Path(account.pw_dir)/'astraeus-phase41-local'
work=Path(tempfile.mkdtemp(prefix='phase41-root-controller-',dir='/var/tmp'));os.chown(work,account.pw_uid,account.pw_gid)
exe=work/'windows-smoke.exe';shutil.copyfile('/mnt/d/Astraeus-Phase4-Integration-Evidence/public/gaming-plain/share/fixtures/windows-smoke.exe',exe);exe.chmod(0o644)
assert hashlib.sha256(exe.read_bytes()).hexdigest()=='5cee03d79ce1a46be0fb9e731d2ab5ce10cba1a46de86430e6afa6553c6e1347'
compat=work/'compat';compat.mkdir();os.chown(compat,account.pw_uid,account.pw_gid)
steam=work/'steam';steam.mkdir();os.chown(steam,account.pw_uid,account.pw_gid)
prefix=['runuser','-u','noel','--','env','DISPLAY=:0','WAYLAND_DISPLAY=wayland-0','XDG_RUNTIME_DIR=/run/user/1000','DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus']
checks={}
for negative in [False,True]:
 key='exit-control' if negative else 'normal'
 checks[key]=proton.run_case(prefix,root/'GE-Proton11-7-x86_64/proton',root/'SteamLinuxRuntime_4/_v2-entry-point',exe,compat,steam,work,negative)
 print(key,checks[key]['status'],checks[key]['code'],checks[key].get('window'),checks[key].get('evidence_error'),flush=True)
Path('out/remediation/local-proton-root-controller.json').write_text(json.dumps(dict(work=str(work),controller_uid=os.getuid(),desktop_uid=account.pw_uid,umask='0077',harness_commit='600319505033eac4540c2ac74e6a0a265e1a3f60',checks=checks),indent=2))
