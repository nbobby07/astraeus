#!/usr/bin/env python3
"""Reproducible ArchISO and installed-payload build glue; Python 3.11+."""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "distro/branding/project.toml"
sys.path.insert(0, str(ROOT / "scripts"))
import installer

CUSTOM_PACKAGES = {"distroctl", "calamares"}
ARCHIVE_DB_LIMIT = 64 * 1024 * 1024


def project():
    data = tomllib.loads(MANIFEST.read_text())
    identity, build = data["identity"], data["build"]
    for value in [identity["id"], identity["version"], build["archiso_version"], build["rust_version"]]:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", value):
            raise ValueError("unsafe metadata token")
    if not re.fullmatch(r"[a-zA-Z0-9 .-]+", identity["name"]):
        raise ValueError("unsafe display name")
    day = dt.datetime.strptime(build["archive_date"], "%Y/%m/%d").replace(tzinfo=dt.timezone.utc)
    if int(day.timestamp()) != build["source_date_epoch"] or build["architecture"] != "x86_64":
        raise ValueError("unsupported architecture or inconsistent build epoch")
    if data["schema_version"] != 1:
        raise ValueError("unsupported metadata schema")
    return data


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def render(text, values):
    for key, value in values.items():
        text = text.replace(f"@@{key}@@", str(value))
    if re.search(r"@@[A-Z0-9_]+@@", text):
        raise ValueError("unresolved template variable")
    return text


def new_directory(path):
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def archive(source, target, epoch):
    """Stable source archive: sorted files, fixed owner/time/mode, no host metadata."""
    with tarfile.open(target, "w:xz", format=tarfile.PAX_FORMAT) as tar:
        for file in sorted(source.rglob("*")):
            if file.is_symlink():
                raise ValueError(f"source symlink not supported: {file}")
            if file.is_file():
                content = file.read_bytes()
                entry = tarfile.TarInfo("platform/" + file.relative_to(source).as_posix())
                entry.size, entry.mtime, entry.mode = len(content), epoch, 0o644
                tar.addfile(entry, io.BytesIO(content))


def prepare_package(output):
    data = project()
    run("cargo", "run", "--locked", "-q", "-p", "distroctl", "--", "validate", MANIFEST, cwd=ROOT)
    out = new_directory(output)
    source = out / "source"
    source.mkdir()
    for file in [ROOT / "Cargo.toml", ROOT / "Cargo.lock", MANIFEST,
                 ROOT / "distro/installed/astraeus-confirm-boot.service", ROOT / "docs/snapshots.md",
                 ROOT / "distro/installed/astraeus-bless-boot.conf", ROOT / "docs/boot-generations.md",
                 *sorted((ROOT / "crates").rglob("*"))]:
        if file.is_file():
            destination = source / file.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, destination)
    run("cargo", "vendor", "--locked", source / "vendor", cwd=ROOT, stdout=subprocess.DEVNULL)
    write(source / ".cargo/config.toml", '[source.crates-io]\nreplace-with = "vendored-sources"\n'
          '[source.vendored-sources]\ndirectory = "vendor"\n')
    archive(source, out / "platform.tar.xz", data["build"]["source_date_epoch"])
    values = {"VERSION": data["identity"]["version"].replace("-", "."), "SHA256": digest(out / "platform.tar.xz"),
              "RUST_VERSION": data["build"]["rust_version"]}
    write(out / "PKGBUILD", render((ROOT / "distro/packages/distroctl/PKGBUILD.in").read_text(), values))
    shutil.copytree(ROOT / "distro/packages/calamares", out / "calamares")
    print(f"Prepared {out}. Run makepkg as a non-root user in the pinned Arch builder.")


def packages(path="distro/archiso/packages.x86_64"):
    return [line.strip() for line in (ROOT / path).read_text().splitlines()
            if line.strip() and not line.startswith("#")]


def upstream_packages():
    return (set(packages()) | set(packages("distro/installed/packages.x86_64"))
            | set(packages("distro/packages/calamares/build-packages.x86_64")) | {"archiso", "rust"}) - CUSTOM_PACKAGES


def check_archive(destination):
    version = run("curl", "--version", capture_output=True, text=True).stdout
    match = re.match(r"curl (\d+)\.(\d+)\.", version)
    if not match or tuple(map(int, match.groups())) < (8, 4):
        raise ValueError("archive verification requires curl 8.4 or later for streaming size limits")
    lock = json.loads((ROOT / "distro/repo/archive.lock.json").read_text())
    if lock["archive_date"] != project()["build"]["archive_date"]:
        raise ValueError("archive lock and manifest disagree")
    if set(lock["direct_packages"]) != upstream_packages():
        raise ValueError("archive lock and package list disagree")
    found = {}
    destination.mkdir(parents=True, exist_ok=False)
    for repo, expected in lock["databases"].items():
        url = f'https://archive.archlinux.org/repos/{lock["archive_date"]}/{repo}/os/x86_64/{repo}.db'
        target = destination / f"{repo}.db"
        try:
            run("curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
                "--max-filesize", ARCHIVE_DB_LIMIT, "--connect-timeout", "20", "--max-time", "60",
                "--output", target, url, timeout=65)
            if target.stat().st_size > ARCHIVE_DB_LIMIT or digest(target) != expected:
                raise ValueError(f"archive database changed or oversized: {url}")
        except (OSError, ValueError, subprocess.SubprocessError):
            target.unlink(missing_ok=True)
            raise
        target.chmod(0o444)
        with tarfile.open(target) as tar:
            for entry in tar:
                if entry.name.endswith("/desc"):
                    desc = tar.extractfile(entry).read().decode()
                    name = desc.split("%NAME%\n")[1].splitlines()[0]
                    version = desc.split("%VERSION%\n")[1].splitlines()[0]
                    found[name] = version
    missing = upstream_packages() - found.keys()
    if missing:
        raise ValueError(f"packages absent from locked snapshot: {sorted(missing)}")
    for name, version in lock["direct_packages"].items():
        if found.get(name) != version:
            raise ValueError(f"version mismatch: {name}")
    print(f"Verified both database hashes and {len(upstream_packages())} upstream package names.")
    return lock["databases"]


def verify_archive_files(directory, hashes):
    for repo, expected in hashes.items():
        if digest(directory / f"{repo}.db") != expected:
            raise ValueError(f"verified archive database changed: {repo}")


def pinned_archive_config(config, directory):
    archive = project()["build"]["archive_date"]
    server = f"https://archive.archlinux.org/repos/{archive}/$repo/os/$arch"
    # CacheServer supplies packages only; metadata can only come from verified local files.
    return config.replace(f"Server = {server}",
                          f"CacheServer = {server}\nServer = {directory.as_uri()}")


def create_profile(out, repo, fingerprint):
    data = project()
    repo = repo.resolve(strict=True)
    if not re.fullmatch(r"[A-F0-9]{40}", fingerprint):
        raise ValueError("supply the full uppercase 40-hex primary signing fingerprint")
    # Pacman configuration values are line-oriented; reject paths that could inject directives.
    if any(c.isspace() for c in str(repo) + str(out)) or not repo.is_dir():
        raise ValueError("build/repository paths must be directories without whitespace")
    required = ["distro.db", "distro.db.sig", "repository-key.asc"]
    if any(not (repo / file).is_file() for file in required):
        raise ValueError("repository is missing its database, signature or public key")
    profile = out / "profile"
    shutil.copytree(ROOT / "distro/archiso", profile)
    keyring = out / "keyring"
    keyring.mkdir(mode=0o700)
    # Check identity in a throwaway keyring before importing or locally trusting the key.
    result = run("gpg", "--homedir", keyring, "--batch", "--with-colons", "--show-keys",
                 repo / "repository-key.asc", capture_output=True, text=True)
    primary = []
    want = False
    for line in result.stdout.splitlines():
        fields = line.split(":")
        if fields[0] == "pub":
            want = True
        elif fields[0] == "fpr" and want:
            primary.append(fields[9])
            want = False
    if primary != [fingerprint]:
        raise ValueError("exported public key does not match the supplied primary fingerprint")
    for args in [("--init",), ("--populate", "archlinux"), ("--add", repo / "repository-key.asc"),
                 ("--lsign-key", fingerprint)]:
        run("pacman-key", "--gpgdir", keyring, *args)
    values = dict(ID=data["identity"]["id"], NAME=data["identity"]["name"],
                  VERSION=data["identity"]["version"], ARCHIVE=data["build"]["archive_date"],
                  KEYRING=keyring, REPO=repo, FINGERPRINT=fingerprint, EPOCH=data["build"]["source_date_epoch"])
    for template in sorted(profile.rglob("*.in")):
        write(template.with_suffix(""), render(template.read_text(), values))
        template.unlink()
    root = profile / "airootfs"
    shutil.copytree(repo, root / "opt/distro/repo", symlinks=False)
    write(root / "usr/share/distro/repository-key.asc", (repo / "repository-key.asc").read_text())
    write(root / "usr/local/libexec/live-smoke.sh", (ROOT / "tests/boot/live-smoke.sh").read_text())
    write(root / "etc/pacman.conf", render((ROOT / "distro/archiso/pacman.conf.in").read_text(),
          dict(values, KEYRING="/etc/pacman.d/gnupg", REPO="/opt/distro/repo")))
    # Archive transfers can stall beyond pacman's ten-second low-speed timeout.
    build_config = profile / "pacman.conf"
    write(build_config, build_config.read_text().replace("[options]\n", "[options]\n"
          "XferCommand = /usr/bin/curl -fL --retry 3 --retry-all-errors --connect-timeout 20 --max-time 300 -o %o %u\n", 1))
    write(build_config, pinned_archive_config(build_config.read_text(), out / "archive"))
    write(root / "etc/os-release", f'NAME="{values["NAME"]}"\nPRETTY_NAME="{values["NAME"]} (Live installer)"\n'
          f'ID={values["ID"]}\nID_LIKE=arch\nVERSION_ID={values["VERSION"]}\nVARIANT_ID=development\n')
    write(root / "etc/issue", f'{values["NAME"]}: ephemeral live installation environment\n')
    installer.stage(root, values, write)
    (root / "etc/localtime").symlink_to("/usr/share/zoneinfo/UTC")
    links = {
        "default.target": "/usr/lib/systemd/system/graphical.target",
        "display-manager.service": "/usr/lib/systemd/system/sddm.service",
        "systemd-firstboot.service": "/dev/null",
        "multi-user.target.wants/NetworkManager.service": "/usr/lib/systemd/system/NetworkManager.service",
        "multi-user.target.wants/live-keyring.service": "/etc/systemd/system/live-keyring.service",
        "graphical.target.wants/live-smoke.service": "/etc/systemd/system/live-smoke.service",
        "sysinit.target.wants/systemd-timesyncd.service": "/usr/lib/systemd/system/systemd-timesyncd.service",
    }
    for name, target in links.items():
        link = root / "etc/systemd/system" / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
    return profile


def build_iso(output, repo, fingerprint):
    data = project()
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise ValueError("ISO builds require an x86_64 Arch Linux builder; see docs/building.md")
    if os.geteuid() != 0:
        raise ValueError("mkarchiso build must run as root inside a disposable Arch builder")
    for tool in ["mkarchiso", "pacman", "pacstrap", "pacman-key", "gpg", "xorriso", "mksquashfs", "curl"]:
        if not shutil.which(tool):
            raise ValueError(f"required build tool unavailable: {tool}")
    version = run("pacman", "-Q", "archiso", capture_output=True, text=True).stdout.split()[1]
    if version != data["build"]["archiso_version"]:
        raise ValueError(f"archiso version must be {data['build']['archiso_version']}, got {version}")
    out = new_directory(output)
    archive_hashes = check_archive(out / "archive")
    profile = create_profile(out, repo, fingerprint)
    env = dict(os.environ, SOURCE_DATE_EPOCH=str(data["build"]["source_date_epoch"]), TZ="UTC", LC_ALL="C")
    values = dict(ID=data["identity"]["id"], NAME=data["identity"]["name"], VERSION=data["identity"]["version"],
                  ARCHIVE=data["build"]["archive_date"], EPOCH=data["build"]["source_date_epoch"], FINGERPRINT=fingerprint)
    verify_archive_files(out / "archive", archive_hashes)
    installer.build_payload(out, profile, values, lambda *a, **kw: run(*a, env=env, **kw), write, render)
    verify_archive_files(out / "archive", archive_hashes)
    run("mkarchiso", "-v", "-w", out / "work", "-o", out / "iso", profile, env=env)
    with (out / "builder-packages.txt").open("w") as builder_log:
        run("pacman", "-Q", stdout=builder_log)
    with (out / "image-packages.txt").open("w") as image_log:
        run("pacman", "--root", out / "work/x86_64/airootfs", "-Q", stdout=image_log)
    write(out / "inputs.json", json.dumps({"project": data, "repository_key": fingerprint,
          "archive_databases": archive_hashes,
          "repository": {p.name: digest(p) for p in sorted(repo.iterdir()) if p.is_file()},
          "sources": {p.relative_to(ROOT).as_posix(): digest(p) for folder in ["crates", "distro", "scripts"]
                      for p in sorted((ROOT / folder).rglob("*")) if p.is_file() and "__pycache__" not in p.parts},
          "cargo_lock_sha256": digest(ROOT / "Cargo.lock")}, indent=2) + "\n")
    write(out / "iso/SHA256SUMS", "".join(f"{digest(p)}  {p.name}\n" for p in sorted((out / "iso").glob("*.iso"))))
    print(f"ISO built at {out / 'iso'}. Boot validation is still required.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    package = sub.add_parser("package", help="vendor locked Cargo sources and prepare a makepkg input")
    package.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify-archive", help="check snapshot hashes and package availability over HTTPS")
    verify.add_argument("--output", type=Path, help="retain verified databases in a new directory")
    iso = sub.add_parser("iso", help="build on a disposable pinned Arch Linux machine")
    iso.add_argument("--output", type=Path, required=True)
    iso.add_argument("--repo", type=Path, required=True)
    iso.add_argument("--fingerprint", required=True)
    args = parser.parse_args()
    try:
        if args.command == "package":
            prepare_package(args.output)
        elif args.command == "verify-archive":
            if args.output:
                check_archive(args.output)
            else:
                with tempfile.TemporaryDirectory() as temp:
                    check_archive(Path(temp) / "archive")
        else:
            build_iso(args.output, args.repo, args.fingerprint)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError, tarfile.TarError) as error:
        parser.exit(1, f"bootstrap: {error}\n")


if __name__ == "__main__":
    main()
