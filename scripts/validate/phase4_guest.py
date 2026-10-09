#!/usr/bin/env python3
"""TEST ONLY: graphics observations inside a disposable Phase 2 command-channel guest."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('p2guest', HERE / 'phase2-guest.py')
p2guest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p2guest)
FIXTURES = HERE / 'fixtures'


def execute(argv, timeout=30, env=None):
    """Record real exits, limit output, and reap the whole launched process group."""
    started = time.monotonic()
    with tempfile.TemporaryFile() as log:
        try:
            child = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                                     env=env, start_new_session=True)
        except OSError as error:
            return dict(command=argv, code=127, output=str(error), error='launch failed', seconds=0)
        error = None
        while child.poll() is None:
            if time.monotonic() - started >= timeout:
                error = 'timeout'
            if os.fstat(log.fileno()).st_size > p2guest.LIMIT:
                error = 'output limit'
            if error:
                break
            time.sleep(0.05)
        # Steam and Wine may leave descendants after their launcher exits.
        try:
            os.killpg(child.pid, signal.SIGTERM)
            time.sleep(0.1)
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        code = child.wait(timeout=5)
        if os.fstat(log.fileno()).st_size > p2guest.LIMIT:
            error = 'output limit'
        log.seek(0)
        return dict(command=argv, code=code, output=log.read(p2guest.LIMIT).decode('utf-8', 'replace'),
                    error=error, seconds=round(time.monotonic() - started, 3))


def session(user):
    account = pwd.getpwnam(user)
    if account.pw_uid == 0:
        raise ValueError('desktop probes require an unprivileged disposable user')
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if proc.stat().st_uid != account.pw_uid or (proc / 'comm').read_text().strip() != 'plasmashell':
                continue
            env = dict(item.decode().split('=', 1) for item in (proc / 'environ').read_bytes().split(b'\0') if b'=' in item)
            if env.get('XDG_SESSION_TYPE') != 'wayland' or 'KDE' not in env.get('XDG_CURRENT_DESKTOP', ''):
                continue
            keys = ['DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS',
                    'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP']
            values = {key: env[key] for key in keys if key in env}
            return ['runuser', '-u', user, '--', 'env', *[f'{k}={v}' for k, v in values.items()]], values
        except (OSError, UnicodeError, ValueError):
            continue
    return None, {}


def verdict(reply, marker=None, bits=None):
    if reply['code'] == 127 and reply.get('error') in [None, 'launch failed']:
        return 'NOT RUN'
    if reply['code'] == 77 and not reply.get('error'):
        return 'UNSUPPORTED'
    if reply['code'] != 0 or reply.get('error'):
        return 'FAIL'
    if marker and marker not in reply['output'].splitlines():
        return 'FAIL'
    if bits and f'architecture_bits={bits}' not in reply['output'].splitlines():
        return 'FAIL'
    return 'PASS'


def renderer(text):
    values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
    name = values.get('renderer', 'unobserved')
    software = values.get('device_type') == '4' or bool(re.search(r'llvmpipe|lavapipe|software|swrast', name, re.I))
    return dict(name=name, software=software, device_type=values.get('device_type'),
                vendor=values.get('vendor'), physical_qualified=False)


def gpu_classification(text):
    displays = [line for line in text.splitlines() if re.search(r'VGA|3D controller|Display controller', line)]
    virtual = bool(displays) and all(re.search(r'Virtio|QXL|Bochs|VMware|VirtualBox', line, re.I) for line in displays)
    return dict(display_devices=displays, classification='virtual' if virtual else 'unqualified',
                physical_qualified=False)


def suite(user, work, proton=None, runtime=None):
    checks = {}
    prefix, desktop = session(user)

    def probe(name, argv, marker=None, bits=None, user_session=False, env=None, timeout=30):
        if user_session and not prefix:
            checks[name] = dict(status='NOT RUN', code=None, output='Log into disposable Plasma Wayland user first')
            return checks[name]
        reply = execute((prefix if user_session else []) + [str(a) for a in argv], timeout, env)
        reply['status'] = verdict(reply, marker, bits)
        checks[name] = reply
        return reply

    probe('packages', ['pacman', '-Q'])
    probe('dependencies', ['pacman', '-Dk'])
    probe('lib32-packages', ['pacman', '-Q', 'lib32-vulkan-icd-loader'])
    probe('gaming-packages', ['pacman', '-Q', 'steam', 'gamescope', 'mangohud', 'gamemode',
                             'vulkan-icd-loader', 'lib32-vulkan-icd-loader'])
    gpu = probe('gpu', ['lspci', '-nnk'])
    gpu['classification'] = gpu_classification(gpu['output'])
    probe('hardware-json', ['distroctl', 'hardware', '--json'])
    probe('input', ['bash', '-euc', 'cat /proc/bus/input/devices; ls -l /dev/input; '
           'find /usr/lib/udev/rules.d /etc/udev/rules.d -iname "*steam*" -o -iname "*gamepad*"'])
    probe('display', ['kscreen-doctor', '-o'], user_session=True)
    probe('kwin-support', ['qdbus6', 'org.kde.KWin', '/KWin', 'supportInformation'], user_session=True)
    probe('opengl', ['glxinfo', '-B'], user_session=True)
    probe('xwayland', ['xdpyinfo'], user_session=True)
    probe('vulkan-enumeration', ['vulkaninfo', '--summary'], user_session=True,
          env={**os.environ, 'VK_LOADER_DEBUG': 'driver'})
    icds = []
    for root in ['/usr/share/vulkan/icd.d', '/etc/vulkan/icd.d']:
        for path in sorted(Path(root).glob('*.json')):
            entry = dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            try:
                entry['contents'] = json.loads(path.read_text())
            except (ValueError, UnicodeError) as error:
                entry['error'] = str(error)
            icds.append(entry)
    checks['icds'] = dict(status='PASS' if icds and all('error' not in x for x in icds) else 'FAIL',
                          code=None, observations=icds, scope='manifest discovery only')
    builds = {}
    for bits in [64, 32]:
        binary = work / f'vulkan{bits}'
        prebuilt = FIXTURES / f'vulkan{bits}'
        if prebuilt.is_file():
            manifest = json.loads((FIXTURES / 'prebuilt.json').read_text())
            if hashlib.sha256(prebuilt.read_bytes()).hexdigest() != manifest['binaries'][prebuilt.name]:
                raise ValueError('prebuilt Vulkan binary changed in guest')
            shutil.copyfile(prebuilt, binary)
            binary.chmod(0o755)
            build = dict(status='PASS', code=None, scope='copied hash-bound host-built fixture, not installed compiler')
            checks[f'build-{bits}'] = build
        else:
            build = probe(f'build-{bits}', ['cc', f'-m{bits}', '-Wall', '-Wextra', '-Werror',
                           FIXTURES / 'vulkan-workload.c', '-o', binary, '-lvulkan'])
        if build['status'] != 'PASS':
            checks[f'vulkan-{bits}'] = dict(status='NOT RUN', code=None, output='Fixture compilation unavailable; inspect build evidence')
            continue
        builds[bits] = binary
        probe(f'elf-{bits}', ['file', binary])
        probe(f'link-{bits}', ['ldd', binary])
        result = probe(f'vulkan-{bits}', [binary], 'PHASE4_VULKAN_OK pixels=256', bits,
                       user_session=True, env={**os.environ, 'VK_LOADER_DEBUG': 'driver'})
        result['renderer'] = renderer(result['output'])
        result['binary_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
    binary = builds.get(64)
    if binary:
        cases = [('missing-icd', None), ('corrupt-icd', '{broken')]
        elf32 = next((p for p in Path('/usr/lib32').glob('libvulkan*.so*')
                      if p.is_file() and p.read_bytes()[:5] == b'\x7fELF\x01'), None)
        if elf32:
            cases.append(('wrong-architecture', json.dumps(dict(file_format_version='1.0.0',
                          ICD=dict(library_path=str(elf32), api_version='1.0.0')))))
        else:
            checks['wrong-architecture'] = dict(status='NOT RUN', code=None,
                output='No real ELF32 Vulkan library available; a missing path cannot prove ELFCLASS32 refusal')
        for name, contents in cases:
            path = work / f'{name}.json'
            if contents is not None:
                path.write_text(contents)
            result = probe(name, [binary], user_session=True,
                           env={**os.environ, 'VK_DRIVER_FILES': str(path), 'VK_ICD_FILENAMES': str(path),
                                'VK_LOADER_DEBUG': 'all'})
            # A negative pass needs an actual execution failure and actionable loader diagnostics.
            if result['status'] != 'NOT RUN':
                result['status'] = 'PASS' if result['code'] is not None and 0 < result['code'] <= 125 and not result.get('error') and re.search(
                    r'ICD|driver|VkResult|ELFCLASS', result['output'], re.I) else 'FAIL'
                result['scope'] = 'Vulkan loader refusal, not production readiness CLI'
                if name == 'wrong-architecture' and 'ELFCLASS32' not in result['output']:
                    result['status'] = 'FAIL'
    if binary and 32 in builds:
        missing32 = work / 'absent32.json'
        result = probe('missing-lib32-icd', [builds[32]], user_session=True,
                       env={**os.environ, 'VK_DRIVER_FILES': str(missing32), 'VK_ICD_FILENAMES': str(missing32),
                            'VK_LOADER_DEBUG': 'all'})
        if result['status'] != 'NOT RUN':
            result['status'] = 'PASS' if result['code'] is not None and 0 < result['code'] <= 125 and not result.get('error') and 'VkResult' in result['output'] else 'FAIL'
            result['scope'] = 'lib32 ICD hidden by per-process override; packages unchanged'
    if prefix:
        probe('user-failed', ['systemctl', '--user', '--failed', '--no-legend', '--plain'], user_session=True)
        probe('gamemode-readiness', ['systemctl', '--user', 'status', 'gamemoded.service', '--no-pager'], user_session=True)
        probe('gamemode-test', ['gamemoded', '-t'], user_session=True, timeout=45)
        if binary:
            before = probe('gamemode-before', ['gamemoded', '-s'], user_session=True)
            probe('gamemode-invoke', ['gamemoderun', binary], 'PHASE4_VULKAN_OK pixels=256', 64, user_session=True)
            after = probe('gamemode-after', ['gamemoded', '-s'], user_session=True)
            checks['gamemode-restoration'] = dict(status='PASS' if before['code'] in [0, 1]
                and before['code'] == after['code'] and not before.get('error') and not after.get('error')
                and before['output'] == after['output'] else 'FAIL', code=None,
                scope='daemon status restored; gamemoded -t separately checks its configured optimizations')
            probe('mangohud-invoke', ['mangohud', binary], 'PHASE4_VULKAN_OK pixels=256', 64, user_session=True,
                  env={**os.environ, 'MANGOHUD_CONFIG': 'fps,frametime'})
        probe('mangohud-wsi', ['mangohud', 'vkcube', '--c', '60'], user_session=True, timeout=30,
              env={**os.environ, 'MANGOHUD_CONFIG': 'fps,frametime'})
        probe('gamescope-launch', ['gamescope', '--', 'vkcube', '--c', '60'], user_session=True, timeout=30)
    checks['overlay-visible'] = dict(status='NOT RUN', code=None,
        output='Invocation is separate from visible overlay acceptance; retain private QMP screenshot and manual inspection')
    checks['vrr-hdr-physical'] = dict(status='UNSUPPORTED', code=None,
        output='Virtual display cannot qualify physical VRR/HDR output')
    # Disposable HOME prevents reading personal Steam sessions and confines downloads/logs.
    steamhome = work / 'steam-home'
    steamhome.mkdir()
    account = pwd.getpwnam(user)
    os.chown(steamhome, account.pw_uid, account.pw_gid)
    steam = probe('steam-launch', ['env', f'HOME={steamhome}', 'steam', '-nochatui', '-nofriendsui'],
                  user_session=True, timeout=45)
    if steam['status'] == 'PASS' or steam.get('error') == 'timeout':
        steam['status'] = 'NOT RUN'
        steam['boundary'] = 'Launch attempted; login screen and runtime readiness require inspection. Game execution NOT RUN'
    probe('steam-logs', ['bash', '-c', 'find "$1" -type f -name "*.txt" -size -512k -exec tail -c 32768 {} ";"',
                         'steam-logs', steamhome])
    checks['steam-game-execution'] = dict(status='NOT RUN', code=None, output='No credentials collected; login-required boundary')
    checks['steam-runtime'] = dict(status='NOT RUN', code=None,
        output='Inspect downloaded runtime tools and dependency diagnostics in disposable Steam HOME; download presence alone is insufficient')
    if proton and runtime and prefix and proton.is_file() and runtime.is_file():
        probe('runtime-version', [runtime, '--version'], user_session=True)
        exe = work / 'windows-smoke.exe'
        prebuilt = FIXTURES / 'windows-smoke.exe'
        if prebuilt.is_file():
            manifest = json.loads((FIXTURES / 'prebuilt.json').read_text())
            if hashlib.sha256(prebuilt.read_bytes()).hexdigest() != manifest['binaries']['windows-smoke.exe']:
                raise ValueError('prebuilt Win32 binary changed in guest')
            shutil.copyfile(prebuilt, exe)
            exe.chmod(0o755)
            build = dict(status='PASS', code=None, scope='copied hash-bound Windows fixture')
            checks['windows-build'] = build
        else:
            build = probe('windows-build', ['x86_64-w64-mingw32-gcc', '-Wall', '-Wextra', '-Werror',
                                           FIXTURES / 'windows-smoke.c', '-o', exe, '-luser32'])
        if build['status'] == 'PASS':
            compat = work / 'compatdata'
            compat.mkdir()
            os.chown(compat, account.pw_uid, account.pw_gid)
            nonce = uuid.uuid4().hex
            result = probe('proton-execution', ['env', f'STEAM_COMPAT_DATA_PATH={compat}',
                f'STEAM_COMPAT_CLIENT_INSTALL_PATH={steamhome}', 'SteamAppId=0', 'PROTON_LOG=1',
                f'PROTON_LOG_DIR={work}', runtime, '--verb=waitforexitandrun', '--', proton, 'run', exe, nonce],
                f'PHASE4_WINDOWS_OK {nonce}', user_session=True, timeout=60)
            result['fixture_sha256'] = hashlib.sha256(exe.read_bytes()).hexdigest()
            result['proton_sha256'] = hashlib.sha256(proton.read_bytes()).hexdigest()
            result['scope'] = 'Win32 window/exit smoke only; DirectX and games unqualified'
        else:
            checks['proton-execution'] = dict(status='NOT RUN', code=None, output='Win32 compiler unavailable')
    else:
        checks['proton-execution'] = dict(status='NOT RUN', code=None,
            output='Provide inspected Proton script and Steam Linux Runtime _v2-entry-point; no raw Wine substitution')
    probe('proton-logs', ['bash', '-c', 'find "$1" -maxdepth 1 -name "steam-*.log" -exec tail -c 131072 {} ";"', 'logs', work])
    checks['vulkan-32']['runtime_verification'] = 'VERIFIED' if checks['vulkan-32']['status'] == 'PASS' else 'UNVERIFIED'
    return dict(schema_version=1, desktop=desktop, checks=checks, physical_gpu_qualified=False,
                gaming_validated=False, work=str(work))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', required=True)
    parser.add_argument('--proton', type=Path)
    parser.add_argument('--runtime', type=Path)
    args = parser.parse_args()
    p2guest.guard()
    account = pwd.getpwnam(args.user)
    if account.pw_uid == 0:
        parser.error('root cannot be the gaming user')
    with tempfile.TemporaryDirectory(prefix='phase4-', dir='/var/tmp') as temp:
        work = Path(temp)
        os.chown(work, account.pw_uid, account.pw_gid)
        result = suite(args.user, work, args.proton, args.runtime)
        print(json.dumps(result))


if __name__ == '__main__':
    main()
