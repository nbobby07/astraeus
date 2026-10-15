import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

base = Path('/home/ubuntu/p42')
out = base / 'nge'
private = Path('/root/p42-nge-private')
scripts = base / 'h216cf37/scripts/validate'
sys.path.insert(0, str(scripts))
import phase2 as p2

spec = importlib.util.spec_from_file_location('baseline', scripts / 'phase42-baseline.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
assert os.geteuid() == 0 and Path('/dev/kvm').exists()
assert not (out / 'baseline.json').exists() and not (out / 'resume-result.json').exists()
failed = json.loads((out / 'result.json').read_text())
assert not failed['accepted'] and 'actual-desktop-1 exited 1' in failed['error']
detail = json.loads((out / 'boot-2/051-actual-desktop-1.json').read_text())
assert 'runuser failed (28)' in detail['result']['output']
assert not any(Path('/sys/block').glob('nbd*/pid'))
for proc in Path('/proc').glob('[0-9]*/cmdline'):
    try:
        executable = proc.read_bytes().split(b'\0')[0]
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    assert not Path(os.fsdecode(executable)).name.startswith('qemu-system')
config = m.configuration(json.loads((out / 'installation.json').read_text()))
inputs = json.loads((out / 'inputs.json').read_text())
installed = json.loads((out / 'fresh-installation.json').read_text())
assert config['source_commit'] == 'ec3641b72ad48d0ed24d4d9c8aa1a39cce938025'
assert config['encryption'] == 'LUKS2' and installed['preexisting_application']['unmanaged']
share = private / 'share'
assert share.is_dir() and not share.is_symlink()
assert not any((share / n).exists() for n in ['db.key', 'login-password', 'luks-passphrase'])
for name in ['phase2-guest.py', 'phase42-baseline.py', 'phase42_trust.py']:
    assert p2.digest(share / name) == p2.digest(scripts / name)
assert p2.digest(share / 'installed-smoke.sh') == p2.digest(base / 'h216cf37/tests/boot/installed-smoke.sh')
pins = {n: p2.digest(out / 'public-owner' / (n + '.cer')) for n in ['PK', 'KEK', 'db']}
assert pins['db'] == config['certificate_sha256']
code = Path(inputs['ovmf_code']['path'])
assert p2.digest(code) == inputs['ovmf_code']['sha256']
result = dict(accepted=False, retained_failure='result.json', started=p2.now(),
              before={n: p2.digest(out / n) for n in ['disk.qcow2', 'vars.fd']})
vm = p2.VM(out, code, share, 1800, secure_boot=True)
vm.number = 2
boots = []
try:
    for number in [1, 2]:
        vm.start()
        p2.save(out / 'attention.json', dict(stage='unlock-and-sddm-login', boot=number,
                qmp=str(vm.monitor), credentials=str(private), user='tester', encryption='LUKS2'))
        vm.ready()
        assert vm.boot_id not in boots
        boots.append(vm.boot_id)
        p2.save(out / ('resumed-uki-trust-' + str(number) + '.json'), m.installed_boot_trust(vm, pins['db']))
        vm.command('systemctl start NetworkManager-wait-online.service', timeout=120, label='network-online')
        p2.healthy(p2.observe(vm, 'resumed-installed-' + str(number), product=False), 'LUKS2')
        if number == 1:
            vm.command('find /home/tester -maxdepth 3 -path "/home/tester/installation-evidence.*/health.log" -type f -exec tail -n 70 {} \\;', label='retained-original-smoke-failure')
        vm.command('python3 /mnt/astraeus-validation/phase42-baseline.py guest-desktop'
                   + (' --initial' if number == 1 else ''), timeout=900, label='actual-resumed-desktop-' + str(number))
        if number == 1:
            vm.command('distroctl boot enable', timeout=300, label='enable-managed-generations')
        vm.shutdown()
    manifest = dict(schema_version=1, kind='phase42-fresh-candidate-payload', accepted=True,
        method=installed['method'], calamares_ui=False, encryption='LUKS2', source_commit=config['source_commit'],
        inputs=inputs, signer_sha256=pins['db'], public_fingerprints=pins, boot_ids=boots, created=p2.now(),
        preexisting_application=installed['preexisting_application'], installation_firmware=installed['installation_firmware'],
        management_firmware_required=m.MANAGEMENT_FIRMWARE,
        installed_binaries={n: config[k] for n, k in [('distroctl', 'distroctl_sha256'), ('astraeus-control-center', 'desktop_sha256')]},
        sha256={n: p2.digest(out / n) for n in ['disk.qcow2', 'vars.fd']},
        retained_failed_attempt='result.json', resumed_validation='resume-result.json')
    p2.save(out / 'baseline.json', manifest)
    for name in ['disk.qcow2', 'vars.fd']:
        (out / name).chmod(0o444)
    result.update(accepted=True, boot_ids=boots)
    p2.save(out / 'attention.json', dict(stage='complete'))
except BaseException as error:
    result['error'] = f'{type(error).__name__}: {error}'
    raise
finally:
    vm.stop()
    result['finished'] = p2.now()
    p2.save(out / 'resume-result.json', result)
