# Post-security Phase 2 requalification

Status: PASS, including the required health, service and space fault variants.
Current hardened production inputs are requalified for the recorded
x86-64 QEMU/KVM target. Both fresh installations, A-G and applicable security
regressions passed; verified evidence is preserved outside Freestyle.
Historical acceptance of `dde0970118ed3003221770d9004bea3147c030ef` remains separate.
This run does not start Phase 3 or publish development installation media.

## Source audit

GitHub `main`, retrieved with `git ls-remote` and fetched on 2026-10-08 UTC:
`01ed00da86db276c4d3b6a4dd7ab756e367c0741`.
The original local `main` remains at `5c6aeba89b6e53441273170b9de6388369b55616`.
All seven original checkouts were observed clean and left at their original revisions.

Dedicated branch: `validation/post-security-phase2`.
Candidate source: `0f984fcc898439c0a3f7c64ae1b7bd16d034e5e1`.
The candidate adds only a test prerequisite and test documentation; production
inputs match starting GitHub `main`. The candidate checkout was clean when archived.

Source archive: `source.tar.xz`, 527,728 bytes, SHA-256:
`a745ce45523d3eb7b0290bd0886b6e7f21c6374ff1d84b4c87184f936e200926`.
The archive was made with `git archive`, an `operating-system/` prefix and XZ
compression. Its checksum matched after transfer to the validator.

Since historical Phase 2 runtime acceptance, relevant changes include:

- Pinned, verified local archive metadata and bounded database downloads in
  `scripts/bootstrap.py` and `scripts/validate/arch-builder.sh`.
- Private authoritative history, public publication copies, migration, legacy
  writer reconciliation and restrictive update locks in `crates/transactions/`.
- Snapshot lock permissions, unfinished metadata refusal and safer installed
  and recovery mount validation in `crates/snapshots/`.
- Transaction eligibility and stale rollback checks in the CLI and shared
  integration code, plus refusal of unsupported systemd/bootloader updates.
- Confirmation service ordering and harness recovery/boot-failure fixes.

Cargo manifests and lockfile, Rust toolchain pin, package recipes, package lists,
archive lock and pinned build versions are unchanged from historical runtime
acceptance. Complete changed-file inventory is retained with the local evidence.

## Preliminary checks

| Check | Fresh result |
| --- | --- |
| Windows Rust workspace, locked | PASS, 52 tests |
| Windows formatting and Clippy, warnings denied | PASS |
| Windows Python | PASS, 32 passed, 11 platform/tool skips |
| Linux WSL Rust workspace, locked, root run | PASS, 59 passed, one explicitly ignored loopback test |
| Linux formatting and Clippy, warnings denied | PASS |
| Linux Python, root run with native tools | PASS, all 43 tests |
| Existing Bash syntax checks | PASS, all 12 |
| Online pinned archive verification on Freestyle | PASS, both hashes and 74 direct upstream packages |
| Fresh Arch builder Rust checks | PASS, including cross-UID permissions and hot-journal migration |
| Fresh Arch builder Python | PASS, 42 passed; qcow2 tool check skipped because qemu-img is absent inside the builder |

The Linux non-root Python run first exposed a test prerequisite bug: native
`pacman -Sy` requires root even with temporary database/cache/log paths. The new
metadata test checked for Linux and pacman but omitted that prerequisite. Commit
`0f984fc` adds an explicit root prerequisite and documents it. All original test
assertions remain. Both the non-root skip and the actual root execution were
checked. The initial failure log is retained. No product security check was relaxed.

## Infrastructure and frozen inputs

Reused `astraeus-phase0-validator`: Ubuntu 24.04, 8 vCPU, 16 GiB RAM, 64 GiB disk.
Outer kernel: `6.1.102`; QEMU: `8.2.2 (1:8.2.2+ds-0ubuntu1.18)`.
KVM API 12 and CREATE_VM succeeded. The running fresh Arch guest's QEMU monitor
reported `kvm support: enabled` and `VM status: running`.

Ordinary OVMF 4M CODE/VARS are used, with a fresh writable VARS copy per guest.
No firmware enforcement setting, cloud plan, billing method or unrelated VM was
changed. The unrelated `atm10` resource remained paused.

The retained Arch cloud base is
`Arch-Linux-x86_64-cloudimg-20261001.604814.qcow2`, SHA-256
`360f0fa49db6813bdc8e35bed230a2dc2ae3567b7b5ab74719c0a706e4e34e87`.
Its detached signature was reverified against primary fingerprint
`1B9A16984A4E8CB448712D2AE0B78BF4326C6F8F`.

Each independent builder uses 6 guest vCPUs, 8 GiB RAM, a fresh sparse 36 GiB
overlay and the existing `host-builder.py`/`arch-builder.sh` pipeline. The copied
test orchestration adds the existing host suites and signed version 1/2 fixtures.
It retains the current archive hardening. Shared downloads are immutable upstream
archives and signatures; their hashes are recorded. No installed build root or
temporary state is shared. Heavy tasks run sequentially.

Arch archive: `2026/10/01`; ArchISO: `91-1`; image compiler: Rust `1.98.1`;
source epoch: `1790812800`; Calamares: `3.4.3-1`.

The dashboard confirmed the existing sponsored Hobby plan and sufficient
included usage and promotional credits before resuming. Published compute rates
were $0.04032/vCPU-hour and $0.0129/GiB-hour, or $0.52896/hour for this host before
allowances. Storage and transfer are separate. This is a cost estimate, not an invoice.
Source: [Freestyle pricing](https://www.freestyle.sh/pricing).

## ISO and installed-system gates

| Gate | Result |
| --- | --- |
| Independent ISO A | PASS, exit 0 and complete success receipt |
| Independent ISO B | PASS, exit 0 and complete success receipt |
| Full-file SHA-256 and cmp comparison | PASS, matching full hashes and cmp exit 0 |
| Plain Calamares installation and two disk-only cold boots | PASS |
| LUKS2 Calamares installation and two disk-only cold boots | PASS |
| Plasma Wayland, both terminals, network/DNS and PipeWire | PASS, both systems and both cold boots |
| A: Signed update and boot confirmation | PASS, including installed security fixtures |
| B: Failed transaction and recovery | PASS |
| C: Plain Btrfs rollback | PASS |
| D: LUKS2 rollback | PASS |
| E: Interrupted package mutation and recovery | PASS |
| F: Broken UKI and live-media recovery | PASS |
| G: Final candidate ISO reproducibility | PASS |

## Independent builds

Build A ran from `2026-10-08T05:57:27Z` to `2026-10-08T06:34:25Z`.
Its ISO is `astraeus-dev-0.1.0-dev-x86_64.iso`, 3,534,505,984 bytes, SHA-256
`065b95c50f8514407f8a32e72687ef372ca1adec896515b9a285b5348c2f0d21`.
Development repository fingerprint: `182E5C838715263EDA6D7FBDB30284029D070C33`.
The build A evidence archive was exported locally and verified as
`1518462fa8b1ed3697e10cf9f59f30edb6bff50769a2360436e72da94204b2e3`
(50,415,068 bytes) before its stopped builder disk was retired.

Build B ran from `2026-10-08T06:39:04Z` to `2026-10-08T07:14:25Z`. It produced the same 3,534,505,984-byte ISO and the same full SHA-256.
Full-file `cmp` exited 0. Builder, live and installed package manifests,
`inputs.json` and independently compiled unsigned package hashes also compared
equal. Both live manifests contain 687 packages and both installed manifests
contain 676; their version lists also match historical Phase 2. The B evidence
archive is 50,413,780 bytes, SHA-256
`4d0c73c622830c8c5e3ac07bba282c3ffd61c1b8ee601fd42769a7fc64e2e149`.

## Fresh installations

The fresh encrypted installation completed through native Calamares in
`install-luks-r2`. Both disk-only cold boots passed the user-session acceptance
script, with Plasma Wayland, NetworkManager/DNS/HTTPS, PipeWire and no failed
system/user units. Both Konsole and Ghostty accepted commands on both boots.
Boot IDs were `62be08c9-0c77-42aa-abc9-a9ea36131a41` and
`023e301c-05ac-4722-88dd-3e7ffe97c6f3`. The installed binary SHA-256 is
`b3259b5a98679623f1378bfb252c037b92c38fbfb093dbcf50c6180f12a725b5`,
matching the binary extracted from the final signed package. The original UKI
hash is `64e6cc48fbf10cea6c2fe81682a4e855cbddbec735d3d4c1a6b5b2929cd6029b`.
LUKS2 uses Argon2id with the default calibration: time cost 15, memory 464,370 KiB,
four threads. Root login is locked; the live account and Calamares are absent.
Installer logs were exported through the existing redacting serial exporter.

An initial launcher attempt stopped before QEMU started because the root-run
harness encountered Git's ownership check on the dedicated source clone.
Correcting ownership of that clone resolved it without adding a global Git trust
exception. The failed `install-luks` receipt remains preserved separately.

The plain Calamares run completed in `install-plain` at
`2026-10-08T09:00:32Z`. Both disk-only cold boots passed the same desktop script,
with successful Konsole and Ghostty command checks and zero failed system/user
units. Boot IDs were `278c1f6e-4c82-469d-a191-cac2bd529750` and
`38e1f97d-4dd3-4261-8c12-459f4f242614`. The candidate binary hash matched the
signed package and the encrypted installation on both boots. The plain UKI hash
was unchanged: `4e98179ea5c3c485ac5ea4675077c2bb765c0962108477b3731fa94db3f79b24`.
The disk has a 1 GiB FAT32 ESP and a 31 GiB Btrfs partition with all six expected
subvolumes. Btrfs UUID: `f15dfa26-1d54-46f0-9df9-49d5983fe6b8`; ESP UUID:
`A2D4-1119`. Root is locked, and both the live account and Calamares are absent.

## Installed transaction evidence

The encrypted recovery scenarios used fresh overlays of the sealed `base-luks`
disk. B retained the controlled PreTransaction package failure; D restored a
successful but unconfirmed update. E verified version B and changed installed
packages while the transaction was still applying, killed that QEMU process,
rebooted, reconciled to rollback-required and recovered offline. F corrupted the
active UKI after a successful update. Its disk-only boot exited through the
firmware-reset path with the required serial evidence; the recovery DVD was then
selected manually in OVMF. Firmware settings were unchanged. B, D, E and F each
restored the original package set and matching UKI, preserved the marker written
to /home after snapshot creation, booted from disk, and finalized as rolled-back
with a known-good snapshot and a distinct confirmation boot ID.


C performed the same update and offline restore on the independent plain Btrfs
baseline. It passed with the original packages and UKI, preserved user data,
and a rolled-back transaction confirmed on a new disk-only boot.

| Scenario | Pre-update snapshot | Final confirmation boot ID |
| --- | --- | --- |
| A | `1791446722-761644413-1060` | `f93217aa-c43c-459b-88f6-f9bea1b1c4a6` |
| B | `1791447110-826344587-854` | `97b354a0-208b-494f-811a-bae6df88c03c` |
| C | `1791451295-400175017-562` | `a3143fd7-b056-489f-9519-9e7e91166f57` |
| D | `1791448105-557805057-861` | `22b12ecc-6555-4ae9-9976-e7076ccd2148` |
| E | `1791448523-709304135-855` | `76270b34-6048-482f-b73c-2da886d19a3a` |
| F | `1791448953-804840851-847` | `bab085a1-d915-4ac5-939d-5b029cb515a2` |

A finalized as succeeded with its post-update snapshot known-good. B through F
finalized as rolled-back with their original snapshot known-good. The receipts
retain all intermediate states, exact commands, exit codes, package lists,
health checks, saved UKI hashes and persistent sentinels.

The additional plain `rejected-update --fault payload` run passed: the actual
updater refused the corrupted payload for the expected verification reason,
recorded failure, created no snapshot and changed neither packages nor root.
The unchanged guest also passed its disk-only reboot check.

Both baselines were sealed read-only after two harness-verified cold boots and
rechecked after each destructive scenario. Disk SHA-256 values:

- Plain: `677b2676e5b98af30d04149f21ad235969a8391ffcd20ff0f5598fac922e7ca3`.
- LUKS2: `ecd3a271112b76d6f749781be9c7d13d8f20dd8d2a1a27f96bc81f9ff9b6819e`.

Baseline manifests also record VARS hashes and the source installation disk
identity. Scenario overlays never write to the sealed baseline.

## Installed security regressions

The signed-update scenario ran additional disposable fixtures before and after
package mutation. Both fixture stages passed, retaining 30 before-update and 25
after-update receipts, including exact commands, exit codes and diagnostics.
The normal update and new-boot confirmation then passed with the original state
restored after each negative fixture.

| Check | Result and evidence |
| --- | --- |
| Private history ownership and mode | PASS: root-owned directory 0700 and database 0600; UID 65534 read/write attempts refused |
| Public history copy | PASS: 0644, non-root readable, non-root writes refused; private history remains authoritative |
| Update and snapshot locks | PASS: root-owned 0600; unprivileged access refused; held locks reject concurrent mutations |
| Privileged entry points | PASS: ordinary-user update refused root requirement; distroctl has no setuid bit or file capabilities |
| Legacy history migration | PASS: public-only history migrated without record loss |
| Older updater compatibility | PASS: actual historical dde0970 binary wrote legacy state, then current updater reconciled it without losing history |
| Divergent histories | PASS: expected divergence error; both conflicting database byte sequences preserved |
| Invalid/incomplete history | PASS: malformed record refused update and rollback |
| Invalid and stale rollback targets | PASS: malformed ID, post-update snapshot and stale transaction refused for their respective expected reasons |
| Interrupted metadata journal | PASS: metadata.next blocked snapshot mutation and rollback; original metadata remained intact |
| Unsafe mounts | PASS: nested ESP mount and unprotected /opt mount refused by snapshot and rollback commands |
| Untrusted package key | PASS: native pacman refused the candidate fixture with unknown trust |
| Corrupt package signature | PASS: native pacman refused the corrupted fixture; packages unchanged |
| Corrupt repository signature | PASS: isolated native pacman sync refused the modified custom database |
| Unsupported systemd update | PASS: installed CLI refused dry-run and real update before mutation at the conflicts/replacements gate; dedicated loader-plan unit tests also passed |
| Loader preservation | PASS: installed loader hashes unchanged across the signed update |

Every command refusal above exited 1 with its asserted diagnostic. Permission
and history preservation checks also inspect the underlying file modes and bytes.
These tests run only inside the disposable nested guest, never against the outer
Freestyle root. The historical updater is a test fixture, not installed over the
candidate binary. No production input was changed for these fixtures.

Archive regression tests additionally passed for modified pinned database bytes,
changed bytes at consumption, incorrect signing fingerprint, and real curl
responses with oversized declared lengths, oversized streams and slow delivery.
The size/time fixtures asserted curl exit 63/28, a bounded deadline and absence of
an accepted output. The build configuration test verifies bounded package retries;
the actual builders consumed the verified pinned databases and signed packages.

Additional archive fixtures rejected a mismatched archive date, an unexpected
package-list entry and a wrong pinned version. A real loopback HTTP test using
the configured package retry policy made exactly four requests on persistent
503 responses and stopped with curl exit 22 in 7.04 seconds. A transient 503
followed by corrupted bytes completed the download, but the production integrity
check rejected those bytes. This isolates transport retry behavior from archive
acceptance; receipt: `archive-extra-negatives.json`.

## Evidence, cleanup and delivery

Working evidence: `out/requalification/` in the dedicated validation checkout.
Freestyle evidence: `/home/ubuntu/p2sec/`. Source checkout used by the runner:
`/home/ubuntu/p2sec-src/`.

Before the build, two redundant historical Phase 0 ISO copies were removed only
after matching their hashes to the retained local ISO. The stopped, incomplete
review builder B disk was retired after verifying that its serial/configuration
logs matched the exported, checksum-verified evidence archive. Historical
installed disks were retained. Deletion receipts are in `retired-duplicates.json`.

The runtime export is `security-0f984fc-runtime-evidence.tar.xz`, 60,039,104
bytes, SHA-256 `35dcf2ac81b09f3b4141bf9bba0d0d284e5145cc7b769a3477dfd41dd8817c37`.
It contains 1,936 files, including an index of 1,935 member hashes. The downloaded
archive and every indexed member were verified locally. Credential/private-key
scans passed. The two ISO exports and both builder archives were also rehashed
before cleanup. Canonical local copies are in `D:/Astraeus-Phase2-Evidence/`:

- `security-0f984fc-A.iso` and `security-0f984fc-B.iso`.
- `security-0f984fc-build-A-evidence.tar.xz` and `security-0f984fc-build-B-evidence.tar.xz`.
- `security-0f984fc-runtime-evidence.tar.xz`.
- `security-0f984fc-source.tar.xz`.
- `security-0f984fc-local-evidence.zip`, with preliminary logs, cleanup receipts,
  the report and final delivery/CI metadata.

Repository copies of the [scenario receipts](evidence/phase2-security/acceptance-summary.json),
[installation summary](evidence/phase2-security/installation-summary.json),
[security receipts](evidence/phase2-security/security-summary.json),
[artifact manifest](evidence/phase2-security/artifacts.json) and
[usage summary](evidence/phase2-security/freestyle-summary.json) provide a compact
index into the raw evidence. The bundle retains exact QEMU commands, OVMF hashes,
serial output, screenshots, fixture sources, package manifests, transaction
records, snapshots, UKI hashes and health checks.

After verified exports, nine completed disposable installation/scenario disks
were checked with qemu-img and retired. Both sealed baselines, historical
installed disks and all logs were retained. All nested guests stopped before
the outer validator was paused at `2026-10-08T09:33:33Z`. The final account query
showed zero running VMs; unrelated `atm10` remained paused. Existing idle and
24-hour auto-delete settings were left unchanged, so local exports are the
long-term evidence copies.

Freestyle cumulative runtime increased from 57,058 to 70,546 seconds: 13,488
seconds, or **3h 44m 48s**. At the inspected published rates this is approximately
**$1.98 compute**, plus **$0.02 storage during the run**, before allowances or
promotional credits and excluding transfer. CPU-time metering was unavailable;
this estimate uses actual elapsed runtime and the unchanged 8-vCPU/16-GiB
allocation. It is not an invoice. No plan, billing or unrelated resource changed.

Initially only the root prerequisite in the native pacman test needed a tracked
fix. Review follow-up also fixes the space fixture, as recorded below. No
production code changed during acceptance, so the tested ISO inputs remained
frozen. The report commit contains documentation and evidence only and is
separate from runtime `0f984fc`. GitHub Checks is run on the report revision;
its exact revision and CI run are recorded in the final local delivery receipt.
Historical tags and acceptance records are preserved. No stable release or
public ISO was created, and Phase 3 was not started.

Operational attempts are retained separately from product results. Besides the
initial non-root test and pre-launch Git ownership failure described above,
one baseline setup command used a mistyped health-log path and refused before
setup. Correcting the path allowed the unchanged harness to proceed. A premature
serial extraction found no markers while the desktop script was still running;
the completed export passed. Initial public-key import, evidence-selection and
CLI argument-format issues were resolved in disposable orchestration. None
required a product change or a relaxed acceptance gate. All final A-G runs passed
on their first scenario attempt against the frozen candidate.

## Remaining limits

Physical hardware, dual boot, enforced Secure Boot, arbitrary power-loss points,
automatic recovery, full-disk failure behavior, root/ESP exhaustion and physical
audio playback remain outside this qualification. Root and ESP switching are not
atomic. A test at one interrupted-update barrier cannot establish general crash safety.

## Review follow-up: omitted required fault variants

Codex review of report commit `d10e56f` identified three scenarios required by
[the harness matrix](phase2-validation.md#acceptance-scenarios) that the initial
requalification omitted: health failure, service failure and package-cache space
rejection. The initial blanket PASS was premature. The original evidence archives
are preserved unchanged; a separate supplement records these additional runs.

The follow-up reuses the same frozen runtime `0f984fc`, accepted ISO A and sealed
LUKS2 baseline. It uses fresh overlays for each fault. Health and service runs use the original
harness. The space rerun uses test-only harness fix `88bce55`, described below.
No production input, signing requirement or acceptance gate changes.

| Required scenario | Result |
| --- | --- |
| `update-failure --fault health` | PASS |
| `update-failure --fault service` | PASS |
| `rejected-update --fault space` | PASS after fixture correction; initial refusal retained |

The separately reported CI problem was a stale cancellation in the original
push run. The manual archive-verification workflow shared its concurrency group
and cancelled it. A partial rerun passed Ubuntu but retained the cancelled
Windows result. Rerunning the Windows job completed that run successfully without
changing the workflow or tests.

The first space run correctly refused an unsupported nested mount beneath
`/var/cache/pacman/pkg` before creating a transaction. It therefore failed the
insufficient-space acceptance assertion, rather than passing for an unrelated
refusal. This was an obsolete fixture layout after mount-policy hardening.

Test-only commit `88bce5546b555dc6b75ef563a0f6783ea9f1e08b` mounts the bounded
16 MiB tmpfs under `/run`, preserves the original cache directory beside its
original path, and temporarily points the standard cache path to the tmpfs.
After verifying the actual insufficient-space failure and unchanged package and
snapshot state, the runner requires successful restoration of the original cache
and unmounts the fixture before reboot. The guest privilege/KVM guards remain.
The production mount policy and disk-space checks are unchanged. The fixture
files are not packaged into the ISO, so the frozen image pair remains applicable.

A new regression test checks the runtime mount location, actual cache symlink,
restoration of the original inode and cached file contents, preserved fault
marker, and refusal of an invalid cleanup state. The Linux root suite passed all
44 Python tests; Windows passed 32 with 12 platform/tool skips. Bash syntax passed.

The completed supplement is
`D:/Astraeus-Phase2-Evidence/security-0f984fc-review-followup-evidence.tar.xz`,
863,120 bytes, SHA-256
`bb8b2e139cb1cd112cc9d42097e6649afb335fbc53c4d9d588e13a3fcedeb92f`.
All 542 indexed member hashes were verified after download; credential scanning
passed. The [supplemental receipts](evidence/phase2-security/review-followup-summary.json)
are also appended to the main scenario index, including the failed original
space run and passing rerun.

Health and service faults produced `rollback_required` for the intended failed
check, then restored the original root/packages/UKI and user data and finalized
as `rolled_back` on new encrypted boots. The corrected space run exited 1 with
268,439,681 bytes required and zero available, recorded `failed`, created no
snapshot, changed no packages, restored the cache and passed its disk-only boot.

After verified export, all four follow-up overlays were retired and the validator
was paused again at `2026-10-08T15:30:07Z`. Both sealed baselines and all logs remain.
The account again showed zero running VMs, with unrelated `atm10` still paused.
The follow-up added 2,238 seconds (37m 18s), about $0.33 compute before allowances.
Combined qualification runtime is 15,726 seconds (4h 22m 6s). These are elapsed
allocation estimates, not invoiced charges.
