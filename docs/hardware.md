# Read-only hardware and status

`distro-hardware` provides `discover(root) -> RawHardware`,
`normalize(raw) -> Hardware`, and `probe()` for the running Linux system.
Raw observations, normalized data and derived capabilities are separate. The
library uses Rust's filesystem APIs and serde, with no command execution, device
opens, system writes, tuning, root requirement or privileged helper.

`distroctl` consumes this model in both commands:

```sh
distroctl status
distroctl status --json
distroctl hardware
distroctl hardware --json
```

Status summarizes the system and whole disks; hardware includes partitions,
mapped devices, core counts, available memory, DRM nodes and probe issues.
Human output uses IEC memory/storage units. JSON retains exact integer bytes.
Partial discovery succeeds with exit 0. Invalid arguments, metadata validation
failures and JSON serialization failures exit 1. Unknown data is not a failure.

## Sources and interpretation

| Information | Source | Interpretation |
| --- | --- | --- |
| CPU architecture | Rust target architecture | No x86-only API; not a parser for another architecture's captured host |
| CPU vendor/model/logical CPUs | `/proc/cpuinfo` | Vendor ID, model name, ARM Hardware or cpu model; numbered processor records |
| Physical CPU cores | `/proc/cpuinfo` | Distinct `(physical id, core id)` pairs, only with complete topology |
| Total/available RAM | `/proc/meminfo` | `MemTotal` and `MemAvailable`, checked kB to byte conversion |
| PCI GPUs | `/sys/bus/pci/devices` | Display class `0x03`; AMD, Intel, NVIDIA, Virtio, QEMU, VMware, Microsoft, Red Hat vendor IDs |
| GPU model | `/usr/share/hwdata/pci.ids`, then `/usr/share/misc/pci.ids` | Exact vendor/device lookup if the optional local database exists |
| GPU driver and nodes | PCI driver links and `/sys/class/drm` | `cardN` and `renderDN` associated through canonical device paths; connectors excluded |
| Boot GPU | PCI `boot_vga` | Firmware boot VGA indication; never equated with compositor/render priority |
| Block devices | `/sys/class/block`, fallback `/sys/block` | Model, size, rotational flag, partition marker and actual containing disk |
| Transport | Canonical sysfs topology and kernel device names | USB first, then NVMe, virtio, SATA; unresolved transports stay null |
| Firmware | `/sys/firmware/efi` | UEFI present; BIOS when firmware is accessible without EFI and no container is marked; unknown otherwise |
| Virtualization | `/sys/hypervisor/type`, device-tree hypervisor compatible, DMI, CPU hypervisor flag | Positive evidence only; unknown is not physical hardware |
| Container | `/run/systemd/container` | Explicit systemd marker; absence does not prove a non-container host |
| Release | `/etc/os-release`, fallback `/usr/lib/os-release` | Running OS NAME, VERSION_ID, VARIANT_ID; never substituted with bundled build metadata |
| Kernel/hostname | `/proc/sys/kernel/osrelease`, `/proc/sys/kernel/hostname` | Running kernel and hostname |
| Bootloader/stub/UKI path | systemd `LoaderInfo`, `StubInfo`, `StubImageIdentifier` EFI variables | EFI attribute header followed by checked UTF-16; unreadable variables stay null |
| Root filesystem/encryption | `/proc/self/mountinfo`, `/dev` symlinks, sysfs `dm/uuid` and `slaves` | Root type/source/options and known LUKS2/LUKS1/dm-crypt signature; unresolved backing device stays null |
| Desktop session | `XDG_CURRENT_DESKTOP`, `XDG_SESSION_TYPE` | Current invocation's session; recognized session types are wayland and x11 |

Partitions need not have a `slaves` directory. The shared `partition_parent`
function follows the canonical sysfs partition directory to its containing disk.
Both storage inventory and root encryption traversal use it. Loop, ram and zram
devices are omitted; dm devices remain in detailed hardware data. No capacities
are summed across disks, partitions and mappings.

The block size is the kernel's 512-byte sector unit, independent of hardware
logical sector size. See the [kernel block ABI](https://github.com/torvalds/linux/blob/master/Documentation/ABI/stable/sysfs-block),
[DRM node interface](https://www.kernel.org/doc/html/latest/gpu/drm-uapi.html),
and [systemd virtualization implementation](https://github.com/systemd/systemd/blob/main/src/basic/virt.c).

## JSON schema version 1

Both documents have `schema_version: 1`. Consumers should ignore new fields and
handle null explicitly. Objects and arrays are data, never formatted text.

`hardware --json` is a `Hardware` object. `status --json` has top-level
`name`, `version`, `channel`, `hostname`, `kernel`, `boot`, `filesystem`,
`desktop` and `hardware`, plus its own schema version. `hardware` is exactly the
same model used by the hardware command; collection times may differ.

| Hardware field | JSON type | Meaning |
| --- | --- | --- |
| cpu.architecture | string | Rust target architecture |
| cpu.vendor, cpu.model | string or null | Observed identity |
| cpu.logical_count, cpu.physical_core_count | integer or null | Reported CPU topology |
| memory_bytes, memory_available_bytes | integer or null | Exact bytes |
| gpus | array or null | Empty means enumeration found no GPUs; null means no discovery source |
| gpus[].pci_address, vendor, vendor_id, device_id, model, driver | string or null | IDs are lowercase `0x` plus four hex digits; platform DRM GPUs may lack PCI data |
| gpus[].drm_nodes | array of strings | Associated `/dev/dri` paths; these paths do not promise permission to open the nodes |
| gpus[].boot_vga | boolean or null | Explicit firmware boot GPU flag |
| storage | array or null | Empty means enumeration found no included devices; null means source unavailable |
| storage[].name, path | string | Kernel name and corresponding `/dev` path |
| storage[].model, parent | string or null | Model and containing disk name for a partition |
| storage[].transport | string or null | `nvme`, `sata`, `virtio`, `usb` |
| storage[].size_bytes | integer or null | Capacity, not filesystem free space |
| storage[].rotational | boolean or null | Explicit kernel rotational flag |
| storage[].kind | string | `disk`, `partition`, `mapped` |
| capabilities.uefi, virtual_machine | boolean or null | Positive or explicit negative observations; VM absence remains null |
| capabilities.virtualization_type, container_type | string or null | Observed hypervisor/systemd container type |
| issues | array of objects | `source`, `kind`, `message` diagnostics |

`issues[].kind` is `unavailable` for missing principal sources, `unknown` for
malformed numeric observations, or `error` for IO/permission/encoding failures.
Missing optional attributes become null without individual unavailable issues.
Unknown PCI vendors retain numeric IDs with a null vendor name. Empty optional
strings become null. Diagnostic messages are explanatory and not a parsing API.

Status `boot` contains nullable strings `firmware` (`UEFI`/`BIOS`), `bootloader`,
`stub`, `uki_path`. It preserves the Phase 1 installer smoke script's existing
fields. `filesystem` has nullable `root_type`, `source`, `options`, `encryption`
(`LUKS2`, `LUKS1`, `dm-crypt`, `none`). `desktop` has nullable `name` and
`session_type`. A visible UKI filename alone is not a validated boot image.

Existing Phase 1 field names remain in place. New fields are additive, except
the formerly literal `Unknown` GPU vendor now serializes as null. Raw Rust PCI
tuples are replaced by `RawGpu`; callers constructing raw fixtures should use
the typed fields and `Default` for new observations.

## Limits and validation

VM topology describes CPUs presented to the guest, not the physical host.
VM detection covers several DMI vendors and ARM device-tree evidence; generic
`Virtual Machine` and Amazon EC2 DMI alone are insufficient. EC2 bare-metal hosts
must not be mislabeled. A hypervisor CPU flag can establish a VM with unknown
type. No negative VM result is inferred from missing evidence.

Containers may expose host memory/CPU, only some GPUs/devices, and masked firmware
or EFI variables. Memory is system RAM, not cgroup allocation. No render node is
required for success. Explicitly marked containers without EFI report firmware
as unknown. An unmarked container that selectively masks EFI may still hide its
actual host boot mode.
Restricted EFI or mapper metadata stays unknown and requires no elevation.

Desktop data describes the calling environment, not all logged-in sessions. No
Plasma version, driver installation status, GPU performance suitability, active
compositor GPU, CPU feature catalogue or tuning recommendations are inferred.
Root encryption traverses the observed mount source and sysfs backing chain,
with a depth bound of 16; it does not validate every member of a multi-device
Btrfs filesystem or unlock/read device headers. `none` refers to that inspected
chain, not a cryptographic audit of all disks.

Fixture tests cover CPU/memory parsing, vendors and incomplete GPUs, block
parents without slaves, firmware/VM fallbacks, malformed/missing observations,
IO diagnostics, JSON types, formatting and exact CLI exit codes. Unix tests
exercise actual PCI/DRM/block symlinks. Tests use supplied roots and never need
the developer's GPU, EFI access, root privileges or an installed Astraeus image.
See [testing](testing.md) for commands. Bare-metal and installed-image acceptance
remain separate from these subsystem checks.
