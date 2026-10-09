# Build the bootstrap

## Development checks (Windows or Linux)

Install Rust 1.96 or later and Python 3.11 or later. No Python dependencies are
required. Online archive verification also needs curl 8.4 or later for streaming
size enforcement. The tested developer toolchain is 1.96.0; image packages use the compiler
from the pinned Arch snapshot, currently 1.98.1.

```sh
cargo fmt --all --check
cargo test --workspace --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
python3 -m unittest discover -s tests -v
python3 scripts/bootstrap.py verify-archive
```

On Windows use `python` instead of `python3`. Bash syntax checks can run in WSL.
Native Windows cannot run mkarchiso. WSL alone is insufficient without an Arch
userspace, working mount/loop support and suitable VM tools.

## Prepare a disposable Arch builder

Use an x86-64 Arch Linux VM or dedicated throwaway machine, with at least 8 GiB
RAM and 30 GiB free on a Linux filesystem. These are starting allocations, not
measured minimums. Use a path without spaces. Do not build under `/mnt/c`, FAT or
a network share. The image build needs root, chroot, mount and loop-device support.

Start with an authenticated Arch installation and a current trusted Arch keyring.
Clone/copy this repository to the VM. In this **disposable builder only**, configure
the normal `core`, `extra` and `multilib` repositories to use the pinned archive. Disable any
other enabled repositories in the builder's pacman configuration. Keep signature
verification enabled. From the source root:

```sh
ARCHIVE=$(python3 -c 'import tomllib; print(tomllib.load(open("distro/branding/project.toml", "rb"))["build"]["archive_date"])')
sudo python3 scripts/bootstrap.py verify-archive --output /var/tmp/astraeus-archive
printf 'CacheServer = https://archive.archlinux.org/repos/%s/$repo/os/$arch\nServer = file:///var/tmp/astraeus-archive\n' "$ARCHIVE" | sudo tee /etc/pacman.d/mirrorlist
sudo pacman -Syyuu --needed base-devel archiso rust python gnupg git qemu-desktop edk2-ovmf systemd-ukify sbsigntools efitools
```

Install Python and curl from the authenticated baseline before this step. Use a
fresh root-owned archive directory. Package metadata comes only from the verified
local files; CacheServer supplies signed packages without supplying databases.
ISO builds retain their own verified files in `archive/`, check them before both
package resolvers, and record the hashes in `inputs.json`. Downloads are capped at
64 MiB per database and 60 seconds, with a 65-second subprocess deadline.
Do not mix current mirrors with archived mirrors. Reboot if the full snapshot sync
changed the running kernel or core services. Verify `pacman -Q archiso` reports
`91-1` and `/usr/bin/rustc --version` reports `1.98.1`. Save `pacman -Q` with build
evidence. The ISO script rejects the wrong ArchISO version; the PKGBUILD rejects
the wrong compiler. Host kernel, filesystem and tool configuration also affect
reproducibility, so use the same VM baseline for comparison builds.

Reference: [Arch Linux Archive](https://wiki.archlinux.org/title/Arch_Linux_Archive).

## Build and sign the platform package

As the ordinary build user, choose or create a **development-only** GPG signing
identity outside the source tree. Use an isolated `GNUPGHOME`, mode 0700, and run
`gpg --full-generate-key` interactively if needed. Never put a private key in this
repository. Set `KEY` to the full uppercase 40-hex primary fingerprint from
`gpg --list-secret-keys --with-subkey-fingerprint`. Signing uses your normal GPG
agent and may prompt for the key passphrase.

```sh
export KEY=YOUR_FULL_PRIMARY_FINGERPRINT
export SOURCE_DATE_EPOCH=$(python3 -c 'import tomllib; print(tomllib.load(open("distro/branding/project.toml", "rb"))["build"]["source_date_epoch"])')
export PACKAGER='Distribution developers'
python3 scripts/bootstrap.py package --output .build/package
(
  cd .build/package
  makepkg --config /etc/makepkg.conf --cleanbuild --sign --key "$KEY"
)
bash scripts/publish-repo.sh "$KEY" out/repo .build/package/*.pkg.tar.zst
```

The first package preparation downloads exactly the dependencies in Cargo.lock,
vendors them and creates a normalized source archive with a SHA256-pinned PKGBUILD.
`makepkg` then builds and tests offline with `cargo --frozen`. It must not run as
root. Keep the same signed package/repository input for both ISO comparison builds;
regenerating signatures changes bytes independently of the image build.

`publish-repo.sh` only publishes into a new local directory. It checks package
signatures against `KEY`, signs the pacman database and exports only the public
key. A failure leaves that new directory for inspection; do not use partial
output. No network repository is created by these commands.

## Build the live ISO

Phase 1 also requires the signed `calamares` package. After package preparation,
install the pinned build prerequisites and build the upstream release as `builder`:

```sh
sudo pacman -S --needed $(cat distro/packages/calamares/build-packages.x86_64)
(
  cd .build/package/calamares
  makepkg --config /etc/makepkg.conf --cleanbuild --sign --key "$KEY"
)
bash scripts/publish-repo.sh "$KEY" out/phase1-repo \
  .build/package/*.pkg.tar.zst .build/package/calamares/*.pkg.tar.zst
```

Use this complete repository as `--repo` below. The existing `out/repo` example
must likewise contain both signed packages. Publication always requires a new
directory. The Calamares source URL/version/hash and its minimal upstream module
selection are in the reviewable PKGBUILD. Build prerequisites also belong to the
archive lock; verification checks the union of live, installed and builder inputs.

Before mkarchiso, the ISO builder creates `installed-root/` with pacstrap from the
separate explicit installed package list. It verifies packages with the isolated
build keyring, stages installed configuration and creates a timestamp-normalized
`install-root.sfs` inside the live profile. Account policy, keyring initialization
and bootable UKI generation happen later in Calamares. This second payload means
Phase 1 images require more disk space than Phase 0. Allocate 50 GiB free for an
individual clean builder as a conservative allowance; measure actual usage.

From the source root in the pinned Arch builder:

```sh
sudo python3 scripts/bootstrap.py iso \
  --repo "$(pwd)/out/repo" --fingerprint "$KEY" \
  --output "$(pwd)/out/build-a"
```

The script verifies all three archive database hashes, stages the profile, verifies the
repository public-key fingerprint, initializes an isolated build keyring and runs
mkarchiso with a fixed `SOURCE_DATE_EPOCH`. Pacman verifies package signatures and
the custom database before installation. The live ISO includes the signed custom
repository so its pacman configuration never refers to the build host.

Successful output includes `iso/*.iso`, `iso/SHA256SUMS`, `inputs.json`,
and the selected [graphics bundles](graphics.md#image-selection). Add `--graphics`
with the intended vendor names for native and 32-bit Vulkan in the installed image.
The default payload includes Mesa and loaders but no vendor Vulkan ICD.
Other build outputs include
`builder-packages.txt`, `image-packages.txt`, `installed-packages.txt`, the generated `profile/`, `keyring/`
and `work/`. The isolated keyring contains locally generated trust material and
is not a release artifact. Do not distribute it. Retain the package/repository
inputs, manifests and boot logs with the ISO. No automatic publication occurs.

The builder intentionally refuses existing output directories. Use `build-b`
for a fresh retry; never reuse ArchISO's cached work after changing an input.

## UEFI boot verification

Use `pacman -Ql edk2-ovmf` to locate a matching ordinary, non-enforcing OVMF CODE
and VARS pair. Set `OVMF_CODE` and `OVMF_VARS` to their absolute paths. Do not use
the secure/enrolled variants for this unsigned Phase 0 image. The harness copies
the VARS template and does not modify the original firmware file or host firmware.

```sh
python3 scripts/boot-smoke.py out/build-a/iso/*.iso \
  --ovmf-code "$OVMF_CODE" --ovmf-vars "$OVMF_VARS" \
  --log out/boot-a.serial.log
```

QEMU requires KVM by default and records its invocation beside the serial log.
Software emulation requires an explicit `--accel tcg`; that result is not KVM
validation. It has no virtual hard disk
and no host-directory sharing. The test waits up to ten minutes for evidence from
the actual guest: UEFI, the platform CLI, NetworkManager, initialized keyring, an
active live-user Wayland session, plasmashell, and PipeWire/Pulse sockets. A boot
menu, SDDM greeter or early kernel log cannot satisfy this check. The harness does
not prove network connectivity or successful audio playback; inspect those manually.

For visual inspection, run the same QEMU arguments shown in `boot-smoke.py` with
`-display gtk` instead of `-display none`, using a copied writable VARS file.
Confirm scaling, keyboard input, opening Ghostty and Konsole, NetworkManager UI,
audio playback and shutdown. See [testing](testing.md) for the complete gate.

On a headless cloud host, `scripts/validate/visual-boot.py` keeps the same KVM/UEFI
guest running with a private Unix QMP socket. Use `scripts/validate/qmp.py` for
`screendump`, keyboard and pointer events, and `quit` when finished. No public VNC
server or forwarded shell is required. `--gpu VGA` selects standard VGA for a
diagnostic comparison; the default remains `virtio-vga`. Record which device was
actually tested. A running compositor process is not visual desktop evidence.

## Reproducibility

Repeat the ISO command with `out/build-b`, the same repository, source tree and
builder baseline. Compare both ISO SHA256 values and package manifests. Source
archives normalize ordering, ownership, modes and timestamps and are covered by
a determinism test. Archive database hashes and Cargo.lock pin dependency inputs.

**Full ISO byte reproducibility matched for the recorded final pair.** See
[validation](validation.md) for the exact source, signed inputs and complete hashes.
Changed profiles or tool versions require a new comparison. If hashes differ,
compare extracted trees and use diffoscope before changing the pipeline. Record
each cause and verify its correction with two fresh builds.

The real A/B comparison isolated two differences. The profile excludes
`var/cache/ldconfig/aux-cache` from SquashFS because that generated cache records
build-filesystem identity; the runtime loader's `/etc/ld.so.cache` is retained.
It also passes xorriso's `--set_all_file_dates` using `SOURCE_DATE_EPOCH`, since
the environment variable alone does not normalize every ISO directory timestamp.
These options are applied during construction, never by editing a finished ISO.
The profile's command functions are supported by the pinned ArchISO 91 root build
path; changing ArchISO or allowing non-root builds requires revalidating them.

## Disposable cloud validator

The optional `scripts/validate/host-builder.py` starts independent Arch cloud-image
overlays under **required KVM**, using 6 guest vCPUs, 8 GiB RAM and a sparse 36 GiB
disk. Sequential builds are the default on one outer Linux machine. The outer host needs
QEMU, OVMF, Python and `cloud-localds` (Ubuntu's `cloud-image-utils`).

Authenticate the official Arch cloud image before use. This run uses
`Arch-Linux-x86_64-cloudimg-20261001.604814.qcow2` and its detached signature from
[Arch's mirror](https://geo.mirror.pkgbuild.com/images/latest/), verified with the
public release key in the [Arch-boxes repository](https://github.com/archlinux/arch-boxes).
The verified primary fingerprint is
`1B9A16984A4E8CB448712D2AE0B78BF4326C6F8F`. Do not replace the dated image with an
unverified `latest` download when repeating a run.

Prepare a private host directory containing:

- `source.tar.xz`: the complete intended working tree under `operating-system/`,
  including uncommitted files, excluding build outputs and credentials;
- `arch-builder.sh`: the script from `scripts/validate/`;
- space for `repo/`, `repository-fingerprint.txt` and `evidence/` generated by A.

Record the source archive's SHA256 before and after transfer. A Git revision alone
does not identify uncommitted source. Use a clean revision for qualification and record it with the archive hash.
For restricted browser-terminal transfers, use bounded chunks and verify the
assembled checksum rather than relying on a large paste completing successfully.

Example, using the paths on the disposable Ubuntu validator:

```sh
sudo python3 scripts/validate/host-builder.py A \
  --base /home/ubuntu/phase0-vms/arch-base.qcow2 \
  --share /home/ubuntu/phase0-share \
  --output /home/ubuntu/phase0-vms/builder-A \
  --ovmf-code /usr/share/OVMF/OVMF_CODE_4M.fd \
  --ovmf-vars /usr/share/OVMF/OVMF_VARS_4M.fd
```

The guest mounts the private 9p share, switches its **whole** package set to the
project's archive, installs the builder dependencies and runs the existing package
and ISO commands. A creates a disposable one-day signing key inside the guest and
exports only its public key/repository. B independently prepares/builds the platform
package but uses A's identical signed repository bytes for ISO assembly. This keeps
signature timestamps from becoming an accidental difference in the ISO inputs.

The generated build-only pacman configuration uses curl with three retries,
a 20-second connection timeout and a 300-second transfer limit per attempt.
This handles archive stalls that caused pacman's default low-speed timeout to
abort two real runs. TLS verification and package/database signature requirements
remain enabled. The live image retains pacman's normal downloader configuration.

Wait for `evidence/A/exit-code` and guest shutdown before launching B with a new
output directory and label `B`. No public ports, SSH credentials or outer-host
package-manager replacement are involved. Failed attempts require a new overlay;
preserve their evidence under a separate attempt directory before retrying. Never
delete or overwrite the base image or an unrelated VM.

An optional `package-cache/` beside the source archive may contain only upstream
package archives and their signatures. Each fresh builder copies it into its own
cache, then performs normal pacman verification. Keep custom packages out of that
cache and record its hashes. Sharing immutable downloads does not share an installed
root, build tree, signing key or pacman database between builders.

To overlap downloads after A has finished publishing `repo/` and its fingerprint,
B may use `--memory-mib 6144` alongside A's 8192 MiB. Both still start from separate
clean overlays and consume the identical source archive and signed repository.
Record the resource difference and keep their combined maximum below usable host
RAM. Do not add a live desktop guest until one builder has stopped.

The scripts are validation automation, not an installer. Cloud-init powers off the
guest after the attempt; the **outer host must still be paused or deleted** after
exporting evidence. See `docs/validation.md` for which steps have actually passed.
