# Phase 4.1 focused guest requalification

Follow-up: the [signed fixture refresh](phase4-signed-fixture-refresh.md) closes
the blocked K case. This original run and its failures remain preserved below;
the full GameMode self-test failure still prevents an overall pass.

**PHASE 4.1 GUEST REQUALIFICATION INCOMPLETE**

Tested October 10, 2026, Pacific time. Raw records use UTC. Normal Proton execution
now passes inside installed Astraeus. Gamescope refuses the unsupported device
without launching. Available GameMode functionality and restoration pass. The
full GameMode self-test still returns 255 without a CPU governor interface, and
one K-gate case is blocked by expired disposable repository signatures. Neither
failure is converted into a pass.

## Source and environment

| Item | Identity |
| --- | --- |
| Integration baseline | `ccb33fc0324bbd139a94e0237d4395680f5a2559` |
| Integrated remediation | `09b8e9e0beaa433b27a74c5b01ec84c695a3d899`, fast-forwarded from the baseline |
| Production runtime | `cac8998ad7730e69ae354c3162ef4a0677cfc162`, unchanged |
| Additional collector fix | `076d68a1aa1c85f2abe948d3a486447b461cca69` |
| Worktree/branch | Separate `phase4-runtime-requalification/operating-system`, branch `phase4/runtime-requalification` |
| Outer validator | `vm-9350aa5ae5534cc0a68551e6e040bcf2`, Ubuntu 24.04, 4 vCPU, 16 GiB RAM, 64 GiB disk |
| Installed guest | Q35/KVM/SMM, 4 vCPU, 8 GiB RAM, Virtio VGA, Plasma Wayland/XWayland; no GPU passthrough |

Git's complete changed-path audit found only validation code/tests and
documentation differences from the frozen runtime. `crates`, `distro`, Cargo.toml
and Cargo.lock have identical Git object identities. No production files changed.
The original integration, remediation and development worktrees were not edited.
The existing PR #7 remains open/draft at the original integration commit.

The original validator was absent. One authorized replacement was created within
the existing plan. The full local ISO hash and size were checked before restoration.
The archived installed baseline and enrolled VARS were checked locally, transferred,
then checked again before constructing a disposable overlay. The first large upload
failed at 13%; all 50 smaller files subsequently transferred and passed their own
hash checks. Reassembly reproduced the original complete disk hash.

| Restored input | SHA-256 |
| --- | --- |
| Existing ISO, 3,707,426,816 bytes | `bbc3a397dbd34672994e97405e70a5d441b206820b905cfa4f6b4bd36e69905f` |
| Installed baseline, 3,305,373,696 bytes | `eafebca45776fca62b848c77dfbb40dd3189b616727fe0bc9b8c9cb03eaa67a9` |
| Enrolled VARS | `ea6d7892aa8d2416a1314975eab29547c0d56454ae3cc6949c1b24b8a0947620` |
| OVMF CODE | `1286f2a3217d09b374d05951355d7a561c8bacecd74845c8a1fbb71a48c0de8d` |

The guest booted with SecureBoot true, SetupMode false and the original owner
certificate. Installed distroctl, both boot helpers and both graphics probes
matched the baseline's binary hashes. The installed smoke test passed. This was
a restored installed guest, not an Ubuntu substitute or a fresh installation.
Test-only autologin was confined to the overlay and removed before shutdown;
it does not qualify authentication. The canonical disk and VARS remained unchanged.

## Proton

The stdout defect is confirmed in the actual guest. GE's normal launcher gives a
console PE its own console, so the old parent-output test could miss its nonce.
The corrected harness uses normal Proton `run` with Proton's Windows `cmd.exe`
to redirect output and propagate the original fixture's exit. It does not use
system Wine or substitute `runinprefix`.

GE-Proton 11-7 archive SHA-256 remains
`c5448b76a230384e2d7bc6beb5ccb97bafb7e2c3b6c527cb03a1a546bbcb00a0`.
Matching Steam Linux Runtime 4 `4.0.20260805.254769` remains
`3226d8234e7c0542ee767837832bfb1dad5e5e2dc944ec97eb221b437f6b9349`.
The launcher, tool manifest, runtime version files and entrypoint identity are
recorded separately. The unchanged CC0 AMD64 PE hash is
`5cee03d79ce1a46be0fb9e731d2ab5ce10cba1a46de86430e6afa6553c6e1347`.

Normal launch passed with nonce `a95c4b276e57472293c6f830574a4f29`, traced fixture
PID `016c`, matching window handle `0x100b2` creation/destruction and child/outer
exit 0. The no-argument control produced no nonce or fixture window and propagated
the traced fixture exit 2 through the normal launcher. Full commands, environment,
timestamps, stdout/stderr and process/window logs are in
[proton.json](evidence/phase4-runtime-requalification/proton.json).

This qualifies the direct Win32 fixture diagnostic on Astraeus. It does not
qualify authenticated Steam game launch, D3D11/12, 32-bit Windows games or broad
GE compatibility. The upstream supported Steam/umu boundary remains documented;
no account credentials were supplied to Steam.

## Gamescope and GameMode

The Gamescope adapter returned structured **UNSUPPORTED, exit 77**, with
`launched: false`. Its actual Vulkan inventory showed that no enumerated device
provided the required DRM render capability for this nested Wayland/XWayland
test. The capability refusal passes its negative safety check. Gamescope itself
was not started, and presentation remains **UNSUPPORTED**. The original abort
134 is preserved in the historical record. No extension or upstream check was
disabled.

GameMode initially had an inactive service. Explicit start/health, active client
observation, `gamemoderun` around the real Vulkan workload, request release and
return to inactive all passed. The service was stopped to restore its original
state. Configuration hashes and observed tuning values matched before and after;
`split_lock_mitigate` stayed `1`. CPU governor paths were absent and are classified
**UNSUPPORTED**. No substitute interface or privileged tuning was introduced.

The upstream self-test returned **255, FAIL**. Basic, dual-client, reaper,
supervisor and I/O-priority subtests passed; its required governor test failed.
Unconfigured scripts, GPU tuning and renice are not performance qualifications.
The original all-subchecks I gate remains FAIL, with the unsupported governor
capability reported separately. See
[gamemode.json](evidence/phase4-runtime-requalification/gamemode.json).

## Negative tests and the remaining blocker

**16 of 17 executed cases passed.** Four missing/invalid ICD and ELF-architecture
cases returned exactly 1. Twelve namespace cases passed their exact code and
diagnostic assertions, including missing native/lib32 loaders, missing tools,
absent devices, malformed UTF-8 configuration, blocked enable/disable proposals
and Gamescope refusals. Diagnostic commands that deliberately return 0 also had
their absent/unknown/untested fields checked. Zero alone is never the criterion.

The dependency-mismatch update case failed. Its intended prerequisite error is
`inconsistent graphics package state`; instead, pacman refused the expired
signature on the disposable `distro` database before that guard could be reached.
The actual distroctl exit was 1, but the wrong refusal reason cannot pass this
test. The active test repository refers to signer
`F906EC2B4A5285323BC5B40F4F8CC48CA5C57760`.

The preserved Phase 4 repository was also inspected as a possible restoration
input. Its original signer `D1C5011CA247200E6194FE0E33784DB62DDE4F5F` is expired;
the guest key listing reports `expired: 2026-10-10`. It therefore cannot provide
a valid unchanged replacement. No key was renewed or imported, no clock was
changed, and no signature policy was relaxed. The original pacman configuration,
database and signature hashes remained unchanged. Signature verification failed
closed, as it should.

This warning exposed an additional validation bug: root package-query stderr
escaped into the collector's JSON stream. Commit `076d68a` routes those queries
through the existing bounded capture helper and records their complete output
and exits inside JSON. The first malformed collector output is retained as
[negatives.json](evidence/phase4-runtime-requalification/negatives.json). The
[structured rerun](evidence/phase4-runtime-requalification/request-negatives-r2.json)
still reports the dependency case FAIL and preserves the expired-key diagnostics.
It does not conceal the prerequisite failure.

A follow-up needs a reviewed, current signed validation-repository fixture with
explicit trust/provenance, followed by the blocked mismatch case and state checks.
Refreshing production repository trust or embedded signing inputs requires a
separate clean qualification plan. Do not solve this by disabling verification,
backdating the guest, or running an unsafe package transaction.

## Updated gates and regressions

| Gate | Original | Actual guest result |
| --- | --- | --- |
| G | FAIL | **PASS**, normal Proton fixture plus exit-2 control |
| H | UNSUPPORTED | **UNSUPPORTED** presentation; clean preflight refusal safety check PASS |
| I | FAIL | **FAIL** under the original full-test rule; available functionality/restoration PASS, governor UNSUPPORTED |
| K | FAIL | **FAIL**, 16 cases PASS; mismatch case blocked by expired repository signature |
| L | UNSUPPORTED | Unchanged: targeted gaming transactions do not exist |
| P | NOT RUN | Unchanged: no physical GPU qualification |

The [supplemental matrix](evidence/phase4-runtime-requalification/matrix.json)
contains original results, exact commands/exits, environment and evidence paths.
The historical A-P matrix was not rewritten. Phase 4 is not fully validated.

Actual guest gaming status/doctor documents pass their JSON schema and contain
the same raw graphics report as `distroctl graphics --probe --json`. Native and
32-bit Vulkan readback pass; hardware acceleration remains unsupported/untested.
OpenGL/XWayland and the installed smoke test pass. MangoHud invocation passes on
both Vulkan architectures; two inspected native cube frames show changing visible
overlay content, followed by normal close 0. No performance benefit is claimed.

Steam's actual ELF32 client, runtime library check and runtime diagnostics pass.
Normal shutdown returned 0 after 766.934 seconds, before the 900-second safety
timeout. The initial screen capture showed the locked desktop, so no new usable
login-window qualification is claimed. Authentication/game launch remain untested.

After testing, package lists, transaction history and snapshot records matched
their initial state. Installed binary hashes and enforcing boot trust remained
intact. QEMU shut down gracefully with exit 0. The complete destructive Phase 3
suite was not repeated because production inputs were unchanged.

## Host checks, evidence and delivery

Rust: 114 passed, one privileged test ignored. Formatting and warnings-denied
Clippy passed. Each full Python run contained 119 tests: Linux user 92 passed/27
skipped, Linux root 116/3, Windows 72/47. The post-fix Linux suite and all 15 focused
tests passed. Bash syntax, four host JSON schema documents, both actual guest
gaming documents, all 15 gaming catalog records and the graphics catalog passed.
Platform/tool skips remain explicit; they are not counted as passing tests.

The [public evidence manifest](evidence/phase4-runtime-requalification/FILES.json)
binds the committed records. Complete raw evidence is in the ACL-protected local
`D:\Astraeus-Phase41-Requalification-Evidence\private\acceptance-raw.tar.gz`:
2,460,731 bytes, SHA-256
`0fc3e4c5fb2e505747b221500ad00bd290d9290211f526d84d1b60b8e264f16a`.
All 147 payload member hashes were verified after download. The private test
password is excluded. Public evidence is a documented selection, not a rewrite
of raw failures. Earlier setup-line-ending and transfer failures are retained.

The validator is **paused**, with no nested QEMU process remaining. Provider
active usage was **3,340 seconds (55m 40s)**, below the two-hour ceiling. At the
[published rates](https://www.freestyle.sh/docs/vms/pricing-and-limits), the
conservative compute estimate is $0.34113 and active storage $0.00511 before
allowances. Transfer was not metered locally and is additional where billable.
Paused storage is $0.005504/hour before allowances. The unrelated VM remained
paused with unchanged resource and runtime counters. No plan/billing changes or
additional provider VMs were made. The API did not return an auto-delete timer;
the verified local export is the durable evidence copy.

The final documentation/evidence commit is the tip of
`phase4/runtime-requalification`; the delivery receipt records its full SHA.
The branch is prepared for review, not merged or released. To integrate after
review, verify PR #7 still points to the baseline, inspect the branch diff, then
fast-forward `phase4/integration` to the reviewed final commit and push that branch
to update PR #7. Do not retag the remaining failed gates during integration.
The original integration and three development branches were left unchanged.

No ISO was rebuilt. No targeted transactions, driver transitions, new module
trust, Phase 4.2 or Phase 5 work was implemented.
