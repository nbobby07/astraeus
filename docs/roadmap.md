# Roadmap and acceptance gates

Phases 0 and 1 are validated on the recorded x86-64 UEFI/QEMU/KVM target.
The current version is `0.1.0-dev`. See [validation](validation.md) for the exact
implementation, hashes and installed-guest results. Phase 2 has not started.

| Phase | State | Deliverable | Evidence needed to close |
| --- | --- | --- | --- |
| 0 | Validated | Workspace, signed package repository, Plasma live ISO | Independent ISO byte comparison, UEFI/KVM Wayland boot, interactive desktop and service checks |
| 1 | Validated | Calamares, Btrfs, optional LUKS2, installed UKI, hardware/status | Fresh encrypted and plain native installations; two ISO-detached boots of each; actual CLI, network, audio and failed-unit checks; repeated ISO comparison |
| 2 | Planned | Package transactions, snapshots, history, rollback | Break a test package, restore the matching root and boot generation, reboot; inject update failures and verify durable recovery state |
| 3 | Planned | Secure Boot, signing and fallback | Enforcing OVMF accepts signed generations, rejects tampering and boots a known-good fallback |
| 4 | Planned | Gaming preset and diagnostics | Steam, Vulkan and the 32-bit stack validated across documented GPU families |
| 5 | Planned | Measured performance policies | Recorded baselines, power/thermal context, safety checks, restoration and repeatable improvements |
| 6 | Planned | Declarative state | Parse, validate, plan, diff, apply and adopt against resolved package state; safe failure handling |

## Next engineering boundary

Phase 2 must coordinate the package database, root snapshot and ESP boot artifacts.
A successful pacman invocation is insufficient: a candidate needs a healthy boot,
and the previous generation must remain bootable. Interrupted mutation needs an
explicit recovery state. The [architecture](architecture.md) records these
constraints. Phase 2 implementation is a separate milestone.

The first stable `v0.1` requires the complete install, update, deliberate break,
rollback and reboot flow, with user files and failure logs preserved. Milestone
completion tags are evidence markers, not stable releases.

## Work without a scheduled phase

Bare-metal qualification, dual boot/manual partitioning, proprietary NVIDIA and
hybrid graphics, swap/hibernation and TPM unlock need their own compatibility or
design work. Current QEMU results do not establish support for them.

Stable/current/edge promotion, mixed component channels, reproducible AUR builds,
a Qt/QML control center, Hyprland and a custom compositor remain deferred. Add
components when their implementation is needed; do not create empty services or
crates to fill out the roadmap. No calendar promises are attached to these items.
