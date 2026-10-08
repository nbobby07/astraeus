# Phase 2 snapshots and offline rollback

`distro-snapshots` provides the Rust state-management library; `distroctl` owns
argument parsing and presentation only. Base: `aad4409`, following completed
Phase 1 installation validation. This branch executes no package updates and
does not qualify a new installed guest.

## Actual layout and policy

[Phase 1 validation](validation.md#actual-storage) recorded plain and encrypted
installations with these siblings under Btrfs top-level ID 5. Their initial IDs
were 256 through 261; runtime checks do not hardcode those numeric IDs.

| Subvolume | Mount | Recovery policy |
| --- | --- | --- |
| `@` | `/` | Restore OS, configuration, pacman database and other service state together |
| `@home` | `/home` | Preserve documents, user Flatpaks and user VM disks |
| `@snapshots` | `/.snapshots` | Preserve snapshots, metadata and recovery evidence |
| `@log` | `/var/log` | Preserve logs |
| `@cache` | `/var/cache` | Preserve downloads and package caches |
| `@containers` | `/var/lib/containers` | Preserve container data |

Other `/var/lib` data rolls back. Docker and VM disks outside these persistent
mounts need their own policy. Unexpected nested subvolumes, separate `/boot` or
`/usr`, and additional system fstab mounts are rejected. Only `@` is snapshotted,
read-only, into a sibling subvolume's storage. No snapshot contains itself.

Btrfs snapshots are nonrecursive. Phase 1 explicitly selects `@` in fstab and
the UKI, so `set-default` would not switch its root. Recovery replaces the named
`@` with a writable clone, retaining its predecessor. These semantics follow
the [Btrfs documentation](https://btrfs.readthedocs.io/en/stable/btrfs-subvolume.html).

## API and metadata

`Manager<Commands>` exposes `plan_create`, `create`, `list`, `inspect`, `mark`,
`plan_rollback`, `rollback` and `delete`. `Native` runs fixed `/usr/bin/` tools
with argument arrays, a controlled environment and C locale. Tests provide
command fixtures and temporary filesystem trees. Filesystem mutation stays in
the library.

`lock` returns a `MutationGuard`. Hold it across a transaction and use
`create_locked` for pre/post snapshots. It uses Rust's OS file lock, released on
process exit. Never unlink the lock file. Independent package tools do not honor
this lock: callers must prevent concurrent package/boot changes. Creation also
refuses an existing pacman database lock. No pacman commands are run here.

```text
@snapshots/astraeus/
  lock
  pending.json                         # incomplete mutation only
  operation-<operation-id>.json         # completed intent/history
  operation-<operation-id>-previous.efi # retained pre-rollback UKI
  <seconds>-<nanoseconds>-<pid>/
    metadata.json                      # public, mode 0644
    private/                           # mode 0700
      root                             # read-only Btrfs snapshot
      boot.efi                         # saved UKI
```

Catalog directories have mode 0755. Online list/show reads mount observations
and public metadata without requesting root or invoking Btrfs. `/.snapshots`
must be traversable, normally mode 0755. Rollback planning reads private content
and normally needs sudo. Malformed metadata and foreign UUIDs fail visibly.

JSON schema 1 records a validated ID, Unix creation time in seconds, filesystem
UUID, source root ID/UUID/parent UUID, reason (`manual`, `pre-update`,
`post-update`), optional opaque transaction ID, snapshot ID/UUID/parent UUID,
top-level identity, read-only status, health, validation evidence and boot state.
Source UUID identifies the mutable source subvolume. Snapshot ID identifies the
historical generation. Transaction IDs are references, not a transaction DB.

Boot state binds the ESP UUID, fixed UKI relative path and SHA256. The saved
x86-64 PE image must contain `.linux`, `.cmdline`, `.initrd` and `.uname`. Kernel
bytes must match `/boot/vmlinuz-linux`, command-line tokens must match
`/etc/kernel/cmdline`, and the corresponding module directory must exist. See
the [UKI format specification](https://uapi-group.org/specifications/specs/unified_kernel_image/).
This does not establish boot health or validate every module/initrd member.

New snapshots start `unknown`. Explicit health changes require evidence text.
States are `unknown`, `candidate`, `known-good` and `bad`. Failed states cannot
transition directly to `known-good`. Neither package success nor snapshot
creation promotes health. Metadata publication follows file/filesystem sync;
health updates use same-directory temporary files and atomic rename. A leftover
`metadata.next` must be inspected before another update; it is not overwritten.

## Commands

```sh
distroctl snapshot list --json
distroctl snapshot show ID --json
distroctl snapshot create --dry-run --json
sudo distroctl snapshot create --reason pre-update --transaction 108 --json
sudo distroctl snapshot create --reason post-update --transaction 108 --json
sudo distroctl snapshot mark ID candidate --evidence 'awaiting boot validation'
sudo distroctl snapshot mark ID known-good --evidence 'boot-health report reference'
sudo distroctl rollback ID --dry-run --json
```

Use actual validation evidence when promoting. Dry-run performs discovery and
checks only: no locks, intent files, snapshots, copies, renames or deletions.
`--json` provides structured output; ordinary output uses labeled fields.
Unknown, unrelated, repeated and conflicting options are rejected.

## Offline execution

Use trusted recovery media. Unlock encrypted roots as `/dev/mapper/root` without
changing headers or keyslots. Mount the intended Btrfs filesystem with
`subvolid=5` and its ESP at separate dedicated mountpoints. Leave all installed
subvolumes unmounted. Once mounted:

```sh
sudo distroctl rollback ID --dry-run --top-level /mnt/astraeus --esp /mnt/astraeus-esp --json
sudo distroctl rollback ID --execute --top-level /mnt/astraeus --esp /mnt/astraeus-esp --json
sudo distroctl snapshot delete UNUSED_ID --top-level /mnt/astraeus --esp /mnt/astraeus-esp
```

Execution under the store lock:

1. Refuse containers, chroots, private mount namespaces, unexpected layouts and
   any additional mount of the target filesystem. Validate root-owned managed
   paths and reject symlinks in their ancestry.
2. Require known-good evidence, recorded read-only target identity, filesystem
   and ESP UUIDs, intact UKI, coherent six-entry fstab and explicit
   `rootflags=subvol=@`. Require the Phase 1 loader default
   `astraeus-dev-linux.efi`.
3. Persist `pending.json` with current/target identities and recovery paths.
   Save the current UKI in snapshot history. Copy and sync the target UKI to
   a hidden temporary ESP filename.
4. Create writable `@restore-<operation-id>` from the historical root; verify
   its parent UUID, boot relationship and durability.
5. Recheck mounts/current identity. Rename `@` to `@previous-<operation-id>` and
   sync. Rename the prepared root to `@` and sync.
6. Replace the stable UKI path with the staged artifact and sync the ESP.
   Verify final identities and archive the completed intent.
7. Return the plan, restored identity, retained root/UKI paths and operation ID.
   The plan reports reboot required. Never reboot automatically.

The read-only target, previous root, previous UKI, logs and five persistent
subvolumes survive. Repeating a completed rollback restores again and retains
another previous root; parent UUID alone is not proof of unchanged root content.
Deletion is offline-only and protects known-good snapshots, the current root's
parent and all targets referenced by completed rollback history. No automatic
pruning or recursive deletion of previous roots is implemented.

### Interrupted operations

Btrfs renames and FAT replacement are not a single atomic transaction. Power
loss between switching root and UKI can leave a mismatched boot pair. Keep
recovery media available and remain in recovery until completion. This is not
an unattended or power-loss-safe reboot mechanism.

`pending.json` blocks further mutations. Do not remove it and retry. Inspect its
identities and paths against actual `btrfs subvolume show` output. If `@` is
missing, the previous root remains at `previous` and the prepared root at
`candidate`. If `@` is the candidate clone, its parent UUID must match the target.
The old UKI is at `previous_uki`; the target UKI remains in the snapshot private
directory and at `staged_uki` until renamed. Restore a matching old root/old UKI
pair or finish installing the verified target pair, then sync both filesystems.
Only archive the intent after checking the resulting pair and recording manual
recovery evidence. No automatic resume or interactive recovery command exists.

An unfinished health write leaves `metadata.next` beside `metadata.json`. Its
presence blocks new mutations and rollback planning across the store, even when
there is no `pending.json`. Do not discard it to reuse an older known-good label.
Inspect and retain both records offline, check their snapshot identity and health
evidence, and resolve the interrupted change before continuing. A pending promotion
does not establish a healthy boot; unknown health must remain unconfirmed or bad.

## Integration and limits

Mounted Btrfs UUIDs identify ordinary partitions, virtio devices and LUKS mappings;
there is no duplicate hardware/partition-parent resolver. Encrypted targets
additionally verify the opened `root` mapper's backing LUKS UUID and its Btrfs
UUID against crypttab, fstab and UKI. No secret enters metadata or arguments.

Chat 1 should hold `MutationGuard` across pre-snapshot, package changes, UKI
staging and post-snapshot, recording returned snapshot IDs in its own history.
Use `create_locked` while holding the guard. A changed kernel without a matching
UKI is rejected at post-snapshot creation. Package/UKI failure must retain the
pre-snapshot and report recovery required. Boot confirmation supplies the health
evidence. Service databases may need quiescing: snapshots are crash-consistent,
not automatically application-consistent.

The stable UKI path matches Phase 1. A boot-generation owner must extend the
binding and loader checks before introducing an independent "Astraeus Previous
Known Good" entry. Boot menus, Secure Boot enforcement, firmware overrides,
bootloader binary rollback and multiple kernels are not implemented/qualified.
The integrated updater rejects systemd/bootloader update plans before mutation
and never refreshes the loader copies as part of a package transaction.
There is no full data scrub, backup replication, automatic retention,
multi-device Btrfs qualification or cross-filesystem atomicity.

Unit tests cover discovery, metadata, health changes, pre/post correlation,
catalog privileges, lock contention, command generation, dry-run, wrong/missing
filesystems and targets, corrupt UKIs, malformed metadata, symlinks, fstab
mismatch, persistent exclusions and interrupted durability boundaries.
Windows and Linux workspace tests pass. A real disposable Btrfs/FAT loopback
roundtrip passed on WSL2 6.6.114.1 using btrfs-progs 6.17.1 and dosfstools 4.2.
Its test executor allows an isolated WSL fixture; production refuses WSL.
Its synthetic UKI qualifies storage/byte handling, not UEFI boot.

Chat 3 owns real plain/encrypted QEMU boots, power-cut recovery, disk-full/ESP
failure qualification and installed non-root catalog checks. See [testing](testing.md).

## Integrated live-media recovery procedure

The signed distroctl package is included in both the installed payload and live
ISO, with Btrfs, cryptsetup and UKI inspection dependencies. A copy of this guide
is installed at `/usr/share/doc/distroctl/offline-recovery.md`. There is no automatic
fallback menu entry. If disk boot fails, boot the Astraeus ISO from the firmware's
one-time boot menu, open a terminal, identify the installed disk with `lsblk -f`,
and run the following with the actual system and ESP partitions. Do not select the
live media or another disk. Do not mount the installed root or persistent siblings.

```sh
sudo cryptsetup open /dev/ACTUAL_SYSTEM_PARTITION root  # LUKS2 only
sudo mkdir -p /mnt/astraeus /mnt/astraeus-esp
sudo mount -t btrfs -o subvolid=5 /dev/mapper/root /mnt/astraeus
# Plain root: use /dev/ACTUAL_SYSTEM_PARTITION instead of /dev/mapper/root.
sudo mount -t vfat /dev/ACTUAL_ESP_PARTITION /mnt/astraeus-esp
sudo distroctl snapshot list --top-level /mnt/astraeus --esp /mnt/astraeus-esp --json
sudo distroctl rollback ID --dry-run --top-level /mnt/astraeus --esp /mnt/astraeus-esp --json
# Inspect target, affected root and preserved siblings. --execute is explicit consent.
sudo distroctl rollback ID --execute --top-level /mnt/astraeus --esp /mnt/astraeus-esp --json
sync
sudo umount /mnt/astraeus-esp /mnt/astraeus
sudo cryptsetup close root  # only if opened above
```

Remove the ISO and boot the installed disk. Run `sudo distroctl finalize-rollback
TRANSACTION_ID` and inspect `distroctl history --json`. A restored filesystem alone
does not finalize the transaction. If a confirmation unit previously failed,
inspect its journal and fix the cause before a retry. A new boot clears its failed
runtime state; do not erase failed-unit evidence to manufacture acceptance.

If `pending.json` exists, stop and follow Interrupted operations above. Root and
ESP switches are not atomic together. No power-loss protection or automatic
interrupted-rollback resume is claimed.
