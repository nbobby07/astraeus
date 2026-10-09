#!/usr/bin/env python3
"""Phase 3 test fixtures and enforcing OVMF probes; see docs/phase3-validation.md."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import time
import uuid

import phase2 as p2
from phase3_guest import section_offset

HERE = Path(__file__).resolve().parent
PROBE = p2.REPO / 'tests/fixtures/phase3/firmware-probe.c'
X509 = uuid.UUID('a5c059a1-94e4-4aa7-87b5-ab155c2bf072').bytes_le
REFUSED = '800000000000000f'  # EDK2 deny policy: EFI_ACCESS_DENIED plus the execution table.
CHECKPOINTS = ['uki-staging', 'boot-entry-staging', 'generation-activation',
               'health-confirmation', 'rollback-preparation']


def execute(out, command, timeout=120, check=True):
    """Record actual host exit codes, including failed fixture commands."""
    command = [str(x) for x in command]
    path = out / f'host-{len(list(out.glob("host-*.json"))) + 1:03d}.json'
    started = p2.now()
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        p2.save(path, dict(command=command, started=started, finished=p2.now(), code=None,
                           error=f'timeout after {timeout}s'))
        raise
    p2.save(path, dict(command=command, started=started, finished=p2.now(),
                       code=result.returncode, stdout=result.stdout, stderr=result.stderr))
    if check:
        p2.require(result.returncode == 0, f'host command failed, exit {result.returncode}: {path}')
    return result


def signature_certificates(data):
    certs = []
    while data:
        p2.require(len(data) >= 28, 'truncated EFI signature list')
        kind = data[:16]
        size, header, entry = struct.unpack_from('<III', data, 16)
        p2.require(kind == X509 and 28 <= size <= len(data) and header == 0 and entry > 16,
                   'unexpected EFI signature list')
        p2.require((size - 28) % entry == 0, 'invalid EFI signature list entries')
        certs.extend(data[i + 16:i + entry] for i in range(28, size, entry))
        data = data[size:]
    return certs


def firmware_result(text, nonce, certificate, load_only=False):
    prefix = f'P3 {nonce} '
    lines = [line[len(prefix):].rstrip() for line in text.splitlines() if line.startswith(prefix)]
    p2.require(lines.count('COMPLETE') == 1, 'missing unique firmware completion evidence')
    results = {}
    for name in ['SecureBoot', 'SetupMode', 'PK', 'KEK', 'db']:
        matches = [line.split() for line in lines if line.startswith(name + ' ')]
        p2.require(len(matches) == 1 and len(matches[0]) == 4, f'missing unique {name} evidence')
        _, status, attributes, raw = matches[0]
        p2.require(status == '0000000000000000', f'firmware could not read {name}')
        data = bytes.fromhex(raw)
        if name in ['SecureBoot', 'SetupMode']:
            p2.require(data == (b'\x01' if name == 'SecureBoot' else b'\x00'), f'firmware is not enforcing: {name}')
        else:
            p2.require(signature_certificates(data) == [certificate], f'{name} differs from the sole intended test certificate')
        results[name] = dict(attributes=attributes, sha256=hashlib.sha256(data).hexdigest())
    for name in ['trusted', 'unsigned', 'untrusted', 'tampered']:
        expected = '0000000000000000' if name == 'trusted' else REFUSED
        actual = [line for line in lines if line.startswith(name + ' LOAD ')]
        p2.require(actual == [f'{name} LOAD {expected}'], f'{name}: expected firmware LoadImage status {expected}, got {actual}')
        starts = [line for line in lines if line.startswith(name + ' START ')]
        p2.require(starts == (['trusted START 0000000000000000'] if name == 'trusted' and not load_only else []),
                   f'unexpected launch result: {name}')
        results[name] = dict(load_status=expected, executed=name == 'trusted' and not load_only)
        if name != 'trusted':
            entries = [line for line in lines if line.startswith('DENIED_IMAGE ') and
                       line.endswith(f'\\EFI\\tests\\{name}.efi')]
            action = '00000000' if name == 'unsigned' else '00000003'
            p2.require(len(entries) == 1 and entries[0].split()[1] == action,
                       f'missing firmware authentication refusal record: {name}')
            results[name]['authentication_record'] = entries[0]
    p2.require(lines.count('PAYLOAD_EXECUTED') == (0 if load_only else 1), 'unexpected payload execution count')
    return results


def verify_inputs(base, code):
    manifest = p2.verify_baseline(base)
    p2.require(manifest.get('kind') == 'phase3-firmware-fixture', 'not a Phase 3 firmware fixture')
    p2.require(manifest['ovmf_code']['sha256'] == p2.digest(code), 'OVMF CODE changed')
    for name, expected in manifest['public_sha256'].items():
        path = (base / name).resolve(strict=True)
        p2.require(path.is_relative_to(base.resolve()), 'fixture path escaped baseline')
        p2.require(p2.digest(path) == expected, f'public fixture changed: {name}')
    return manifest


def fixtures(args):
    out, private = args.output, args.private_keys.resolve()
    p2.require(not private.is_relative_to(out) and not out.is_relative_to(private),
               'private keys and public fixtures must be separate directories')
    p2.require(not private.is_relative_to(p2.REPO), 'test private keys must stay outside the source checkout')
    private.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(private, 0o700)
    public = out / 'public'
    public.mkdir()
    nonce = uuid.uuid4().hex
    owner = str(uuid.uuid4())
    for identity in ['trusted', 'untrusted']:
        key, cert = private / f'{identity}.key', public / f'{identity}.pem'
        execute(out, ['openssl', 'req', '-new', '-x509', '-newkey', 'rsa:2048', '-nodes',
                      '-sha256', '-days', '14', '-subj', f'/CN=Astraeus disposable {identity} {nonce}',
                      '-keyout', key, '-out', cert])
        os.chmod(key, 0o600)
        execute(out, ['openssl', 'x509', '-in', cert, '-outform', 'DER', '-out', public / f'{identity}.der'])
    fingerprint = {name: p2.digest(public / f'{name}.der') for name in ['trusted', 'untrusted']}
    source = out / PROBE.name
    shutil.copyfile(PROBE, source)
    builds = [('probe', ['-DLOAD_ONLY'] if args.artifact else []), ('unsigned', ['-DPAYLOAD'])]
    for name, defines in builds:
        if name == 'unsigned' and args.artifact:
            shutil.copyfile(args.artifact, public / 'unsigned.efi')
            unsigned = execute(out, ['sbverify', '--list', public / 'unsigned.efi'], check=False)
            p2.require(unsigned.returncode == 0 and unsigned.stderr.strip() == 'No signature table present',
                       '--artifact must be an unsigned EFI executable')
            continue
        obj, shared, efi = out / f'{name}.o', out / f'{name}.so', public / f'{name}.efi'
        execute(out, ['gcc', '-I/usr/include/efi', '-I/usr/include/efi/x86_64', '-DEFI_FUNCTION_WRAPPER',
                      f'-DRUN_ID="{nonce}"', *defines, '-fpic', '-fshort-wchar', '-mno-red-zone',
                      '-fno-stack-protector', '-Wall', '-Wextra', '-Werror', '-c', source, '-o', obj])
        execute(out, ['ld', '-nostdlib', '-znocombreloc', '-T', '/usr/lib/elf_x86_64_efi.lds',
                      '-shared', '-Bsymbolic', '/usr/lib/crt0-efi-x86_64.o', obj,
                      '-L/usr/lib', '-lefi', '-lgnuefi', '-o', shared])
        execute(out, ['objcopy', '-j', '.text', '-j', '.sdata', '-j', '.data', '-j', '.dynamic',
                      '-j', '.dynsym', '-j', '.rel', '-j', '.rela', '-j', '.reloc', '-j', '.p3data',
                      '--target=efi-app-x86_64', shared, efi])
    for name, identity, source_name in [('boot', 'trusted', 'probe'), ('trusted', 'trusted', 'unsigned'),
                                         ('untrusted', 'untrusted', 'unsigned')]:
        execute(out, ['sbsign', '--key', private / f'{identity}.key', '--cert', public / f'{identity}.pem',
                      '--output', public / f'{name}.efi', public / f'{source_name}.efi'])
        execute(out, ['sbverify', '--cert', public / f'{identity}.pem', public / f'{name}.efi'])
    data = bytearray((public / 'trusted.efi').read_bytes())
    offset = section_offset(data, (b'.linux' if args.artifact_role == 'uki' else b'.text') if args.artifact else b'.p3data')
    data[offset] ^= 1
    (public / 'tampered.efi').write_bytes(data)
    for name in ['unsigned', 'tampered']:
        verification = execute(out, ['sbverify', '--cert', public / 'trusted.pem', public / f'{name}.efi'], check=False)
        p2.require(verification.returncode == 1, f'{name} fixture is not invalid as expected')
    execute(out, ['virt-fw-vars', '--input', args.ovmf_vars, '--output', out / 'vars.fd',
                  '--set-pk', owner, public / 'trusted.pem', '--add-kek', owner, public / 'trusted.pem',
                  '--add-db', owner, public / 'trusted.pem', '--secure-boot'])
    execute(out, ['virt-fw-vars', '--input', out / 'vars.fd', '--print', '--verbose',
                  '--output-json', out / 'enrollment.json'])
    raw = out / 'fixture.fat'
    with raw.open('wb') as stream:
        stream.truncate(max(64 * 1024 * 1024, 4 * (public / 'trusted.efi').stat().st_size + 16 * 1024 * 1024))
    execute(out, ['mkfs.vfat', raw])
    execute(out, ['mmd', '-i', raw, '::/EFI', '::/EFI/BOOT', '::/EFI/tests'])
    execute(out, ['mcopy', '-i', raw, public / 'boot.efi', '::/EFI/BOOT/BOOTX64.EFI'])
    for name in ['trusted', 'unsigned', 'untrusted', 'tampered']:
        execute(out, ['mcopy', '-i', raw, public / f'{name}.efi', f'::/EFI/tests/{name}.efi'])
    execute(out, ['qemu-img', 'convert', '-f', 'raw', '-O', 'qcow2', raw, out / 'disk.qcow2'])
    # accepted means sealed fixture inputs, never Astraeus boot or generation acceptance.
    p2.save(out / 'baseline.json', dict(accepted=True, kind='phase3-firmware-fixture', created=p2.now(),
             nonce=nonce, owner_guid=owner, certificate_sha256=fingerprint,
             load_only=bool(args.artifact), artifact=dict(path=str(args.artifact), role=args.artifact_role, sha256=p2.digest(args.artifact))
             if args.artifact else None,
             source_commit=args.source_commit, probe_sha256=p2.digest(PROBE),
             ovmf_code=dict(path=str(args.ovmf_code), sha256=p2.digest(args.ovmf_code)),
             ovmf_template=dict(path=str(args.ovmf_vars), sha256=p2.digest(args.ovmf_vars)),
             sha256={name: p2.digest(out / name) for name in ['disk.qcow2', 'vars.fd']},
             public_sha256={str(p.relative_to(out)): p2.digest(p) for p in public.iterdir()}))
    for name in ['disk.qcow2', 'vars.fd']:
        os.chmod(out / name, 0o444)


def firmware(vm, args, manifest):
    vm.start()
    deadline = time.monotonic() + args.timeout
    serial = vm.session / 'serial.log'
    while time.monotonic() < deadline:
        vm.alive()
        text = serial.read_text(errors='replace') if serial.exists() else ''
        if p2.marker_present(text, f'P3 {manifest["nonce"]} COMPLETE '):
            break
        time.sleep(0.1)
    else:
        raise TimeoutError('firmware probe incomplete; absence of a boot is not signature rejection')
    vm.qmp_state('firmware-complete')
    result = firmware_result(text, manifest['nonce'], (args.base / 'public/trusted.der').read_bytes(), manifest.get('load_only', False))
    p2.save(args.output / 'firmware-verdict.json', result)


def installed_fixture(args):
    """Sign copies of the existing Phase 2 ESP, never product build inputs."""
    out = args.output
    original = p2.verify_baseline(args.base)
    trust = verify_inputs(args.trust_base, args.ovmf_code)
    p2.require(original['encryption'] == 'none', 'offline fixture signing currently requires the plain baseline')
    raw = out / 'installed.raw'
    execute(out, ['qemu-img', 'convert', '-O', 'raw', args.base / 'disk.qcow2', raw], timeout=3600)
    partition = json.loads(execute(out, ['sfdisk', '--json', raw]).stdout)['partitiontable']
    esps = [p for p in partition['partitions'] if p['type'].lower() == 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b']
    p2.require(partition['label'] == 'gpt' and len(esps) == 1 and partition['sectorsize'] == 512,
               'expected one GPT ESP with 512-byte sectors')
    esp = f'{raw}@@{esps[0]["start"] * 512}'
    public = out / 'public'
    public.mkdir()
    for name, path in [('loader', 'EFI/systemd/systemd-bootx64.efi'),
                       ('fallback', 'EFI/BOOT/BOOTX64.EFI'), ('uki', 'EFI/Linux/astraeus-dev-linux.efi')]:
        source, signed = public / f'{name}-unsigned.efi', public / f'{name}.efi'
        execute(out, ['mcopy', '-i', esp, f'::/{path}', source])
        execute(out, ['sbsign', '--key', args.private_keys / 'trusted.key', '--cert',
                      args.trust_base / 'public/trusted.pem', '--output', signed, source])
        execute(out, ['sbverify', '--cert', args.trust_base / 'public/trusted.pem', signed])
        execute(out, ['mcopy', '-o', '-i', esp, signed, f'::/{path}'])
        roundtrip = out / f'{name}-roundtrip.efi'
        execute(out, ['mcopy', '-i', esp, f'::/{path}', roundtrip])
        p2.require(p2.digest(roundtrip) == p2.digest(signed), f'ESP write differs: {name}')
    execute(out, ['qemu-img', 'convert', '-f', 'raw', '-O', 'qcow2', raw, out / 'disk.qcow2'], timeout=3600)
    shutil.copyfile(args.trust_base / 'vars.fd', out / 'vars.fd')
    p2.save(out / 'baseline.json', dict(accepted=True, kind='phase3-installed-fixture',
             created=p2.now(), encryption='none', source_commit=args.source_commit,
             original=original, original_path=str(args.base), trust=trust, trust_path=str(args.trust_base),
             esp_offset=esps[0]['start'] * 512,
             ovmf_code=dict(path=str(args.ovmf_code), sha256=p2.digest(args.ovmf_code)),
             sha256={name: p2.digest(out / name) for name in ['disk.qcow2', 'vars.fd']},
             public_sha256={str(p.relative_to(out)): p2.digest(p) for p in public.iterdir()}))
    for name in ['disk.qcow2', 'vars.fd']:
        os.chmod(out / name, 0o444)
    p2.verify_baseline(args.base)
    verify_inputs(args.trust_base, args.ovmf_code)
    raw.unlink()  # Converted fixture retained; this temporary copy has no unique evidence.


def installed(vm, args, manifest):
    vm.start()
    vm.ready()
    evidence = p2.observe(vm, 'installed', product=True)
    p2.healthy(evidence, manifest['encryption'])
    commands = {
        'firmware': "python3 -c 'import pathlib,json; p=pathlib.Path(\"/sys/firmware/efi/efivars\"); "
                    "print(json.dumps({n:next(p.glob(n+\"-*\")).read_bytes()[4:].hex() "
                    "for n in [\"SecureBoot\",\"SetupMode\",\"PK\",\"KEK\",\"db\"]}))'",
        'kernel': 'uname -a', 'loader': 'bootctl --print-loader-path',
        'entry': 'bootctl --print-stub-path',
        'encryption': 'lsblk --json -o NAME,TYPE,FSTYPE,UUID,MOUNTPOINTS',
        'boot-confirmation': 'systemctl show astraeus-confirm-boot.service -p Result -p ExecMainStatus',
        'esp-files': 'find /efi/EFI /efi/loader -type f -exec sha256sum {} +',
    }
    extra = {name: vm.command(command, check=False, label=name) for name, command in commands.items()}
    p2.save(args.output / 'installed-phase3.json', extra)
    state = json.loads(p2.value(extra, 'firmware'))
    p2.require(state['SecureBoot'] == '01' and state['SetupMode'] == '00', 'installed guest is not enforcing')
    certificate = Path(manifest['trust_path']) / 'public/trusted.der'
    p2.require(p2.digest(certificate) == manifest['trust']['certificate_sha256']['trusted'], 'trust certificate changed')
    for name in ['PK', 'KEK', 'db']:
        p2.require(signature_certificates(bytes.fromhex(state[name])) == [certificate.read_bytes()], f'wrong installed {name}')
    p2.require(p2.value(extra, 'loader').replace('\\', '/').lower().endswith('/efi/boot/bootx64.efi'), 'unexpected loaded bootloader')
    p2.require(p2.value(extra, 'entry').replace('\\', '/').lower().endswith('/efi/linux/astraeus-dev-linux.efi'), 'unexpected loaded UKI')
    p2.require(p2.value(evidence, 'uki-sha256').split()[0] == manifest['public_sha256']['public/uki.efi'], 'active UKI hash differs')
    confirmation = dict(line.split('=', 1) for line in p2.value(extra, 'boot-confirmation').splitlines())
    p2.require(confirmation == dict(Result='success', ExecMainStatus='0'), 'boot confirmation service failed')
    p2.value(extra, 'kernel')
    p2.value(extra, 'encryption')
    files = {path: digest for digest, path in (line.split(maxsplit=1) for line in p2.value(extra, 'esp-files').splitlines())}
    for name, path in [('loader', '/efi/EFI/systemd/systemd-bootx64.efi'),
                       ('fallback', '/efi/EFI/BOOT/BOOTX64.EFI'), ('uki', '/efi/EFI/Linux/astraeus-dev-linux.efi')]:
        p2.require(files.get(path) == manifest['public_sha256'][f'public/{name}.efi'], f'installed signed {name} hash differs')
    if args.mode == 'inject':
        command = ['python3', '/mnt/astraeus-validation/phase3_guest.py', args.fault,
                   '--uki', '/efi/EFI/Linux/astraeus-dev-linux.efi']
        if args.replacement:
            command += ['--replacement', f'/mnt/astraeus-validation/public/{args.replacement.name}',
                        '--sha256', p2.digest(args.replacement)]
        receipt = json.loads(vm.command(shlex.join(command), label='fault-injection')['output'])
        p2.require(receipt['fault'] == args.fault and receipt['before_sha256'] == manifest['public_sha256']['public/uki.efi'],
                   'fault did not target the observed signed UKI')
        p2.save(args.output / 'fault-injection.json', receipt)
        p2.observe(vm, 'after-fault', product=True)
    vm.shutdown()


def cut_at_barrier(vm, checkpoint, generation, root_uuid, uki_sha256):
    """Wait for an integration-owned write barrier, then cut only this QEMU child."""
    p2.require(checkpoint in CHECKPOINTS, 'unknown Phase 3 interruption checkpoint')
    p2.require(generation and str(uuid.UUID(root_uuid)) == root_uuid and re.fullmatch('[0-9a-f]{64}', uki_sha256),
               'power cut requires previously inspected generation/root/UKI identities')
    deadline = time.monotonic() + vm.timeout
    receipt = None
    while time.monotonic() < deadline:
        reply = vm.command('cat /var/log/astraeus-validation-phase3-barrier.json',
                           timeout=5, check=False, label='phase3-barrier')
        if reply['code'] == 0:
            receipt = json.loads(reply['output'])
            p2.require(receipt.get('checkpoint') == checkpoint and receipt.get('boot_id') == vm.boot_id
                       and receipt.get('generation') == generation and receipt.get('root_uuid') == root_uuid
                       and receipt.get('uki_sha256') == uki_sha256
                       and receipt.get('blocked') is True, 'invalid or stale Phase 3 barrier receipt')
            break
        p2.require(reply['code'] == 1 and not reply.get('error'), 'barrier inspection failed')
        time.sleep(0.1)
    p2.require(receipt is not None, 'interruption hook unavailable or barrier timed out; no power cut')
    vm.qmp_state('before-powercut')
    p2.save(vm.session / 'barrier-before-powercut.json', receipt)
    vm.alive()
    vm.child.kill()
    code = vm.child.wait(timeout=10)
    p2.require(code == -signal.SIGKILL, f'unexpected controlled power-cut exit {code}')
    p2.save(vm.session / 'powercut.json', dict(time=p2.now(), checkpoint=checkpoint, code=code, barrier=receipt))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['fixtures', 'firmware', 'installed-fixture', 'installed', 'inject'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ovmf-code', type=Path, required=True)
    parser.add_argument('--ovmf-vars', type=Path)
    parser.add_argument('--private-keys', type=Path)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--base', type=Path)
    parser.add_argument('--trust-base', type=Path)
    parser.add_argument('--artifact', type=Path, help='unsigned EFI artifact for firmware LoadImage-only verification')
    parser.add_argument('--artifact-role', choices=['uki', 'loader'], default='uki')
    parser.add_argument('--fault', choices=['tampered', 'missing', 'partial-esp-write', 'unsigned',
                                           'untrusted', 'wrong-root', 'full-esp'])
    parser.add_argument('--replacement', type=Path, help='public UKI fixture for unsigned/untrusted/wrong-root injection')
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    p2.require(sys.platform == 'linux' and Path('/dev/kvm').exists(), 'Linux nested KVM is required')
    p2.require(re.fullmatch('[0-9a-f]{40}', args.source_commit), 'source revision must be a full Git SHA')
    p2.require(10 <= args.timeout <= 3600, 'timeout must be 10..3600 seconds')
    args.output, args.ovmf_code = map(p2.safe_path, [args.output, args.ovmf_code])
    p2.require(args.ovmf_code.is_file(), 'missing OVMF CODE')
    if args.mode == 'inject':
        p2.require(args.fault, 'inject requires --fault')
        if args.fault in ['unsigned', 'untrusted', 'wrong-root']:
            p2.require(args.replacement and args.replacement.is_file(), 'this fault requires --replacement')
        p2.require(not args.replacement or args.replacement.suffix == '.efi', 'replacement must be a public EFI file')
    if args.mode == 'fixtures':
        p2.require(args.private_keys and args.ovmf_vars and args.ovmf_vars.is_file(),
                   'fixtures require a fresh VARS template and separate private key directory')
        if args.artifact:
            args.artifact = args.artifact.resolve(strict=True)
    else:
        p2.require(args.base and args.base.is_dir(), 'requires a sealed baseline')
        args.base = p2.safe_path(args.base)
        if args.mode == 'firmware':
            verify_inputs(args.base, args.ovmf_code)
        elif args.mode == 'installed-fixture':
            p2.require(args.private_keys and args.trust_base, 'installed-fixture requires test keys and --trust-base')
            args.trust_base = p2.safe_path(args.trust_base)
            verify_inputs(args.trust_base, args.ovmf_code)
        else:
            manifest = p2.verify_baseline(args.base)
            p2.require(manifest.get('kind') == 'phase3-installed-fixture', 'not a signed installed fixture')
            p2.require(manifest['ovmf_code']['sha256'] == p2.digest(args.ovmf_code), 'OVMF CODE changed')
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(args.output, 0o700)
    vm = None
    result = dict(passed=False, mode=args.mode, started=p2.now(), source_commit=args.source_commit,
                  integrated_acceptance=False, security_acceptance=False,
                  injection_only=args.mode == 'inject')
    try:
        p2.save(args.output / 'host.json', dict(qemu=execute(args.output, ['qemu-system-x86_64', '--version']).stdout,
                 packages=execute(args.output, ['dpkg-query', '-W', 'ovmf', 'python3-virt-firmware',
                                                'sbsigntool', 'gnu-efi']).stdout,
                 harness_files={str(p.relative_to(p2.REPO)): p2.digest(p) for p in
                                [Path(__file__), PROBE, HERE / 'phase3_guest.py', HERE / 'phase2-guest.py',
                                 HERE / 'phase2.py', HERE / 'qmp.py', HERE.parent / 'install-smoke.py']}))
        if args.mode == 'fixtures':
            fixtures(args)
        elif args.mode == 'installed-fixture':
            installed_fixture(args)
        else:
            manifest = p2.clone(args.base, args.output)
            share = None
            if args.mode in ['installed', 'inject']:
                share = args.output / 'share'
                share.mkdir()
                for name in ['phase2-guest.py', 'phase3_guest.py']:
                    shutil.copyfile(HERE / name, share / name)
                if args.replacement:
                    (share / 'public').mkdir()
                    shutil.copyfile(args.replacement, share / 'public' / args.replacement.name)
            vm = p2.VM(args.output, args.ovmf_code, share, args.timeout, secure_boot=True)
            if args.mode == 'firmware':
                firmware(vm, args, manifest)
            else:
                installed(vm, args, manifest)
        result['passed'] = True
        result['security_acceptance'] = args.mode == 'firmware'
    except BaseException as error:
        result['error'] = f'{type(error).__name__}: {error}'
        if vm and vm.boot_id and vm.child.poll() is None:
            try:
                p2.observe(vm, 'failure-diagnostics', product=True)
            except Exception as diagnostic_error:
                result['diagnostic_error'] = str(diagnostic_error)
        raise
    finally:
        try:
            if vm:
                vm.stop()
            if args.mode == 'firmware':
                verify_inputs(args.base, args.ovmf_code)
            elif args.base:
                p2.verify_baseline(args.base)
        except BaseException as error:
            result.update(passed=False, cleanup_error=str(error))
            raise
        finally:
            result['finished'] = p2.now()
            p2.save(args.output / 'result.json', result)
            p2.save(args.output / 'evidence-sha256.json', {str(p.relative_to(args.output)): p2.digest(p)
                     for p in args.output.rglob('*') if p.is_file() and p.name != 'evidence-sha256.json'})
            print(f'Evidence retained: {args.output}', flush=True)


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise InterruptedError(f'validation interrupted by signal {signum}')

    signal.signal(signal.SIGTERM, interrupted)
    main()
