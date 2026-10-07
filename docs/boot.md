# Installed boot

The implemented chain is UEFI, systemd-boot, a Type #2 Unified Kernel Image,
systemd initramfs, optional LUKS2 unlock, Btrfs `@`, systemd, SDDM and Plasma Wayland.
Boot acceptance remains a separate gate in [validation](validation.md).

The ESP is mounted at `/efi`. The one current kernel is the stock Arch `linux`
package from the pinned snapshot. The preset at `/etc/mkinitcpio.d/linux.preset`
uses `/boot/vmlinuz-linux`, `/etc/mkinitcpio.conf` and `/etc/kernel/cmdline` to write:

```text
/efi/EFI/Linux/astraeus-dev-linux.efi
```

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
passphrase handling. Multi-generation boot artifacts and rollback are later work.
