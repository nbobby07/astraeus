# Architecture

## Phase 0 decision

Build an inspectable upstream-based live environment before introducing system
mutation APIs. ArchISO 91 provides image assembly and UEFI systemd-boot support.
Pacman installs conventional signed Arch packages. The custom `distro` repository
comes first and initially supplies only `distroctl`.

The workspace now has six crates:

```text
distroctl -> distro-config -> serde / TOML
          -> distro-hardware -> serde
          -> distro-graphics -> distro-hardware / serde / serde_json
          -> distro-snapshots -> serde / serde_json
          -> distro-transactions -> distro-snapshots / serde / SQLite / SHA-256
```

`distro-config` owns release metadata and validation. Parsing produces a typed
value; semantic validation is a separate method. `distroctl` handles arguments,
file I/O and presentation. Metadata and status commands remain read-only.
The [graphics foundation](graphics.md) separates GPU discovery, driver candidates,
package requirements and native/32-bit runtime evidence. Its update preconditions
are called by the existing transaction planner; it has no mutation executor.
The read-only CLI exposes `info`, `validate`, `hardware`, `status`, help and version.
Phase 2 adds `snapshot` and `rollback` through `distro-snapshots`; privileged
mutation belongs to that library. See [snapshots and recovery](snapshots.md).
Phase 2 adds read-only `update --dry-run` and `history`, plus an update coordinator
connected to the Btrfs manager and verified boot confirmation. See [transactions](transactions.md) for the model, failure states,
history database and integration contract.
`status` reports observations from procfs, sysfs, EFI variables and the current
desktop environment, with JSON schema version 1. Unavailable values remain null.
Neither status nor hardware detection invokes privileged commands or requests root.
The Rust hardware crate separates discovery observations, normalized CPU/memory/
GPU/storage information, and UEFI/VM capabilities. It does not tune hardware.
Storage discovery and encryption inspection share the partition-parent resolver,
which does not require a partition `slaves` directory. CLI presentation is separate
from the serializable hardware model. [Hardware/status](hardware.md) documents
sources, JSON schema version 1, partial observations and privilege assumptions.

Python scripts handle source packaging, image build glue and the narrow owner
signing/trust boundary through OpenSSL, sbsigntools, efitools and ukify. Transaction
and generation state remains in Rust. Small Bash files call standard Arch
publishing tools and perform guest boot assertions.
No empty crates or directories stand in for unimplemented components.

The profile is maintained here rather than copied from whatever releng profile
happens to be installed. Template generation centralizes the product identity,
archive URL, trusted repository and signing fingerprint. Linux staging creates
symlinks, so Windows checkouts do not have to preserve Unix symlinks.

## Live system

UEFI -> systemd-boot -> stock Linux/initramfs -> ArchISO read-only SquashFS with
ephemeral writable overlay -> systemd -> SDDM -> Plasma Wayland. This is live
media, not the installed Btrfs layout. No BIOS path is configured. The upstream
boot mode can additionally copy IA32 firmware support for an x86-64 CPU; there is
no i686 userspace target or separately supported mixed-firmware test target.

NetworkManager is the sole network manager. PipeWire and WirePlumber provide
audio. Ghostty is selected as the terminal; Konsole remains installed. Breeze
and Noto provide coherent defaults without custom shell extensions. KDE retains
its upstream panel behavior. Bash remains the live user's shell.

The unprivileged `live` account logs in automatically and has passwordless sudo
on this disposable medium. Root password login is locked. No SSH server is
installed. This account policy must never be copied to an installed system.

## Assumptions and boundaries

- English (US), one disposable live user. Phase 1 adds Calamares and a separate
  installed payload; the live environment itself remains ephemeral.
- Build on a disposable Arch x86-64 machine using the dated full repository set.
  Do not switch a daily-use workstation to these build mirrors.
- Package snapshots are pinned inputs, not a tested stable distribution channel.
- Upstream Mesa drivers cover AMD, Intel and Nouveau for initial live testing.
  NVIDIA proprietary drivers, hybrid switching, VRR/HDR and real hardware remain
  unqualified. No GPU vendor is selected as the architecture's only target.
- Use ordinary, unsigned UEFI boot for Phase 0 validation. No Secure Boot
  enrollment, bypass or firmware-setting modification is attempted by scripts.
- Source packaging is deterministic. Full ISO byte reproducibility is a separate
  acceptance gate; it must be measured, not inferred from fixed input versions.

## Later platform boundaries, not implemented

Configuration decoding -> typed configuration -> validation -> desired state ->
current-state comparison -> execution plan -> transaction -> structured report.
The eventual desired-state model must not depend on TOML syntax. No full Nix
semantics, custom package format, pacman replacement or plugin system is planned.
`system.lock` will describe resolved inputs and provenance, not imply hermetic
execution on a normally writable Linux filesystem.

Hardware probing will separate raw observations from capabilities. Performance
policies consume capabilities, validate safety, plan changes and record reversible
actuations. Deterministic rules come before adaptation. No security mitigation
changes or speculative tuning are part of this milestone.

Privileged execution will be confined to the transaction/actuator boundary,
with argument-array subprocess calls, inspected plans and structured failures.
Reusable libraries serve both CLI and future Qt/QML applications. Do not add a
daemon until lifetime, arbitration or privilege requirements justify it.

## Phase 1 installed foundation

Calamares 3.4.3 integrates the normal installer pages and upstream storage/account
jobs. A separately assembled explicit package set keeps live account and boot
workarounds out of persistent installations. See [installation](installation.md)
and [boot](boot.md) for source/configuration boundaries and validation status.

## Installed Btrfs layout

Flat sibling subvolumes under top-level ID 5, mounted by explicit `subvol=` paths:

| Subvolume | Mount | Reason |
| --- | --- | --- |
| `@` | `/` | OS, `/etc`, `/usr`, `/var/lib/pacman` roll back together |
| `@home` | `/home` | Keep user documents and user Flatpaks across rollback |
| `@snapshots` | `/.snapshots` | Keep recovery generations outside snapshotted root |
| `@log` | `/var/log` | Retain evidence of failed updates and boots |
| `@cache` | `/var/cache` | Avoid snapshot retention of large download caches |
| `@containers` | `/var/lib/containers` | Keep container data outside OS generations |

Do not split all of `/var`: the package database must match the restored files.
Do not exclude all of `/var/lib`: service schema migrations need explicit recovery
policy. Docker, when added, needs its own data-root/subvolume decision; user
containers/VMs under `/home` are already excluded. `/tmp` is tmpfs. No swap or
hibernation policy is added in Phase 1. The six subvolumes above are the implemented
Calamares configuration; actual installed-system qualification is recorded in
[validation](validation.md). [Storage](storage.md) documents mount options.

Btrfs snapshots are not recursive across subvolumes and are not backups. See the
[upstream Btrfs description](https://btrfs.readthedocs.io/en/latest/Subvolumes.html).

## Transactions and boot generations

The FAT ESP is outside Btrfs and cannot be rolled back by restoring `@`. The
snapshot manager saves the matching UKI with root metadata before package hooks
can overwrite the active artifact. Offline recovery restores the root and saved
UKI together, retaining their predecessors. Opt-in Phase 3 adds the native owner
trust provider, immutable signed UKIs and an independently rooted recovery entry.
See [boot generations](boot-generations.md) and [integration acceptance](phase3-acceptance.md).
The implementation and preliminary fixture boots do not establish final image
acceptance or arbitrary power-loss safety.

Durable phases distinguish preparation, downloaded/verified inputs, pre-snapshot,
package mutation, boot-artifact work, validated candidate and boot-confirmed
success. Intent is persisted before mutation. A crash during pacman application
means recovery-required. The coordinator holds MutationGuard through the update
and respects pacman's own lock. Independent package tools do not honor Astraeus's
advisory lock and must not run concurrently.

A successful package command and post-update snapshot leave the transaction at
awaiting_boot. Confirmation checks a new kernel boot ID, intended root, saved and
active UKI, running kernel/command line, package map and required services before
known-good promotion. Transaction history lives on persistent @log. See the
[acceptance report](phase2-integration.md) for successful real update, interruption
and recovery scenarios. Root/ESP changes remain non-atomic; disk-full failures,
arbitrary write-boundary power loss and interrupted rollback resumption remain
unqualified.

Upstream references: [ArchISO 91 source](https://github.com/archlinux/archiso/tree/v91),
[Arch archive](https://wiki.archlinux.org/title/Arch_Linux_Archive),
[systemd boot counting](https://systemd.io/AUTOMATIC_BOOT_ASSESSMENT/).
