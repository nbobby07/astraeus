# Milestones and gates

| Phase | Deliverable | Required exit evidence |
| --- | --- | --- |
| 0 | Workspace, signed repository, Plasma live ISO | Real ISO build, QEMU UEFI Wayland boot log, interactive desktop check, repeated-build comparison |
| 1 | Calamares integration, Btrfs, optional LUKS2, installed UKI, hardware probe/status | Install to disposable virtual disk and boot installed Plasma |
| 2 | Package transactions, snapshots, history, rollback | Break test package, restore generation, reboot successfully; inject update failures |
| 3 | Secure Boot, signing and fallback | Enforcing OVMF accepts signed generation, rejects tampering and boots known-good fallback |
| 4 | Gaming preset and diagnostics | Steam/Vulkan/32-bit stack validated across GPU families |
| 5 | Measured performance policies | Baselines, safety checks and restoration; reproducible benchmark improvement |
| 6 | Declarative state | Parse/validate/plan/diff/apply/adopt against resolved package state |

Current status: **Phase 0 validated** on Freestyle KVM. Two independent clean
builds produce identical ISO bytes, and the final image passes UEFI boot, Plasma
Wayland, terminal, input, network and service checks. See the
[validation record](validation.md) for evidence and limitations. Phase 1 remains
unstarted and requires a separate request.

The planned Phase 1 installer is Calamares, not a custom installer. v0.1
requires the complete boot/install/update/break/rollback/reboot acceptance flow,
not merely a themed desktop or a successful pacman command.

Stable/current/edge promotion, mixed component channels, reproducible AUR builds,
adaptive tuning, a Qt/QML control center, Hyprland and a custom compositor remain
outside the bootstrap. Add crates only as their implementations become necessary.
