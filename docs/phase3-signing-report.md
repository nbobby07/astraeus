# Phase 3 Secure Boot signing handoff

Integration note: `phase3/integration` now connects the native provider,
coordinator guards, maintenance publication, health checks and offline public
policy reads. SHA-256 image revocations are checked through efitools; unsupported
dbx formats remain refused. See [integration](phase3-integration.md) and
[current acceptance](phase3-acceptance.md). The original branch handoff below is
retained as historical evidence and does not qualify an integrated ISO.

Branch: `phase3/secure-boot`.
Base: `6a8fda25d25df74215ed0bbe06b97804e053d950`.
The dedicated `a9e7/operating-system` checkout was confirmed clean at that exact
base before edits. No sibling worktree, boot-generation implementation or QEMU
validation harness was changed. The final commit is the commit containing this
report, also identified in the delivery message; no branch was merged.

## Delivered architecture

[ADR 0003](adr/0003-owner-secure-boot.md) was written before security-critical
implementation. Direct owner db trust authenticates systemd-boot and the UKI
through firmware image validation. A signed UKI includes the kernel, initramfs
and embedded command line. It does not authenticate writable root contents.
Firmware enforcement is a distinct acceptance gate.

The implementation uses OpenSSL, sbsign, sbverify, ukify and ukify's existing
pefile dependency. Policies pin the SHA-256 of the public certificate's DER
encoding, check certificate validity and key agreement, enforce private file
permissions, and support local certificate denial. Development, disposable OVMF
and machine-owner purposes are distinct; production distribution is unsupported.
PK/KEK administration stays offline. The test preparer creates distinct short-lived
PK/KEK/db identities and EFI signature lists, and performs no enrollment.

## Signing, validation and installer integration

`astraeus-secure-boot` checks x86-64 PE32+ EFI application structure and required
UKI sections, signs a private input copy, verifies its signature, and compares
section content. It syncs image, original input and receipt before publishing a
candidate directory. Incomplete staging and unconsumed candidates block reuse.
It never writes the active ESP, so prior boot material remains untouched.

The installed mkinitcpio preset selects private staging whenever policy, retained
signing state or firmware-reported SecureBoot requires it. The packaged post hook
signs that output. A missing signer cannot select unsigned fallback. A
PreTransaction/AbortOnFail guard and installer preflight refuse legacy boot writes
until the generation integration is connected. Unprovisioned development systems
retain the original UKI path. Existing systemd/bootloader update restrictions and
the transaction/snapshot implementation are unchanged.

`distroctl security status --json` delegates to read-only inspection. Unknown
firmware variables remain unknown; signatures and firmware state are separate.
Exact certificate membership in PK/KEK/db/dbx can be observed. The narrow
`check-enrollment` command refuses missing/removed/revoked trust and any nonempty
or unavailable dbx requiring full firmware policy evaluation. No host-side dbx
emulation or enforcement claim is made.

## Tests executed

| Command/check | Environment | Result |
| --- | --- | --- |
| `cargo test --workspace --locked` | Windows, Rust 1.96.0 | 53 passed |
| `cargo fmt --all --check` | Windows, Rust 1.96.0 | PASS |
| `cargo clippy --workspace --all-targets --locked -- -D warnings` | Windows, Rust 1.96.0 | PASS |
| `python -m unittest discover -s tests -v` | Windows, Python 3.11 | 45 passed, 27 platform/tool skips |
| `python3 -m unittest discover -s tests -v` | WSL Ubuntu 26.04, root | 71 passed, one existing qemu-img skip |
| Shell syntax, including preset/post hook and package recipe | WSL Bash | PASS |
| CLI read-only status smoke | WSL, no policy or EFI variables | PASS; unknown firmware and no enforcement claim |
| Source archive determinism/private-key exclusion | Python suite | PASS |
| `git diff --check` | Windows | PASS |

The 15 native security tests use actual OpenSSL 3.5.5, sbsigntools 0.9.4, efitools
and ukify 259.5 with synthetic UKIs and packaged systemd EFI files. Their temporary
keys live under private `/root/astraeus-signature-tests-*` directories and are
cleaned up by the fixtures. These are signature and filesystem tests, not boot
tests. CI now installs the native tools and runs these fixtures as root in its
disposable Linux runner, with an explicit prerequisite assertion. That CI change
has not yet run remotely. Local logs are in ignored `out/secure-boot/`.

Negative coverage includes malformed policy, duplicate fields, wrong pin, revoked
identity, missing key, mismatched private key, expired validity at a simulated
verification time, unsigned images, wrong-key UKIs/loaders, tampered content,
wrong architecture/subsystem, missing required sections/artifacts, receipt
tampering, nonzero signing failure, interruption, unsigned signer output,
incomplete staging, receipt-write failure, concurrent signing, unsafe owners,
permissions, symlinks/hardlinks, prior-artifact preservation, removed/unknown
firmware trust, suppressed tool diagnostics, deleted-policy fallback prevention,
and installer refusal before boot/configuration writes.

## Key handling and reproducibility

No private key was placed in the repository, package inputs, ISO or committed
evidence. Private extensions are ignored by Git. Package input preparation uses
an explicit helper/template/document allowlist; the regression fixture proves
adjacent private material does not enter its source archive and changing that
material does not change archive bytes. Production construction never invokes
the random test-key generator. Machine provisioning stays outside deterministic
ISO inputs. Two complete ISO builds have not been rerun for this branch.

## Required work by Chat 2

The [integration contract](secure-boot.md#signing-and-generation-interface) defines
fixed candidate paths and versioned receipts. Connect candidate consumption under
the existing mutation and signing locks, bind kernel/root/transaction semantics,
reverify the ESP copy before selection, retain the prior root/UKI pair, and include
signature checks in health, boot confirmation and offline recovery.

Replace the explicit legacy-write guard with the qualified generation handoff.
The present branch intentionally blocks package mutation once signing is required.
Preserve both installed loader copies and bind signed-loader source bytes to the
packaged loader before adapting Phase 2's unsigned byte comparisons. Signing alone
does not authorize systemd/bootloader upgrades; retain that restriction until
preservation and recovery are proven.

## Required work by Chat 3 and remaining limits

Use a fresh disposable OVMF VARS copy, enroll test material only there, and prove
the actual firmware loader/UKI chain enforces signatures. Run unsigned, wrong-key,
tampered and revoked/removed-trust negative boot tests independently for loader
and UKI. Qualify installation, updates, recovery and Phase 2 regressions on the
pinned Arch mkinitcpio 42.1/systemd 262 stack after Chat 2 integration.

No enforcing OVMF boot, real hardware enrollment, full ISO rebuild, power-loss
qualification or Linux Rust run was performed here. Online db keys remain exposed
to a compromised root and are retained in protected root snapshots. Automatic
rotation, lost-key repair, production key distribution and firmware dbx updates
are unsupported. Recovery trust and overlapping-key rotation procedures are
documented in [the operator guide](secure-boot.md#rotation-lost-keys-and-reproducibility).
