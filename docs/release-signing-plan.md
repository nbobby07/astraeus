# Release signing and distribution plan

Status: **plan only**. Nothing here is implemented, provisioned or qualified.
It defines what must exist before any image, repository or recovery medium is
published under an Astraeus release identity. Items marked **Decision needed**
require an owner choice before the corresponding phase starts.

Originally drafted at `8a4f1e5`; reconciled with accepted runtime `c38209c`
on 2026-10-15. See the [current handoff](release-readiness.md). Related records:
[security](security.md), [owner Secure Boot](secure-boot.md),
[ADR 0003](adr/0003-owner-secure-boot.md), [releases](releases.md),
[building](building.md) and [Phase 4.2 acceptance](phase42-acceptance.md).

## Current state

All acceptance so far uses disposable identities on QEMU/KVM. The table records
what exists, where, and what production lacks.

| Area | Implemented today | Source | Production gap |
| --- | --- | --- | --- |
| Repository key creation | Validator A runs `gpg --quick-generate-key ... ed25519 sign 1d` with an empty passphrase inside the disposable builder | `scripts/validate/arch-builder.sh` | No long-lived identity, offline primary, subkeys, backup or revocation certificate |
| Package and database signing | `makepkg --sign`; `publish-repo.sh` verifies each detached signature against a supplied 40-hex primary fingerprint (subkey `VALIDSIG` accepted), then `repo-add --sign` and writes `SHA256SUMS` | `scripts/publish-repo.sh`, `docs/building.md` | Signing happens on the build host; no token, ledger or two-person check |
| Build-time trust | `bootstrap.py iso` checks the exported key has exactly the supplied primary, then `pacman-key --add`/`--lsign-key` in an isolated keyring; `[distro]` is `SigLevel = Required DatabaseRequired` | `scripts/bootstrap.py`, `distro/archiso/pacman.conf.in` | Sound; the fingerprint source is the operator, not a published release identity |
| Live and installed trust | Live: `live-keyring.service` lsigns the baked-in fingerprint. Installed: provisioning reads `/usr/share/distro/repository-fingerprint` and lsigns it in a fresh keyring | `distro/archiso/airootfs/etc/systemd/system/live-keyring.service.in`, `scripts/provision.py`, `scripts/installer.py` | No keyring package, so installed systems cannot receive new subkeys, expiry extensions or revocations |
| Repository location | Installed systems use `Server = file:///opt/distro/repo`, a copy of the ISO's repository | `scripts/installer.py`, `distro/archiso/pacman.conf.in` | No remote `distro` repository; there is no update or revocation channel for Astraeus packages |
| Upstream packages | Pinned `archive.archlinux.org` snapshot; `archlinux-keyring` is whatever the snapshot contains | `distro/repo/archive.lock.json` | Arch key revocations after the snapshot date do not reach builds or installs until the pin advances |
| Expiry behaviour | pacman refused the database with `signature from "Phase 0 disposable package signing" is expired` | `docs/evidence/phase4-signed-fixture-refresh/fixture-result.json` | Any production key expiry must be extended and distributed before it lapses |
| Secure Boot keys | Owner-held PK/KEK/db per machine. `prepare-test-keys --disposable-ovmf-only` makes RSA-2048, 30-day self-signed PK/KEK/db and no `.auth` files | `scripts/secure_boot.py`, `docs/secure-boot.md` | No project Secure Boot identity exists; that is by design (ADR 0003) |
| Test enrollment | `virt-fw-vars --set-pk/--add-kek/--add-db` on a copied OVMF VARS only | `scripts/validate/phase42-baseline.py` | Real hardware enrollment is unsupported and untested |
| UKI and loader signing | The machine-owner db key is an unencrypted root-only PEM at `/var/lib/astraeus/secure-boot/keys/db.key`, pinned by certificate SHA-256 in `policy.json`. ukify, sbsign and sbverify run via the mkinitcpio post hook `95-astraeus-sign` | `distro/installed/secure-boot/`, `docs/secure-boot.md` | Online key by design for locally built UKIs; the helper rejects encrypted keys and has no token support |
| dbx | Read-only. SHA-256 image lists are evaluated; certificate/TBS lists fail closed | `docs/secure-boot.md`, `scripts/secure_boot.py` | Vendor-updated dbx on physical hardware may contain certificate entries; see [physical hardware](#microsoft-signed-shim-versus-owner-enrolled-keys) |
| Installation and recovery media | The default ISO boot chain is unsigned. Phase 4.2 recovery images are signed with each baseline's own test db key and verify SquashFS in RAM | `docs/boot.md`, `docs/phase42-recovery.md` | No media signed by a release identity; the live SquashFS of the setup ISO is unauthenticated |
| Reproducibility | Two independent builders produce byte-identical ISOs, but B consumes A's signed repository bytes | `docs/building.md`, `docs/validation.md` | Proves reproducibility with fixed signed inputs, not two independent signings; no attestation format |
| ISO checksums | `bootstrap.py` writes an unsigned `iso/SHA256SUMS` | `scripts/bootstrap.py` | No release signature, fingerprint publication or user verification guide |

The historical Phase 4.2 repository key `6DA84EB479F3A2F88C2B658E17BF6CA306695F72`
expires at 2026-10-15 16:18:26 UTC. After that time, the `distro` database in the
Phase 4.2 candidate images will fail verification, as recorded for earlier keys.
Further validation needs a fresh disposable key and rebuilt repository, which
changes ISO bytes. Production must provide a tested rotation and distribution path.

The accepted Phase 5 candidate instead uses
`27CCE96199D30A7ABA1BE86CC6722DAA8014EE89`, expiring on
2026-10-16 at 08:55:39 UTC. Its public metadata is recorded in the
[integration evidence](evidence/release-readiness-20261015/repository-public-key.json).
This is also a disposable identity, not a release key. Key expiry affects package
verification; it does not add an expiry check to the unsigned live boot chain.

## Principles

- Project release identities never sign on an online build host. Machine-owner
  Secure Boot keys remain per-machine and are never held by the project.
- Every key has one purpose. pacman trusts all valid subkeys of an lsigned
  primary, so purpose separation between repository and release signing
  requires separate primaries, not just separate subkeys.
- A signature attests "built from this recorded source by this process and
  reviewed". It does not prove safety. Do not claim more in release notes.
- Changes go through Git review, and so do public-key changes. Fingerprints are
  confirmed through at least two independent channels.

## Key hierarchy

| Key | Type | Signs | Storage | Lifetime |
| --- | --- | --- | --- | --- |
| Repository primary | OpenPGP, certify-only | Its own subkeys, expiry extensions, revocations | Offline: air-gapped generation, encrypted backups, optional token | Expiry 3 years, extended in ceremony |
| Repository signing subkey (active) | OpenPGP signing subkey | Packages and `distro.db` | Hardware token (OpenPGP card) | Expiry 1 year, extended yearly |
| Repository signing subkey (standby) | OpenPGP signing subkey | Nothing until activated | Second token, stored separately | Same; published in advance |
| Release primary | OpenPGP, certify-only | Its own subkeys | Offline, as above | As above |
| Release signing subkey | OpenPGP signing subkey | `SHA256SUMS`, build attestation bundle, release tags | Hardware token | 1 year, extended |
| Project Secure Boot media db (optional) | X.509 RSA-2048 or 3072, self-signed | Live ISO `BOOTX64.EFI` and live UKI, recovery media | PKCS#11 token; offline signing host | 2-3 years; firmware usually ignores expiry |
| Machine-owner PK/KEK | X.509 | Firmware database updates on one machine, including dbx appends | Owner's offline storage (existing model) | Owner's choice |
| Machine-owner db | X.509 | Locally built UKIs and systemd-boot on that machine | Online root-only file (existing model) | Owner's choice; rotation per [secure-boot.md](secure-boot.md#rotation-lost-keys-and-reproducibility) |

**Decision needed:** OpenPGP algorithm (ed25519, already used by the disposable
keys and supported by pacman/gpgme, versus RSA-4096 for wider smartcard support).

**Decision needed:** whether the repository and release identities are separate
primaries (recommended, because of the subkey trust property above) or one primary
for a simpler fingerprint story.

**Decision needed:** whether to create a project Secure Boot media identity
at all; see the shim section. Without one, release media boot only with
Secure Boot disabled or in setup mode, which is today's state.

The project never creates a PK or KEK for users. A project-held PK would let the
project control every enrolled machine, which ADR 0003 rules out.

## Custody, hardware and ceremony

The Secure Boot owner db key stays online on installed machines because
mkinitcpio builds UKIs locally. Nothing in this plan changes that. Only
project keys move offline.

OpenPGP subkeys on OpenPGP cards need no code changes. `publish-repo.sh` and
`makepkg --sign` already call `gpg`, which uses the agent and card. A dry run must
confirm this, including the `VALIDSIG` subkey match in `publish-repo.sh`. An
X.509 media key on PKCS#11 needs sbsign's OpenSSL engine option, or ukify's
signing engine/provider options. This is untested with the pinned OpenSSL 3.5.5,
and `astraeus-secure-boot` accepts only unencrypted PEM keys. It needs a separate
offline media-signing path; do not weaken the machine-owner policy checks.

**Decision needed:** token models and count. At minimum, two OpenPGP tokens
(active and standby repository subkeys, plus the release subkey), and one PKCS#11
token if a media db key exists.

Ceremony, used for generation and for every expiry extension or rotation:

1. Boot an air-gapped machine from a verified, pinned Arch ISO with networking
   disabled. Record the ISO hash and machine.
2. Generate primaries and subkeys in a tmpfs `GNUPGHOME`. Generate revocation
   certificates immediately.
3. Move subkeys to tokens with `keytocard`. Set user and admin PINs, and record
   them only in the sealed backup.
4. Export encrypted primary backups to two media. Put one in a separate physical
   location. Make a paper copy (paperkey) of each primary.
5. Export public keys and fingerprints only. Wipe tmpfs and power off.
6. Write a ceremony log listing date, participants, hashes and fingerprints,
   with no secrets, and sign it. Commit it via reviewed PR.

**Decision needed:** backup scheme (two encrypted copies, or Shamir-split shares
with trusted holders) and the physical locations.

## Separation of duties

A solo maintainer cannot have true two-person control. This plan substitutes
independent verification for it:

- **Independent rebuilder.** A second builder, run on different infrastructure
  and ideally by a different person, must publish a matching signed attestation
  before the release signature is made. See [attestations](#reproducible-build-attestations).
- **Physical and time separation.** Tokens are not kept attached to build hosts.
  The release signature is made at least 24 hours after the candidate hashes
  are published in a reviewed PR.
- **Signing ledger.** Every package, database, `SHA256SUMS` and media signature
  is recorded in an append-only file in the repository: signed hash, key,
  date and source commit. Signatures not in the ledger are treated as
  compromise indicators.
- **Pushback.** CI success, a single build, or a validator report alone cannot
  authorize signing. This is already stated in [releases](releases.md).

**Decision needed:** whether to recruit a second maintainer or rebuilder. If
there is one, decide whether they hold the standby token or a backup share.

## Rotation, expiry and revocation

### Repository OpenPGP

- **Expiry.** Extend subkey expiry at least 60 days before it lapses, and ship
  the updated public key in a keyring update. pacman then accepts old signatures
  again; no re-signing is needed.
- **Keyring package.** Add `astraeus-keyring` to `distro`, modelled on
  `archlinux-keyring`, with `astraeus.gpg`, `astraeus-trusted` and
  `astraeus-revoked` installed for `pacman-key --populate astraeus`. The
  provisioner and live service switch from a bare fingerprint lsign to
  populate. The package must update before other packages, as Arch does with
  `archlinux-keyring`.
- **Rotation.** Activate the standby subkey and generate a new standby, both
  already published in the keyring. Retire the old subkey with a revocation
  ("superseded") certificate after one release cycle of overlap.
- **Subkey compromise.** The primary revokes it ("compromised"). A keyring
  update signed by the standby subkey carries the revocation. Installed systems
  already trust the standby, so this works in-band.
- **Primary compromise.** This cannot be fixed in-band. Publish the
  pre-generated revocation, issue an advisory, and require users to remove the
  old lsign and verify a new primary out of band. Fresh media are needed for
  new installs.
- **Limits.** pacman has no freshness guarantee. A mirror can withhold updates
  (a freeze attack), and a revocation reaches a machine only when it updates.
  None of this works until a remote `distro` repository exists.

**Decision needed:** whether to host a remote `distro` repository, and where.
Without it, installed systems are frozen at their ISO's packages and keys.

**Decision needed:** whether to add a signed freshness or expiry marker (for
example a periodically re-signed database) to bound freeze attacks, or to
document the limit.

**Decision needed:** cadence for advancing the Arch archive pin, which governs
when Arch key revocations take effect.

### Secure Boot

- **Machine-owner db.** Use the existing overlap procedure in
  [secure-boot.md](secure-boot.md#rotation-lost-keys-and-reproducibility).
  No change.
- **Project media db (if created).** Rotate by publishing a new certificate
  before the old one expires. Owners add it with their KEK, and new media are
  signed with it. Old media keep booting until the owner removes the old cert.
- **Revoking project-signed media.** Publish the Authenticode SHA-256 of each
  revoked image. Owners append these to dbx with their offline KEK. This hash
  format is what the provider already evaluates. Do not revoke by certificate:
  certificate dbx entries make the current provider fail closed.
- **How installed systems learn.** A package update ships the revocation list
  and `distroctl security status` reports enrolled-but-revoked media. Applying
  the dbx entries remains a manual owner step, because the KEK is offline and
  no tool writes firmware.
- **Factory dbx.** Machines that keep the factory KEK can receive vendor dbx
  updates through firmware or fwupd. Those updates may add certificate entries;
  see the next section.

**Decision needed:** whether Astraeus ships a dbx-append helper that produces
`.auth` files for the owner to sign offline, or documents `sign-efi-sig-list`
steps only.

## Recovery after key loss

| Lost | Effect | Recovery |
| --- | --- | --- |
| Active repository token | No new package or database signatures | Activate the standby subkey (already trusted) and issue a new standby in ceremony |
| Both repository tokens | Same | Primary backup issues new subkeys. Installed systems must fetch the updated public key (`pacman-key --refresh-keys` via WKD/keyserver, or manual import) before a keyring update signed by the new subkey verifies. Keep tokens apart |
| Repository primary (backups intact) | None | Restore from backup |
| Repository primary (all copies) | Existing subkeys work until expiry; no extension or revocation possible | New primary, out-of-band re-trust, advisory. Prevent with two locations |
| Release subkey | Cannot sign new releases | New subkey from the release primary; publish the updated public key through the fingerprint channels |
| Project media db key | Cannot sign new media | New certificate; owners enroll it with their KEK |
| Machine-owner db key | Existing generations boot, new signing refused | Existing procedure in [secure-boot.md](secure-boot.md#rotation-lost-keys-and-reproducibility) |
| Machine-owner PK/KEK | No firmware database changes | Vendor physical-presence reset to setup mode, then re-enroll with recovery media trusted by the current db |

## Compromise response

1. Stop all signing. Revoke the affected key as described above, and compare the
   ledger with every observed signature.
2. Publish a GitHub security advisory per [SECURITY.md](../SECURITY.md) with
   affected fingerprints, the time window, artifact hashes and the replacement
   fingerprint, plus a notice in the README and release page.
3. User guidance: update the keyring first. Run `pacman-key --list-sigs` against
   the published fingerprints and `pacman -Qkk` for altered files. Compare
   installed package hashes with published manifests. Apply the published dbx
   hashes with the owner KEK. If a malicious package or boot image was installed,
   reinstall from new media; snapshots taken after the event are untrusted.
4. Rebuild affected releases from reviewed source with new keys, through the
   full two-builder process.
5. Write a post-incident record in `docs/` and keep the original evidence.

## Reproducible-build attestations

Signing sits in the middle of the pipeline: the signed repository is copied into
the ISO (`bootstrap.py` `create_profile`), and GPG signatures carry timestamps.
Today, builder B consumes A's signed repository (`docs/building.md`). Release
builds therefore use three stages:

1. **Packages.** Builders A and B independently compile from the same source
   archive. Unsigned package hashes must match; they already do in recorded
   runs. Each builder writes an attestation: source archive SHA-256, commit,
   `archive.lock.json` hash, `Cargo.lock` hash, builder image hash, and package
   hashes. The builder signs it with its own builder key, not a release key.
2. **Repository signing.** On the offline signer, after checking that both
   attestations match, sign each package and run `publish-repo.sh` with the
   repository subkey. This happens once. If the ISO must be Secure Boot signed,
   sign the live loader and UKI here as well, as fixed signed inputs, so the
   ISO stays byte-reproducible.
3. **ISO.** A and B independently assemble the ISO from the identical signed
   repository. ISO bytes, `inputs.json` and manifests must match, and each
   builder signs a second attestation. The release subkey then signs
   `SHA256SUMS`, which covers the ISO, manifests and both attestation files.

**Decision needed:** attestation format. Options are a plain JSON statement
with a detached OpenPGP signature (minimal, matches current tooling) or
in-toto/SLSA provenance (more tooling).

**Decision needed:** what counts as "independent": different cloud account,
different physical host, different operator. At least one should differ from
the release signer's own infrastructure.

## Distribution and user verification

Each release publishes:

- `astraeus-VERSION-x86_64.iso`
- `SHA256SUMS`
- `SHA256SUMS.sig`
- both builder attestations
- package manifests
- the qualification record
- `release-key.asc`

The published `release-key.asc` is a convenience copy. Users must verify its
fingerprint independently.

- **Hosting.** The ISO is about 3.5 GB. GitHub release assets are limited to
  2 GiB per file, so it cannot be a release asset. **Decision needed:** object
  storage/CDN, mirrors and/or BitTorrent, plus who pays and how mirrors are
  admitted. Mirrors are untrusted; only the signature matters.
- **Fingerprint channels.** Publish in `SECURITY.md` and the docs (via a signed
  tag), on the project website over HTTPS, via WKD, and in the release
  announcement. **Decision needed:** which channels, and whether a domain
  exists for WKD.
- **User steps, Linux.** Import `release-key.asc` and compare the full
  fingerprint with two channels. Then run `gpg --verify SHA256SUMS.sig
  SHA256SUMS` and `sha256sum -c --ignore-missing SHA256SUMS`.
- **User steps, Windows.** Use Gpg4win, or WSL, for the signature check.
  `Get-FileHash` alone checks only integrity, and the guide must say so.
- **Writing USB media.** Use raw-image writers (`dd`, `cp`, Rufus in DD mode,
  Fedora Media Writer). Multi-ISO loaders such as Ventoy insert their own boot
  chain, which invalidates any Secure Boot claim; document this as unsupported.
- **Trust handoff.** The ISO embeds `repository-key.asc` and the fingerprint used
  by `live-keyring.service` and `provision.py`. A verified ISO signature therefore
  authenticates the initial repository trust of every installation.

**Decision needed:** whether to also offer a signify/minisign signature alongside
OpenPGP, for users without GnuPG.

## Microsoft-signed shim versus owner-enrolled keys

ADR 0003 chose direct owner db trust without shim or MOK. That remains
the model for installed systems. The open question is how release media and
first installs behave on physical PCs that ship with factory keys.

| | Owner-enrolled (current) | Microsoft-signed shim |
| --- | --- | --- |
| Out-of-box boot with Secure Boot on | No; user enters setup mode or disables Secure Boot to install | Yes, on machines trusting the Microsoft third-party UEFI CA |
| Third parties in the trust chain | None, if factory certificates are removed | Microsoft, plus everything else signed by that CA |
| Locally built UKIs | Signed by owner db key | Still need a per-machine key enrolled through MOK (`mokutil` plus MokManager at reboot), or must be vendor-signed, which is impossible for locally built initramfs |
| Project obligations | None beyond media signing (optional) | shim-review submission, SBAT metadata, an HSM-held vendor certificate embedded in shim, an EV code-signing account for Microsoft submission, and rapid response to shim/SBAT revocations |
| Firmware risk | Removing factory certificates can break GPU/NIC option ROMs signed by Microsoft's CA; some boards brick or need a vendor reset | Low; factory keys untouched |
| Fit with existing code | Implemented, QEMU-qualified | New ADR; provider, `check-enrollment` and recovery need MOK awareness; systemd-boot under shim needs validation |

Practical constraints for owner enrollment on physical hardware, beyond QEMU:

- Keeping the Microsoft UEFI CA in db, for option ROMs, means any
  Microsoft-signed shim and whatever it loads can boot. Then "owner-controlled"
  means "owner plus Microsoft". Documentation and status output must say so.
- Firmware dbx updated by the vendor or fwupd may contain X.509 entries. The
  current provider refuses certificate/TBS dbx lists, so it may refuse to
  operate on such machines until that evaluation is designed and tested.
- The Microsoft 2011 UEFI CAs reached their scheduled 2026 expiry, with 2023
  replacements rolling out. Check the actual db/KEK contents of target hardware
  instead of assuming either.

**Decision needed:** physical-hardware strategy. The options are:

- owner-enrolled only, with Secure Boot disabled or in setup mode during
  installation (no third party; highest user effort);
- owner-enrolled while retaining Microsoft certificates for option ROMs,
  stated honestly;
- shim for installation media only, then owner keys after installation;
- full shim/MOK.

The first two need no new trust code. The last two need a new ADR.

**Decision needed:** whether to accept certificate entries in dbx through
firmware-trusted evaluation, or to restrict supported hardware to SHA-256-only dbx.

## Implementation checklist

Phases are gated. Each needs review and evidence, as with existing phases.

**R0: decisions (no keys)**

- [ ] Resolve every **Decision needed** above and record them in an ADR.
- [ ] Document a disposable-key refresh procedure for validation after
      2026-10-15 16:18:26 UTC. Validation only.

**R1: tooling, using rehearsal keys with the production hierarchy**

- [ ] `astraeus-keyring` package. Switch `provision.py` and
      `live-keyring.service` to `pacman-key --populate`, and add a test that
      fails when a revoked key still verifies.
- [ ] Remote `distro` repository and `Server` configuration, if decided.
      Installed `pacman.conf` stops using only `file:///opt/distro/repo`.
- [ ] Three-stage A/B build with builder attestations. Extend
      `arch-builder.sh` so B also compiles packages and its hashes are compared
      before signing.
- [ ] Release manifest and `SHA256SUMS.sig` generation, plus a user
      verification script and guide.
- [ ] Signing ledger format and a check that every published signature is
      listed.
- [ ] If media signing is chosen: an offline PKCS#11 sbsign/ukify path and
      SquashFS authentication for the setup ISO (generalize the Phase 4.2
      RAM-verified recovery design).

**R2: rehearsal**

- [ ] Run a full ceremony with throwaway tokens in QEMU-only scope.
- [ ] Drill expiry extension, standby activation, subkey compromise and
      lost-token recovery on a fresh installed guest, with negative checks.
- [ ] Drill a project-media dbx hash revocation on OVMF with owner KEK
      signing.

**R3: production keys**

- [ ] Hold the generation ceremony, store backups in separate locations, and
      commit the signed ceremony log and fingerprints via reviewed PR.
- [ ] Publish fingerprints on all decided channels.

**R4: first release**

- [ ] Follow the [releases](releases.md) checklist with three-stage
      attestations. Sign after the waiting period, upload, re-download,
      verify, and then announce.

**R5: physical hardware**, separate from R4

- [ ] Run the chosen Secure Boot strategy on named hardware: factory
      database backup, option ROM check, dbx contents, recovery media, and
      vendor reset path.
