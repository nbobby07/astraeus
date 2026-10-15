#!/usr/bin/env python3
"""Verify gaming package records against pinned archive DBs. No install or extraction."""
import hashlib
import argparse
import io
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "crates/distroctl/src/gaming/catalog.json"
LIMIT = 64 * 1024 * 1024


def verify_database(data, repository, catalog):
    if len(data) > LIMIT or hashlib.sha256(data).hexdigest() != catalog["databases"][repository]:
        raise ValueError(f"{repository}: database hash/size mismatch")
    expected = {name: record for name, record in catalog["packages"].items()
                if record["repository"] == repository}
    found = set()
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive:
            if not member.name.endswith("/desc"):
                continue
            if not member.isfile() or member.size > 256 * 1024:
                raise ValueError("invalid package metadata member")
            blocks = archive.extractfile(member).read().decode().strip().split("\n\n")
            fields = {lines[0].strip("%"): lines[1:] for block in blocks
                      if (lines := block.splitlines())}
            name = fields["NAME"][0]
            if name not in expected:
                continue
            if name in found:
                raise ValueError(f"duplicate package: {name}")
            actual = {"repository": repository, "version": fields["VERSION"][0],
                      "sha256": fields["SHA256SUM"][0], "depends": fields.get("DEPENDS", []),
                      "provides": fields.get("PROVIDES", [])}
            if actual != expected[name]:
                raise ValueError(f"package metadata mismatch: {name}")
            found.add(name)
    if found != expected.keys():
        raise ValueError(f"packages absent: {sorted(expected.keys() - found)}")
    return len(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--databases", type=Path, help="existing pinned repository databases; no network requests")
    args = parser.parse_args()
    catalog = json.loads(CATALOG.read_text())
    base = json.loads((ROOT / "distro/repo/archive.lock.json").read_text())
    if catalog["archive_date"] != base["archive_date"]:
        raise ValueError("gaming catalog and base snapshot differ")
    if catalog["databases"] != base["databases"]:
        raise ValueError("gaming and base databases differ")
    for name, record in catalog["packages"].items():
        if base["direct_packages"].get(name) != record["version"]:
            raise ValueError(f"gaming version missing from archive lock: {name}")
    for repo in catalog["databases"]:
        url = f'https://archive.archlinux.org/repos/{catalog["archive_date"]}/{repo}/os/x86_64/{repo}.db'
        if args.databases:
            with (args.databases / f"{repo}.db").open("rb") as stream:
                data = stream.read(LIMIT + 1)
        else:
            with urllib.request.urlopen(url, timeout=60) as response:
                if not response.url.startswith("https://"):
                    raise ValueError("archive redirected away from HTTPS")
                data = response.read(LIMIT + 1)
        count = verify_database(data, repo, catalog)
        print(f"Verified {repo} database and {count} gaming package records")
    print("Metadata verification only; package signatures, dependency resolution and runtime remain separate gates.")


if __name__ == "__main__":
    main()
