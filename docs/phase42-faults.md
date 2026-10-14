# Phase 4.2 fault acceptance

`scripts/validate/phase42-faults.py` exercises eight destructive scenarios in
separate disposable KVM overlays. It requires a sealed fresh Phase 4.2 baseline,
the exact runtime candidate source and binary hashes, and a signed RAM-verified
recovery image made for that baseline by `phase42-recovery.py`.

Initial VM installation uses the existing SetupMode bootstrap. The baseline records
actual `SecureBoot` and `SetupMode` EFI variables before the first partition write
as `installation_firmware`; this is not an enforcing installer acceptance claim.
The fault report carries that observation separately from
`management_firmware_required` (`SecureBoot=true`, `SetupMode=false`). Both accepted
installed baseline boots and every management/recovery scenario require enforcement.
Missing or contradictory baseline provenance is refused.

The runner never uses a host block device, changes firmware trust, removes a live
package lock, or replays a failed package transaction. The installed disk and
firmware variables are copies or overlays; the recovery disk is attached read-only
as a separate USB device. Baseline and recovery-image hashes are checked again
after execution.

## Executed scenarios

`metadata` first checks a true no-op. It then adds an already installed package to
the saved explicit choices, requires an empty package change list, and applies
through the actual systemd worker. It checks paired snapshots, regenerated boot
artifacts, same-boot confirmation refusal, and successful confirmation after a new
boot. It restores the pre-transaction snapshot from signed recovery media and
checks configuration, ownership, installation reasons, the complete package map,
filesystem identities and a user-owned home sentinel. Before finalizing rollback,
it briefly installs the internally consistent *wrong* management state while
package versions remain identical and requires finalization to refuse it. This
negative control first verifies the real restore and restores exactly the bytes
it changed; it cannot repair a failed rollback to manufacture a pass.

`interruption` adds a temporary PostTransaction hook for one initially absent
approved package. The hook waits after the real libalpm package commit, while the
durable transaction is still Applying. The runner verifies the coordinator owns
the writable native lock descriptor and a competing libalpm transaction cannot
acquire that same lock. It sends SIGKILL to the actual systemd service control
group, records the exit evidence, and requires a durable interrupted
`rollback_required` record. Replaying its request must fail without mutation.
Signed offline recovery then restores the package database and all management
state, restores the snapshot's lock-free package database, preserves home
data, and requires explicit rollback finalization after a new installed boot.
The temporary hook is test instrumentation retained in this disposable overlay.

Before the install, this scenario submits a freshly reviewed true no-op through
a deliberately symlinked request directory. Staging must initially be absent;
the target is a new private evidence directory, never an existing request store.
It requires a trusted-path refusal and unchanged request/receipt/history
inventories and package/management state. Cleanup removes only the exact symlink
created by the fixture. Any unexpected target writes are retained as failed
evidence. While the genuine post-commit barrier holds, a second submission must
be refused explicitly for the active operation. The original worker PID, kernel
start tick, unit, operation, inventories and system state must stay unchanged.

`abandoned` injects the documented durable boundary after staging a queued
submission but before starting its unit. Its receipt explicitly calls this
`injected-durable-submit-boundary`; it does not claim a submitting process was
actually killed. An ordinary user must see the old, inactive request as failed.
A newly submitted reviewed no-op must finish, and a delayed worker for the old ID
must fail the current-request identity check. Inspection and replacement must not
change packages, reasons, configuration, ownership or home data.

This scenario first verifies a real systemd start failure. On an idle guest it
creates an exclusive runtime mask for `astraeus-apply@.service` and submits a
reviewed true no-op. The actual start must fail because the unit is masked, with
one publicly inspectable Failed receipt, no transaction, unchanged packages and
management state, and refused replay. Its `finally` path removes only that exact
owned runtime mask and reloads systemd. Existing overrides are never changed.
The submission fixtures save success or failure records under the disposable
guest's `/var/log/astraeus/phase42-submission-*` directories.

`failed-hook` uses a real PreTransaction hook with `AbortOnFail` and a durable
marker tied to the actual worker. It requires the native hook error, unchanged
packages and management state, a retained pre-snapshot and recovery-required
history. It then checks replay refusal and performs signed offline rollback.

`signing-failure` moves only the disposable guest's signing key away from its
configured path in a PostTransaction hook, after the protected pre-snapshot exists.
The key is neither read nor exported. The runner requires real package and
management changes, an actual signing-provider refusal, failed boot regeneration,
and no published post-snapshot or successful confirmation. Offline recovery must
restore the previous packages, metadata and valid signing identity.

`root-space`, `cache-space` and `esp-space` require actual available space below
the reviewed native policy budget. Cache uses the existing bounded 16 MiB tmpfs
fixture. Root uses direct Btrfs `fallocate` reservation without data writes; it
does not use `posix_fallocate`, whose fallback can write zeros. ESP writes at most
1 GiB in a dedicated fixture file. Each case requires at least 4 GiB of extra host
headroom, caps observed overlay growth, proves the exact capacity preflight
refusal before snapshots or mutation, removes only its owned fixture, and reboots
to prove the failed transaction was not replayed. Root and cache normally share
one Btrfs filesystem; the cache fixture also exercises the distinct cache-path
check without exhausting the shared root.

## Inputs and operation

Choose an initially absent small repository package for `--package`. Choose an
already installed package that is not yet in `configuration.packages` for
`--metadata-package`; a package supplied by a gaming feature is suitable. These
conditions are checked inside the actual candidate guest. Example names below
are placeholders until the candidate inventory confirms them.

```sh
python3 scripts/validate/phase42-faults.py run \
  --base /home/ubuntu/p42/bp --output /home/ubuntu/p42/fp1 \
  --ovmf-code /usr/share/OVMF/OVMF_CODE_4M.secboot.fd \
  --recovery-image /home/ubuntu/p42/rp/recovery.img \
  --recovery-manifest /home/ubuntu/p42/rp/manifest.json \
  --source-commit FULL_RUNTIME_CANDIDATE_COMMIT \
  --harness-commit FULL_VALIDATION_HARNESS_COMMIT \
  --image-sha256 CANDIDATE_ISO_SHA256 \
  --distroctl-sha256 PACKAGED_DISTROCTL_SHA256 \
  --desktop-sha256 PACKAGED_DESKTOP_SHA256 \
  --encryption none --user tester --package hello --metadata-package mangohud
```

`--scenario` runs any one of the named scenarios. On a space-constrained validator,
run one scenario at a time. Export and verify the thin evidence before retiring
that successful run's owned overlay and VARS. Never export disks containing test
private keys, or delete sealed baselines and recovery media. The default `all`
retains every overlay and therefore requires substantially more storage.
A rerun requires a new output directory. LUKS2 uses a separately sealed
encrypted baseline and its own matching owner-signed recovery image. Credentials
are entered through the existing private QMP console, never command arguments
or exported evidence. The runner writes `attention.json` when the signed live
recovery session needs its test command channel started or its LUKS mapping opened.
Only the disposable `/dev/vda2` may be unlocked; mounted filesystem UUIDs must
match the installed observation before any rollback command runs.

The runtime candidate commit is separate from the validation harness commit.
Every script, baseline, recovery image and command result is bound by hashes or
recorded in the evidence. Recovery must emit both the RAM-root verification marker
and the packaged live-desktop smoke marker before the runner proceeds. Live and
installed coordinators must match the candidate binary hash. Firmware must remain
SecureBoot=1 and SetupMode=0 throughout.

## Reporting limits

Rows become PASS only after the corresponding assertions execute. Exceptions mark
the active row FAIL, leave `requested_run_passed` false, stop only the QEMU child
owned by this invocation, and preserve the evidence and damaged overlay. A fully
successful invocation sets `requested_run_passed`; `qualified` and
`physical_hardware_qualified` stay false. GUI/polkit interaction, image repeatability,
recovery refusal tests and physical GPU support need their own evidence.

`python3 -m unittest discover -s tests -p test_phase42_faults.py -v` checks the
adapter and guards without booting a guest. Unit results do not close any runtime
acceptance gate. No guest run is implied by the presence of this harness.
On Linux root, `ASTRAEUS_CAPACITY_LOOPBACK=1` additionally checks the direct Btrfs
reservation against a fresh sparse 1 GiB loopback filesystem, including restored
capacity and a 64 MiB bound on outer-image growth. It uses no existing block device.
