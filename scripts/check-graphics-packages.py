#!/usr/bin/env python3
"""Check graphics metadata and optionally solve each bundle with isolated pacman DBs.

No package installation, refresh, or host database mutation. Input databases must
match archive.lock.json. Run bootstrap.py verify-archive to obtain them.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def check(directory, pacman=None):
    archive = json.loads((ROOT / "distro/repo/archive.lock.json").read_text())
    locked = json.loads((ROOT / "distro/graphics/packages.lock.json").read_text())
    bundles = json.loads((ROOT / "distro/graphics/bundles.json").read_text())
    if locked["archive_date"] != archive["archive_date"]:
        raise ValueError("graphics and repository dates disagree")
    records = {}
    for repository, digest in archive["databases"].items():
        path = directory / (repository + ".db")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"database hash mismatch: {repository}")
        with tarfile.open(path) as database:
            for member in database:
                if member.name.endswith("/desc"):
                    fields = {p.splitlines()[0].strip("%"): p.splitlines()[1:]
                              for p in database.extractfile(member).read().decode().strip().split("\n\n")}
                    records[fields["NAME"][0]] = dict(repository=repository, version=fields["VERSION"][0],
                        depends=fields.get("DEPENDS", []), provides=fields.get("PROVIDES", []),
                        conflicts=fields.get("CONFLICTS", []), sha256=fields["SHA256SUM"][0], filename=fields["FILENAME"][0])
    for name, expected in locked["packages"].items():
        if records.get(name) != expected:
            raise ValueError(f"graphics package metadata mismatch: {name}")
        if archive["direct_packages"].get(name) != expected["version"]:
            raise ValueError(f"graphics version missing from archive lock: {name}")
    resolved = {}
    if pacman:
        with tempfile.TemporaryDirectory(prefix="astraeus-graphics-resolve-") as temporary:
            root = Path(temporary)
            for name in ["root", "db/local", "db/sync", "cache", "gpg", "hooks"]:
                (root / name).mkdir(parents=True)
            for repo in archive["databases"]:
                shutil.copyfile(directory / (repo + ".db"), root / "db/sync" / (repo + ".db"))
            (root / "db/local/ALPM_DB_VERSION").write_text("9\n")
            config = root / "pacman.conf"
            config.write_text(f"[options]\nRootDir = {root}/root\nDBPath = {root}/db\nCacheDir = {root}/cache\n"
                f"GPGDir = {root}/gpg\nLogFile = {root}/pacman.log\nHookDir = {root}/hooks\n"
                "Architecture = x86_64\nSigLevel = Required DatabaseOptional\nLocalFileSigLevel = Required\n" +
                "".join(f"[{repo}]\nServer = https://archive.archlinux.org/repos/{archive['archive_date']}/$repo/os/$arch\n"
                        for repo in archive["databases"]))
            cases = dict(bundles["bundles"])
            cases["base"] = []
            cases["amd-intel-nouveau"] = sorted({p for b in ["amd", "intel", "nouveau"] for p in bundles["bundles"][b]})
            cases["build"] = bundles["build"]
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            for bundle, packages in cases.items():
                result = subprocess.run([pacman, "--config", str(config), "--sync", "--print-format", "%n\t%v",
                    "--noconfirm", *sorted(set(bundles["base"] + packages))], check=True,
                    capture_output=True, text=True, timeout=60)
                resolved[bundle] = dict(line.split("\t") for line in result.stdout.splitlines())
                for name in packages + bundles["base"]:
                    if resolved[bundle].get(name) != records[name]["version"]:
                        raise ValueError(f"resolver changed requested graphics input: {name}")
            after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            if before != after:
                raise ValueError("print-only resolver changed its isolated inputs")
    return {"schema_version": 1, "archive_date": archive["archive_date"], "databases": archive["databases"],
            "verified_packages": len(locked["packages"]), "resolved": resolved,
            "package_installation_tested": False, "hardware_tested": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("databases", type=Path)
    parser.add_argument("--pacman", help="optional pacman executable for a read-only dependency solve")
    args = parser.parse_args()
    print(json.dumps(check(args.databases.resolve(), args.pacman), indent=2))
