"""Inspect and exercise only an already installed ELF32 Mesa window utility."""
from pathlib import Path
import hashlib,json,os,sys
import phase4_guest as g
g.p2guest.guard()
prefix,desktop=g.session('tester');assert prefix
listing=g.execute(['pacman','-Qlq','lib32-mesa-utils'])
assert listing['code']==0
paths=[Path(x) for x in listing['output'].splitlines()]
def select(names):
    for p in paths:
        if p.name in names and p.is_file() and os.access(p,os.X_OK):
            with p.open('rb') as stream:head=stream.read(5)
            if head==b'\x7fELF\x01':return p
    return None
gears=select({'glxgears32','glxgears'})
info=select({'glxinfo32','glxinfo'})
result={'desktop':desktop,'package_files':listing,'gears':str(gears) if gears else None,
        'info':str(info) if info else None,'scope':'Actual installed ELF32 OpenGL presentation; no hardware or Vulkan WSI qualification'}
if sys.argv[1]=='inspect':
    for name,path in [('gears',gears),('info',info)]:
        if path:
            result[name+'_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            result[name+'_libraries']=g.execute(prefix+['ldd',str(path)])
    if info:result['renderer']=g.execute(prefix+[str(info),'-B'])
elif sys.argv[1]=='run':
    assert gears,'No installed ELF32 window workload'
    result['execution']=g.execute(prefix+['env','MANGOHUD_CONFIG=fps,frametime','mangohud','--dlsym',str(gears)],timeout=180)
else:raise ValueError(sys.argv[1])
print(json.dumps(result))
