# Phase 1 validation

**PHASE 1 NOT YET VALIDATED.** Implementation and clean-builder validation are
in progress. The Phase 0 results below apply to their recorded source/artifacts;
they do not establish installed-system boot or reproducibility for Phase 1.

Baseline inspected before edits: clean `main` at
`8dcb2cdf8d9faac97c4ae3367a4d8794a95224ea`. Architecture, building, testing and
validation documentation and the complete profile/build pipeline were read.
Rust formatting, two baseline tests and Clippy passed. Python baseline: Windows
5 passed/3 Linux skips; WSL 7 passed/1 image-tool skip. Both archived database
hashes and 50 upstream package versions passed the online check.

The hardware/status commit `f961158de9461a16e09abfe1282ae2ce2b48cae0` was
reviewed and cherry-picked as `08b6113` from a clean tree. It was based directly
on the current core checkpoint and had no conflicting installer changes.
After integration, Linux passed 15 Rust tests, formatting, Clippy with warnings
denied and all 14 Python tests, including native image-tool byte comparison.
Windows passed 13 Rust tests and ten Python tests with four Unix/Linux skips.
The installed smoke script now runs all four status/hardware text/JSON commands.
Nine Bash files passed syntax checks before integration; the changed installed
smoke script also passed after integration.
The expanded locked package union contains 73 upstream packages and retains the
same Phase 0 database hashes, ArchISO version, compiler and snapshot date.

The existing paused Freestyle validator was resumed, with no new outer VM. The
user authorized official CLI account access. Initial browser transfer failed
partway and is not accepted evidence. Clean builders A6/B6 both exited 0 and
produced byte-identical 3527460864-byte `astraeus-dev-0.1.0-dev-x86_64.iso` files:
SHA256 `e2aabf771b856a503f7acf396d73d8975b74cc42d1a1069db451b09f5d57dc9c`,
with `cmp` exit 0. Their source was clean commit
`ce749b58b00785636b6c9ce1d12c1b82e6114046`, 57556-byte archive SHA256
`69da31b0e5e4c1b9d8ddc764f08050b214670b8990df0e345e5c5dc4d1e16b5b`.
The A6 ISO reached Plasma Wayland and its live smoke success marker.
This pair predates the hardware merge and subsequent installer corrections and
does not qualify the final source.

Real Calamares interaction found two startup-branding fields missing (`slideshow`
and `style`), now supplied and covered by generated-profile tests. Installation
then created the six Btrfs subvolumes but payload mounting failed with ENOSPC:
loop setup through the live overlay copied the 1.5 GiB image into the 256 MiB
writable layer. Accessing the read-only ArchISO SquashFS path succeeded; the
source path and its regression check are corrected. The diagnostic retry uses
those corrections. Builder A7 was canceled after the payload defect was found;
it is not a successful build. Earlier A2/A3 failed or were canceled at an image
timestamp conflict; clearing ambient SOURCE_DATE_EPOCH for the explicit-time
payload compressor fixed it and has a native byte-comparison regression test.
A5 failed during initial archive transfer; the builder now uses the same bounded
curl retries/timeouts as the image build.

The corrected diagnostic Calamares installation completed. Its initial cold boot
fell through to PXE despite valid GPT/ESP flags and boot files; an explicit QEMU
virtio disk boot priority reached systemd-boot and the UKI. A wrong LUKS passphrase
was rejected, and the correct passphrase unlocked root. Boot then found fstab
still naming Calamares's temporary mapper. Finalization now changes all six mount
sources to `/dev/mapper/root`, matching crypttab and the embedded command line;
the regression covers all six mounts, idempotence and untouched ESP/comments.
The diagnostic disk is being repaired to check the remaining boot path. It is
not a fresh final-source installation or accepted Phase 1 system.

Final merged-source ISO reproduction, encrypted/plain installed boots, SDDM
login, installed-session health and second boots remain unaccepted. No installed
success is inferred from WSL fixtures, live boot or partial Calamares progress.

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

- VM: `astraeus-phase0-validator`, ID `vm-cc9d56de23154de7a22492f24dfaae27`.
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
