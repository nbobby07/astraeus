# Roadmap and acceptance gates

Phases 0 through 3 are validated on the recorded x86-64 UEFI/QEMU/KVM target.
The current version is `0.1.0-dev`. See [Phase 2 acceptance](phase2-integration.md)
and [historical Phase 1 validation](validation.md) for exact source revisions,
hashes and installed-guest results. [Phase 3 acceptance](phase3-acceptance.md)
records enforcing owner trust, generation fallback, deliberate recovery and two
identical clean builds at runtime `fdb784c`. Phase 4 is integrated at runtime
`cac8998`, with two identical clean ISO builds, native/ELF32 software Vulkan and
Steam startup evidence. Its initial Proton and optional-tool failures remain in
the historical [Phase 4 report](phase4-acceptance.md). Subsequent
[Phase 4.1 requalification](phase4-runtime-requalification.md) passed the normal
Proton diagnostic, and the [signed fixture refresh](phase4-signed-fixture-refresh.md)
closed the remaining recorded negative case. GameMode's full self-test and
physical gaming qualification remain incomplete.

Phase 4.2 implements selected-subset system management and the native
[Control Center](control-center.md). Corrected runtime `ec3641b` passed two
independent byte-identical builds, native package/GUI checks, fresh plain and
LUKS2 enforcing CLI and desktop lifecycles, signed-media refusal checks, and all
failure/recovery scenarios. The implementation and subsequent Phase 5 corrections
were consolidated into main at `fbb5562` through PR #14. See the
[acceptance report](phase42-acceptance.md) for identities, retained
failures, screenshots and qualification limits.

Phase 5.0 VM acceptance passed at runtime `c38209c` and is included in that same
integration. Historical acceptance reports retain their original PR states and
source identities. The [current handoff](release-readiness.md) records the merged
source, unified dependency/graphics/diagnostics candidate, signing expiry and
physical-test limits.

The [next candidate](next-candidate-acceptance.md) passed fresh VM acceptance at
`518ffed`, including independent matching builds, real Calamares UI installs,
plain/LUKS2 desktop and management checks, signed-media refusals and focused
restored-root recovery. This is release groundwork through PR #16, not a new
performance-tuning phase or physical qualification.

| Phase | State | Deliverable | Evidence needed to close |
| --- | --- | --- | --- |
| 0 | Validated | Workspace, signed package repository, Plasma live ISO | Independent ISO byte comparison, UEFI/KVM Wayland boot, interactive desktop and service checks |
| 1 | Validated | Calamares, Btrfs, optional LUKS2, installed UKI, hardware/status | Fresh encrypted and plain native installations; two ISO-detached boots of each; actual CLI, network, audio and failed-unit checks; repeated ISO comparison |
| 2 | Validated | Package transactions, snapshots, history, offline rollback | Passed signed update, failed update, plain/LUKS2 rollback, interrupted mutation, unbootable recovery and independent full ISO comparison |
| 3 | Validated on recorded QEMU target | Owner Secure Boot, signed generations and deliberate recovery | Integrated A-N matrix, Phase 2 regressions and two identical clean ISO builds passed; see [acceptance](phase3-acceptance.md) |
| 4 | Integrated, not fully qualified | Connected graphics/gaming reports and pinned multilib image selections | Preserve the original runtime evidence and failures; subsequent checks are recorded under 4.1 |
| 4.1 | Partially requalified | Normal Proton diagnostic and recorded negatives passed | Full GameMode self-test and physical gaming qualification remain incomplete; software rendering does not qualify a physical GPU |
| 4.2 | VM acceptance passed; merged through #14 | Selected package/gaming state, native transactions, saved configuration and Qt/Kirigami Control Center | Passed two identical clean images and fresh plain/LUKS2 enforcing management, authorization, failure, reboot and recovery checks; physical qualification remains open |
| 5.0 | VM acceptance passed; merged through #14 | Unprivileged observations, bounded baselines and native saved-result comparison | Two identical clean images and plain/LUKS2 enforcing CLI/GUI, conflict and restored-root recovery checks passed at `c38209c`; [evidence](phase5-acceptance.md). Bare-metal comparison has unit coverage only. |
| 5, later work | Planned | Measured performance policies | Physical measurements, safe restoration and repeatable improvements; 5.0 does not tune the system or qualify physical performance. |
| 6 | Planned | General configuration language and broader desired state | Extend beyond the implemented package/gaming subset with explicit validation, migration and recovery guarantees |

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

The earlier install, update, deliberate break, rollback and reboot flow passed with
user files and failure logs preserved. That evidence qualifies its recorded
development milestone, not a stable `v0.1` release or broader compatibility. Phase 4.2 has its own acceptance record.
Milestone completion tags are evidence markers, not stable releases.

## Work without a scheduled phase

Bare-metal qualification, dual boot/manual partitioning, proprietary NVIDIA and
hybrid graphics, swap/hibernation and TPM unlock need their own compatibility or
design work. Current QEMU results do not establish support for them.

Stable/current/edge promotion, mixed component channels, reproducible AUR builds,
Hyprland and a custom compositor remain deferred. Add
components when their implementation is needed; do not create empty services or
crates to fill out the roadmap. No calendar promises are attached to these items.
