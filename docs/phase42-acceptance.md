# Phase 4.2 implementation and acceptance

Status: **in progress, not qualified for release**. A required gate that fails or
has not run leaves this milestone incomplete. This report will be updated with
candidate identities and exported evidence after the integrated acceptance run.

The current runtime candidate is `620d1d3edf9ba596d22e762591c296267951a81f`.
Its clean-build source archive is 4,982,528 bytes with SHA256
`00b4bcc311aacb96787289bab0be428f6f1d06b446870f3b2e01cb793701e030`.
Earlier stopped build attempts remain preliminary evidence and do not qualify this
candidate. Later validation-only commits are recorded separately from runtime.

The `85ad8f6` package build failed because its generated source archive omitted
two native policy inputs. Candidate `9b0fb7a` includes those files and adds an
archive regression covering literal Rust file inclusions. The failed build's
logs remain evidence, not a passing package gate. Host native checks below ran
on `85ad8f6`; this packaging fix has three passing focused tests, with clean
candidate package and image builds still required.

Candidate `9b0fb7a`, attempt A/r1, was interrupted by an outer-validator reset at
2026-10-13 22:30:39 UTC during native compilation. Its boot identity changed and
the filesystem reported an unclean restart; no normal compiler/build exit, OOM
event or graceful host shutdown was recorded. Source and base hashes, package
manager checks, qcow2 consistency and KVM checks passed afterward. This attempt
does not count as a completed build. Its thin evidence archive is
`interrupted-9b0fb7a-r1-A-evidence.tar.gz` (102,533 bytes), SHA256
`cc03796ed7bfe27270241c9e86f3cdffe53ecdc7ff27b4fa2e09ee166926a9da`.

Attempt A/r2 completed native CLI and Qt compilation, then failed its package
check because the generated source archive omitted the installer helpers used by
the Rust image-seeding test. The transaction suite recorded 52 passes, one failure
and one ignored fixture. The builder exited 4 and shut down normally; no package
or ISO is accepted from this attempt. Its thin archive is
`failed-9b0fb7a-r2-A-evidence.tar.gz` (83,821 bytes), SHA256
`eda0b7cc5f558196bb86094c687c7080837386f90d9c423d528554ac0203cbed`.

Candidate `30e2991` includes both helper scripts. Before starting another cloud
build, its real vendored package source archive was extracted and tested locally:
the native Rust workspace passed 155 tests with five ignored fixtures, and the
native desktop passed 21 controller and 12 QML tests with KDE/Breeze. The new
isolated archive regression reproduced the missing-module failure before the fix
and passed afterward. These are host checks; the pinned cloud package checks and
two independent image builds remain required.

The clean Arch build of `30e2991` passed the native Rust workspace, then failed
both Qt test groups. Arch's debug-path remapping prevented the controller tests
from finding source-relative fixtures. The QML group passed 11 of 12 checks;
its strict warning check caught the missing Sonnet spelling backend in the
minimal builder. No package or ISO is accepted from this attempt. Its thin
archive is `failed-30e2991-r1-A-evidence.tar.gz` (91,804 bytes), SHA256
`526ed122ca51d9a5e496543990ceeabb3f9fee8905c899871c917717962c0000`.

Candidate `620d1d3` copies the controller fixture into the test build directory
and declares pinned Hunspell 1.7.4-1 as the KDE spelling backend, without adding
a dictionary. The fixture failure was reproduced locally with Arch-style
debug-path remapping: the old controller run passed 3 checks and failed 18; the
corrected extracted archive passed all 21. Its 12 QML checks and 155 native Rust
tests also passed. Archive verification checks 118 package names against the
same three pinned repository database hashes. The clean Arch package build has
now passed the same 155 native Rust tests and both Qt groups (21 controller and
12 QML checks). The split packages and Calamares were built and their repository
signatures verified. ISO assembly and installed-VM acceptance are still pending.

The immutable VM harness is `13f573cd5d303c92acc4dcfb43cd9e1127423c7c`,
exported as a 358,400-byte archive with SHA256
`41e8c3db8dce243939e07c11678c022c10a6dedc119b701e60b5e90528892c46`.

The branch starts at `b1d16953ce5918b23c772e3ce99a35c7d37ac6b5`.
Work is isolated on `codex/phase4-system-management`; PR #7, the original
development branches and the signed USB artifacts are separate.

## Implementation boundary

`SystemConfig` manages selected named packages and gaming features. Omission does
not make an installed package unwanted. Pre-existing applications remain
protected; adoption creates a draft without changing installation reasons or
ownership. The build records the actual protected base/graphics closure before
installing optional gaming requests.

Removal also requires complete installed-file verification against the package's
MTREE SHA256 records. Locally changed or unverifiable packages are retained and
their removal ownership is relinquished. The review digest includes that evidence;
the locked worker checks it again immediately before committing.

The Linux-only native feature pins `alpm` 5.0.2 with its libalpm 16 ABI check.
Prepared native transactions provide the dependency closure. Adding applications
includes the synchronized upgrade set from the approved existing databases.
Preview does not refresh metadata. Every apply rechecks the reviewed digest under
the coordinator locks. Ambiguous providers require a selection; replacement,
driver-family, kernel, loader and coordinator transitions remain restricted.

Applied configuration lives at `/etc/astraeus/system.toml`. Ownership and
`system.lock` live under `/var/lib/astraeus/management` in the snapshotted root.
The lock records resolution provenance; it does not make the machine hermetic.
Configuration-only mutations require snapshots, signing and a new verified boot.
The v2 history format reads and transactionally migrates v1 history without
rewriting its historical records. Old snapshots remain inspectable; incompatible
recovery coordinators cannot restore the new management state routinely.

The unprivileged Qt/Kirigami app uses versioned JSON from the same backend as the
CLI. After review, pkexec authenticates a bounded submission. An operation ID
connects the app to the non-enabled systemd worker and durable history. The worker
has no automatic restart or boot replay. Sleep and normal shutdown are inhibited
while it applies. Live sessions permit inspection and planning only.

## Checks so far

| Gate | Current evidence |
| --- | --- |
| Host Rust checks | Windows workspace 140 passed; native Linux workspace 155 passed with 5 fixture/privileged tests ignored by the normal run. Native all-target Clippy passed; earlier Windows Clippy evidence is retained |
| Python, shell and signing | Full Python suites passed: Windows 121 passed/58 skipped, Linux root 175 passed/4 skipped. The 11 Linux file-integrity fixtures also passed explicitly. Shell syntax and native signing checks passed; raw logs and platform skips remain in the host evidence |
| Linux snapshot lock tests | Passed with a real libalpm-compatible lock descriptor and isolated Btrfs/FAT loopback filesystems |
| Native libalpm compilation | Passed with libalpm 16 in both the Linux development environment and the pinned Arch package build |
| Signed native package fixtures | Attempt 13 passed installation, synchronized upgrades, removal, shared/manual package preservation, metadata changes, providers, signatures, corrupt archives, hooks, file conflicts, locks, changed reasons and changed file contents. It also checks named conflicts, versioned missing dependencies and provider choices retained when preparation fails |
| Management publication failures | Real filesystem tests passed at the configuration, lock and ownership write boundaries; mixed state and retries are refused, and pending evidence remains available |
| Native desktop build and tests | 21 Qt controller and 12 QML tests passed with Rust-generated contracts in both the development environment and the pinned Arch package build. Production startup loaded the KDE desktop style; installed-VM backend acceptance pending |
| Plain and LUKS2 installed VMs with enforced Secure Boot | Not run on the new candidate yet |
| Two byte-identical candidate images | Not built yet |
| Physical PC and USB boot | Deferred by request |

The native fixture runner is `scripts/validate/native-alpm.py`. It creates a new
root, small signed packages and its own test keyring, then executes the production
backend from a native Rust test binary inside that chroot. It never replaces the
host package database. Earlier failed fixture attempts are retained separately.
These tests do not establish installed-VM boot, authorization or recovery behavior.

The approved VM setup uses the existing installer in SetupMode, then enrolls the
disposable owner and verifies enforcing installed boots. All management and
recovery acceptance runs must keep Secure Boot enforcing. Live inspection must
use the signed, RAM-verified recovery medium. The initial setup-mode ISO does not
qualify live management, and this milestone does not add an installer path that
runs with Secure Boot already enforcing.

Phase 4.1's normal Proton diagnostic and recorded negative tests passed. GameMode's
full self-test and physical gaming qualification remain incomplete. Software
rendering is never evidence of physical GPU support.

## Validator budget

Additional compute and active storage are capped at $10. Published rates were
checked before starting: $0.04032/vCPU-hour, $0.0129/GiB-memory-hour and
$0.000086/GiB-storage-hour. The existing 4-vCPU, 16-GiB, 64-GiB validator costs
$0.373184/hour at these rates. A temporary replacement ran for 58 seconds at
4-vCPU, 8-GiB, 32-GiB before it was paused when the original became available.
No billing plan was changed. Final usage and exported evidence are pending.

Before candidate builds, the original validator was paused at 4,759 total runtime
seconds, up from 3,486. Combined additional compute and active storage for both
validators was below $0.14 at that checkpoint.

A later stopped checkpoint recorded 7,421 total runtime seconds on the original
validator. Including the temporary replacement, the conservative additional
compute and active-storage estimate was about $0.42. Building resumed afterward;
final usage remains pending.

Source: [Freestyle VM pricing](https://www.freestyle.sh/docs/vms/pricing-and-limits).
