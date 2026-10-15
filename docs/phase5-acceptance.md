# Phase 5.0 performance baselines and diagnostics

Status: implementation in progress. No Phase 5 candidate or VM acceptance is claimed.

The requested A/B source freeze is `4788cb295a89bcb27d96db940c24507e9b1a27d1`.
Its first clean Arch build failed in the package check before producing a signed
repository or ISO. Rust checks passed; the controller regression could not find
`Main.qml` after Arch remapped the compiler's source paths. The performance and
QML suites passed, including 16 QML tests. This attempt is rejected.

[Preserved build evidence](evidence/phase5-build-4788-failed/build.log) and
[the detailed Qt log](evidence/phase5-build-4788-failed/control-center-LastTest.log)
retain the failure. All 20 members of the full public failure archive were
verified locally; the closed builder disk remains retained. The validator is
paused with a conservative Phase 5 compute and active-storage estimate of $1.74.

A one-line CTest working-directory correction fixes the test's source lookup.
[Controlled before/after proof](evidence/phase5-build-4788-failed/remapped-path-proof.json)
reproduces the remapped-path failure, then passes all three Qt suites using the
same test executable. It changes test execution only. A new source freeze is
needed before rebuilding A and B; no corrected image has been built or accepted.

Validation commit `1063ce8` adds the `awaiting-boot-restore` recovery case. It
requires a real update, signed offline restoration before confirmation, successful
automatic `astraeus-confirm-boot` and `systemd-bless-boot` execution, an unchanged
pending transaction and explicit rollback finalization. Its harness tests pass;
the VM case remains unexecuted. Bare-metal detection and memory-tolerant comparison
remain covered by `bare_metal_and_kernel_memory_changes_remain_comparable` unit
tests only. No physical-machine comparison is claimed.

Base: `abe83d078e25cf14b083ae6410953e6a78b695aa`, production Phase 4.2 runtime
`ec3641b72ad48d0ed24d4d9c8aa1a39cce938025`. PR #8 remains draft and unmerged.

The targeted Phase 4.2 closeout inspection checked conservative ownership
reconciliation, package-lock/snapshot integration, bounded submission validation,
and management/reboot identity against their existing regression and exported VM
evidence. No runtime change was required by this inspection. This is not a new
independent security audit. Its final Windows/Linux CI passed. Historical failure
evidence and physical qualification limits remain intact.

Phase 5.0 adds unprivileged observations, bounded CPU/memory/scratch-file workloads,
private saved results, honest comparisons, and a native Performance page. It does
not change governors, drivers, sysctls, package state or signing policy.

Required gates: portable Rust and Clippy; Linux collection/storage/workload tests;
Qt controller and QML tests; packaging/source tests; two independent identical
candidate images; ordinary-user plain/LUKS2 enforcing CLI/GUI acceptance, stop and
closure, missing sensors, management conflicts and unchanged OS state.

The additional Phase 5 compute and active-storage allowance is $10, separately
accounted from Phase 4.2. Inspect inventory/rates before starting paid resources;
reserve $0.50 for export/shutdown. Stop before the cap and retain incomplete gates.
Physical PC/USB/GPU qualification, full GameMode self-test, automatic tuning,
sustained stress testing and production signing remain deferred.
