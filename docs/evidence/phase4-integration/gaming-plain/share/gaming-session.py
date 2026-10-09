"""Extra observable workloads in the disposable desktop, with no credentials."""
from pathlib import Path
import json,os,pwd,signal,subprocess,sys,time
import phase4_guest as guest
guest.p2guest.guard()
work=Path('/home/tester/phase4-session');work.mkdir(exist_ok=True)
account=pwd.getpwnam('tester');os.chown(work,account.pw_uid,account.pw_gid)
mode=sys.argv[1]
if mode=='watch':
 name=sys.argv[2];assert name in ['steam','overlay','overlay-gl']
 command=json.loads((work/(name+'-command.json')).read_text())
 signal.signal(signal.SIGTERM,lambda *_:None)
 result=subprocess.run(command)
 (work/(name+'-exit.json')).write_text(json.dumps(dict(code=result.returncode,finished=time.time()))+'\n')
 sys.exit(0)
prefix,desktop=guest.session('tester');assert prefix
if mode=='diagnostics':
 commands={
  'graphics':['distroctl','graphics','--probe','--json'],
  'gaming_status':['distroctl','gaming','status','--probe','--json'],
  'gaming_doctor':['distroctl','gaming','doctor','--probe','--json'],
  'session':['loginctl','list-sessions'],
  'dependencies':['bash','-c','ldd /usr/bin/steam; ldd /usr/lib/distroctl/graphics-probe64; ldd /usr/lib/distroctl/graphics-probe32'],
  'mangohud32':['env','VK_LOADER_DEBUG=layer','mangohud','/mnt/astraeus-validation/fixtures/vulkan32'],
 }
 results={name:guest.execute(prefix+command,timeout=45) for name,command in commands.items()}
 for name in ['graphics','gaming_status','gaming_doctor']:
  assert results[name]['code']==0 and results[name]['error'] is None
  results[name]['parsed']=json.loads(results[name]['output'])
 print(json.dumps(dict(desktop=desktop,commands=results)))
elif mode in ['steam-start','overlay-start','overlay-gl-start']:
 name=mode.removesuffix('-start');record=work/(name+'-process.json');assert not record.exists()
 if name=='steam':
  home=work/'steam-home';home.mkdir();os.chown(home,account.pw_uid,account.pw_gid)
  command=prefix+['env',f'HOME={home}','steam','-nochatui','-nofriendsui']
 elif name=='overlay':command=prefix+['env','MANGOHUD_CONFIG=fps,frametime','mangohud','vkcube','--c','100000']
 else:command=prefix+['env','MANGOHUD_CONFIG=fps,frametime','mangohud','--dlsym','glxgears']
 command=['timeout','--signal=TERM','--kill-after=10s','900s']+command
 (work/(name+'-command.json')).write_text(json.dumps(command)+'\n')
 with (work/(name+'.log')).open('xb') as stream:child=subprocess.Popen([sys.executable,__file__,'watch',name],stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
 result=dict(pid=child.pid,pgid=os.getpgid(child.pid),command=command,started=time.time())
 record.write_text(json.dumps(result)+'\n');print(json.dumps(result))
elif mode in ['steam-inspect','overlay-inspect','overlay-gl-inspect']:
 name=mode.removesuffix('-inspect');record=json.loads((work/(name+'-process.json')).read_text())
 processes=[]
 for proc in Path('/proc').glob('[0-9]*'):
  try:
   command=proc.joinpath('cmdline').read_bytes().replace(b'\0',b' ').decode()
   if proc.stat().st_uid==account.pw_uid and any(word in command for word in ['steam','vkcube','glxgears','mangohud']):processes.append(dict(pid=int(proc.name),command=command))
  except (OSError,UnicodeError):pass
 candidates=[work/(name+'.log')]+sorted(work.glob('steam-home/**/logs/*.txt'))
 logs={};budget=768*1024
 inventory=[]
 for path in candidates:
  if not path.is_file():continue
  inventory.append(dict(path=str(path.relative_to(work)),bytes=path.stat().st_size))
  if budget<=0:continue
  with path.open('rb') as stream:
   count=min(65536,budget,path.stat().st_size);stream.seek(-count,2);text=stream.read(count)
  logs[str(path.relative_to(work))]=text.decode('utf-8','replace');budget-=len(text)
 exit_path=work/(name+'-exit.json')
 print(json.dumps(dict(record=record,processes=processes,logs=logs,log_inventory=inventory,elapsed=time.time()-record['started'],exit=json.loads(exit_path.read_text()) if exit_path.exists() else None)))
elif mode in ['steam-stop','overlay-stop','overlay-gl-stop']:
 name=mode.removesuffix('-stop');record=json.loads((work/(name+'-process.json')).read_text());pid=record['pid']
 proc=Path('/proc')/str(pid)
 if proc.exists():
  assert proc.joinpath('cmdline').read_bytes().split(b'\0')[1:4]==[__file__.encode(),b'watch',name.encode()]
  assert os.getpgid(pid)==record['pgid']==pid
  os.killpg(pid,signal.SIGTERM);time.sleep(3)
  try:os.killpg(pid,signal.SIGKILL)
  except ProcessLookupError:pass
 print(json.dumps(dict(stopped=True,process=record)))
else:raise ValueError(mode)
