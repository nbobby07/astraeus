"""Copy bounded public test evidence from one cleanly closed task-owned builder."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile

run_name, label = sys.argv[1:]
assert re.fullmatch(r'candidate-[0-9a-f]{12}-r[1-9][0-9]*', run_name)
assert label in {'A', 'B'} and os.geteuid() == 0
base = Path('/home/ubuntu/p50').resolve(strict=True)
attempt = (base / run_name).resolve(strict=True)
assert attempt.parent == base and not (base / run_name).is_symlink()
state = json.loads((attempt / 'run.json').read_text())
assert state['source_commit'] == 'c38209c523e308d23ff622b32d9cd0ed42682962'
assert run_name.startswith('candidate-' + state['source_commit'][:12] + '-')
evidence = attempt / 'share/evidence' / label
assert (evidence / 'exit-code').read_text().strip() == '0'
assert f'BUILDER_{label}_SUCCESS' in (evidence / 'build.log').read_text()
disk = (attempt / f'builder-{label}/disk.qcow2').resolve(strict=True)
assert disk == attempt / f'builder-{label}/disk.qcow2'
for path in Path('/proc').glob('[0-9]*/cmdline'):
    try: arguments = path.read_bytes()
    except FileNotFoundError: continue
    assert os.fsencode(disk) not in arguments
assert not any(Path('/sys/block').glob('nbd*/pid'))
device = Path('/dev/nbd0')
assert Path('/sys/block/nbd0/size').read_text().strip() == '0'
mount = attempt / f'closed-test-evidence-mount-{label}-v2'
mount.mkdir(exist_ok=False)

def run(*args):
    return subprocess.run(list(map(str, args)), check=True, text=True, capture_output=True, timeout=30).stdout

def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()

connected = mounted = False
loop = None
try:
    run('qemu-nbd', '--read-only', '--format=qcow2', '--connect=' + str(device), disk)
    connected = True
    assert Path('/sys/block/nbd0/ro').read_text().strip() == '1'
    raw = run('partx', '--raw', '--noheadings', '--output', 'START,SECTORS,TYPE,SCHEME', device)
    rows = [line.split() for line in raw.splitlines()]
    roots = [row for row in rows if len(row) == 4 and row[3] == 'gpt' and row[2].lower() in {'0fc63daf-8483-4772-8e79-3d69d8477de4', '4f68bce3-e8cd-4db1-96e7-fbcaf984b709'}]
    assert len(roots) == 1
    start, size, *_ = roots[0]
    sector = int(run('blockdev', '--getss', device))
    loop = run('losetup', '--find', '--show', '--read-only', '--offset', int(start) * sector, '--sizelimit', int(size) * sector, device).strip()
    assert re.fullmatch('/dev/loop[0-9]+', loop)
    kind = run('blkid', '-p', '-s', 'TYPE', '-o', 'value', loop).strip()
    assert kind in {'ext4', 'btrfs'}
    run('mount', '-t', kind, '-o', 'ro,noload' if kind == 'ext4' else 'ro,nologreplay', loop, mount)
    mounted = True
    package = mount / 'build/operating-system/.build/package'
    tests = package / 'src/platform/target/control-center/Testing/Temporary/LastTest.log'
    assert tests.is_file() and not tests.is_symlink() and tests.stat().st_size < 8 * 1024 * 1024
    output = evidence / 'control-center-LastTest.log'
    if output.exists():
        assert digest(output) == digest(tests)
    else:
        shutil.copyfile(tests, output)
    source = package / 'platform.tar.xz'
    recipe = package / 'PKGBUILD'
    recipe_text = recipe.read_text()
    source_hash = digest(source)
    assert f"sha256sums=('{source_hash}')" in recipe_text
    record = {'read_only': True, 'source_commit': state['source_commit'], 'label': label, 'test_log_sha256': digest(output), 'platform_source_sha256': source_hash, 'platform_source_bytes': source.stat().st_size, 'recipe_sha256': digest(recipe), 'totals': re.findall(r'Totals:.*', output.read_text())}
    installer_path = mount / 'build/operating-system/scripts/installer.py'
    frozen_installer = attempt / 'source-tree/operating-system/scripts/installer.py'
    assert digest(installer_path) == digest(frozen_installer)
    spec = importlib.util.spec_from_file_location('closed_installer', installer_path)
    installer = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(installer)
    image_build = mount / 'build/iso-build'
    comparisons = {}
    for name, filesystem in [('image', image_build / 'work/x86_64/airootfs'),
                             ('installed', image_build / 'installed-root')]:
        observed = []
        for desc in sorted((filesystem / 'var/lib/pacman/local').glob('*/desc')):
            fields = installer.metadata_fields(desc.read_text())
            assert len(fields['%NAME%']) == len(fields['%VERSION%']) == 1
            observed.append(fields['%NAME%'][0] + ' ' + fields['%VERSION%'][0])
        assert observed and len(observed) == len(set(observed))
        manifest = evidence / (name + '-packages.txt')
        reported = manifest.read_text().splitlines()
        comparisons[name] = dict(local_records=len(observed), manifest_lines=len(reported),
                                 manifest_sha256=digest(manifest), exact_match=sorted(observed) == sorted(reported),
                                 missing=sorted(set(observed) - set(reported))[:50],
                                 extra=sorted(set(reported) - set(observed))[:50])
    record['manifest_completeness'] = comparisons
    record['mkarchiso_package_lists'] = []
    for manifest in sorted((image_build / 'work/iso').rglob('pkglist*')):
        if manifest.is_file() and not manifest.is_symlink():
            assert manifest.stat().st_size < 1024 * 1024
            retained = evidence / ('mkarchiso-' + manifest.name)
            if retained.exists():
                assert digest(retained) == digest(manifest)
            else:
                shutil.copyfile(manifest, retained)
            record['mkarchiso_package_lists'].append(dict(path=str(manifest.relative_to(image_build)),
                                                          bytes=manifest.stat().st_size,
                                                          lines=len(manifest.read_text().splitlines()), sha256=digest(manifest)))
    if label == 'A':
        approved = json.loads((attempt / 'source-tree/operating-system/distro/repo/archive.lock.json').read_text())
        packages = {}
        for name, checksum in approved['databases'].items():
            database = mount / 'build/archive' / (name + '.db')
            assert digest(database) == checksum
            with tarfile.open(database) as archive:
                for member in archive:
                    if not member.name.endswith('/desc'): continue
                    fields = {}
                    for block in archive.extractfile(member).read().decode().strip().split('\n\n'):
                        lines = block.splitlines(); fields[lines[0].strip('%')] = lines[1:]
                    filename = fields['FILENAME'][0]
                    assert Path(filename).name == filename
                    packages[filename] = fields
        cache = attempt / 'share/package-cache'
        verified = {}
        for source in sorted((mount / 'var/cache/pacman/pkg').glob('*.pkg.tar.zst')):
            if source.name not in packages: continue
            fields = packages[source.name]
            assert stat.S_ISREG(source.lstat().st_mode) and digest(source) == fields['SHA256SUM'][0]
            target = cache / source.name
            if target.exists():
                assert not target.is_symlink() and digest(target) == fields['SHA256SUM'][0]
            else:
                shutil.copyfile(source, target); target.chmod(0o444)
            signature = base64.b64decode(fields['PGPSIG'][0], validate=True)
            assert len(signature) < 16384
            target_signature = cache / (source.name + '.sig')
            if target_signature.exists(): assert target_signature.read_bytes() == signature
            else: target_signature.write_bytes(signature); target_signature.chmod(0o444)
            verified[source.name] = {'sha256': digest(target), 'bytes': target.stat().st_size}
        assert verified
        record['b_upstream_cache'] = {'verified_archives': verified,
            'method': 'closed A upstream archives matched to approved pinned database SHA256 and signature bytes',
            'normal_b_verification_required': True}
finally:
    if mounted: run('umount', mount)
    if loop: run('losetup', '--detach', loop)
    if connected: run('qemu-nbd', '--disconnect', device)
assert not any(Path('/sys/block').glob('nbd*/pid'))
record['nbd_disconnected'] = True
(evidence / 'closed-test-evidence.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
