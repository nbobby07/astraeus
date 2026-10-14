# Phase 4.2 implementation and acceptance

Status: **in progress, not qualified for release**. A required gate that fails or
has not run leaves this milestone incomplete. This report will be updated with
candidate identities and exported evidence after the integrated acceptance run.

The current runtime candidate is `9825438d275c3037fcb41fbd768eebc71ef3f38c`.
Its source archive is 5,016,480 bytes with SHA256
`e1eec7917965b73893f013c896bb3028d819f1e362b698a398c85530b3e70c35`.
An independent Git archive and compression pass produced the same bytes. It fixes
missing live repository metadata exposed by the earlier candidate's boot tests.
Replacement build A and its full compressed-image audit passed. Independent
build B and fresh VM acceptance remain required.

The previous `0e8bb00e3edc5382fa177bf0017b2f8595ee8229` source archive was
4,991,208 bytes with SHA256
`f0d5c0019f5e9962506dbcc7359cdc2d98ae4d143528d1ede8943238ea83b0d4`.
Earlier stopped build attempts remain preliminary evidence and do not qualify this
candidate. Later validation-only commits are recorded separately from runtime.

The `85ad8f6` package build failed because its generated source archive omitted
two native policy inputs. Candidate `9b0fb7a` includes those files and adds an
archive regression covering literal Rust file inclusions. The failed build's
logs remain evidence, not a passing package gate. Host native checks below ran
on `85ad8f6`; this packaging fix has three passing focused tests, with clean
candidate package and image builds still required.

Candidate `9b0fb7a`, attempt A/r1, was interrupted by an outer-validator reset at
2026-10-13 22:30:39 UTC during native compilation. Its boot identity changed and
the filesystem reported an unclean restart; no normal compiler/build exit, OOM
event or graceful host shutdown was recorded. Source and base hashes, package
manager checks, qcow2 consistency and KVM checks passed afterward. This attempt
does not count as a completed build. Its thin evidence archive is
`interrupted-9b0fb7a-r1-A-evidence.tar.gz` (102,533 bytes), SHA256
`cc03796ed7bfe27270241c9e86f3cdffe53ecdc7ff27b4fa2e09ee166926a9da`.

Attempt A/r2 completed native CLI and Qt compilation, then failed its package
check because the generated source archive omitted the installer helpers used by
the Rust image-seeding test. The transaction suite recorded 52 passes, one failure
and one ignored fixture. The builder exited 4 and shut down normally; no package
or ISO is accepted from this attempt. Its thin archive is
`failed-9b0fb7a-r2-A-evidence.tar.gz` (83,821 bytes), SHA256
`eda0b7cc5f558196bb86094c687c7080837386f90d9c423d528554ac0203cbed`.

Candidate `30e2991` includes both helper scripts. Before starting another cloud
build, its real vendored package source archive was extracted and tested locally:
the native Rust workspace passed 155 tests with five ignored fixtures, and the
native desktop passed 21 controller and 12 QML tests with KDE/Breeze. The new
isolated archive regression reproduced the missing-module failure before the fix
and passed afterward. These are host checks; the pinned cloud package checks and
two independent image builds remain required.

The clean Arch build of `30e2991` passed the native Rust workspace, then failed
both Qt test groups. Arch's debug-path remapping prevented the controller tests
from finding source-relative fixtures. The QML group passed 11 of 12 checks;
its strict warning check caught the missing Sonnet spelling backend in the
minimal builder. No package or ISO is accepted from this attempt. Its thin
archive is `failed-30e2991-r1-A-evidence.tar.gz` (91,804 bytes), SHA256
`526ed122ca51d9a5e496543990ceeabb3f9fee8905c899871c917717962c0000`.

Candidate `620d1d3` copies the controller fixture into the test build directory
and declares pinned Hunspell 1.7.4-1 as the KDE spelling backend, without adding
a dictionary. The fixture failure was reproduced locally with Arch-style
debug-path remapping: the old controller run passed 3 checks and failed 18; the
corrected extracted archive passed all 21. Its 12 QML checks and 155 native Rust
tests also passed. Archive verification checks 118 package names against the
same three pinned repository database hashes. The clean Arch package build has
passed the same 155 native Rust tests and both Qt groups (21 controller and
12 QML checks). The split packages and Calamares were built and their repository
signatures verified. Its image build then failed after all 736 installed-root
packages and 29 hooks, before management seeding or compression. The metadata
reader rejected the valid empty URL fields in the two new Astraeus packages.
No ISO was produced. The failed A/r1 archive is
`failed-620d1d3-r1-A-evidence.tar.gz` (240,502 bytes), SHA256
`a10a1e44335c50d564d3dff77e677d77642f04c7779b142d4e7400c61a88bd6f`.

Candidate `17773af` fixes both the build-time metadata reader and the embedded
removal-integrity reader. Both now accept empty optional fields while preserving
strict section boundaries, duplicate rejection and identity whitespace. The
captured corpus passes both parsers for all 736 local records and 15,498 repository
records; installed-state observation and exact repository locking also pass for
all 736 packages. Its archive `metadata-620d-r1.tar.gz` has SHA256
`bf5b190a2347421172171e37da9da539f519d20992f88a31099cc179b7b09e40`.
The authoritative extraction used tar and Linux: an earlier Windows transfer
lost colon-containing names and was rejected by its record-count check.

Signed native fixture attempt 14 reproduces the old reader's incorrect retention
after a real libalpm installation with an empty URL. A separate fresh root with
the corrected reader passes the full install/removal fixture. The old negative
run and an initial fixture setup error remain preserved.

The `17773af` clean build was superseded during compilation after a focused GUI
test proved that dismissing an error hid subsequent errors. The exact pinned
Kirigami 6.30.0-1 template sets `visible = false` on Close, replacing the app's
original property binding. Candidate `298e12a` uses an explicit `Binding` and adds
a test that clicks the real close control before raising another error. The old
test fails and the corrected full QML suite passes 13 checks on Qt 6.10.2/Kirigami
6.24.0; the pinned Arch package also contains the triggering close behavior.
The backend is unchanged from the validated `17773af` source.

No completed package or ISO came from `17773af` A/r1. Its thin archive is
`superseded-17773af-r1-A-evidence.tar.gz` (117,489 bytes), SHA256
`86278cb1a050a0aadbafbe5aecfc04991950267cad25affb7b543ad688079dcc`.
The `298e12a` clean Arch build passed 155 native Rust tests with five ignored
fixtures, 21 Qt controller checks and 13 QML checks. Its CLI, Control Center and
Calamares packages were built and their package/database signatures verified.
Its image build failed after all 736 installed-root packages and 29 hooks:
`pacman-conf` refused the missing `/etc/pacman.d/gnupg` directory after build-keyring
cleanup. The exact installed binary reproduced that error on the closed failed
root; no ISO was produced. The thin archive is
`failed-298e12a-r1-A-evidence.tar.gz` (296,987 bytes), SHA256
`e4c6aa314210f88ac1525988da893e57ba8f14fb8eb2716ff332ad9a52f5d48f`.
It includes the final pacman configuration, exact stderr and pinned Qt test logs.
Installed-VM acceptance remains pending. The packaged CLI SHA256 is
`da09689543719261309adb0e41e796f12597e34f75d64865d6c09845e6e00e43`;
the Control Center SHA256 is
`a09c05d9706e2d2fc5ffa75214818e5006efe0ac6d20f4c37f7b465d9db01b41`.
The disposable repository signer is
`10A2160B80D3546E9E754A99875C9A330560CA57`, created 2026-10-14 00:50:43 UTC
and expiring 2026-10-15 00:50:43 UTC. It is separate from the VM Secure Boot key.

Commit `0e8bb00` removes the build keyring and leaves an empty directory with
Arch's normal `0755` mode. Native checks reproduce the missing-directory error
and prove that no key material is needed for configuration expansion. A separate
real initialization check shows that an existing `0700` directory stays private
and blocks ordinary-user public-key queries, while `0755` allows them and leaves
private-key paths protected. Payload tests check that build keys are removed and
the empty directory has the required mode even under a restrictive umask. The
full Python suite passes on Windows (126 passed, 64 platform skips) and Linux
root (186 passed, four skips). A new clean image is still required.

Before rebuilding, a disposable overlay over the read-only failed `298e12a` root
passed the full seeding boundary with its actual installed binaries. Adding only
the empty `0755` directory let `pacman-conf` expand the final configuration;
production seeding resolved and protected all 736 packages; the installed Rust
reader accepted the generated configuration, lock and ownership records. The
lower input hashes remained unchanged and all mounts were detached. The public
`seed-preflight-result.json` has SHA256
`eb622762e3aeeefa133eec5d232fef0a5a9106ece1d6b2f7e5bc9d9933b75352`.
This is a seeding regression check, not an ISO or boot acceptance result. The
first helper attempt stopped before creating an overlay because its restricted
PATH omitted Ubuntu's `blockdev`; that failed harness receipt is also retained.

The new `0e8bb00` A build passed 156 native tests with five ignored fixtures and
both Qt groups, built the split packages and Calamares, and verified its signed
repository. Its clean installed payload passed configuration expansion,
management seeding and the installed Rust reader, then completed the ISO.
`A-initial-seed-check.json` has SHA256
`939bb15cb3b9ff06802a0959dcb36a31b27561c06b44f54fb957f7bdbe99f41f`.
The CLI and GUI binary hashes match the earlier `298e12a` binaries, while the
package archives reflect the changed build inputs. This repository's signer is
`9AA267C32CFD7576040F95A75AE5520391EC79F0`, created 2026-10-14 01:43:52 UTC
and expiring 2026-10-15 01:43:52 UTC. This is a disposable validation repository
key, not a production release key or the VM Secure Boot certificate.

Image A is 3,636,389,888 bytes with SHA256
`2c047e270d6d99e0c0a6a09d81ade25752e4549457052f20d2fbecfa796a3072`.
Its exported copy passes the same whole-file hash. The live manifest matches all
691 installed live records and mkarchiso's final package list; the installed
manifest matches all 736 installed-root records. The 52,812,545-byte thin evidence
archive has SHA256
`bb43725b72b87152f8a89bfd319015df9bfea939a1c44a76692a45266aff5cb2`.
An interrupted ISO transfer was resumed through verified bounded chunks, then
the complete local file was hashed. The failed transport receipts remain saved.

The full image audit passed with result SHA256
`e2bdc2ea831cb24a869b2fb5a7a2ef3662f15e234c160b6230d1f2d394f116d8`.
It checks signed repository contents, both payloads, packaged binary/policy/service
identities, disabled worker instances, accounts, and absence of owner or validation
state. Ubuntu's older SquashFS decoder aborted during the first complete stream;
a task-local decoder from authenticated pinned Arch packages completed the scan.
That tool failure remains recorded.

The scan also identified embedded private-key blocks in three GnuTLS binaries.
All three whole files match their approved signed upstream packages, and all 12
unique blocks match public benchmark or cryptographic self-test constants in the
signed GnuTLS 3.8.13 source release. None matches the generated repository signer.
The audit retains these findings and classifies only those exact file and block
hashes. Seven controls passed, including rejection of changed or appended blocks,
copies elsewhere, and unexpected hardlinks. There is no filename-wide exemption.
The signed-source confirmation has SHA256
`ae67885f23f7339b977067afa88f4f184980e27cc778668d77a08a420037d212`.

The independent B build also completed successfully. Both full ISOs have the
size and SHA256 above, and direct `cmp` returned zero. All five independently
rebuilt package archives, live/installed/builder manifests, input records and
generated package-source archives match. Both images consume the same signed
repository published by A; the unsigned package comparison separately proves
that those packages were independently rebuilt. The comparison receipt has SHA256
`fd294105be7ffdcd7f0a814ae5b4f97851464b453a541922619f8018e0d623df`.
B's 52,722,243-byte thin archive has SHA256
`a2f2bc5f865a284b59af0d9bf68a7038bea50992a4be89aaa8ca8448663c8f8b`.
The [public build receipts](evidence/phase42-system-management/build/README.md)
include the comparisons, test summaries, manifest checks and image-audit proofs.
After remote equality passed, the verified local B ISO path was created as a
read-only hardlink to A. This local content deduplication avoids another identical
download; it does not replace the independent B build or its remote comparison.

Installed-VM acceptance remains pending. B preceded fresh plain and LUKS2 VM
creation because retaining a useful baseline would have consumed its required
35-GiB build reserve. VM acceptance uses separate disposable overlays after both
closed builder disks have been retired and resource guards pass.

The earlier immutable VM harness is `ad3f097d9475c52d18b4095fce5fc160d8edaa04`,
exported as a 368,640-byte archive with SHA256
`819e08cb18e69b8515ccfbf8cabbdb9ff1e88d0f1ad59d82ff06b1109bbb0abb`.
It adds real concurrent-submission, symlink-staging and systemd-start-failure
assertions to the interruption and abandoned-operation scenarios. Focused harness
tests passed on Windows (20 passed, four platform skips) and Linux root (23 passed,
one loopback skip); CLI subprocess rejection tests passed on both platforms.
These new assertions have not run in the candidate VM yet. The earlier `13f573cd`
harness archive remains preserved separately.

The current immutable VM harness is `eb6587a11df844407152cb1c2c29f4c5f750c479`.
Its 30-file archive is 378,880 bytes with SHA256
`340796d25e57c78178f2c41737f032ac94c893c8995fadf3c43b85c28c920236`.
It uses the Secure Boot capable firmware during initial SetupMode installation
and verifies the maintained UKI through the production provider, including dbx
revocations. Fault guards use public verification without requiring the private
key or a clean signing state that the tests deliberately disrupt. This check
does not substitute for running-root and generation confirmation. Focused helper
checks passed on Linux (56 passed, one skip) and Windows (52 passed, five skips).
These changes affect validation only; runtime and both ISO identities are unchanged.

The branch starts at `b1d16953ce5918b23c772e3ce99a35c7d37ac6b5`.
Work is isolated on `codex/phase4-system-management`; PR #7, the original
development branches and the signed USB artifacts are separate.

## Implementation boundary

`SystemConfig` manages selected named packages and gaming features. Omission does
not make an installed package unwanted. Pre-existing applications remain
protected; adoption creates a draft without changing installation reasons or
ownership. The build records the actual protected base/graphics closure before
installing optional gaming requests.

Removal also requires complete installed-file verification against the package's
MTREE SHA256 records. Locally changed or unverifiable packages are retained and
their removal ownership is relinquished. The review digest includes that evidence;
the locked worker checks it again immediately before committing.

The Linux-only native feature pins `alpm` 5.0.2 with its libalpm 16 ABI check.
Prepared native transactions provide the dependency closure. Adding applications
includes the synchronized upgrade set from the approved existing databases.
Preview does not refresh metadata. Every apply rechecks the reviewed digest under
the coordinator locks. Ambiguous providers require a selection; replacement,
driver-family, kernel, loader and coordinator transitions remain restricted.

Applied configuration lives at `/etc/astraeus/system.toml`. Ownership and
`system.lock` live under `/var/lib/astraeus/management` in the snapshotted root.
The lock records resolution provenance; it does not make the machine hermetic.
Configuration-only mutations require snapshots, signing and a new verified boot.
The v2 history format reads and transactionally migrates v1 history without
rewriting its historical records. Old snapshots remain inspectable; incompatible
recovery coordinators cannot restore the new management state routinely.

The unprivileged Qt/Kirigami app uses versioned JSON from the same backend as the
CLI. After review, pkexec authenticates a bounded submission. An operation ID
connects the app to the non-enabled systemd worker and durable history. The worker
has no automatic restart or boot replay. Sleep and normal shutdown are inhibited
while it applies. Live sessions permit inspection and planning only.

## Checks so far

| Gate | Current evidence |
| --- | --- |
| Host Rust checks | Current Windows and Linux CI passed. The clean Arch `9825438` A workspace passed 156 tests with 5 fixture/privileged tests ignored by the normal run. Native all-target Clippy also passed with warnings denied |
| Python, shell and signing | Full Python suites passed on `9825438`: Windows 143 passed/65 skipped, Linux root 204 passed/4 skipped. The 13 Linux file-integrity checks also passed explicitly. Shell syntax and native signing checks passed; raw logs and platform skips remain in the host evidence |
| Linux snapshot lock tests | Passed with a real libalpm-compatible lock descriptor and isolated Btrfs/FAT loopback filesystems |
| Native libalpm compilation | Current source passes with libalpm 16 in the Linux development environment and in the pinned Arch `9825438` A package build |
| Signed native package fixtures | Attempt 14 passed installation, synchronized upgrades, removal, shared/manual package preservation, metadata changes, providers, signatures, corrupt archives, hooks, file conflicts, locks, changed reasons and changed file contents. It also checks named conflicts, versioned missing dependencies, provider choices retained when preparation fails, and removal after libalpm writes an empty optional URL |
| Management publication failures | Real filesystem tests passed at the configuration, lock and ownership write boundaries; mixed state and retries are refused, and pending evidence remains available |
| Native desktop build and tests | 21 Qt controller and 13 QML checks passed in the pinned Arch `9825438` A build. Production startup loaded the KDE desktop style in earlier checks; replacement installed-VM backend acceptance remains pending |
| Plain and LUKS2 installed VMs with enforced Secure Boot | Historical `0e8bb00` plain baseline passed two enforcing cold boots and real SDDM/Plasma logins. Both replacement baselines and management/recovery acceptance remain pending |
| Image contents and signing-key audit | Replacement `9825438` A passed the full content/key audit and strict final compressed repository metadata/access checks in both live and installed roots |
| Two byte-identical candidate images | Passed on historical `0e8bb00`: all five independent package archives matched and full ISO `cmp` returned zero. Replacement `9825438` A built successfully; B and comparison remain pending |
| Physical PC and USB boot | Deferred by request |

The native fixture runner is `scripts/validate/native-alpm.py`. It creates a new
root, small signed packages and its own test keyring, then executes the production
backend from a native Rust test binary inside that chroot. It never replaces the
host package database. Earlier failed fixture attempts are retained separately.
These tests do not establish installed-VM boot, authorization or recovery behavior.

The approved VM setup uses the existing installer in SetupMode, then enrolls the
disposable owner and verifies enforcing installed boots. All management and
recovery acceptance runs must keep Secure Boot enforcing. Live inspection must
use the signed, RAM-verified recovery medium. The initial setup-mode ISO does not
qualify live management, and this milestone does not add an installer path that
runs with Secure Boot already enforcing.

The first fresh plain attempt stopped before partition writes because the chosen
plain OVMF build omitted the SecureBoot and SetupMode variables. A separate
diagnostic with no OS disk found mounted efivarfs and 33 other variables, confirming
that missing variables could not be treated as observed disabled firmware. A second
diskless diagnostic used the pinned Secure Boot-capable CODE, SMM and pristine
unenrolled VARS. It observed the required five-byte Boolean variables with
`SecureBoot=0` and `SetupMode=1`.

Validation-only commit `33f5c11` requires the same capable CODE for setup and
enforcing boots, enables the corresponding machine flags, and checks the mount
and actual variable bytes before permitting writes. Its 12 focused tests passed
on Windows and Linux. Runtime `0e8bb00` and both candidate ISOs are unchanged;
a fresh installed baseline is still required. The failed attempt's thin archive
has SHA256 `c76f2ce32c14573a28c8a869290cc17df2d927b0ceffae047445ecd182a2b2fa`;
the two diagnostic runs' archive has SHA256
`818d7ef6b872d3f3c2bc12eac5c1646b0d4fe5170c6e904fb14007367960dd6c`.

The second attempt installed the production payload and booted its signed UKI
with the intended certificate, `SecureBoot=1` and `SetupMode=0`. It then stopped
at the harness's bare `check-enrollment` call. Firmware dbx contains a SHA256
revocation entry, so the production provider correctly requires an actual image
for evaluation. No dbx entry was removed. A separate diagnostic overlay passed
the existing provider's `ready /efi` and UKI `verify` checks, including revocation,
while preserving the original disk and VARS hashes. That overlay was retired
after verified export; it is not an accepted baseline. The failed run's archive
has SHA256 `bac5eaadd3fb913d8668f9923bac8e461778b6ab7e6ef08cb9d67ffda13b0df4`;
the verifier diagnostic archive has SHA256
`bf16be57ffeae94f2c9809900b103963003b895f9595451da4af6cc6e6c8a218`.

The third fresh plain installation passed on `0e8bb00`, using validation harness
`eb6587a1`. Both installed cold boots observed `SecureBoot=1`, `SetupMode=0`, the
expected owner certificate and successful public image verification. Both real
SDDM/Plasma Wayland logins passed the original installed smoke, including network,
audio services, Btrfs boundaries and healthy management state. The boot IDs were
`744ddea3-4b19-48f9-957c-8163284e28e5` and
`7d916806-ff95-4fe8-894b-b34db4a98ba8`. Its sealed baseline manifest has SHA256
`5597c9fbefcc14d180ffee176fcd5f603f1c4f36e96e6867f741f1d0ff63f0ea`;
the 6,083,576-byte public evidence archive has SHA256
`17def386a7abf05ce00eb106abf23fa8a0314fb2f0e57ca21ef1a96404812dbf`.
The [plain baseline receipts](evidence/phase42-system-management/vm/plain-baseline/README.md)
include the manifest, public trust results and actual desktop smoke observations.
This validates production payload installation and boot readiness, not the
Calamares UI, package management, recovery or physical graphics support.

The matching signed recovery image passed its RAM-root hash and enforcing
firmware checks, then failed the ordinary-user installed-package query because
`/var/lib/pacman/sync` was absent. No live acceptance was claimed. Its failed
44-file evidence archive has SHA256
`6e6218c1092e8b464f01005850628463b834547935ef88f19b50d456caedf306`.
The authenticated ArchISO 91 source confirms that cleanup deletes this directory
immediately before compression. A separate diagnostic boot restored only the
five approved public database/signature files into the ephemeral root. Ordinary
user installed/search/details queries, a resolved KCalc plan, native Control
Center startup and the strengthened live smoke all passed. Package inventory,
original recovery-image bytes and baseline VARS remained unchanged. This was
diagnostic instrumentation, not qualification of either candidate. Its evidence
archive has SHA256
`b521f1ee4eae602a6950d189d2a0e57487d3089f0ca10a28516d1a2f35b9e056`.

Candidate `9825438` stages the verified public metadata outside the live root,
then restores it through the existing compression hook after ArchISO cleanup.
It verifies hashes before and after copying, sets root ownership and public read
access, and normalizes timestamps. It does not refresh metadata at boot or copy
a build keyring. Real compressed-image tests cover exact bytes, reproducibility,
missing signatures, changed databases and unsafe destination paths. An older
reproducibility fixture initially failed because it lacked the now-required
ArchISO inputs; that failure is retained, and the fixture now supplies the real
layout while preserving its time/cache divergence and full ISO comparison.
The final full Python suite passed on Linux root (204 passed, four skipped) and
Windows (143 passed, 65 skipped), 208 cases on each platform.

Before replacement builds, five closed superseded cloud files were retired after
exact path/hash/process checks and verified local exports: the two `0e8bb00`
ISOs, the second and third plain-attempt disks, and matching recovery image.
All small evidence, certificates, VARS and provenance keys remain. The earlier
images remain verified on the local D drive. The retirement receipt has SHA256
`bc91af027d87a0adcae33bd2b089ec00f8e7521de0f8bd68cc8c8859a168f75f`;
42,711,842,816 bytes were free afterward. Original USB artifacts were untouched.

The replacement `9825438` A build completed with exit zero. Its ISO is
3,645,478,912 bytes with SHA256
`558475af3eb219277786ded7379e1c80a12557064b2e26e245648f355011bb16`.
Closed logs confirm 156 native Rust tests, 21 controller tests and 13 QML tests
passed. The live and installed manifests match all 691 and 736 package records,
respectively. All 151 source hashes in the build-input receipt match the exact
frozen Git objects. That receipt has SHA256
`c580a59e4d6f4c71a4ab3f98472ac82cba74b7ef60ba2326f8d7d970b9a192b5`.
The locally verified 52,812,027-byte evidence archive has SHA256
`2c20b9974bb9d95cea849bee8bd1e62e17d8c82d069bb8a783842a98f41342b0`.
Its 49 non-ISO manifest entries were independently checked. The complete local
ISO also passed an independent whole-file hash check. Independent B and all
replacement VM acceptance remain pending.

The direct ISO transfer stopped after 2,374,172,672 bytes. The complete local
prefix matched the original image, and transfer resumed in individually checked
128-MiB chunks. The final whole-file hash matched with no chunk errors. Separately, the first
audit stopped before scanning because its new decoder preflight expected exit
zero from `unsquashfs -version`. The authenticated decoder returned the exact
expected text, empty stderr and exit one, matching
[upstream's version-only behavior](https://github.com/plougher/squashfs-tools/blob/4.7.5/squashfs-tools/unsquashfs.c#L4201).
The corrected check requires that exact result and retains all 57 authenticated
member checks. Five focused tests pass on Linux and Windows. The failed attempt
is retained; this validation-helper correction does not change the OS image.

The new disposable repository signer is
`9F6A6F116D78889664B0936292990E47A359C45A`, created 2026-10-14 05:17:30 UTC
and expiring 2026-10-15 05:17:30 UTC. This validation key is separate from the VM
Secure Boot certificate. The public GnuTLS test-material classification was
compared against this actual new signer; the new proof has SHA256
`936cb17eb1a07023d2387a701612edc104297de876fae535ea8d32fd8b4b55b7`.
This preparation does not by itself constitute the replacement image audit.

The subsequent complete image audit passed. Its result has SHA256
`932fdec80c7e9113fa8383676d0c1518d2bfdbe9078a23269461f97f34eb4754`;
the verified 8,913-byte audit archive has SHA256
`5a7dc414e17cd564698b1bb32689ca76851d7c33d4b403c45a6e1fdea3cfa151`.
It scanned all 139,384 live and 136,903 installed regular-file paths, checked the
signed repository and packaged identities, and found no unclassified private-key
blocks. Both compressed roots contain exactly the five approved repository
database/signature files, matching the actual build-input hashes and verified
repository. Their complete paths are root-owned and readable by ordinary users.
The actual decoder preflight and all five decoder and nine auditor tests passed
before the scan. Audit scratch was removed, and the original ISO hash remained
unchanged. Booted live behavior still requires fresh VM acceptance.

Phase 4.1's normal Proton diagnostic and recorded negative tests passed. GameMode's
full self-test and physical gaming qualification remain incomplete. Software
rendering is never evidence of physical GPU support.

## Validator budget

Additional compute and active storage are capped at $10. Published rates were
checked before starting: $0.04032/vCPU-hour, $0.0129/GiB-memory-hour and
$0.000086/GiB-storage-hour. The existing 4-vCPU, 16-GiB, 64-GiB validator costs
$0.373184/hour at these rates. A temporary replacement ran for 58 seconds at
4-vCPU, 8-GiB, 32-GiB before it was paused when the original became available.
No billing plan was changed. Final usage and exported evidence are pending.

Before candidate builds, the original validator was paused at 4,759 total runtime
seconds, up from 3,486. Combined additional compute and active storage for both
validators was below $0.14 at that checkpoint.

A later stopped checkpoint recorded 7,421 total runtime seconds on the original
validator. Including the temporary replacement, the conservative additional
compute and active-storage estimate was about $0.42. Building resumed afterward;
final usage remains pending.

Source: [Freestyle VM pricing](https://www.freestyle.sh/docs/vms/pricing-and-limits).
