# Physical hardware qualification plan

Status: **plan only**. No physical run has been performed. Nothing here changes a
recorded VM result or qualifies any machine. Originally drafted at `8a4f1e5`;
reconciled with accepted runtime `c38209c` on 2026-10-15. See the
[current live-boot handoff](release-readiness.md) before using a candidate.

This plan extends [physical graphics qualification](phase4-physical-qualification.md).
Its rules remain in force until the owner records the decisions below: the owner's
Windows desktop stays untouched, and Astraeus keys are never enrolled in physical
firmware. Items marked **Decision needed** block the phase that depends on them.

## Current boundary

Every acceptance result so far is x86-64 UEFI under QEMU/KVM with disposable
overlays and test owner keys: Phases 0-3 ([roadmap](roadmap.md)), Phase 4/4.1
([acceptance](phase4-acceptance.md), [requalification](phase4-runtime-requalification.md)),
Phase 4.2 ([acceptance](phase42-acceptance.md)) and Phase 5.0 VM acceptance passed
([acceptance](phase5-acceptance.md)). Those harnesses rely on facts that do not
exist on a physical PC:

| VM mechanism | Where | Physical equivalent |
| --- | --- | --- |
| QMP screenshots, keyboard input, power control | `scripts/validate/qmp.py`, `install-smoke.py`, `visual-boot.py` | Operator at the console; photos; Plasma screenshots |
| Serial console markers | `boot-smoke.py`, `phase42-baseline.py`, `phase42-recovery-check.py` | `journalctl` after boot; photos before userspace |
| Host-edited OVMF VARS; enrollment by `virt-fw-vars` | `phase42-baseline.py:475`, `phase3.py` | Firmware setup UI only |
| Pristine VARS copies, disk overlays, sealed baselines | `phase2.py`, `phase42.py`, `phase42-faults.py` | None. Real disks and NVRAM are mutated in place |
| virtio command port and 9p share, `systemd-detect-virt == kvm` guard | `phase2-guest.py:22-26`, `phase42-baseline.py:105`, `phase42-faults.py:83` | None. These guards must keep refusing physical machines |
| virtio disk assertion | `tests/boot/installed-smoke.sh:35` | NVMe/SATA/USB transport |
| Disposable VM marker | `scripts/validate/phase5.py:48,54` | Operator-declared disposable-machine record |
| `LoadImage` refusal probe with authentication records | Phase 3 B-G | Firmware refusal screen when booting removable media |

Product facts that matter on real hardware:

- The live ISO is unsigned, UEFI-only (`bootmodes=('uefi.systemd-boot')`, label
  `DISTRO_BOOT` in `distro/archiso/profiledef.sh.in`) and has no shim. Firmware
  enforcing factory keys will refuse it. Live boot and installation need Secure
  Boot disabled. Installation with `SecureBoot=1` is refused by `guard-legacy`.
- Calamares finalization runs `bootctl --esp-path=/efi install`
  (`scripts/provision.py:129`). On real firmware this normally also registers a
  boot entry and changes `BootOrder` in NVRAM.
- `check-enrollment` accepts dbx only when it is empty or contains only SHA-256
  image entries (`scripts/secure_boot.py:341-358`). Factory dbx lists that contain
  certificate entries fail closed. This may block signed updates on some
  machines and must be observed before enrollment.
- `prepare-test-keys` writes `DISPOSABLE-OVMF-ONLY` and must never be used for
  physical firmware (`scripts/secure_boot.py:674`).
- The Phase 4.2 validation repository key `6DA84EB4...6306695F72` expires
  2026-10-15 16:18:26 UTC. An image signed with it cannot perform later package
  operations. The Phase 4.1 expired-signature failure is the precedent.
- The newer Phase 5 candidate uses key
  `27CCE96199D30A7ABA1BE86CC6722DAA8014EE89`, expiring at
  2026-10-16 08:55:39 UTC. It selects software Vulkan only, with no gaming
  features. It is not the proposed vendor-GPU image below.
- Performance comparison now recognizes bare metal from readable CPU flags
  without a hypervisor flag and tolerates small kernel-related memory changes.
  Unknown classification still blocks comparison. This has unit coverage only;
  physical comparison remains unqualified. Live sessions permit passive
  recording, but refuse baselines.

## Goals

- Show that a specific, recorded image installs, boots, updates, rolls back and
  recovers on specific, recorded physical machines, with plain and LUKS2 layouts.
- Show owner-enforced Secure Boot on real firmware, with a recovery route that
  was tested before it was needed.
- Turn Phase 4 row P and the deferred GameMode full self-test into per-machine
  results on real GPUs and CPU frequency interfaces.
- Record Phase 5 baselines with real thermal and power context, and state exactly
  what they establish.
- Produce evidence that can be reviewed without QEMU artifacts and that protects
  machine and user privacy.

## Non-goals

- NVIDIA proprietary/open-module activation, driver switching and kernel-module
  trust. These remain refused ([graphics](graphics.md)). NVIDIA rows test Nouveau/NVK only.
- Dual boot, manual partitioning, shared ESPs, TPM unlock, swap/hibernation.
- Production signing, release keys or a public release.
- Repeating all 70 Phase 4.2 fault gates. Space, hook and signing-failure logic
  is hardware-independent and stays VM-qualified.
- General power-loss safety, sustained stress, automatic tuning, cross-machine
  performance ranking or gaming performance claims.
- Any support statement for hardware that was not tested. A pass covers its exact
  model, firmware version, image and configuration.

## Prerequisites before any hardware is touched

1. **Decision needed:** authorize testing on dedicated, disposable machines and
   amend the "never enroll" rule for those machines only (D1).
2. A candidate image built for physical GPUs. The default payload has no vendor
   Vulkan ICD ([image selection](graphics.md#image-selection)). **Decision needed:**
   one union image (`--graphics amd intel nouveau`) or one image per vendor (D6).
   Either way it is a new image. It needs the normal two-independent-build
   comparison and VM install/boot gates before physical use. Earlier image
   evidence does not carry over.
3. A repository signing key that remains valid for the whole test window (D7).
4. Host checks pass at the candidate commit ([testing](testing.md)).
5. Physical test owner keys exist and their custody is decided (D4).

## Hardware matrix

Each row is one physical machine identified by a private alias (for example
`amd-desktop-1`). Record make/model, firmware vendor and version, CPU, GPUs with
PCI IDs, RAM, storage model/transport/capacity and display. Disk serials stay private.

| ID | Class | CPU | GPU(s) | Install targets | Firmware focus | Priority |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | Desktop | AMD Ryzen with iGPU | AMD Radeon discrete (RADV) plus iGPU fallback | NVMe, SATA SSD, USB SSD | AMI Aptio (retail board) | First |
| M2 | Laptop | Intel Core 12th gen+ or Core Ultra | Intel iGPU (i915 or xe, ANV) | Internal NVMe, USB SSD | Insyde H2O or OEM (Dell/Lenovo/HP) | Second |
| M3 | Hybrid laptop | Intel or AMD | iGPU + NVIDIA Turing or newer (Nouveau/NVK) | Internal NVMe | OEM | Third |
| M4 | Desktop | Intel Core with iGPU | Intel Arc discrete | NVMe, SATA SSD | Different board vendor from M1 | Later |
| M5 | Laptop | AMD Ryzen APU | AMD iGPU (RADV) | Internal NVMe | Phoenix or OEM | Later |
| M6 | Desktop | Any | NVIDIA discrete on Nouveau/NVK | NVMe | Any | Later |
| OD | Owner desktop | Ryzen 7 7800X3D | RTX 5070 (Blackwell), Raphael iGPU | None authorized | Unknown | Blocked (D2) |

Coverage targets across the matrix: AMD and Intel CPUs; AMD, Intel and NVIDIA
GPUs, including one hybrid; desktop and laptop; NVMe, SATA and USB install
targets; at least two firmware vendors. Rotational disks, Blackwell on Nouveau,
VRR and HDR are optional rows. They stay `NOT RUN` until hardware is assigned.

## Machine preparation

Complete this checklist before the first boot of each machine and keep the result
in its private record:

- No Windows installation and no personal data. If a disk ever held BitLocker
  volumes, wipe it before testing (D5).
- Firmware updated to a recorded version, or deliberately left as shipped with
  that version recorded. Firmware is not updated in the middle of a round.
- No firmware supervisor password, or one stored with the machine record.
- Setup and one-time-boot hotkeys confirmed. Photograph every Secure Boot and
  key-management screen, plus the boot order, before changing anything.
- A display path that does not depend on a discrete GPU's option ROM (iGPU or
  motherboard output), or a recorded reason why none exists.
- The vendor's factory-key restore option and CMOS clear method located in the
  manual and photographed.
- Install target identified by model, capacity and serial. Physically disconnect
  every other internal disk.
- AC power. Laptops start each destructive step at 50% charge or more.

## USB live media

1. On the build host, check the ISO against `iso/SHA256SUMS` and the recorded
   build identity. On Windows use `Get-FileHash -Algorithm SHA256`.
2. Write raw bytes to a device addressed by stable ID:

   ```sh
   sudo dd if=astraeus.iso of=/dev/disk/by-id/usb-VENDOR_MODEL_SERIAL-0:0 \
     bs=4M conv=fsync oflag=direct status=progress
   sudo cmp -n "$(stat -c %s astraeus.iso)" astraeus.iso \
     /dev/disk/by-id/usb-VENDOR_MODEL_SERIAL-0:0
   ```

   ISO-extracting writers and multi-boot loaders such as Ventoy rewrite or wrap
   the loader. Their results are not evidence for this image. **Decision needed:**
   approved writer when no Linux host is available (D8). Whatever writer is used,
   a raw readback comparison is mandatory.
3. After the session, repeat the readback comparison. The ISO9660 medium should
   be unchanged. The check detects write and media errors. It is not
   authentication: a modified medium can misreport itself.
4. The signed recovery medium is a raw `recovery.img` from
   `scripts/validate/phase42-recovery.py`. Write it the same way and compare it
   against `manifest.json` (`image_sha256`, `image_bytes`). Prefer a stick with a
   hardware write-protect switch, because nothing else makes it read-only.
5. Keep separate sticks for live, recovery, refusal tests and evidence. Never
   reuse a refusal-test stick as live media without rewriting and readback.

## Secure Boot owner enrollment on real firmware

Under D1 this applies only to dedicated machines. No project tool writes firmware
variables ([ADR 0003](adr/0003-owner-secure-boot.md)). Enrollment happens in the
firmware UI, with the operator present.

### Read-only inspection

Boot the live medium with Secure Boot temporarily disabled and record:

- `distroctl status --json` and `distroctl hardware --json`
- `distroctl security status --json`: SecureBoot, SetupMode, AuditMode and
  PK/KEK/db/dbx membership
- Whether dbx contains only SHA-256 entries. If it contains certificate entries,
  `check-enrollment` will refuse. Record this as a product blocker for that machine
  and do not clear dbx.
- Raw copies of `PK`, `KEK`, `db` and `dbx` from `/sys/firmware/efi/efivars/`,
  with SHA-256. Each file includes the 4-byte attribute header. Also use any
  firmware "export keys to file" option.

Store the backups on two separate media. Hash them on both before continuing.

### Enrollment modes

**Decision needed:** mode per round (D3).

| Mode | Firmware result | Risk |
| --- | --- | --- |
| A: append | Factory PK/KEK/db/dbx kept; owner db certificate appended through the firmware UI | Lowest. Microsoft-signed option ROMs keep working. Anything Microsoft-signed, including shim-based loaders, also stays trusted, so this is owner trust in addition to factory trust. Not all firmware offers it |
| B: owner PK, factory entries retained | Setup mode, then owner KEK/db plus backed-up factory KEK/db entries, owner PK last | Moderate. Matches the ADR's PK/KEK/db roles while keeping option-ROM trust |
| C: exclusive owner | Owner-only db | Highest. GPU, NIC or storage option ROMs signed by Microsoft's UEFI CA can fail, causing a blank firmware display or a missing boot device. Never on laptops; on desktops only after B passes with an iGPU fallback |

Recommended order: A on M1 where the firmware supports it, then B on M1. C is
out of scope unless separately approved.

### Steps

1. Install with Secure Boot disabled (see the test cases). Provision the owner
   signer and sign/verify loader and UKI candidates as described in
   [owner-managed Secure Boot](secure-boot.md). Do not run `distroctl boot enable` yet.
2. Copy only public enrollment files (`.cer`/`.esl`, or `.auth` if the firmware
   requires it) to a FAT32 stick. Private keys never go on this stick.
3. In firmware, enroll according to the selected mode, enable Secure Boot, save,
   and power off completely.
4. Cold boot. Require `SecureBoot=1`, `SetupMode=0`, `AuditMode` not true, the owner
   certificate in db, and passing `astraeus-secure-boot check-config`, `verify uki`
   and `verify bootloader`. Then run a second cold boot.
5. Only then run `sudo distroctl boot enable`, matching the Phase 3 order.

### Recovery ladder

Try each step in order. Stop at the first step that restores a known state.

1. **Firmware reachable, OS refused:** disable Secure Boot. Keys are left
   unchanged, and the signed loader boots without enforcement. Collect
   `security status` and verify output, then decide whether to fix or revert.
2. **Revert keys:** use the firmware's factory-key restore, then compare efivarfs
   contents against the backups from a live session. If the vendor default
   differs from the backup (for example after OEM key updates), re-enroll the
   backed-up entries through the UI.
3. **No firmware display:** move the display to the iGPU or motherboard output,
   or remove the discrete GPU, then go back to step 2.
4. **CMOS clear:** follow the vendor manual. Many firmwares keep keys in SPI
   NVRAM, not CMOS. Rely on this step only if it was demonstrated on that model
   beforehand.
5. **Vendor firmware recovery** (for example USB BIOS Flashback): last resort.
   It resets all settings.
6. **Stop:** if nothing works, retire the machine from the matrix, record the
   result and run no further rounds on that model.

Test steps 1 and 2 on M1 before the first enforcing round.

## Dual boot

Recommendation: **not supported** for this qualification (D5).

- The installer has only erase-disk. Manual and alongside paths are disabled
  ([installation](installation.md)). It creates its own 1 GiB ESP. A typical
  Windows ESP is 100-260 MiB, and sharing one is unqualified.
- Boot generations are a single-installation layout and reject foreign BLS/Type #2
  entries ([boot generations](boot-generations.md)).
- Turning Secure Boot on or off, or changing PK/KEK/db, changes the measurements
  BitLocker normally binds (PCR 7) and triggers a recovery-key prompt. Without
  the recovery key, the Windows data is lost.
- Windows servicing can update dbx and boot order. A certificate-type dbx update
  would make Astraeus signed updates fail closed on that machine.
- `bootctl install` changes NVRAM boot order, which affects the other OS.

The lowest-risk future option is coexistence on a separate disk, each OS with its
own ESP and selection through the firmware boot menu. It needs its own design and
tests: BitLocker behavior, Windows updates, and an untouched Windows Boot Manager.
This plan does not cover it.

## Install, upgrade, rollback and recovery cases

Each case runs on plain and LUKS2 unless noted. A case passes only after its
evidence is retained. Software-only paths that are already VM-qualified are not repeated.

| ID | Origin | Physical procedure | Pass evidence |
| --- | --- | --- | --- |
| L1 | Phase 0 boot smoke | Live boot through the one-time boot menu, Secure Boot disabled | `journalctl -u live-smoke.service` contains `DISTRO_BOOT_OK` and `DISTRO_LIVE_MANAGEMENT_OK`; hardware/status JSON |
| L2 | Phase 1 refusal | Select a stick smaller than 20 GiB as the target | Refusal before any partition write; stick bytes unchanged (readback) |
| I1 | Phase 1 install | Real Calamares UI, erase-disk on the identified target. Cancel once before the summary commit, then install | Summary/completion photos, `/var/log/installer/storage.json`, partition table, NVRAM boot entries before and after |
| I2 | Phase 1 boots | Two cold boots without the live stick, real SDDM/Plasma Wayland login | Adapted installed smoke per boot: UEFI/UKI, Btrfs, encryption, transport, network, audio, no failed units |
| I3 | Transports | Repeat I1-I2 on SATA and USB targets on M1 | Correct `storage[].transport`; USB target boots from the firmware menu |
| S1 | Phase 3 A | Enrollment as above; two enforcing cold boots | Firmware JSON, verify output, boot IDs |
| S2 | Phase 3 B-G | Boot removable sticks containing an unsigned, wrong-key and tampered `BOOTX64.EFI`, plus a signed loader with an unsigned/wrong-key/tampered UKI | Photo of the firmware or loader refusal for each; internal ESP hashes unchanged; trusted control stick boots |
| U1 | Phase 3 H | Signed update through `sudo distroctl update` from the approved source (D9) | Snapshot pair, candidate boot, confirmation, history; still enforcing |
| U2 | Phase 3 I | Force failed candidate attempts by holding the power button during candidate boot until counters are consumed | Fallback to retained root/UKI, no promotion, data preserved. Arbitrary-timing power loss is not claimed (D14) |
| R1 | Phase 3 J/M, 4.2 metadata | Boot the signed recovery USB under enforcement, run the offline `distroctl rollback ID --dry-run`, then `--execute` | RAM-verification marker photo or journal, rollback output, healthy installed boot, explicit finalization |
| R2 | 4.2 media cases | Recovery media refusal: untrusted, unsigned, tampered, altered root, Secure Boot disabled | Refusal and poweroff for each; no installed disk changes |
| G1 | 4.2 GUI | Control Center install/remove of a small package with polkit, then reboot | Screenshots, history, verified reboot |
| T1 | Platform | Suspend/resume, lid (laptops), Wi-Fi, wired network, speaker/headphone/HDMI audio, battery and brightness reporting | Journal around each transition; observed result per item |

Under enforcing Secure Boot, the signed UKI's embedded command line cannot be
changed for debugging. A failure that needs kernel debug options is diagnosed
with Secure Boot disabled and recorded as such.

## Graphics and gaming

Follow the [gaming runtime evidence contract](gaming-runtime-tests.md) and Phase 4
rows C-K per machine and GPU:

- `distroctl graphics --probe --json` and `distroctl gaming doctor --probe --json`
  must identify the real vendor ICD and device. A software renderer is a failure.
- Native and 32-bit Vulkan/OpenGL rendering, `vkcube`/`glxgears` visible in Plasma
  Wayland and XWayland, plus 32-bit Vulkan WSI.
- Steam up to its login window. Use the CC0 Proton fixture on the normal path.
  Real games and a licensed D3D11/D3D12 application need D12.
- Gamescope nested presentation on a real DRM device. MangoHud overlay must be
  visible on Vulkan, OpenGL and 32-bit.
- **GameMode full self-test.** Before the test, capture governors, EPP values,
  `split_lock_mitigate` and configuration hashes, using the logic in
  `phase4_guest.py` `gamemode_settings`. Run `gamemoded -t` and keep the exit code
  and output. Run `gamemoderun` around the working Vulkan test and observe request
  and release. Capture the values again; they must match the earlier capture.
  Record any authorization prompt and do not add polkit rules to make it pass.
  The VM failure (exit 255, missing governor interface) closes only if the test
  passes on a machine with a real cpufreq governor.
- Controllers: retain the model, transport and input events before naming
  compatibility.
- Hybrid (M3): both GPUs in hardware/graphics JSON, `boot_vga`, default and
  `DRI_PRIME=1` renderers, external display on a dGPU-wired port, suspend/resume,
  and observed dGPU runtime power state (observation only, no claim).
- VRR/HDR: only under the display requirements in
  [physical graphics qualification](phase4-physical-qualification.md).

## Phase 5 baselines on physical machines

Run as the ordinary desktop user on an installed, managed system: one passive
`performance record`, then two `performance baseline` runs, then `export`.
Record AC or battery state, power profile, governors, ambient conditions, idle
desktop with no Steam running, and which sensors report critical thresholds.
The product stops within 5 C of a reported critical threshold. A sensor without
one cannot trigger that stop, so the operator's thermal stop rule applies.

| Can establish | Cannot establish |
| --- | --- |
| The suite completes, cancels and persists correctly on that machine | Performance relative to other machines, Windows or VMs |
| Descriptive medians and spreads for that machine, image and configuration | Gaming or GPU performance |
| Which sensors and power readings are available | Sustained thermal behavior (the suite takes about two minutes) |
| A context record for later experiments | Improvement from any tuning; statistical significance from three repetitions |

The current product refuses physical comparisons because `virtual_machine` stays
null. **Decision needed** (D10): add a reviewed, positive bare-metal
classification to the product, or leave comparison blocked and compare exported
reports manually with that limit stated. Do not infer "not a VM" from missing
evidence, and do not relax the check only to get a comparison.

## Evidence without QEMU

Use the Phase 2 layout ([validation infrastructure](phase2-validation.md)) per
machine and case: `docs/evidence/physical/<alias>/<case>/` with `inputs.json`,
`result.json` and `evidence-sha256.json`. Raw material stays private. Git
receives only sanitized material (D11).

- **Before userspace:** photos of firmware screens, refusals and console markers.
  Name each file by case and step, strip EXIF, and record its hash. A photo
  records an observation, not a machine-verified result. Optionally use an HDMI
  capture device.
- **In session:** Spectacle screenshots; command outputs captured as files with
  exit codes; `journalctl -b 0 -o export` and a short-iso-precise text copy;
  `journalctl -b -1` for the previous failed boot. `@log` survives root rollback.
  The live session journal is volatile and must be exported to the evidence stick
  before shutdown.
- **Identities:** ISO, media readback, firmware key backups, UKI/loader, binaries
  and evidence files, all by SHA-256. Firmware vendor/version and setting photos
  belong to the case.
- **Redact or keep private:** hostnames, DMI and disk serials, MAC/IP addresses,
  SSIDs, usernames, `machine-id`, Steam data, and BitLocker/LUKS/login secrets
  (these never enter evidence at all). Confirm disk identity privately; publish
  model and capacity only. `performance export` already omits hostnames, serials,
  usernames and command lines. Journals and `lspci -v` output do not.
- Timeouts, missing markers and unobserved screens are `FAIL` or `NOT RUN`,
  never `PASS`.

## Script reuse

| Script | Status on physical hardware |
| --- | --- |
| `tests/boot/live-smoke.sh` (`live-smoke.service`) | Reusable as is; markers go to the journal |
| `scripts/validate/phase4_gamescope.py` | Reusable as is; desktop user, no VM guard |
| `distroctl` and `astraeus-secure-boot` commands | Reusable as is |
| `scripts/bootstrap.py`, `scripts/validate/arch-builder.sh`, `scripts/check-graphics-packages.py` | Unchanged; image build only |
| `tests/boot/installed-smoke.sh` | Adapt: accept `nvme`/`sata`/`usb` per declared target instead of `virtio` |
| `scripts/validate/phase5.py` | Adapt: physical variant without the VM requirement or 9p marker; same assertions |
| `scripts/validate/phase4_guest.py` | Adapt: reuse `session`, `execute`, `renderer` and `gamemode_settings` through a separate physical entry point. `main` calls the VM guard |
| `scripts/validate/phase42-recovery.py` | Adapt: accept a physical installation record instead of the VM `baseline.json`. Key handling depends on D4 |
| `scripts/validate/phase42_trust.py` | Reusable as a library for public trust checks |
| `phase2-guest.py`, `phase3_guest.py`, `phase4_negatives.py` | Do not adapt; their KVM/virtio guards must keep refusing physical machines |
| `boot-smoke.py`, `install-smoke.py`, `qmp.py`, `visual-boot.py`, `phase2.py`, `phase3.py`, `phase4.py`, `phase42.py`, `phase42-baseline.py`, `phase42-faults.py`, `phase42-recovery-check.py`, `host-builder.py` | QEMU-only. Use their assertions and matrices as the reference for physical checklists |

A future physical runner should run as the desktop user, write only to a declared
evidence directory, refuse when `virtual_machine` is true, and require an
operator-created record naming the disposable machine alias. It must not share
the VM command channel.

## Safety and stop rules

Stop, export evidence and power off on any of the following:

- An unexpected disk is visible, or the target identity does not match.
- A key-enrollment, key-reset or BitLocker prompt that was not planned.
- A Secure Boot violation outside S2 or R2.
- Loss of the firmware display, or loss of the recovery route proven for that
  machine.
- Heat, power or fan instability; battery below 30%; smell or noise.
- An unresolved driver fault or GPU hang.
- Evidence capture would record a secret.

Never run more than one risky change at a time. Before every irreversible step,
prove the step that undoes it on that machine. A stopped round restarts from its
last known-good state with a new evidence directory.

## Phased rollout

| Phase | Scope | Exit criteria |
| --- | --- | --- |
| P0 | Decisions, physical image and its VM gates, script adaptations with host tests | D1-D8 recorded; image identity fixed |
| P1 | M1 live USB, read-only: L1, key backups, dbx inspection | Backups verified; no disk written |
| P2 | M1 install with Secure Boot disabled: L2, I1-I3, T1 | Plain and LUKS2 pass two cold boots |
| P3 | M1 enrollment mode A then B: S1, S2, recovery ladder steps 1-2 | Enforcing boots; refusals observed; revert demonstrated |
| P4 | M1 lifecycle: U1, U2, R1, R2, G1 | Recovery USB rollback under enforcement passes |
| P5 | M1 graphics/gaming and Phase 5 baselines | GameMode full self-test result recorded |
| P6 | M2, then M3, repeating P1-P5 | Intel and hybrid rows recorded |
| P7 | Remaining rows; owner desktop only if D2 allows | Per-row results; no unlisted support claims |

## Owner decisions

- **D1** Authorize disposable-machine testing and amend the "never enroll" rule for those machines only.
- **D2** Owner confirmed live-USB testing only on the 7800X3D/RTX 5070 on 2026-10-15 and reported Secure Boot off and encryption off. No installation or firmware-key change is authorized or needed for this live test.
- **D3** Enrollment mode per round: A, B, or C (C not recommended).
- **D4** Physical test owner key generation, offline custody, and whether `db.key` may leave the installed machine to build recovery media.
- **D5** Dual-boot policy: unsupported (recommended), separate-disk later, or same-disk.
- **D6** Union or per-vendor graphics image.
- **D7** Repository signing key refresh covering the test window.
- **D8** Owner selected Rufus for today's live USB. Use DD Image mode to preserve the candidate's layout and verify the written bytes.
- **D9** Signed-update source: local validation package or a real pinned-snapshot upgrade.
- **D10** Run physical comparison acceptance for the implemented classification and memory tolerance; no additional product change is currently required.
- **D11** Evidence publication: which photos, journals and identities enter Git.
- **D12** Steam account, real games and a licensed D3D11/D3D12 application.
- **D13** Hardware budget and acquisition order.
- **D14** Whether forced power-off (U2) and optional plug-pull tests are allowed.
