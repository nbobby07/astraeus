# Phase 1 validation: 2026-10-07 UTC

This is the historical Phase 1 report. Current integration and acceptance results
are in [Phase 2 integration](phase2-integration.md). During Phase 2, the old remote
ISO copies were retired only after exact comparison and local hash verification;
the validated `afac8d64…` ISO remains at `out/phase1/iso/` in the original checkout
and `D:\Astraeus-Phase2-Evidence\phase1-validated-afac8d64.iso`. Original installed
disks and evidence logs were retained.

This report records completed local/cloud acceptance. Raw artifacts under `out/`
are retained by the maintainer and are excluded from Git; paths below identify
that evidence collection and are not public download links. The
[installed acceptance screenshot](assets/installed-acceptance.png) is included.
Milestone tags preserve the historical tested source. Host CI is a separate check.

**PHASE 1 VALIDATED** for the recorded x86-64 UEFI/QEMU/KVM target. Two independent clean builds produced byte-identical ISOs. Fresh encrypted and plain Calamares installations each completed, cold-booted twice without the ISO, reached SDDM, logged into Plasma Wayland, and passed networking, audio, all four status/hardware commands and zero failed system/user units. Neither final installation needed a manual repair. This is development version 0.1.0-dev; no Phase 2 work was started.

## Source and integration

Baseline: clean `main` at `8dcb2cdf8d9faac97c4ae3367a4d8794a95224ea`. Architecture, building, testing, validation and the complete profile/build pipeline were read before edits. Baseline formatting, two Rust tests and Clippy passed. Baseline Python: Windows 5 passed/3 Linux skips; WSL 7 passed/1 image-tool skip. Both archived databases and 50 upstream package versions verified. Existing Phase 0 reproducibility fixes were retained.

The hardware branch's `f961158de9461a16e09abfe1282ae2ce2b48cae0` was inspected against the active core checkpoint, including all seven requested overlapping paths. The active tree was clean and the hardware branch was based on that core checkpoint. Cherry-pick `08b6113fae5ff38ee04965fa7c9460907e53ac6f` applied without conflicts and preserved installer/core changes. The merged commands were subsequently tested inside the final installed Astraeus guests, as ordinary users.

Tested implementation: clean `8ac0b4a20da5c3276c2de32989593f331f9ff7ed`.

```text
source10.tar.xz
70844 bytes
SHA256 ed56ca7a8f86d06eae1917cf209efefc16bd50a8f18ca7a7562dea8253c5d196
```

Local and remote source hashes matched. The final report-only commit follows acceptance; production files under `crates/`, `distro/` and `scripts/` remain those recorded in the tested inputs manifest.

## ISO and independent builds

```text
astraeus-dev-0.1.0-dev-x86_64.iso
3527583744 bytes
SHA256 afac8d64163b716be0bc175bca7e2ffe20f092d123c0ccf518ae17e97c015d37
```

Builders A10 and B10 each used a fresh 36 GiB overlay, fresh OVMF variables, 6 vCPU and 6 GiB RAM. Both exited 0 with their success markers. Full ISO `cmp` exited 0. Recorded inputs, builder/live/installed package manifests and independently compiled unsigned package hashes matched. A generated the signed custom repository; B independently compiled the packages and consumed the same published signed repository bytes. This proves image reproducibility with fixed signed inputs, not independent timestamped signing operations.

Both use Arch snapshot `2026/10/01`, epoch `1790812800`, ArchISO `91-1`, Rust `1.98.1`, and the same verified cloud base as Phase 0. Both database hashes and 74 direct upstream package versions verified. The final manifests contain 682 live packages and 676 installed packages; installed selection is explicitly maintained separately. Calamares remains live-only.

Final public repository fingerprint: `D86C18757DB44DD67A4BFB97C06FD56A751C4E95`. Packages and the custom database remain signature-required. The key is a disposable development validation identity, not a production release identity. Builder private signing material was not included in source, ISO or installed payload; completed builder disks were removed after evidence export and process shutdown.

The local ISO (retained local evidence) also passed exact size/SHA256 verification. Comparison record (retained local evidence), A build record (retained local evidence), and B build record (retained local evidence) are retained. Input/package manifests sit beside each build log.

## Real installation and boot matrix

| Gate | Encrypted `astraeus-encrypted` | Plain `astraeus-plain` |
| --- | --- | --- |
| Fresh disk / UEFI variables | 32 GiB blank disk / fresh VARS | 32 GiB blank disk / fresh VARS |
| Native Calamares installation | Completed | Completed |
| Filesystem | LUKS2 containing Btrfs | Btrfs |
| First cold boot, ISO detached | Passed | Passed |
| systemd-boot / active UKI | Observed in installed CLI and bootctl | Observed in installed CLI and bootctl |
| SDDM password login / default session | Passed / Plasma Wayland | Passed / Plasma Wayland |
| All four text/JSON commands, non-root | Passed | Passed |
| NetworkManager / DNS / outbound HTTPS | Passed | Passed |
| PipeWire / Pulse / WirePlumber | Active | Active |
| Six Btrfs mounts | Passed | Passed |
| Failed system/user units | 0 / 0 | 0 / 0 |
| Second disk-only cold boot and login | Passed | Passed |
| Second-boot commands / network / audio / failed units | Passed / passed / active / 0 | Passed / passed / active / 0 |

Actual QEMU command records for all four cold boots were checked: KVM acceleration and explicit disk boot priority were present, with no ISO drive or ISO path. The same installed disk and VARS persisted between boots. Acceptance did not bypass Calamares partitioning, extraction or account setup. Mouse/keyboard interaction used private QMP sockets and captured actual native pages. No public VNC or shell was exposed.

Calamares version: `3.4.3-1`, built from upstream release SHA256 `144cbbf6bdcebfb21685950db4f0777218519df095f62f4aa392f28348110d18`. Pages: welcome/language, locale/timezone, keyboard, partition, users, summary, installation, finished. Encryption was initially recommended/selected and explicitly disabled for the plain install. Language/locale was American English; timezone America/Los_Angeles; keyboard English (US).

Execution modules:

```text
astraeus-preflight -> partition -> mount -> unpackfs -> machineid -> locale
-> keyboard -> localecfg -> fstab -> users -> astraeus -> umount
```

Native upstream modules created the partitions, LUKS2, six sibling subvolumes, filesystems, locale, fstab and accounts. Two small distribution jobs check requirements and finalize already-mounted filesystems, repository trust, services and standard boot tooling. They do not partition disks or receive passwords. No custom installer or GRUB was introduced.

The installed account is `validator`, UID/GID 1000, with wheel membership and password-authenticated sudo. Root password login is locked; there is no automatic login. Both retain normal password-protected screen locking. Audits confirm the live account, Calamares binary, live idle-lock configuration and live firstboot mask are absent. Selected US layout is present in both vconsole and the installed user's Plasma configuration.

## Actual storage

Both disks have GPT. ESP starts at sector 4096 and contains 2097152 sectors, exactly 1073741824 bytes, FAT32, mounted at `/efi`. System partition starts at sector 2101248 and contains 65007544 sectors, 33283862528 bytes. Sectors are 512 bytes. The encrypted mapping contains 33267085312 bytes after its LUKS2 header.

| Identifier | Encrypted | Plain |
| --- | --- | --- |
| ESP filesystem UUID | `1160-9EE2` | `2E95-28AE` |
| LUKS2 UUID | `0e5796df-94e1-48d6-8b22-ea33984073a1` | None |
| Btrfs UUID | `749738e8-aa7a-4598-9bb4-33d57bbb605a` | `333d0b41-df5b-44b4-a61d-218319dbf128` |
| Root source at boot | `/dev/mapper/root` | `/dev/vda2` |

Both have sibling subvolume IDs 256 through 261, all with top-level ID 5:

| Subvolume | Mount |
| --- | --- |
| `@` | `/` |
| `@home` | `/home` |
| `@snapshots` | `/.snapshots` |
| `@log` | `/var/log` |
| `@cache` | `/var/cache` |
| `@containers` | `/var/lib/containers` |

Fstab selects `defaults,noatime,compress=zstd:1` and each named subvolume. ESP uses `defaults,umask=0077`. Actual plain Btrfs mounts additionally show the kernel's `discard=async` default; the encrypted mapper does not enable discard. `/tmp` is tmpfs; no swap or hibernation path is configured. [Storage design](storage.md) records each subvolume's purpose and future rollback boundary; rollback itself is not implemented.

Actual encrypted fstab:

```fstab
# /etc/fstab: static file system information.
#
# Use 'blkid' to print the universally unique identifier for a device; this may
# be used with UUID= as a more robust way to name devices that works even if
# disks are added and removed. See fstab(5).
#
# <file system>             <mount point>  <type>  <options>  <dump>  <pass>
UUID=1160-9EE2                            /efi           vfat    defaults,umask=0077 0 2
/dev/mapper/root	/	btrfs	subvol=/@,defaults,noatime,compress=zstd:1	0	0
/dev/mapper/root	/home	btrfs	subvol=/@home,defaults,noatime,compress=zstd:1	0	0
/dev/mapper/root	/.snapshots	btrfs	subvol=/@snapshots,defaults,noatime,compress=zstd:1	0	0
/dev/mapper/root	/var/log	btrfs	subvol=/@log,defaults,noatime,compress=zstd:1	0	0
/dev/mapper/root	/var/cache	btrfs	subvol=/@cache,defaults,noatime,compress=zstd:1	0	0
/dev/mapper/root	/var/lib/containers	btrfs	subvol=/@containers,defaults,noatime,compress=zstd:1	0	0
```

Actual plain fstab:

```fstab
# /etc/fstab: static file system information.
#
# Use 'blkid' to print the universally unique identifier for a device; this may
# be used with UUID= as a more robust way to name devices that works even if
# disks are added and removed. See fstab(5).
#
# <file system>             <mount point>  <type>  <options>  <dump>  <pass>
UUID=2E95-28AE                            /efi           vfat    defaults,umask=0077 0 2
UUID=333d0b41-df5b-44b4-a61d-218319dbf128 /              btrfs   subvol=/@,defaults,noatime,compress=zstd:1 0 0
UUID=333d0b41-df5b-44b4-a61d-218319dbf128 /home          btrfs   subvol=/@home,defaults,noatime,compress=zstd:1 0 0
UUID=333d0b41-df5b-44b4-a61d-218319dbf128 /.snapshots    btrfs   subvol=/@snapshots,defaults,noatime,compress=zstd:1 0 0
UUID=333d0b41-df5b-44b4-a61d-218319dbf128 /var/log       btrfs   subvol=/@log,defaults,noatime,compress=zstd:1 0 0
UUID=333d0b41-df5b-44b4-a61d-218319dbf128 /var/cache     btrfs   subvol=/@cache,defaults,noatime,compress=zstd:1 0 0
UUID=333d0b41-df5b-44b4-a61d-218319dbf128 /var/lib/containers btrfs   subvol=/@containers,defaults,noatime,compress=zstd:1 0 0
```

The encrypted crypttab data entry is:

```text
root UUID=0e5796df-94e1-48d6-8b22-ea33984073a1 none luks
```

Plain crypttab contains only the package's explanatory comments. Full partition dumps, subvolume lists, both crypttabs and filesystem/mount evidence are retained in the encrypted audit (retained local evidence) and plain audit (retained local evidence).

Actual cryptsetup `2.8.8-1` parameters were inspected, not assumed: LUKS2, Argon2id keyslot 0, time cost 20, memory 397880 KiB, 4 threads, 64-byte/512-bit key, AES-XTS-plain64, 4096-byte sectors, data offset 16777216 bytes. Calibration defaults were retained; no faster test KDF, cipher/key-size override, keyfile or TPM policy was used. Wrong passphrase kept boot blocked and requested another credential; the correct passphrase booted successfully. Full JSON header metadata is retained in the encrypted audit without password/key material.

## Boot, desktop and services

Both installed systems run kernel `7.2.7-arch1-1`, systemd-boot and systemd-stub `262-1-arch`, mkinitcpio `42.1-1` and systemd-ukify `262-1`. One Type #2 UKI is stored at `/efi/EFI/Linux/astraeus-dev-linux.efi`; systemd-boot discovers it as the default and also exposes Firmware Settings. Loader timeout is 3 seconds and editor access is disabled.

Actual initramfs configuration:

```sh
MODULES=(btrfs virtio_pci virtio_blk nvme ahci xhci_pci usbhid hid_generic)
BINARIES=()
FILES=()
HOOKS=(base systemd autodetect microcode modconf keyboard sd-vconsole block sd-encrypt filesystems fsck)
COMPRESSION="zstd"
```

The preset reads `/boot/vmlinuz-linux` and `/etc/kernel/cmdline`; UKI inspection shows `.linux`, `.initrd`, `.uname`, `.osrel`, `.cmdline` and `.sbat`. Native mkinitcpio replaces the embedded os-release VERSION_ID with the kernel version, while preserving Astraeus identity; the running system's release version remains 0.1.0-dev. See [upstream mkinitcpio v42.1](https://github.com/archlinux/mkinitcpio/blob/v42.1/mkinitcpio#L538).

Original encrypted command line:

```text
rd.luks.name=0e5796df-94e1-48d6-8b22-ea33984073a1=root root=/dev/mapper/root rootflags=subvol=@ rw
```

Plain command line:

```text
root=UUID=333d0b41-df5b-44b4-a61d-218319dbf128 rootflags=subvol=@ rw
```

A real relevant-input test appended `loglevel=6` to the encrypted system's command line and ran `mkinitcpio -P`. Rebuild exited 0, UKI inspection contained the change, and its hash changed:

```text
before 5d1a678ece283c70ef307ec905d1903fa04cc53edbeb4a9ae39ea0e5080fed66
after  e36b0cf769cd0281cca530b63a045336f8b47f7edb8f6345b6a9c03e9cb017f7
```

The second cold boot passed with `loglevel=6` in `/proc/cmdline`, normal LUKS2 unlock, all six mounts and the full health check. No mitigation was disabled. Regeneration evidence (retained local evidence) records command output and inspection. Existing Arch hooks plus the selected microcode/ukify/cryptsetup/Btrfs/systemd hooks preserve the standard regeneration path.

SDDM `0.21.0-7` presented password login and Plasma Wayland by default on all four cold boots. Plasma workspace is `6.7.5-1`. Konsole `26.08.1-1` rendered and accepted the actual acceptance commands in both installed systems. Ghostty `1.3.1-2` rendered and accepted commands in the installed encrypted Wayland session; both installations contain it. QEMU software rendering emitted non-fatal Mesa/GTK warnings; no physical GPU acceleration claim is made.

NetworkManager `1.58.1-1` was active after both boots on both disks; nmcli, DNS lookup and real HTTPS access to the Arch archive passed. PipeWire and PipeWire Pulse `1:1.6.9-1`, and WirePlumber `0.5.18-1`, were active under both normal user sessions after both boots. Both system and user failed-unit files were empty. Complete versions, account, keyboard, timezone, loader and UKI data are in the audits.

## Installed hardware and CLI output

The reusable Rust probe observed x86_64, `AuthenticAMD`, CPU model `19/01`, 4 logical and 4 physical guest cores, approximately 3.8 GiB total memory plus available memory, Virtio GPU `0x1af4:0x1050` with PCI driver/DRM nodes/boot-VGA flag, a 32 GiB virtio disk, partition capacities and `vda` parents, UEFI and positive QEMU virtualization evidence. Model/transport/parent fields that are unavailable remain null. Container type is null. No tuning or recommendations are performed.

The kernel also exposes a QEMU DVD-ROM `sr0` with a reported approximately 1 GiB capacity. Optical-media presence is not separately probed. This is a kernel device observation, not ISO-attachment evidence; the actual cold-boot QEMU command records prove the ISO was absent.

Each accepted installed user session executed, without sudo:

```sh
distroctl status
distroctl status --json
distroctl hardware
distroctl hardware --json
```

Encrypted first-boot `distroctl status`:

```text
Project Astraeus

System
  Version       0.1.0-dev
  Channel       development
  Architecture  x86_64
  Hostname      astraeus-encrypted

Kernel
  Version       7.2.7-arch1-1

Boot
  Firmware      UEFI
  Bootloader    systemd-boot 262-1-arch
  Stub          systemd-stub 262-1-arch
  UKI path      \EFI\Linux\astraeus-dev-linux.efi

Filesystem
  Root          btrfs
  Encryption    LUKS2

Desktop
  Name          KDE
  Session       wayland

Hardware
  CPU           19/01
  Logical CPUs  4
  GPU           Virtio Virtio 1.0 GPU
  Memory        3.8 GiB
  Storage       /dev/sr0 (1024.0 MiB), /dev/vda (32.0 GiB)
```

Plain first-boot `distroctl status`:

```text
Project Astraeus

System
  Version       0.1.0-dev
  Channel       development
  Architecture  x86_64
  Hostname      astraeus-plain

Kernel
  Version       7.2.7-arch1-1

Boot
  Firmware      UEFI
  Bootloader    systemd-boot 262-1-arch
  Stub          systemd-stub 262-1-arch
  UKI path      \EFI\Linux\astraeus-dev-linux.efi

Filesystem
  Root          btrfs
  Encryption    none

Desktop
  Name          KDE
  Session       wayland

Hardware
  CPU           19/01
  Logical CPUs  4
  GPU           Virtio Virtio 1.0 GPU
  Memory        3.8 GiB
  Storage       /dev/sr0 (1024.0 MiB), /dev/vda (32.0 GiB)
```

Complete encrypted first-boot `distroctl status --json`, including the normalized hardware model:

```json
{
  "schema_version": 1,
  "name": "Project Astraeus",
  "version": "0.1.0-dev",
  "channel": "development",
  "hostname": "astraeus-encrypted",
  "kernel": "7.2.7-arch1-1",
  "boot": {
    "firmware": "UEFI",
    "bootloader": "systemd-boot 262-1-arch",
    "stub": "systemd-stub 262-1-arch",
    "uki_path": "\\EFI\\Linux\\astraeus-dev-linux.efi"
  },
  "filesystem": {
    "root_type": "btrfs",
    "source": "/dev/mapper/root",
    "options": "rw,noatime,rw,compress=zstd:1,space_cache=v2,subvolid=256,subvol=/@",
    "encryption": "LUKS2"
  },
  "desktop": {
    "name": "KDE",
    "session_type": "wayland"
  },
  "hardware": {
    "schema_version": 1,
    "cpu": {
      "architecture": "x86_64",
      "vendor": "AuthenticAMD",
      "model": "19/01",
      "logical_count": 4,
      "physical_core_count": 4
    },
    "memory_bytes": 4089905152,
    "memory_available_bytes": 2817626112,
    "gpus": [
      {
        "pci_address": "0000:00:02.0",
        "vendor": "Virtio",
        "vendor_id": "0x1af4",
        "device_id": "0x1050",
        "model": "Virtio 1.0 GPU",
        "driver": "virtio-pci",
        "drm_nodes": [
          "/dev/dri/card1",
          "/dev/dri/renderD128"
        ],
        "boot_vga": true
      }
    ],
    "storage": [
      {
        "name": "dm-0",
        "path": "/dev/dm-0",
        "model": null,
        "transport": null,
        "size_bytes": 33267085312,
        "rotational": true,
        "kind": "mapped",
        "parent": null
      },
      {
        "name": "sr0",
        "path": "/dev/sr0",
        "model": "QEMU DVD-ROM",
        "transport": "sata",
        "size_bytes": 1073741312,
        "rotational": false,
        "kind": "disk",
        "parent": null
      },
      {
        "name": "vda",
        "path": "/dev/vda",
        "model": null,
        "transport": "virtio",
        "size_bytes": 34359738368,
        "rotational": true,
        "kind": "disk",
        "parent": null
      },
      {
        "name": "vda1",
        "path": "/dev/vda1",
        "model": null,
        "transport": "virtio",
        "size_bytes": 1073741824,
        "rotational": true,
        "kind": "partition",
        "parent": "vda"
      },
      {
        "name": "vda2",
        "path": "/dev/vda2",
        "model": null,
        "transport": "virtio",
        "size_bytes": 33283862528,
        "rotational": true,
        "kind": "partition",
        "parent": "vda"
      }
    ],
    "capabilities": {
      "uefi": true,
      "virtual_machine": true,
      "virtualization_type": "qemu",
      "container_type": null
    },
    "issues": []
  }
}
```

Complete plain status JSON (retained local evidence), encrypted hardware text (retained local evidence) / hardware JSON (retained local evidence), and plain hardware text (retained local evidence) / hardware JSON (retained local evidence) are retained verbatim. Both second-boot output sets are preserved alongside their health logs. These are actual installed Astraeus observations, not WSL fixture output.

## Tests and failure paths

- Linux: `cargo test --workspace --locked`, 15 tests passed; `cargo fmt --check` passed; `cargo clippy --workspace --all-targets --locked -- -D warnings` passed.
- Windows: 13 Rust tests passed, formatting and Clippy passed. Two Unix-specific sysfs-symlink tests are Linux-only.
- `python3 -m unittest discover -s tests -v`: all 15 Linux tests passed, including native SquashFS/xorriso byte comparison. Windows passed 11 with 4 Unix/Linux skips.
- All nine CI Bash syntax checks passed; the changed Calamares recipe was checked again after the libparted correction.
- Archive verification passed for both original database hashes and all 74 selected upstream package versions.
- Two independent final Arch builds, full ISO byte comparison and matching input/package manifests passed.
- Two real final Calamares installs and four installed disk-only KVM boots passed the full normal-user acceptance script.
- Final 8 GiB guest was blocked at welcome with “At least 20 GiB is required”; Next was disabled, and sfdisk/lsblk confirmed the disk remained blank.
- Wrong LUKS2 credential was rejected during the final encrypted boot; correct unlock passed on both boots.
- Real Calamares cancellation before mutation on Source9 returned to desktop and left the disk blank. The cancellation path itself was unchanged by Source10's build-dependency fix.
- Malformed installer configuration, weak/incorrect policy choices, mount/UUID inputs and encrypted/plain boot inputs have unit regression coverage. Builder interruption cannot produce accepted success evidence.

## Real bugs found and fixed

| Cause | Fix | Regression / actual verification |
| --- | --- | --- |
| Encryption probe expected a partition `slaves` directory | Shared sysfs partition-parent resolver | Fixture and real-symlink tests; final encrypted/plain status |
| QMP text input lacked JSON and subvolume punctuation | Complete needed key map and prevalidate before sending | Input/invalid-input tests; actual private GUI/console interaction |
| CLI PTY input could echo credentials or arrive before echo was disabled | Non-echo stdin plus readiness marker before transmitting | stdin tests/documented workflow; final installer evidence checked against disposable credentials |
| Ambient SOURCE_DATE_EPOCH conflicted with explicit installed SquashFS times | Clear ambient variable for explicit-time compressor | Native byte regression with ambient epoch and changed file time; final ISO pair |
| Initial archive transfer had unbounded/default network behavior | Reuse bounded curl retries/connect/transfer timeouts | Successful clean builders and locked archive verification |
| Calamares branding omitted required slideshow/style fields | Supply native required fields | Generated-profile regression; actual final startup |
| Loop setup via live overlay copied the large install image into its small writable layer | Read payload through ArchISO's read-only lower SquashFS mount | Source-path regression; both final installs |
| fstab retained Calamares's temporary encrypted mapper after crypttab/UKI used `root` | Rewrite all six mount sources consistently | Six-mount/idempotence/plain/ESP/comment regression; final encrypted two boots |
| OVMF default disk selection fell through to PXE | Explicit ISO/disk device boot priorities | Launcher regression and four ISO-free final boots |
| Passwordless live idle lock hit a QML error after PAM accepted the blank account | Disable idle/resume lock only in live configuration | Payload-boundary tests; final install stayed accessible unattended; installed audit excludes live setting |
| libparted missing during compilation silently removed Calamares's storage check | Add parted build/runtime dependency and mandatory CMake find-package lookup | Policy/dependency regression, both native builds found libparted, final 8 GiB refusal before writes |

Earlier failed/canceled attempts were retained as diagnostic evidence and never counted as accepted installs or builds. Historical Source6, Source8 and Source9 ISO pairs reproduced before later installer defects were corrected. Diagnostic disk repairs were used only to isolate causes; final Source10 installations received no manual target repairs.

## Evidence, cleanup and limits

Build evidence: `out/phase1/A10-evidence/`, `B10-evidence/`, source10 archive/metadata and reproducibility10.json. Installed evidence: `out/phase1/encrypted10-health/{boot1,boot2}/`, `plain10-health/{boot1,boot2}/`, redacted installer logs, and `final10-guests/` containing screens, serial and launch commands. Guest evidence archive (retained local evidence) preserves the native interaction and boot records. Generated artifacts are ignored by Git; accepted findings and representative output are recorded here.

All nested QEMU guests were stopped and this was explicitly checked before cleanup. The existing Freestyle validator `vm-cc9d56de23154de7a22492f24dfaae27` was paused with the official CLI; returned state was `paused`. No new outer VM, paid resize or public console was created. Unrelated `atm10` was untouched. Original Phase 0 artifacts remain retained. Superseded Phase 1 media and completed builder overlays were retired after hash/evidence preservation to stay within the existing 64 GiB disk.

Qualification covers this UEFI/KVM virtual target and erase-disk workflow. Physical hardware, proprietary/hybrid GPUs, physical audio output, mixed firmware, manual/alongside/dual-boot layouts, low-RAM refusal and power loss during partition mutation remain unqualified. QEMU graphics use software rendering; the SDDM greeter's layout indicator is unpolished, while actual console and user keyboard configurations were verified as US. No enforced Secure Boot, production release signing, TPM unlock, swap/hibernation, recovery generations, transactional update or rollback manager was implemented. No Phase 2 work was started.

# Phase 0 validation: 2026-10-06 to 2026-10-07 UTC

**PHASE 0 VALIDATED** for the recorded x86-64 QEMU/KVM environment. Two independent
clean Arch builds produced byte-identical ISOs. The final image passed UEFI boot,
visual Plasma Wayland, terminal, network, repository and service checks. No Phase 1
implementation was added. This is Phase 0 validation media, not v0.1 or production
release signing.

## Accepted results

| Gate | Result |
| --- | --- |
| Working-tree transfer | VERIFIED: source archive hashes match locally and remotely |
| Independent Arch builders | VERIFIED: separate clean overlays and identical inputs |
| ISO A and B | VERIFIED: exit 0, complete artifacts and success markers |
| Full ISO reproducibility | **MATCH**: equal SHA256 values and `cmp` exit 0 |
| Package manifests and recorded inputs | VERIFIED: comparisons exit 0; 673 image packages |
| UEFI and nested KVM | VERIFIED: actual cold boots and QMP KVM confirmation |
| Plasma Wayland, panel and input | VERIFIED: screenshots, mouse menu and keyboard interaction |
| Ghostty and Konsole | VERIFIED: both render and accept commands on the final ISO |
| NetworkManager, DNS and repository access | VERIFIED: full connectivity, DNS resolution and HTTPS repository refresh |
| PipeWire, Pulse and WirePlumber | VERIFIED: all three user services active |
| Final idle-boot systemd state | VERIFIED: running; zero failed system or user units |
| distroctl | VERIFIED: valid metadata; unsupported status correctly exits 1 |
| Signing | VERIFIED: genuine signatures accepted; tampered package and wrong signer rejected |
| Cleanup | VERIFIED: nested guests stopped; outer VM paused; account shows two paused VMs |

## Source tested

The local `main` branch had no commits or remote. All intended uncommitted Phase 0
files were transferred under `operating-system/`, excluding `.git`, generated
outputs and credentials. The final archive contains 56 files and is 36476 bytes:

```text
source-round6.tar.xz
69370282b68fc866903c6493f0fce232da1fecf6dd1c9028566b144aaeb473fd
```

The per-file manifest is `out/freestyle/source-round6-manifest.json`. All production
files under `crates/`, `distro/` and `scripts/` remained byte-identical afterward.
Only documentation, CI tool installation and a stronger timestamp variation in the
regression test changed after that archive. The strengthened test also passed on
real image tools. The archive identifies exactly what was built; the initial
validation commit follows successful tests, documentation and cleanup.

## Freestyle and clean Arch environments

- VM: `astraeus-phase0-validator`, private infrastructure identifier omitted.
- Image: `freestyle/ubuntu-lg`, Ubuntu 24.04; snapshot `sh-ffe8873ae9ac4b91b60ef539c3aa59c0`.
- Outer resources: 8 vCPU, 16 GiB RAM, 64 GB disk.
- Outer kernel: `6.1.102 #1 SMP PREEMPT_DYNAMIC Wed Aug 26 20:12:24 UTC 2026`.
- `/dev/kvm` exists; KVM API 12 and CREATE_VM succeed.
- QEMU: `8.2.2 (Debian 1:8.2.2+ds-0ubuntu1.18)`.
- No plan/billing change, public repository, public console, TLS route, VPC or
  Freestyle snapshot was created. The existing `atm10` VM was left untouched.

Each final builder used 6 vCPU, 6 GiB RAM and a new sparse 36 GiB overlay from the
same official `Arch-Linux-x86_64-cloudimg-20261001.604814.qcow2` (578080256 bytes).
Base SHA256: `360f0fa49db6813bdc8e35bed230a2dc2ae3567b7b5ab74719c0a706e4e34e87`.
Its detached signature verified against the Arch-boxes published primary key
`1B9A16984A4E8CB448712D2AE0B78BF4326C6F8F`, signing subkey
`656E4C5AC1CC3B86E539D97E343635A6859A9174`.

Builder kernel: `7.2.7-arch1-1`, x86_64. The whole builder package set and image use
`https://archive.archlinux.org/repos/2026/10/01/`; both database hashes are verified
against the project lock. ArchISO is 91-1 and Rust is 1.98.1. Full package versions
are retained in the builder and image manifests.

A 1.5 GiB cache of upstream archives/signatures was recovered read-only from a
stopped builder. Each fresh guest copied it separately and performed normal pacman
verification. Custom packages were excluded. No installed root, build tree or
pacman database was shared. Both guests independently rebuilt the unsigned platform
packages and produced matching hashes.

A generated a disposable one-day signing key; B consumed the same signed repository
bytes for ISO assembly. This proves ISO reproducibility with fixed signed inputs,
not reproducibility of independently timestamped signing operations. Final public
fingerprint: `C4E69984BAEE86F6FADB778098B410CA897EA890`.

## Exact commands and artifacts

Outer launch for A:

```sh
sudo python3 /home/ubuntu/phase0-round6/operating-system/scripts/validate/host-builder.py A \
  --base /home/ubuntu/phase0-vms/arch-base.qcow2 \
  --share /home/ubuntu/phase0-round6 \
  --output /home/ubuntu/phase0-vms/builder-A6 \
  --memory-mib 6144 \
  --ovmf-code /usr/share/OVMF/OVMF_CODE_4M.fd \
  --ovmf-vars /usr/share/OVMF/OVMF_VARS_4M.fd
```

B uses label `B` and output `builder-B5`, with the same remaining arguments. Each
starts from a new overlay. Cloud-init runs
`PHASE0_DISPOSABLE=1 bash /run/phase0-builder.sh A` (or `B`), using the existing
vendored makepkg, signing and repository workflow. Both then run:

```sh
python3 scripts/bootstrap.py iso --repo /build/operating-system/out/repo --fingerprint C4E69984BAEE86F6FADB778098B410CA897EA890 --output /build/iso-build
```

Both filenames are `astraeus-dev-0.0.1-x86_64.iso`.

| Build | Start UTC | End UTC | Size | SHA256 |
| --- | --- | --- | ---: | --- |
| A | 2026-10-07 02:02:36 | 2026-10-07 02:14:36 | 1949771776 bytes | `ec0c6ef0c3f0bd92171b302ce02f093355af4feb624fb75f3cded2f03ab9bd69` |
| B | 2026-10-07 02:11:08 | 2026-10-07 02:24:27 | 1949771776 bytes | `ec0c6ef0c3f0bd92171b302ce02f093355af4feb624fb75f3cded2f03ab9bd69` |

Both exited zero and emitted their success markers. Finished ISOs were not rewritten
or modified. The host ran:

```sh
cd /home/ubuntu/phase0-round6/evidence
sha256sum A/*.iso B/*.iso
cmp A/astraeus-dev-0.0.1-x86_64.iso B/astraeus-dev-0.0.1-x86_64.iso
cmp A/image-packages.txt B/image-packages.txt
cmp A/inputs.json B/inputs.json
cmp A/platform-package-sha256.txt B/platform-package-sha256.txt
```

All four comparisons returned 0. `comparison.log` records the results.

## Boot, desktop and system

The existing `scripts/boot-smoke.py` ran in the foreground of a transient outer-host
systemd service. The actual guest emitted its full acceptance marker at 60.5 seconds
and the harness returned zero. The later QEMU SIGTERM is normal cleanup after success.

Configuration: q35, required KVM, host CPU, 4 vCPU, 4096 MiB RAM, virtio-vga,
virtio user-mode networking, optical ISO boot and serial logging. No virtual hard
disk or host-directory share is attached to the live desktop. The visual helper
adds a private Unix QMP socket and USB tablet. Exact argument arrays are retained
beside the logs. QMP reports KVM `enabled: true, present: true`.

CODE is read-only and VARS is copied per guest:

- `/usr/share/OVMF/OVMF_CODE_4M.fd`, SHA256 `ad23261d43116abc3747d59a7837fbf578c9586a8993f4eeba064cd07eccb083`.
- `/usr/share/OVMF/OVMF_VARS_4M.fd`, SHA256 `5d2ac383371b408398accee7ec27c8c09ea5b74a0de0ceea6513388b15be5d1e`.

This is ordinary UEFI, not enforcing Secure Boot. Host firmware was not modified.

The final idle-host visual boot reached the acceptance marker at 61.1 seconds.
Plasma 6.7.5 rendered wallpaper and panel; mouse clicks opened the menu, and keyboard
input launched applications and executed commands. Konsole 26.08.1 and Ghostty 1.3.1
both rendered working shells. `XDG_SESSION_TYPE` returned `wayland`.

```text
systemctl is-system-running: running
systemctl --failed: 0 loaded units listed
systemctl --user --failed: 0 loaded units listed
pipewire, pipewire-pulse, wireplumber: active, active, active
nmcli general status: connected, full
getent hosts archive.archlinux.org: resolved
sudo pacman -Sy --noconfirm: exit 0; distro/core/extra refreshed
```

The live config requires custom database and package signatures and uses the local
repository and pinned HTTPS archive. Its GPG directory initializes successfully.
The build-only curl override is absent from the live config. Real publisher tests
accepted the genuine database signature and rejected a corrupted package (`BAD
signature`, exit 1) and a valid package with an unrelated requested signer (exit 1).
Negative tests used copies and new output directories.

One final-image boot during B's compression had a **FAILED cosmetic
`plasma-ksplash.service`**, exceeding its 40-second startup timeout. The desktop and
major services worked. A fresh boot with builders stopped had zero failed system
or user units. Both logs are retained. No failed-state reset, masking or runtime
repair was used to obtain the clean result. Startup during heavy software-rendering
contention remains a limitation; no performance claim is made.

## distroctl

`distroctl status` returns exit 1, as required by the current Phase 0 contract. It
does not crash or invent system status. Complete output:

```text
distroctl: unsupported arguments

distroctl: Phase 0 build metadata tools

Usage:
  distroctl info [--json]       Show metadata compiled into this binary
  distroctl validate <path>    Validate a project release TOML file
  distroctl --version
  distroctl --help

These commands are read-only. System status, updates and installation are not implemented.
```

`distroctl info --json` succeeds: schema 1, ID `astraeus-dev`, name `Project Astraeus`,
version `0.0.1`, x86_64, archive `2026/10/01`, epoch 1790812800, ArchISO 91-1 and
Rust 1.98.1. Full JSON is retained in the serial logs.

## Bugs, fixes and regression evidence

| Cause | Fix | Verification |
| --- | --- | --- |
| Minimal Arch image had no Git when first called | Install dependencies before Git inspection | Subsequent clean builders pass |
| QEMU allowed implicit KVM-to-TCG fallback | Require KVM; TCG must be explicit | Command regression and QMP confirmation |
| Unset timezone caused systemd-firstboot prompt | Live-only UTC symlink, US keymap and firstboot mask | Linux profile regression and real cold boots |
| GPGDir absent; pacman-key used the wrong location | Create it before initialization; remove fragile pubring condition | Profile regression, cold boot and repository refresh |
| Interrupted builder could record exit 0 | Explicit HUP/INT/TERM traps and complete-artifact acceptance | Real TERM regression checks exit 143 |
| Archive stalls exceeded pacman's low-speed timeout | Build-only bounded curl retries/timeouts | Trust/scope regression and successful builds |
| Linker auxiliary cache varied across builds | Exclude only `var/cache/ldconfig/aux-cache` during SquashFS creation | Native image regression and full ISO match |
| ISO directory timestamps used build wall time | Set all xorriso file dates from SOURCE_DATE_EPOCH during creation | Native timestamp regression and full ISO match |

The earlier completed pair differed at byte 32947 despite matching inputs:
A `b707659786d393e7f7c5ff9532c5eb47ab534759d72dc0bd3baa9c3d48599e27`,
B `0693ee22d992e8abdb8f08f8ebf9209157892f59c2a29b28f649e2a9cda745d0`.
Read-only comparison found identical kernel/initramfs/EFI files. Only SquashFS and
its checksum differed; the only differing live file was the auxiliary cache.
Metadata/xattr comparison covered 186933 paths with zero differences. ISO root
mtimes were 1791336125 and 1791336667. The two corrections were followed by the new
clean pair above, not by post-processing the failed images.

Failed operational attempts remain in the evidence: initial Git-order failure,
firstboot prompt, missing keyring directory, canceled B, two archive stalls,
terminal-reconnection SIGHUP, and a queued B launcher whose exiting service stopped
its child VM before building. B was restarted directly on a new disk. Use a
foreground smoke harness under systemd; do not wrap a daemonizing builder launcher
in a service that immediately exits. Bounded source transfers and `cat -v` serial
inspection avoid the earlier paste/control-code problems. No failed attempt counts
as an accepted artifact.

## Tests and retained evidence

- Rust formatting, workspace tests and Clippy with warnings denied: passed locally.
- Pinned Arch makepkg compilation and Rust checks: passed in clean builders.
- Python: 8/8 passed on Linux with real image tools; WSL 7 passed/1 native-tool skip;
  Windows 5 passed/3 Linux skips. Bash syntax passed.
- CI now installs the image regression tools. Remote CI execution is UNVERIFIED;
  no remote repository or workflow run was created.
- The native regression varies cache bytes and ISO input timestamps and compares
  complete small ISO bytes. It supplements the full independent A/B comparison.

Complete exported evidence:

```text
out/freestyle/final-evidence.tar.xz
312056 bytes
eb8743eb8448d98234cb7db1da23d075fa9b4741000f583afe612de9b675a304
```

Checksums matched before and after download. Its 294 members include full build
logs, manifests, signing tests, comparisons, QEMU commands, serial logs, native
tests and cleanup evidence. No VM disks, ISO payloads or private signing keys are
included. It is extracted at `out/freestyle/final-evidence/`. Source archives and
per-file manifests are also retained locally; generated outputs are ignored by Git.

Final screenshots under `out/freestyle/`: `accepted-desktop.png`,
`accepted-health.png`, `accepted-terminals.png`, `freestyle-paused.jpg`, and
`freestyle-vm-inventory.jpg`. Earlier failure evidence remains available there.

## Cleanup and usage

All nested QEMU guests and transient validation services stopped. Disposable
builder disks, their test private keys and superseded ISOs were removed. The outer
VM was paused around **2026-10-07 02:42 UTC**. The account list showed two paused
VMs, including untouched `atm10`, and no running VM.

Retained temporarily on the paused validator: the accepted ISO pair in
`/home/ubuntu/phase0-round6/evidence/A/` and `B/`, verified clean Arch base, upstream
package cache, source and logs. No Freestyle snapshot was added. The VM auto-deletes
after one day without running, shown as October 7, 7:42 PM PDT (October 8, 02:42 UTC).
Resume only if those cloud artifacts are needed.

Approximate runtime: 3 hours 18 minutes, about 26.4 vCPU-hours and 52.8 GiB-memory-hours.
Published rates imply about **$1.77 gross compute/storage before allowances or
credits**. This is not an invoice; transfer charges were not separately metered.
Paused compute holds no CPU/RAM reservation. Retained 64 GiB storage is about
$0.13/day before allowances, bounded here by the one-day deletion policy.
See [Freestyle pricing](https://www.freestyle.sh/docs/vms/pricing-and-limits).

## Remaining limits

UNVERIFIED: physical GPU/hardware compatibility, Wi-Fi hardware, sound-device
playback, enforcing Secure Boot and remote CI. Audio was checked at service level;
the QEMU guests had no sound device. The disposable signing identity expires after
one day, so these are validation artifacts rather than production release media.

The cosmetic splash timeout during concurrent compression is recorded above.
Installation, installed Btrfs layout, updates, rollback, performance policies and
other later-phase features remain unimplemented. Phase 1 was not started.
