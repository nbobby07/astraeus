# ADR 0003: owner-managed Secure Boot signing boundary

Date: 2026-10-08. Base: `6a8fda25d25df74215ed0bbe06b97804e053d950`.
Status: accepted for implementation; enforcing firmware qualification pending.

## Decision

Use direct UEFI trust in an owner-selected X.509 db certificate, with upstream
OpenSSL, sbsigntools and ukify. Do not introduce shim, a new bootloader, or custom
cryptography. Pin the SHA-256 fingerprint of the certificate's DER encoding in a
root-owned signing policy. Check validity, private/public key agreement, file
permissions and local revocations before signing; verify every result against
that certificate. These host checks do not establish firmware trust.

Firmware authenticates systemd-boot through its image security policy. The loader
uses firmware LoadImage for the selected UKI. In enforcing mode firmware applies
db/dbx policy to that image too. The signed UKI covers the kernel, initramfs and
embedded command line. With Secure Boot enabled, systemd-stub ignores invocation
command-line overrides when an embedded command line exists. Writable Btrfs root,
ESP menu selection and filenames are not authenticated by a UKI signature.
An old signed image can still boot while its key remains trusted. LUKS2 provides
encryption, not an authenticated or immutable root filesystem.

Keep PK and KEK administration offline. The online db key is owner-specific and
root-private. Development keys, disposable OVMF keys, machine-owner keys and future
release keys are different roles. Never generate or copy private keys into build
inputs, a package or an ISO. Production release key distribution is out of scope.

## Signing and generation ownership

The existing Phase 2 preset writes `/efi/EFI/Linux/astraeus-dev-linux.efi` directly.
Changing that active generation belongs to the boot-generation owner. Retain the
default unsigned output only for unprovisioned systems and keep Phase 2 updater
restrictions. The installed preset queries the signing helper for its output;
policy, retained signing state or firmware-reported SecureBoot enables a private,
non-discoverable output. A packaged mkinitcpio post hook then publishes a verified
candidate directory. No signing command writes to the ESP or invokes bootctl
install/update. Failed or interrupted work
never changes the active UKI, loader, or previous recovery copies.

The candidate is a directory containing the signed image and a schema-versioned
receipt, published by a same-filesystem rename only after file and directory sync.
An existing candidate or incomplete staging directory blocks another publication.
Consumers must reverify signatures and receipt identity/content before activation,
preserve the previous root/UKI pair using Phase 2, and sync/verify the ESP copy.
Receipt hashes bind artifacts; they are not substitutes for signatures.

The installer payload carries the helper and optional preset but no active signing
policy or keys. Owner provisioning is an explicit post-installation operation.
Installer finalization refuses its unsigned path before writing configuration
or invoking bootctl when signing is required.
An AbortOnFail PreTransaction hook blocks package mutation when signing is
required, pending the generation integration. Deleting a policy while signing
state remains cannot re-enable unsigned output. Unknown firmware is reported as
unknown; an unprovisioned development system makes no enforcement promise.
Chat 2 must connect candidate consumption, active-generation verification and the
signed-loader source comparison before updates on provisioned systems are
qualified. Keep systemd/bootloader package-update rejection even after that work.

## Enrollment and revocation

Read firmware variables only. Report missing, malformed or inaccessible state as
unknown. Report artifact signature validity separately from SecureBoot/SetupMode
and database observations. Do not infer enforcement from signed files. Firmware
dbx evaluation (including image hashes and certificate TBS revocations) remains
the firmware's responsibility; the local policy can deny certificate fingerprints
but is not a dbx emulator.

Prepare fresh PK, KEK and db material and EFI signature lists only in an explicitly
requested disposable-test directory. Do not write efivars, modify VARS, or place
auto-enrollment files on an ESP. Chat 3 owns enrollment into a fresh disposable
OVMF VARS copy and the actual enforcement/negative-boot tests. Real hardware
requires operator confirmation in its firmware UI, factory database backups and
a tested recovery route. Never replace factory db/dbx automatically.

Rotation uses overlapping firmware trust and independently verified recovery
images before changing the signer pin. Expiry is a local signing-policy gate,
not a promise that firmware rejects expired certificates. Revoking an old key
can make known-good recovery images unbootable. No unattended rotation, firmware
revocation update or lost-key recovery mutation is implemented in this phase.

## Alternatives and consequences

Signing the active ESP file in place exposes partial or unsigned data. Automatic
bootctl updates would cross the unpreserved bootloader recovery boundary. A
single certificate for PK, KEK and db would unnecessarily couple administration
and routine signing. None of those approaches is used.

Deterministic package/ISO preparation remains separate from random, machine-local
provisioning. Full ISO reproducibility and enforcing Secure Boot acceptance must
be rerun by their respective validators; host signature tests establish neither.

## Upstream evidence

- [UEFI 2.11, section 32.5](https://uefi.org/specs/UEFI/2.11/32_Secure_Boot_and_Driver_Signing.html): PK/KEK, authenticated database changes and db/dbx image validation.
- [systemd-stub](https://man.archlinux.org/man/systemd-stub.7.en): embedded sections, command-line policy, and the distinct companion-file boundary.
- [systemd 262 boot loader source](https://github.com/systemd/systemd/blob/v262/src/boot/boot.c): selected-image loading through firmware.
- [ukify](https://man.archlinux.org/man/ukify.1.en): structure inspection and upstream signing support.
- [mkinitcpio](https://man.archlinux.org/man/mkinitcpio.8.en) and [v42.1 post-hook implementation](https://github.com/archlinux/mkinitcpio/blob/v42.1/mkinitcpio): post-hook arguments and nonzero failure propagation.
- [bootctl](https://man.archlinux.org/man/bootctl.1.en): preference for `.efi.signed` inputs does not itself make updates recoverable.
- [sbverify](https://man.archlinux.org/man/sbverify.1.en): certificate-selected image signature verification.
