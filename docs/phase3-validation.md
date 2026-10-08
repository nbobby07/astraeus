# Phase 3 enforcing Secure Boot validation

Branch: `phase3/validation`. Base: `6a8fda25d25df74215ed0bbe06b97804e053d950`.
This branch owns fixtures, QEMU control, failure injection and evidence. It does
not change production signing, snapshots, transactions or generation selection.
See [the acceptance matrix](phase3-acceptance.md) for actual results and pending
integration gates. Phase 3 is not fully qualified.

## Reused infrastructure

`phase3.py` imports Phase 2's `VM`, overlay creation, baseline verification,
guest command channel, observations and health checks. `install-smoke.py` accepts
an optional `secure_boot=True`; Phase 2 defaults stay unchanged. Secure guests use
Q35/KVM, SMM, protected pflash, 4 vCPU and 4 GiB RAM. There is no TCG fallback,
public monitor, forwarded port or host EFI-variable access. Firmware CODE is
read-only. Every run copies VARS and creates a new qcow2 overlay. Baseline disk,
VARS and public fixture hashes are checked before and after firmware runs.

The Linux host needs Python 3.11+, working `/dev/kvm`, QEMU, matching Secure Boot
OVMF CODE and clean VARS, GCC/binutils, GNU EFI, OpenSSL, sbsigntool, mtools,
dosfstools, fdisk and python3-virt-firmware. On the reused Ubuntu validator:

```sh
sudo apt-get install python3-virt-firmware sbsigntool gnu-efi mtools dosfstools fdisk
```

Run QEMU as an account permitted to open `/dev/kvm`. The existing validator needs
root for this. Use short absolute paths without spaces or commas. Commands and
guest readiness are bounded; SIGTERM/interrupt cleanup stops only the owned child
and retains failed attempts, logs and disks. A host kill still needs operator cleanup.

## Disposable enrollment and firmware proof

```sh
SRC=/home/ubuntu/p3/src
BASE=6a8fda25d25df74215ed0bbe06b97804e053d950
CODE=/usr/share/OVMF/OVMF_CODE_4M.secboot.fd
VARS=/usr/share/OVMF/OVMF_VARS_4M.fd
sudo python3 "$SRC/scripts/validate/phase3.py" fixtures \
  --output /home/ubuntu/p3/firmware-base \
  --private-keys /home/ubuntu/p3-private \
  --ovmf-code "$CODE" --ovmf-vars "$VARS" --source-commit "$BASE"
sudo python3 "$SRC/scripts/validate/phase3.py" firmware \
  --output /home/ubuntu/p3/firmware-run --base /home/ubuntu/p3/firmware-base \
  --ovmf-code "$CODE" --source-commit "$BASE" --timeout 120
```

Output directories must be new. Private keys are generated outside both the
checkout and public fixture tree, in a mode-0700 directory with mode-0600 files.
They never enter a guest or read-only share. Certificates are RSA-2048/SHA256,
self-signed disposable identities with 14-day validity. These are test identities,
not production/release keys. Evidence records only public certificates/fingerprints
and key file paths, never private contents. Preserve private files separately if
further test signing is needed; do not export them with public evidence.

Enrollment modifies a **file**, using `virt-fw-vars --input TEMPLATE --output COPY
--set-pk OWNER TRUSTED.pem --add-kek OWNER TRUSTED.pem --add-db OWNER TRUSTED.pem
--secure-boot`. It does not call efivarfs, `efi-updatevar`, physical firmware or an
in-place writer. The clean template avoids Microsoft/distro trust additions. Live
PK, KEK and db must each contain exactly the intended DER certificate. Baseline
VARS is sealed read-only and cloned per run.

The signed `firmware-probe.c` boots from the fixture disk. It reads live
`SecureBoot`, `SetupMode`, PK, KEK and db through UEFI GetVariable, then calls
LoadImage on four controlled files. The trusted payload must execute once and
return success. The unsigned, differently signed and tampered copies must fail
LoadImage, never reach StartImage, and have matching authentication records in
the firmware image execution table. Fixture nonces identify the signed probe;
each run creates a fresh serial-log path.
Missing files, missing markers, crashes and timeouts fail validation.

This OVMF build uses EDK2's deny policy. Its expected LoadImage status is
`800000000000000f` (EFI_ACCESS_DENIED), together with authentication-table actions
0 for unsigned and 3 for untrusted/tampered files. A generic access error alone
does not pass. EDK2 documents this policy in
[DxeImageVerificationLib](https://github.com/tianocore/edk2/blob/edk2-stable202402/SecurityPkg/Library/DxeImageVerificationLib/DxeImageVerificationLib.c)
and defines the table in
[ImageAuthentication.h](https://github.com/tianocore/edk2/blob/edk2-stable202402/MdePkg/Include/Guid/ImageAuthentication.h).
Another firmware policy requires separately justified expectations.

`fixtures --artifact UNSIGNED_UKI --artifact-role uki` signs a real UKI with both
identities and changes one byte in `.linux` without resigning. The same mode with
`--artifact-role loader` changes `.text` in systemd-boot. For these fixtures the
trusted file is loaded and unloaded, without starting it; evidence explicitly
reports `executed=false`. The installed boot test supplies actual execution proof.
The original artifact must have no signature table. The ordinary tiny payload
fixture changes `.p3data`, retaining valid PE structure and the signature table.

## Installed fixture boot and faults

`installed-fixture` takes an existing accepted, stopped **plain** Phase 2 baseline
and `--trust-base FIRMWARE_BASE --private-keys MATCHING_KEYS`. It converts the source
to a separate sparse raw file, locates its sole GPT ESP, signs copies of both
systemd-boot paths and the UKI, writes only that copy using mtools, verifies write
hashes and converts it to an independent qcow2. No host block device is mounted.
The original baseline remains unchanged. This prepares test signing fixtures;
it does not implement product signing or mark a generation known-good.

```sh
sudo python3 "$SRC/scripts/validate/phase3.py" installed-fixture \
  --base /home/ubuntu/p2sec/base-plain --output /home/ubuntu/p3/signed-plain \
  --trust-base /home/ubuntu/p3/firmware-base --private-keys /home/ubuntu/p3-private \
  --ovmf-code "$CODE" --source-commit "$BASE"
sudo python3 "$SRC/scripts/validate/phase3.py" installed \
  --base /home/ubuntu/p3/signed-plain --output /home/ubuntu/p3/trusted-boot \
  --ovmf-code "$CODE" --source-commit "$BASE"
```

The installed gate checks actual guest readiness, root health, live firmware trust,
loaded loader/UKI paths, signed UKI hash, kernel, root/subvolumes/encryption,
transaction/snapshot history, ESP file hashes and boot-confirmation service status.
The manifest retains the original runtime revision, which differs from this branch's
base/report revision. It does not infer generation acceptance from kernel boot.

`inject --fault KIND` boots and observes an overlay of that signed fixture, runs
`phase3_guest.py`, observes the damaged state and shuts down. It supports tampered
`.linux`, missing UKI, partial ESP artifact write, unsigned/untrusted/wrong-root
replacement UKIs and bounded full ESP. Replacement files require `--replacement`;
only a public `.efi` is copied to the read-only guest share, and the guest verifies
its SHA256 and UKI section. Supply a separately validated, trusted-signed wrong-root
fixture after signing integration; a byte-corrupted command line is not equivalent.
Full ESP requires the expected `/dev/vda1` vfat mount, an ESP no larger than 2 GiB,
a new filler and actual ENOSPC within 30 seconds. No root data is filled.

The fault helper requires root, nested KVM, the test-only virtio port and a UKI
inside the disposable `/efi/EFI/Linux` mount. Guard refusal occurs before target
access. Fault receipts retain before/after hashes and times. `inject` success means
**injection completed**, with `injection_only=true` and `security_acceptance=false`.
It is not a rejection or recovery verdict. Neither guest helper ships in an ISO.

## Required integration APIs and acceptance order

The base exposes update, confirm-boot, snapshots and offline rollback. It has one
unsigned development UKI, ordinary loader installation and no Phase 3 generation
schema or signed recovery media. Do not call unsupported generation commands or
use the unsigned Phase 2 recovery ISO as a trusted Phase 3 recovery result.

The two product branches must supply:

* Trusted signed loader, UKI and recovery-media inputs plus their public trust
  identity. Test keys stay outside the release build and public ISO.
* A read-only generation inventory that identifies active, candidate, previous and
  known-good generations, root UUID/subvolume identity, UKI path/hash/signer,
  boot-entry selection/counters, attempts and health confirmation.
* Native candidate staging/activation, selection/fallback and confirmation APIs.
  Validation needs the supported refusal codes and durable reason/attempt records.
* A documented on-disk metadata schema and test-only fixture boundary for mismatch,
  missing previous generation, exhausted counters and encrypted unlock failure.
* Synchronous test-only barriers at UKI staging, boot-entry staging, generation
  activation, health confirmation and rollback preparation. Each must be inside
  the actual write operation and remain blocked until the host cuts power.

`cut_at_barrier(vm, checkpoint, generation, root_uuid, uki_sha256)` is ready for
the last hook. The integration adapter must clear stale receipts and write
`/var/log/astraeus-validation-phase3-barrier.json` with `checkpoint`, `boot_id`,
`generation`, `root_uuid`, `uki_sha256` and `blocked:true`, then block. Expected
identities come from independently inspected product state. The helper refuses
stale/mismatched receipts and missing hooks, captures QMP and the barrier, kills
only its QEMU child and records actual SIGKILL status. It does not resume or repair
product state. No write-boundary power cuts are accepted on this branch.

After Chats 1 and 2 are merged, build and inspect the integrated artifacts, prepare
fresh plain/LUKS2 baselines, complete A-J, and repeat the existing clean ArchISO
pipeline twice with full-file SHA256 **and byte comparison**. Keep phase-specific
negative evidence and exact generation/root/UKI pairing after each reboot and
recovery. The Phase 2 post-package barrier remains a separate test, not a substitute
for the five Phase 3 checkpoints. These cuts cannot qualify arbitrary power loss.

## Export and cleanup

Retain every attempt's command/status logs, serial output, QMP, signed file hashes,
baseline disk/VARS identities, source and harness file hashes, observations and
start/end times. `evidence-sha256.json` includes the stopped output disk and VARS.
Export a whitelist of public artifacts and logs, then verify all exported hashes.
Preserve canonical test images outside nested guests and export durable copies
before retiring anything unique. Do not include private key directories, cloud
credentials, test passwords or the old Phase 2 secrets directory.

Stop all QEMU children owned by validation, verify no nested QEMU remains, record
provider runtime/resource counters, pause only `astraeus-phase0-validator`, and
compare account inventories to confirm unrelated VMs remained untouched. Do not
merge this branch or start Phase 4.
