"""TEST ONLY: focused assertions using the unchanged Phase 4.1 adapters."""
from pathlib import Path
from datetime import datetime, timezone
import atexit, hashlib, json, os, pwd, re, shutil, subprocess, sys, tempfile, time
import phase4_guest as guest
import phase4_proton as proton

guest.p2guest.guard()
prefix, desktop = guest.session('tester')
assert prefix, 'Actual Plasma Wayland session required'
account = pwd.getpwnam('tester')
attempt = sys.argv[2] if len(sys.argv) > 2 else 'r1'
assert re.fullmatch('[a-z0-9-]+', attempt)
parent = Path('/home/tester/phase41-tests'); parent.mkdir(exist_ok=True)
os.chown(parent, account.pw_uid, account.pw_gid)
work = parent / attempt; work.mkdir(exist_ok=True, mode=0o700)
os.chown(work, account.pw_uid, account.pw_gid)
manifest = json.loads((guest.FIXTURES / 'prebuilt.json').read_text())
checks = {}
now = lambda: datetime.now(timezone.utc).isoformat()
started = now()

def fixture(name):
    source = guest.FIXTURES / name
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest['binaries'][name]
    target = work / name
    if not target.exists(): shutil.copyfile(source, target)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == manifest['binaries'][name]
    target.chmod(0o755)
    return target

def probe(name, argv, marker=None, bits=None, timeout=30, env=None):
    start = now()
    result = guest.execute(prefix + [str(a) for a in argv], timeout=timeout, env=env)
    result.update(started=start, finished=now(), status=guest.verdict(result, marker, bits))
    checks[name] = result
    return result

mode = sys.argv[1]
atexit.register(lambda: (work/(mode+'-partial.json')).write_text(json.dumps(dict(checks=checks))))
if mode == 'proton':
    executable = fixture('windows-smoke.exe')
    assert manifest['windows_source_sha256'] == hashlib.sha256((guest.FIXTURES/'windows-smoke.c').read_bytes()).hexdigest()
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == '5cee03d79ce1a46be0fb9e731d2ab5ce10cba1a46de86430e6afa6553c6e1347'
    tool = Path('/home/tester/.local/share/Steam/compatibilitytools.d/GE-Proton11-7-x86_64/proton')
    runtime = Path('/home/tester/phase4-runtimes/SteamLinuxRuntime_4/_v2-entry-point')
    assert hashlib.sha256(tool.read_bytes()).hexdigest() == 'c0fe398829c78c82b26d39c20fbeb6b28d1e46941723962d794d7e5f67d402be'
    checks['runtime-identity'] = dict(proton_version=(tool.parent/'version').read_text(),
        tool_manifest=(tool.parent/'toolmanifest.vdf').read_text(), runtime_versions=(runtime.parent/'VERSIONS.txt').read_text(),
        launcher_sha256=hashlib.sha256(tool.read_bytes()).hexdigest(), runtime_entry_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),
        fixture_manifest=manifest)
    compat = work/'compatdata'; compat.mkdir(); os.chown(compat, account.pw_uid, account.pw_gid)
    steam = Path('/home/tester/phase4-session/steam-home/.local/share/Steam')
    for name, negative in [('proton-execution',False), ('proton-exit-control',True)]:
        start = now()
        checks[name] = proton.run_case(prefix, tool, runtime, executable, compat, steam, work, negative)
        checks[name].update(started=start, finished=now())
elif mode == 'core':
    probe('packages', ['pacman','-Q'])
    probe('dependencies', ['pacman','-Dk'])
    probe('installed-smoke', ['bash',guest.HERE/'installed-smoke.sh','none'],
          'DISTRO_INSTALL_OK: uefi uki none btrfs sddm plasma wayland network audio status', timeout=90)
    for name, argv in [('graphics',['distroctl','graphics','--probe','--json']),
                       ('gaming-status',['distroctl','gaming','status','--probe','--json']),
                       ('gaming-doctor',['distroctl','gaming','doctor','--probe','--json'])]:
        result = probe(name, argv, timeout=60)
        if result['code'] == 0 and not result['error']: result['parsed'] = json.loads(result['output'])
    probe('opengl', ['glxinfo','-B'])
    probe('xwayland', ['bash','-euc','pgrep -u "$UID" -x Xwayland; glxinfo -B'])
    for bits in [64,32]:
        exe = fixture(f'vulkan{bits}')
        probe(f'elf-{bits}', ['file',exe])
        link = probe(f'link-{bits}', ['ldd',exe])
        if 'not found' in link['output']: link['status']='FAIL'
        result = probe(f'vulkan-{bits}', [exe], 'PHASE4_VULKAN_OK pixels=256', bits)
        result['renderer'] = guest.renderer(result['output'])
        result['fixture_sha256'] = hashlib.sha256(exe.read_bytes()).hexdigest()
        probe(f'mangohud-{bits}', ['mangohud',exe], 'PHASE4_VULKAN_OK pixels=256', bits)
    native, compat = fixture('vulkan64'), fixture('vulkan32')
    library = next(p for p in Path('/usr/lib32').glob('libvulkan*.so*') if p.is_file() and p.read_bytes()[:5] == b'\x7fELF\x01')
    for name, exe, contents in [('missing-icd',native,None), ('invalid-icd',native,'{broken'),
        ('wrong-architecture',native,json.dumps(dict(file_format_version='1.0.0',ICD=dict(library_path=str(library),api_version='1.0.0')))),
        ('missing-lib32-icd',compat,None)]:
        path = work/(name+'.json'); assert not path.exists()
        if contents is not None: path.write_text(contents)
        result = probe(name,[exe],env={**os.environ,'VK_DRIVER_FILES':str(path),'VK_ICD_FILENAMES':str(path),'VK_LOADER_DEBUG':'all'})
        result['expected_code'] = 1
        result['status'] = 'PASS' if result['code']==1 and not result['error'] and re.search(r'ICD|driver|VkResult|ELFCLASS',result['output'],re.I) else 'FAIL'
        if name=='wrong-architecture' and 'ELFCLASS32' not in result['output']: result['status']='FAIL'
    result = probe('gamescope-preflight',['python3',guest.HERE/'phase4_gamescope.py'],timeout=65)
    if result['code']==77 and not result['error']:
        result['parsed']=json.loads(result['output'])
        result['negative_status']='PASS' if result['parsed']['launched'] is False and result['parsed']['status']=='UNSUPPORTED' else 'FAIL'
elif mode == 'gamemode':
    before = guest.gamemode_settings('tester')
    initial = probe('service-initial',['systemctl','--user','is-active','gamemoded.service'])
    initial['status']='PASS' if initial['code'] in [0,3] and not initial['error'] else 'FAIL'
    initial['scope']='Initial service state observation; inactive is allowed before explicit start'
    probe('service-start',['systemctl','--user','start','gamemoded.service'])
    probe('service-health',['systemctl','--user','status','gamemoded.service','--no-pager'])
    probe('client-before',['gamemoded','-s'])
    probe('upstream-self-test',['gamemoded','-t'],timeout=45)
    exe = fixture('vulkan64')
    with tempfile.TemporaryFile() as output:
        argv=prefix+['gamemoderun','bash','-euc','"$1"; sleep 4','workload',str(exe)]
        child=subprocess.Popen(argv,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            time.sleep(1)
            active=probe('client-during',['gamemoded','-s'])
            active['status']='PASS' if active['code']==0 and not active['error'] and active['output'].strip()=='gamemode is active' else 'FAIL'
            code=child.wait(timeout=20)
        finally:
            if child.poll() is None:
                child.terminate(); child.wait(timeout=5)
        output.seek(0); text=output.read(guest.p2guest.LIMIT).decode(errors='replace')
        reply=dict(command=argv,code=code,output=text,error=None)
        checks['gamemoderun-workload']=dict(reply,status=guest.verdict(reply,'PHASE4_VULKAN_OK pixels=256',64))
    for index in range(15):
        after=probe('client-after',['gamemoded','-s'])
        if after['output'].strip()=='gamemode is inactive': break
        time.sleep(1)
    after['status']='PASS' if after['code']==0 and not after['error'] and after['output'].strip()=='gamemode is inactive' else 'FAIL'
    if initial['code'] != 0: probe('service-stop-restoration',['systemctl','--user','stop','gamemoded.service'])
    final=probe('service-final',['systemctl','--user','is-active','gamemoded.service'])
    final['status']='PASS' if final['code']==initial['code'] and final['output']==initial['output'] and not final['error'] else 'FAIL'
    after_settings=guest.gamemode_settings('tester')
    checks['settings-restoration']=dict(status='PASS' if before==after_settings and not before['errors'] else 'FAIL',before=before,after=after_settings)
    checks['cpu-governor']=dict(status='UNSUPPORTED' if before['cpu_governor']=='UNSUPPORTED' else 'NOT RUN',paths=before['governor_paths'])
    probe('service-journal',['journalctl','--user','-u','gamemoded.service','-b','--no-pager','-n','100'])
elif mode == 'steam-runtime':
    root=Path('/home/tester/phase4-session/steam-home/.local/share/Steam')
    runtime=root/'ubuntu12_32/steam-runtime'; steam=root/'ubuntu12_32/steam'
    probe('client-elf',['file',steam])
    libraries=probe('runtime-libraries',[runtime/'run.sh','--','ldd',steam],timeout=60)
    if 'not found' in libraries['output']:libraries['status']='FAIL'
    probe('runtime-diagnostics',[runtime/'run.sh','--','steam-runtime-system-info'],timeout=120)
    checks['identity']=dict(steam_sha256=hashlib.sha256(steam.read_bytes()).hexdigest(),elf_header=steam.read_bytes()[:20].hex(),
        versions={str(p.relative_to(root)):p.read_text(errors='replace') for p in [runtime/'version.txt',root/'steamrt64/pv-runtime/steam-runtime-steamrt/VERSIONS.txt'] if p.is_file()})
    if steam.read_bytes()[:5]!=b'\x7fELF\x01':checks['client-elf']['status']='FAIL'
else: raise ValueError(mode)
print(json.dumps(dict(schema_version=1,mode=mode,attempt=attempt,started=started,finished=now(),desktop=desktop,checks=checks,
    kernel=os.uname().release,os_release=Path('/etc/os-release').read_text(),boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    work=str(work),physical_gpu_qualified=False,gaming_validated=False)))
