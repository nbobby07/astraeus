# Architecture

## Phase 0 decision

Build an inspectable upstream-based live environment before introducing system
mutation APIs. ArchISO 91 provides image assembly and UEFI systemd-boot support.
Pacman installs conventional signed Arch packages. The custom `distro` repository
comes first and initially supplies only `distroctl`.

The workspace has two crates:

```text
distroctl -> distro-config -> serde / TOML
```

`distro-config` owns release metadata and validation. Parsing produces a typed
value; semantic validation is a separate method. `distroctl` handles arguments,
file I/O and presentation. Neither crate mutates the system or requests root.
The CLI exposes `info`, `validate`, help and version. Its command dispatch can
grow when real subsystems exist. Unsupported commands fail, including `status`.

Python standard-library scripts handle source packaging and image build glue;
small Bash files call standard Arch publishing tools and perform guest boot
assertions. These are build/test tools, not the future runtime platform.
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

- English (US), one live user, no disk installation or persistence in this phase.
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

## Proposed installed Btrfs layout

Flat sibling subvolumes under top-level ID 5, mounted by explicit `subvol=` paths:

| Subvolume | Mount | Reason |
| --- | --- | --- |
| `@` | `/` | OS, `/etc`, `/usr`, `/var/lib/pacman` roll back together |
| `@home` | `/home` | Keep user documents and user Flatpaks across rollback |
| `@snapshots` | `/.snapshots` | Keep recovery generations outside snapshotted root |
| `@log` | `/var/log` | Retain evidence of failed updates and boots |
| `@cache` | `/var/cache` | Avoid snapshot retention of large download caches |
| `@containers` | `/var/lib/containers` | Keep container data outside OS generations |
| `@vm` | `/var/lib/libvirt/images` | Keep VM disk state outside OS rollback |
| `@transactions` | `/var/lib/distro` | Keep durable transaction/recovery journal |

Do not split all of `/var`: the package database must match the restored files.
Do not exclude all of `/var/lib`: service schema migrations need explicit recovery
policy. Docker, when added, needs its own data-root/subvolume decision; user
containers/VMs under `/home` are already excluded. `/tmp` is tmpfs. Initially use
zram instead of placing an ordinary swapfile in a snapshotted root. These are
Phase 1 design inputs, not an implemented installer.

Btrfs snapshots are not recursive across subvolumes and are not backups. See the
[upstream Btrfs description](https://btrfs.readthedocs.io/en/latest/Subvolumes.html).

## Transactions and boot generations

The FAT ESP is outside Btrfs and cannot be rolled back by restoring `@`. A future
generation must bind its root snapshot, kernel/modules, initramfs/UKI, boot entry,
package changes and signing identity. Retain a known-good boot artifact before
switching a boot entry. Never overwrite the only bootable UKI during an update.

Durable phases will distinguish preparation, downloaded/verified inputs,
pre-snapshot, package mutation, boot-artifact staging, validated candidate and
boot-confirmed success. Persist intent before each irreversible step. A crash
during pacman mutation means recovery-required, not an automatic retry or success.
Hold the platform transaction lock and respect pacman's own lock.

A successful package command and post-update snapshot are not proof of a good
boot. Promote a candidate only after a defined boot-health check. Preserve failed
transaction history outside `@`. Test power loss, disk full, failed signature,
interrupted initramfs generation and ESP write failure before declaring rollback
ready. Initial updates may wrap pacman and Btrfs; do not claim atomic live-system
mutation or cross-filesystem atomicity.

Upstream references: [ArchISO 91 source](https://github.com/archlinux/archiso/tree/v91),
[Arch archive](https://wiki.archlinux.org/title/Arch_Linux_Archive),
[systemd boot counting](https://systemd.io/AUTOMATIC_BOOT_ASSESSMENT/).
