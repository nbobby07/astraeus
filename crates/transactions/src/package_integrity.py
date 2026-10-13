"""Read-only package removal evidence. The embedded entry point always inspects /."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import zlib

LIMIT = 16 * 1024 * 1024
METADATA_UID = 0
PACKAGE_METADATA = {'.PKGINFO', '.BUILDINFO', '.MTREE', '.INSTALL', '.CHANGELOG'}


def identity(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def relative_path(value):
    if value.startswith('./'):
        value = value[2:]
    value = value.removesuffix('/')
    if not value or len(value.encode()) > 4096 or '\\' in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('unsupported package path')
    if value.startswith('/') or any(part in ('', '.', '..') for part in value.split('/')):
        raise ValueError('unsafe package path')
    return value


def safe_path(root, relative):
    parts = relative_path(relative).split('/')
    current = root
    for part in parts[:-1]:
        current = current / part
        observed = current.lstat()
        if not stat.S_ISDIR(observed.st_mode):
            raise ValueError('package path contains a link or non-directory')
        if os.name == 'posix' and (observed.st_uid != METADATA_UID or observed.st_mode & 0o022 or not observed.st_mode & 0o001):
            raise ValueError('package directory is externally writable or not publicly traversable')
    return current / parts[-1]


def stamp(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_metadata(root, relative):
    path = safe_path(root, relative)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    observed = path.lstat()
    if not stat.S_ISREG(observed.st_mode):
        raise ValueError('package metadata is not a regular file')
    # Decide public readability before opening so privileged and unprivileged plans agree.
    if os.name == 'posix' and (observed.st_uid != METADATA_UID or observed.st_mode & 0o022 or observed.st_nlink != 1 or not observed.st_mode & 0o004):
        raise ValueError('untrusted package metadata file')
    with os.fdopen(os.open(path, flags), 'rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > LIMIT:
            raise ValueError('invalid or oversized package metadata')
        if os.name == 'posix' and (before.st_uid != METADATA_UID or before.st_mode & 0o022 or before.st_nlink != 1 or not before.st_mode & 0o004):
            raise ValueError('untrusted package metadata file')
        value = source.read(LIMIT + 1)
        if len(value) > LIMIT or stamp(before) != stamp(os.fstat(source.fileno())):
            raise ValueError('package metadata changed during inspection')
    if stamp(before) != stamp(path.lstat()):
        raise ValueError('package metadata was replaced during inspection')
    return value


def fields(text):
    result = {}
    for block in text.strip().split('\n\n'):
        if not block:
            continue
        lines = block.splitlines()
        if not re.fullmatch(r'%[A-Z0-9_]+%', lines[0]) or lines[0] in result:
            raise ValueError('invalid or duplicate package metadata field')
        result[lines[0]] = lines[1:]
    return result


def unescape(value):
    # libarchive MTREE encodes whitespace and special bytes using octal escapes.
    output = bytearray()
    index = 0
    while index < len(value):
        if value[index] != '\\':
            output.extend(value[index].encode('utf-8'))
            index += 1
        elif re.fullmatch(r'[0-7]{3}', value[index + 1:index + 4]):
            byte = int(value[index + 1:index + 4], 8)
            if byte > 255:
                raise ValueError('invalid MTREE escape')
            output.append(byte)
            index += 4
        elif value[index:index + 2] == '\\\\':
            output.append(92)
            index += 2
        else:
            raise ValueError('unsupported MTREE escape')
    return output.decode('utf-8')


def mtree_entries(compressed):
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
        data = source.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('oversized MTREE')
    text = data.decode('utf-8')
    if not text.startswith('#mtree\n'):
        raise ValueError('invalid MTREE header')
    defaults, entries = {'type': 'file'}, {}
    for line in text.replace('\\\n', '').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if len(line) > 16384:
            raise ValueError('oversized MTREE entry')
        tokens = line.split()
        if tokens[0] == '/unset':
            if tokens[1:] == ['all']:
                defaults = {'type': 'file'}
            else:
                for key in tokens[1:]:
                    defaults.pop(key, None)
            continue
        attributes = {}
        for token in tokens[1:]:
            if '=' not in token:
                raise ValueError('unsupported MTREE attribute')
            key, value = token.split('=', 1)
            if not key or key in attributes:
                raise ValueError('duplicate MTREE attribute')
            attributes[key] = unescape(value)
        if tokens[0] == '/set':
            defaults.update(attributes)
            continue
        attributes = {**defaults, **attributes}
        if tokens[0] == '.' and attributes.get('type') == 'dir':
            continue
        path = relative_path(unescape(tokens[0]))
        if path in PACKAGE_METADATA:
            continue
        if path in entries or len(entries) >= 100000:
            raise ValueError('duplicate or excessive MTREE entries')
        entries[path] = attributes
    return entries


def pacman_check(name, deadline):
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(['/usr/bin/pacman', '--query', '--check', '--check', '--', name],
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                   env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline or os.fstat(output.fileno()).st_size > 2 * 1024 * 1024:
                    raise ValueError('pacman integrity inspection exceeded its limit')
                time.sleep(0.02)
            if os.fstat(output.fileno()).st_size > 2 * 1024 * 1024:
                raise ValueError('pacman integrity inspection exceeded its output limit')
            if process.returncode != 0:
                raise ValueError('pacman -Qkk reported changed, missing or unverifiable package files')
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def inspect_package(root, name, version, check=pacman_check, deadline=None):
    evidence = []
    deadline = deadline or time.monotonic() + 120
    try:
        if time.monotonic() >= deadline:
            raise ValueError('package integrity inspection exceeded its time limit')
        if not re.fullmatch(r'[a-z0-9][a-z0-9@._+-]{0,127}', name) or not version or len(version) > 256 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c in '/\\' for c in version):
            raise ValueError('invalid package identity')
        directory = f'var/lib/pacman/local/{name}-{version}'
        metadata = {kind: read_metadata(root, directory + '/' + kind) for kind in ('desc', 'files', 'mtree')}
        evidence.append({kind: hashlib.sha256(value).hexdigest() for kind, value in metadata.items()})
        description = fields(metadata['desc'].decode('utf-8'))
        if description.get('%NAME%') != [name] or description.get('%VERSION%') != [version]:
            raise ValueError('installed package identity changed')
        contents = fields(metadata['files'].decode('utf-8'))
        names = contents.get('%FILES%', [])
        owned = [relative_path(path) for path in names]
        if len(set(owned)) != len(owned) or (contents and '%FILES%' not in contents):
            raise ValueError('invalid installed file list')
        entries = mtree_entries(metadata['mtree'])
        if entries.keys() != set(owned):
            raise ValueError('MTREE does not cover the complete installed file list')
        check(name, min(deadline, time.monotonic() + 30))
        for relative, expected in sorted(entries.items()):
            if time.monotonic() >= deadline:
                raise ValueError('package integrity inspection exceeded its time limit')
            path = safe_path(root, relative)
            observed = path.lstat()
            kind = expected.get('type', 'file')
            if os.name == 'posix' and observed.st_uid != METADATA_UID:
                raise ValueError('package payload is externally owned: ' + relative)
            if kind == 'dir':
                if not stat.S_ISDIR(observed.st_mode) or os.name == 'posix' and (observed.st_mode & 0o022 or not observed.st_mode & 0o001):
                    raise ValueError('package directory type changed: ' + relative)
                evidence.append([relative, 'dir'])
            elif kind == 'link':
                if not stat.S_ISLNK(observed.st_mode):
                    raise ValueError('package symlink changed: ' + relative)
                target = os.readlink(path)
                if target != expected.get('link') or stamp(observed) != stamp(path.lstat()):
                    raise ValueError('package symlink changed: ' + relative)
                evidence.append([relative, 'link', target])
            elif kind == 'file':
                digest = expected.get('sha256digest', expected.get('sha256', ''))
                if not stat.S_ISREG(observed.st_mode) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
                    raise ValueError('regular file lacks verifiable SHA256: ' + relative)
                if os.name == 'posix' and (observed.st_mode & 0o022 or not observed.st_mode & 0o004):
                    raise ValueError('package payload is externally writable or not publicly readable: ' + relative)
                flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
                with os.fdopen(os.open(path, flags), 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode) or stamp(before) != stamp(observed):
                        raise ValueError('package file changed before inspection: ' + relative)
                    actual = hashlib.sha256()
                    while block := stream.read(1024 * 1024):
                        if time.monotonic() >= deadline:
                            raise ValueError('package integrity inspection exceeded its time limit')
                        actual.update(block)
                    if stamp(before) != stamp(os.fstat(stream.fileno())):
                        raise ValueError('package file changed during inspection: ' + relative)
                actual = actual.hexdigest()
                evidence.append([relative, 'file', actual])
                if actual != digest.lower() or stamp(before) != stamp(path.lstat()):
                    raise ValueError('package file content changed: ' + relative)
            else:
                raise ValueError('unsupported package file type: ' + relative)
        for kind, previous in metadata.items():
            if read_metadata(root, directory + '/' + kind) != previous:
                raise ValueError('installed metadata changed during inspection')
        return {'removable': True, 'digest': identity(evidence), 'detail': 'pacman metadata and complete MTREE SHA256 verification passed'}
    except (OSError, ValueError, UnicodeError, EOFError, zlib.error) as error:
        detail = ''.join(c if c.isprintable() else '?' for c in str(error))[:512]
        return {'removable': False, 'digest': identity([*evidence, {'error': detail}]), 'detail': detail}


def main():
    data = sys.stdin.buffer.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError('oversized integrity request')
    packages = json.loads(data)
    if not isinstance(packages, dict) or len(packages) > 1024 or not all(isinstance(name, str) and isinstance(version, str) for name, version in packages.items()):
        raise ValueError('invalid integrity request')
    deadline = time.monotonic() + 120
    result = {name: inspect_package(Path('/'), name, version, deadline=deadline) for name, version in sorted(packages.items())}
    print(json.dumps({'schema_version': 1, 'packages': result}, separators=(',', ':')))


if __name__ == '__main__':
    main()
