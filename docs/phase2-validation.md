# Phase 2 destructive validation harness

This document began as the validation branch handoff. The integrated product and
actual acceptance results are recorded in [Phase 2 integration](phase2-integration.md).
The branch history below describes the original infrastructure work. No Phase 1
acceptance claim is changed.

Base: `aad4409b258a3aa86049b3f737568feaea49d790`. Branch: `phase2/validation`.
Inspected integration inputs:

* Transactions: `86acd45eecbbe35a6bd833ac83fdd5999434a83f`.
* Snapshots: `e74d1570cfc677f658803fd1e1af5a43951fa3b3`.

The transaction branch deliberately uses `UnavailableSnapshots`; nonempty updates
stop before mutation. The snapshot branch supplies offline rollback, not an
automatic fallback boot entry. Combining their source files alone is insufficient.
The harness must fail until the product integration described below is complete.

## Topology and isolation

One Linux outer host runs one disposable nested KVM guest at a time: Q35, host CPU,
4 vCPUs, 4096 MiB RAM, virtio disk/GPU/network, UEFI with copied OVMF variables.
The harness imports the Phase 1 `install-smoke.py` QEMU configuration and uses the
existing private `qmp.py`. No public console, forwarded port, SSH server or key is
created. Linux Python 3.11+, QEMU, `qemu-img`, matching ordinary OVMF CODE/VARS,
and `/dev/kvm` are required. No TCG fallback is allowed.

Each invocation owns a foreground QEMU child and a new mode-0700 output directory.
Cleanup terminates only that child, never a process found through an old PID file.
Failures, timeouts, Ctrl-C and SIGTERM retain logs and the overlay. An uncatchable
outer-host kill still requires operator cleanup. Commands and guest readiness have
bounded deadlines; QMP has a deadline, shutdown gets 60 seconds and forced cleanup
gets two 10-second waits. Hashing and evidence export scale with artifact size.

The guest uses a test-only virtio serial port for command requests and replies.
Every reply must match a fresh request ID. The guest runs Bash with `-euo pipefail`,
returns the real exit status and boot ID, and kills the command process group on
timeout. Output is limited to 4 MiB per command; truncation is a failure. The outer
runner stores commands as evidence but never executes fixture commands on the host.
The only host share is read-only and contains explicitly selected test files.

`phase2-guest.py` must never enter a production package or ISO. Its setup writes a
root command service **only into a disposable validation baseline**. Setup and
fault injection require root, KVM detection and the dedicated virtio port. The
service activates only when that port exists. The baseline is a test artifact,
not a distributable installation image.

## Installation and baseline creation

Use short absolute paths on the Linux host, without commas or whitespace. Unix
socket paths must fit within 104 bytes. Set the following to real inputs:

```sh
export ISO=/srv/astraeus/installed-and-recovery.iso
export OVMF_CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
export OVMF_VARS=/usr/share/OVMF/OVMF_VARS_4M.fd
export SOURCE_COMMIT=aad4409b258a3aa86049b3f737568feaea49d790
```

For integrated acceptance, replace `SOURCE_COMMIT` with the actual integrated
build commit. Repeat `--source-commit FULL_SHA` for additional input commits. Use
the integrated CLI in both the installed image and trusted recovery ISO. Keep
the ISO's build manifests and signature evidence alongside the test evidence.

```sh
python3 scripts/validate/phase2.py install --output /srv/vm/install \
  --iso "$ISO" --ovmf-code "$OVMF_CODE" --ovmf-vars "$OVMF_VARS" \
  --source-commit "$SOURCE_COMMIT" --timeout 3600
```

This creates a blank 32 GiB qcow2 disk and fresh firmware variables. Complete the
native Calamares workflow through the emitted QMP socket, then shut down. The
installation window is bounded by `--timeout`. Exit zero here means only that the
installer VM ended normally: `installation_accepted` remains false. It does not
automate Calamares clicks or count the completion screen as installation acceptance.
The existing Phase 1 installation launcher remains usable as an alternative.

Create a candidate baseline from that **stopped** installation, or from a retained
known-good Phase 1 installation directory containing `disk.qcow2` and `vars.fd`:

```sh
python3 scripts/validate/phase2.py baseline --source /srv/vm/install \
  --output /srv/vm/base-luks --iso "$ISO" --ovmf-code "$OVMF_CODE" \
  --source-commit "$SOURCE_COMMIT" --encryption LUKS2 --timeout 1800
```

`qemu-img convert` flattens the source into an independent candidate without
writing to the source. QEMU image locking rejects a running source. The candidate
cold-boots without ISO. Through private QMP, unlock LUKS and log into Plasma. In
the installed desktop terminal:

```sh
sudo mkdir -p /mnt/astraeus-validation
sudo mount -t 9p -o trans=virtio,version=9p2000.L,ro acceptance /mnt/astraeus-validation
bash /mnt/astraeus-validation/installed-smoke.sh LUKS2
# Use the actual health.log path printed by the previous command.
sudo python3 /mnt/astraeus-validation/phase2-guest.py setup "$HOME/installation-evidence.ACTUAL/health.log"
```

The runner checks the exact installed acceptance line and observed Btrfs, LUKS2,
UEFI, package database and failed-unit state. It shuts down, cold-boots again
without ISO, requires a different kernel boot ID and repeats root health checks.
Unlock the second boot through QMP as usual. Desktop/audio acceptance is the
existing user-session script, not the root agent's readiness marker. If refreshing
full Phase 1 qualification, rerun the desktop script after the second login too.

Only after clean shutdown does the runner write `baseline.json` with disk and
firmware SHA256 values and make both files read-only. A missing manifest, failed
acceptance or changed hash is refused by the scenario runner. Baseline creation
also records the original source disk/firmware hashes and path. Existing read-only
baselines are never opened as writable VM disks.

For every destructive test, `qemu-img create -f qcow2 -F qcow2 -b BASE OVERLAY`
creates a fresh overlay and firmware is copied separately. Both baseline hashes
are checked again after cleanup. Keep the baseline in a directory ordinary test
operators cannot modify; read-only modes are not a security boundary against root.
Never run two writers against the same output directory.

## Signed package fixture

`tests/fixtures/phase2/PKGBUILD` builds `astraeus-validation-fixture` version 1 or 2.
Version 1 owns `/etc/astraeus-test-state` containing `version-A`; version 2 owns
the same path containing `version-B`. Build separate copies, changing only
`pkgver=1` to `pkgver=2` in the second copy. Use the normal pinned Arch builder,
`makepkg --sign --key "$KEY"`, and `scripts/publish-repo.sh` from Phase 1. Do not
disable package or database signature checks. Keep private signing material out
of the fixture share, guest and evidence.

Prepare this in a **disposable candidate**, before sealing the baseline:

1. Install the signed version 1 fixture, using the trusted validation key.
2. Copy the signed version 2 repository to
   `/var/lib/astraeus-validation/repo` inside the guest. The existing publisher
   creates a `distro.db`; point this disposable guest's `[distro]` repository at
   `file:///var/lib/astraeus-validation/repo` with signatures still required.
   Preserve the installed integrated `distroctl`; the fixture repo need not
   contain another version of it. Keep upstream repositories pinned.
3. Refresh the guest's sync databases normally. Confirm the dry-run plans the
   fixture upgrade to `2-1`, then run installed acceptance and seal the baseline.

Preparation is deliberate test setup, not a bypass in production update code.
The scenario adapter refuses a baseline without version 1 or a plan without the
version 2 upgrade. Package ownership proves that rollback restores the package DB
with `/etc`, rather than merely rewriting an unowned marker.

## Acceptance scenarios

All commands use a new output directory. Copy `tests/fixtures/phase2` to a private
fixture directory if implementing missing integration actions, then pass
`--fixtures /absolute/path/to/fixtures`. Its contents are copied into evidence and
hashed; include no secrets, personal files or symlinks to such files.

```sh
python3 scripts/validate/phase2.py run --base /srv/vm/base-luks \
  --output /srv/vm/success-01 --iso "$ISO" --ovmf-code "$OVMF_CODE" \
  --source-commit "$SOURCE_COMMIT" --scenario update-success
```

Repeat with the following scenario/fault combinations:

| Scenario | Behavior and required result |
| --- | --- |
| `update-success` | New correlated pre-snapshot before applying; nonempty package plan; exact resulting package map; version B; live checks; disk-only reboot; product boot confirmation; `succeeded` |
| `update-failure --fault package` | Targeted pacman PreTransaction hook aborts fixture upgrade; `rollback_required`; offline restore; version A and original package set after reboot |
| `update-failure --fault health` | Targeted PostTransaction hook starts a deliberately failing oneshot unit; structured health must reject it; rollback and clean reboot |
| `update-failure --fault service` | Targeted PostTransaction hook masks/stops NetworkManager; health must reject it; rollback restores the service configuration |
| `rejected-update --fault payload` | Corrupt only the guest's signed fixture archive and remove its cached copy; download/verification failure; no snapshot or package mutation; unchanged system after reboot |
| `rejected-update --fault space` | Fill a 16 MiB tmpfs mounted over the guest package cache; explicit insufficient-space refusal; unchanged system after reboot |
| `rollback` | Complete a good live update, then restore its pre-snapshot offline and verify version A after reboot |
| `interruption` | A targeted PostTransaction hook writes/syncs a barrier and blocks; require changed package state and version B while the journal remains `applying`, plus the pre-snapshot; kill only the owned QEMU child; boot; capture unreconciled state; reconcile to `rollback_required`; recover offline |
| `boot-recovery` | Good live update, then overwrite its active UKI only in the overlay; failed boot window; recovery ISO restore; disk-only reboot and original system checks |

The boot-failure window is an expected absence of readiness only after explicit
UKI damage. A clean QEMU exit is also accepted at this stage only when its serial
log shows systemd-boot's firmware-setup path: `-no-reboot` turns that firmware
reset into exit 0. The runner records the exit status and rejects crashes or
unexplained exits. Neither failure path can make the scenario pass: successful offline recovery, a new
boot, restored package/root state and persistent data are still mandatory. This
is a recovery-media test; it does not prove an automatic fallback entry exists.

Package failure, interruption, service and health hooks target only the fixture's
upgrade. No global pacman behavior is changed. Hooks are test setup stored before
the snapshot, so they may be present after rollback. The run ends there; discard
the overlay rather than using it for a second scenario. Runtime fault effects
are applied after snapshot creation where appropriate.

Before updating, each run captures system/package state and writes a random marker
under `/home/astraeus-validation`. After snapshot creation it writes a *different*
marker there. Rollback must restore root version A and the complete original
package/version map while keeping this later home marker. It also reads version A
directly from the pre-snapshot. Transaction IDs, snapshot transaction references,
read-only status and event ordering must agree. A stale snapshot or an empty
update cannot pass. Every final path requires Btrfs, the requested encryption,
a healthy package database and zero failed system units.

`LUKS2` is the default and must be included in the final acceptance matrix.
`--encryption none` permits an additional plain baseline/run but does not replace
encrypted rollback acceptance.

## Offline recovery interaction

The same overlay and firmware are restarted with the supplied recovery ISO.
Installed subvolumes must remain unmounted. Use QMP to open a live terminal:

```sh
sudo mkdir -p /mnt/astraeus-validation
sudo mount -t 9p -o trans=virtio,version=9p2000.L,ro acceptance /mnt/astraeus-validation
# Encrypted guests only: enter the disposable passphrase interactively.
sudo cryptsetup open /dev/vda2 root
sudo python3 /mnt/astraeus-validation/phase2-guest.py serve
```

The checked-in recovery adapter assumes the deterministic Phase 1 erase-disk
layout: `/dev/vda1` ESP, `/dev/vda2` Btrfs or LUKS2, mapper name `root`. It mounts
top-level ID 5 and the ESP, then calls the product's dry-run and execute rollback
commands. It never implements Btrfs restore itself. The product validates UUIDs,
layout, target and UKI binding; the adapter unmounts its mounts afterward.
The runner then shuts down the recovery guest and boots the disk without ISO.

Baseline health evidence justifies explicitly marking the correlated pre-update
snapshot known-good through the product CLI before recovery. This does not mark
the updated candidate good. Recovery still requires transaction finalization
after the restored system passes its boot checks.

## Integration responsibilities

The checked-in adapter calls real commands from the two inspected branches:
`update --dry-run --json`, `update`, `history --json`, `snapshot list --json`,
`snapshot mark`, and offline `rollback --dry-run/--execute` with `--json`.

Chat 1 integration must connect `SnapshotBackend` to the real manager, retain the
returned snapshot ID in transaction records, respect the snapshot owner's lock,
and supply product-owned boot confirmation and verified rollback finalization.
Implement the adapter actions `confirm-boot TRANSACTION_ID` and
`finalize-rollback TRANSACTION_ID` against those eventual public interfaces.
The integration branch connects them to `distroctl confirm-boot` and `distroctl finalize-rollback`; a missing product command is a hard test failure. Never implement them by
editing SQLite records or returning canned success. The runner independently
reads history and requires `succeeded` or `rolled_back` for the same transaction.
Interruption reconciliation invokes the native updater; it must preserve failure
history and refuse unsafe replay.

Chat 2 integration must preserve root/package DB plus the UKI before mutation,
return a durable snapshot ID correlated with the transaction ID, expose schema-1
catalog metadata and provide the offline recovery binary on the trusted ISO.
The existing layout and known-good requirement are used directly. Changes to the
metadata layout or JSON schema require updating this harness, not silently
accepting unobserved fields. Automatic fallback boot and interrupted rollback
resume remain separate product work.

## Evidence, secrets and cleanup

Each new output directory contains:

* `inputs.json`: requested source commits, actual harness commit/dirty flag, ISO
  and OVMF CODE paths/hashes, QEMU version and hashes of guest/fixture files.
* `source-installation.json` or `baseline-reference.json`: source disk and firmware
  identity; `baseline.json` exists only for a sealed, accepted baseline.
* `boot-N/`: exact QEMU argument array, process/timestamps, serial and QEMU logs,
  QMP status/KVM/block replies, individually timestamped guest command replies,
  shutdown/reboot/power-cut records. Credentials never enter these commands.
* `before.json`, `after-update.json`, `after-reboot.json`, `after-rollback.json`,
  interruption/rejection variants and best-effort failure diagnostics: transaction
  output, catalog, distroctl status, failed units, mounts/subvolumes, package list,
  DB checks, boot state, bounded journal/transaction logs and sentinel data.
* `result.json`: start/end time, scenario, requested encryption, final boolean
  pass/fail and error/cleanup details. Errors never turn into pass through timeout.
* `evidence-sha256.json`: hashes of retained regular evidence files, excluding
  large writable disk/firmware files. Canonical baseline hashes live in its manifest.

Keep installer screenshots/logs and original ISO build manifests too. Use the
existing QMP screenshot command for visual evidence. Do not include passwords in
command arguments, adapter files, shell history or screen captures. Use the
existing `qmp.py --text-stdin` for disposable credentials, with terminal echo
disabled at the outer interactive transport as documented in Phase 1. The harness
does not log environment variables or command stdin. Arbitrary fixture stdout
cannot be reliably redacted: adapters must not print secrets.

For an evidence-only bundle after the runner exits:

```sh
tar --exclude='*.qcow2' --exclude='*.fd' --exclude='*.sock' \
  -C /srv/vm/success-01 -cJf /srv/vm/success-01-evidence.tar.xz .
```

Retain failed overlays for diagnosis as needed. Once logs are exported and the
owned QEMU process is confirmed stopped, remove only that run's `disk.qcow2` and
`vars.fd`, or its explicitly selected run directory. No automatic recursive
deletion or canonical baseline cleanup is performed. A reset means a new run
directory and a fresh overlay, not reusing a partial failure.

## Freestyle and cost

No Freestyle resources were used or changed while building this infrastructure.
For integrated acceptance, reuse one authorized outer VM with nested KVM, enough
RAM for the outer OS plus the 4 GiB guest, and room for the ISO, canonical disk and
one overlay. Guest disk sizes are sparse, not host storage reservations. Check
outer free space before each run and retain a host reserve. The bounded cache
fault avoids exhausting the outer filesystem; root/ESP disk-full qualification
needs a separately budgeted disposable disk and remains untested.

Run guests sequentially. Do not resize paid compute, modify plans/billing, or
touch unrelated VMs. Export evidence, verify all owned nested guests stopped,
then pause/delete only the authorized outer resource through its normal controls.
The local harness deliberately does not discover or control cloud resources.

## Harness checks and limits

```sh
python3 -m unittest discover -s tests -v
bash -n tests/fixtures/phase2/adapter.sh
bash -n tests/fixtures/phase2/PKGBUILD
python3 scripts/validate/phase2.py --help
```

Tests cover marker matching, modified baseline rejection, overlay arguments and
firmware isolation, stale/failed transactions, health/package/snapshot ordering,
QMP event/error/deadline handling, guest command status/pipeline failures, process
group timeout, output bounds, stale response rejection, failure artifacts,
shutdown cleanup and reboot identity. Linux exercises a real local Unix socket
and real Bash subprocesses; `qemu-img` enables an additional real overlay test.
These checks exercise the harness, not installed product acceptance.

Host checks: Windows 34 Python tests, 25 passed and nine platform/tool skips;
Linux passed all 34, including the real qcow2 overlay test with `qemu-img` 10.2.1.
The Linux tool and three shared-library dependencies were downloaded into ignored
`out/phase2-tools`, checked against the distribution package index's SHA512 values,
and extracted privately. No host packages were installed. Linux CI now installs
`qemu-utils` alongside its existing image test tools to keep that check enabled.
Windows also passed all 13 Rust tests, formatting and Clippy with warnings denied.
New and existing validation shell syntax checks passed. Logs are retained under
ignored `out/phase2/checks-{win32,linux}.log`.

No integrated ISO was
built, no baseline was sealed and no destructive installed scenario was run.
Manual Calamares, LUKS unlock and recovery-terminal setup remain required. A root
agent cannot certify Plasma/audio after each reboot; use the existing desktop
acceptance script for that additional gate. No production file was modified.
