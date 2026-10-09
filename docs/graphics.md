# Graphics foundation

## Phase 4 integration

The integrated ISO at `cac8998ad7730e69ae354c3162ef4a0677cfc162` executed
both ELF64 and ELF32 Vulkan clear/readback on llvmpipe (LLVM 23.1.1, 256 bits),
vendor `0x10005`, CPU device type 4. The actual Virtio GPU remains a virtual
device. Gaming JSON correctly reports successful software Vulkan operations and
unsupported hardware acceleration. Native/ELF32 OpenGL and XWayland also passed after the
test adapter preserved the desktop user's actual XAUTHORITY path. This did not
change the ISO, authentication policy or cookie. Physical rows remain unqualified;
see [acceptance](phase4-acceptance.md) for exact evidence and failed attempts.

Gaming consumes this report directly, with no second GPU discovery implementation.
Use `distroctl gaming doctor --probe --json` for the same raw native/32-bit probe
results plus Steam diagnostics. Reports keep installed loader, installed ICD,
enumerated device, successful clear/readback and physical acceleration distinct.

An explicit `--graphics software` image bundle adds pinned `vulkan-swrast` and
`lib32-vulkan-swrast` (`1:26.2.3-2`), plus the existing native/32-bit Mesa diagnostic
utilities. It is optional and is never selected automatically for a physical GPU.
The virtual acceptance image selects `--graphics virtio software`. Lavapipe
readback is software API evidence only; it does not establish host GPU acceleration.
The shared transaction guard now also rejects mismatched software ICD versions.

NVIDIA activation and driver/kernel transitions remain refused. Signed UKIs do
not establish third-party kernel-module trust. AMD/Intel/Nouveau selection and
existing kernel bindings are unchanged. The original graphics implementation
record follows; final runtime results belong to [acceptance](phase4-acceptance.md).

This branch provides read-only graphics diagnostics, explicit image bundles and
transaction preconditions. It does not qualify Phase 4 or physical GPU support.

The base is `2e4c1725e6ad9d70654ca32158cf524feabfc91f`. Graphics policy consumes
the existing `distro-hardware` probe. It does not rediscover PCI devices or change
bindings, global environment variables, firmware, boot policy or compositor settings.

## Commands and evidence

```sh
distroctl graphics
distroctl graphics --json
distroctl graphics --probe --json
```

Ordinary inspection reads the pacman local database, ELF headers, system ICD
manifests, existing hardware observations and NVIDIA sysfs state. With a loaded
NVIDIA module, it also reads on-disk version, vermagic and signer with `modinfo`.
It never loads a module. Installed packages, ELF files and manifest API versions
are evidence of installation only. Missing/unreadable metadata cannot pass a check.

`--probe` calls separate ELF64 and ELF32 helpers as the invoking desktop user.
Each loads the Vulkan loader, requests Vulkan 1.1, enumerates physical devices,
records the device API version and raw vendor-specific driver version, driver
properties and PCI bus information where available. A 1.0-only implementation is
reported unsupported by this probe, not mislabeled as absent. It performs a 4x4
offscreen graphics render-pass clear, image-to-buffer copy and pixel comparison
on each device. The fence wait is three seconds; each helper has a 20-second
outer deadline and a 1 MiB stdout limit. Driver errors, unavailable helpers,
crashes and headless failures remain diagnostic outcomes. No display connection
is required. The helpers refuse root/setuid execution because they load userspace
driver code and inherit the invoking user's environment.

The smoke test verifies a color attachment, graphics queue, transfer and readback.
It does **not** test shader compilation, swapchain/presentation, window-system
integration, synchronization under load, Proton features or game performance.
Vulkan API version alone is not a game compatibility verdict. Consumers must
check the extensions/features their application requires separately. Standard
`vulkaninfo --summary` and `vulkaninfo --json=N --output FILE` remain available
from `vulkan-tools` for deeper manual investigation. The CLI never scrapes their
human-readable output or mistakes their first GPU for every GPU.

CPU devices and the llvmpipe driver ID are always software. A passing software
readback does not establish GPU acceleration. Virtual Vulkan devices describe
the guest interface, not which physical host GPU rendered. Per-GPU matching uses
PCI bus address when supplied; otherwise vendor/device IDs must identify exactly
one discovered GPU. Identical GPUs without bus information remain ambiguous.
Unmatched Vulkan devices stay visible in the architecture report. Multiple ICDs
for one GPU are not collapsed into a single successful rendering claim.

The OpenGL renderer is currently null. Wayland session state describes only
`XDG_SESSION_TYPE` of this invocation. It does not prove KWin uses a particular GPU.
Per-GPU Wayland support remains unknown except an observed NVIDIA KMS failure.
VRR, HDR and actual loaded firmware remain unknown. No package set proves them.

## Driver selection

`distro/graphics/bundles.json` is the shared package policy. Candidate selection
and requirements are separate from installed state and actual rendering results.

| Hardware/binding | Candidate | Boundary |
| --- | --- | --- |
| AMD, amdgpu or unbound | Mesa RadeonSI and RADV | Kernel chooses the binding; legacy radeon does not automatically become amdgpu |
| AMD, radeon | Existing Mesa legacy stack | No RADV promise or forced SI/CIK kernel parameters |
| Intel | Mesa Iris/Crocus and ANV | Accept observed i915 or xe; no force-probe or generation guess |
| NVIDIA, nouveau already bound | Mesa Nouveau and NVK | Preserve driver family; generation/API support requires runtime checks |
| NVIDIA in the pinned open-module device list | NVIDIA open-module candidate and proprietary userspace | Activation refused until module trust and transaction support exist |
| Older, unknown or subsystem-only NVIDIA entry | No automatic NVIDIA candidate | Review required; no legacy AUR/vendor installer or silent fallback |
| Virtio | Mesa VirGL/Venus candidate | Host Venus/virgl support and guest rendering must be tested |
| VMware, QEMU display, QXL, Hyper-V, unknown | Existing display stack | No hardware Vulkan claim |

Integrated versus discrete identity comes only from a uniquely matched Vulkan
device type, not from an AMD or Intel vendor ID. `boot_gpu` is populated only for
exactly one `boot_vga=true`; it is explicitly not compositor priority. Hybrid
requirements are a deduplicated union, retaining both GPU records. Intel+NVIDIA,
AMD+NVIDIA and AMD+AMD can therefore expose different readiness for each device
and architecture.

Offloading is an application-level choice. Mesa supports `DRI_PRIME` and NVIDIA
provides `prime-run` through optional `nvidia-prime`. Neither is applied globally.
Use a scoped launch environment and recheck the selected device in that same
environment. Games, diagnostic tools, containers and Steam runtimes can see
different ICD search paths, permissions and libraries. The report lists detected
override variable names, never their values, and warns when results are scoped
by them. System manifest inventory does not model user ICD directories or the
dynamic linker's entire search path; the actual probes expose the runtime result.

## Pinned packages and multilib

All repositories use `2026/10/01`: core, extra and the newly pinned multilib.
The multilib database SHA-256 is
`17e1a87e6ecd932e053e6553187a468820c9dbc2e3a0954162f7ca349c4d47cf`.
The existing core and extra hashes are unchanged. Build resolvers consume
verified local metadata through the existing CacheServer arrangement. Both
installed and live pacman templates use the same archive date; required package
signatures and the curated repository's required database signature are retained.
No live mirror, partial refresh, `pacman -Sy`, signature bypass or AUR is added.

| Selection | Direct graphics packages |
| --- | --- |
| Installed base | mesa, lib32-mesa, vulkan-icd-loader, lib32-vulkan-icd-loader, vulkan-tools |
| amd | linux-firmware-amdgpu, vulkan-radeon, lib32-vulkan-radeon |
| intel | linux-firmware-intel, vulkan-intel, lib32-vulkan-intel |
| nouveau | linux-firmware-nvidia, vulkan-nouveau, lib32-vulkan-nouveau |
| virtio | vulkan-virtio, lib32-vulkan-virtio |
| nvidia-open candidate, refused for activation | nvidia-open, nvidia-utils, lib32-nvidia-utils, egl-wayland, egl-wayland2, egl-gbm |
| Optional investigation/offload | mesa-utils, lib32-mesa-utils, nvidia-prime |
| Probe build | gcc, lib32-glibc, lib32-gcc-libs, vulkan-headers |

Mesa and its Vulkan/32-bit packages are `1:26.2.3-2`. Both Vulkan loaders and
vulkan-tools are `1.4.357.0-1`; firmware is `20260916-1`. The existing installed
`linux-firmware` metapackage already depends on the vendor firmware packages,
including amdgpu, Intel and NVIDIA. Keeping it preserves non-graphics firmware.
No AMDGPU-PRO package is required. The pinned GCC includes its 32-bit compiler
runtime objects; there is no `gcc-multilib` package in this snapshot.

`distro/graphics/packages.lock.json` records the exact version, repository,
filename, archive hash, dependencies, provides and conflicts of all 28 graphics,
diagnostic and build inputs. The archive lock includes these inputs too. Transitive
dependencies remain pacman's responsibility, not a hand-maintained replacement
solver. To verify the metadata and optionally resolve every bundle:

```sh
python3 scripts/bootstrap.py verify-archive --output out/graphics-archive
python3 scripts/check-graphics-packages.py out/graphics-archive --pacman /usr/bin/pacman
```

The second command uses disposable local/sync databases and print-only pacman
operations. It verifies that the inputs remain unchanged. It does not download,
authenticate or install package archives, run hooks, or qualify an image.

### Image selection

The live medium retains its existing broad Mesa/Intel/Radeon/Nouveau display
coverage. The installed payload now has a vendor-neutral Mesa and dual-loader
base. **The default installed image has no selected vendor Vulkan ICD.** Select
the intended hardware bundles at build time, including all intended hybrid GPUs:

```sh
python3 scripts/bootstrap.py iso --repo /absolute/repo --fingerprint FULL_FINGERPRINT \
  --output /absolute/new-build --graphics amd intel
```

The existing build runs in a disposable root-owned Arch builder. It adds the
selected native and 32-bit packages to the separate pacstrap payload, then records
the selection in build `inputs.json` and installed
`/usr/share/distro/install-inputs/graphics.json`. Omitting `--graphics` deliberately
builds the base, whose diagnostics report missing hardware-specific requirements.
No install-time network or package mutation job is added. A universal offline
gaming image must deliberately select the desired union; a hardware-specific
image can avoid irrelevant vendor ICDs. Calamares does not yet select/prune these
bundles dynamically. Existing installed systems do not acquire packages by
upgrading distroctl alone. Chat 2 must treat missing requirements as a precondition,
not run a separate package manager to fill them.

## NVIDIA release and trust boundary

The pinned repository contains `nvidia-open 615.71.09-4`,
`nvidia-utils 615.71.09-1` and `lib32-nvidia-utils 615.71.09-1`.
Both the kernel package and lib32 userspace require `nvidia-utils=615.71.09`.
The inspected nvidia-open archive has hash
`3e6cac6bb7c24cea068d1a987e7c40b68a094529c19720b3eb2db6008d281c97`
and modules beneath `/usr/lib/modules/7.2.7-arch1-1/extramodules`, matching
`linux 7.2.7.arch1-1`. Its dependency on linux is not an ABI proof on another kernel.
NVIDIA requires matching module, GSP and userspace releases. DKMS and LTS variants
exist upstream but are not selected: this project supports one stock kernel and
has no qualified DKMS/module-signing update path.

`nvidia-open.json` contains 217 generic PCI IDs extracted from NVIDIA's versioned
615.71.09 open-module README, with source URL and SHA-256. Entries requiring PCI
subsystem IDs are deliberately excluded because the current hardware model lacks
those observations. Turing and later can use open modules; Blackwell and later
require them. The repository does not contain the old proprietary `nvidia` or
legacy branches. Absence from this list means unsupported by this policy, not
proof that the silicon can never work. No GPU-name substring, broad numeric PCI
range or guessed NVIDIA generation authorizes activation.

The open kernel modules still need proprietary NVIDIA userspace. They are not
Nouveau. Existing Nouveau users stay on Nouveau, and the alternative is advisory.
`nvidia_drm` KMS must be observed enabled for the Wayland path; this code does not
rewrite the signed kernel command line or assume a package default enabled it.
Loaded module version, on-disk module version, kernel vermagic and native/lib32
userspace disagreement are reported separately. A signer string is recorded but
never interpreted as trusted. Actual loaded flavor and signature enforcement
remain unknown without stronger evidence.

Phase 3 signs PE boot artifacts, not external `.ko` modules. Firmware db enrollment
does not automatically establish a trusted module-signing key in the running
kernel. There is no shim/MOK enrollment, module signing hook, or attested kernel
keyring here. Both NVIDIA image activation and updates touching NVIDIA packages,
or linux/linux-headers while NVIDIA packages are installed, return unsupported.
This conservative refusal applies even to unsigned development installations.
It prevents an unqualified path from becoming an implicit supported one.

## Updates, recovery and Chat 2 interface

The new crate is `distro-graphics`, with no new external Rust dependency:

```text
distro-hardware::probe() -> Hardware
distro_graphics::discover(root) -> Observations
distro_graphics::select_driver(&Gpu) -> DriverSelection
distro_graphics::bundle_packages(bundle) -> Vec<String>
distro_graphics::diagnose(Hardware, Observations) -> GraphicsReport
distro_graphics::probe(runtime) -> GraphicsReport
distro_graphics::validate_update(current, candidate) -> Result<(), String>
```

Use `GraphicsReport` or `distroctl graphics --probe --json` as the graphics input
to gaming readiness. `required_packages` is a requirements set, **not an executable
transaction**. The current `DesiredUpdate` supports only `SystemUpgrade`.
No install/activate command is accepted. Package-family changes require an
explicit reviewed plan and a future complete resolver that can account for
removals/conflicts; the existing adapter refuses those cases.

`ExecutionPlan::validate` calls the graphics precondition check before download,
snapshots or mutation. Native/lib32 Mesa, Vulkan loader and selected ICD versions
must agree by upstream version. NVIDIA changes described above are rejected as
a whole plan. Already installed ordinary Mesa updates continue through the same
full-system update coordinator, MutationGuard, pre/post snapshots, matching UKI,
retained known-good generation and boot confirmation. No coordinator, health
provider, service, kernel mitigation or signed-boot guard is replaced. Existing
systemd/bootloader and distroctl self-update refusals remain intact.

Graphics success is **not** automatically included in the existing boot-health
promotion gate. Operators must compare diagnostics after a GPU update and after
reboot, test the desktop, and use the existing offline root/UKI recovery flow if
the graphics stack regresses. Automated session-bound graphics health needs
separate integration; running user ICDs as the privileged confirmer is unsafe.
No partial pacman upgrade, direct driver installer, unsigned vendor binary or
external repository is an alternative to a refused transaction.

### JSON schema 1

Consumers ignore unknown additive fields, preserve null, and handle unrecognized
future enum values conservatively. Status enum values are `present`, `absent`,
`passed`, `failed`, `unsupported`, `unknown`, `untested`. Presence and successful
testing are separate states. Command exit 0 means diagnostics were collected,
not that gaming is ready; malformed CLI arguments exit 1.

| Field | Meaning |
| --- | --- |
| schema_version, archive_date | Protocol version and selection-policy snapshot |
| gpus | null if hardware discovery unavailable; otherwise per-device objects |
| gpus[].hardware | Existing hardware GPU object, including observed kernel binding |
| gpus[].selection | Candidate bundle, possible kernel drivers, userspace, ICD library, reason/alternative |
| gpus[].required_packages, missing_packages | Requirements; missing is null if package database unavailable |
| gpus[].firmware_package, firmware_loaded | Package observation versus actual firmware, which remains unknown |
| gpus[].native_devices, compat32_devices | Indices into the corresponding runtime device arrays, empty if unmatched/untested |
| gpus[].form_factor | integrated/discrete/virtual only from uniquely matched runtime type; otherwise null |
| gpus[].rendering | Native matched-device smoke result, never derived from packages |
| native, compat32 | Architecture bits, ELF loader state, system ICD observations, enumeration, loader API, runtime devices |
| native.devices[], compat32.devices[] | Name, numeric vendor/device/type, packed Vulkan API, raw driver version, optional driver ID/name/info and PCI address, software boolean, rendering result |
| boot_gpu, multi_gpu | Firmware-boot device index and hardware count evidence; nullable |
| wayland | Calling session, nullable active flag/compositor GPU, unknown VRR/HDR |
| opengl_renderer | null until an OpenGL context is actually queried |
| nvidia_module | Loaded/disk version, vermagic, KMS, signer; trust unknown and activation unsupported |
| packages, required_packages | Observed installed name/version map, or null; union of requirements |
| environment_overrides | Present override variable names, not values |
| activation, activation_reason | Unsupported mutation boundary, not a runtime rendering verdict |
| issues[] | Stable code, optional GPU index, explanatory message |

A game-specific readiness consumer must select a device, require non-software
evidence, inspect that architecture's enumeration and rendering results, and apply
its own feature requirements. The native GPU's smoke result says nothing about
the 32-bit GPU unless both architectures actually tested the intended device.
Do not replace missing evidence with `true`, infer readiness from an empty issues
array, or merge different devices' successful checks.

## Verification and remaining work

Recorded host checks are in [checks.json](evidence/phase4-graphics/checks.json),
with [resolved package graphs](evidence/phase4-graphics/package-graph.json).
Windows passed 88 Rust tests and Linux/WSL passed 95, with one ignored Linux
loopback test. Formatting and warnings-denied Clippy passed. Python ran 99 tests
on each host: 62 passed/37 skipped on Windows and 72 passed/27 skipped on WSL.
Skips are explicit platform, root, signing-tool, Vulkan-header or QEMU requirements.
Raw local logs remain under ignored `out/graphics`; their hashes are recorded.

Separate GCC checks built both ELF64 and ELF32 probes with warnings denied using
isolated Ubuntu development packages in the worktree, without installing them on
the host. The [64-bit probe](evidence/phase4-graphics/native-probe64.json) passed
offscreen readback on software llvmpipe. The
[32-bit probe](evidence/phase4-graphics/native-probe32.json) ran and reported an
absent loader; 32-bit rendering was not tested. A root invocation returned
unsupported. These are helper checks on WSL, not pinned Arch package/image or
physical GPU acceptance. Online archive verification matched all three database
hashes and 98 direct package versions. Print-only pacman resolved eight cases,
including every bundle, the mixed Mesa set and build inputs.

The normal Rust and Python suites cover vendor and hybrid fixtures, unknown and
virtual devices, legacy NVIDIA/radeon policy, missing firmware packages/loaders/
ICDs, ELF architecture, native/lib32 mismatch, wrong bindings, software rendering,
ambiguous identical GPUs, module/kernel mismatches, JSON and mutation refusal.
The existing transaction test also verifies NVIDIA plans cannot reach snapshots
or package application. `test_graphics.py` can compile/run the native helper when
Vulkan headers exist; an unavailable compiler/header is an explicit skip.

Required release checks remain:

1. Build the distroctl package and both probes on the pinned Arch builder, install
   signed bundle packages, and rebuild/requalify image reproducibility.
2. Test AMD APU and discrete, old/new Intel i915/xe, NVIDIA Turing/Ampere/Ada and
   Blackwell, older rejected NVIDIA, hybrid combinations, and virtual/display-only
   devices. Record both architectures, permissions and exact library/device IDs.
3. Run native/32-bit Vulkan and OpenGL workloads, Wayland presentation, game shader
   compilation, suspend/resume, offload and external displays on physical machines.
4. Qualify full update, reboot, rollback and recovery with the existing signed
   generation infrastructure. Preserve a verified root/UKI pair and diagnostic
   evidence before deliberately inducing a driver failure.
5. Before enabling NVIDIA activation, integrate module signing, trusted-keyring
   verification, module ABI/GSP checks, safe initramfs contents and transaction
   health into the existing owner trust model. Do not weaken Secure Boot to pass.

No Steam, Proton, Gamescope, MangoHud, gaming manager, Freestyle/QEMU harness or
Phase 5 work is included. Expected merge conflicts are workspace Cargo files,
distroctl dependency/dispatch/package recipe, installed package list, archive lock,
pacman template, and narrow bootstrap/installer build arguments. The transaction
manifest/plan guard has an additional graphics dependency. Resolve shared lists
as unions of reviewed policy, regenerate Cargo.lock and rerun all checks.

References: [NVIDIA 615.71.09 open modules](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/615.71.09/README.md),
[NVIDIA module flavors](https://download.nvidia.com/XFree86/Linux-x86_64/615.71.09/README/kernel_open.html),
[Vulkan loader driver discovery](https://github.com/KhronosGroup/Vulkan-Loader/blob/main/docs/LoaderDriverInterface.md),
[Vulkan-Tools output modes](https://github.com/KhronosGroup/Vulkan-Tools/blob/main/vulkaninfo/vulkaninfo.md),
[Mesa per-process selection](https://docs.mesa3d.org/envvars.html),
[the pinned archive](https://archive.archlinux.org/repos/2026/10/01/).
