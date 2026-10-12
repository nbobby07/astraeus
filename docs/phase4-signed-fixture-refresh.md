# Phase 4.1 signed validation fixture refresh

The blocked **K dependency-mismatch case now passes** in an installed Astraeus
guest. Tested October 11, 2026, Pacific time; raw timestamps are UTC. K has passing
evidence for all 17 cases across two runs: the previous 16 passes plus this one
targeted rerun. The other 16 cases were not rerun here.

**PHASE 4.1 GUEST REQUALIFICATION INCOMPLETE** remains the overall verdict. The
original full GameMode self-test still has a recorded exit 255 and its governor
capability remains unsupported. Gamescope presentation, targeted gaming
transactions and physical GPU qualification remain outstanding as previously
classified. No acceptance requirement was relaxed.

## Fixture provenance and trust boundary

This follows commit `3163c86f75c8cd226456dd6b30b1c5b683f830cc` on
`phase4/runtime-requalification`. Production source remains
`cac8998ad7730e69ae354c3162ef4a0677cfc162`. The original signed ISO, installed
baseline, firmware and enrolled trust state were reused; no ISO was rebuilt.
The baseline disk and VARS hashes were verified before and after the new overlay.
The previous guest and its failed evidence were not modified.

The existing `distro.db` was signed without changing one byte of its contents.
Its hash was asserted against the previously preserved baseline before signing.
A dedicated Ed25519 signing key was generated in the disposable guest with a
seven-day lifetime. The detached signature was verified against its exact
fingerprint. Only the public key, signature and database are exported.

| Input | Identity |
| --- | --- |
| Database SHA-256, unchanged | `7f3515f1cdc3453ed606340f2ac0715faf0e327898e9b51de1f7ec5d975d6dca` |
| New signer fingerprint | `266918787E6570FD0B4B6E889E8A79CE8852B557` |
| Key created, UTC | `2026-10-12T02:04:22Z` |
| Key expires, UTC | `2026-10-19T02:04:22Z` |
| New signature SHA-256 | `06c10c15983135ec7c830c403ae12a71dcd64fbbfc0de290352d8008c174391c` |
| Public key SHA-256 | `14544fcfa0a8a1ad4722d0470eaaec99d8c5132bdacf33920dc8ea886c821487` |

Both `/etc/pacman.d/gnupg` and `/var/lib/pacman/sync` were overlaid inside a
private mount namespace. The new key was imported and locally signed there
using `pacman-key`. The test used the unchanged production CLI and unchanged
`phase4_negatives.py --case dependency-mismatch` in a nested private namespace.
The parent guest never received the new trust entry or replacement signature.
No clock adjustment, package transaction or signature-policy override occurred.

The actual effective `distro` policy remained `PackageRequired`,
`PackageTrustedOnly`, `DatabaseRequired`, `DatabaseTrustedOnly`. Existing embedded
package signatures were not refreshed. This fixture qualifies database selection
and the dry-run guard only; it is not a repository qualified for package installation.
The temporary signing home was removed on test completion; its private key was
not exported. Future runs after expiry require a new explicitly recorded fixture.

## Actual guest results

| Check | Actual exit | Result |
| --- | --- | --- |
| Original expired database signature | 1 | Expected rejection preserved |
| Fresh signature before granting namespace trust | 1 | Unknown signer rejected |
| Correctly signed database with namespace trust | 0 | Database accepted |
| Database tampered after signing | 1 | Invalid signature rejected |
| Original database bytes restored under fresh signature | 0 | Database accepted again |
| `distroctl update --dry-run --json` with Mesa/lib32-Mesa mismatch | 1 | Intended guard reached; PASS |
| Unchanged dependency-case collector | 0 | All original assertions passed |

The exact CLI error was:

```text
distroctl: inconsistent graphics package state: mesa and lib32-mesa must have matching upstream versions; entire plan rejected
```

The [raw case and signature controls](evidence/phase4-signed-fixture-refresh/fixture-result.json)
retain exact commands, output, exit codes and times. The
[supplemental matrix](evidence/phase4-signed-fixture-refresh/matrix.json) links to
the previous run and records the cumulative K result without rewriting it.

After leaving the namespace, all regular-file hashes in the original keyring,
installed-package database and sync databases matched their initial values.
`pacman.conf`, installed binaries, package lists, history and snapshots also
matched. Secure Boot remained enforcing with the original certificate. Temporary
autologin was removed, and QEMU shut down normally with exit 0.

## Evidence, checks and cleanup

New scripts passed local Python compilation and their actual guest assertions.
The local Windows Python suite ran 119 tests: 72 passed, 47 platform skips.
Production and canonical test code did not change, so the previous Rust,
formatting, Clippy and Linux Python results were retained rather than repeated.

The [public manifest](evidence/phase4-signed-fixture-refresh/FILES.json) binds the
new records and signed fixture. The complete private export is
`D:\Astraeus-Phase41-Requalification-Evidence\private\fixture-refresh-raw.tar.gz`:
192,869 bytes, SHA-256
`f8271b7c6f4aa8c546233085086fd1647a216d98100cbdb9bd1cbcddef22784a`.
All 84 payload hashes were verified after download. No historical evidence
bundle was overwritten. The exported detached signature also passed an independent
local GPG verification against the recorded fingerprint in a temporary keyring.

Validator `vm-9350aa5ae5534cc0a68551e6e040bcf2` is paused, with no nested QEMU
processes remaining. This follow-up added 146 seconds of active use; cumulative
active use is 3,486 seconds, below the original two-hour ceiling. At the previously
recorded rates, incremental compute plus active storage is approximately $0.015
before allowances. Transfer is unmetered locally; paused storage remains
$0.005504/hour before allowances. Resources and billing settings did not change.

The changes are prepared on the existing requalification branch for review and
integration into PR #7. No branch was pushed or merged. Original development and
integration worktrees are unchanged. Phase 4.2 and Phase 5 were not started.
