# Security and signing

## Trust model in Phase 0

Use Arch's package format, libalpm/pacman verification and upstream keyring. The
curated repository requires signed packages and a signed database. Arch packages
require signatures; upstream database signatures remain optional according to
Arch's repository policy. HTTPS and pinned database hashes protect repeatability
of the chosen snapshot. Neither a hash nor a signature establishes that code is
safe; review/build provenance and integration gates remain necessary.

The build operator supplies a full primary fingerprint independently of the
repository key file. The builder checks it, initializes a separate keyring and
locally certifies only that selected key. This leaves the host pacman keyring
unchanged. The live image initializes its own ephemeral keyring. The publisher
verifies detached package signatures, includes them in the database and signs
that database. No code path falls back to unsigned packages or `TrustAll`.

Private keys stay outside the repository, build source archive and ISO. Generate
development keys in an isolated `GNUPGHOME`; do not ship them as release keys.
Production requires an offline primary key, constrained signing subkeys,
separate release authorization, encrypted backups, expiry/rotation procedures and
revocation distribution. Public-key changes must be reviewed against a fingerprint
communicated over an independent trusted channel. Release artifact checksums need
a detached signature from the release identity; the local checksum file alone is
not release authentication.

No telemetry, background analytics, remote management, AUR helper or security
mitigation override is installed by this project. The live environment grants
local physical users passwordless sudo and an empty-password `live` account. It
is a rescue/development medium, not an installed-system account policy. Do not
enable network login services with that account configuration.

## Secure Boot boundary

Phase 0 media has unsigned boot artifacts and must not be represented as Secure
Boot capable. Test using a separate non-enforcing OVMF variable store. Scripts
never disable Secure Boot, alter host firmware or enroll keys. Machines enforcing
Secure Boot are outside this phase's boot acceptance target.

Phase 1 introduces systemd-boot and UKIs for installed systems. Phase 3 adds UKI
and bootloader signing, key handling/enrollment and chain verification. Firmware
that cannot enroll keys automatically needs an explicit explained user step.
There must be no unsigned fallback that silently weakens a promised verified boot
chain. Distinguish owner-managed keys from compatibility with factory trust stores.

## Recovery constraints

LUKS2 and Btrfs are intended installed-system components, not proof that this
ephemeral ISO is encrypted. Snapshot rollback must coordinate the ESP and root
generation and keep a boot-confirmed fallback. Snapshots do not protect against
disk loss or hostile physical access. Secret provisioning, firmware trust,
encrypted swap, hibernation and TPM unlock need separate designs and tests.
