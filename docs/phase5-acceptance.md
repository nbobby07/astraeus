# Phase 5.0 performance baselines and diagnostics

Status: incomplete. The `08713df` builds are reproducible, but their candidate
failed a required production CLI gate on both plain and LUKS2 installations.

The independent builds used source
`08713dfa7f2096217710ef4f6311e2d6bb264db5`. B ran on a separate validator with its
own 64 GiB disk and consumed A's verified signed repository. The complete
3,785,316,352-byte ISOs passed an actual byte comparison, with SHA256
`cf5f3d557d5078e7622731b27aa0b5ed1909cc9716afa39de31ae6b478f110c5`.
All five independently compiled package archives, source inputs, repository
contents and package manifests also matched. Both builder disks remain retained
and both builders are paused. [Comparison proof](evidence/phase5-build-08713df/comparison.json).

Separate plain and LUKS2 VMs passed fresh candidate-payload installation through
the production provisioner, then two cold boots with Secure Boot enforced,
maintained UKI verification and actual SDDM/Plasma Wayland logins. This does not
claim Calamares GUI installation. The installer used the approved SetupMode
bootstrap; all installed tests required SecureBoot=1 and SetupMode=0.
[Plain result](evidence/phase5-build-08713df/p5p-result.json) and
[LUKS2 result](evidence/phase5-build-08713df/p5e-result.json).

Both ordinary-user CLI suites completed their two real baselines, then failed
because reading saved JSON changed some floating-point values. For example,
`13.165680473372781` became `13.16568047337278`. Protected OS state stayed unchanged.
The correction enables the JSON parser's exact float round-trip feature and adds
the observed values to the existing storage regression. That regression fails
before the correction and passes afterward; Windows workspace tests, Linux
`distroctl` tests and Clippy on both platforms pass.
[Failure and correction evidence](evidence/phase5-json-roundtrip/proof.json).
Acceptance assertions remain unchanged. The correction needs a new frozen A/B
build and production VM acceptance; `08713df` must not be accepted.

The earlier `4788cb2` clean build failed when Arch's remapped compiler paths
prevented a controller test from locating `Main.qml`. Its
[build log](evidence/phase5-build-4788-failed/build.log),
[Qt log](evidence/phase5-build-4788-failed/control-center-LastTest.log) and
[controlled correction proof](evidence/phase5-build-4788-failed/remapped-path-proof.json)
remain preserved. All 20 public export members were verified before retiring
that closed failed builder disk.

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

The user lifted the original $10 cap for parallel builders. Compute and active
storage remain tracked separately from Phase 4.2; the conservative estimate was
$3.51 at 2026-10-15 07:33 UTC. No billing plan changed. Export evidence before
pausing validators and retain incomplete gates.
Physical PC/USB/GPU qualification, full GameMode self-test, automatic tuning,
sustained stress testing and production signing remain deferred.
