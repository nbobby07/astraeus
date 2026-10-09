# Phase 4 validation infrastructure

Base: `2e4c1725e6ad9d70654ca32158cf524feabfc91f`. Branch: `phase4/validation`.
This work owns tests and evidence only. Phase 4 is not validated.

## Running the harness

`scripts/validate/phase4.py` imports the existing Phase 2 VM, overlay, health,
command-channel and QMP helpers. It requires the sealed `phase3-integrated`
baseline and its exact enforcing OVMF CODE hash. It copies VARS, never enrolls
keys, never writes the baseline, and starts only its own foreground QEMU child.
The command is recorded under `boot-1/qemu-command.json`: Q35/KVM/SMM, 4 vCPU,
4 GiB, UEFI, protected pflash, virtio-vga, private Unix QMP and command sockets,
read-only test share, no VNC and no port forwarding. Plain and LUKS2 baselines
use the same adapter; encrypted unlock remains a private QMP/manual step.

```sh
python3 scripts/validate/phase4.py matrix --output /new/path/matrix.json
sudo python3 scripts/validate/phase4.py run \
  --base /home/ubuntu/p3i/final/base-plain --output /home/ubuntu/p4/plain-01 \
  --ovmf-code /usr/share/OVMF/OVMF_CODE_4M.secboot.fd \
  --source-commit FULL_HARNESS_SHA --user tester --timeout 180
```

Log into the disposable Plasma account through private QMP before desktop
probes. Root-agent readiness alone cannot certify a desktop. A missing user
session records NOT RUN. Never transmit credentials in argv, recorded commands,
screenshots or shell history. The command channel is test-only and must never
ship in an ISO or package. Each retry gets a new output directory.

The baseline source revision, requested revision, actual harness commit/dirty
state, all adapter/fixture hashes, QEMU version, firmware identity and baseline
hashes are retained. Disk/VARS hashes are recorded after shutdown. Guest JSON
contains exact commands, exits, bounded output, elapsed process lifetime, ICD
contents/hashes, package state, ELF/link diagnostics, renderer and session data.
Phase 2 observations collect failed units, history, snapshots, mounts, logs and
CLI JSON before and after. Probes must preserve package, snapshot and history
state. Evidence stays on the outer host; it is exported before discarding disks.
Output over 4 MiB fails, rather than becoming a truncated pass.

## Graphics and gaming boundaries

The source-owned CC0 Vulkan fixture clears a 16x16 linear image on a graphics
queue, waits for its fence and checks every RGBA pixel. It reports pointer width,
device type, vendor and renderer. This proves submission/readback, not shader,
swapchain, DirectX, game compatibility or performance. A coherent linear image
memory type is required; its absence returns 77 (UNSUPPORTED). Compile both
`cc -m64` and `cc -m32` against the installed libraries. A failed fixture build
leaves runtime NOT RUN. Package/dependency results remain separate. Run `file`
and `ldd` on each executable, then require the exact bitness and readback marker.

`vulkaninfo --summary` and loader debug output preserve actual ICD selection.
`glxinfo -B`, `xdpyinfo`, `kscreen-doctor -o` and the real Plasma environment
provide separate OpenGL, XWayland, display and Wayland observations. Software
devices, Lavapipe and llvmpipe are explicitly marked software. Even a hardware
renderer name alone cannot qualify a physical vendor.

The loader negatives use per-process ICD overrides, leaving `/etc`, installed
ICDs and package state untouched. Missing, corrupt and ELF32-only ICDs must
produce nonzero exits with actionable loader diagnostics. A 32-bit missing-ICD
negative runs only when its real ELF32 workload built. Missing tools are failures
for the tool check, while dependent workloads remain NOT RUN. Unsupported
virtual hardware is a separate capability result, never a generic escape from
an advertised capability failure.

Steam launches as the desktop user with a new writable disposable HOME. Logs,
exit and lifetime are captured. Launch survival or reaching login is not a game
pass. Runtime diagnostic inspection and the login screen remain explicit gates;
the adapter cannot infer them from files. No personal credentials are requested.

For Proton, supply `--proton /inspected/guest/path/proton` and
`--runtime /inspected/guest/path/SteamLinuxRuntime_sniper/_v2-entry-point`.
The adapter uses that runtime to run Proton, never silently substitutes Wine.
It builds the checked-in CC0 `windows-smoke.c` using MinGW, hashes the PE and
Proton script, and uses a fresh compatibility prefix and nonce. Only real Win32
window creation, destruction, matching nonce and exit 0 pass. Compiler/runtime
absence remains NOT RUN. Preserve runtime version, dependency logs and Proton
logs. This does not qualify DXVK, VKD3D or a game. Fixture source and executable
hashes are mandatory evidence; no third-party executable download is needed.

Gamescope and MangoHud run a bounded `vkcube --c 60`. A timeout is not success.
The offscreen wrapper test is distinct from presentation. Visible MangoHud
requires a private QMP screenshot and manual confirmation. Its absence remains
NOT RUN. GameMode runs its own `gamemoded -t`, wrapper workload and before/after
daemon status comparison. Preserve power/governor observations when qualifying
physical hardware. No FPS gain is claimed.

Controller evidence enumerates actual Linux input devices and Steam udev rules.
It does not certify Steam Input behavior. To test a virtual controller later,
use a dedicated guest `/dev/uinput` producer with a unique test identity, record
evdev button/axis events and remove only that producer; verify disappearance and
permissions afterward. No physical Xbox/PlayStation claim follows. Virtual
refresh data and gamescope support are observations; physical VRR/HDR is
UNSUPPORTED on this target and must be tested separately.

## Integration hooks and regressions

The machine matrix has all A-P scenarios, expected behavior, actual result,
environment, hardware, evidence paths, exit codes and four allowed statuses.
Missing hooks stay NOT RUN. Aggregate FAIL takes priority; partial passes never
hide missing subchecks. The matrix JSON is an evidence adapter, not a product
readiness API or an integrated Phase 4 acceptance declaration.

Chat 1 must provide the final GPU/readiness observation schema and supported
test input boundary for no device, unknown vendor, missing lib32 and corrupt
graphics configuration. Chat 2 must provide real readiness/preset commands,
expected JSON, stable refusal exits and diagnostics, package feature resolution,
Proton/runtime policy and supported dependency/transaction fault boundaries.
Do not invent their command names or modify their implementations.

`--hooks /public/guest-hooks.json` accepts keys from the pending K checks and
`readiness-json`. Each contains `command`, exact `exit_code`, and nonempty
`marker`. Commands execute only through the existing disposable guest channel;
readiness JSON must also parse. A crash with the expected text is not accepted
unless the actual expected exit matches, so integration must use deliberate
refusal codes, never signal/crash exits. Hooks must inspect actual public CLI
output and must not print secrets, edit SQLite, or return canned success.

After Chat 1 and Chat 2 merge, build a gaming baseline through signed product
transactions. Repeat A/L with installed-smoke.sh. Reuse Phase 3
`docs/evidence/phase3-integration/integrated-run.py`, `integrated-regression.py`,
`integrated-fallback-recovery.py`, `integrated-powercut.py`, the direct-package
refusal adapter and `scripts/validate/phase3.py` firmware probes. Those historical
adapters pin their source/paths: copy them into a new private integration area
and update only inspected revision/path/artifact identities. Retain their health,
signature, root/UKI, snapshot, history and recovery predicates unchanged.

M needs signed valid/invalid repository inputs, preserved known-good generations,
Btrfs snapshots/history, deliberate failed update, plain/LUKS recovery and direct
package permission refusal. N needs actual enforcing boot, trusted UKI signatures
and unsigned/untrusted/tampered loader/UKI refusal. A trusted baseline boot alone
does not repeat these negative security gates. O requires two independent final
ISO builds and complete byte comparison. Historical Phase 3 results establish
the baseline only; they do not pass new Phase 4 regressions.

Do not disable signing, guards, UKI verification or enforcement to install Steam.
Do not perform a final integrated ISO run during parallel production work.

## Cost and cleanup

Inspect the Freestyle inventory before resuming the existing validator. Never
create or resize compute, change billing, or alter unrelated VMs. Run one guest
at a time and check free space first. Keep a host reserve; overlays are sparse
but writes still consume storage. Avoid builds until production integration.
After shutdown, verify baseline hashes, export public evidence and hashes, confirm
the owned QEMU child stopped, then pause the validator. Keep private keys, owner
disks and credentials outside source and evidence exports. The provider's current
auto-delete timer must be recorded; pausing does not disable deletion.

Upstream references used for these probes: [Vulkan memory synchronization](https://docs.vulkan.org/spec/latest/chapters/memory.html),
[Vulkan cube](https://github.com/KhronosGroup/Vulkan-Tools/blob/main/cube/cube.c),
[Proton launcher](https://github.com/ValveSoftware/Proton/blob/proton_10.0/proton),
[MangoHud](https://github.com/flightlessmango/MangoHud), and
[GameMode tests](https://github.com/FeralInteractive/gamemode).
