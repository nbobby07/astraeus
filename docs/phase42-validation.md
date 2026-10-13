# Phase 4.2 candidate validation

`scripts/validate/phase42.py` extends the existing Phase 2 KVM/guest-command
runner for the managed-package lifecycle. It does not qualify an older installed
baseline as the new product. Every run requires a sealed **freshly installed
candidate** baseline whose source commit, ISO digest, firmware digest and
encryption mode match the requested inputs. Both installed distroctl and native
desktop binaries must match hashes independently extracted from the new packages.

Run the lifecycle once on plain Btrfs and once on LUKS2/Btrfs. Each invocation
creates a fresh overlay and copies firmware variables, preserving the sealed
baseline. The existing installed-smoke and Phase 2 baseline procedure must run
before sealing those inputs. Encrypted boots use the existing private QMP unlock
workflow; test credentials must not appear in process arguments or exported logs.

`scripts/validate/phase42-baseline.py` provides the automated fresh-install route.
It creates a blank disk, unpacks this candidate's installer payload and calls its
shipped provisioning code. It requires exact candidate identities, a separate
private directory, fresh firmware variables, and two enforcing boots with an
authenticated SDDM Wayland session before sealing the baseline. See its `--help`
for the firmware and private QMP inputs. Its receipt explicitly records
`calamares_ui: false`; it does not claim a new Calamares UI test.
Initial provisioning uses the existing SetupMode path. The recorded enrollment
step precedes every management and recovery acceptance test.

```sh
python3 scripts/validate/phase42.py run \
  --base /private/candidate-plain --output /private/p42-plain-run1 \
  --ovmf-code /usr/share/OVMF/OVMF_CODE_4M.secboot.fd --secure-boot \
  --source-commit FULL_CANDIDATE_COMMIT --image-sha256 CANDIDATE_ISO_SHA256 \
  --distroctl-sha256 PACKAGED_DISTROCTL_SHA256 --desktop-sha256 PACKAGED_DESKTOP_SHA256 \
  --encryption none --package hello --user YOUR_DISPOSABLE_INSTALLED_USER
```

Choose a small, available, initially absent, unprotected package from the approved
pinned repositories. `hello` is an example, not an assertion that it exists in the
active snapshot. The runner verifies availability before any operation. Phase 4.2
acceptance requires `--secure-boot` with the enrolled baseline's recorded Secure
Boot firmware CODE. The runner never enrolls or replaces keys.

The implemented path records ordinary-user observations, rejected configurations,
direct unprivileged submission refusal, stale-plan rejection, complete install
planning, the real root systemd worker, snapshots before mutation, pending-boot
blocking, a verified reboot, saved configuration, removal, a second verified
reboot, retained transaction/snapshot history and a home-data sentinel.

Every guest command has its actual exit code/output and boot ID recorded by the
existing runner. Matrix rows are marked PASS only after their assertions finish.
Interruption records a failure on the active gate, preserves evidence, terminates
only this invocation's QEMU child, and rechecks baseline hashes. Output directories
are exclusive; reruns require a new path. An interrupted mutation can require
offline recovery inside its disposable overlay, and is never silently replayed.

The matrix also lists the broader required gates: both fresh installation modes,
independent clean-image equality, live-session refusal, dependency ownership,
conflicts/providers, signature/provenance negatives, protected-package refusals,
worker interruption, hooks/space failures, offline rollback, real GUI/polkit use,
GUI close/crash survival, enforcing signed generations and absence of private
keys in the image. Those remain **NOT RUN** in this focused lifecycle runner until
their actual separate evidence is collected. A successful lifecycle process sets
`requested_run_passed`; it never sets `qualified` or physical hardware support.
Root CLI success is not evidence that a polkit dialog or native GUI worked.

Generate an entirely unexecuted gate inventory with:

```sh
python3 scripts/validate/phase42.py matrix --output /private/phase42-matrix.json
```

Host unit tests check the adapter, quoting, candidate guards and reporting rules.
They do not run an installed OS and cannot close any runtime acceptance gate.
