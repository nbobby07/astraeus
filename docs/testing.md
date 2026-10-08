# Verification and acceptance

Phase 2 destructive VM workflows, integration hooks and evidence requirements
are in [Phase 2 validation infrastructure](phase2-validation.md). Host harness
tests do not establish installed update or rollback acceptance.

## Checks that run without an Arch builder

```sh
cargo fmt --all --check
cargo test --workspace --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
python3 -m unittest discover -s tests -v
python3 scripts/bootstrap.py verify-archive
bash -n scripts/publish-repo.sh
bash -n tests/boot/live-smoke.sh
bash -n distro/archiso/profiledef.sh.in
bash -n distro/packages/distroctl/PKGBUILD.in
```

Rust tests cover malformed/unknown configuration fields, schema and architecture
constraints, dates/epoch consistency, CLI JSON output, validation and unsupported
commands. Python tests cover template completion, security/boot policy, package
list consistency and source archive determinism despite changed filesystem mtimes.
The optional online check validates the saved repository database hashes and the
existence/version of selected packages. It is not a dependency-solving or boot test.

The QEMU command test rejects implicit KVM-to-TCG fallback. The private monitor
helper test verifies that asynchronous events, QMP errors and a closed connection
cannot be reported as command success. `scripts/validate/qmp.py` uses a local Unix
socket, so monitor access need not be exposed over a public network.

The generated-profile regression check verifies UTC, the US console keymap and a
masked `systemd-firstboot.service` on the ephemeral live image. Without these, the
first real boot blocked on a timezone prompt before SDDM could launch.

The same test checks that live-keyring creates its configured GPG directory before
calling pacman-key. Otherwise pacman-conf rejects the missing path and initialization
uses the wrong directory. It also checks that bounded archive retries apply only
to the build configuration and retain required repository signatures.

`test_reproducibility.py` uses real `mksquashfs` and `xorriso` binaries to build two
small images with different auxiliary-cache bytes and source-file timestamps. It
requires identical output bytes. Install `squashfs-tools` and `xorriso` to run it;
CI installs them explicitly. It skips on unsupported hosts and does not replace
the full independent ISO comparison.

Inspect serial logs with `tail -n 40 FILE | cat -v`, or read them as files. Raw
serial output can contain terminal control sequences and interactive setup UIs.
Keep the raw log for evidence, but do not replay those controls into a host shell.

For a remote browser-terminal run, use an outer-host transient systemd service
instead of relying on a background sudo command surviving terminal reconnection:

```sh
sudo systemd-run --unit=phase0-smoke --collect \
  --property=StandardOutput=append:/home/ubuntu/phase0-smoke.harness.log \
  --property=StandardError=append:/home/ubuntu/phase0-smoke.harness.log \
  /usr/bin/python3 -u /path/to/scripts/boot-smoke.py /path/to/test.iso \
  --ovmf-code /usr/share/OVMF/OVMF_CODE_4M.fd \
  --ovmf-vars /usr/share/OVMF/OVMF_VARS_4M.fd \
  --log /home/ubuntu/phase0-smoke.serial.log
```

Use fresh unit and log names for retries. A successful build requires the ISO,
checksum, resolved manifests and `BUILDER_A_SUCCESS` or `BUILDER_B_SUCCESS`, not
merely a zero exit-code file. Interrupted attempts are not accepted.

CI runs Rust/Python checks on Ubuntu and Windows, plus shell syntax checks on Ubuntu. A manual workflow dispatch
also checks the archive over HTTPS. It does not use signing secrets, privileged
runners or claim to build an ISO. The public repository records actual host-check runs in its Actions tab.
These checks do not replace the separate guest acceptance record.

## Phase 0 Linux acceptance

1. Build/test/sign the package with the pinned compiler using makepkg.
2. Build the signed custom repository, then the ISO from a fresh work directory.
3. Keep resolved package lists, source/repo fingerprints and ISO checksums.
4. Run the UEFI QEMU harness and retain a new serial log. Check
   `journalctl -u live-smoke.service` for guest-side evidence on failure.
5. Inspect Plasma Wayland, Ghostty/Konsole, keyboard, networking and audio manually.
6. Build again with identical signed inputs. Compare ISO and manifest hashes.
7. In a copied test repository, corrupt a package/signature and confirm that the
   publisher or package install fails. Use an unrelated fingerprint and confirm
   the builder refuses it. Do not run these negative tests against release inputs.

No Phase 0 completion declaration before real build and boot evidence. If ISO
hashes differ, byte reproducibility remains an open issue even when both boot.
Booting this image on bare metal is additional compatibility work, not established
by a virtio/QEMU pass.

## Phase 1 installation tests

The ordinary Rust checks also exercise hardware fixture normalization, missing
observations, malformed mount data, EFI UTF-16 decoding, encrypted/plain Btrfs
root detection and status/hardware JSON CLI output. Tests do not require root or
assume the host has Linux procfs. Python tests validate module ordering, exact
subvolume/mount definitions, account policy, encrypted/plain command lines,
crypttab mapper consistency, UKI inputs and ISO detachment during disk boots.

Hardware/status coverage also includes CPU socket/core topology and ARM model
fallbacks, available memory and overflow rejection, PCI model/vendor lookup,
partition capacity/transport/rotational inheritance without `slaves`, firmware
and multi-vendor VM fallbacks, distinct unavailable/unknown/IO diagnostics,
human-readable formatting, byte-valued JSON and exact CLI exit codes. Unix-only
fixtures use real sysfs-style PCI/DRM/block symlinks. Run the workspace tests on
Linux as well as Windows to exercise those symlinks. See [hardware](hardware.md)
for schema details and detection limits. These checks do not establish installer
or physical hardware acceptance.

Additional Bash syntax checks:

```sh
bash -n distro/packages/calamares/PKGBUILD
bash -n distro/installed/mkinitcpio.conf
bash -n distro/installed/linux.preset.in
bash -n tests/boot/installed-smoke.sh
```

On the Linux KVM validator, create independent clean disks for both scenarios:

```sh
python3 scripts/install-smoke.py install --iso /absolute/path/current.iso \
  --ovmf-code "$OVMF_CODE" --ovmf-vars "$OVMF_VARS" --output out/install-encrypted
```

Use `scripts/validate/qmp.py` with the emitted private monitor for screenshots,
mouse/keyboard interaction, installation cancellation, a wrong unlock attempt,
and normal Calamares installation. Test-only credentials stay disposable and out
of source/log files; use `qmp.py --text-stdin` to avoid credentials in command arguments.
Preserve the install summary, completion and boot screenshots,
Calamares log, `/var/log/installer/storage.json`, partition table and UKI inspection.

Shut down and quit that QEMU process, then cold boot the same disk without ISO:

```sh
python3 scripts/install-smoke.py boot --output out/install-encrypted \
  --ovmf-code "$OVMF_CODE" --run boot1
```

Unlock and log in at SDDM. In the installed user session run the acceptance script
from this source tree, transferred privately for testing:

```sh
bash installed-smoke.sh LUKS2
```

For a local transfer, pass `--test-share /absolute/path/test-scripts` at each
QEMU launch. Put only the acceptance script in that host directory. The share
is read-only. Mount it and run the script as the desktop user:

```sh
sudo mount -t 9p -o trans=virtio,version=9p2000.L,ro acceptance /mnt
bash /mnt/installed-smoke.sh LUKS2
```

Keep credentials in memory. When using Freestyle's interactive CLI to feed
stdin, disable terminal echo and wait for a readiness marker before transmitting
the credential; `--text-stdin` by itself cannot control an outer terminal's echo.

It runs `distroctl status`, `status --json`, `hardware` and `hardware --json` as
the installed desktop user. It checks the observed UKI/loader, Btrfs/encryption,
Plasma Wayland, network/DNS/HTTPS, audio services and failed units, retaining
both text/JSON command outputs and fstab.
Open Ghostty and Konsole manually. Shut down and cold boot again with `--run boot2`,
then repeat the same assertions. Repeat the complete process with a new output
directory and encryption disabled; pass `none` to its guest acceptance script.

`install-smoke.py` is a semi-automated launcher, not a substitute for Calamares
execution. It never calls installation successful. Test an undersized disk using
`--disk-gib 8` and confirm refusal before disk mutation. Cancel before the summary
commit. An interrupted-install test is optional and must use another disposable
disk. Do not reuse its partial result for acceptance. Neither source inspection,
unit tests nor a Calamares completion page qualifies Phase 1 without both installed
systems booting and surviving the second boot. Repeat full ISO A/B comparison.

## Phase 2 snapshot checks

The ordinary Rust/Python checks above include command fixtures and temporary
trees without mutating host root. Linux has an additional ignored test using
new 512 MiB Btrfs and 64 MiB FAT regular-file images:

```sh
cargo test -p distro-snapshots --locked --no-run
sudo env ASTRAEUS_LOOPBACK_TEST=1 cargo test -p distro-snapshots --locked \
  disposable_linux_btrfs_roundtrip -- --ignored --nocapture
```

Use the same Rust toolchain for sudo, or run the compiled test executable with
`ASTRAEUS_LOOPBACK_TEST=1` and the arguments
`--ignored --exact system::tests::disposable_linux_btrfs_roundtrip`.
Required tools: `mkfs.btrfs`, `btrfs`, `mkfs.vfat`, `mount`, `umount`, `findmnt`,
`sha256sum`, `sync`, loop devices and kernel Btrfs support. Formatters receive
only the test's newly created regular files. Both mounts are released before
fixture cleanup.

The test executor permits its isolated fixture in WSL/private namespaces;
production refuses these environments. Its synthetic PE UKI qualifies storage
and byte handling only. It passed on WSL2 6.6.114.1 with btrfs-progs 6.17.1 and
dosfstools 4.2. Real UEFI boots, plain/LUKS2 recovery and a verified mutation
interruption subsequently passed through the existing QEMU runner. See the
[Phase 2 acceptance record](phase2-integration.md) and
[snapshot policy and recovery](snapshots.md). ENOSPC, arbitrary power-cut points
and interrupted root/ESP rollback remain outside that qualification.

## Transaction and boot-confirmation tests

Phase 2 transaction tests run with the same workspace commands above on Windows
and Linux. They cover typed plans, pacman machine-output parsing, byte arithmetic,
SQLite schema/persistence/read-only history, locking, legal/illegal transitions,
missing snapshot integration, cancellation, interrupted restart recovery, package
and UKI failures, health aggregation, CLI dry-run presentation and history JSON.
Integration checks cover snapshot failure before package mutation, boot identity,
required health evidence, idempotent confirmation and rollback finalization.
Injected package/command backends never mutate the host package database.
Successful live execution in fixtures ends at `awaiting_boot`; it is not installed
update or rollback acceptance. The real installed scenarios are recorded in
[Phase 2 acceptance](phase2-integration.md). See [transactions](transactions.md)
for the product lifecycle.

`test_transactions_pacman.py` additionally exercises real pacman when available:
temporary local/sync databases, dependency resolution, epoch versions, exact
print-format fields, inherited signature policy and before/after file equality.
It never installs packages or touches the host database. An extracted pacman can
be selected with `ASTRAEUS_TEST_PACMAN` and `ASTRAEUS_TEST_PACMAN_CONF`; otherwise
the check skips when those tools are absent.

| Boundary | Required evidence before broadening implementation |
| --- | --- |
| Configuration/planning | Fixture desired/current states, deterministic plans, dry-run side-effect checks |
| Hardware | Captured proc/sysfs fixtures for AMD/Intel/NVIDIA/hybrid and missing/unknown data |
| Transactions | Explicit phase transitions, crash/restart recovery and pacman lock contention |
| Snapshots/rollback | Disposable Btrfs VM disks; package DB/root/boot-generation consistency |
| UKI/Secure Boot | Enforcing OVMF, wrong signatures, damaged artifact and fallback boot |
| Diagnostics | Structured outcomes including unknown, unsupported and failed checks |
| Performance | Real baselines, thermal/power context, safe policy restoration and measured gains |

No fake benchmarks or success values substitute for these checks. The eventual
v0.1 gate includes installation, update, deliberate package failure, rollback and
successful reboot while preserving user documents and failure logs.
