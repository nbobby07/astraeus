"""Additional read-only gaming evidence after the second encrypted cold boot."""
import json
import phase4_guest as guest
guest.p2guest.guard();prefix,desktop=guest.session('tester');assert prefix
reply=guest.execute(prefix+['distroctl','gaming','doctor','--probe','--json'],timeout=60)
assert reply['code']==0 and reply['error'] is None
report=json.loads(reply['output'])
for name in ['vulkan64','vulkan32']:assert report['checks'][name]['runtime']=='passed'
assert report['checks']['graphics_acceleration']['state']=='unsupported'
for architecture in ['native','compat32']:
 devices=report['graphics'][architecture]['devices'];assert devices and all(item['software'] for item in devices)
print(json.dumps(dict(scope='Initial signed image features after two enforced LUKS2 boots; targeted transactions remain unsupported',desktop=desktop,reply=reply)))
