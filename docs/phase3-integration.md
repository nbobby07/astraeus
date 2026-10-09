# Phase 3 integration

Status: **PHASE 3 VALIDATED** on the recorded x86-64 QEMU/KVM target.
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
subvolume to verify lock ownership. Full Windows and Linux checks were repeated
after the final CLI fix, and both final Arch builders passed their native gates.

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
or preserved in a private lossless archive, with full-file verification before
retirement. Completed builder scratch disks have hash receipts and exported
build evidence. Receipts remain with the evidence;
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
history. Both builds and all required runtime qualification were repeated
against this fix and passed; the earlier candidate is not the final qualified image.

The frozen source, two independent images, integrated A-N results and applicable
Phase 2 regressions pass. Their hashes, final Git state and Freestyle cleanup are
recorded in the delivery evidence and [acceptance](phase3-acceptance.md). Root and ESP are
not atomic. Physical hardware, dual boot, real firmware enrollment, TPM unlock,
arbitrary power loss, full-disk behavior, key rotation/recovery, release signing
and unqualified GPU/audio hardware remain outside any current claim.
Phase 4 has not started.

## Frozen runtime and independent builds

The final runtime is `fdb784c8539fb7679f7ab6e350583f523a80728d`.
Its deterministic source archive is 639,632 bytes, SHA-256
`7987aec5d982f30d469fa11b98492ff1f037eb8f47755b2d87ffccc06e46e2b2`.
Commit `6bf49cd6eda785f5665282ca76aa36d2a6319df0` only updates CI tooling:
Ubuntu's ukify 255 cannot supply the JSON inspection required by the provider,
so the runner verifies and installs the pinned upstream ukify 262 script.
This does not alter installed-system code or image inputs. Linux and Windows
GitHub checks pass at that delivery commit; the initial CI failure is retained.

Independent clean builds A and B both completed their native checks and produced
3,535,165,440-byte ISOs with SHA-256
`520ca25fc9c9b9c3706011780d431f08a2f0c1c6e2848ff73dead21cc0b13905`.
Source, builder packages, live packages, installed packages, signed repository
inputs and rebuilt package hashes match. Full-file `cmp` returned 0.
The live and installed SquashFS audit confirms the packaged native binaries,
no owner signing state or private keys, and no validation agent. The installed
payload contains neither the live account nor the disposable tester account.

The first final H run stalled in firmware before Linux startup. Its QMP status,
registers, serial log and screenshot are retained in `h-plain-firmware-stall`.
The unchanged-input retry, after the second builder finished, completed the
signed update and enforced candidate boot. This establishes that scenario's
successful run, not a diagnosis or a general cold-boot reliability guarantee.

## Owner identity and recovery result

Only disposable OVMF variable stores were enrolled. The public certificate
SHA-256 fingerprints are:

| Role | DER SHA-256 |
| --- | --- |
| PK | `18b5f3379cdc44713925652c9d25e839d447acde983da87a1419051b99b80ea8` |
| KEK | `f21ac614e148e567ed74f9c2c437744d95710df5fb6b3ada3c6fed2304d87971` |
| db | `35b131177d53a681d5d2808a992ed237d7a9f457f733eb4e040616bceb6073e8` |

The enrolled VARS input SHA-256 is
`6ce6b19cfc0f7c5bcae1d5e82dbc28d1dded2ff9de76254c214ed548f3704f65`.
Enforcing OVMF CODE SHA-256 is
`1286f2a3217d09b374d05951355d7a561c8bacecd74845c8a1fbb71a48c0de8d`.
Each accepted guest checks SecureBoot=true, SetupMode=false and the exact enrolled
certificates. The owner-key manifest predates the final CLI-only fix and records
its creation revision; runtime provenance is separately pinned to `fdb784c`.
These identities are not release or factory firmware identities.

Final encrypted recovery consumes all three failed candidate attempts, boots the
retained signed root/UKI, then restores through the signed test recovery companion.
The restored canonical root unlocks normally and passes package, artifact, root,
user-data and health checks. Its transaction is not `rolled_back` before the
explicit finalization request. `finalize-rollback` verifies and completes it;
an immediate repeat returns the identical confirmation. Plain rollback and the
Phase 2 destructive regressions also pass under enforcing firmware.

The test recovery loader and UKI are signed by the same db identity. The live
SquashFS is pinned by host hash and read-only attachment, not cryptographically
covered by the UKI. Root, ESP, transaction storage and firmware are not atomic.
The exact acceptance scope and retained failures are in
[the acceptance report](phase3-acceptance.md).

## Delivery and cleanup

The public runtime archive is
`D:/Astraeus-Phase3-Integration-Evidence/fdb784c-integrated-acceptance.tar.gz`,
1,183,676,822 bytes, SHA-256
`ca2773613602401e878fed1447005c961a5b09305219e10ff727071051dcfa86`.
All 2,876 members were rehashed against the exported index. A 399-file review
selection, the adapters, host-check receipts and cleanup facts are in
[`docs/evidence/phase3-integration`](evidence/phase3-integration).
The two final ISOs, deterministic source archive, both build evidence archives,
original installed images and historical failure archives have verified local
exports. Private owner-bearing test disks remain on the paused validator.
No private key is in either ISO, the frozen source archive, Git or public evidence bundle.

All nested guests and final drivers were stopped before pausing
`astraeus-phase0-validator` at `2026-10-09T01:36:41Z`. Its 8 vCPU, 16 GiB RAM
and 64 GiB disk were unchanged. Runtime rose from 75,318 to 96,468 seconds:
21,150 seconds, or 5 hours 52 minutes 30 seconds for this integration run.
At the verified list rate of $0.52896 per running hour, approximate compute is
$3.11 before included allowances and credits. Storage and transfer are separate;
paused storage remains billable. The unrelated `atm10` VM remains paused with
unchanged configuration and runtime. No plan, billing or resize change was made.
See [the cleanup receipt](evidence/phase3-integration/freestyle-summary.json).

The final delivery commit contains documentation/evidence only after the CI-only
commit following `fdb784c`. Its exact hash is recorded in the PR and external
delivery receipt, avoiding a self-referential commit hash. The original three
Phase 3 branches and worktrees remain unchanged and clean. Main was not rewritten
or merged, and no production release was created.
