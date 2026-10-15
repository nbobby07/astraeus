# Phase 5.0 performance baselines and diagnostics

Status: implementation in progress. No Phase 5 candidate or VM acceptance is claimed.

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
