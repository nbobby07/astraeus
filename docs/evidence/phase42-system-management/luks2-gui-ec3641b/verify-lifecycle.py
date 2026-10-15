import json,hashlib,sys
from pathlib import Path
base=Path(sys.argv[1]);root=base/'luks2-gui-accepted-evidence';p=root/'gce/requests'
def raw(n):
 x=json.loads((p/(str(n).zfill(4)+'.result')).read_text())['result'];assert x['code']==0,(n,x);return x['output']
def r(n):return json.JSONDecoder().raw_decode(raw(n).lstrip())[0]
initial=r(2);final=r(60)
assert initial==r(4)
assert r(7)==r(8)==r(9)
assert 'ORIGINAL_GUI_EXITED' in raw(19)
for a,b in [(r(18),r(19)),(r(28)['barrier_before'],r(29))]:
 assert a['record']==b['record'] and a['worker_alive'] and b['worker_alive']
 assert a['finished'] is None and b['finished'] is None
assert r(28)['only_ordinary_gui_sigkill']['uid']==1000
assert r(36)['observed']==r(38)['observed'] and r(36)['snapshots']==r(38)['snapshots']
install=json.loads(r(24)['observed']['stdout']);removed=json.loads(r(32)['observed']['stdout'])
assert set(install['packages'])-set(removed['packages'])=={'mangohud','lib32-mangohud'}
assert not set(removed['packages'])-set(install['packages'])
for name in removed['packages']:
 assert removed['packages'][name]==install['packages'][name] and removed['reasons'][name]==install['reasons'][name],name
for x in [initial,install,removed,final]:
 assert x['packages']['tree']==initial['packages']['tree'] and x['reasons']['tree']=='explicit'
 assert x['home']==initial['home']
 assert x['firmware']=={'SecureBoot':True,'SetupMode':False}
 assert 'tree' not in x['management']['packages']
assert all(x in final['packages'] for x in ['steam','kcalc','mangohud','lib32-mangohud'])
fixture=r(39)
for k in ['packages','home','management','system_lock','configuration']:assert fixture['before'][k]==fixture['after'][k],k
assert fixture['before']['reasons']['kcalc']=='explicit' and fixture['after']['reasons']['kcalc']=='dependency'
reconciled=json.loads(r(45)['observed']['stdout'])
for k in ['packages','reasons','home']:assert fixture['after'][k]==reconciled[k]
assert final['reasons']['kcalc']=='dependency'
for n,j in [(5,21),(26,31),(40,41),(46,47),(53,55)]:
 v=r(j);e=v['submission'] if j in [21,31] else v['envelope']
 assert r(n)['plan_id']==e['submission']['expected_plan']
 assert e['initiating_uid']==1000
for k in ['packages','reasons','home']:assert r(54)[k]==r(56)[k]==final[k]
for k in ['management','system_lock','configuration','config_toml']:assert r(56)[k]==final[k],k
assert set(final['configuration']['gaming'])=={'core','tools'}
assert final['boot_id']!=r(56)['boot_id']
h=r(59)['history'];assert len(h)==6 and all(x['state']=='succeeded' for x in h)
for x in h:
 if x['id']==3:assert not x['snapshot'] and not x['post_snapshot'] and not x['boot_regenerated']
 else:assert x['confirmation']['snapshot']==x['post_snapshot'] and not x['confirmation']['rollback']
assert next(x for x in h if x['id']==6)['confirmation']['boot_id']==final['boot_id']
assert r(12)['gui_export_uid']==1000
assert json.loads((p/'0061.result').read_text())['graceful_shutdown']
out={'passed':True,'archive_sha256':'ff51b09a1342f8091d6ba4cb9548b3e106b6f16e45a41e33bc8ddd39b94edf58','checks':['draft adoption unchanged','cancel and deny unchanged','same worker survives close and guarded GUI crash','removal only MangoHud; all retained versions/reasons preserved','pre-existing unmanaged tree and personal sentinel preserved','true noop unchanged after worker exit','external reason drift preserved by metadata reconciliation','all five independent CLI/GUI plan digests and UID1000 match','bundle overlap preserves every package and reason','six successful audit records; five new-root boot confirmations, one true noop','native export owned by ordinary user','graceful final shutdown'],'note':'Root request channel is test observation/injection only. Actual GUI interaction and authentication are separately retained in QMP screenshots. Original failed and premature screenshots are retained, not treated as passing observations.'}
(base/'luks2-gui-lifecycle-verified.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
