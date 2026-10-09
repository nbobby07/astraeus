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
