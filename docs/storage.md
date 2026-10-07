# Phase 1 storage

This is the implemented installer configuration. On-disk qualification is recorded
separately in [validation](validation.md), including actual UUIDs and fstab output.

Default erase-disk installation uses GPT, a 1 GiB FAT32 ESP mounted at `/efi`, and
the remaining disk as Btrfs. With encryption the latter is a LUKS2 container.
Calamares delegates formatting to KPMcore/cryptsetup; the finalization job rejects
anything other than a LUKS2 header using Argon2id. It does not override cryptsetup
cipher, key size, memory budget, iteration time or parallelism. The actual
resulting KDF parameters and segment encryption settings are retained in
`/var/log/installer/storage.json`. They vary with cryptsetup's hardware calibration.

The upstream mount module first mounts Btrfs top-level ID 5, creates these six
sibling subvolumes, unmounts it, then explicitly mounts each configured subvolume.
Its fstab module uses the curated subvolume list and mount options. Creation is
not inferred from the partition module. No default-subvolume change is required.

| Subvolume | Mount | Purpose | Future system rollback |
| --- | --- | --- | --- |
| `@` | `/` | OS, configuration and pacman database | Included together |
| `@home` | `/home` | User files and user Flatpaks | Excluded |
| `@snapshots` | `/.snapshots` | Reserved snapshot storage | Excluded |
| `@log` | `/var/log` | Persistent install and service evidence | Excluded |
| `@cache` | `/var/cache` | Package/download caches | Excluded |
| `@containers` | `/var/lib/containers` | Container state | Excluded |

Btrfs mounts use `defaults,noatime,compress=zstd:1,subvol=/NAME`; the ESP uses
`defaults,umask=0077`. Calamares's fstab adds filesystem UUIDs. `/tmp` is tmpfs.
No swap partition or swapfile is created. Hibernation and zram policy are not
implemented. There is no VM-specific subvolume in Phase 1; no virtualization stack
is installed. Ordinary VM disks under `/home` already remain outside root rollback.

The package database remains under `@` so future root rollback cannot separate it
from installed files. Service state under `/var/lib` otherwise stays with root.
The ESP and UKI are outside Btrfs snapshots. No snapshot manager, rollback, TPM
unlock, recovery generations or transaction history is implemented.

No encryption password or keyfile is written to the payload or installed logs.
The initramfs asks for the passphrase. The unlocked mapping is named `root` during
boot regardless of Calamares's temporary installation mapper name. No discard
option is enabled on the encrypted mapping.
