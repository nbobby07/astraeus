#!/usr/bin/env python3
"""Actual candidate recovery-media boots, using private OVMF copies and no OS disk."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid

import phase2 as p2
import phase42
from phase3 import signature_certificates
from phase3_guest import section_offset

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('recovery_builder', HERE / 'phase42-recovery.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
MODES = ['trusted', 'untrusted', 'tampered', 'unsigned', 'root-tampered', 'disabled']
VERIFIED = 'ASTRAEUS_SECURE_LIVE_OK: SecureBoot=1 SetupMode=0 rootfs=verified-in-RAM'
REFUSED = 'ASTRAEUS_SECURE_LIVE_REFUSED: verification or required boot step failed; powering off.'
DESKTOP = 'DISTRO_BOOT_OK: uefi plasma wayland pipewire networkmanager distroctl'


def observed_verdict(mode, serial):
    p2.require(mode in MODES, 'unknown recovery test case')
    if mode == 'trusted':
        return VERIFIED in serial and DESKTOP in serial and REFUSED not in serial
    if mode in ['root-tampered', 'disabled']:
        return REFUSED in serial and VERIFIED not in serial and DESKTOP not in serial
    return ('Access Denied' in serial or 'Security Violation' in serial) and all(
        text not in serial for text in ['Linux version', VERIFIED, REFUSED, DESKTOP])


def media_command(original, image, ram, *values, **options):
    result = original(*values, **options)
    disk = next(item for item in result if item.startswith('if=none,id=osdisk,'))
    result[result.index(disk)] = f'if=none,id=osdisk,format=raw,readonly=on,file={image}'
    controller = result.index('qemu-xhci')
    del result[controller - 1:controller + 1]
    device = next(item for item in result if item.startswith('virtio-blk-pci,drive=osdisk,'))
    at = result.index(device) - 1
    result[at:at + 2] = ['-device', 'qemu-xhci', '-device', 'usb-storage,drive=osdisk,bootindex=1']
    result[result.index('-m') + 1] = str(ram * 1024)
    p2.require(not any('format=qcow2' in item for item in result), 'media-only check must never attach an OS disk')
    return result


def mutate(build, out, mode, certificate):
    image = build / 'recovery.img'
    if mode not in ['tampered', 'unsigned', 'root-tampered']:
        return image, None
    variant = out / 'variant.img'
    p2.host(['cp', '--reflink=auto', '--sparse=always', image, variant], timeout=600)
    fat = str(variant) + '@@1048576'
    if mode == 'root-tampered':
        source, member = out / 'bad.sfs', '::/arch/x86_64/airootfs.sfs'
        p2.host(['mcopy', '-i', fat, member, source], timeout=600)
        p2.require(source.stat().st_size > 1024 * 1024, 'root filesystem too small for the nominated fault')
        offset = 1024 * 1024
        with source.open('r+b') as stream:
            stream.seek(offset)
            byte = stream.read(1)
            stream.seek(offset)
            stream.write(bytes([byte[0] ^ 1]))
    else:
        source, member = out / 'bad.efi', '::/EFI/BOOT/BOOTX64.EFI'
        shutil.copyfile(build / ('live-unsigned.efi' if mode == 'unsigned' else 'BOOTX64.EFI'), source)
        offset = None
        if mode == 'tampered':
            data = bytearray(source.read_bytes())
            offset = section_offset(data, b'.linux')
            data[offset] ^= 1
            source.write_bytes(data)
        verification = subprocess.run(['sbverify', '--cert', str(certificate), str(source)], capture_output=True, text=True)
        p2.save(out / 'fixture-signature.json', dict(code=verification.returncode,
                stdout=verification.stdout, stderr=verification.stderr))
        p2.require(verification.returncode == 1, 'negative UKI fixture was not rejected by signature verification')
    p2.host(['mcopy', '-o', '-i', fat, source, member], timeout=600)
    p2.require(builder.copied_digest(fat, member) == p2.digest(source), 'negative fixture differs from assembled media')
    mutation = dict(mode=mode, member=member, byte_offset=offset, payload_sha256=p2.digest(source),
                    image_sha256=p2.digest(variant), image_bytes=variant.stat().st_size)
    p2.save(out / 'mutation.json', mutation)
    return variant, source


def runtime_identity(vm, manifest, certificate):
    firmware = json.loads(vm.command('''python3 - <<'PY'
import json,pathlib
root=pathlib.Path('/sys/firmware/efi/efivars')
result={}
for name in ['SecureBoot','SetupMode','db']:
    paths=list(root.glob(name+'-*'))
    assert len(paths)==1
    result[name]=paths[0].read_bytes()[4:].hex()
print(json.dumps(result))
PY''', label='actual-recovery-firmware')['output'])
    p2.require(firmware['SecureBoot'] == '01' and firmware['SetupMode'] == '00', 'actual recovery firmware is not enforcing')
    p2.require(signature_certificates(bytes.fromhex(firmware['db'])) == [certificate], 'actual firmware db is not the baseline owner')
    for path, expected in [('/usr/bin/distroctl', manifest['distroctl_sha256']),
                           ('/usr/bin/astraeus-control-center', manifest['desktop_sha256']),
                           ('/run/archiso/copytoram/airootfs.sfs', manifest['rootfs_sha256'])]:
        value = vm.command('sha256sum ' + path, timeout=180, label='actual-' + Path(path).name)['output'].split()
        p2.require(len(value) == 2 and value[0] == expected, 'booted recovery identity differs: ' + path)
    vm.command('test -d /run/archiso; test "$(findmnt -rn -M / -o FSTYPE)" = overlay', label='ephemeral-live-root')
    return firmware


def management_fingerprint(vm, label):
    observed = phase42.observed_state(vm, label)
    observed['files'] = json.loads(vm.command('''python3 - <<'PY'
import hashlib,json,pathlib
result={}
for name in ['/etc/astraeus/system.toml','/var/lib/astraeus/management','/var/log/astraeus',
             '/run/astraeus','/run/astraeus-update.lock','/var/lib/pacman/db.lck']:
    root=pathlib.Path(name)
    candidates=[root,*root.rglob('*')] if root.is_dir() else [root]
    for path in candidates:
        if path.is_symlink(): result[str(path)]={'link':str(path.readlink())}
        elif path.is_file():
            with path.open('rb') as stream: result[str(path)]={'sha256':hashlib.file_digest(stream,'sha256').hexdigest()}
        elif path.is_dir(): result[str(path)]={'directory':True}
        else: result[str(path)]=None
print(json.dumps(result,sort_keys=True))
PY''', label=label + '-files')['output'])
    return observed


def live_cli(vm):
    before = management_fingerprint(vm, 'live-before')
    _, status = phase42.json_command(vm, ['system', 'status', '--json'], user='live', label='live-user-status')
    p2.require(status.get('live') is True and status.get('supported') is True, 'native live inspection is unavailable')
    _, features = phase42.json_command(vm, ['system', 'features', '--json'], user='live', label='live-user-features')
    _, packages = phase42.json_command(vm, ['system', 'packages', 'installed', '--json'], user='live', label='live-user-packages')
    p2.require(features.get('features') and packages.get('packages'), 'live inspection returned no feature/package catalog')
    config = {'schema_version': 1, 'packages': [], 'gaming': [], 'providers': {}}
    _, plan = phase42.json_command(vm, ['system', 'plan', '--stdin', '--json'], config, 'live', label='live-user-plan')
    p2.require(plan.get('executable') is False and any('live' in blocker.lower() for blocker in plan.get('blockers', [])),
               'live plan did not expose its mutation blocker')
    # A syntactically valid root request must still stop at the live guard. The
    # fallback digest never grants review approval when planning has no plan ID.
    expected_plan = plan.get('plan_id') or 'sha256:' + '0' * 64
    reply, _ = phase42.json_command(vm, ['system', 'submit', '--json'],
             {'schema_version': 1, 'config': config, 'expected_plan': expected_plan},
             label='live-root-submit-refusal', check=False)
    p2.require(reply['code'] != 0 and 'live sessions cannot apply' in reply['output'],
               'privileged live request was not refused by the explicit live guard')
    after = management_fingerprint(vm, 'live-after')
    p2.require(after == before, 'live CLI inspection/refusal changed package, management, history or operation state')
    return {'passed': True, 'status': status, 'plan': plan, 'before': before, 'after': after}


def validate_gui_receipt(receipt, manifest, source):
    p2.require(isinstance(receipt, dict) and type(receipt.get('schema_version')) is int and receipt.get('schema_version') == 1
               and receipt.get('source_commit') == source and receipt.get('live') is True
               and receipt.get('distroctl_sha256') == manifest['distroctl_sha256']
               and receipt.get('desktop_sha256') == manifest['desktop_sha256']
               and receipt.get('firmware') == {'SecureBoot': True, 'SetupMode': False},
               'GUI evidence does not belong to this enforcing candidate live session')
    checks = receipt.get('checks', {})
    p2.require(all(checks.get(name) is True for name in
               ['inspection_visible', 'live_warning_visible', 'review_blocked', 'apply_disabled']),
               'visible Control Center inspection/refusal checks did not pass')
    evidence = receipt.get('evidence')
    p2.require(isinstance(evidence, list) and evidence, 'GUI receipt needs actual screenshot/observation evidence')
    for item in evidence:
        p2.require(isinstance(item, dict) and isinstance(item.get('path'), str)
                   and not Path(item['path']).is_absolute() and '..' not in Path(item['path']).parts,
                   'GUI evidence must stay inside this test output')
        builder.identity(item.get('sha256'))


def wait_for_gui(vm, args, manifest):
    complete = args.output / 'gui-complete.json'
    before = management_fingerprint(vm, 'gui-before')
    p2.save(args.output / 'attention.json', dict(stage='trusted-recovery-gui', qmp=str(vm.monitor),
            channel=str(vm.channel), complete_file=str(complete), source_commit=args.source_commit,
            distroctl_sha256=manifest['distroctl_sha256'], desktop_sha256=manifest['desktop_sha256']))
    print('Trusted live identity/CLI checks passed. Waiting for visible Control Center evidence in gui-complete.json.', flush=True)
    deadline = time.monotonic() + args.timeout
    while not complete.exists():
        vm.alive()
        p2.require(time.monotonic() < deadline, 'visible live GUI evidence was not supplied; no GUI acceptance claimed')
        time.sleep(1)
    builder.regular(complete)
    p2.require(complete.stat().st_uid == 0 and complete.stat().st_size <= 256 * 1024,
               'GUI completion receipt must be bounded and written by the root validation controller')
    receipt = json.loads(complete.read_text())
    validate_gui_receipt(receipt, manifest, args.source_commit)
    for item in receipt['evidence']:
        path = (args.output / item['path']).resolve(strict=True)
        p2.require(path.is_relative_to(args.output) and path.is_file() and not path.is_symlink()
                   and p2.digest(path) == item['sha256'], 'GUI evidence file changed or escaped the output')
    p2.require(management_fingerprint(vm, 'gui-after') == before, 'live GUI inspection/refusal changed managed system state')
    return receipt


def run(args):
    p2.require(os.name == 'posix' and os.geteuid() == 0 and Path('/dev/kvm').exists(), 'disposable root KVM validator required')
    for name in ['build', 'baseline', 'output', 'ovmf_code', 'pristine_vars']:
        setattr(args, name, p2.safe_path(getattr(args, name)))
    p2.require(60 <= args.timeout <= 1800, 'timeout must be 60..1800 seconds')
    baseline = json.loads((args.baseline / 'baseline.json').read_text())
    pin, cli = builder.baseline_identity(baseline, args.source_commit, args.iso_sha256)
    manifest = json.loads((args.build / 'manifest.json').read_text())
    p2.require(manifest.get('schema_version') == 1 and manifest.get('kind') == 'phase42-ram-verified-recovery'
               and manifest.get('source_commit') == args.source_commit and manifest.get('iso_sha256') == args.iso_sha256
               and manifest.get('certificate_sha256') == pin and manifest.get('distroctl_sha256') == cli
               and manifest.get('desktop_sha256') == baseline['installed_binaries']['astraeus-control-center']
               and manifest.get('baseline_manifest_sha256') == p2.digest(args.baseline / 'baseline.json')
               and manifest.get('image') == 'recovery.img', 'recovery medium is not bound to this candidate baseline')
    p2.require(manifest['image_sha256'] == p2.digest(args.build / 'recovery.img'), 'recovery media changed')
    p2.require(manifest.get('uki_sha256') == p2.digest(args.build / 'BOOTX64.EFI')
               and manifest.get('unsigned_uki_sha256') == p2.digest(args.build / 'live-unsigned.efi'),
               'candidate signed/unsigned UKI fixture identity changed')
    p2.require(p2.digest(args.ovmf_code) == baseline['inputs']['ovmf_code']['sha256'], 'OVMF CODE differs from the accepted baseline')
    p2.require(p2.digest(args.baseline / 'vars.fd') == baseline['sha256']['vars.fd'], 'baseline VARS changed')
    p2.require(p2.digest(args.pristine_vars) == baseline['inputs']['pristine_ovmf_vars']['sha256'],
               'disabled/untrusted fixtures require the exact pristine baseline VARS input')
    certificate = (args.baseline / 'public-owner/db.cer').read_bytes()
    p2.require(hashlib.sha256(certificate).hexdigest() == pin, 'baseline public certificate changed')
    p2.require(type(manifest.get('minimum_ram_gib')) is int and 8 <= manifest['minimum_ram_gib'] <= 12, 'unexpected RAM budget')
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    out = args.output
    result = dict(schema_version=1, mode=args.mode, passed=False, source_commit=args.source_commit,
                  iso_sha256=args.iso_sha256, recovery_manifest=manifest, baseline_attached=False,
                  harness_sha256=p2.digest(__file__), started=p2.now())
    vm, variant_source = None, None
    try:
        variables = out / 'vars.fd'
        if args.mode == 'disabled':
            shutil.copyfile(args.pristine_vars, variables)
        elif args.mode == 'untrusted':
            other = args.baseline / 'public-owner/PK.crt'
            other_der = subprocess.check_output(['openssl', 'x509', '-in', str(other), '-outform', 'DER'])
            p2.require(hashlib.sha256(other_der).hexdigest() != pin, 'untrusted case requires a distinct owner')
            owner = str(uuid.uuid4())
            p2.host(['virt-fw-vars', '--input', args.pristine_vars, '--output', variables,
                     '--set-pk', owner, other, '--add-kek', owner, other, '--add-db', owner, other, '--secure-boot'])
        else:
            shutil.copyfile(args.baseline / 'vars.fd', variables)
        p2.host(['virt-fw-vars', '--input', variables, '--output-json', out / 'firmware-before.json'])
        image, variant_source = mutate(args.build, out, args.mode, args.baseline / 'public-owner/db.crt')
        share = out / 'share'
        share.mkdir(mode=0o700)
        shutil.copyfile(HERE / 'phase2-guest.py', share / 'phase2-guest.py')
        vm = p2.VM(out, args.ovmf_code, share, args.timeout, secure_boot=True)
        original = p2.install.qemu_command
        p2.install.qemu_command = lambda *values, **options: media_command(original, image, manifest['minimum_ram_gib'], *values, **options)
        try:
            vm.start()
        finally:
            p2.install.qemu_command = original
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            serial_path = vm.session / 'serial.log'
            serial = serial_path.read_text(errors='replace') if serial_path.exists() else ''
            if observed_verdict(args.mode, serial):
                break
            vm.alive()
            time.sleep(1)
        else:
            raise TimeoutError('no actual expected boot/refusal evidence; absence of boot is not a pass')
        if vm.child.poll() is None:
            vm.qmp_state('verdict')
            p2.qmp.execute(str(vm.monitor), {'execute': 'screendump', 'arguments': {'filename': str(out / 'screen.ppm')}})
        if args.mode == 'trusted':
            p2.save(out / 'attention.json', dict(stage='trusted-recovery-command-channel', qmp=str(vm.monitor),
                command='sudo mkdir -p /mnt/astraeus-validation; sudo mount -t 9p -o trans=virtio,ro acceptance /mnt/astraeus-validation; sudo systemd-run --unit=astraeus-live-validation python3 /mnt/astraeus-validation/phase2-guest.py serve'))
            print('Start the command channel from the real recovery desktop through private QMP; see attention.json.', flush=True)
            vm.ready()
            result['firmware'] = runtime_identity(vm, manifest, certificate)
            result['live_cli'] = live_cli(vm)
            result['live_gui'] = wait_for_gui(vm, args, manifest) if args.gui_handoff else {'status': 'NOT RUN'}
            vm.shutdown()
        elif args.mode in ['root-tampered', 'disabled']:
            p2.require(vm.child.wait(timeout=30) == 0, 'verification refusal did not power off the guest cleanly')
        result['passed'] = True
    except BaseException as error:
        result['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if vm:
            vm.stop()
            result['qemu_exit'] = vm.child.returncode if vm.child else None
        preserved = (p2.digest(args.build / 'recovery.img') == manifest['image_sha256']
                     and p2.digest(args.baseline / 'vars.fd') == baseline['sha256']['vars.fd'])
        if not preserved:
            result.update(passed=False, input_preservation_error=True)
        result['finished'] = p2.now()
        p2.save(out / 'result.json', result)
        if result['passed'] and variant_source is not None:
            # These paths were created exclusively by mutate, and their identities
            # remain in mutation.json. The original recovery medium is never deleted.
            variant_source.unlink()
            (out / 'variant.img').unlink()
        p2.save(out / 'evidence-sha256.json', {str(path.relative_to(out)): p2.digest(path)
                for path in out.rglob('*') if path.is_file() and path.suffix not in ['.img', '.fd']
                and path.name != 'evidence-sha256.json'})
        p2.require(preserved, 'validation changed original recovery media or accepted baseline VARS')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=MODES)
    for name in ['build', 'baseline', 'output', 'ovmf-code', 'pristine-vars']:
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ['source-commit', 'iso-sha256']:
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--gui-handoff', action='store_true', help='trusted case: wait for actual visible Control Center evidence before shutdown')
    args = parser.parse_args()
    p2.require(not args.gui_handoff or args.mode == 'trusted', 'GUI handoff requires the trusted enforcing live case')
    run(args)


if __name__ == '__main__':
    def interrupted(_signal, _frame):
        raise InterruptedError('recovery-media validation interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    main()
