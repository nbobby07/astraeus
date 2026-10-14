#!/usr/bin/env python3
"""Candidate-only Phase 4.2 KVM lifecycle evidence. Missing gates never become passes."""
import argparse
import copy
from importlib import import_module
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import sys
import time
import uuid

import phase2 as p2
from phase42_trust import verify_maintained_uki

GATES = {
    'candidate-identity': 'Fresh candidate source, ISO, firmware and installed binary identities agree',
    'readonly-user': 'Ordinary-user observations and planning leave package/configuration/history state unchanged',
    'invalid-configuration': 'Malformed, duplicate, unsupported and unsafe requests are rejected without mutation',
    'unprivileged-submit': 'Direct unauthenticated submission cannot start a root operation',
    'stale-plan': 'A different reviewed-plan digest is rejected without mutation',
    'install-plan': 'The selected approved package resolves to an executable complete installation plan',
    'install-transaction': 'The worker applies the reviewed package set after a snapshot and stops at awaiting_boot',
    'pending-boot-block': 'A second request cannot mutate the system while boot confirmation is pending',
    'install-confirmation': 'A different healthy boot verifies the installed package and desired configuration',
    'remove-transaction': 'Removing the managed choice removes its package through the same coordinator',
    'remove-confirmation': 'Another healthy boot verifies removal and restored desired configuration',
    'history-and-home': 'Pre/post snapshots and complete history remain, while home test data survives',
    'fresh-install-plain': 'Fresh candidate installs and authenticates on plain Btrfs',
    'fresh-install-luks2': 'Fresh candidate installs and authenticates on LUKS2/Btrfs',
    'image-reproducibility': 'Two independent clean builds produce identical candidate ISO bytes',
    'live-readonly': 'Packaged GUI and CLI refuse mutation from live media',
    'dependency-ownership': 'Shared dependencies, explicit choices and externally changed packages remain safe',
    'resolver-conflicts': 'Conflicts, replacements and ambiguous providers expose the complete reviewed outcome',
    'signature-and-provenance': 'Tampered/unsigned packages and changed repository provenance are rejected',
    'protected-packages': 'Protected base, bootloader, graphics transitions and coordinator changes are refused',
    'worker-interruption': 'Killed worker leaves a visible durable failure or recovery-required state without replay',
    'failed-hooks-and-space': 'Failed package hooks, health checks and capacity failures preserve recovery evidence',
    'offline-recovery': 'Deliberate offline rollback restores packages, ownership, configuration and signed boot state',
    'gui-polkit': 'Packaged native GUI authenticates through the real desktop polkit agent',
    'gui-close-survival': 'Accepted mutation survives closing the native GUI and reconnects on reopening',
    'gui-crash-survival': 'Accepted mutation survives a GUI crash and reconnects on reopening',
    'signed-boot-generations': 'Secure Boot remains enforcing across candidate install, removal and recovery',
    'image-key-audit': 'Candidate media and repository contain no private signing keys',
}
TERMINAL = {'succeeded', 'awaiting_boot', 'failed', 'rollback_required', 'rolled_back', 'rejected'}


def matrix():
    return {'schema_version': 1, 'qualified': False, 'physical_hardware_qualified': False,
            'scenarios': [{'id': name, 'expected': expected, 'status': 'NOT RUN', 'evidence': [],
                           'detail': 'Not executed by this run'} for name, expected in GATES.items()]}


def candidate_matches(manifest, source, image, firmware, encryption):
    inputs = manifest.get('inputs', {})
    revisions = inputs.get('source_commits', [])
    if manifest.get('source_commit'):
        revisions = revisions + [manifest['source_commit']]
    p2.require(manifest.get('accepted') is True, 'candidate baseline must already be sealed')
    p2.require(source in revisions, 'baseline source is not this candidate; do not reuse older qualification')
    p2.require(inputs.get('iso', {}).get('sha256') == image, 'baseline ISO is not this candidate')
    p2.require(inputs.get('ovmf_code', {}).get('sha256') == firmware, 'baseline firmware CODE changed')
    p2.require(manifest.get('encryption') == encryption, 'baseline encryption does not match this run')


def json_command(vm, arguments, payload=None, user=None, label='system-json', check=True):
    command = shlex.join(['/usr/bin/distroctl', *arguments])
    if user:
        command = shlex.join(['/usr/bin/runuser', '-u', user, '--']) + ' ' + command
    if payload is not None:
        text = payload if isinstance(payload, str) else json.dumps(payload, separators=(',', ':'))
        command = "printf '%s' " + shlex.quote(text) + ' | ' + command
    reply = vm.command(command, timeout=120, label=label, check=check)
    if reply['code'] != 0:
        return reply, None
    value = json.loads(reply['output'])
    if arguments[0] not in {'history', 'snapshot'}:
        p2.require(isinstance(value, dict) and value.get('schema_version') == 1, 'unsupported system JSON schema')
    return reply, value


def observed_state(vm, label):
    _, status = json_command(vm, ['system', 'status', '--json'], label=label + '-status')
    _, history = json_command(vm, ['history', '--json'], label=label + '-history')
    packages = vm.command('LC_ALL=C pacman -Q | LC_ALL=C sort', label=label + '-packages')['output']
    reasons = vm.command('LC_ALL=C pacman -Qqe | LC_ALL=C sort', label=label + '-reasons')['output']
    return {'configuration': status['configuration'], 'packages': packages, 'explicit': reasons, 'history': history}


def wait_operation(vm, operation_id, timeout):
    p2.require(re.fullmatch('[0-9a-f]{32}', operation_id), 'invalid submitted operation identifier')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, result = json_command(vm, ['system', 'operation', operation_id, '--json'], label='operation-' + operation_id)
        if result.get('state') in TERMINAL:
            return result
        time.sleep(2)
    raise TimeoutError('worker did not reach a terminal receipt state')


def submit(vm, config, plan_id, timeout, label='submit'):
    reply, result = json_command(vm, ['system', 'submit', '--json'],
                                 {'schema_version': 1, 'config': config, 'expected_plan': plan_id},
                                 label=label, check=False)
    if result is None:
        return reply, None
    operation = wait_operation(vm, result['operation_id'], timeout)
    # A terminal receipt can precede ExecStopPost and release of the worker's locks.
    import_module('phase42-faults').wait_worker_exit(vm, result['operation_id'], timeout)
    return reply, operation


def installed_trust(vm, manifest, label):
    trust = verify_maintained_uki(
        lambda *args: vm.command(shlex.join(args), label=label + '-trust')['output'],
        manifest['signer_sha256'])
    p2.save(vm.session / (label + '-trust.json'), dict(boot_id=vm.boot_id, **trust))
    return trust


def check_transaction(record, expected_kind, package):
    p2.require(record.get('state') == 'awaiting_boot', 'package mutation was not left awaiting boot')
    changes = record.get('plan', {}).get('packages', {}).get('changes', [])
    p2.require(any(change.get('kind') == expected_kind and change.get('name') == package for change in changes),
               'transaction does not contain the intended package change')
    phases = [event['state'] for event in record.get('events', [])]
    p2.require('snapshot_created' in phases and 'applying' in phases
               and phases.index('snapshot_created') < phases.index('applying'), 'mutation lacks prior snapshot evidence')
    p2.require(record.get('snapshot') and record.get('post_snapshot'), 'transaction lacks paired recovery snapshots')
    p2.require(record.get('boot_regenerated') is True, 'transaction did not regenerate its boot artifact')
    p2.require(record.get('plan', {}).get('management'), 'transaction lacks configuration and ownership evidence')


def confirmed(vm, transaction_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, records = json_command(vm, ['history', '--json'], label='boot-confirmation-history')
        matching = [record for record in records if record['id'] == transaction_id]
        p2.require(len(matching) == 1, 'transaction history identity changed')
        record = matching[0]
        if record['state'] == 'succeeded':
            confirmation = record.get('confirmation') or {}
            p2.require(confirmation.get('boot_id') and confirmation['boot_id'] != record.get('update_boot_id')
                       and not confirmation.get('error') and confirmation.get('snapshot') == record['post_snapshot'],
                       'success lacks matching evidence from a new boot')
            return record
        p2.require(record['state'] == 'awaiting_boot', 'transaction failed during boot confirmation')
        time.sleep(2)
    raise TimeoutError('boot confirmation did not succeed')


def run(args):
    p2.require(args.secure_boot, 'Phase 4.2 acceptance requires enforcing Secure Boot')
    p2.require(sys.platform == 'linux' and Path('/dev/kvm').exists() and os.geteuid() == 0,
               'run only as root on a disposable Linux KVM validator')
    p2.require(re.fullmatch('[0-9a-f]{40}', args.source_commit), 'full candidate source commit required')
    for value in [args.image_sha256, args.distroctl_sha256, args.desktop_sha256]:
        p2.require(re.fullmatch('[0-9a-f]{64}', value), 'candidate SHA256 must contain 64 lowercase hex digits')
    p2.require(re.fullmatch('[a-z_][a-z0-9_-]*', args.user) and args.user != 'root', 'ordinary installed user required')
    p2.require(re.fullmatch('[a-z0-9][a-z0-9@._+-]{0,127}', args.package), 'invalid nominated repository package')
    p2.require(60 <= args.timeout <= 3600, 'timeout must be 60..3600 seconds')
    args.base, args.output, args.ovmf_code = map(p2.safe_path, [args.base, args.output, args.ovmf_code])
    manifest = p2.verify_baseline(args.base)
    candidate_matches(manifest, args.source_commit, args.image_sha256, p2.digest(args.ovmf_code), args.encryption)
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    report = matrix()
    report.update(started=p2.now(), encryption=args.encryption, candidate_source=args.source_commit,
                  candidate_iso_sha256=args.image_sha256, requested_run_passed=False,
                  secure_boot_requested=args.secure_boot)
    rows = {row['id']: row for row in report['scenarios']}
    vm = None

    def gate(name, function):
        row = rows[name]
        row['started'] = p2.now()
        row['evidence'] = [f'boot-{vm.number}/']
        try:
            value = function()
            row.update(status='PASS', detail='Observed assertions passed')
            return value
        except BaseException as error:
            row.update(status='FAIL', detail=f'{type(error).__name__}: {error}')
            raise
        finally:
            row['finished'] = p2.now()
            p2.save(args.output / 'matrix.json', report)

    try:
        p2.clone(args.base, args.output)
        share = args.output / 'share'
        share.mkdir()
        shutil.copyfile(p2.HERE / 'phase2-guest.py', share / 'phase2-guest.py')
        p2.save(args.output / 'inputs.json', {
            'source_commit': args.source_commit, 'iso_sha256': args.image_sha256,
            'distroctl_sha256': args.distroctl_sha256, 'desktop_sha256': args.desktop_sha256,
            'baseline': manifest, 'package': args.package,
            'harness_sha256': {name: p2.digest(p2.HERE / name) for name in
                               ['phase42.py', 'phase2.py', 'qmp.py', 'phase42-faults.py', 'phase42_trust.py']}})
        vm = p2.VM(args.output, args.ovmf_code, share, args.timeout, secure_boot=args.secure_boot)
        vm.start()
        print('If encrypted, unlock this disposable guest through its private QMP console.', flush=True)
        vm.ready()

        def identity():
            for binary, expected in [('distroctl', args.distroctl_sha256), ('astraeus-control-center', args.desktop_sha256)]:
                actual = vm.command('sha256sum ' + shlex.quote('/usr/bin/' + binary), label='candidate-' + binary)['output'].split()[0]
                p2.require(actual == expected, 'installed candidate binary differs: ' + binary)
            _, status = json_command(vm, ['system', 'status', '--json'], user=args.user, label='candidate-status')
            p2.require(status.get('live') is False and not status.get('reboot_required') and not status.get('drift'),
                       'baseline is live, pending a reboot, or has configuration drift')
            health = p2.observe(vm, 'candidate-health')
            p2.healthy(health, args.encryption)
            installed_trust(vm, manifest, 'candidate')
            return status
        status = gate('candidate-identity', identity)
        original = copy.deepcopy(status['configuration'])
        p2.require(args.package not in original['packages'], 'choose an initially absent package')
        _, details = json_command(vm, ['system', 'packages', 'details', args.package, '--json'], label='package-details')
        matches = [item for item in details['packages'] if item['name'] == args.package]
        p2.require(len(matches) == 1 and not matches[0].get('installed_version') and not matches[0].get('protected'),
                   'nominated package must be available, initially absent, and unprotected')
        desired = copy.deepcopy(original)
        desired['packages'] = sorted([*desired['packages'], args.package])
        initial = observed_state(vm, 'initial')

        def readonly():
            for arguments in [['system', 'status', '--json'], ['system', 'features', '--json'],
                              ['system', 'packages', 'installed', '--json'], ['system', 'export', '--json']]:
                json_command(vm, arguments, user=args.user, label='ordinary-user-' + arguments[1])
            json_command(vm, ['system', 'plan', '--stdin', '--json'], desired, args.user, label='ordinary-user-plan')
            p2.require(observed_state(vm, 'readonly-after') == initial, 'read-only commands changed system state')
        gate('readonly-user', readonly)

        def invalid():
            for index, text in enumerate(['not = [valid', 'schema_version=1\nunknown=true',
                                         'schema_version=1\npackages=["hello","hello"]',
                                         'schema_version=1\npackages=["../escape"]',
                                         'schema_version=1\ngaming=["heroic"]']):
                reply, _ = json_command(vm, ['system', 'parse', '--stdin', '--json'], text,
                                        args.user, label=f'invalid-config-{index}', check=False)
                p2.require(reply['code'] != 0 and reply['output'].strip(), 'invalid configuration was accepted or lacked diagnostics')
            p2.require(observed_state(vm, 'invalid-after') == initial, 'invalid configuration changed system state')
        gate('invalid-configuration', invalid)

        def installation_plan():
            _, plan = json_command(vm, ['system', 'plan', '--stdin', '--json'], desired, args.user, label='install-plan')
            p2.require(plan.get('executable') is True and not plan.get('blockers'), 'installation plan is blocked')
            p2.require(re.fullmatch('sha256:[0-9a-f]{64}', plan.get('plan_id', '')), 'reviewed plan fingerprint missing')
            p2.require(any(item.get('kind') == 'install' and item.get('name') == args.package
                           for item in plan['plan']['packages']['changes']), 'plan does not install nominated package')
            p2.save(args.output / 'install-plan.json', plan)
            return plan
        plan = gate('install-plan', installation_plan)

        def unprivileged():
            reply, _ = json_command(vm, ['system', 'submit', '--json'],
                                    {'schema_version': 1, 'config': desired, 'expected_plan': plan['plan_id']},
                                    args.user, label='unauthenticated-submit', check=False)
            p2.require(reply['code'] != 0, 'ordinary direct command unexpectedly submitted root work')
            p2.require(observed_state(vm, 'unprivileged-after') == initial, 'unprivileged command changed system state')
        gate('unprivileged-submit', unprivileged)

        def stale():
            bad = plan['plan_id'][:-1] + ('0' if plan['plan_id'][-1] != '0' else '1')
            reply, operation = submit(vm, desired, bad, args.timeout, 'stale-plan-submit')
            p2.require(reply['code'] != 0 or operation['state'] in {'failed', 'rejected'}, 'stale plan unexpectedly executed')
            p2.require(observed_state(vm, 'stale-after') == initial, 'stale plan changed system state')
        gate('stale-plan', stale)
        marker = uuid.uuid4().hex
        marker_path = f'/home/{args.user}/.astraeus-phase42-{marker}'
        vm.command("printf '%s' " + shlex.quote(marker) + ' > ' + shlex.quote(marker_path), label='home-sentinel')

        def change(config, fingerprint, kind):
            reply, operation = submit(vm, config, fingerprint, args.timeout, kind + '-submit')
            p2.require(reply['code'] == 0 and operation['state'] == 'awaiting_boot', 'worker did not finish at awaiting_boot')
            record = operation.get('transaction')
            p2.require(isinstance(record, dict), 'worker receipt lacks transaction evidence')
            check_transaction(record, kind, args.package)
            p2.save(args.output / (kind + '-operation.json'), operation)
            return record
        installed = gate('install-transaction', lambda: change(desired, plan['plan_id'], 'install'))

        def pending():
            before = observed_state(vm, 'pending-before')
            reply, operation = submit(vm, desired, plan['plan_id'], args.timeout, 'pending-boot-submit')
            p2.require(reply['code'] != 0 or operation['state'] in {'failed', 'rejected'}, 'pending boot did not block another operation')
            p2.require(observed_state(vm, 'pending-after') == before, 'blocked second request changed system state')
        gate('pending-boot-block', pending)

        def reboot_check(record, config, present):
            vm.reboot()
            installed_trust(vm, manifest, 'confirmation-' + str(record['id']))
            confirmed(vm, record['id'], min(args.timeout, 180))
            _, actual = json_command(vm, ['system', 'status', '--json'], label='confirmed-configuration')
            p2.require(actual['configuration'] == config and not actual.get('reboot_required') and not actual.get('drift'),
                       'boot-confirmed configuration differs or is still pending')
            check = vm.command('pacman -Q ' + shlex.quote(args.package), label='confirmed-package', check=False)
            p2.require((check['code'] == 0) is present, 'confirmed package presence is wrong')
            p2.healthy(p2.observe(vm, 'confirmed-health-' + str(record['id'])), args.encryption)
        gate('install-confirmation', lambda: reboot_check(installed, desired, True))
        _, remove = json_command(vm, ['system', 'plan', '--stdin', '--json'], original, args.user, label='remove-plan')
        p2.require(remove.get('executable') is True, 'removal plan is blocked')
        removed = gate('remove-transaction', lambda: change(original, remove['plan_id'], 'remove'))
        gate('remove-confirmation', lambda: reboot_check(removed, original, False))

        def retention():
            p2.require(vm.command('cat ' + shlex.quote(marker_path), label='retained-home-sentinel')['output'] == marker,
                       'home test data changed across transactions or reboots')
            _, history = json_command(vm, ['history', '--json'], label='retained-history')
            _, snapshots = json_command(vm, ['snapshot', 'list', '--json'], label='retained-snapshots')
            # Snapshot CLI predates the system command envelope and returns an array.
            identifiers = {item['id'] for item in snapshots}
            p2.require({installed['id'], removed['id']} <= {item['id'] for item in history}, 'transaction history disappeared')
            for record in [installed, removed]:
                p2.require(record['snapshot'] in identifiers and record['post_snapshot'] in identifiers,
                           'transaction snapshot disappeared')
        gate('history-and-home', retention)
        vm.shutdown()
        report['requested_run_passed'] = True
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if vm:
            vm.stop()
        try:
            p2.verify_baseline(args.base)
        finally:
            report['finished'] = p2.now()
            p2.save(args.output / 'matrix.json', report)
            p2.save(args.output / 'evidence-sha256.json', {str(path.relative_to(args.output)): p2.digest(path)
                for path in args.output.rglob('*') if path.is_file() and path.suffix not in {'.qcow2', '.fd'}
                and path.name != 'evidence-sha256.json'})
            print('Evidence retained: ' + str(args.output), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    template = commands.add_parser('matrix')
    template.add_argument('--output', type=Path, required=True)
    lifecycle = commands.add_parser('run')
    for name in ['base', 'output', 'ovmf-code']:
        lifecycle.add_argument('--' + name, type=Path, required=True)
    for name in ['source-commit', 'image-sha256', 'distroctl-sha256', 'desktop-sha256', 'package', 'user']:
        lifecycle.add_argument('--' + name, required=True)
    lifecycle.add_argument('--encryption', choices=['none', 'LUKS2'], required=True)
    lifecycle.add_argument('--secure-boot', action='store_true')
    lifecycle.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    if args.command == 'matrix':
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(matrix(), stream, indent=2)
            stream.write('\n')
    else:
        run(args)


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise InterruptedError(f'Phase 4.2 validation interrupted by signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    main()
