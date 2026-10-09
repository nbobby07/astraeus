# Phase 3 integration plan

Prepared before production edits. Integration branch: `phase3/integration`.
Base: `6a8fda25d25df74215ed0bbe06b97804e053d950`, the merged Phase 2
security requalification report. Its production inputs match hardened `01ed00d`;
its recorded runtime candidate is `0f984fc`. This is prior evidence, not Phase 3
acceptance. All three requested commits exist and share this base.

1. Merge signing `267ed14`, recovery `09b66dd`, then validation `19da3b2`,
   preserving each implementation and its tests. Shared edits are CLI dispatch
   and tests, the distroctl package recipe, bootstrap source packaging, and boot
   documentation. Inspect conflicts individually. Build the merged Rust workspace
   before implementing the missing provider.
2. Implement the native `astraeus-boot-artifact` ready/verify/rebind contract on
   the existing owner signing code. Bind signed loader contents to the packaged
   systemd 262 loader, verify both installed copies and the running ESP, and keep
   signature integrity distinct from observed firmware enforcement. Refuse unknown
   trust, unsupported revocation policy, or a missing key where signing is needed.
3. Connect private signed candidate consumption to the existing mutation locks,
   snapshot journals and immutable generation artifacts. Keep the old pair
   selectable before package mutation. Replace the explicit signing integration
   refusal only with a checked transaction handoff. Keep systemd/loader upgrades
   prohibited. Cover hooks, presets, package inputs, installer behavior and CLI.
4. Verify generation/root/UKI/transaction identity through staging, activation,
   health-gated blessing and deliberate offline rollback. Preserve the existing
   boot counter logic, error handling and Phase 2 finalization. Expose retained
   root boot as recovery, not a completed rollback. Never clear interrupted intent
   merely to retry or promote a candidate on elapsed time.
5. Run locked Rust tests, fmt, Clippy, Python tests and shell syntax checks on the
   integrated tree, with focused native signature/provider regression coverage.
   Reuse the Phase 3 harness and all existing negative firmware fixtures.
6. Inspect the existing Freestyle validator, then freeze and archive the tested
   source. Build two clean images from pinned identical inputs. Run the actual
   integrated A-N matrix and applicable Phase 2 regressions under enforcing OVMF,
   including plain/LUKS2 recovery and controlled interruption. Preserve failures,
   exact exits, identities and hashes outside disposable guests; any subsequent
   product change invalidates the affected acceptance and build results.
7. Update acceptance and operator documentation, inspect the complete diff,
   commit with a clean worktree, and prepare a review PR when appropriate. Stop
   nested guests, verify evidence exports, pause only the validator, and record
   runtime/cost. Do not begin Phase 4 or publish a release.

The signing API publishes fixed private candidates with versioned receipts.
The generation API owns root clones, metadata, ESP publication, selection and
blessing journals. Transaction history authorizes recovery and final success.
Tests must reject incomplete metadata, mismatched roots, stale transactions,
failed signing, unknown trust and unresolved journals. Root, ESP, firmware and
SQLite are separate durability domains; no arbitrary power-loss guarantee follows
from unit tests or signed bytes alone. Original worktrees and historical evidence
remain unchanged.
