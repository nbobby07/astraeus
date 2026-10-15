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
    assert Path('/proc/self/ns/mnt').readlink()!=Path('/proc/1/ns/mnt').readlink()
    prefix,_=guest.session('tester');assert prefix,'desktop session unavailable'
    package_query=None
    with tempfile.TemporaryDirectory(prefix='phase4-negative-') as temporary, ExitStack() as mounts:
        work=Path(temporary);work.chmod(0o755)
        def overlay(target):
            area=work/Path(target).name;area.mkdir()
            for part in ['upper','work']:(area/part).mkdir()
            subprocess.run(['mount','-t','overlay','overlay','-o',f'lowerdir={target},upperdir={area}/upper,workdir={area}/work',target],check=True)
            mounts.callback(subprocess.run,['umount','--lazy',target],check=True)
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
            for kind,target in [('pci','/sys/bus/pci/devices'),('drm','/sys/class/drm')]:
                empty=work/kind;empty.mkdir()
                subprocess.run(['mount','--bind',str(empty),target],check=True)
                mounts.callback(subprocess.run,['umount','--lazy',target],check=True)
            reply=invoke(prefix+['distroctl','gaming','doctor','--json']);assert reply['code']==0
            report=json.loads(reply['output']);assert report['graphics']['gpus']==[]
            assert report['checks']['graphics_acceleration']['runtime']=='untested'
        elif name=='dependency-mismatch':
            overlay('/var/lib/pacman/local')
            records=list(Path('/var/lib/pacman/local').glob('lib32-mesa-[0-9]*/desc'));assert len(records)==1
            original=records[0].parent;replacement=original.with_name('lib32-mesa-999:999-1')
            assert original.parent==Path('/var/lib/pacman/local') and not replacement.exists()
            shutil.copytree(original,replacement);shutil.rmtree(original)
            path=replacement/'desc';text=path.read_text();version=text.split('%VERSION%\n')[1].splitlines()[0]
            path.write_text(text.replace('%VERSION%\n'+version+'\n','%VERSION%\n999:999-1\n'))
            package_query=invoke(['pacman','-Q','lib32-mesa'])
            assert package_query['code']==0 and '999:999-1' in package_query['output']
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
        elif name=='missing-optional-tool':
            overlay('/usr/bin');Path('/usr/bin/gamescope').unlink()
            reply=invoke(prefix+['python3',str(guest.HERE/'phase4_gamescope.py')])
            report=json.loads(reply['output'])
            assert reply['code']==77 and report['launched'] is False
            assert report['reason']=='Missing optional tool: gamescope'
        elif name=='malformed-gaming-config':
            config=work/'config';path=config/'MangoHud/MangoHud.conf'
            path.parent.mkdir(parents=True);path.write_bytes(b'fps\n\xff\xfeinvalid')
            before=path.read_bytes()
            reply=invoke(prefix+['env',f'XDG_CONFIG_HOME={config}','distroctl','gaming','doctor','--json'])
            assert reply['code']==0
            report=json.loads(reply['output'])
            assert report['checks']['mangohud_config']['state']=='unknown'
            assert report['checks']['mangohud_config']['runtime']=='untested'
            assert path.read_bytes()==before
        elif name in ['gamescope-invalid-config','gamescope-unsupported']:
            options=['--backend','drm'] if name=='gamescope-invalid-config' else []
            reply=invoke(prefix+['python3',str(guest.HERE/'phase4_gamescope.py')]+options)
            report=json.loads(reply['output'])
            assert reply['code']==77 and report['status']=='UNSUPPORTED' and report['launched'] is False
            if name=='gamescope-unsupported':
                assert report['devices'] and all(d['missing'] for d in report['devices'])
            else:
                assert '--backend wayland' in report['reason']
        else:raise ValueError(name)
        print(json.dumps(dict(status='PASS',scope='actual production CLI under isolated test mount/environment; no physical qualification',reply=reply,package_query=package_query)))

if len(sys.argv)==3 and sys.argv[1]=='--case':
    case(sys.argv[2])
else:
    before=invoke(['pacman','-Q']);assert before['code']==0
    files=[Path('/usr/bin/steam'),Path('/usr/bin/gamescope'),Path('/usr/lib/libvulkan.so.1'),Path('/usr/lib32/libvulkan.so.1')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    result={}
    for name in ['missing-loader64','missing-loader32','missing-steam','missing-proton','no-device','dependency-mismatch',
                 'enable-refusal','disable-refusal','invalid-preset','missing-optional-tool','malformed-gaming-config',
                 'gamescope-invalid-config','gamescope-unsupported']:
        reply=invoke(['unshare','--mount','--propagation','private',sys.executable,__file__,'--case',name])
        result[name]=dict(status='FAIL',reply=reply) if reply['code'] else json.loads(reply['output'])
    after=invoke(['pacman','-Q']);assert after['code']==0 and after['output']==before['output']
    assert {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}==hashes
    print(json.dumps(dict(checks=result,package_and_file_state_preserved=True,package_query_before=before,package_query_after=after)))
