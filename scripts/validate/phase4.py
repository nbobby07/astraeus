#!/usr/bin/env python3
"""Phase 4 evidence adapter over the existing Phase 2/3 runner. No gaming qualification implied."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import sys

import phase2 as p2

MATRIX = p2.REPO / 'tests/fixtures/phase4/matrix.json'
STATUSES = {'PASS', 'FAIL', 'UNSUPPORTED', 'NOT RUN'}
GROUPS = {
    'B': ['gaming-packages', 'dependencies'],
    'C': ['icds', 'vulkan-enumeration'],
    'D': ['vulkan-64'],
    'E': ['lib32-packages', 'link-32', 'vulkan-32'],
    'F': ['steam-runtime', 'steam-launch', 'xwayland'],
    'G': ['proton-execution'],
    'H': ['gamescope-launch'],
    'I': ['mangohud-invoke', 'mangohud-wsi', 'overlay-visible', 'gamemode-test',
          'gamemode-invoke', 'gamemode-restoration'],
    'J': ['readiness-json'],
    'K': ['missing-icd', 'corrupt-icd', 'wrong-architecture', 'missing-lib32-icd',
          'no-device', 'unknown-vendor', 'missing-steam', 'missing-proton', 'gamescope-unsupported',
          'dependency-mismatch', 'transaction-refusal', 'invalid-preset'],
}


def matrix(environment='not executed', hardware=None, checks=None):
    checks = checks or {}
    result = json.loads(MATRIX.read_text())
    for row in result['scenarios']:
        row.update(status='NOT RUN', actual_result='Not executed', environment=environment,
                   relevant_hardware=hardware or {}, evidence_path=[], exit_code=None)
        names = GROUPS.get(row['id'], [])
        if names:
            parts = {name: checks.get(name, dict(status='NOT RUN', code=None,
                     output='Missing integration hook or prerequisite')) for name in names}
            states = [item['status'] for item in parts.values()]
            p2.require(all(state in STATUSES for state in states), 'unknown result status')
            row['status'] = next((state for state in ['FAIL', 'NOT RUN', 'UNSUPPORTED'] if state in states), 'PASS')
            row['actual_result'] = {name: dict(status=item['status'], detail=item.get('output', item.get('scope', '')))
                                    for name, item in parts.items()}
            row['exit_code'] = {name: item.get('code') for name, item in parts.items()}
            row['evidence_path'] = ['guest.json#/checks/' + name for name in parts if name in checks]
    result.update(gaming_validated=False, physical_gpu_qualified=False)
    return result


def hooks(vm, path):
    """Integration supplies real CLI commands; unknown interfaces never become fixture passes."""
    if not path:
        return {}
    items = json.loads(path.read_text())
    p2.require(isinstance(items, dict) and set(items) <= set(GROUPS['K'] + ['readiness-json']), 'unknown hook')
    result = {}
    for name, item in items.items():
        p2.require(set(item) == {'command', 'exit_code', 'marker'} and isinstance(item['command'], str)
                   and type(item['exit_code']) is int and 0 <= item['exit_code'] <= 125
                   and isinstance(item['marker'], str) and item['marker'],
                   'hook needs command, exact exit_code and diagnostic marker')
        reply = vm.command(item['command'], timeout=30, check=False, label='hook-' + name)
        reply['status'] = 'PASS' if reply['code'] == item['exit_code'] and item['marker'] in reply['output'] else 'FAIL'
        if name == 'readiness-json':
            try:
                json.loads(reply['output'])
            except ValueError:
                reply['status'] = 'FAIL'
        result[name] = reply
    return result


def run(args):
    p2.require(sys.platform == 'linux' and Path('/dev/kvm').exists(), 'Linux nested KVM required')
    p2.require(re.fullmatch('[0-9a-f]{40}', args.source_commit), 'full source Git SHA required')
    p2.require(re.fullmatch('[a-z_][a-z0-9_-]*', args.user), 'invalid disposable username')
    p2.require(10 <= args.timeout <= 3600, 'timeout must be 10..3600 seconds')
    args.base, args.output, args.ovmf_code = map(p2.safe_path, [args.base, args.output, args.ovmf_code])
    manifest = p2.verify_baseline(args.base)
    p2.require(manifest.get('kind') == 'phase3-integrated', 'use an enforcing integrated Phase 3 baseline')
    p2.require(manifest['inputs']['ovmf_code']['sha256'] == p2.digest(args.ovmf_code), 'firmware CODE changed')
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(args.output, 0o700)
    report = matrix('nested Astraeus KVM baseline')
    vm = None
    receipt = dict(started=p2.now(), source_commit=args.source_commit, installed_source=manifest['source_commit'],
                   gaming_validated=False, completed=False)
    try:
        p2.clone(args.base, args.output)
        share = args.output / 'share'
        share.mkdir(mode=0o755)
        for name in ['phase2-guest.py', 'phase4_guest.py']:
            shutil.copyfile(p2.HERE / name, share / name)
        shutil.copytree(MATRIX.parent, share / 'fixtures')
        if args.fixture_binaries:
            binaries = json.loads((args.fixture_binaries / 'manifest.json').read_text())
            p2.require(set(binaries) == {'source_sha256', 'binaries'}
                       and binaries['source_sha256'] == p2.digest(MATRIX.parent / 'vulkan-workload.c'),
                       'prebuilt Vulkan fixture source changed')
            p2.require(set(binaries['binaries']) <= {'vulkan64', 'vulkan32'}
                       and binaries['binaries'], 'unexpected prebuilt fixture')
            for name, expected in binaries['binaries'].items():
                source = args.fixture_binaries / name
                p2.require(source.is_file() and not source.is_symlink() and p2.digest(source) == expected,
                           'prebuilt fixture hash mismatch')
                shutil.copyfile(source, share / 'fixtures' / name)
                (share / 'fixtures' / name).chmod(0o755)
            shutil.copyfile(args.fixture_binaries / 'manifest.json', share / 'fixtures/prebuilt.json')
        p2.save(args.output / 'inputs.json', dict(source_commit=args.source_commit,
            harness_commit=p2.host(['git', '-C', p2.REPO, 'rev-parse', 'HEAD']).strip(),
            harness_dirty=bool(p2.host(['git', '-C', p2.REPO, 'status', '--porcelain']).strip()),
            firmware=dict(path=str(args.ovmf_code), sha256=p2.digest(args.ovmf_code)),
            qemu=p2.host(['qemu-system-x86_64', '--version']),
            files={str(p.relative_to(p2.REPO)): p2.digest(p) for p in
                   [Path(__file__), p2.HERE / 'phase4_guest.py', p2.HERE / 'phase2.py',
                    p2.HERE / 'qmp.py', p2.HERE.parent / 'install-smoke.py',
                    *MATRIX.parent.iterdir()] if p.is_file()},
            share_files={str(p.relative_to(share)): p2.digest(p) for p in share.rglob('*') if p.is_file()}))
        # QEMU traverses the share as root; the desktop reads only public fixture files.
        vm = p2.VM(args.output, args.ovmf_code, share, args.timeout, secure_boot=True)
        vm.start()
        vm.ready()
        if args.autologin:
            vm.command('test -e /dev/virtio-ports/org.astraeus.validation; '
                       'mkdir -p /etc/sddm.conf.d; '
                       f'printf %s {shlex.quote("[Autologin]\nUser=" + args.user + "\nSession=plasma.desktop\n")} '
                       '> /etc/sddm.conf.d/99-phase4-validation.conf; systemctl restart sddm; '
                       f'for attempt in $(seq 1 60); do if pgrep -u {args.user} -x plasmashell >/dev/null; '
                       'then exit 0; fi; sleep 1; done; echo "Plasma startup timed out" >&2; exit 1',
                       timeout=75, label='disposable-autologin')
        state = p2.observe(vm, 'before')
        p2.healthy(state, manifest['encryption'])
        security = vm.command('distroctl security status --json', label='security')
        trust = json.loads(security['output'])
        p2.require(trust['firmware']['SecureBoot'] is True and trust['firmware']['SetupMode'] is False
                   and trust['identity'] == 'valid' and trust['certificate_sha256'] == manifest['signer_sha256'],
                   'guest firmware trust changed')
        for name in ['bootloader', 'fallback_bootloader']:
            p2.require(trust['artifacts'][name]['signature'] == 'valid-for-configured-certificate', 'invalid loader')
        vm.command('distroctl boot status --json', label='generations')
        command = ['python3', '/mnt/astraeus-validation/phase4_guest.py', '--user', args.user]
        for option in ['proton', 'runtime']:
            if getattr(args, option):
                command += ['--' + option, getattr(args, option)]
        guest = json.loads(vm.command(shlex.join(command), timeout=600, label='graphics-suite')['output'])
        guest['checks'].update(hooks(vm, args.hooks))
        p2.save(args.output / 'guest.json', guest)
        report = matrix('nested Astraeus KVM baseline', dict(qemu_device='virtio-vga',
                        physical_passthrough=False, desktop=guest['desktop'],
                        renderer=guest['checks'].get('vulkan-64', {}).get('renderer')), guest['checks'])
        report['observed_boot'] = dict(status='PASS', scope='sealed baseline cold boot, not a fresh Phase 4 install',
                                       evidence_path='before.json', boot_id=vm.boot_id)
        report['observed_secure_boot'] = dict(status='PASS', scope='trusted cold boot only; negative refusal not rerun',
                                              evidence_path=str(vm.session.relative_to(args.output)) + '/security')
        after = p2.observe(vm, 'after')
        p2.healthy(after, manifest['encryption'])
        for name in ['packages', 'history', 'snapshots']:
            p2.require(p2.value(state, name) == p2.value(after, name), f'probe unexpectedly changed {name}')
        vm.shutdown()
        receipt['completed'] = True
    except BaseException as error:
        receipt['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        try:
            if vm:
                vm.stop()
            p2.verify_baseline(args.base)
        except BaseException as error:
            receipt.update(completed=False, cleanup_error=str(error))
            raise
        finally:
            receipt['finished'] = p2.now()
            p2.save(args.output / 'matrix.json', report)
            p2.save(args.output / 'result.json', receipt)
            p2.save(args.output / 'artifact-sha256.json', {name: p2.digest(args.output / name)
                     for name in ['disk.qcow2', 'vars.fd'] if (args.output / name).is_file()})
            p2.save(args.output / 'evidence-sha256.json', {str(p.relative_to(args.output)): p2.digest(p)
                for p in args.output.rglob('*') if p.is_file() and p.name not in
                ['evidence-sha256.json', 'disk.qcow2', 'vars.fd']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['matrix', 'run'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base', type=Path)
    parser.add_argument('--ovmf-code', type=Path)
    parser.add_argument('--source-commit')
    parser.add_argument('--user', default='tester')
    parser.add_argument('--autologin', action='store_true',
                        help='prepare disposable overlay SDDM session; never qualifies login security')
    parser.add_argument('--proton', help='inspected guest Proton script path')
    parser.add_argument('--runtime', help='inspected guest Steam Linux Runtime _v2-entry-point path')
    parser.add_argument('--hooks', type=Path, help='guest-only production CLI negative/readiness hooks')
    parser.add_argument('--fixture-binaries', type=Path, help='source/hash-bound prebuilt Vulkan binaries and manifest.json')
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    if args.mode == 'matrix':
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(matrix(), stream, indent=2)
            stream.write('\n')
    else:
        if not all([args.base, args.ovmf_code, args.source_commit]):
            parser.error('run requires --base, --ovmf-code and --source-commit')
        run(args)


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise InterruptedError(f'validation interrupted by signal {signum}')

    signal.signal(signal.SIGTERM, interrupted)
    main()
