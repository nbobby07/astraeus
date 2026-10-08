# Phase 2 integration acceptance

**Review follow-up awaiting acceptance.** The two runtime fixes described below
must pass fresh installed-system validation before PR #3 is merged. The historical
`dde0970` build's A-G results remain recorded here; they do not qualify newer code.

Tests A through G passed in disposable installed-system
VMs, including real LUKS2 recovery and two byte-identical clean ISO builds.
Acceptance ran on 2026-10-07/08 UTC. The safety boundaries below still apply.

The repository includes the [machine-readable scenario receipts](evidence/phase2/acceptance-summary.json)
and [artifact checksum manifest](evidence/phase2/artifacts.json). These retain failed
attempts alongside passing reruns. Host test logs are in `docs/evidence/phase2/`.
The full raw VM archives and ISO copies remain at the local paths recorded below;
this Git publication does not publish installation media or a stable release.

## PR review follow-up

Code review identified two recovery gaps after the first acceptance run. The
updater previously refreshed loader binaries although snapshots preserve only the
UKI. It now rejects entire plans changing systemd or requesting bootloader updates
before any mutation, and only compares the installed loader copies. No package
plan is silently reduced. Full loader backup/restore remains outside this change.

An interrupted health update could leave `metadata.next` while an older
known-good `metadata.json` remained eligible for rollback. Snapshot mutation and
rollback planning now refuse any store with an unfinished health write. Regression
tests cover both gaps. Security review and Bugbot reported no additional findings.
Fresh ISO and installed-system results for these fixes will be recorded below.

## Source and merge audit

Branch: `phase2/integration`, in the Codex `phase2-integration/operating-system`
worktree. Base: `aad4409b258a3aa86049b3f737568feaea49d790`.
The base contains Phase 1 report `ce85250` and hardware/status integration `08b6113`.
At that base, a direct diff of crates, distro files and installer/build production scripts against
the historical accepted source `8ac0b4a` is empty. The hardware crate and distroctl
library also match the completed hardware worktree `f961158` exactly. Integration
later made an equivalent EFI decoder change to satisfy the pinned compiler's lint.
The original three Phase 2 worktrees were not modified.

Merged in order:

| Branch | Supplied commit | Integration merge |
| --- | --- | --- |
| Snapshots | `e74d1570cfc677f658803fd1e1af5a43951fa3b3` | `db39fe0` |
| Transactions | `86acd45eecbbe35a6bd833ac83fdd5999434a83f` | `0536e5e` |
| Validation | `3930b1c2a71f2d296944945df7999ff783a0b1ea` | `a03937e` |

Conflicts occurred in Cargo.toml, Cargo.lock, distroctl's manifest, CLI dispatch,
CLI tests, package recipe and architecture documentation. Both workspace members,
dependencies, command branches, negative CLI cases and documentation were retained.
Validation merged cleanly. No tests from the supplied branches were removed.

Implementation commits: `67bf42f`, `e24fb59`, `412ac60`, `d25dc3c`, `f12b539`, `dde0970`.
Harness changes: `0d92ecc`, `1de22d5`, `adbd014`, `ceef809`, `f214938`, `2bc5219`.
The first ISO used source `412ac60`;
installed testing found three runtime defects, so that artifact is not accepted.
The current clean build uses `dde0970`. The harness separately records its own
commit and file hashes. No Phase 3 work is included.

## Implemented behavior

The updater holds the snapshot manager's MutationGuard across planning, download,
verified pre-snapshot, pacman application, UKI regeneration, post-snapshot and live
checks. Pre-snapshot failure prevents package application. Package or later failures
retain durable failure state and the previous recovery material. Pacman continues
to require trusted package signatures and rejects incomplete replacement/conflict
plans. Transaction history remains on the persistent @log subvolume.

Boot confirmation requires a different kernel boot ID, the intended root identity,
matching saved/current UKI, matching running kernel and command line, the complete
expected package map and fresh health checks. Regenerated UKIs include a transaction
marker. Required services include NetworkManager, SDDM and logind. Boot attempts
are retained; failed confirmation remains pending and blocks another update. The
systemd oneshot has no timer-based promotion. Completed confirmation is idempotent;
interrupted confirmation is revalidated. Later transactions block stale promotion.

Rollback uses the existing offline Btrfs manager and explicit --execute flag. It
restores @ and the matching UKI, retaining the previous root/UKI and all five
persistent siblings. Dry-run does not create snapshots or mutation journals.
finalize-rollback verifies the restored parent UUID, original package map, UKI and
fresh boot health before recording rolled_back. The standard live ISO provides
distroctl and dependencies; its installed guide documents the exact procedure.
There is no automatic previous-good boot menu entry.

The CLI retains info, validate, hardware and status, plus update --dry-run, update,
history, snapshot list/create/show and rollback --dry-run/--execute. Structured
JSON remains available. confirm-boot and finalize-rollback connect the existing
QEMU adapter hooks to product APIs without direct SQLite edits.

## Completed checks

| Check | Actual result |
| --- | --- |
| Windows Rust workspace | 45 passed |
| Linux Rust workspace | 48 passed, one explicit disposable loopback test ignored |
| Formatting and Clippy, warnings denied | Passed locally and with pinned Arch Rust 1.98.1 |
| Windows Python | 30 passed, 10 platform/tool skips |
| Linux Python | All 40 passed together, including native pacman and qcow2 |
| Bash syntax | All 12 existing/template/fixture checks passed |
| Archived upstream inputs | Verified in the clean Arch builder |
| Integrated package contents | Binary, confirmation service and recovery guide verified |
| Fresh LUKS2 installation and immutable baseline | Passed installed acceptance and two cold boots |
| Update success | Final signed runtime and ISO input passed in LUKS2 guest |
| Encrypted rollback | Passed successful update, final-ISO offline restore and verified LUKS2 reboot |
| Intentional failed update | Passed with final recovery ISO and LUKS2 reboot |
| Plain rollback | Passed fresh final-ISO installation, offline restore and verified disk-only reboot |
| Interrupted update | Passed after verified package mutation and forced QEMU termination |
| Unbootable recovery | Passed UKI corruption, firmware-menu live recovery and restored LUKS2 boot |
| Independent ISO reproducibility | Passed exact size, SHA-256, full-file cmp, manifests and unsigned package hashes |

Local logs: `out/integration/rust-windows.log`, `clippy-windows.log`,
`fmt-windows.log`, `python-windows.log`, `linux-validation.log` and the final
`linux-check-firmware-reset.log`. The required commands were
`cargo test --workspace --locked`, `cargo fmt --check`,
`cargo clippy --workspace --all-targets --locked -- -D warnings` and
`python3 -m unittest discover -s tests -v`, plus the existing build checks.
The Linux check reuses already extracted native tools read-only; no original
worktree files were changed to provide them.

## Build and installed-system evidence

Initial build source archive `source3.tar.xz`, SHA-256:
`ad0a5512952146f001d3acba8d2bbf67e9489ba7cdfd30c8b80389c84898ed12`.
The source is the committed Git tree under an operating-system/ prefix.

That initial ISO completed successfully: 3,534,465,024 bytes, SHA-256
`0b335446cf4a8ceff9c7a6b60c562da939fa1fc174dcb979ad5bcee53f0506ed`.
A downloaded copy was hash-verified at `D:\Astraeus-Phase2-Evidence\initial-412ac60.iso`.
It contains the subsequently discovered defects and is not the final accepted ISO.
The corrected `source6.tar.xz` archive uses `dde0970`, SHA-256
`f736366f8945a4c6d8c955585147441bde659051e416c33b7242e27f8d43aba5`.
Its build A completed with exit 0: 3,534,465,024 bytes, SHA-256
`80876324bac1975e5be408deb57bd7d10712f0a203a9148ca1ac96cbdd476b0d`.
Both downloaded copies, `D:\Astraeus-Phase2-Evidence\phase2-dde0970-A.iso`
and `phase2-dde0970-B.iso`, have the same verified hash.
Independent build B completed with exit 0 and produced the exact same size and
SHA-256. Full-file `cmp` returned 0. Image/installed package manifests and the
independently compiled unsigned package hashes also match. The receipt is
`/home/ubuntu/p2r4/evidence/reproducibility.txt`. Both used fresh cloud-image
overlays, the same verified source archive and identical signed repository inputs.
Both builder processes exited and their disposable disks were retired after export.

The sealed encrypted baseline is `/home/ubuntu/p2/base-luks2`. Its root filesystem
UUID is `acb0f960-8cc1-477c-9263-91813956b18d`; the LUKS2 UUID is
`2faaa97b-4907-4dfa-8598-bf67f7194085`. The original UKI SHA-256 is
`46b316e054c727a45f56f2a95e1420076737b31c3093657b8d5070517e1a32a4`.
The baseline passed the actual user-session networking/audio/hardware/status
acceptance script and root health checks on two distinct cold boots. Its manifest
records disk and firmware hashes; scenario runs use disposable overlays.

`/home/ubuntu/p2/success-luks` failed during package verification because pacman's
print-format `%s` falls to zero once the archive is cached. `d25dc3c` uses the
repository's canonical CSIZE instead, retaining the complete plan comparison.
Native pacman and Rust regression checks cover cached versus uncached planning.
`/home/ubuntu/p2/diag-cache` then created a real read-only pre-update snapshot but
refused its boot identity before applying packages. Upstream systemd-stub 262
appends detected serial, virtio and graphical console arguments. `f12b539` accepts
only those exact suffix forms after the complete embedded command line; added
root, encryption, init, transaction or unknown arguments still fail. Diagnostic
probes and failed receipts are retained separately and do not count as acceptance.

`/home/ubuntu/p2/diag-console` reached real package mutation and UKI regeneration,
then recorded `rollback_required`: bootctl returned failure because both installed
loaders already had the current version. `dde0970` uses bootctl's native graceful
update mode and then compares both EFI copies byte-for-byte against the packaged
x86-64 loader. Any command failure, absent file or differing copy still fails.
The test covers every command failure and both comparisons. The upstream behavior
is documented in [systemd 262's loader updater](https://github.com/systemd/systemd/blob/v262/src/bootctl/bootctl-install.c).
The unchanged unsigned systemd loader is the Phase 2 configuration; independently
signed loader overrides are not qualified here.

`/home/ubuntu/p2/diag-bootctl` passed the existing runner's complete update-success
scenario with signed runtime `dde0970` (2026-10-07 23:23:26 to 23:26:42 UTC).
Transaction 1 changed the package-owned sentinel to `version-B`, created pre
snapshot `1791415504-396488767-1217` and post snapshot
`1791415523-249566050-1217`, then rebooted from boot ID
`05728c99-7ff9-4b38-8d26-27d5921ac233` to
`e524bb49-ba51-4da6-aec3-f78b2ac94bf7`. All ten required post-boot checks passed;
history reports succeeded and the post snapshot is known-good. The active UKI
SHA-256 is `444153a17132cb7a211dad12a9db2c4af642a6b73dd8a930026b5ff360e11017`.
The later `/home` sentinel survived. This diagnostic used the initial ISO only as
the runner's recovery-media input; normal boots were disk-only. The final-media
acceptance replay is recorded below.
The observation taken before the adapter's explicit confirmation already reports
`succeeded` with one boot attempt: the enabled boot service performed confirmation.
The subsequent CLI call verified the terminal operation was idempotent.

`/home/ubuntu/p2/diag-rollback` passed encrypted offline rollback (23:27:13 to
23:34:05 UTC). The live ISO unlocked the real LUKS2 device and the existing backend
restored snapshot `1791415725-58217494-1214`, root subvolume ID 264, parent UUID
`22db8bae-6e70-5240-a43a-2ff8c60954b7`. The saved original UKI was restored, the
disk-only reboot passed, the complete original package map and `version-A` returned,
and the later `/home` sentinel survived. History reached `rolled_back` through the
product's verified confirmation API. Recovery required live-media intervention.
This diagnostic used the initial recovery ISO; the final-media replay passed below.
The pre-finalization observation already reports `rolled_back`, showing that the
boot service recognized and verified the restored generation before the explicit
CLI retry.

The first final-media update run, `/home/ubuntu/p2r4/final-success-luks`, failed
honestly when the adapter raced the still-running boot confirmation service for
the update lock. `adbd014` makes the harness synchronously wait on the actual
systemd confirmation job before invoking the idempotent product command. Service
failure still aborts acceptance; there is no timer, lock bypass or history edit.
A regression covers both confirmation actions and job failure. The product ISO
is unchanged, and a new disposable run is used for the retry.

Final Test A passed in `/home/ubuntu/p2r4/final-success-luks2`, from 2026-10-08
00:10:44 to 00:13:21 UTC, using the final signed runtime, final ISO input and
corrected harness `adbd014`. The nonempty package update, correlated pre/post
snapshots, pending boot state, new kernel boot, complete package map, all required
health checks, known-good promotion and retained home sentinel passed.

Final Test B passed in `/home/ubuntu/p2r4/final-failure-luks`, from 00:14:16 to
00:21:06 UTC. The targeted pacman hook aborted the fixture transaction, which
returned exit 1 and recorded `rollback_required`. The final ISO then performed
real offline dry-run and execution against the unlocked LUKS2 root. The restored
system rebooted, recovered its original package map and version-A sentinel,
preserved the later home sentinel, and finalized `rolled_back` with the original
failure evidence retained.

Final Test D passed in `/home/ubuntu/p2r4/final-rollback-luks`, from 00:21:55 to
00:30:31 UTC. A successful package update reached `awaiting_boot`; final-media
offline rollback restored the pre-update root and matching UKI. LUKS2 unlock,
disk-only reboot, original package map, version-A sentinel, persistent home data
and verified rollback finalization all passed.

Final Test C passed in `/home/ubuntu/p2r4/final-rollback-plain`, from 01:39:58 to
01:50:11 UTC. This used a fresh unencrypted Calamares installation from the final
ISO, followed by ordinary user-session Phase 1 acceptance and two cold boots
before sealing `/home/ubuntu/p2r4/base-plain`. Its Btrfs UUID is
`d55ba172-f016-4ddd-ae04-26b007f8ac1a`, and ESP UUID is `FEB8-E8ED`.
The signed update changed version-A to version-B and reached `awaiting_boot`.
Offline dry-run and execution restored snapshot `1791423633-437521075-792`,
root subvolume 264 with parent UUID `c3bda636-6652-f547-b91d-fe7507557b96`, and UKI
SHA-256 `a72680410879aef2210df5af3172d6892eb72c9e24c3323cc1d3dcf8eae3fa64`.
The restored disk-only boot passed all ten required checks, recovered the complete
original package map and version-A, preserved the later home marker, and recorded
`rolled_back`. For every passed recovery scenario, the retained evidence also
verifies unchanged subvolume IDs for @home, @snapshots, @log, @cache and @containers.

The encrypted baseline was freshly installed with the Phase 1 layout and passed
the Phase 1 installed acceptance suite; each disposable scenario then received the
exact final signed Phase 2 runtime before the controlled fixture update. The plain
baseline was freshly installed directly from the final ISO. Original historical
Phase 1 installed disks were not mutated.

Interruption qualification was strengthened in `f214938`: the original harness
barrier was before package application. The acceptance barrier now runs inside
pacman's PostTransaction hook, and the host refuses to cut power unless both
the package map and the package-owned sentinel have changed while history still
reports `applying`. The earlier pre-application cut is retained as an additional
diagnostic, not substituted for this stronger test. `ceef809` also waits for the
boot service before interrupted-state reconciliation, avoiding the same lock race.

Final Test E passed in `/home/ubuntu/p2r4/final-interrupted-applied-luks`, from
00:40:38 to 00:50:13 UTC. Before the forced power cut, the fixture was version B
and the package map had changed while the durable transaction remained `applying`.
The next boot reconciled it to `rollback_required`, never success. Offline restore
and a further LUKS2 boot recovered the complete original package state, matching
UKI and version-A sentinel while preserving the later home marker. The original
pre-application interruption also passed and remains an additional diagnostic.

The first Test F run (`final-unbootable-luks`) stopped before recovery because the
runner expected only a readiness timeout. With the sole UKI invalid, systemd-boot
offered only firmware setup, whose reset exits QEMU under `-no-reboot`. `2bc5219`
records process exit codes and permits that specific failure path only with exit
0 and firmware-reset serial evidence. Abnormal exits and clean exits without that
evidence remain failures. Recovery and restored-boot acceptance are still required.

The second Test F attempt (`final-unbootable-luks2`) recorded the expected clean
firmware reset but exceeded the five-minute manual recovery setup window. Its
failure is retained. The third run used the same ten-minute operator window as
the other manual scenarios, without changing health or restoration criteria.

Final Test F passed in `/home/ubuntu/p2r4/final-unbootable-luks3`, from 01:06:16 to
01:14:09 UTC. The invalid UKI left only the firmware-setup boot entry and produced
an evidenced clean reset. From OVMF Boot Manager, the operator selected the recovery
DVD, unlocked LUKS2 and ran the real offline restore. The restored disk then booted
successfully with its original package map, saved UKI, version-A sentinel and
preserved home data. History finalized `rolled_back`. The firmware menu screenshot
and all four boot logs are retained. This qualifies manual recovery, not automatic
fallback or power-loss safety during a root/ESP switch.

Closed early runs were exported to `out/integration/p2-early-evidence.tar.xz`,
5,181,312 bytes, SHA-256
`6b1cb47937b686a42f82ef78d3ca72ab6f438cd732d359df9a47a215ebdf401e`.
The archive excludes VM disks, firmware variables, ISOs and credentials.
The later runtime diagnostic export is `out/integration/p2-runtime-evidence.tar.xz`,
3,495,428 bytes, SHA-256
`d11c78fc4598f5eb5b25506e320f9ec14d0ac575abc42414e1f92be4e127d284`.
Both archives, corrected source archive and local check logs are also preserved
outside the worktree under `D:\Astraeus-Phase2-Evidence\diagnostic-evidence`, with
a SHA-256 CSV manifest. Closed diagnostic disks were removed only after these
exports were verified and no process held the disk; their retained evidence and
the immutable baseline were not removed.

Three unsuccessful builder attempts are retained separately: an incorrect attempt
to install a separate clippy package; a new pinned-compiler lint in inherited EFI
parsing, fixed with the equivalent as_chunks API; and a missing systemd-ukify
builder prerequisite, now installed before makepkg. None produced an accepted ISO.
Their logs remain under `/home/ubuntu/p2/evidence/A-failed-*` on the validator.
Only stopped failed builder disks were removed.

## Final evidence and compute cleanup

All accepted runtime inputs are commit
`dde0970118ed3003221770d9004bea3147c030ef`. The final harness is
`2bc521943cf616aae1a572858a3ed15007ca8826`. Later report changes do not change
crates, distro inputs or installer/build production scripts. The final report
commit is recorded in the external delivery manifest and final handoff.

The final encrypted export is `D:\Astraeus-Phase2-Evidence\phase2-encrypted-evidence.tar.xz`,
50,677,560 bytes, SHA-256
`df97f0d52c7a0af0ba92d06591df14bfd30e9cc2e9c8413bfaa198ae6a6b360a`.
It includes passing and failed attempts, build logs, manifests, signed repository,
source archive, QEMU/OVMF commands, boot logs, histories, snapshot state, Btrfs
layout, UKI hashes, sentinel checks and command exit codes.

The final plain export is `D:\Astraeus-Phase2-Evidence\phase2-plain-evidence.tar.xz`,
2,812,612 bytes, SHA-256
`0928413ca279dea00b3d4efbd4e8bb618fdf1ab31a9aeaf7dd8f102b3443a7f7`.
It contains fresh installation, sealed baseline and Test C evidence, plus the
updated acceptance summary and final process/service inventory. Both archives
were downloaded and hash-verified. Disks, firmware variable stores and synthetic
credentials are excluded. Raw logs are evidence; the summary does not replace them.

The existing authorized Freestyle validator
`vm-cc9d56de23154de7a22492f24dfaae27` used its original 8 vCPU, 16 GiB RAM and
64 GiB disk, Ubuntu 24.04, nested KVM, QEMU 8.2.2 and OVMF 4M firmware.
Acceptance guests used 4 vCPU/4 GiB and disposable qcow2 overlays. Independent
builders used 6 vCPU/8 GiB. No other VM was modified. The retained Arch base image's
signature was rechecked against the Phase 0 signer fingerprint. Package signature
verification stayed enabled throughout.

All nested QEMU processes exited; no Astraeus validation service remained active.
The outer validator was returned to its original paused state at
2026-10-08 01:51:42 UTC. Its totalRunSeconds changed from 35,001 to 53,592:
18,591 seconds (5 hours 9 minutes 51 seconds) of added runtime. No VM was created
or resized. Dollar charges are not inferred from runtime. The provider's existing
24-hour idle deletion policy remains unchanged, so local exports are the durable
handoff. Final provider state is saved in `diagnostic-evidence/freestyle-final.json`.
Original main and all three development worktrees were checked clean and retained
at their original commits. No Phase 3 work was started.

## Safety boundaries

Root and ESP changes are not atomic together. An interrupted rollback journal
requires offline inspection; do not delete pending.json and retry. There is no
power-loss guarantee or automatic interrupted-rollback resume. Independent package
tools do not honor Astraeus's advisory lock. Do not run them concurrently.
Snapshots are crash-consistent, not application-consistent backups. Arbitrary
service database migrations, additional kernels, multi-device Btrfs and physical
hardware are not qualified by the current checks. Root/ESP exhaustion and bootloader
binary damage require additional fault qualification. Manual recovery uses trusted
live media and an interactive LUKS unlock. No Secure Boot enforcement is added.
The power cut was qualified at the verified post-package-mutation barrier, not at
every possible write boundary. Arbitrary kernel/systemd upgrades and independent
signed loader overrides remain unqualified. Updates use the configured pinned
repository database; automatic repository refresh/channel management is outside
this integration. Unsupported replacement/conflict plans are rejected explicitly.
