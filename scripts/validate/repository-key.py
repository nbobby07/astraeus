#!/usr/bin/env python3
"""Check the disposable repository signer before spending time on a candidate."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

MINIMUM_VALIDITY_SECONDS = 72 * 60 * 60


def inspect(listing, fingerprint, now):
    if not re.fullmatch(r"[A-F0-9]{40}", fingerprint):
        raise ValueError("expected one full uppercase primary fingerprint")
    rows = [line.split(":") for line in listing.splitlines() if line]
    keys = [row for row in rows if row[0] in {"pub", "sub", "sec", "ssb"}]
    fingerprints = [row[9] for row in rows if row[0] == "fpr" and len(row) > 9]
    # shortcut: validators use one primary signer; extend this check before introducing signing subkeys.
    if len(keys) != 1 or keys[0][0] != "pub" or fingerprints != [fingerprint]:
        raise ValueError("expected exactly the selected disposable public primary, without subkeys")
    key = keys[0]
    if len(key) < 12 or key[1] in {"r", "e", "d", "i"} or "D" in key[11] or "s" not in key[11]:
        raise ValueError("repository primary is not an enabled signing key")
    created, expires = int(key[5]), int(key[6] or "0")
    if created <= 0 or created > now or expires <= created:
        raise ValueError("disposable signer needs a valid creation time and finite expiry")
    if expires <= now + MINIMUM_VALIDITY_SECONDS:
        raise ValueError("repository signer has less than 72 hours of remaining validity")
    return {
        "schema_version": 1,
        "fingerprint": fingerprint,
        "checked_unix": now,
        "expires_unix": expires,
        "expires_utc": dt.datetime.fromtimestamp(expires, dt.timezone.utc).isoformat(),
        "minimum_remaining_seconds": MINIMUM_VALIDITY_SECONDS,
        "scope": "Disposable validation repository only; package signatures are verified separately.",
    }


def check(path, fingerprint, now=None):
    if not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024:
        raise ValueError("repository public key must be a nonempty file of at most 1 MiB")
    with tempfile.TemporaryDirectory(prefix="astraeus-key-preflight-") as home:
        result = subprocess.run(
            ["gpg", "--homedir", home, "--no-options", "--batch", "--with-colons",
             "--with-fingerprint", "--show-keys", str(path.resolve())],
            check=True, capture_output=True, text=True, timeout=30,
        )
    return inspect(result.stdout, fingerprint, int(time.time()) if now is None else now)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("public_key", type=Path)
    parser.add_argument("fingerprint")
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.public_key, args.fingerprint), indent=2))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Repository key preflight failed: {error}\n")


if __name__ == "__main__":
    main()
