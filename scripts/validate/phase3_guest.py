#!/usr/bin/env python3
"""Test-only UKI fault injection in disposable nested guests; never ship this file."""
import argparse
import errno
import hashlib
import importlib.util
import json
from pathlib import Path
import os
import struct
import subprocess
import time


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def section_offset(data, section):
    """Locate signed section bytes without damaging PE headers or certificate tables."""
    require(len(data) >= 64 and data[:2] == b'MZ', 'not a PE image')
    offset = struct.unpack_from('<I', data, 60)[0]
    require(offset + 24 <= len(data) and data[offset:offset + 4] == b'PE\0\0', 'invalid PE header')
    count = struct.unpack_from('<H', data, offset + 6)[0]
    optional = struct.unpack_from('<H', data, offset + 20)[0]
    table = offset + 24 + optional
    require(table + 40 * count <= len(data), 'truncated section table')
    for i in range(count):
        entry = table + i * 40
        if data[entry:entry + 8].rstrip(b'\0') == section:
            size, raw = struct.unpack_from('<II', data, entry + 16)
            require(size > 0 and raw >= table + 40 * count and raw + size <= len(data),
                    'invalid section bounds')
            return raw
    raise RuntimeError(f'missing signed section {section!r}')


def guard():
    spec = importlib.util.spec_from_file_location('phase2_guest', Path(__file__).with_name('phase2-guest.py'))
    guest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guest)
    guest.guard()


def uki_path(path):
    path = path.resolve(strict=True)
    require(path.is_file() and path.is_relative_to('/efi/EFI/Linux') and path.suffix == '.efi',
            'fault target must be an installed UKI inside /efi/EFI/Linux')
    mount = json.loads(subprocess.check_output(['findmnt', '--json', '--target', path,
                                               '-o', 'TARGET,SOURCE,FSTYPE'], timeout=10))['filesystems']
    require(len(mount) == 1 and mount[0]['target'] == '/efi' and mount[0]['fstype'] == 'vfat'
            and mount[0]['source'] == '/dev/vda1', 'unexpected disposable ESP mount')
    return path


def fault(kind, path, replacement=None, expected=None):
    guard()
    path = uki_path(path)
    data = path.read_bytes()
    require(len(data) > 4096, 'UKI fixture is too small')
    receipt = dict(fault=kind, path=str(path), before_sha256=hashlib.sha256(data).hexdigest(),
                   started=time.time(), injected=False, expected='refusal, never timeout-based acceptance')
    log = Path('/var/log/astraeus-validation-phase3-fault.json')
    log.write_text(json.dumps(receipt) + '\n')
    if kind == 'tampered':
        damaged = bytearray(data)
        damaged[section_offset(data, b'.linux')] ^= 1
        path.write_bytes(damaged)
    elif kind == 'missing':
        path.unlink()
    elif kind == 'partial-esp-write':
        path.write_bytes(data[:len(data) // 2])
    elif kind in ['unsigned', 'untrusted', 'wrong-root']:
        require(replacement is not None and expected is not None, 'replacement and public SHA256 are required')
        replacement = replacement.resolve(strict=True)
        require(replacement.is_file() and replacement.is_relative_to('/mnt/astraeus-validation/public'),
                'replacement must come from the read-only public fixture share')
        copied = replacement.read_bytes()
        require(hashlib.sha256(copied).hexdigest() == expected, 'replacement fixture hash mismatch')
        section_offset(copied, b'.linux')
        path.write_bytes(copied)
        receipt['replacement_sha256'] = expected
    elif kind == 'full-esp':
        filler = Path('/efi/astraeus-validation-filler')
        require(not filler.exists(), 'ESP filler already exists')
        space = os.statvfs('/efi')
        require(space.f_blocks * space.f_frsize <= 2 * 1024**3, 'ESP exceeds bounded 2 GiB fault budget')
        require(space.f_bavail > 0, 'ESP was full before fault injection')
        deadline = time.monotonic() + 30
        written = 0
        with filler.open('xb', buffering=0) as stream:
            while True:
                require(time.monotonic() < deadline, 'ESP filling timed out without ENOSPC')
                try:
                    written += stream.write(b'x' * 65536)
                except OSError as error:
                    if error.errno != errno.ENOSPC:
                        raise
                    receipt.update(errno=errno.ENOSPC, written=written)
                    break
    else:
        raise ValueError('unknown Phase 3 fault')
    os.sync()
    receipt.update(finished=time.time(), injected=True, after_sha256=hashlib.sha256(path.read_bytes()).hexdigest()
                   if path.exists() else None)
    log.write_text(json.dumps(receipt) + '\n')
    os.sync()
    print(json.dumps(receipt))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fault', choices=['tampered', 'missing', 'partial-esp-write', 'unsigned',
                                         'untrusted', 'wrong-root', 'full-esp'])
    parser.add_argument('--uki', required=True, type=Path)
    parser.add_argument('--replacement', type=Path)
    parser.add_argument('--sha256')
    args = parser.parse_args()
    fault(args.fault, args.uki, args.replacement, args.sha256)
