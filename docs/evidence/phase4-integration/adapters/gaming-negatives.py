"""TEST ONLY: namespace-scoped missing files and real CLI refusals, no package writes."""
import hashlib,json,os,pwd,shutil,subprocess,sys,tempfile
from contextlib import ExitStack
from pathlib import Path
import phase4_guest as guest
guest.p2guest.guard()

def invoke(argv):
    result=guest.execute(argv,timeout=60)
    assert result['error'] is None,result
    return result

def case(name):
    prefix,_=guest.session('tester');assert prefix,'desktop session unavailable'
    with tempfile.TemporaryDirectory(prefix='phase4-negative-') as temporary, ExitStack() as mounts:
        work=Path(temporary);work.chmod(0o755)
        def overlay(target):
            area=work/Path(target).name;area.mkdir()
            for part in ['upper','work']:(area/part).mkdir()
            subprocess.run(['mount','-t','overlay','overlay','-o',f'lowerdir={target},upperdir={area}/upper,workdir={area}/work',target],check=True)
            mounts.callback(subprocess.run,['umount',target],check=True)
        if name in ['missing-loader64','missing-loader32']:
            target='/usr/lib' if name.endswith('64') else '/usr/lib32'
            overlay(target)
            paths=list(Path(target).glob('libvulkan.so*'));assert paths
            for path in paths:path.unlink()
            reply=invoke(prefix+['distroctl','gaming','doctor','--probe','--json']);assert reply['code']==0
            report=json.loads(reply['output']);arch='native' if name.endswith('64') else 'compat32'
            assert report['graphics'][arch]['loader']=='absent'
            assert report['checks']['vulkan'+name[-2:]]['runtime']!='passed'
        elif name=='missing-steam':
            overlay('/usr/bin');Path('/usr/bin/steam').unlink()
            reply=invoke(prefix+['distroctl','gaming','doctor','--json']);assert reply['code']==0
            report=json.loads(reply['output']);assert report['checks']['steam_launcher']['state']=='not_installed'
            assert report['checks']['steam_runtime']['runtime']=='untested'
        elif name=='missing-proton':
            home=work/'home';home.mkdir();account=pwd.getpwnam('tester');os.chown(home,account.pw_uid,account.pw_gid)
            reply=invoke(prefix+['env',f'HOME={home}',f'XDG_DATA_HOME={home}/data','distroctl','gaming','doctor','--json']);assert reply['code']==0
            report=json.loads(reply['output']);assert not report['tools']
            assert all(report['checks'][key]['state']=='not_installed' for key in ['proton','proton_ge','proton_custom'])
        elif name=='no-device':
            empty=work/'pci';empty.mkdir()
            subprocess.run(['mount','--bind',str(empty),'/sys/bus/pci/devices'],check=True)
            mounts.callback(subprocess.run,['umount','/sys/bus/pci/devices'],check=True)
            reply=invoke(prefix+['distroctl','gaming','doctor','--json']);assert reply['code']==0
            report=json.loads(reply['output']);assert report['graphics']['gpus']==[]
            assert report['checks']['graphics_acceleration']['runtime']=='untested'
        elif name=='dependency-mismatch':
            overlay('/var/lib/pacman/local')
            records=list(Path('/var/lib/pacman/local').glob('lib32-mesa-*/desc'));assert len(records)==1
            path=records[0];text=path.read_text();version=text.split('%VERSION%\n')[1].splitlines()[0]
            path.write_text(text.replace('%VERSION%\n'+version+'\n','%VERSION%\n999:999-1\n'))
            reply=invoke(prefix+['distroctl','update','--dry-run','--json'])
            assert reply['code']==1 and 'inconsistent graphics package state' in reply['output'],reply
        elif name in ['enable-refusal','disable-refusal']:
            action=name.split('-')[0]
            reply=invoke(prefix+['distroctl','gaming',action,'core','--json'])
            assert reply['code']==1 and 'only supports synchronized upgrades' in reply['output']
            payload=reply['output'].split('\ndistroctl:')[0]
            assert json.loads(payload)['executable'] is False
        elif name=='invalid-preset':
            reply=invoke(prefix+['distroctl','gaming','enable','invalid-fixture','--dry-run','--json'])
            assert reply['code']==1 and 'unsupported gaming feature' in reply['output']
        else:raise ValueError(name)
        print(json.dumps(dict(status='PASS',scope='actual production CLI under isolated test mount/environment; no physical qualification',reply=reply)))

if len(sys.argv)==3 and sys.argv[1]=='--case':
    case(sys.argv[2])
else:
    before=subprocess.check_output(['pacman','-Q'])
    files=[Path('/usr/bin/steam'),Path('/usr/lib/libvulkan.so.1'),Path('/usr/lib32/libvulkan.so.1')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    result={}
    for name in ['missing-loader64','missing-loader32','missing-steam','missing-proton','no-device','dependency-mismatch','enable-refusal','disable-refusal','invalid-preset']:
        reply=invoke(['unshare','--mount','--propagation','private',sys.executable,__file__,'--case',name])
        result[name]=dict(status='FAIL',reply=reply) if reply['code'] else json.loads(reply['output'])
    assert subprocess.check_output(['pacman','-Q'])==before
    assert {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}==hashes
    print(json.dumps(dict(checks=result,package_and_file_state_preserved=True)))
