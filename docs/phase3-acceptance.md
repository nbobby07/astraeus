# Phase 3 validation infrastructure acceptance matrix

Branch: `phase3/validation`. Confirmed base:
`6a8fda25d25df74215ed0bbe06b97804e053d950`.
Final commit is recorded in the delivery receipt outside the commit itself.
The dedicated worktree is `C:\Users\Noel\.codex\worktrees\1a56\operating-system`.
No merge into main, product signing/recovery changes, integrated acceptance suite
or Phase 4 work is included.

**Result: enforcing firmware and signed fixture boot are proven. Full Phase 3
acceptance remains pending the signing and recovery branches.** The installed
fixture derives from the previously accepted Phase 2 runtime
`0f984fcc898439c0a3f7c64ae1b7bd16d034e5e1`; it is not a Phase 3 production ISO.

## Actual infrastructure

Reused `astraeus-phase0-validator`, VM
`vm-cc9d56de23154de7a22492f24dfaae27`, Ubuntu 24.04, outer kernel `6.1.102`,
8 vCPU, 16 GiB RAM and 64 GiB disk. QEMU is
`8.2.2 (1:8.2.2+ds-0ubuntu1.18)`. Nested guests use 4 vCPU/4 GiB each.
Two nested guests briefly overlapped during independent probes; peak configured
nested allocation was 8 vCPU/8 GiB. The outer disk went from 41 GiB used to about
46 GiB before exports. No VM was created/resized, no plan/billing/access setting
changed, and unrelated `atm10` remained paused.

OVMF package: `2024.02-2ubuntu0.10`; GNU EFI: `3.0.15-1build1`;
sbsigntool: `0.9.4-3.1ubuntu7`; virt-firmware: `24.1.1-2`.
Firmware CODE: `/usr/share/OVMF/OVMF_CODE_4M.secboot.fd`; clean template:
`/usr/share/OVMF/OVMF_VARS_4M.fd`. Actual QEMU commands explicitly enable SMM
and protected pflash. Live firmware reports SecureBoot 1 and SetupMode 0, and
PK/KEK/db each contain exactly the relevant trusted test certificate.
All accepted probes report KVM enabled. Enrollment and reproduction commands are
in [the runbook](phase3-validation.md).

## Public test identities

These are SHA256 fingerprints of DER certificates, not private keys. Each fixture
family has an independently generated trusted/untrusted pair. The ordinary EFI
pair also signs the installed systemd-boot/UKI fixture.

| Family | Trusted | Untrusted |
| --- | --- | --- |
| EFI payload and installed boot | `08a1c08c0cff31f7517fd20a929af454b9139eaa5d05b8843d42846f43a59a74` | `976fcbbb37c86cc733077c1319f5e26dd5abd965cd32b615a77c1bb4f068458e` |
| Real UKI LoadImage tests | `b27adc1207c94bf6b12cbd06ea0dfd5cd9910d35e73c4173ff701680cf2785c2` | `be5220171050b063a90e98a54e0da2f0b9b1ab71706d24ec87e9de976fc61799` |
| Real systemd-boot LoadImage tests | `38e8a36bfa9561b93f2e04dc1575109029dca0eeafad14ff8bd28e2de8336ec1` | `90a21a8a5f1addee59c335b502d2fab1822b2bbcbaf5a235cd30dc8b364f2f65` |

Private files stay outside source/evidence trees on the validator. No private key
entered a guest, ISO, Git commit or evidence export. Test signing is independent
of the product's pending production/release signing implementation.

## A-J matrix

| Case | Actual result | Evidence / remaining requirement |
| --- | --- | --- |
| A: trusted boot | **Pass for the signed Phase 2 fixture** | `delivery-trusted-astraeus`: signed systemd-boot and UKI start Astraeus; expected live trust, Btrfs root, artifact identities, healthy units and successful boot-confirmation service. Integrated Phase 3 generation acceptance remains pending. |
| B: tampered UKI | **Pass for direct firmware refusal** | `final-uki-firmware-base-r2`: one changed `.linux` byte, signature retained, LoadImage refused and authentication-table record present. Installed tamper injection also completed. Generation fallback remains pending. |
| C: untrusted signer | **Pass for direct firmware refusal** | Real UKI, real systemd-boot and tiny EFI controls refuse the untrusted signature. Installed replacement injection completed. |
| D: missing signature | **Pass for direct firmware refusal** | Real UKI and systemd-boot unsigned controls refuse execution. Installed unsigned replacement injection completed. |
| E: valid candidate B | **Pending integration** | Native signed staging/activation and generation-specific health/promotion/retention APIs are not present at the base. |
| F: failed candidate B | **Pending integration** | Missing, damaged and partial-write UKI injection is ready and exercised. Previous generation selection, attempts and correct root/UKI pairing need product integration. |
| G: LUKS2 fallback | **Pending integration** | Existing encrypted Phase 2 baseline retained unchanged. Signed recovery chain, generation fallback, interactive unlock and persistent-data checks must run on the integrated product. |
| H: five power cuts | **Harness unit checks pass; VM acceptance pending** | Correlated, blocking checkpoint helper implemented for all five points. No product write barriers exist at the base, so no Phase 3 power cut was run or counted as accepted. |
| I: invalid generation metadata | **Pending integration** | Need the real metadata schema, mutation fixture boundary, refusal reason and generation/root/UKI inventory. No invented metadata format is used. |
| J: recovery trust | **Pending integration** | Firmware refuses unsigned/untrusted real EFI artifacts. Trusted recovery media and native recovery path are missing; unsigned Phase 2 recovery media were not used as equivalent evidence. |

In each successful negative firmware probe the trusted control loads with status
0, each invalid control returns `800000000000000f` (EFI_ACCESS_DENIED), and the
firmware execution table contains the matching authentication failure record.
No failed control reaches StartImage. The ordinary trusted payload executes
exactly once. Real loader/UKI probes use LoadImage-only and do not claim kernel
execution; A supplies the separate executed boot evidence. Timeout, missing
file, unrelated refusal, missing record and crashed QEMU are failures.

## Failure injection coverage

| Fault | Infrastructure result | Product acceptance |
| --- | --- | --- |
| Tampered signed UKI | Real overlay injection completed; before/after SHA256 differs in `.linux` | Firmware rejection proven separately; recovery pending |
| Missing UKI | Real overlay injection completed; artifact absent | Recovery pending |
| Partial ESP write | Real overlay injection completed; UKI truncated to half its original bytes | Recovery pending |
| Unsigned UKI | Real overlay replacement completed from a hash-checked read-only fixture | Firmware rejection proven separately |
| Wrong signing identity | Real overlay replacement completed from an untrusted signed fixture | Firmware rejection proven separately |
| Full ESP | Real overlay injection completed; errno 28 after writing 1,033,166,848 bytes; signed UKI hash unchanged | Staging/refusal/recovery under ENOSPC pending |
| Wrong root UUID | Guarded replacement helper implemented | Need a correctly signed wrong-root fixture and product pairing refusal |
| Missing previous generation / exhausted counter | No speculative implementation | Need product inventory and documented metadata fixture boundary |
| Interrupted staging / activation / confirmation / rollback preparation | Guarded power-cut helper implemented and unit checked | Need synchronous native write barriers |
| Invalid generation metadata | No speculative implementation | Need actual schema and refusal API |
| Encrypted unlock failure | Existing private QMP unlock workflow retained | Need integrated LUKS2 recovery baseline and refusal test |

`inject` receipts prove the injection happened. They explicitly set
`injection_only=true` and `security_acceptance=false`; their exit 0 is not a
negative-security-test or recovery pass. Destructive disks are disposable
overlays; sealed source disk and VARS hashes remain unchanged.

## Observed trusted boot

The accepted signed UKI SHA256 is
`c9f82468afbb5375f49673e701f7136ac7c0300357ffc6a71a52716a35599a3b`.
Both signed systemd-boot paths have SHA256
`8664887987f64787ca171d84ecdd22a1b3fb72d7651a3dee69ee41a4d128740a`.
Loaded paths are `/efi/EFI/BOOT/BOOTX64.EFI` and
`/efi/EFI/Linux/astraeus-dev-linux.efi`. Kernel: `7.2.7-arch1-1`.
Plain Btrfs root UUID: `f15dfa26-1d54-46f0-9df9-49d5983fe6b8`, root `@`,
persistent home `@home`; ESP UUID `A2D4-1119`.
The command channel, full package map, database check, failed units, mounts,
subvolumes, firmware keys, kernel command line, histories, boot state, ESP hashes,
journals and boot-confirmation status are retained. No Phase 3 generation is
asserted known-good and no recovery outcome is inferred from this boot.

## Checks and retained failures

* `cargo test --workspace --locked`: exit 0 on Windows, 52 Rust tests passed.
* `cargo fmt --all --check`: exit 0.
* `cargo clippy --workspace --all-targets --locked -- -D warnings`: exit 0.
* Windows Python discovery: exit 0, 55 tests, 12 explicit platform/tool skips.
* Ubuntu Python discovery: exit 0, 55 tests, 2 explicit skips for unavailable
  pacman/pacman-conf. Linux-only existing QMP/process/image tests ran.
* Bash syntax checks for the existing live/installed smoke scripts and Phase 2
  adapter: exit 0. The installed gate reuses Phase 2 guest and health checks.
* EFI fixture compilation uses GCC `-Wall -Wextra -Werror` and actual signing/
  verification commands; all three final firmware probes pass under nested KVM.

Retained non-passing attempts: the first QEMU launch lacked `/dev/kvm` permission
(QEMU exit 1); the first enforcing probe expected the wrong deny-policy status;
the first real-UKI fixture setup expected the wrong `sbverify --list` exit code.
These remain in the export and are not counted as security acceptance. The firmware
status was corrected against upstream EDK2 and strengthened with authentication
records. No enforcement flag or health/recovery condition was relaxed.

Linux-native Rust package integration was not rerun on this Ubuntu host, which
has no Rust/pacman toolchain. Rust production code is unchanged. The final two
clean ISO builds and full-file comparison are deliberately pending integration.
No reproducibility claim is made from manifests or signing these fixtures.

## Evidence

Host root: `/home/ubuntu/p3`. Compact receipts are committed under
[`docs/evidence/phase3`](evidence/phase3). Every run retains source revision,
harness/probe hashes, command exit codes, UTC start/end times, boot IDs, QMP,
serial logs, signed artifact hashes and sealed baseline references. Successful
firmware runs retain actual VARS/disk hashes before and after cleanup. Failed
attempts and fault states remain on the outer validator.

Durable local exports: `D:\Astraeus-Phase3-Evidence`.

| Export | Bytes | SHA256 |
| --- | ---: | --- |
| `evidence.tar.gz` | 379,721,424 | `ad591bd87f28e488bf7e6d98b6344c117901e6a279284f271e7b01c595e9e7e5` |
| `images.tar` | 3,082,792,960 | `2031dd9e74a751a98027d50915de7eddfe7276d05c1c8aad75b4b09f47ce8208` |

The image archive preserves four independent sealed baseline disks and variable
stores outside the nested guests. The evidence archive includes public signed/
unsigned/tampered fixtures, raw logs, manifests and receipts. Private keys and
provider credentials are excluded. Archive and member hash verification, final
provider state, runtime/cost and delivery commit are recorded in the export's
delivery receipts.

All archive hashes and every archived member hash were verified locally before
cleanup. The accepted guest run's harness-file hashes also match the committed
source files. No nested QEMU remained. The validator was paused at
`2026-10-08T19:13:18.379978Z` (12:13 PM PDT); provider runtime rose from 72,784 to
75,318 seconds, an additional **2,534 seconds (42 minutes 14 seconds)**.
The final account inventory has zero running VMs and the unrelated VM's entire
provider record is unchanged. See
[the cleanup/usage receipt](evidence/phase3/freestyle-summary.json).

At the [published Freestyle rates](https://www.freestyle.sh/pricing), gross compute
value is about **$0.37**, before plan allowances/credits, plus about **$0.004** for
64 GiB of storage during this run. Storage continues while paused and may include
saved memory; this is not a final storage bill. The existing sponsored Hobby plan
and billing settings remain unchanged. Transfer charges were not inferred from
archive sizes or delayed account usage figures. Dollar amounts are estimates,
not an invoice.

## Limits

These results prove the configured OVMF fixture trust and the signed plain test
boot. They do not qualify the pending production signing pipeline, generation
selection/promotion, trusted recovery, LUKS2 fallback, metadata handling, write
interruption recovery, arbitrary power loss or physical hardware. Full ESP is a
bounded test filesystem fault; partial artifact truncation is not an arbitrary
filesystem power-loss guarantee. The validator has an existing 24-hour idle
deletion policy, so verified local exports are the durable handoff.
