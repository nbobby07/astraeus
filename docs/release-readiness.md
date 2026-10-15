# Integration and first physical boot, 2026-10-15

The completed development stack has passed its recorded VM acceptance. It is
not a production release. The existing ISO can support an exploratory live
desktop session on compatible hardware with non-enforcing UEFI. It cannot
establish factory Secure Boot compatibility, accelerated vendor Vulkan, gaming
readiness, or installation support on a physical PC.

## What was completed overnight

- Phase 5 added ordinary-user observations, bounded CPU/memory/filesystem
  baselines, private results, exact export and comparison in Control Center.
- Follow-up fixes covered physical-machine comparison classification, peripheral
  power-supply privacy, management conflicts, keyboard focus, close/discard,
  packaged Qt tests, and exact floating-point JSON round trips.
- Restored pre-update roots now remain pending until explicit rollback
  finalization, and automatic boot confirmation requests the blessing service.
- Runtime `c38209c523e308d23ff622b32d9cd0ed42682962` passed two independent
  byte-identical builds and plain/LUKS2 enforcing VM acceptance, including the
  changed restored-root case. Report commit: `33d15a6`.
- Separate local commits prepared a physical qualification plan (`aa492c8`), a
  release-signing plan (`3aef36b`), and the SHA-2 migration fix (`b8ccd07`). The
  plans are incorporated here, with stale statements corrected. Dependency
  changes belong to a separate candidate and do not describe the accepted ISO.

The [Phase 5 report](phase5-acceptance.md) preserves the full results and failed
attempts. The older `08713df` image failed required gates and must not be used as
the accepted candidate. Original branches and evidence remain preserved.

## PR map

This is the inventory before consolidation. GitHub records the final PR states.

| PR | Purpose | Integration disposition |
| --- | --- | --- |
| [#7](https://github.com/nbobby07/astraeus/pull/7) | Graphics detection, gaming diagnostics and pinned image selections | Included through the complete feature stack; its original Proton limitations were subsequently addressed in Phase 4.1 |
| [#8](https://github.com/nbobby07/astraeus/pull/8) | Control Center, reviewed package/configuration changes, background worker and recovery | Included, together with Phase 5's restored-root corrections |
| [#13](https://github.com/nbobby07/astraeus/pull/13) | Performance workspace and final overnight VM evidence | Accepted runtime baseline for this integration |
| [#1](https://github.com/nbobby07/astraeus/pull/1) | Pinned GitHub checkout action v7.0.1 | Included; CI tooling only |
| [#9](https://github.com/nbobby07/astraeus/pull/9) | TOML parser 0.8 to 1.1 | Separate dependency integration; changes runtime build inputs |
| [#10](https://github.com/nbobby07/astraeus/pull/10) | serde_json 1.0.151 to 1.0.154 | Separate dependency integration; retain the float_roundtrip correction |
| [#11](https://github.com/nbobby07/astraeus/pull/11) | SHA-2 0.10 to 0.11 | Original PR fails both host checks; local migration fix must accompany the upgrade |
| [#12](https://github.com/nbobby07/astraeus/pull/12) | rusqlite 0.38 to 0.40.2 and bundled SQLite | Separate dependency integration; transaction storage needs fresh candidate qualification |

Source consolidation preserves the runtime, package recipes, installer, lockfile
and test code from `c38209c`. Documentation and CI updates do not rebuild the
ISO. Any later dependency, driver, signing or package-selection change needs its
own build identity and acceptance; the old ISO hash cannot qualify new bytes.

## Exact available candidate

| Field | Value |
| --- | --- |
| Local path | `C:/Astraeus-Phase5-Performance/candidate-c38209c523e3/candidate-A.iso` |
| Runtime source | `c38209c523e308d23ff622b32d9cd0ed42682962` |
| Length | 3,785,349,120 bytes |
| SHA-256 | `174197f2878e8bb03ddef517878550ebfa4f16ede30a50c177c06a905fac0c6c` |
| Image selections | `graphics_bundles = ["software"]`, `gaming_features = []` |
| Repository key | `27CCE96199D30A7ABA1BE86CC6722DAA8014EE89` |
| Repository key expires | October 16, 2026, 08:55:39 UTC, or 01:55:39 Pacific |
| Boot | Unsigned x86-64 UEFI setup ISO, no factory-trusted shim |

The local ISO hash and all 178 members of the committed Phase 5 evidence manifest
were rechecked during this integration. See [build inputs](evidence/phase5-build-c38209c/build-A/inputs.json),
[package list](evidence/phase5-build-c38209c/build-A/image-packages.txt), and
[public key metadata](evidence/release-readiness-20261015/repository-public-key.json).
The latter was extracted from the retained A build evidence archive, not inferred
from the older Phase 4.2 key.

Repository-key expiry can block package and database verification. Do not change
the clock, disable signature checks or substitute another image while retaining
this one's acceptance claim. An already built live desktop does not cease to boot
because its package key expires. Installation or management beyond that window
needs refreshed signed inputs and a newly qualified image.

## Today's live session

Record the PC, GPU, firmware Secure Boot state and intended USB writer before
choosing the boot procedure. The previously documented owner desktop is a
Ryzen 7 7800X3D with RTX 5070; that does not establish which machine is in use
today. NVIDIA open-module activation remains unsupported in this source.

1. Verify the ISO before writing. In PowerShell:

   ```powershell
   Get-FileHash -Algorithm SHA256 -LiteralPath 'C:/Astraeus-Phase5-Performance/candidate-c38209c523e3/candidate-A.iso'
   ```

2. Select the USB by its actual model and capacity. Writing an image erases the
   selected USB. Use a raw-image write and verify the written bytes; an extracted
   ISO or another boot manager does not preserve this image's tested boot path.
3. Use the firmware's one-time boot menu. This ISO will not boot under factory
   Secure Boot enforcement. Do not clear or enroll firmware keys to try to make
   the disposable VM keys work. Changes to the owner's Windows boot policy are
   a separate decision, including any BitLocker recovery consequences.
4. Keep this session live-only. Do not start Calamares, mount personal Windows
   volumes, apply packages, or run the VM-only installation/recovery harnesses.
   Record whether Plasma, display output, keyboard/mouse, network and audio work.
5. Run the existing ordinary-user observations below. A failed or unavailable
   probe is evidence, not a reason to weaken a guard:

   ```sh
   distroctl info --json
   distroctl status --json
   distroctl hardware --json
   distroctl graphics --probe --json
   distroctl performance status --json
   distroctl performance record --duration 30 --json
   systemctl --failed --no-pager
   ```

6. Photograph or save results to an explicitly chosen evidence location before
   shutdown. Live session state is temporary. Review logs for personal identifiers
   before publishing them. Shut down and remove the USB to return to the normal
   boot device.

The current image supplies software Vulkan, not AMD/Intel/Nouveau vendor Vulkan
bundles or NVIDIA's driver stack. A desktop may still use the hardware through
its kernel driver and Mesa OpenGL; the actual report decides. Do not equate a
visible desktop with accelerated Vulkan or gaming support. Live sessions allow
passive performance recording and intentionally refuse baselines.

## Work remaining before production

| Work | Completion needed |
| --- | --- |
| Physical image | Choose the actual GPU path, build with its pinned packages and a key valid for the test window, then repeat independent image and VM acceptance |
| Physical qualification | Real USB boot, display, networking, audio, input and GPU observations on named hardware; full GameMode and actual gaming tests where selected |
| Installation | Fresh Calamares UI acceptance for the final candidate, then separately authorized spare-disk physical installation and recovery |
| Dependency integration | Review the combined upgrades, pass Windows/Linux checks, rebuild and qualify the resulting candidate before attributing any ISO acceptance to it |
| Signing and updates | Decide release-key custody and rotation, trustworthy distribution, update/key-revocation delivery and the physical Secure Boot strategy |
| Release | Publish verified artifacts, signed checksums, provenance and an honest supported-hardware scope only after those gates pass |

The [physical plan](physical-qualification-plan.md) and
[signing plan](release-signing-plan.md) contain the detailed work. They are plans,
not completed controls. The preserved acceptance reports remain historical records
of their exact revisions even after their PRs are consolidated or closed.
