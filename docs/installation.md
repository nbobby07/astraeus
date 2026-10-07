# Installation foundation

Phase 1 source is under development. Successful unit tests or an installer success
page do not establish installed-OS acceptance. See [validation](validation.md).

The live application menu exposes **Install Project Astraeus**. Calamares 3.4.3
is built from the upstream release, SHA256
`144cbbf6bdcebfb21685950db4f0777218519df095f62f4aa392f28348110d18`, and signed with
the same operator-selected custom-repository identity as distroctl. It is absent
from the dated official Arch repositories. No AUR helper or third-party binary
repository is used.

The normal pages are welcome/language, timezone/locale, keyboard, disk, account,
summary, installation, and finish. Encryption is selected by default and remains
optional. Installation requires UEFI, 20 GiB storage and 2 GiB RAM. The default
disk uses GPT, a 1 GiB unencrypted FAT32 ESP at `/efi`, and a Btrfs system
partition, optionally inside LUKS2. Manual partitioning is disabled for this
foundation. Existing-system replace/alongside paths need separate qualification.

The Calamares build requires libparted so its storage requirement cannot be
silently compiled out. [CMake's required-package option](https://cmake.org/cmake/help/latest/variable/CMAKE_REQUIRE_FIND_PACKAGE_PackageName.html)
makes a missing library fail the build. An 8 GiB guest is checked during
acceptance before partitioning.

The passwordless live session does not automatically lock during long installs
or on resume. A real unattended test reached an upstream lock-screen QML error
after PAM accepted the blank live account. The live-only `kscreenlockerrc`
prevents that interruption; it is not copied into the installed payload.
Installed users retain normal password-protected screen locking. These settings
use [KDE's screen-lock configuration](https://github.com/KDE/kscreenlocker/blob/master/settings/kscreenlockersettings.kcfg).

`distro/installer/config.json` is the source for module settings. The build
generator writes JSON, which is valid YAML, into `/etc/calamares/*.conf`. The
upstream modules perform partitioning, encryption, subvolume creation, extraction,
locale/timezone/keyboard configuration, fstab generation and user/password setup.
The two small distribution jobs check requirements before partitioning and
finalize the already-mounted target's UKI, bootloader, repository and services.
They do not partition disks or handle passwords.

Execution order:

```text
astraeus-preflight -> partition -> mount -> unpackfs -> machineid -> locale
-> keyboard -> localecfg -> fstab -> users -> astraeus -> umount
```

`unpackfs` reads `/run/archiso/airootfs/opt/distro/install-root.sfs`, a separate root assembled by
pacstrap from `distro/installed/packages.x86_64`. Package signatures are verified
with the build keyring before packaging. The source is accessed through ArchISO's
read-only SquashFS mount. Opening it as a loop device through `/opt` triggers
overlay copy-up into the small live writable layer and fails with ENOSPC.
This payload contains no `live` account,
live sudo policy, live firstboot mask, live autologin, ArchISO initramfs hooks,
installer package or installer configuration. It includes the signed local custom
repository and pinned HTTPS Arch repositories. During installation a fresh pacman
keyring initializes and trusts the selected public fingerprint. No build keyring
or private development signing key is copied.

Calamares creates one user with password-authenticated sudo via `wheel`, locks
root password login, and disables automatic login. SDDM uses KWin for its Wayland
greeter and initially selects Plasma Wayland. The selected keyboard layout is
also written to the installed user's Plasma configuration. NetworkManager owns
networking and `/etc/resolv.conf`; PipeWire/Pulse sockets and WirePlumber are
enabled for normal user sessions. No SSH service is added.

UKI paths and regeneration are documented in [boot](boot.md); the six mounts and
future rollback boundaries are documented in [storage](storage.md).

Research used the actual release source, especially
[mount/main.py](https://codeberg.org/Calamares/calamares/src/tag/v3.4.3/src/modules/mount/main.py),
[fstab/main.py](https://codeberg.org/Calamares/calamares/src/tag/v3.4.3/src/modules/fstab/main.py),
[partition configuration](https://codeberg.org/Calamares/calamares/src/tag/v3.4.3/src/modules/partition/partition.conf),
and [bootloader/main.py](https://codeberg.org/Calamares/calamares/src/tag/v3.4.3/src/modules/bootloader/main.py).
The upstream bootloader module writes separate kernel/initramfs entries rather
than this project's UKI preset, so the final distribution job invokes standard
`bootctl` and `mkinitcpio` directly. GRUB is not installed.
