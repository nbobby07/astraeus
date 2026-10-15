# Phase 4.1 runtime remediation

**PHASE 4 RUNTIME BLOCKERS REMAIN**

Base: `ccb33fc0324bbd139a94e0237d4395680f5a2559`. Branch:
`phase4/runtime-remediation`, in the separate managed `phase4-runtime-remediation`
worktree. Validation source: `600319505033eac4540c2ac74e6a0a265e1a3f60`.
No production files changed. The original integration worktree remains clean at
the base commit. Original A-P results and failures are unchanged.

The local investigation establishes an output-capture defect in the Proton test
and adds a bounded Gamescope capability refusal. These changes still need an
Astraeus guest rerun. Freestyle returns `NOT_FOUND` for the former validator
`vm-cc9d56de23154de7a22492f24dfaae27`; the snapshot inventory is empty. Replacement
compute was requested because the instruction was to reuse that validator, and
has not been approved at this checkpoint. No other VM was started or changed.

## Proton diagnosis and result

The GE-Proton 11-7 launcher downloaded for inspection has exactly the original
SHA-256 `c0fe398829c78c82b26d39c20fbeb6b28d1e46941723962d794d7e5f67d402be`.
Its manifest requires Steam Linux Runtime 4, app ID 4183110. The same runtime
`4.0.20260805.254769` and GE archive hashes were verified for the local tests:

| Input | SHA-256 |
| --- | --- |
| GE-Proton11-7-x86_64.tar.gz | `c5448b76a230384e2d7bc6beb5ccb97bafb7e2c3b6c527cb03a1a546bbcb00a0` |
| SteamLinuxRuntime_4.tar.xz | `3226d8234e7c0542ee767837832bfb1dad5e5e2dc944ec97eb221b437f6b9349` |
| Original CC0 windows-smoke.exe | `5cee03d79ce1a46be0fb9e731d2ab5ce10cba1a46de86430e6afa6553c6e1347` |
| Unchanged windows-smoke.c | `5ef05abfc2a10d7e4f5b573d9fd8c0b5aadb94dfcd9388751c5f6c33045f6208` |

`run` invokes Proton's Steam helper, or its UMU helper when that mode is selected.
For a console PE supplied as an absolute Unix path, both helpers request
`CREATE_NEW_CONSOLE` and do not inherit the parent's handles. The fixture's
`printf` therefore need not reach the captured Unix stdout or Proton log.
`runinprefix` takes a different path directly to the bundled Wine executable.
The helpers wait for their child and obtain its exit code. See the pinned
[Steam helper](https://github.com/GloriousEggroll/proton-ge-custom/blob/GE-Proton11-7/steam_helper/steam.cpp#L1199)
and [UMU helper](https://github.com/GloriousEggroll/proton-ge-custom/blob/GE-Proton11-7/umu_helper/umu.c#L285).

This explains the reproduced discrepancy. Under WSL, the original direct normal
launch returned 0 without a captured nonce, while Wine tracing independently
recorded the fixture's window creation, destruction and child exit 0. Completion
preceded the harness's process-group cleanup. The cleanup hypothesis was therefore
not the cause in this reproduction. The saved Astraeus log also loads the actual
fixture; its native Steam-client and Xalia warnings alone do not establish that
the fixture failed. The historical attempt stays FAIL because its required
observable nonce was absent.

The corrected test keeps the original PE bytes and normal Proton `run` entrypoint.
Proton's own Windows `cmd.exe` redirects the fixture's stdout and stderr to fresh
files, waits, and propagates its exit. A random nonce, matching fixture PID exit,
and creation/destruction of the same named window handle are mandatory. The
no-argument control must return the fixture's actual exit 2 and no nonce. Full
bounded Wine process/window logs are retained. No system Wine is used.

| Local diagnostic | Result |
| --- | --- |
| Original direct `run` | Exit 0; child and window complete; nonce absent from captured output, so observation contract FAIL |
| Normal `run` with explicit Windows output redirection | PASS: original fixture, fresh exact nonce, window lifecycle, traced child exit 0 |
| Normal `run` with no fixture argument | PASS negative control: traced child and outer exit 2, no nonce |
| Root controller, unprivileged desktop child, umask 0077 | Both corrected cases PASS; command file owned by the desktop user |
| First local root-controller attempt | FAIL before Proton: inherited root bus inaccessible; preserved separately, then corrected to the actual user's bus |
| Corrected Astraeus guest launch | NOT RUN: validator unavailable |
| Steam-managed authenticated launch | NOT RUN: authentication boundary retained |

The local environment is WSL/WSLg, not the pinned Astraeus image. Its missing
32-bit host loader and locale warnings remain in the logs. These tests establish
the capture defect and basic AMD64 Win32 diagnostic behavior only. GE documents
[Steam or umu-launcher as its supported launch paths](https://github.com/GloriousEggroll/proton-ge-custom/blob/GE-Proton11-7/README.md#overview).
Setting `UMU_ID` is not an umu-launcher invocation. The direct diagnostic cannot
certify Steam integration, D3D11/12, games, or upstream support for external launch.
No account or credentials were supplied.

## Gamescope and negative handling

The installed product only reports/proposes Gamescope; its controlled launch is
in validation tooling. `phase4_gamescope.py` checks the installed Vulkan-Tools
structured device inventory before invoking the nested Wayland test. Every
device's extension list, properties and DRM properties are recorded. Missing
`VK_EXT_physical_device_drm` or a render node yields JSON and actual exit 77.
Mixed-capability selection and unsupported adapter backends are explicit refusals.
Malformed/query-failed output yields FAIL and exit 2, with the query's real exit.
Missing optional tools return a named diagnostic. Preflight success promises no
presentation; an actual launch remains bounded and crash exits remain failures.

The check follows the pinned
[Gamescope DRM handling](https://github.com/ValveSoftware/gamescope/blob/3.16.31/src/rendervulkan.cpp#L434).
Missing DRM properties initially produces a warning upstream, not a universal
extension-fatal rule. On this recorded Wayland/XWayland path the renderer then
failed to supply a DRM FD and aborted. The refusal is scoped to that test path.
No upstream code, required extension check, GPU identity or driver policy changed.
Actual Gamescope presentation on the original virtual device remains UNSUPPORTED.
The original abort 134 is preserved as a failed negative, never a clean refusal.

| Negative coverage | Evidence and status |
| --- | --- |
| Missing native/lib32 Vulkan loader | Original actual guest diagnostic exits 0 with absent loader and unpassed runtime; assertions preserved in reusable namespace adapter; new guest rerun NOT RUN |
| Missing/corrupt ICD and wrong ELF architecture | Original four actual guest refusals, exit 1, remain PASS; original assertions unchanged |
| Unsupported GPU | Original software/virtual reports and no-device namespace case retained; new DRM preflight covered by controlled tests; guest refusal NOT RUN |
| Unsupported Gamescope configuration | Controlled CLI test returns 77 before launch; guest rerun NOT RUN |
| Missing optional tool | Controlled CLI test returns 77 and names Gamescope; guest namespace case added, NOT RUN |
| Malformed gaming configuration | Invalid UTF-8 MangoHud config must produce unknown/untested doctor output, exit 0, unchanged bytes; guest case added, NOT RUN |
| Malformed adapter arguments / capability data / query abort | Local parser and CLI tests verify failure/refusal codes; abort 134 remains FAIL, no Gamescope launch |
| Existing package mismatch and enable/disable refusal | Original actual exit-1 evidence preserved; transaction code unchanged |

No aggregate K pass is claimed. `phase4_negatives.py` reuses the original private
mount-namespace adapter, keeps before/after package and file hashes, and checks
actual inner return codes. Matrix hooks also reject timed-out replies even if
their captured code and text otherwise match.

## GameMode

The saved corrected upstream self-test returned 255. Basic client, dual-client,
reaper, supervisor and I/O-priority checks passed. CPU governor selection failed
with `glob failed for cpu governors`; scripts, GPU tuning and renice were not
configured. GameMode 1.8.2's
[upstream self-test](https://github.com/FeralInteractive/gamemode/blob/1.8.2/daemon/gamemode-tests.c#L786)
treats governor operation as required, so its overall failure is preserved.
The guest's absent cpufreq interface is an environment/kernel capability
limitation, not evidence that registration or the daemon failed. There is no
evidence that changing Astraeus configuration would create that capability.

The service log additionally records denied privileged split-lock tuning and an
I/O-priority restoration warning from an earlier attempt. These are not erased
by later client-test passes. No privileges, group policy or governor interface
were added. Existing wrapper/status restoration passed, but only establishes its
recorded scope. The new harness snapshots governor/EPP/split-lock values and
configuration hashes around the tests; that stronger guest restoration check
is NOT RUN. No GameMode tuning was performed on the local developer system.

## Verification and delivery

Windows: 106 Rust tests passed, formatting and warnings-denied Clippy passed.
Linux/WSL: 114 Rust tests passed, plus the separately invoked privileged Btrfs
roundtrip; formatting and warnings-denied Clippy passed. An initial shell
redirection error prevented the Linux Clippy invocation; it was corrected and
Clippy then passed. This was an orchestration error, not a suppressed finding.

Python: 119 tests per full suite. Windows passed 72 with 47 platform skips;
unprivileged Linux passed 92 with 27 skips; root Linux passed 116 with three skips.
The root-only skip for the unprivileged Gamescope CLI test is covered by the user
suite. Native Vulkan-header compilation and real qemu-img checks remain skipped
on this host. The final focused suite passed all 15 tests. Local Proton process,
window, nonce and exit controls were also executed, including the root-controller
case on the final validation source. See the [evidence manifest](evidence/phase4-runtime-remediation/FILES.json).

Production files changed: **none**. Changes are validation adapters, validation
tests, documentation and evidence. Secure Boot, signed UKIs, module trust,
package signatures, locking, snapshots, boot confirmation, recovery, driver
guards and native/lib32 consistency are unchanged. No direct package transaction,
gaming enable/disable implementation or Phase 5 work was added.

No ISO was rebuilt because the runtime is unchanged. The existing independent
CAC builds retain SHA-256
`bbc3a397dbd34672994e97405e70a5d441b206820b905cfa4f6b4bd36e69905f`
at 3,707,426,816 bytes each. Their historical full-byte comparison remains evidence
for that runtime, not a new build claim. Security/update/recovery guest regressions
were not rerun in this task; original results remain bound to CAC.

Freestyle runtime for this task: **0 seconds; $0 new VM compute/storage/transfer**.
Only inventory, snapshot-list and missing-resource reads were made. Local downloads
are not Freestyle runtime. No replacement VM exists at this checkpoint.

Remaining blockers: rerun the corrected Proton and Gamescope adapters, available
GameMode functionality/restoration, and new negative cases in the unchanged
Astraeus image; retain the upstream self-test's capability failure and the
authenticated Steam boundary. Physical GPU qualification and targeted gaming
transactions remain separate outstanding gates. This report does not validate
all of Phase 4. Changes are committed for review and are not merged; the final
documentation/evidence commit is the branch tip, separate from the validation
source revision above.
