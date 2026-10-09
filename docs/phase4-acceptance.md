# Phase 4 integrated acceptance

Verdict: **PHASE 4 NOT YET VALIDATED**. The integrated development ISO is
reproducible and boots plain and encrypted installations with enforcing Secure
Boot. Native and ELF32 software Vulkan, Steam startup and visible MangoHud overlays
have actual runtime evidence. The normal Proton launch path, full GameMode
self-test and complete optional-tool/negative matrix did not pass. Targeted
gaming transactions remain unsupported. Physical gaming is unqualified.

## Source and integration

Common base: `2e4c1725e6ad9d70654ca32158cf524feabfc91f`. Work is on
`phase4/integration` in the separate managed `phase4-integration/operating-system`
worktree. Graphics `9707583ce6773ef789a20dcb1349505c2191e3d5`, gaming
`f582b09e47cf4790a217a0845f6649ec923ee6d9` and validation
`276bea551fd68293e83bdfec1c0ad64552c3d589` were verified and merged in that
order. All three source branches and unrelated worktrees remain unchanged.
The integration plan was committed first. The CLI help conflict retained both
graphics and gaming commands; no implementation was discarded.

Frozen runtime and both ISO builds:
`cac8998ad7730e69ae354c3162ef4a0677cfc162`. Validation-only correction:
`493e2229e27456ae9e35c9845cad8fbee3087f54`, followed by the shutdown-timer fix
`722f3b97ae67587b895bce68c44608f34e4c6a8a`. Later evidence/documentation
commits do not change the runtime bytes. The final delivery commit and PR are
recorded by the delivery receipt and GitHub, separately from the frozen source.

The production GraphicsProvider consumes `distro_graphics::GraphicsReport` and
preserves it in an additive schema-1 `graphics` field. Explicit `--probe` status
and doctor use the existing bounded unprivileged native/32-bit helpers. Installed
loader, ICD presence, enumeration, successful operation and hardware acceleration
remain separate. Software or virtual devices cannot establish acceleration.
Ordinary status does not run rendering probes. Existing CLI interfaces remain.

All 31 graphics and 15 gaming catalog records use the same pinned 2026/10/01
core/extra/multilib databases; 113 direct upstream names were verified and real
pacman dependency resolution passed. The image explicitly selects
`--graphics virtio software --gaming core tools`. Core does not implicitly select
the optional tools, Lutris, Heroic or OBS. Native/lib32 Mesa and software ICD
versions match. Package signatures, update locks and driver-transition guards
remain enforced. NVIDIA activation is blocked; UKI trust does not establish
third-party kernel-module trust.

Enable/disable still return `executable: false` proposals and refuse execution.
The upgrade-only backend has no complete targeted add/remove/conflict resolver
or feature ownership ledger. Implementing that boundary safely is separate work;
initial signed image contents are not a targeted feature transaction.

## Complete A-P matrix

The original definitions in `tests/fixtures/phase4/matrix.json` are authoritative.
Their letters differ from the abbreviated integration request. The aggregate
[matrix](evidence/phase4-integration/integration-matrix.json) joins original
attempts and supplemental results without rewriting the original failed matrix.

| Gate | Result | Actual outcome |
| --- | --- | --- |
| A: Base install and boot | PASS | Fresh plain and LUKS2 installations, two cold enforcing UEFI boots each, actual Plasma Wayland, Btrfs, network/audio and health checks. |
| B: Gaming packages | PASS | Signed pinned image inputs and coherent native/lib32 package database; Core and tools explicitly selected. |
| C: Native Vulkan loader and ICD | PASS | Real native loader/ICDs, Vulkan enumeration and software device identity; no physical device qualified. |
| D: Vulkan execution | PASS | ELF64 Vulkan clears/readbacks all 256 pixels; native WSI moving cube separately observed. Software only. |
| E: 32-bit Vulkan | PASS | ELF32 loader/ICD and 256-pixel readback pass. ELF32 OpenGL presentation also passes; 32-bit Vulkan WSI remains NOT RUN. |
| F: Steam runtime and session | PASS | Steam client reached usable empty login window, runtime/dependencies diagnosed, normal close exit 0. No authentication or game acceptance. |
| G: Proton Win32 smoke | FAIL | Normal Proton run exits 0 without nonce. Genuine runinprefix diagnostic in initialized disposable prefix executes Win32 window fixture and fresh nonce, exit 0; this bounded subcheck does not replace the failed normal path. |
| H: Gamescope nested launch | UNSUPPORTED | Nested Gamescope aborts 134 on llvmpipe with missing DRM/VK_EXT_physical_device_drm prerequisites; no presentation pass. |
| I: MangoHud and GameMode | FAIL | Visible native Vulkan/OpenGL and ELF32 OpenGL MangoHud, plus ELF32 Vulkan layer invocation pass. GameMode wrapper/restoration passes; full self-test fails 255 without CPU governor interface. OpenGL window closes return 143, not zero. |
| J: Gaming readiness CLI JSON | PASS | Actual status/doctor JSON validates and reports software readback separately from unsupported hardware acceleration. Raw PCI binding and driver-selection issues remain visible. |
| K: Controlled negatives | FAIL | Four ICD/architecture and nine production negatives pass; vendor policies covered by controlled Rust fixtures. Gamescope unsupported-device launch still aborts, so the complete no-crash negative requirement is unmet. |
| L: Encrypted gaming setup | UNSUPPORTED | Initial signed gaming image passes encrypted boots and probes. Targeted feature transactions remain blocked proposals, not executable setup. |
| M: Signed update and rollback | PASS | All source-bound Phase 3 update/fallback/recovery/powercut/metadata gates and Phase 2 payload/space/package/health/service/interruption/direct-package regressions pass. |
| N: Enforcing Secure Boot | PASS | Enforced real boot plus exact integrated loader/UKI trusted controls and unsigned/untrusted/tampered firmware refusals with denied-image records. |
| O: Independent ISO bytes | PASS | Independent clean builds, full-file comparison exit 0 and identical package manifests/ISO SHA256. |
| P: Physical GPU qualification | NOT RUN | NVIDIA/AMD/Intel/hybrid, controllers, hardware Vulkan, VRR/HDR and real game frametimes require approved physical qualification. |

## Actual runtime

The target is Q35/KVM/SMM with enforcing OVMF, Virtio VGA and no GPU passthrough.
Installed guests use 4 vCPU/4 GiB; the gaming overlay uses 4 vCPU/8 GiB. Plasma
Wayland, XWayland, NetworkManager and PipeWire passed the installed checks, with
no unexpected failed units. Both plain and LUKS2 installations passed two cold,
ISO-detached enforcing boots with exact owner PK/KEK/db and packaged binary
hashes. Initial installation and test-owner provisioning used compatibility
setup before those acceptance boots. Test agents/accounts and private signing keys do not ship in
the ISO. The gaming overlay's recorded test-only autologin does not qualify
authentication; the baselines used normal login and encrypted unlock.

The real PCI device is Virtio `1af4:1050`. PCI discovery records its `virtio-pci`
binding; the raw graphics report retains the candidate-driver mismatch warning
and unmatched physical-device observations. It does not invent a native GPU.
Both architectures enumerate llvmpipe (LLVM 23.1.1, 256 bits), vendor `0x10005`,
CPU device type 4. The independent 16x16 fixture verifies all 256 pixels; the
packaged graphics helpers separately pass their own render/readback operation.
Gaming JSON reports `runtime_verified/passed` for software Vulkan and
`unsupported/untested` for hardware acceleration. Native OpenGL and XWayland
pass. Native moving-cube presentation is separate from the offscreen proof;
ELF32 OpenGL presentation also passed with the installed `glxgears32`, while
32-bit Vulkan window-system presentation remains unqualified.

Steam's pinned bootstrap is `1.0.0.87-3`. The real client updated to build
`1788652215`, initialized Scout `steam-runtime_1.0.20260714.251828` and its browser
container `3c.0.20260729.253765` with pressure-vessel `0.20260728.0`. Its actual
32-bit ELF and runtime library check passed, as did `steam-runtime-system-info`.
The usable empty login window was inspected, then closed normally: exit 0 after
797.2 seconds. No personal credentials were requested or entered. Its QR-bearing
screenshot stays in the private export. Client startup is not authenticated game
execution, Steam Input or broad Steam compatibility.

The manually inspected GE-Proton 11-7 x86_64 fixture came from the
[official release](https://github.com/GloriousEggroll/proton-ge-custom/releases/tag/GE-Proton11-7).
Archive SHA256:
`c5448b76a230384e2d7bc6beb5ccb97bafb7e2c3b6c527cb03a1a546bbcb00a0`.
Its manifest selects Steam Linux Runtime 4, app ID 4183110, tested at
`4.0.20260805.254769`, SHA256
`3226d8234e7c0542ee767837832bfb1dad5e5e2dc944ec97eb221b437f6b9349`.
HTTPS origin and published checksums were verified; no independent publisher
signature is claimed. Archives were inspected and extracted into disposable
user-owned directories with safe extraction. No product downloader or automatic
trust of discovered tools was added.

The source-owned CC0 AMD64 Win32 fixture SHA256 is
`5cee03d79ce1a46be0fb9e731d2ab5ce10cba1a46de86430e6afa6553c6e1347`.
Normal Proton `run` attempts exited 0 without the required nonce and therefore
failed. Preserving X authentication and setting install-path visibility did not
fix that; the executable was already visible. A later genuine `runinprefix`
invocation through the matching runtime, in the initialized disposable prefix,
created/destroyed the fixture window, printed fresh nonce
`fd80504268a2485783806e49cc75c814` and exited 0. Its Wine cleanup warning is
retained. This bounded diagnostic does not replace the failed normal launch or
qualify D3D11, D3D12, 32-bit Windows applications or any game.

MangoHud was visible in two changing Vulkan frames and two OpenGL frames.
The cube closed with exit 0; the OpenGL window close returned 143, which is
recorded rather than called exit 0. ELF32 layer invocation/readback passed.
The subsequent ELF32 OpenGL test also showed a changing overlay in two frames.
Its actual `glxinfo32` result reports llvmpipe and no acceleration; window close
returned 143 with no timeout. Virtual GPU telemetry and CPU temperature were
unavailable, as preserved in MangoHud's logs. GameMode readiness, wrapper workload and
restoration passed on the corrected session. Its full self-test still failed
255 because the guest has no CPU governor interface. Gamescope selected llvmpipe
but aborted 134 with missing DRM/VK_EXT_physical_device_drm prerequisites and
XWayland/wlserver errors. No global preload, permanent tuning or trust bypass
was used to manufacture a pass.

## Security regressions

All final source-bound security cases passed:

| Evidence case | Verified behavior |
| --- | --- |
| `h-plain` | Signed update, pre/post snapshots, correct root/UKI pair, enforced candidate boot, confirmation and known-good blessing |
| `i-plain` | Damaged candidate consumes three attempts; trusted retained root boots; no false promotion; persistent data survives |
| `j-luks` | Same fallback with normal LUKS2 unlock, signed live recovery, healthy restored root, original packages/data and explicit idempotent finalization |
| `k-plain` | Correlated power cut at generation activation; exact journal and trusted prior root retained; unsafe continuation refused |
| `l-plain` | Unknown metadata field, wrong root/UKI identities, stale transaction reference and corrupt SQLite record refused |
| `m-plain-r2` | Trusted live plain rollback and healthy reboot; the earlier `m-plain` timer timeout remains a failed attempt |
| `reg-payload`, `reg-space` | Invalid payload and insufficient cache capacity refused before snapshots/mutation; state remains unchanged after reboot |
| `reg-package`, `reg-health`, `reg-service` | Deliberate failures require rollback; signed recovery restores packages/root while preserving user data and failure history |
| `reg-interruption` | Power cut after verified package mutation; durable intent reconciles to recovery-required; trusted rollback and finalization pass |
| `security-direct-package` | Actual signed pacman mutation outside the coordinator is refused without changing protected state |


Firmware tests use the exact installed loader and UKI, independently signed
trusted/untrusted controls and a trusted EFI LoadImage probe. Trusted controls
return `0000000000000000`; unsigned, untrusted and tampered variants each return
`800000000000000f` plus a matching `DENIED_IMAGE` authentication record. The
original probe's `integrated_acceptance=false` is preserved. Artifact provenance
binds its security result to the integrated image; A separately proves execution.

Signed-update tests use the small validation package upgrade `1-1` to `2-1`.
They do not qualify arbitrary kernel/systemd upgrades or targeted gaming package
changes. The power cut covers one completed-sync/before-loader-rename boundary;
its exact pending journal is retained and unsafe continuation refused. It does
not establish arbitrary power-loss safety. Trusted fallback selects a retained
root/UKI; canonical restoration and explicit finalization remain separate steps.

The recovery companion authenticates its loader, kernel/initrd and command line.
Its live SquashFS is not cryptographically covered by that signature. Tests use
the exact host-hashed ISO and companion read-only. Production recovery-media
signing, root/ESP atomicity, interrupted rollback resumption, whole-disk-full
behavior, physical enrollment and key recovery/rotation remain unqualified.

## Builds, host checks and retained failures

Two independent clean Arch guests built the same frozen source and signed inputs.
Both ISOs are **3,707,426,816 bytes**, SHA256:

```text
bbc3a397dbd34672994e97405e70a5d441b206820b905cfa4f6b4bd36e69905f
```

Full-file comparison exited 0. Source/input JSON and builder, live, installed,
platform-package and source manifests match. The source archive is 1,033,160
bytes, SHA256
`779a0065f6469727f237e637c14932542e84bc55cef25b84393a5af787440068`.
Repository signer: `D1C5011CA247200E6194FE0E33784DB62DDE4F5F`.
The audit found the exact live/installed binaries and ELF64/ELF32 helpers, with
no private signing keys or test agents/accounts in the ISO. Existing mkinitcpio
chroot/root-detection, memdiskfind and firmware warnings are retained; actual
UEFI boots passed. BIOS boot is not qualified.

Locked Rust tests, formatting and warnings-denied Clippy passed on Windows and
Linux: 106 and 114 Rust tests respectively, plus the separately executed ignored
real Btrfs roundtrip. Final Python discovery ran 114 tests: Windows skipped 42;
root Linux skipped 2. The two missing WSL capabilities, native Vulkan compilation
and real qcow2 overlay testing, then passed on Freestyle. Native signing, Btrfs
lock/snapshot checks, all 14 shell syntax checks, catalog/archive resolution,
both probe builds and actual runtime JSON schema checks passed. GitHub CI passed
at the frozen runtime and validation correction; final delivery CI is linked in
the receipt.

The initial clean build failed at ELF32 linking because lib32-gcc-libs was absent
from builder inputs. That failure is retained; the build dependency and pinned
compiler-runtime metadata were corrected before the two final builds. A focused
regression failed before and passed after the fix. Later test-only corrections
preserved XAUTHORITY, replaced an unavailable xdpyinfo call with the actual user
XWayland process plus GLX execution, and read `VERSIONS.txt` instead of an
unsupported runtime `--version` flag. Their regression and same-ISO reruns pass.

The first plain recovery attempt timed out before entering recovery. Its
one-second poweroff timer inherited systemd's default one-minute coalescing
window, which could consume the harness's 60-second wait. Validation-only
`722f3b9` sets `AccuracySec=1s` on that transient timer, retaining the original
deadline and clean-exit requirement. The focused regression failed before and
passed after; both full Python suites passed. The failed `m-plain` run remains
separate from the fresh `m-plain-r2` retry. The frozen ISO/harness is unchanged;
later recovery runs use a clean separately recorded validation checkout.

Other retained attempts include the first Steam initialization timeout, an
oversized Steam log inspection, the initial negative namespace/package overlay
fixtures, failed Proton paths, Gamescope and GameMode failures, and the partial
QMP setup command that triggered the disposable user's normal failure counter.
The latter was corrected without changing password or authentication policy.
The second builder briefly paused at the outer disk reserve; after verified
redundant-copy reclamation it resumed and matched A. No failed attempt is counted
as a pass because another check succeeded.

## Evidence, cleanup and remaining qualification

Compact evidence is committed under [`docs/evidence/phase4-integration`](evidence/phase4-integration).
The runtime source archive, both ISOs, signed repository, independent build logs,
failed build and full acceptance archives are exported to
`D:/Astraeus-Phase4-Integration-Evidence`. Public acceptance archive:
`acceptance-public.tar.gz`, 792,776,880 bytes, SHA256
`5fdf3389c2b6f3445f4ae75f43924ccb912ad91e11febf3cd6217d193f999f04`.
Its hash and all 3,234 payload members were verified, then extracted to `public/`.
The private context archive is 794,651,782 bytes, SHA256
`33a8b506efc0c3b14cb9d65f31d59518692a8c7c2afedbb2d425f24a50b45b0e`;
all 3,291 payload members were verified. Private keys, test secrets, VARS, raw
password hashes, QR-bearing Steam screenshot and owner-bearing disks remain in
the access-restricted `private/` export, outside Git and the public archive.
The public export redacts the four Calamares/serial test-password hash occurrences.

Both fresh installed baselines and original installation disks have verified
local copies. Historical Phase 0-3 evidence remains intact in Git. Retired
historical disks were losslessly archived, every member rehashed locally, and
unused backing references checked before removal. Restoring archived old LUKS
overlays requires restoring the exported old LUKS baseline to its recorded path.
The old plain baseline remains on the validator for historical dependents.
Remote ISO B was hardlinked to A only after independent full-byte comparison and
verification of both distinct local exports. All storage receipts are retained.
The exact signed repository is separately exported and all 19 members verified;
its disposable signing identity is not a production release identity.


Reused `astraeus-phase0-validator`, `vm-cc9d56de23154de7a22492f24dfaae27`,
Ubuntu 24.04.5 LTS, kernel 6.1.102, 8 vCPU, 16 GiB RAM and 64 GiB disk.
Heavy nested guests ran sequentially. All nested QEMU processes were stopped
before export, and the validator was paused at `2026-10-09T08:46:01.867650Z`.
The final provider inventory has zero running/starting VMs and two paused VMs.
The unrelated `atm10` provider record is unchanged. Cumulative runtime increased
from 97,410 to 115,097 seconds: **17,687 seconds (4h 54m 47s)**.

At the [published allocation rates](https://www.freestyle.sh/docs/vms/pricing-and-limits),
gross compute is about **$2.60**, plus **$0.03** active-time storage, about **$2.63**
combined before allowances/credits. Transfer and later paused storage are excluded;
this is not an invoice. Paused storage remains allocated. The existing 3,600-second
idle timeout and 86,400-second auto-delete policy were recorded and left unchanged.
Verified local exports are the durable handoff. See
[the usage/cleanup receipt](evidence/phase4-integration/freestyle-summary.json).


NVIDIA/AMD/Intel/hybrid hardware, module-signature enforcement and ABI/GSP checks,
controllers/Steam Input, physical VRR/HDR, suspend/offload/external displays and
real-game frametimes remain NOT RUN. The
[physical procedure](phase4-physical-qualification.md) requires deliberately
approved disposable media or an isolated disk. The owner's Ryzen 7 7800X3D,
RTX 5070, 32 GB Windows machine, partition table, firmware keys and primary boot
configuration were not changed. Unsupported NVIDIA activation and driver/kernel
transitions remain blocked. No PR was merged, stable release created or Phase 5
work begun.

## Historical validation-branch report

The original report below is retained verbatim. Its incomplete Phase 3 baseline
runtime results describe the earlier validation branch, not this integrated ISO.

# Phase 4 infrastructure results

Phase 4 is **not validated**. Production graphics and gaming branches were not
merged, modified or included in an integrated ISO run.

Confirmed base: `2e4c1725e6ad9d70654ca32158cf524feabfc91f`.
Branch: `phase4/validation`, managed worktree
`C:/Users/Noel/.codex/worktrees/phase4-validation/operating-system`.
Final executed harness: `f4ce16a54337413603fe802754785015ef1464a1`.
Installed baseline source: `fdb784c8539fb7679f7ab6e350583f523a80728d`.
Delivery commit is recorded separately so the receipt can name its actual hash.

## Actual environment and observations

Reused `astraeus-phase0-validator`,
`vm-cc9d56de23154de7a22492f24dfaae27`, Ubuntu 24.04, outer kernel 6.1.102,
8 vCPU, 16 GiB RAM, 64 GiB disk. Its initial state was paused, cumulative
runtime 96,468 seconds. The local development host is Windows with an Ubuntu
26.04 WSL environment. No compute was created/resized, billing/access changed,
or unrelated VM modified. The complete `atm10` provider record is identical
before and after. No nested QEMU remained when the final export was made.

Three sequential plain Btrfs overlays booted the accepted Phase 3 baseline.
The first collected missing-session/compiler prerequisites. The second prepared
test-only SDDM autologin in its overlay and used a source/hash-bound ELF64
fixture. The final repeated those checks with the final adapter corrections.
The short-revision attempt was rejected before creating an output or guest.
Each completed run shut down cleanly and reverified disk/VARS baseline hashes.

QEMU 8.2.2, OVMF 2024.02-2ubuntu0.10, enforcing
`/usr/share/OVMF/OVMF_CODE_4M.secboot.fd`, Q35/KVM/SMM, protected pflash,
4 vCPU/4 GiB, private QMP and command channel, no VNC or forwarded port.
The guest reports Virtio 1.0 GPU `1af4:1050`, with no physical GPU passthrough.
Plasma Wayland used Virtual-1 at 1280x800, approximately 74.99 Hz.
KWin's actual OpenGL renderer was
`llvmpipe (LLVM 23.1.1, 256 bits)`, Mesa 26.2.3-arch1.2, EGL/OpenGL 4.6.
Its output reports Adaptive Sync incapable. Physical VRR/HDR is UNSUPPORTED.
Input enumeration found virtual keyboard/mouse/tablet devices. No virtual
gamepad event injection or physical controller qualification was performed.

The installed loader linked the ELF64 fixture successfully. Actual Vulkan
enumeration failed with exit 1, `VkResult=-3`, and real Mesa/RADV device errors.
Only Intel, Intel HasVK, Nouveau and Radeon ICD manifests were present.
Manifest discovery passes; a usable Vulkan device and a Vulkan renderer were
not established. `vulkaninfo`, `glxinfo` and `xdpyinfo` were absent and their
diagnostic checks are NOT RUN. This baseline is from Phase 3, not the pending
gaming image. These results do not identify a Phase 4 production regression.

The ELF64 fixture separately passed all 256 pixel checks on local WSL software
Vulkan: llvmpipe LLVM 21.1.8, device type CPU, vendor 0x10005. It used the actual
`lvp_icd.json`; loader output, binary/source/ICD hashes and exact build command
are in `software-vulkan.json`. This is fixture qualification on Ubuntu, not
Astraeus Vulkan or physical GPU acceptance.

Missing and corrupt ICD negatives returned real nonzero exits with loader
diagnostics in both the Astraeus guest and local software self-check. The earlier
wrong-architecture receipt in `baseline-03` is retained but invalid as proof:
its library path did not exist. The final adapter requires an actual ELF32
library and an ELFCLASS32 diagnostic. The final architecture case is NOT RUN.
The lib32 loader package is absent; 32-bit dependency checks fail, runtime is
NOT RUN/UNVERIFIED, and no coherent 32-bit userspace is claimed.

Steam, Proton, Gamescope, MangoHud and GameMode runtime checks remain NOT RUN
where their tools are absent. GameMode readiness/restoration cannot pass without
its daemon. The source-owned CC0 Win32 fixture compiles warning-free to AMD64 PE
using MinGW GCC 16.1.0, but no Proton execution occurred. No Steam credentials,
paid game, private session or hardware test was used. Login/game execution and
Steam Runtime readiness remain unqualified. There is no FPS benefit claim.

## Matrix and regressions

The final machine matrix is
[`matrix.json`](evidence/phase4/baseline-final/matrix.json).
Its A-P statuses represent expected gaming acceptance requirements on the
incomplete baseline, not historical Phase 3 passes. B/D/E/I expose prerequisite
or execution failures; the other scenarios remain NOT RUN. Physical output
limitations are recorded separately as UNSUPPORTED. Raw command exit codes and
partial subchecks remain visible. `completed=true` in the runner receipt means
evidence collection completed; `gaming_validated=false` remains explicit.

Observed baseline cold boot, enforcing firmware identity and signed loader
checks passed. Existing Phase 2 health predicates passed before/after, with
identical package maps, snapshots and transaction history. Existing native
signature/owner-policy, package-guard and Btrfs lock/snapshot unit/integration
checks also passed locally. No signing rule or update guard was disabled.

New gaming-package signed updates, failed-candidate fallback, LUKS2 feature setup,
recovery, firmware-negative probes on final gaming bytes and independent gaming
ISO builds are NOT RUN. Those must reuse the existing Phase 3 adapters after the
production merges. Prior Phase 3 acceptance does not qualify those regressions.

## Checks

All requested commands passed with the locked workspace and Python discovery:

| Check | Result and evidence |
| --- | --- |
| Windows cargo test / fmt / Clippy | PASS, `rust-windows.log`, `fmt-windows.log`, `clippy-windows.log` |
| Linux cargo test / fmt / Clippy | PASS, `rust-linux.log`, `fmt-linux.log`, `clippy-linux.log` |
| Windows Python | 103 tests, 40 platform/tool skips, `python-windows.log` |
| Unprivileged WSL Python | 103 tests, 26 skips, `python-linux.log` |
| Root WSL Python with disposable Btrfs enabled | 103 tests, one skip for unavailable qemu-img, `python-linux-root.log`; native signing and real Btrfs lock checks ran |
| Freestyle Python | 103 tests, 26 skips, `python-freestyle.log`; real QMP sockets and qcow2 overlay tests ran |
| Ignored disposable Linux Btrfs roundtrip | PASS, `btrfs-linux.log` |
| Vulkan source compile / readback / missing+corrupt ICD self-check | PASS on local software renderer, `software-vulkan.json` |
| Win32 fixture compilation | PASS, `fixture-builds.json`; runtime NOT RUN |

The initial Python 3.11 f-string syntax failure is retained as
`python-windows-first-failure.log`; the final source passes. Existing acceptance
tests remain intact. No new production dependency was added.

## Evidence and cleanup

Compact committed evidence: [`docs/evidence/phase4`](evidence/phase4).
Full public archive: `D:/Astraeus-Phase4-Validation-Evidence/public-evidence.tar.gz`,
579,380 bytes, SHA256
`f489fb5f8a7169f5139981ef3966dd223dc6d556d8841d10eaa7426167ec90d8`.
The archive and every member hash were verified locally. It contains original
and final attempts, command replies, source/fixture hashes, package/CLI/session
state, failed units, security observations, logs and baseline/overlay hashes.
Private owner disks, keys and VARS bytes are excluded. Public fixture binaries
and their source-bound manifest are retained in the archive/export directory.

Freestyle work is confined to `/home/ubuntu/p4`. The validator is paused,
cumulative runtime 97,410 seconds. Added runtime: **942 seconds (15m 42s)**.
At published allocation rates this is about **$0.14 before included allowances**,
including active-time storage and excluding data transfer. Actual invoice/credits
were not inspected. Rates and accounting are in `freestyle-summary.json`.
Paused storage remains allocated. Its existing one-day auto-delete policy was
recorded and left unchanged; the public evidence is exported independently.

## Remaining work for Chat 4

1. Merge the production graphics/gaming work through its normal review process.
   Supply the real readiness JSON, preset, package-resolution and fault hooks
   listed in [the validation runbook](phase4-validation.md).
2. Prepare signed plain/LUKS2 gaming baselines without direct-package guard or
   signature bypasses. Include a software Vulkan ICD when that test capability
   is advertised, tools, coherent lib32 libraries and source-bound ELF32 fixture.
3. Execute Vulkan64/32, Steam Runtime/session/login-boundary inspection, explicit
   Proton+Runtime smoke, Gamescope presentation, visible MangoHud and GameMode
   restoration. Run missing-driver/architecture/vendor/dependency/preset and
   transaction negatives against actual public interfaces.
4. Repeat A/L and all M/N security/update/recovery gates. Build O independently
   only after integration and compare full ISO bytes.
5. Qualify NVIDIA/AMD/Intel/hybrid, controllers and physical VRR/HDR only with
   actual hardware and evidence. The RTX 5070 desktop plan requires explicit
   preparation/approval and never touches Windows disks or firmware keys.

No merge, Phase 4 validation declaration or Phase 5 work is included.
