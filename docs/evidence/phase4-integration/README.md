# Phase 4 integration evidence

Runtime: `cac8998ad7730e69ae354c3162ef4a0677cfc162`.
Validation corrections: `493e2229e27456ae9e35c9845cad8fbee3087f54` and
`722f3b97ae67587b895bce68c44608f34e4c6a8a`.
Verdict: **PHASE 4 NOT YET VALIDATED**. See the
[complete acceptance report](../../phase4-acceptance.md).

`integration-matrix.json` preserves the original A-P definitions and combines
source-bound results without overwriting `gaming-plain/matrix.json`. That original
matrix contains first-pass failures and missing subchecks. Supplemental reruns,
runtime inspections and the ELF32 OpenGL window test are separate records.
`m-plain` is the failed timer attempt; `m-plain-r2` is its accepted fresh retry.

The `adapters/` directory preserves the host adapters and original guest helper
copies. The actual corrected scripts used for final gaming diagnostics are under
`gaming-plain/share/`; their hashes match `inspection-complete.json`. The original
and corrected files differ intentionally. Host checks and their explicit skips
are under `checks/`. `FILES.json` hashes the committed payload bytes; `.gitattributes`
prevents evidence normalization. Private material is excluded.

Full public evidence and exact signed EFI fixtures are in
`D:/Astraeus-Phase4-Integration-Evidence/acceptance-public.tar.gz`, extracted to
`public/`. Its receipt and verification record are included here. The separately
verified private context and installed disks are in the access-restricted sibling
`private/` directory. Both ISO files, frozen source archive, signed repository and
independent build archives are in the export root. No stable release is published.

The original `cac8998` harness remains unchanged on the validator. Recovery reruns
use a separate clean `harness-validation` checkout at `722f3b9`, with the same
shutdown deadline, health, signing and recovery predicates. All source/file
identities, exits and failed attempts are retained in the full export. Reproduction
requires disposable nested disks, the exact exported baselines/VARS, recorded
public/private fixture inputs and deliberate encrypted unlocks.

`freestyle-summary.json` records the paused validator, zero running compute,
unchanged unrelated VM and gross usage estimate. The provider's existing one-day
auto-delete policy is unchanged. Use the local exports for durable recovery.
