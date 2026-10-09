# Phase 4 integration plan

Base: `2e4c1725e6ad9d70654ca32158cf524feabfc91f`, verified as the common
ancestor of all three branches and current origin/main. Work is confined to the
managed `phase4-integration/operating-system` worktree on `phase4/integration`.
The initial checkout is clean; the three source branches remain unchanged.

1. Merge graphics `9707583ce6773ef789a20dcb1349505c2191e3d5`, gaming
   `f582b09e47cf4790a217a0845f6649ec923ee6d9`, then validation
   `276bea551fd68293e83bdfec1c0ad64552c3d589`. Preserve both CLI dispatches,
   package inputs, tests and historical evidence. Run locked workspace tests.
2. Implement the gaming GraphicsProvider using distro-graphics' existing report.
   Preserve the complete hardware, binding, loader, ICD, enumeration and rendering
   evidence in additive schema fields. Keep software and virtual rendering explicit.
   Add focused adapter and CLI/schema checks, without duplicating discovery.
3. Extend the existing image-selection path with reviewed gaming catalog profiles.
   Steam Core and optional utilities remain separate. Verify all selected metadata
   against the same pinned core/extra/multilib databases. Use pacman's real signed
   dependency resolution in clean builders. Investigate an explicit software Vulkan
   test bundle for Virtio; never describe it as hardware acceleration.
4. Keep targeted enable/disable blocked. The current upgrade-only backend lacks
   complete add/remove/conflict resolution and ownership tracking. Preserve update
   locks, signatures, snapshots, root/UKI pairing, generation trust, recovery and
   NVIDIA activation/kernel transition refusals.
5. Run Windows/Linux Rust, formatting, Clippy, Python, shell, catalog, probe and
   schema checks. Fix integration failures before freezing runtime source.
6. Inspect the existing Freestyle validator and capacity. Reuse authenticated Arch
   builder inputs and existing QEMU harnesses, one heavy guest at a time. Freeze
   source and archive hash, build two independent clean images, compare manifests
   and every ISO byte, audit packaged artifacts and absence of private keys.
7. Install fresh disposable Astraeus guests and execute the full existing A-P
   matrix, plus signed update, fallback, plain/LUKS recovery and firmware-negative
   regressions against the final candidate. Run actual ELF64/ELF32 Vulkan readback,
   Steam launch and provenance-recorded Proton fixture when available. Preserve
   failed attempts and missing prerequisites rather than inventing passes.
8. Export evidence and images with verified checksums, stop owned nested guests,
   pause the validator and record usage/cost. Update the seven requested documents,
   preserving historical reports. Commit, push, run CI and open an unmerged PR.

Affected scope: distroctl gaming adapter/report/CLI and schemas/tests; graphics
bundle policy if software Vulkan is supported; package catalogs/archive lock;
bootstrap, installer and Arch builder selection; integration validation adapters,
CI checks and documentation. Existing config/hardware/snapshot/transaction APIs,
signing hooks and package guard remain the authority for their boundaries.
No new target transaction API, driver activation, personal Steam authentication,
Windows disk/firmware changes, stable release or Phase 5 work is included.

Acceptance is bounded to the identified virtual target. Software Vulkan proves
API plumbing only. Physical AMD/Intel/NVIDIA, controllers, HDR/VRR and game
frametimes require separate hardware evidence. Final verdict stays NOT YET
VALIDATED unless all required integrated gates for that target actually pass.
