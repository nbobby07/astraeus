# Current candidate and release readiness

The next candidate is built at `518ffede377615357cc7f86660fb57c75fce872d`.
Independent packages and full A/B ISO bytes match. Windows/Linux CI, image
auditing and packaged/native checks passed. Fresh plain/LUKS2 Calamares UI,
enforcing cold boots, installed desktop and management acceptance passed.
Signed-media and focused restored-root recovery acceptance also passed.
Physical hardware is unqualified.

The [next-candidate report](next-candidate-acceptance.md) records its exact gates,
retained failures, artifacts and costs. Historical reports continue to describe
their original source revisions. This is development work, not a public release.

## PR disposition

| PR | Purpose | Current disposition |
| --- | --- | --- |
| [#14](https://github.com/nbobby07/astraeus/pull/14) | Consolidate the previously accepted Phase 4.2/5.0 stack and release plans | Merged; starting main is `fbb5562c1fc418d26be7d7cc6de63ab9976cb488` |
| [#15](https://github.com/nbobby07/astraeus/pull/15) | TOML, serde_json, SHA-2 and SQLite upgrades, preserving report precision and stored formats | Included and qualified in #16; do not merge independently |
| [#16](https://github.com/nbobby07/astraeus/pull/16) | Fresh AMD/Nouveau candidate, live diagnostics, signing preflight, clock-collision fixes and renewed acceptance | Unified integration; candidate VM gates passed, final repository checks govern merge |
| #1, #7, #8, #9, #10, #11, #12, #13 | Original CI, graphics, management, dependency and performance branches | Closed during consolidation; original branches and evidence retained |

Phase 5.0's accepted runtime remains `c38209c523e308d23ff622b32d9cd0ed42682962`.
Its [acceptance report](phase5-acceptance.md) records the byte-identical builds,
plain/LUKS2 enforcing VM tests and restored-root recovery. Report commit
`33d15a6` is preserved. The new candidate has its own acceptance because its
runtime, package selection and signatures differ.

## Fresh artifact identity

| Field | Value |
| --- | --- |
| Local A | `C:/Astraeus-Next-Candidate/candidate-518ffede3776-r1/candidate-A.iso` |
| Local B | `C:/Astraeus-Next-Candidate/candidate-518ffede3776-r1/candidate-B.iso` |
| Runtime source | `518ffede377615357cc7f86660fb57c75fce872d` |
| Length, each | 3,925,192,704 bytes |
| SHA-256, both | `8c8a9f5a2627ab7ce4cdd8910e804d1b5d2b0fd17a824895c3add9f833ef94a9` |
| Archive pin | `2026/10/01` |
| Installed selections | `graphics_bundles = ["amd", "nouveau"]`, `gaming_features = []` |
| Live selection | Native and 32-bit AMD, Intel and Nouveau Vulkan packages, Mesa/Zink and diagnostics |
| Development repository signer | `08AA130849B706CDB20AAA4484BD7DFCF71254F6` |
| Signer expiry | `2026-10-22T20:29:47Z` |
| Setup boot policy | Unsigned x86-64 UEFI ISO; no factory-trusted shim |

A and B compiled their own five package archives from the frozen source. B used
A's verified signed repository for image assembly. Complete package archives,
manifests, repository inputs and ISO bytes match. This does not claim that two
independent signing operations produce identical bytes.

The accepted older Phase 5 LIVE image already contained native AMD, Intel and
Nouveau Vulkan packages. Only its separate installed payload selected software
Vulkan. The new installed AMD/Nouveau selection does not establish that the
RTX 5070 works. Neither image activates NVIDIA's `nvidia-open` stack.

## Owner's first physical session

The owner reports a Ryzen 7 7800X3D and RTX 5070, with **Secure Boot on** and
**BitLocker off**. Intended use is a Rufus-written live USB, with no installation.
Read-only Windows inventory also identified the Raphael integrated GPU and an
ASUS B650E MAX GAMING WIFI board. Firmware/encryption status is owner-reported.

The setup ISO is not bootable under the reported factory Secure Boot policy.
Installed VMs enforcing their disposable owner keys do not change that fact.
Rufus cannot grant firmware trust to an unsigned image. No firmware change,
enrollment, reboot, raw disk write, flashing or physical test is authorized in
this development window. The physical boot remains pending a separately chosen
boot-policy path; do not enroll the disposable VM keys on the owner's machine.

Once a physical session is separately authorized and its boot prerequisite is
resolved, start with display, keyboard/mouse, network and audio observations.
Keep internal volumes unmounted and do not start Calamares or apply packages.
The new packaged collector runs as the ordinary live desktop user:

```sh
astraeus-collect-live-evidence --output /home/live/first-boot-evidence \
  --image-source-commit 518ffede377615357cc7f86660fb57c75fce872d \
  --image-sha256 8c8a9f5a2627ab7ce4cdd8910e804d1b5d2b0fd17a824895c3add9f833ef94a9
```

The output directory must be new. Its `public.json` records typed observations;
review it before sharing. Keep `private/` private. The supplied source/hash fields
are operator declarations, not proof that the running USB matches the ISO.
A failed or unavailable rendering probe remains a failed or unavailable probe,
even when collection succeeds. Live sessions permit passive recording and refuse
performance baselines. Copy evidence only to an explicitly chosen destination.

Verify the ISO before a later authorized USB write:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:/Astraeus-Next-Candidate/candidate-518ffede3776-r1/candidate-A.iso'
```

USB identity, Rufus mode and readback verification remain part of the
[physical plan](physical-qualification-plan.md). An ISO hash does not verify the
written USB. A live-only observation does not qualify disk installation.

## Work still required for production

| Area | Remaining evidence or decision |
| --- | --- |
| Broader VM regression scope | Current candidate gates passed; the full historical 70-scenario fault matrix was not rerun |
| Physical compatibility | Real USB boot and both GPU architectures on named hardware; display, audio, networking and input observations |
| Physical installation | Separately authorized disposable disk, real firmware behavior, plain/LUKS2 install/update/rollback/recovery |
| Gaming/performance | Full GameMode self-test where selected, physical graphics/game tests, repeatable thermal/power-aware measurements |
| Signing | Release-key custody, rotation, revocation delivery, trustworthy distribution and a physical Secure Boot strategy |
| Release | Reviewed supported-hardware scope, signed checksums and provenance, final checks, and explicit publication authorization |

The [signing plan](release-signing-plan.md) describes production work that remains
unimplemented. The current signing-lifetime preflight and disposable validation
keys are development controls. No production identity or public release was
created. Repository-key expiry affects package verification, not the unsigned
live boot chain; never change clocks or disable signature checks to bypass it.
