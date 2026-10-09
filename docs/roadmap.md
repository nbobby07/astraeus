# Roadmap and acceptance gates

Phases 0 through 3 are validated on the recorded x86-64 UEFI/QEMU/KVM target.
The current version is `0.1.0-dev`. See [Phase 2 acceptance](phase2-integration.md)
and [historical Phase 1 validation](validation.md) for exact source revisions,
hashes and installed-guest results. [Phase 3 acceptance](phase3-acceptance.md)
records enforcing owner trust, generation fallback, deliberate recovery and two
identical clean builds at runtime `fdb784c`. Phase 4 integration is in progress. Runtime acceptance remains open.

| Phase | State | Deliverable | Evidence needed to close |
| --- | --- | --- | --- |
| 0 | Validated | Workspace, signed package repository, Plasma live ISO | Independent ISO byte comparison, UEFI/KVM Wayland boot, interactive desktop and service checks |
| 1 | Validated | Calamares, Btrfs, optional LUKS2, installed UKI, hardware/status | Fresh encrypted and plain native installations; two ISO-detached boots of each; actual CLI, network, audio and failed-unit checks; repeated ISO comparison |
| 2 | Validated | Package transactions, snapshots, history, offline rollback | Passed signed update, failed update, plain/LUKS2 rollback, interrupted mutation, unbootable recovery and independent full ISO comparison |
| 3 | Validated on recorded QEMU target | Owner Secure Boot, signed generations and deliberate recovery | Integrated A-N matrix, Phase 2 regressions and two identical clean ISO builds passed; see [acceptance](phase3-acceptance.md) |
| 4 | Integration in progress, not validated | Connected graphics/gaming reports, pinned multilib image selections, blocked feature proposals | Complete integrated A-P matrix, signed update/recovery regressions and independent ISO bytes; physical families remain separate |
| 5 | Planned | Measured performance policies | Recorded baselines, power/thermal context, safety checks, restoration and repeatable improvements |
| 6 | Planned | Declarative state | Parse, validate, plan, diff, apply and adopt against resolved package state; safe failure handling |

## Validated boundary and remaining limits

Phase 2 coordinates the package database, root snapshot and saved UKI. A successful
pacman invocation leaves a candidate awaiting boot; promotion requires evidence
of the intended running state and healthy required services. Interrupted mutation
records a recovery state. The [architecture](architecture.md) records these
boundaries and the [acceptance report](phase2-integration.md) records actual tests.

Phase 3 counts failed candidate boots and selects a trusted retained root/UKI
pair. This is a recovery session. Canonical-root restoration remains manual
through the signed test recovery companion, followed by explicit verified
rollback finalization. Its live SquashFS is pinned by host hash, not authenticated
by the UKI signature. Root and ESP changes are not atomic; general power-loss
safety, whole-disk-full qualification and interrupted rollback resumption remain
unresolved. Physical hardware and arbitrary kernel/systemd upgrades are not
qualified by controlled fixture updates. Production recovery-media signing and
key recovery/rotation still need qualification.

The install, update, deliberate break, rollback and reboot flow passed with user
files and failure logs preserved. That evidence qualifies this development
milestone, not a stable `v0.1` release or broader compatibility. Milestone
completion tags are evidence markers, not stable releases.

## Work without a scheduled phase

Bare-metal qualification, dual boot/manual partitioning, proprietary NVIDIA and
hybrid graphics, swap/hibernation and TPM unlock need their own compatibility or
design work. Current QEMU results do not establish support for them.

Stable/current/edge promotion, mixed component channels, reproducible AUR builds,
a Qt/QML control center, Hyprland and a custom compositor remain deferred. Add
components when their implementation is needed; do not create empty services or
crates to fill out the roadmap. No calendar promises are attached to these items.
