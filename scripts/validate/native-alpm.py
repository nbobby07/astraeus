#!/usr/bin/env python3
"""Run the production native package backend against signed fixtures in a fresh chroot.

The caller supplies the native Rust test executable. No host package database,
configuration, keyring or files are modified. Keep the output directory as evidence.
"""
import argparse
import base64
import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def copy_program(root, source, target=None):
    source = Path(source)
    target = root / (target or str(source)).lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    output = run("ldd", source, capture_output=True, text=True).stdout
    for name in re.findall(r"(/[\w/+.@-]+)", output):
        library = Path(name)
        if library.is_file():
            destination = root / name.lstrip("/")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(library, destination)


def tar_entry(archive, path, data):
    member = tarfile.TarInfo(path)
    member.size, member.mode, member.mtime = len(data), 0o644, 1790812800
    archive.addfile(member, io.BytesIO(data))


def fixture(root, keyring):
    repo = root / "opt/distro/repo"
    packages = {
        "manual-app": {},
        "test-dep": {},
        "test-app": {"depend": "test-dep"},
        "test-app2": {"depend": "test-dep"},
        "test-provider-a": {"provides": "test-virtual"},
        "test-provider-b": {"provides": "test-virtual"},
        "test-needs-provider": {"depend": "test-virtual"},
        "test-missing": {"depend": "test-absent>=2"},
        "test-choice-a": {"provides": "test-choice-virtual", "conflict": "manual-app"},
        "test-choice-b": {"provides": "test-choice-virtual", "conflict": "manual-app"},
        "test-choice-client": {"depend": "test-choice-virtual"},
        "test-conflict": {"conflict": "test-app2"},
        "test-unsigned": {},
        "test-corrupt": {},
        "test-file-conflict": {},
        "test-hook-failure": {},
        "test-file-edited": {},
        "test-stale-file": {},
    }
    rows = []
    for name, extra in packages.items():
        archive = repo / f"{name}-1-1-any.pkg.tar.gz"
        # libalpm serializes a legitimate empty optional URL with extra separators.
        info = dict(pkgname=name, pkgver="1-1", pkgdesc="Astraeus disposable native test",
                    url="" if name == "test-app" else "https://example.invalid",
                    builddate="1790812800", packager="Astraeus tests",
                    size="64", arch="any", **extra)
        with tarfile.open(archive, "w:gz") as tar:
            tar_entry(tar, ".PKGINFO", "".join(f"{k} = {v}\n" for k, v in info.items()).encode())
            filename = "collision" if name == "test-file-conflict" else name
            data = (name + "\n").encode()
            path = f"usr/share/astraeus-fixtures/{filename}"
            tar_entry(tar, path, data)
            mtree = (f"#mtree\n/set type=file uid=0 gid=0 mode=644\n./{path} size={len(data)} "
                     f"time=1790812800 sha256digest={hashlib.sha256(data).hexdigest()}\n").encode()
            tar_entry(tar, ".MTREE", gzip.compress(mtree, mtime=1790812800))
        signature = None
        if name != "test-unsigned":
            run("gpg", "--homedir", keyring, "--batch", "--yes", "--detach-sign", archive)
            signature = archive.with_suffix(archive.suffix + ".sig").read_bytes()
        fields = dict(FILENAME=archive.name, NAME=name, VERSION="1-1", DESC=info["pkgdesc"],
                      CSIZE=str(archive.stat().st_size), ISIZE="64", ARCH="any",
                      SHA256SUM=hashlib.sha256(archive.read_bytes()).hexdigest())
        if signature:
            fields["PGPSIG"] = base64.b64encode(signature).decode()
        for key, field in [("depend", "DEPENDS"), ("provides", "PROVIDES"), ("conflict", "CONFLICTS")]:
            if key in extra:
                fields[field] = extra[key]
        rows.append((name, "".join(f"%{key}%\n{value}\n\n" for key, value in fields.items()).encode()))
    db = root / "var/lib/pacman/sync/distro.db"
    with tarfile.open(db, "w:gz") as tar:
        for name, row in rows:
            tar_entry(tar, f"{name}-1-1/desc", row)
    run("gpg", "--homedir", keyring, "--batch", "--yes", "--detach-sign", db)
    (repo / "test-corrupt-1-1-any.pkg.tar.gz").write_bytes(b"corrupted archive\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("requires root for an isolated chroot")
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    root = output / "root"
    for directory in ["usr/bin", "var/lib/pacman/local", "var/lib/pacman/sync", "var/cache/pacman/pkg",
                      "var/log", "etc/pacman.d/hooks", "opt/distro/repo", "dev", "tmp", "proc",
                      "usr/share/astraeus-fixtures"]:
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "tmp").chmod(0o1777)
    for name in ["pacman", "pacman-conf", "gpg", "gpgconf", "gpg-agent", "touch", "false", "sh", "python3"]:
        copy_program(root, shutil.which(name), f"/usr/bin/{name}")
    stdlib = Path(sysconfig.get_path("stdlib"))
    shutil.copytree(stdlib, root / str(stdlib).lstrip("/"), dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "test", "tests", "ensurepip", "idlelib"))
    for module in list(sys.modules.values()):
        source = getattr(module, "__file__", "")
        if source and source.endswith(".so"):
            copy_program(root, source)
    (root / "bin").symlink_to("usr/bin")
    (root / "etc/mtab").symlink_to("/proc/self/mounts")
    copy_program(root, args.test_binary.resolve(), "/usr/bin/native-tests")
    for name, major, minor in [("null", 1, 3), ("zero", 1, 5), ("random", 1, 8), ("urandom", 1, 9)]:
        os.mknod(root / "dev" / name, 0o20666, os.makedev(major, minor))
    keyring = output / "signing"
    keyring.mkdir(mode=0o700)
    run("gpg", "--homedir", keyring, "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
        "--quick-generate-key", "Astraeus isolated package tests", "ed25519", "sign", "1d")
    fixture(root, keyring)
    # Only the public trust material enters the package-test root.
    installed_keyring = root / "etc/pacman.d/gnupg"
    installed_keyring.mkdir(mode=0o700)
    public = run("gpg", "--homedir", keyring, "--export", capture_output=True).stdout
    trust = run("gpg", "--homedir", keyring, "--export-ownertrust", capture_output=True).stdout
    run("gpg", "--homedir", installed_keyring, "--batch", "--import", input=public)
    (installed_keyring / "pubring.gpg").write_bytes(public)
    run("gpg", "--homedir", installed_keyring, "--batch", "--import-ownertrust", input=trust)
    run("gpg", "--homedir", installed_keyring, "--batch", "--check-trustdb")
    run("gpgconf", "--homedir", installed_keyring, "--kill", "all")
    (root / "etc/pacman.conf").write_text("[options]\nArchitecture = x86_64\nCheckSpace\n"
        "SigLevel = Required DatabaseRequired\n[distro]\nSigLevel = Required DatabaseRequired\n"
        "Server = file:///opt/distro/repo\n")
    (root / "var/lib/pacman/local/ALPM_DB_VERSION").write_text("9\n")
    manual = root / "var/lib/pacman/local/manual-app-0-1"
    manual.mkdir()
    (manual / "desc").write_text("%NAME%\nmanual-app\n\n%VERSION%\n0-1\n\n%ARCH%\nany\n\n%SIZE%\n0\n\n%REASON%\n0\n\n")
    (manual / "files").write_text("%FILES%\n\n")
    (root / ".astraeus-native-fixture").write_text("isolated-package-test\n")
    hooks = root / "etc/pacman.d/hooks"
    (hooks / "accept.hook").write_text("[Trigger]\nOperation = Install\nType = Package\nTarget = test-app\n"
        "[Action]\nWhen = PostTransaction\nExec = /usr/bin/touch /hook-ran\n")
    (hooks / "reject.hook").write_text("[Trigger]\nOperation = Install\nType = Package\nTarget = test-hook-failure\n"
        "[Action]\nWhen = PreTransaction\nExec = /usr/bin/false\nAbortOnFail\n")
    command = ["chroot", str(root), "/usr/bin/native-tests", "signed_native_backend", "--ignored", "--nocapture", "--test-threads=1"]
    run("mount", "--bind", root, root)
    try:
        run("mount", "--bind", "/proc", root / "proc")
        try:
            with (output / "native.log").open("w") as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        finally:
            run("umount", root / "proc")
    finally:
        run("umount", root)
    (output / "result.json").write_text(json.dumps(dict(exit_code=result.returncode,
        test_binary_sha256=hashlib.sha256(args.test_binary.read_bytes()).hexdigest(), command=command), indent=2)+"\n")
    print((output / "native.log").read_text())
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
