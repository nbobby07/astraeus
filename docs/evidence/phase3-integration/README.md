# Integrated Phase 3 evidence

Runtime: `fdb784c8539fb7679f7ab6e350583f523a80728d`. Start with
`acceptance-summary.json`, then each named scenario's `result.json`, observations
and native command receipts. `review-index.json` hashes this selected subset;
`export.json` identifies the complete public archive and its separately verified
index. Every archive member was rehashed locally before this subset was written.

This directory is test evidence, not installed software. The Python adapters
reuse the frozen repository's original Phase 2/3 VM, fault and acceptance code.
Their absolute paths identify the disposable Freestyle workspace used in this
run. They must not be run against a physical installation. No test agent,
validation account or owner key is part of the ISO payload.

Reproduction order on an equivalent disposable nested-KVM host:

1. Check out the frozen runtime and reconstruct the recorded pinned Arch builder,
   signed repository and clean inputs. Build A and B independently and compare all
   manifests, package hashes and full ISO bytes as recorded in `reproducibility.json`.
2. Use the original `scripts/validate/phase2.py install` with each encryption mode
   and the final ISO. Complete native Calamares installation. Installation alone
   is not acceptance: `integrated-baseline.py` requires the original installed
   smoke test from the real logged-in Wayland session, then provisions disposable
   owner keys and checks two enforcing cold boots. Private keys must be generated
   outside the source tree and enrolled only in disposable OVMF VARS.
3. Use original `phase3.py fixtures` and `firmware` with the exported actual loader
   and initial installed UKI. Keep the original `integrated_acceptance=false`
   probe flag. Its firmware rejection result is linked to this runtime through
   the artifact hashes in `base-plain/public-artifacts/provenance.json`.
4. Run `integrated-run.py` for update, fallback and metadata, then
   `integrated-powercut.py` and `direct-package-refusal.py`. The power-cut wrapper
   executes real sync before blocking the selected native activation checkpoint;
   the original harness performs the correlated SIGKILL.
5. Build the signed recovery companion with `build-recovery-kit.py`. Run
   `integrated-regression.py` for plain rollback and the original Phase 2 payload,
   space, package, interruption, health and service cases. Start the original live
   guest agent only after recovery boots; it is not baked into recovery media.
6. Run `integrated-fallback-recovery.py` against the encrypted baseline. Supply the
   ordinary LUKS passphrase at each required unlock. In live recovery, first open
   `/dev/vda2` as `root`, then start the test agent. Its final assertions require
   the healthy restored root to remain unfinalized until the explicit command,
   and require repeated finalization to be idempotent.
7. Run `acceptance-summary.py` only after all cases finish. It checks source and
   artifact identity, firmware refusal records, every integrated acceptance gate,
   Phase 2 regressions, ISO audit and byte reproducibility before emitting PASS.

`owner-firmware/manifest.json` records when the disposable identity was created,
which predates the final CLI-only fix. Baseline manifests and exact installed
binary hashes independently bind runtime execution to `fdb784c`. The recovery
kit's creation-time `boot_qualified=false` is also preserved; actual per-boot
`recovery-trust.json` files supply the qualification proof.

The initial H firmware stall remains in `h-plain-firmware-stall`. The earlier
`cf8e435` auto-finalization failure and superseded results remain in separate
historical archives under `D:/Astraeus-Phase3-Integration-Evidence`. Neither is
silently replaced by a passing result. Raw owner-bearing disks and private keys
are excluded from this directory and the public archive. They remain private on
the paused validator; sealed-disk receipts identify their exact retained bytes.

See `../../phase3-acceptance.md` for the test limits. In particular, the signed
recovery UKI does not authenticate live SquashFS, fallback does not restore `@`,
and the one tested power cut is not an arbitrary power-loss guarantee.
