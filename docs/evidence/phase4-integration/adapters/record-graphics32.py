from pathlib import Path
import hashlib,json
r=Path('/home/ubuntu/p4i/r2/graphics32')
inspection=json.loads((r/'inspection.json').read_text());run=json.loads((r/'workload.json').read_text())
assert inspection['gears']=='/usr/bin/glxgears32' and inspection['renderer']['code']==0
assert 'llvmpipe' in inspection['renderer']['output'] and 'Accelerated: no' in inspection['renderer']['output']
for name in ['gears_libraries','info_libraries']:
    assert inspection[name]['code']==0 and 'not found' not in inspection[name]['output']
assert run['execution']['code']==143 and run['execution']['error'] is None
frames={name:hashlib.sha256((r/name).read_bytes()).hexdigest() for name in ['frame-1.png','frame-2.png','closed.png']}
assert frames['frame-1.png']!=frames['frame-2.png']
result={'source_commit':'cac8998ad7730e69ae354c3162ef4a0677cfc162','elf32_opengl_presentation':'PASS',
        'visible_mangohud':'PASS','operator_observation':'Two actual rendered gears frames with changing FPS, frame time and graph. Closed the focused window through Alt+F4 after both captures.',
        'exit_code':143,'exit_scope':'Window-manager close yielded Terminated/143; no zero-exit or game compatibility claim.',
        'frames_sha256':frames,'binary_sha256':inspection['gears_sha256'],
        'limitations':['Software llvmpipe only','32-bit Vulkan WSI remains NOT RUN','MangoHud cannot collect this virtual GPU telemetry or CPU temperature']}
(r/'visual-observation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
