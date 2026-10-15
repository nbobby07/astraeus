#!/usr/bin/env python3
"""Unprivileged, bounded live observations. No raw logs or hardware acceptance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time

LIMIT = 1024 * 1024
TIMEOUT = 30
PACKAGES = (
    'distroctl', 'astraeus-control-center', 'linux', 'linux-firmware', 'mesa',
    'lib32-mesa', 'vulkan-icd-loader', 'lib32-vulkan-icd-loader',
    'vulkan-swrast', 'lib32-vulkan-swrast', 'vulkan-radeon', 'vulkan-intel',
    'vulkan-nouveau', 'lib32-vulkan-radeon', 'lib32-vulkan-intel', 'lib32-vulkan-nouveau',
    'linux-firmware-amdgpu', 'linux-firmware-intel', 'linux-firmware-nvidia',
    'nvidia-open', 'nvidia-utils', 'plasma-workspace', 'kwin',
)
SERVICES = {'sddm.service', 'NetworkManager.service', 'systemd-udevd.service',
            'dbus.service', 'pipewire.service', 'wireplumber.service',
            'live-keyring.service', 'live-smoke.service'}


def execute(argv, directory, timeout=TIMEOUT, limit=LIMIT):
    """Drain both pipes with a shared byte cap; kill descendants, including on Ctrl+C."""
    env = dict(os.environ, PATH='/usr/bin:/bin', LC_ALL='C',
               HOME=str(directory / 'private'), XDG_CACHE_HOME=str(directory / 'private'),
               MESA_SHADER_CACHE_DISABLE='true', __GL_SHADER_DISK_CACHE='0')
    started = time.monotonic()
    result = dict(exit_code=None, outcome='ok', seconds=0)
    output = bytearray()
    try:
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, cwd=directory, env=env,
                                 start_new_session=True)
    except OSError as error:
        result['outcome'] = 'missing_tool' if isinstance(error, FileNotFoundError) else 'launch_error'
        return result, b''
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            selector.register(child.stderr, selectors.EVENT_READ)
            size = 0
            while selector.get_map() or child.poll() is None:
                if time.monotonic() - started >= timeout:
                    result['outcome'] = 'timeout'
                    break
                for key, _ in selector.select(0.05):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    size += len(data)
                    if key.fileobj is child.stdout:
                        output.extend(data[:max(0, limit - len(output))])
                if size > limit:
                    result['outcome'] = 'output_limit'
                    break
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            result['exit_code'] = child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            result['outcome'] = 'cleanup_timeout'
        child.stdout.close()
        child.stderr.close()
    result['seconds'] = round(time.monotonic() - started, 3)
    if result['outcome'] == 'ok' and result['exit_code'] != 0:
        result['outcome'] = 'nonzero_exit'
    return result, bytes(output)


def number(value):
    return type(value) is int and 0 <= value < 2**64


def boolean(value):
    return type(value) is bool


def choices(*values):
    return lambda value: type(value) is str and value in values


def pattern(expression):
    return lambda value: type(value) is str and len(value) <= 128 and re.fullmatch(expression, value) is not None


# Custom version suffixes can contain local host/user names. Fail closed.
VERSION = pattern(r'[0-9]+(?:[.+:~_-](?:[0-9]+|dev|rc[0-9]+|arch[0-9]+|beta[0-9]+|alpha[0-9]+|g[0-9a-f]{7,40}))*')
HEX_ID = pattern(r'0x[0-9a-fA-F]{4}')
STATE = choices('present', 'absent', 'passed', 'failed', 'unsupported', 'unknown', 'untested')
GPU = dict(vendor_id=HEX_ID, device_id=HEX_ID,
           driver=choices('amdgpu', 'radeon', 'i915', 'xe', 'nouveau', 'nvidia',
                          'virtio-pci', 'virtio_gpu', 'bochs-drm', 'qxl'), boot_vga=boolean)
DEVICE = dict(vendor_id=number, device_id=number, device_type=number,
              api_version=number, driver_version=number, driver_id=number,
              software=boolean, rendering=STATE)
SCHEMAS = {
    'info': dict(identity=dict(id=choices('astraeus-dev'), name=choices('Project Astraeus'),
                               version=VERSION), build=dict(
        architecture=choices('x86_64'), archive_date=pattern(r'\d{4}/\d{2}/\d{2}'),
        source_date_epoch=number, archiso_version=VERSION, rust_version=VERSION)),
    'status': dict(version=VERSION, kernel=VERSION,
                   boot=dict(firmware=choices('UEFI', 'BIOS')),
                   filesystem=dict(root_type=choices('overlay', 'btrfs', 'ext4', 'squashfs', 'tmpfs'),
                                   encryption=choices('none', 'LUKS1', 'LUKS2', 'dm-crypt')),
                   desktop=dict(session_type=choices('wayland', 'x11'))),
    'hardware': dict(cpu=dict(architecture=choices('x86_64'), logical_count=number,
                              physical_core_count=number), memory_bytes=number,
                     memory_available_bytes=number, gpus=[GPU], capabilities=dict(
                         uefi=boolean, virtual_machine=boolean)),
    'graphics': dict(archive_date=pattern(r'\d{4}/\d{2}/\d{2}'),
                     gpus=[dict(hardware=GPU, firmware_package=STATE, firmware_loaded=STATE,
                                wayland=STATE, rendering=STATE)],
                     boot_gpu=number, multi_gpu=boolean, activation=STATE,
                     wayland=dict(session_type=choices('wayland', 'x11'), active=boolean,
                                  vrr=STATE, hdr=STATE),
                     native=dict(bits=number, loader=STATE, enumeration=STATE),
                     compat32=dict(bits=number, loader=STATE, enumeration=STATE),
                     nvidia_module=dict(loaded_version=VERSION, disk_version=VERSION,
                                        modeset=boolean, trusted=STATE, activation=STATE)),
    'probe64': dict(architecture=lambda value: type(value) is int and value == 64,
                    loader_version=number, status=STATE, devices=[DEVICE]),
    'performance': dict(context=dict(architecture=choices('x86_64'), logical_cpus=number,
                                     memory_bytes=number, virtual_machine=boolean,
                                     kernel=VERSION, binary_sha256=pattern(r'[0-9a-f]{64}')),
                        sample=dict(memory_available_bytes=number, swap_used_bytes=number)),
}
# Keep the existing Vulkan helper schema and architecture checks.
SCHEMAS['probe32'] = dict(SCHEMAS['probe64'], architecture=lambda value: type(value) is int and value == 32)


def project(value, schema, unavailable, path='data'):
    """Only explicitly typed fields cross the public-output boundary."""
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            unavailable.append(path)
            value = {}
        return {key: project(value.get(key), rule, unavailable, path + '.' + key)
                for key, rule in schema.items()}
    if isinstance(schema, list):
        if not isinstance(value, list) or len(value) > 128:
            unavailable.append(path)
            return None
        return [project(item, schema[0], unavailable, f'{path}[{index}]')
                for index, item in enumerate(value)]
    if schema(value):
        return value
    unavailable.append(path)
    return None


def parse_json(raw, name, unavailable):
    value = json.loads(raw)
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value['schema_version'] != 1:
        raise ValueError('unsupported_schema')
    if name in ('probe32', 'probe64'):
        if type(value.get('architecture')) is not int or value['architecture'] != int(name[-2:]):
            raise ValueError('unsupported_schema')
        devices = value.get('devices')
        if (value.get('status') not in ('passed', 'failed', 'absent', 'unsupported')
                or not isinstance(devices, list) or len(devices) > 64
                or (value['status'] != 'passed' and devices)):
            raise ValueError('malformed_output')
        for device in devices:
            if (not isinstance(device, dict) or type(device.get('device_type')) is not int
                    or not 0 <= device['device_type'] <= 4
                    or device.get('rendering') not in ('passed', 'failed', 'unsupported', 'untested')):
                raise ValueError('malformed_output')
            if device['device_type'] == 4 or device.get('driver_id') == 13:
                device['software'] = True
    return dict(schema_version=1, **project(value, SCHEMAS[name], unavailable))


def parse_packages(raw, unavailable):
    found = {}
    for line in raw.decode('utf-8').splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in PACKAGES and VERSION(parts[1]):
            found[parts[0]] = parts[1]
    unavailable.extend('packages.' + name for name in PACKAGES if name not in found)
    return found


def parse_services(raw, unavailable):
    rows = raw.decode('utf-8').splitlines()
    known, withheld, malformed = [], 0, 0
    for line in rows:
        parts = line.split()
        if (len(parts) < 4 or parts[1] not in ('loaded', 'not-found', 'error', 'bad-setting', 'masked')
                or parts[2:4] != ['failed', 'failed']):
            malformed += 1
        elif parts[0] in SERVICES:
            known.append(parts[0])
        else:
            withheld += 1
    if malformed:
        unavailable.append('services.malformed_rows')
    return dict(known_failed=sorted(set(known)), withheld_names=withheld, malformed_rows=malformed)


def new_directory(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('destination must be absolute without parent traversal')
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('destination must not traverse symlinks')
    if not path.parent.is_dir():
        raise ValueError('destination parent must already exist')
    path.mkdir(mode=0o700, exist_ok=False)
    return path


def collect(directory, image_source_commit=None, image_sha256=None):
    private = directory / 'private'
    private.mkdir(mode=0o700)
    report = dict(schema_version=1, physical_acceptance=False,
                  identity=dict(collector_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                image_source_commit=image_source_commit, image_sha256=image_sha256,
                                image_identity_origin='operator_supplied_unverified'), observations={})
    commands = [(name, ['/usr/bin/distroctl', *args, '--json']) for name, args in (
        ('info', ['info']), ('status', ['status']), ('hardware', ['hardware']),
        ('graphics', ['graphics']), ('performance', ['performance', 'status']))]
    commands += [(f'probe{bits}', [f'/usr/lib/distroctl/graphics-probe{bits}']) for bits in (64, 32)]
    commands += [('packages', ['/usr/bin/pacman', '-Q', *PACKAGES]),
                 ('services', ['/usr/bin/systemctl', '--failed', '--type=service', '--plain',
                               '--no-legend', '--no-pager'])]
    for name, argv in commands:
        result, raw = execute(argv, directory)
        result.update(command=argv, data=None, unavailable=[])
        if result['outcome'] in ('ok', 'nonzero_exit'):
            try:
                if name == 'packages':
                    result['data'] = parse_packages(raw, result['unavailable'])
                elif name == 'services':
                    if result['exit_code'] == 0:
                        result['data'] = parse_services(raw, result['unavailable'])
                else:
                    result['data'] = parse_json(raw, name, result['unavailable'])
                if result['unavailable'] and result['outcome'] == 'ok':
                    result['outcome'] = 'partial_output'
            except (ValueError, UnicodeError, RecursionError) as error:
                result['outcome'] = 'unsupported_schema' if str(error) == 'unsupported_schema' else 'malformed_output'
        report['observations'][name] = result
    report['unavailable'] = [key for key in ('image_source_commit', 'image_sha256')
                             if report['identity'][key] is None]
    with (directory / 'public.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return report


def sha(value, length):
    if not re.fullmatch(f'[0-9a-f]{{{length}}}', value):
        raise argparse.ArgumentTypeError(f'expected {length} lowercase hex digits')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='new absolute evidence directory; parent must exist')
    parser.add_argument('--image-source-commit', type=lambda value: sha(value, 40))
    parser.add_argument('--image-sha256', type=lambda value: sha(value, 64))
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() == 0:
        parser.exit(2, 'Use an ordinary Linux desktop user, without sudo.\n')
    os.umask(0o077)
    try:
        directory = new_directory(args.output)
        collect(directory, args.image_source_commit, args.image_sha256)
    except (OSError, ValueError):
        parser.exit(2, 'Cannot create evidence; choose a new writable absolute directory with an existing parent.\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Collection interrupted; the evidence directory may be incomplete.\n')
    print('Evidence saved as public.json. Review before sharing; keep private/ private.')


if __name__ == '__main__':
    main()
