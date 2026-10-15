# Physical graphics qualification

## Integration boundary

The integrated virtual target may execute Vulkan on Lavapipe in both architectures.
That result does not pass any physical row below. RTX 5070 qualification additionally
requires its exact PCI ID in the pinned open-module support list, matching module,
GSP, native/lib32 userspace and kernel ABI, plus independently demonstrated kernel
module-signature enforcement and trust. Firmware acceptance of the UKI is insufficient.
Nouveau-to-NVIDIA transitions remain blocked. No changes to the owner's Windows
installation, partition table, firmware keys or primary boot configuration are authorized.

All physical rows are NOT RUN and unqualified. CPU VMs and software Vulkan
provide no vendor compatibility or performance qualification.

The integrated virtual results at `cac8998ad7730e69ae354c3162ef4a0677cfc162`
do not change that status. Before qualifying a physical gaming target, repeat
the normal Proton launch path, Gamescope presentation and full GameMode self-test
that did not pass on the virtual target. Also supply visible ELF32 presentation
and overlay evidence, then separate D3D11/D3D12 and real-game results. The
successful software readback and bounded Proton `runinprefix` fixture cover
neither those paths nor real game frametimes. Use a recorded game/build, scene,
resolution, graphics settings and frame-time capture with thermal/power context;
do not infer a performance improvement from an FPS overlay.

| Target | Required evidence | Current state |
| --- | --- | --- |
| NVIDIA RTX 5070, Ryzen 7 7800X3D owner's Windows desktop | PCI IDs, exact driver/kernel/firmware, modules, native/lib32 ICDs, real Vulkan/OpenGL execution, Plasma Wayland/XWayland, signed boot, suspend/reboot | NOT RUN; no disk or firmware changes authorized |
| AMD discrete/integrated | Same graphics and security checks, RADV/device identity, controller and display probes | NOT RUN; hardware not assigned |
| Intel discrete/integrated | Same graphics and security checks, ANV/device identity, controller and display probes | NOT RUN; hardware not assigned |
| Hybrid AMD/Intel plus NVIDIA | Both enumerated GPUs, default/offload renderer, external-display ownership, suspend and unplug/replug behavior | NOT RUN; hardware not assigned |

Before execution, the owner must explicitly approve a particular live USB or
spare-disk session and prepare backups, recovery media, disk identities and a
clear stop procedure. The RTX desktop's Windows disks must remain untouched;
prefer physically disconnected internal storage and an identified spare disk.
Never repartition the Windows disk or enroll Astraeus keys in physical firmware.
If existing firmware cannot authenticate the test media, signed physical boot
qualification remains NOT RUN. Do not automatically change firmware policy.

A reviewed live USB can establish bounded driver/userspace observations without
installation, using the existing firmware policy. A spare-disk installation is
a separate, explicitly approved step. The installer must target only the
prepared spare disk, confirmed by model/serial/capacity. No physical operation
is run by the Phase 4 harness.

Collect the same A-P evidence schema: exact source/ISO/firmware/artifact hashes,
package state, loaded module versions, PCI/DRM topology, selected 64/32-bit ICDs,
renderer and workload exits, logs and failed units. Run Steam only to its login
boundary unless a later explicit session is authorized. Run the CC0 Proton
fixture using its recorded source/binary hash and inspected Steam Linux Runtime.
Qualify Gamescope presentation, visible MangoHud and GameMode restoration
separately. Retain actual connected controller model/transport and button/axis
events before naming Xbox or PlayStation compatibility.

VRR needs a capable GPU, cable and display, advertised connector capabilities,
observed compositor state and visible output verification across changing frame
rates. HDR needs capable display/cable, EDID metadata, compositor and application
support plus actual HDR output confirmation. A setting or EDID alone is not a
runtime pass. Record resolution/refresh, display model and mode, and distinguish
application, compositor and physical-output limits. No performance benefit is
claimed without a separately approved measurement protocol.

Stop on unexpected disk discovery, signature refusal, firmware enrollment prompt,
loss of the intended recovery path, heat/power instability or unresolved driver
faults. Export evidence and shut down before reconnecting Windows storage.
