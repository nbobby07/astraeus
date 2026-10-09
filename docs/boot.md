# Installed boot

Phase 3 adds opt-in [boot generations and retained-root recovery](boot-generations.md).
The fixed Type #2 layout below remains the default until that feature is enabled.

Provisioning an owner signing policy and enrolling its public identity are
separate from installing the development ISO. The Phase 3 acceptance setup signs
the installed loader and initial UKI with disposable owner keys, then uses
enforcing firmware for installed-generation and recovery tests. The ISO is not
an out-of-box signed release. See [current acceptance](phase3-acceptance.md).

In generation mode, immutable UKIs bind their expected root identities and
embedded command lines. systemd-boot counts candidate attempts; a successful
health-verified boot is blessed. Exhausted attempts can select the retained root
and its signed UKI. This fallback is a recovery session: restoring `@` and
finalizing rollback still require deliberate recovery steps.

The implemented chain is UEFI, systemd-boot, a Type #2 Unified Kernel Image,
systemd initramfs, optional LUKS2 unlock, Btrfs `@`, systemd, SDDM and Plasma Wayland.
Boot acceptance remains a separate gate in [validation](validation.md).

The ESP is mounted at `/efi`. The one current kernel is the stock Arch `linux`
package from the pinned snapshot. The preset at `/etc/mkinitcpio.d/linux.preset`
uses `/boot/vmlinuz-linux`, `/etc/mkinitcpio.conf` and `/etc/kernel/cmdline` to write
the following path on an unprovisioned, non-enforcing development installation:

```text
/efi/EFI/Linux/astraeus-dev-linux.efi
```

The Phase 3 helper selects private output when a signing policy, retained signing
state or firmware SecureBoot=1 requires signing. Its post hook publishes verified
candidates outside the ESP. The integrated update hook requires the locked
coordinator and a verified retained generation before package mutation. See the
[signing contract](secure-boot.md#signing-and-generation-interface); the signer does
not select or activate boot generations; it supplies their verified artifacts.

The product ID comes from the central manifest. `mkinitcpio` with `systemd-ukify`
packages the kernel, initramfs, OS release, kernel version and embedded command
line. The installer runs `ukify inspect` on the generated artifact before finishing.
systemd-boot automatically discovers this Type #2 entry. Its loader configuration
selects the filename, waits three seconds, and disables interactive command-line
editing. Firmware Settings is supplied by upstream systemd-boot when supported.
There is no additional kernel, LTS entry or recovery manager.

Command lines generated from the actual partition UUID:

```text
root=UUID=<Btrfs UUID> rootflags=subvol=@ rw
rd.luks.name=<LUKS UUID>=root root=/dev/mapper/root rootflags=subvol=@ rw
```

For encrypted installations, `/etc/crypttab` and all six Btrfs fstab entries use
the `root` mapper too. Keeping Calamares's temporary mapper name in fstab would
make the remaining subvolume mounts wait for a device the initramfs never creates.

The QEMU acceptance launcher uses explicit device boot priorities: ISO first and
disk second during installation, disk first with the ISO detached afterward.
Legacy/default disk selection fell through to PXE on the validator's OVMF;
the same disk booted with `virtio-blk-pci,bootindex=1`. See the
[QEMU bootindex documentation](https://www.qemu.org/docs/master/system/bootindex.html).

The initramfs uses `base systemd autodetect microcode modconf keyboard sd-vconsole
block sd-encrypt filesystems fsck`, with explicit Btrfs, virtio, NVMe, AHCI and
USB/HID modules. `sd-vconsole` includes the selected console keymap for passphrase
entry. There is no embedded unlock key or TPM policy.

Arch's mkinitcpio package hooks regenerate the preset for kernel/initramfs changes.
The additional hooks cover ukify, microcode, cryptsetup and Btrfs package changes,
and update systemd-boot after a systemd upgrade. For manual edits to
`/etc/kernel/cmdline`, `/etc/mkinitcpio.conf` or `/etc/vconsole.conf`, run:

```sh
sudo mkinitcpio -P
sudo ukify inspect /efi/EFI/Linux/astraeus-dev-linux.efi
```

There is no enforced Secure Boot in Phase 1. The stable `/EFI/Linux/` output path
and standard ukify boundary leave signing work separate from installer UI and
passphrase handling. Multi-generation boot menu integration remains later work.
The Phase 2 [snapshot library](snapshots.md) binds saved UKIs to root snapshots
and restores the pair through explicit offline recovery.
