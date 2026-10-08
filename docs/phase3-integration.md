# Phase 3 integration

Status: integration in progress, **PHASE 3 NOT YET VALIDATED**.
Branch: `phase3/integration`, separate managed worktree
`C:/Users/Noel/.codex/worktrees/phase3-integration/operating-system`.
The [plan](phase3-integration-plan.md) was committed before production edits.

Base `6a8fda25d25df74215ed0bbe06b97804e053d950` is the merged Phase 2 security
requalification baseline. Merges preserve the three original commits, in order:
`267ed14f2079767ce33d0c6f1b89ac1816f6cfec`,
`09b66ddd0d2fc47910457dbbf4470138e408876a`, and
`19da3b2d13b6c1432522313b14824458217e1d82`.
The originals are unchanged. Conflicts in CLI dispatch, source packaging and the
package recipe retained both branches' additions. Cargo manifests and lockfile
needed no conflict resolution. The merged Rust workspace built before new code.

## Integrated behavior

The installed native provider connects owner signing to generation verification
and UKI rebinding. Readiness checks the packaged and running loader identity,
both signed ESP copies, current firmware trust and signing readiness. SHA-256
image revocations are checked using efitools' PE digest, separate from metadata's
full-file SHA-256. Unknown/certificate/TBS dbx policies remain refused. No test
provider or enrollment code is used by the production path.

The package guard requires the coordinator's actual process ancestry and both
held mutation locks, plus a verified retained root and authoritative transaction
reference. Signed candidates remain private until verification, then a journal
controls maintenance publication. The Rust generation manager owns immutable
paths and selection. Candidate boot eligibility is durable before activation;
activation failure remains recovery-required. Health checks include the native
loader/artifact trust verdict. Only a verified new boot can bless the candidate.

Offline recovery reads the installed public policy and certificate through an
explicit root context, under the recovery system's actual firmware policy.
It cannot sign through that context. Retained-root boot is a recovery session;
offline rollback and post-boot finalization remain separate actions. Systemd and
bootloader upgrades are still refused. Direct package writes cannot bypass the
coordinator's guard. Factory key enrollment, shim trust and production signing
are not implemented.

## Preliminary evidence, not integrated-image acceptance

Host logs are in `out/integration/`. Locked Windows and Linux Rust tests,
formatting, Clippy, native Python signatures and shell syntax checks have passed
during integration. The signing suite also exercises an actual disposable Btrfs
subvolume to verify lock ownership. Final candidate checks must be recorded after
the last production edit.

Freestyle work is isolated under `/home/ubuntu/p3i`, on the existing 8-vCPU,
16-GiB, 64-GiB validator. Its original state was paused, cumulative runtime
75,318 seconds. Account/billing and the unrelated VM were not changed.
Local durable exports use `D:/Astraeus-Phase3-Integration-Evidence`.

The historical signed fixture was cloned for inexpensive plumbing tests before
building images. `probe0` exposed the signing branch's blanket nonempty-dbx
refusal. The provider now evaluates supported image-hash revocations without
changing firmware data. `probe1` retained a transient package-download DNS
failure. `probe2`/`probe3` exposed a real Btrfs lock-observation mismatch:
`st_dev` is per subvolume, while `/proc/locks` identifies the superblock.
The provider now matches the ancestor's open descriptors and their lock records;
a real Btrfs regression covers it. The retained root from that failed update
booted under enforcing OVMF. `probe4` then completed signing, activation, a new
enforced boot and health-gated confirmation. These worktree probes explicitly
set `integrated_acceptance=false`; they do not qualify a newly built ISO.

Previously exported ISO/archive duplicates were rehashed locally and remotely
before retiring their remote duplicates. Superseded stopped disks are exported
and full-file verified before any retirement. Receipts remain with the evidence;
historical repository evidence is unchanged.

## Required final gates

The `cf8e435` candidate passed two byte-identical builds and most enforcing
runtime scenarios, but encrypted failed-candidate recovery exposed a remaining
CLI defect: automatic boot confirmation inferred rollback authorization from a
restored package map. The actual healthy restored boot was prematurely marked
`rolled_back`. Its failing acceptance record is retained in `p3i/j-luks`.
Automatic confirmation now leaves that transaction pending for an explicit
`finalize-rollback` request. A focused Rust regression checks repeated calls,
normal candidate selection, unknown packages, unreadable state and ambiguous
history. Both builds and the affected runtime qualification must be repeated
against this fix; the earlier candidate is not the final qualified image.

The frozen source, two independent images, integrated A-N results, applicable
Phase 2 regressions, hashes, final Git state and Freestyle cleanup remain to be
recorded in this report and [acceptance](phase3-acceptance.md). Root and ESP are
not atomic. Physical hardware, dual boot, real firmware enrollment, TPM unlock,
arbitrary power loss, full-disk behavior, key rotation/recovery, release signing
and unqualified GPU/audio hardware remain outside any current claim.
Phase 4 has not started.
