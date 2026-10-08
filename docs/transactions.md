# Phase 2 transactions

The integrated `distro-transactions` coordinator uses `BtrfsSnapshots`, holding
`MutationGuard` across planning, pre/post snapshots, package mutation and UKI work.
The pre-update snapshot saves the matching UKI before pacman can run hooks. Failed
snapshot creation prevents package application. A candidate post-snapshot and live
checks lead to `awaiting_boot`, never immediate success.

`distroctl confirm-boot [ID]` verifies a different kernel boot ID, embedded command line and kernel release, root identity, saved/current UKI hash, package map
and required system health. The regenerated UKI includes a transaction marker. The checker permits only the
ordered console suffixes added by systemd-stub 262 when the embedded command line
has no console parameter. Root, LUKS, transaction and all other embedded arguments
must remain unchanged; extra boot-mode arguments are refused. This behavior is
specified in [systemd's console detection](https://github.com/systemd/systemd/blob/v262/src/boot/console.c).
The installed systemd oneshot runs after NetworkManager, SDDM and logind. It has no
timer-based promotion. Failed observations remain pending, are retained in
`boot_attempts`, and block new updates. Explicit retries collect fresh evidence.
Completed confirmation is idempotent. Older transactions cannot be promoted after
later nonempty updates. Pre-snapshots are marked known-good only after checking the
already booted baseline and system health; previous known-good snapshots survive.

`distroctl finalize-rollback ID` verifies the restored root's parent UUID against
the pre-snapshot, the matching UKI, original complete package map and post-boot
health before recording `rolled_back`. Offline execution remains mandatory.
The boot service can also recognize an awaiting transaction restored offline.
Failures in history or metadata persistence leave a pending record for retry.
Snapshot metadata and SQLite are separate durable stores, not one atomic commit.

These are implemented interfaces, **not installed-system acceptance evidence**.
See [integration acceptance](phase2-integration.md) for actual results.

## Commands

```sh
distroctl update --dry-run
distroctl update --dry-run --json
distroctl history
distroctl history --json
distroctl history --database /path/to/copied/transactions.sqlite --json
sudo distroctl update
```

Planning and history do not request root. An absent history database yields an
empty list without creating a directory or file. History opens SQLite read-only
and does not run migrations or recover unfinished transactions. Resolution failures
return an error before a plan/history record exists. `--database` is
only a history-reading option; privileged update paths cannot be overridden by
arguments or environment variables. There is no setuid executable or daemon.

## Data and planning

`CurrentSystemState`, `DesiredUpdate`, `PackagePlan`, `ExecutionPlan`,
`TransactionRecord`, `HealthCheckResult` and `TransactionOutcome` are serializable
Rust types independent of terminal formatting. Plan/record JSON schema version is
1. State identifiers hash the sorted installed package/version map with SHA-256;
they are not filesystem hashes or snapshot generation identifiers. Timestamps are
Unix seconds in UTC. Unobserved resulting state and snapshot references are null.

The pacman adapter uses `pacman --query` for installed names/versions and
`pacman --sync --sysupgrade --print-format` with explicit tab-delimited fields for
resolved targets. It never runs `--refresh` during planning. Results describe the
existing sync databases, including the pinned archive repositories shipped by
Phase 1. Refresh/channel selection is not implemented by this branch.

Installed sizes come from pacman's tagged local `desc` records and sync database
members, read through `bsdtar -xOf`. It does not scrape localized `pacman -Si`
output. Identity/version/SHA-256 are cross-checked against resolved targets.
Archive bytes come from the sync database's `CSIZE`, because pacman's `%s`
reports remaining download size and becomes zero for cached archives. This was
confirmed by the native pacman regression after an installed-system update exposed
plan drift following download. Download bytes conservatively include cached archives. Installed delta
is the sum of new installed sizes minus old sizes. Missing/malformed sizes,
checksums, duplicate names, arithmetic overflow or changed installed state fail
planning rather than inventing data.

The general model supports install, upgrade and removal. This initial pacman
adapter refuses any candidate declaring conflicts or replacements because the
print interface does not expose a complete removal set. That refusal can include
harmless conflicts. It must not be relaxed until a complete libalpm transaction
resolver and corresponding replacement/removal tests are integrated. Alternative
root/database/cache layouts are also refused. A no-change plan needs no snapshot.

Every nonempty plan conservatively requests UKI regeneration and bootloader
update. This covers hooks and arbitrary package changes affecting initramfs
inputs, without duplicating Phase 1's trigger lists.

## Execution and failure semantics

```text
planned -> preparing -> downloaded -> snapshot_pending -> snapshot_created
        -> applying -> validating -> awaiting_boot -> succeeded
```

`downloaded` means pacman's download and verification phases both returned
success. Failure before `applying` becomes `failed`; failure from `applying`
onward becomes `rollback_required`. `rolled_back` is a separate state and never
inferred from a rollback request. Invalid/skipped/terminal transitions fail.
Only an empty plan may move directly from `planned` to `succeeded`.

The coordinator persists intent before each external phase, the snapshot
reference before package mutation, and health results before aggregation. It
checks the resolved plan again immediately before applying, then checks the
observed complete installed package set against the expected result. Failed
commands, missing required health observations, cancellation and persistence
errors cannot produce a success report. Error records retain the failing phase,
message, interruption flag, phase timestamps, package plan and observed results.

The package boundary has separate resolve, prerequisites, download, verify, apply
and current-state operations. Native download and verify each use pacman's normal
download-only transaction, which checks cached package integrity and signatures.
Apply revalidates the full plan, then runs pacman's native system upgrade without
refreshing metadata. Dependencies retain pacman's normal install reasons; passing
every dependency as an explicit target would change those reasons.
`pacman-conf` must report required, trusted package signatures for each repository;
an inherited repository policy is checked against the global policy. No signature
policy is weakened. Pacman still owns dependency/file conflict
checks, archive verification, package scripts, hooks and its database lock.

Prerequisites include root, the standard pacman layout/cache, no existing pacman
lock, database sanity and free space. The disk budget includes all archives plus
the gross size of new installed packages, with a 256 MiB reserve, checked on both
root and cache. UKI work requires another 512 MiB free on `/efi`. These conservative
checks are not guarantees against Btrfs metadata exhaustion, concurrent writes or
ESP exhaustion during hooks. Snapshot-specific capacity and preservation checks
belong to the snapshot backend.

The OS file lock `/run/astraeus-update.lock` serializes Astraeus updates. It remains
held through planning, execution and final persistence and releases on process
exit. The lock file is never unlinked. Native pacman still uses its own lock; this
adapter does not delete it or claim to exclude independent package-management
commands between subprocesses. Do not run another package manager during an
update. Full single-handle libalpm resolution/execution is a future integration
requirement if stronger exclusion is needed.

Cancellation is checked between phases through the library callback. A process
signal/kill leaves the last durable phase for diagnosis. The next updater, after
acquiring the lock, marks unfinished pre-apply records failed and applying or
validating records rollback-required. It never replays a package operation.
An `awaiting_boot` or `rollback_required` record blocks the next update. Read-only
history preserves the recorded phase and does not imply that its owner is alive.
If SQLite cannot persist an error, the caller receives a persistence failure and
the last durable intent remains authoritative.

## Boot and health

Boot work reuses `mkinitcpio -P` and `bootctl --esp-path=/efi --graceful update`.
Both installed systemd-boot EFI copies must then match the packaged x86-64 loader
byte-for-byte. This accepts an already-current loader without ignoring missing
or mismatched files. Independently signed loader overrides are not qualified.
Existing Arch
and Astraeus hooks remain unchanged; the explicit post-transaction commands may
repeat their work so failures have a checked exit status. The snapshot backend
must preserve the current ESP artifacts before any package hook can overwrite
them. A root snapshot alone is insufficient.

Structured checks cover pacman's database, repository configuration,
`ukify inspect` of the product UKI, installed bootloader, failed system units, a writable
root mount, NetworkManager, SDDM, logind and `distroctl info --json`. Spawn/read errors are
`unavailable`, unsuccessful checks are `fail`. All current system checks are
required. Optional checks can warn or be unavailable; any explicit failure blocks
acceptance. Tests inject commands/checks and need no desktop or host mutation.
An unsuccessful systemd query that cannot establish unit state is unavailable;
an observed inactive/failed critical service is a failure.

Successful package application and live checks end at `awaiting_boot`. The integrated boot-confirmation path above supplies fresh evidence before promotion.

## History database

The default database is `/var/log/astraeus/transactions.sqlite`, inside Phase 1's
separate `@log` subvolume so root rollback does not erase evidence. The writer uses
SQLite's full synchronization and DELETE journal mode. Readers therefore do not
need write access to WAL/shared-memory files. Deployment should keep the directory
root-owned. The CLI sets directory/database modes to 0755/0644 so ordinary users
can read history even with a restrictive root umask; records contain no credentials.
Library callers must provide trusted database and lock paths.

Schema migration 0 -> 1 creates an integer autoincrement primary key and one JSON
record per transaction, atomically with `PRAGMA user_version=1`. Unknown versions
are rejected. Insert assigns the ID and serialized record in one SQL transaction.
Phase updates replace a whole record atomically, including its event list. JSON
retains the package plan, previous/resulting state IDs, snapshot reference, boot
requirements/results, failure and health checks. Command diagnostics are bounded
to 4096 characters; full pacman evidence remains in `/var/log/pacman.log` rather
than embedded command transcripts. History currently reads all records; add
indexed summaries and pagination when the retained history requires them.

## Original branch snapshot integration contract (now connected)

Implement `SnapshotBackend` in the snapshot owner's crate:

1. `prerequisites(plan)` rejects unsupported layouts or inability to preserve both
   root/package DB and boot artifacts. It must not create the snapshot yet.
2. `create_pre_transaction_snapshot(transaction_id, plan)` returns a nonempty
   opaque durable reference only after recovery material is safe. It must be
   idempotent by transaction ID so an interruption in `snapshot_pending` can be
   reconciled. History stays outside the restored root.
3. `mark_snapshot_good(reference)` is reserved for verified post-boot promotion.
   The live execution coordinator never calls it.
4. `request_rollback(reference)` requests recovery. The transaction remains
   rollback-required until the external recovery owner verifies completion.

The integrated CLI now uses `BtrfsSnapshots` from the transaction integration
module; `UnavailableSnapshots` remains a fail-closed library/test backend.
The existing snapshot crate owns Btrfs operations and saved boot artifacts.
Verified boot confirmation and rollback finalization supply the missing lifecycle.
See [actual installed-system results](phase2-integration.md); mock-backed tests
alone do not establish working update or recovery.

Upstream interfaces: [pacman manual](https://man.archlinux.org/man/pacman.8.en),
[pacman-conf manual](https://man.archlinux.org/man/pacman-conf.8.en).

## Original branch validation and handoff

Base: `aad4409b258a3aa86049b3f737568feaea49d790`, confirmed by the maintainer.
Branch: `phase2/transactions`, isolated in the existing `838d` Codex worktree.
No main or sibling worktree files were edited. Phase 1 acceptance records and
installed boot hooks/presets remain unchanged.

Before implementation, Windows passed 13 Rust tests, formatting and Clippy;
Python passed 12 tests with four Linux-only skips. The existing Linux Python
suite passed all 16 tests. After implementation:

| Check | Windows | Linux (WSL) |
| --- | --- | --- |
| `cargo test --workspace --locked` | 30 passed | 32 passed |
| `cargo fmt --check` | passed | passed |
| `cargo clippy --workspace --all-targets --locked -- -D warnings` | passed | passed |
| `python3 -m unittest discover -s tests -v` | 12 passed, 5 platform/tool skips | 17 passed |
| Existing Bash syntax checks | not applicable | all 10 passed |

The extra Linux Python test used extracted pacman 7.1.0/libalpm 16.0.0 and a
temporary fixture database. It confirmed print-format/dependency/epoch behavior,
global signature-policy inheritance and unchanged files. It did not install
packages. Dependency artifacts and Linux validation logs are under ignored
`out/transactions/`; native tools were not installed into the host package DB.
No new ISO, installed update, power-loss or rollback acceptance is claimed.

Changed areas: workspace manifest/lockfile; the new transaction crate; distroctl
dependency, dispatch, update/history presentation and CLI tests; distroctl package
runtime dependencies; architecture/testing/transaction docs; optional native
pacman contract test. No snapshot-specific file or destructive guest harness
was added or modified.

Likely integration conflicts are `Cargo.toml`, `Cargo.lock`, distroctl's manifest
and CLI dispatch, its package recipe, and shared architecture/testing docs if
sibling branches edit those same files. Keep the transaction implementation in
its crate and connect the snapshot implementation through the trait. Resolve
workspace dependencies together and regenerate the lockfile once after merging
the source changes, then rerun both host suites and the snapshot owner's installed
system validation. This branch must not enable production package mutation until
boot preservation, confirmation and recovery finalization have been integrated.
