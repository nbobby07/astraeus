# Owner-managed Secure Boot

Phase 3 integrates owner signing with [boot generations](boot-generations.md),
private candidate staging, firmware inspection and disposable test keys.
The default installer remains unsigned; owner provisioning is a separate step.
No tool enrolls firmware keys. See [integration acceptance](phase3-acceptance.md)
before relying on this development implementation for recovery.

Decision and upstream references: [ADR 0003](adr/0003-owner-secure-boot.md).

## Trust and key model

The intended chain is firmware image validation of signed systemd-boot, followed
by firmware image validation of the signed UKI requested by that loader. The UKI
includes the kernel, initramfs and embedded command line. This does not verify
the writable Btrfs root. Neither a signed filename, a matching hash, a booted
desktop nor `sbverify` alone proves that firmware enforced this chain.

| Identity | Purpose and storage |
| --- | --- |
| Development | Disposable local tests; never treated as a release identity |
| Disposable OVMF | Separate PK, KEK and db keys, explicitly marked and short lived |
| Machine owner | Owner-controlled PK/KEK offline; local db key in a root-private directory |
| Future production | Not provisioned by this implementation; separate release authorization required |

PK authorizes platform administration; KEK authorizes trust-database updates;
db authorizes images. Preserve factory databases and their recovery procedures.
dbx is read only here. No command clears, replaces or writes any firmware variable.
No shim/MOK trust, network key service or custom cryptography is introduced.

The online signer trusts the installed root and the upstream tools. A root
compromise can use an accessible db key to sign malicious code. Key files inside
`@` are also present in root snapshots: their private directories and snapshot
access controls are part of the confidentiality boundary. Never publish snapshots
or diagnostic bundles containing them. An offline or hardware signer is future
work; do not provision a release key as an online machine key.

## Policy and dependencies

The package installs `/usr/bin/astraeus-secure-boot`, the native
`astraeus-boot-artifact` provider, a mkinitcpio post hook and documentation.
OpenSSL, Python, systemd-ukify, sbsigntools and efitools are runtime dependencies.
Provisioning is separate from ISO construction; builds do not generate keys or
install an active policy. efitools computes the PE Authenticode SHA-256 used for
image revocations. This differs from the full-file hash in generation metadata.

The package also carries an AbortOnFail hook in `/usr/share/libalpm/hooks`, so
existing installations receive the update guard when upgrading distroctl.
Calamares finalization calls `guard-legacy` before configuration writes or
unsigned bootctl installation. The package hook uses `guard-update`, which
requires the running distroctl coordinator to hold both mutation locks and have
a freshly verified retained generation selected. On an older installation,
provision the matching package, the guarded `linux.preset` rendered by the
installer, and its post hook together. Keep the guarded preset's legacy argument:
the generation manager relocates it when the first retained root is selectable.

`/etc/astraeus/secure-boot/policy.json` has exactly these fields:

```json
{
  "schema_version": 1,
  "purpose": "machine-owner",
  "certificate": "/etc/astraeus/secure-boot/db.crt",
  "private_key": "/var/lib/astraeus/secure-boot/keys/db.key",
  "certificate_sha256": "REPLACE_WITH_64_LOWERCASE_HEX_DIGITS",
  "revoked_certificate_sha256": []
}
```

The placeholder is deliberately invalid. Compute the pin with
`openssl x509 -in db.crt -outform DER | sha256sum` and confirm it through an
independently trusted copy of the owner's certificate. Do not trust a fingerprint
merely because it accompanies an unfamiliar key file. Policies reject duplicate,
missing and unknown fields. All paths and ancestors must be root-owned and not
writable by other users, with no symlinks. Private keys need mode 0600 and their
containing directory mode 0700. Policies/certificates can be 0644 in root-owned
0755 directories. Keys and certificates must be different regular files.

The supported signer uses a self-signed certificate and an unencrypted local
PEM key. OpenSSL checks certificate validity/signature and key agreement; the
pin and local deny list select the authorized identity. An encrypted or unavailable
key fails without a prompt. Tool diagnostics are suppressed to avoid disclosing
input data. The helper never prints or copies private key bytes.

```sh
sudo astraeus-secure-boot check-config
distroctl security status --json
sudo astraeus-secure-boot verify uki /efi/EFI/Linux/astraeus-dev-linux.efi
sudo astraeus-secure-boot verify bootloader /efi/EFI/systemd/systemd-bootx64.efi
sudo astraeus-secure-boot verify bootloader /efi/EFI/BOOT/BOOTX64.EFI
```

Status is read only, returns JSON, and works without a policy. Non-root inspection
can report inaccessible keys, ESP files or firmware variables as unavailable.
Missing or malformed firmware booleans remain null. Artifact verification means
valid for the configured certificate under local policy; it is not firmware
authorization. PK/KEK/db/dbx observations include exact certificate membership and
unrecognized signature types. No raw key/database contents are printed.

The enrollment-only command requires the configured signer in db, an observed
empty dbx, SecureBoot=1 and SetupMode=0. It cannot authorize a particular image.
The generation provider additionally accepts SHA-256-only dbx lists after
checking the exact image's Authenticode hash against every entry. Missing,
unreadable, malformed, certificate/TBS and unsupported lists still fail closed.
Revoked signatures and known image hashes cannot pass. Never clear dbx to satisfy
this policy. Certificate expiry is a local policy; actual enforcing boot and
refusal remain separate acceptance gates.

## Signing and generation interface

The shipped `astraeus-boot-artifact` implements the strict schema-1 ready,
verify and rebind interface in [boot generations](boot-generations.md).
Readiness checks both signed loader copies against all packaged loader bytes
except Authenticode metadata and alignment padding. It checks the running
systemd-boot 262 identity, ESP and absence of another XBOOTLDR partition.
Artifact verification checks both full-file integrity and current owner/firmware
policy. Signing alone does not establish that firmware enforced an earlier boot.

Rebinding verifies the source signature, changes only the embedded command line,
signs the new image and verifies all other PE sections are unchanged. The new
selector must fit the original section's allocated padding; larger selectors
are refused. An interrupted rebind retains `rebind.pending` and blocks reuse.
Completed rebind receipts remain in `rebind.consumed.*` directories.

The package hook accepts signed updates only when its ancestor is the installed
distroctl process holding both the update and snapshot locks. It asks Rust to
verify the selected retained root and its authoritative transaction reference.
The post hook stages and verifies a private candidate, then journals publication
to the unselected maintenance path. It verifies the ESP copy before replacement.
The retained generation remains immutable and selectable throughout. Completed
candidate receipts move to `uki.consumed.*`; `uki.publish.json` or unfinished
signing state requires deliberate inspection. Direct pacman and manual
mkinitcpio cannot use this handoff without the locked coordinator.

Offline recovery passes `--policy-root INSTALLED_ROOT verify IMAGE`. Only public
policy and certificate reads are allowed in this mode; paths are resolved beneath
that root with the same ownership and link checks. The currently running recovery
firmware must trust the installed identity. Recovery never borrows a private key
from the installed root for verification.

The low-level candidate interface below also supports explicit initial owner
provisioning. Initial loader/UKI installation must be completed and independently
booted under enforcing firmware before `distroctl boot enable`. Preserve the
guarded preset, both signed loader copies, the original UKI and signing receipts.
Neither a signing command nor `boot enable` enrolls keys or proves boot acceptance.

Create `/var/lib/astraeus/secure-boot` root-owned mode 0700. Under the generation
coordinator's mutation lock, build unsigned material outside the ESP and call:

```sh
sudo astraeus-secure-boot stage uki /path/to/private/generated-uki
sudo astraeus-secure-boot verify-candidate uki
sudo astraeus-secure-boot stage bootloader /usr/lib/systemd/boot/efi/systemd-bootx64.efi
sudo astraeus-secure-boot verify-candidate bootloader
```

Inputs must satisfy the trusted-path rules above. Outputs are fixed:

```text
/var/lib/astraeus/secure-boot/
  signing.lock
  uki.pending/                 # interruption/failure, never eligible
  uki.ready/                   # complete candidate only
    input.efi
    artifact.efi
    receipt.json
  bootloader.pending/          # same contract, independent candidate
  bootloader.ready/
```

Candidate directories are 0700 and files 0600. The receipt schema is version 1:
kind, purpose, certificate SHA-256, input SHA-256, artifact SHA-256 and
`firmware_trust: "not-evaluated"`. No timestamp or private data is needed.
ukify inspects required sections, sbsign signs the private copy, sbverify checks
the selected certificate, and inspection confirms section content is unchanged.
Profiles and repeated sections are unsupported. Files and directory entries are
synced before publication by rename. A ready or pending directory blocks another
publication; neither is overwritten or automatically pruned.

For mkinitcpio integration:

- The installed `/etc/mkinitcpio.d/linux.preset` calls `uki-output` to select its
  output. With a policy, retained signing state, or firmware SecureBoot=1, it
  always selects private staging. Helper failure aborts preset processing.
- `/usr/lib/initcpio/post/95-astraeus-sign` signs private output. It is a no-op
  for ordinary unsigned presets only when signing is not required.
- `/usr/share/distro/secure-boot/linux.preset` always selects private output,
  for explicit generation-manager provisioning and validation.

That preset sends ukify output to `/var/lib/astraeus/secure-boot/unsigned.efi`.
The post hook accepts only that path and propagates signing failure. Existing
Arch and Astraeus package hooks already call mkinitcpio, as does the Phase 2
coordinator. Missing policy/key, invalid signatures and incomplete staging fail
closed. No unsigned fallback is supplied. A ready candidate alone changes no
bootable generation. Retained signing state prevents a removed policy from
silently restoring unsigned output. `80-astraeus-secure-boot.hook` uses
PreTransaction/AbortOnFail to require the verified generation handoff described
above. Unprovisioned, non-enforcing systems keep their original behavior.
Unknown firmware alone does not turn an unprovisioned development installation
into a managed signer.

Original integration requirements, now exercised by the provider and coordinator:

1. Hold the existing transaction/snapshot mutation guard; preserve the active
   root/UKI pair before package hooks. Run `check-config` and reject unresolved
   pending/ready candidates before mutation. Account for two candidate copies.
   Replace `guard-legacy`' explicit integration refusal with a checked handoff
   under that coordinator; never simply remove the hook or bypass AbortOnFail.
2. Check the candidate's expected kernel, initramfs, embedded command line and
   transaction identity against the generation being built. The signer validates
   structure and signature, not the intended semantics of root selection.
3. Hold `signing.lock` with flock during consumption. Re-run `verify-candidate`,
   copy the signed artifact into hidden ESP staging, sync it, and verify that
   copy's signature and receipt hash before making the generation selectable.
4. Keep the old verified root/UKI material until a new boot is accepted. Archive
   the receipt with generation metadata. Only then resolve the consumed ready
   directory under the same locks; the signer does not own retention policy.
5. Check signatures in health, boot confirmation and offline recovery. Recheck
   current firmware trust before offering an older generation after rotation.
6. For initial signed-loader provisioning, preserve both installed EFI loader
   copies and recovery media. Bind each signed candidate's original bytes to the
   packaged loader. Adapt the Phase 2 unsigned `cmp` checks without treating an
   arbitrary signed executable as the packaged systemd-boot. Keep the rejection
   of systemd/bootloader update plans until preservation/recovery is qualified.

After an interruption, retain pending/ready directories as evidence and compare
their files with the active generation and receipt. An incomplete directory is
not resumable automatically. Reverification is mandatory even after a rename
completed. ESP and root switching remain separate operations; this helper makes
no power-loss guarantee for that handoff.

## Disposable OVMF preparation and acceptance

Only in a Linux test environment, explicitly request fresh short-lived keys:

```sh
sudo astraeus-secure-boot prepare-test-keys /root/astraeus-ovmf-test --disposable-ovmf-only
```

The destination must not exist. It receives independent PK/KEK/db RSA-2048 keys,
self-signed 30-day certificates, DER certificates, EFI signature lists, a sample
policy, and a completion marker. An interrupted destination is retained and
never reused. No `.auth` enrollment action, efivar write, firmware access or VARS
modification occurs. Private material must stay outside the repository and ISO.

Validation must use a fresh, explicitly disposable VARS copy with Secure Boot capable
OVMF firmware. Enroll the test db and KEK, then PK last through that guest's setup
mechanism, preserving logs and hashes of public inputs and the before/after VARS.
Never point that automation at host firmware or real-hardware variables. Preserve
dbx. Record SecureBoot=1 and SetupMode=0 after cold boot, and demonstrate:

- Positive boot through signed systemd-boot and the intended signed UKI.
- Firmware rejection of an unsigned loader and an unsigned UKI independently.
- Firmware rejection of a wrong-key loader, wrong-key UKI and tampered UKI.
- Refusal after removing/revoking the trusted signer, with a separately trusted
  recovery route retained. Exercise supported dbx behavior in firmware.
- Signing failure, missing key and interrupted staging leave prior boot material
  intact and cannot select unsigned output.
- Plain and LUKS2 installs, successful update/confirmation and retained-generation
  recovery on the integrated image, followed by Phase 2 regression acceptance.

Real hardware enrollment requires an explicit operator decision and confirmation
in firmware, a backup/export of factory PK/KEK/db/dbx, vendor recovery instructions,
and recovery media signed by a retained trusted identity. Some devices rely on
factory-signed option ROMs. No generic key-replacement command is provided.

## Rotation, lost keys and reproducibility

Plan rotation before expiry: retain the old trust and recovery image, provision
a new db key separately, verify its pin, add its public certificate through an
authorized firmware update, sign and boot a new generation, then change the local
signer policy. Revalidate all retained recovery choices before removing old trust.
Local deny-list changes do not update firmware dbx, and can make local verification
of old artifacts fail. A compromised old key needs firmware revocation plus a
recovery image signed by an unaffected key. Do not revoke the only recovery key.

If an online owner key is lost, already signed trusted generations can still boot
subject to firmware policy, but this helper refuses new signing. Recover an
encrypted offline backup or authorize a replacement with the retained offline
PK/KEK or vendor physical-presence recovery. Automatic recovery, rotation,
production key distribution and firmware dbx updates are unsupported.

The package source allowlist contains only helper code, public templates and
documentation. Default ISO builds remain unsigned and generate no random signing
material. Owner-specific signatures and enrollment happen after installation,
outside deterministic build inputs. Full byte-identical ISO builds have not been
rerun for this branch; do not extend the Phase 2 evidence to a new image by claim.
