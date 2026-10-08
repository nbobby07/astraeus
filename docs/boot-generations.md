# Phase 3 boot generations

Implementation branch: `phase3/recovery`. Base:
`6a8fda25d25df74215ed0bbe06b97804e053d950`.
The clean base passed all 52 Windows Rust tests. Phase 2's hardened acceptance
is recorded in [its requalification report](phase2-security-requalification.md).
That evidence does not qualify these Phase 3 changes.

Generation mode is **opt-in**. The integration branch ships the owner signing
provider required by this implementation; see [its contract](secure-boot.md).
`boot enable` verifies readiness before enabling the feature. Firmware enrollment
remains an explicit owner operation. The original branch's host evidence below
does not qualify the integrated image; current results are in
[Phase 3 acceptance](phase3-acceptance.md).

## Ownership and binding

`distro-snapshots::generations` defines `GenerationId`, `Generation`, `RootKind`,
`Selection`, `BootCount`, `TrustVerdict` and `LoaderTrust`. Generation IDs are
validated snapshot IDs with a distinct Rust type.

| Information | Authority |
| --- | --- |
| Generation ID, snapshot reference, root ID/UUID/parent, filesystem/ESP UUID, embedded command line, UKI hash, prior generation | Immutable generation metadata |
| UKI path and BLS entry ID | Derived from the generation ID |
| Transaction ID, original snapshot identity, health and health evidence | Referenced Phase 2 snapshot metadata |
| Package maps, transaction state, confirmation and userspace boot attempts | Private Phase 2 transaction database on `@log` |
| Remaining/consumed boot attempts | Observed BLS counter filename; saved with confirmation and blessing journal |
| Current and previous roles | `selection.json`, cross-checked against loader configuration |
| Recovery eligibility | Fresh root/artifact/trust verification and transaction-reference validation |

The public history database remains a read-only publication. Mutating CLI paths
use the authoritative private history and existing update/snapshot locks.
Matching filenames or a stored trust label never establish eligibility.

The candidate boots mutable `@`, bound to its actual subvolume identity and
post-update snapshot. The predecessor boots a separate writable clone of the
verified pre-update snapshot, under
`@snapshots/astraeus/generations/ID/private/root`. Its signed UKI embeds
`rootflags=subvolid=ACTUAL_CLONE_ID`; its root fstab uses that same ID.
Selecting its UKI therefore selects the retained root, independently of `@`.
The retained clone is reserved for recovery and is never an updater target.
Writable service state can change after it boots; the original read-only
snapshot and saved UKI remain preserved for deliberate restoration.

Both plain and LUKS2 roots retain their filesystem and ESP checks. Plain UKIs
retain `root=UUID=...`. Encrypted UKIs retain `rd.luks.name=...=root` and
`root=/dev/mapper/root`, with the existing mapper/crypttab/backing UUID checks.
Only the root subvolume selector changes. No credentials, TPM policy, new
keyslots, or unlock keys are stored in generation metadata.

## Update and activation

1. Resolve the complete plan and run Phase 2 prerequisites. In generation mode,
   also require the systemd 262 trust contract and installed blessing gate.
2. Create and verify the pre-update snapshot. Persist its reference and enter
   the transaction mutation phase before changing generation state.
3. Journal staging, clone the verified root, rebind its UKI through the owner provider,
   verify kernel/initrd/release/OS/microcode payload preservation and the new
   root selection, then verify its signature and firmware trust.
4. Sync the root and metadata. Copy the UKI to a temporary ESP file, check its
   hash/trust again, sync, and publish its immutable path outside `EFI/Linux`.
5. Journal selection and publish the verified fallback entry. Select it before
   package mutation. On first activation, change the mkinitcpio preset and move
   the maintenance UKI to `/efi/EFI/Astraeus/maintenance.efi`. It must not remain
   an uncounted Type #2 entry. Clear overriding loader EFI preferences and
   retire older managed menu entries, retaining their artifacts and roots.
6. Apply packages and regenerate the maintenance UKI using existing hooks.
   Preserve the systemd package-update prohibition. Create the post snapshot,
   verify the full expected package map and live health, stage the candidate's
   trusted immutable UKI.
7. Persist `awaiting_boot` before publishing candidate selection. An interrupted
   or failed activation remains unconfirmed and requires recovery. A different
   kernel boot, matching root/kernel/UKI,
   exact expected packages and fresh required health checks are still required.

Generation staging, selection, blessing and rollback use the existing durable
`pending.json` and `operation-*.json` journal mechanism. A leftover journal,
`metadata.next`, or `generations/selection.next` blocks mutation and promotion.
There is no blind retry or automatic journal deletion.

## Upstream boot assessment

The implementation targets the reviewed **systemd 262** behavior. It uses BLS
Type #1 `uki` entries referring to signed UKIs outside `EFI/Linux`, with filenames
`astraeus-ID+3.conf`, then `+2-1`, `+1-2`, and `+0-3`. systemd-boot owns counter
renaming. No firmware counter is implemented here. The final attempt may still
be blessed if that boot actually passes all checks.

Type #2 `.efi` files support the same upstream filename counters, but the Phase 2
fixed output filename would provide an uncounted bypass. BLS `uki` entries let
the artifact stay immutable while upstream renames only the small entry file.
An `efi` entry would not get boot counting in this version.

`loader.conf` uses `preferred astraeus-CANDIDATE.conf` and
`default astraeus-PRIOR.conf`. In v262 `preferred` respects exhausted counters;
an explicit `default` does not. Foreign BLS/Type #2 entries are rejected during
activation rather than being silently adopted. This is a single-installation
layout, not a dual-boot manager. Firmware Settings remains upstream's entry.

The package supplies a `systemd-bless-boot.service` drop-in that requires the
Astraeus confirmation service and replaces automatic blessing with
`distroctl confirm-boot`. Only the transaction coordinator calls upstream
`/usr/lib/systemd/systemd-bless-boot --path ESP good`, after saving actual health
evidence. It checks `LoaderEntrySelected`, the firmware-reported UKI path/ESP,
`LoaderBootCountPath`, root identity and the observed counter before invoking it.
It verifies counter removal before snapshot promotion and transaction success.
Blessing/promotion failures are saved as confirmation errors. Repeated completed
confirmation is idempotent. There is no timer-based promotion or automatic reboot.

Reviewed upstream sources:

- [Automatic boot assessment, v262](https://github.com/systemd/systemd/blob/v262/docs/AUTOMATIC_BOOT_ASSESSMENT.md)
- [Boot entry types, counters and selection, v262](https://github.com/systemd/systemd/blob/v262/src/boot/boot.c)
- [Blessing and EFI counter paths, v262](https://github.com/systemd/systemd/blob/v262/src/bless-boot/bless-boot.c)
- [Boot Loader Specification](https://uapi-group.org/specifications/specs/boot_loader_specification/)

## Failure boundaries

| Failure | Response |
| --- | --- |
| No userspace, kernel panic, missing confirmation | Each actual loader attempt consumes a try; no success is inferred. Reboot/power-cycle may require the operator. |
| Last attempt fails | On the next loader selection, the exhausted candidate loses preference and the retained root is the default. |
| Critical health check, package map, kernel, root or UKI mismatch | Remain unconfirmed; do not bless. Save available failure evidence. |
| Missing/corrupt candidate UKI | Verification refuses activation; after activation, firmware/load errors consume available attempts. Exact reboot behavior needs QEMU qualification. |
| Trust provider absent, rejected signature or incompatible encryption metadata | Refuse staging/activation or verification. |
| Interrupted package work | The prior root/artifact was selected before mutation; history records recovery required on reconciliation. |
| Interrupted staging/activation/blessing | Keep the journal and all prior recovery material. Block updates and confirmation until deliberate reconciliation. |
| Retained root boot | Record the observed recovery boot; do not mark the transaction succeeded or rolled back. Block updates from this root. |
| Prior root or ESP itself lost/corrupt | No guaranteed automatic recovery. Use trusted external recovery media. |

Btrfs, FAT, EFI variables and SQLite do **not** form one atomic transaction.
Artifact publication uses unique destinations and synced staging. During first
activation, the independent fallback is durable/selectable before the maintenance
preset or file changes. During offline rollback, the candidate entry is retired
and the retained root selected before `@` is replaced. The restored root and
signed UKI are verified before returning to the legacy menu. The old root, old
UKI, original snapshots, generation artifacts and journals remain retained.

If power fails after upstream blessing but before health/transaction finalization,
the durable health evidence predates blessing. An unfinished journal blocks new
work; a completed blessing journal with incomplete finalization requires fresh
confirmation. This boundary cannot be made cross-filesystem atomic.
FAT media damage and firmware that fails to persist counter writes are outside
the host-test guarantee. Keep recovery media available.

## CLI and recovery

```sh
distroctl boot list --json
distroctl boot status --json
distroctl boot inspect ID --json
sudo distroctl boot verify ID --json
sudo distroctl boot enable
sudo distroctl boot set-default ID
```

List/status/inspect are read-only and distinguish metadata/reference eligibility
from a fresh privileged artifact verification. Permission-denied counter reads
are reported as unavailable. JSON includes roles, health, assessment, transaction
references, confirmation, userspace attempts, observed boot counters and pending
state. `verify` reads private roots and calls the trust provider; it writes no
generation state. `set-default` requires root and both locks and accepts only
the current pair after authoritative history/root/artifact verification. It does
not restore a filesystem, reset an exhausted counter or reboot the machine.

The menu provides Astraeus and Astraeus Previous Known Good (Recovery). A separate
on-disk recovery OS is not invented. External recovery uses the existing trusted
ISO and [offline recovery procedure](snapshots.md#integrated-live-media-recovery-procedure).
A retained-root session cannot perform an online root replacement. Boot the ISO,
unmount installed subvolumes, then restore the selected prior snapshot with the
existing explicit `rollback --execute` workflow. Managed recovery verifies that
snapshot, quiesces the candidate menu entry, restores `@` and its UKI, restores
the maintenance preset's legacy output path, and archives selection metadata.
Only a subsequent verified installed boot can finalize the rollback in history.
Use the integrated Phase 3 recovery binary and owner provider for managed installs;
old Phase 2 media does not understand the new boot metadata.

## Native signing interface

`Commands::boot_artifact` is the testable boundary. The native implementation
calls a root-owned, non-writable-by-other-users `/usr/bin/astraeus-boot-artifact`
with argument arrays and a cleared environment. The package installs the owner
provider from `scripts/secure_boot.py`. Offline verification adds
`--policy-root INSTALLED_ROOT` to use its public policy under enforcing recovery
firmware; it cannot sign or activate through that option.

| Invocation | Required behavior |
| --- | --- |
| `ready ESP` | Read-only verification of the installed/running systemd 262 loader, both loader copies, firmware trust/enforcement and signing readiness. Return JSON with schema_version=1, systemd_version=262, loader_verified=true, firmware_trusted=true. |
| `verify IMAGE` | Read-only verification of this exact artifact against the enforced firmware trust policy. Return JSON with schema_version=1, sha256, signature_verified=true, firmware_trusted=true. Mere certificate presence is insufficient. |
| `rebind SOURCE_UKI CMDLINE_FILE NEW_OUTPUT` | Produce a newly sealed/signed UKI at a previously absent private output path. Preserve the source kernel, initrd, release, OS release and optional microcode payload; use exactly the provided embedded command line. Do not modify SOURCE_UKI, enroll keys, or change firmware. |

Provider failure, unknown response fields, wrong schema/hash and negative verdicts
fail closed. Verification is repeated on the staged ESP copy. The provider
consumes private mkinitcpio candidates into `EFI/Astraeus/maintenance.efi` only
under the locked coordinator. The generation code never writes a signature or
enrolls firmware keys. No CLI flag accepts a user-supplied trust
verdict. The provider contract must cover the currently booted ESP and reject
alternate loader/XBOOTLDR configurations outside this layout.

## Validation and remaining qualification

Deterministic tests cover candidate/prior creation, root/UKI pairing, plain and
LUKS selectors, malformed metadata, stale/missing transaction references, failed
candidate activation, missing roots/UKIs, untrusted artifacts, foreign/duplicate
entries, exact counter transitions, final-attempt blessing, repeated blessing,
wrong EFI entry/path/counter/root/command line, fallback evidence, interrupted
staging/selection and offline rollback journaling. Fault injection occurs at
command and durability boundaries, including first maintenance-path activation.
Existing Phase 2 tests remain in place.

The disposable Linux Btrfs/FAT test additionally exercises a real retained clone,
its numeric subvolume selector, metadata/ESP publication, maintenance relocation
and offline restoration. Its synthetic UKI and explicit fake trust/EFI adapters
do not qualify signatures, firmware, or booting. It never writes host EFI variables
or formats a host block device. Fresh host results, using Rust 1.96.0:

| Check | Result |
| --- | --- |
| Windows Rust workspace, locked | 69 passed |
| Linux WSL Rust workspace, locked, root | 76 passed; disposable loopback excluded from default run |
| Explicit disposable Btrfs/FAT test | 1 passed separately |
| Formatting and Clippy, warnings denied | Passed on Windows and Linux |
| Windows Python | 33 passed, 12 platform/tool skips |
| Linux Python, root | 44 passed, 1 skip for unavailable qemu-img |
| Existing Bash syntax checks | All 12 passed |
| Source-package input regression | Passed on both platforms; includes blessing gate and recovery guide |

[Host-check receipts](evidence/phase3/host-checks.json) record commands and log
hashes. Raw local logs are under ignored `out/phase3/`. No ISO was built.

Integrated acceptance needs actual plain and LUKS2 QEMU boots: three failed attempts,
last-attempt success, panic/no-userspace, failed service and skipped confirmation,
missing/corrupt candidate, wrong root, stale references, signed artifact rejection,
firmware preference overrides, read-only/full ESP, power cuts at each journal
boundary, repeated updates, retained-root boot and offline restoration/finalization.
It must verify the shipped systemd unit ordering and actual initramfs use of the
retained numeric subvolume selector. No acceptance harness was changed here.

There is no automatic retention, online restoration, alternate bootloader,
firmware counter, TPM unlock, GUI recovery, Phase 4 work, or main-branch merge.
