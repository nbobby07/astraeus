# Next hardware-test candidate, October 15, 2026

Status: **candidate VM acceptance passed** at the frozen runtime below.
No physical GPU, performance improvement or production-readiness claim is made.
The setup ISO remains incompatible with the owner's reported factory Secure Boot
policy; a separate boot-policy decision is needed before a physical session.

## Frozen inputs

- Source: `518ffede377615357cc7f86660fb57c75fce872d`.
- Source archive: 21,287,616 bytes, SHA-256
  `8c3990ee4974374445f9d64d9378e301de6a49866439bcc641f643f846b4c42f`.
- Expected-source manifest SHA-256:
  `839a92145bf5687e6cdc34175cbf7cd846dcb3ed6b661bbffe20022250d3ee66`.
- Archive: `2026/10/01`; source-date epoch: `1790812800`.
- Installed graphics: AMD and Nouveau; gaming selection: empty. Live graphics
  include native and 32-bit AMD, Intel and Nouveau Vulkan packages.
- Original authenticated Arch base:
  `Arch-Linux-x86_64-cloudimg-20261001.604814.qcow2`, SHA-256
  `360f0fa49db6813bdc8e35bed230a2dc2ae3567b7b5ab74719c0a706e4e34e87`.
  Release signer: `1B9A16984A4E8CB448712D2AE0B78BF4326C6F8F`.

Both final builders start from that original base and compile their own packages.
B consumes A's verified signed repository. No compiler outputs or installed root
are shared. This checks reproducibility with fixed signed inputs, not independent
signature generation.

| Identity | Recorded value |
| --- | --- |
| A host | `vm-a30caad091aa4b339d8171aaa10f4b03` |
| B host | `vm-350bd14005144e769d3e06c693e43048` |
| Remote run | `/home/ubuntu/next-r4/candidate-518ffede3776-r1` |
| Local artifacts | `C:/Astraeus-Next-Candidate/candidate-518ffede3776-r1` |
| Repository signer | `08AA130849B706CDB20AAA4484BD7DFCF71254F6` |
| Signer expiry | `2026-10-22T20:29:47Z` |
| Verified repository transfer | 53,360,640 bytes; SHA-256 `2aafa5f7379c47e6134702767e56d2c40dcfe2063f48f0117dcfd1e6aae226ed` |
| A/B ISO size and SHA-256 | 3,925,192,704 bytes each; `8c8a9f5a2627ab7ce4cdd8910e804d1b5d2b0fd17a824895c3add9f833ef94a9` |

The development signing identity must pass the 72-hour remaining-lifetime check
before compilation and ISO assembly. No production key or public release exists.

Worker handoffs were reviewed at these exact revisions before integration:

| Worker | Reviewed commit | Integration |
| --- | --- | --- |
| Graphics | `a27f078640710594b69ec9ff2680c39e040e5cbc` | `aac8480` |
| Dependencies | `fd8e6a0b8ce7a07a450cabd06143d8cc6d139f6b` | `4cbd585` |
| Live diagnostics | `bb1156b7444056f66837bf85247bc377ca52b2e3` | `ed81528` |

The frozen combined source received the independent package, native, Qt, image
and runtime checks below. No worker provisioned cloud resources in this window.

## Required final gates

| Gate | Result |
| --- | --- |
| Exact-source Windows/Linux CI | Windows/Linux and PR-title checks passed at `518ffed` |
| Independent complete A/B builds and packaged Qt tests | Both passed, each including Qt groups 22/13/16 with zero skips |
| Five independently compiled packages and complete ISO byte comparison | Passed; full `cmp` exit 0, all package hashes/manifests/repository inputs equal |
| Image audit, source/binary/package identities, public-test-material classification | Passed on A; live 751 and installed 736 package records exactly match manifests; no unclassified private-key blocks |
| Actual ISO kernel/initramfs modules and GB205 firmware content | Passed on A; Nouveau/amdgpu modules and GB205 FMC, bootloader and GSP content match the pinned packages |
| Native workspace, root publication/lock tests and signed backend fixture | Passed: 178 workspace tests, six ignored; explicit root publication (1), snapshot locks (2) and signed backend (1) passed |
| Fresh plain/LUKS2 Calamares UI installs | Both passed through actual welcome, partition, user, summary and finished pages; independent installed-disk verification passed without replaying provisioning |
| Two enforcing owner-trust cold boots per installed disk | Both passed, with distinct boot IDs, ordinary-user installed smoke and maintained-UKI trust checks |
| Actual desktop/performance CLI and GUI behavior, protected-state preservation | Passed on plain and LUKS2; all 17 protected-state fields unchanged |
| Management, authorization, update and failure behavior | Passed on both; metadata boot confirmation, authentication cancellation, native package locks, real signing failure and passive recording; encrypted worker survived desktop close/reopen |
| Signed-media trust/refusal checks and restored-root explicit finalization | Passed: all six media modes and six focused restored-root gates per layout; whole fault matrix was not rerun |
| Packaged ordinary-user live evidence collector | Passed on both live desktops; UID 1000, modes 700/600/700; failed probes and unavailable observations remain recorded as such |

Setup ISO acceptance uses observed OVMF SetupMode. Installed and recovery checks
use enforcing owner trust with disposable keys. Neither qualifies factory Secure
Boot. The owner's Secure Boot-on PC has not been changed or booted by this task.

A's public build evidence is `evidence-A.tar.gz`, 53,629,974 bytes, SHA-256
`7b7acf37539625190b4d4fcea6f93d046281a55f607f5411c1c7aa2a4c86843b`.
B's public build evidence is `evidence-B.tar.gz`, 53,626,227 bytes, SHA-256
`b1489797508442727d45d8daa8992c1a85d3f3e78841e44b99046830fbd65f92`.
Both local ISO downloads were checked against their full recorded SHA-256 and
compared byte for byte. The separate builders overlapped for 2,330 seconds. Native
evidence is in `native-final/manifest.json`; the image audit is in
`audit-A/result.json` beneath the artifact directory above. The initramfs SHA-256
is `47817a2bb64059eb6a78b593826c43ee7cf24f8a16d4d129339a279e9fc3c61f`;
the kernel SHA-256 is
`8ebc2c71271e000540f0a7545afd8e73504fcb724671f3d38c720b241842b901`.
These content checks do not prove either physical GPU can render.

## Runtime scope and evidence

Each fresh Calamares installation used a separate blank 32 GiB VM disk. Both
sealed baselines completed two ISO-detached enforcing owner-trust cold boots.
Desktop tests used separate clones of those baselines. Ordinary-user CLI checks
covered real recording, repeated bounded baselines, saved JSON precision,
compatible comparison, refusal of incompatible or overlapping measurements,
termination and scratch-file cleanup. Actual Qt interactions covered a complete
baseline, native file-dialog export, comparison, keyboard confirmation, ordinary
close, dirty-draft cancel/discard and forced process death during scratch I/O.
All 17 protected-state fields matched before and after these performance tests.
VM throughput variation is not evidence of a physical performance improvement.

Both installed desktop sessions passed metadata-only changes with regenerated
UKIs and confirmation on a new boot. A queued management operation interrupted a
running baseline while passive recording remained available. Native package
locks blocked baselines. Cancelling the actual administrator dialog submitted
nothing. Authenticated installation of `kcalc` and `libmpc` then reached an
injected missing-development-key failure and correctly required offline recovery.
The encrypted production worker survived closing and reopening Control Center
while held at its committed test barrier. Passive 60-second recordings completed
in both recovery-required sessions. These faulted clones remain retained.

Separate plain and LUKS2 recovery clones each passed the six focused
`awaiting-boot-restore` gates. Signed recovery restored the root and maintained
UKI, preserving home data. Automatic restored-root startup left the original
`awaiting_boot` transaction unchanged; explicit verified finalization marked it
`rolled_back` on a distinct boot ID. The broader fault matrix remains
`qualified: false`: this run did not repeat all 70 historical scenarios.
Actual recovery desktops refused baselines and accepted keyboard cancellation of
passive recordings. This is development owner-trust VM evidence only.

The packaged live collector completed as UID 1000 on both setup desktops. Its
output modes were 700/600/700. Graphics/status remained partial and both rendering
probe architectures reported no usable Vulkan device in these VMs. Those failed
or unavailable observations are preserved, not converted into hardware passes.

| Public runtime archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `518f4-p5p2-public.tar.gz` | 6,245,151 | `c4514f94e366dedeefc8fee7efcd330a41712997efaeb78977e49193ab4023ee` |
| `518f4-p5e2-public.tar.gz` | 7,572,086 | `c2056f1c0b60c9d4b349519ccd7eab9478ecf9f61bf18facaa1a10726af01453` |
| `518f4-p5gp2-public.tar.gz` | 15,174,621 | `25c094cfa591d2cc09578670d11f4d0e1b0ce964f54594bdf019583caf548d81` |
| `518f4-p5ge2-public.tar.gz` | 12,905,191 | `bb4067adfb6f7637c51238f18a14d9314cee5f8fb5334b8b7dc9f76f1050f919` |
| `518f4-p5rp2-public.tar.gz` | 6,330,151 | `c67da08d7e998e6e5da8d5259bbba9aa047bcd5b10809fe88d5d56bea55ece79` |
| `518f4-p5re2-public.tar.gz` | 6,795,792 | `c424ef37038abbf924d773fb36bcda7a063d7e74e5f238142fe4f113776633c8` |

Archives are under the local artifact directory above. Each archive hash and every
manifest member were verified before local extraction. Private credentials and
keys are excluded; full disks stay on the retained cloud hosts. The [curated manifest](evidence/next-candidate-518ffed/manifest.json) records
226 files copied without changing their bytes. Its runtime summary binds the
installation, desktop, recovery and media results to the exact source and ISO.

The separate media-only checks passed trusted boot, untrusted signer refusal,
tampered UKI refusal, unsigned UKI refusal, modified root-filesystem refusal and
Secure Boot-disabled refusal. The installed disk was absent in all six modes.
Trusted live CLI and actual GUI inspection left managed state unchanged; review
showed the live blocker and Apply remained disabled. Refusal cases required their
specific firmware/verification evidence, not merely a missing desktop.

Media evidence is `518f4-media-518-public.tar.gz`, 5,844,558 bytes, SHA-256
`f295769dca39021c8a02683cb41a48cda92dd4e1b3f6886e821dbaa9fafc22c3`.
Original media and disks remain retained. The frozen checker removes only its
own successful temporary mutation copies after recording their hashes.

## Retained diagnostic attempts

- `4a1d769`: B's snapshot-generation tests exposed clock-derived ID collisions.
  The earlier completed A image and both disks remain retained.
- `b48d533`: snapshot tests passed; two parallel performance fixtures then
  collided on their temporary-directory names. That failed disk remains retained.
  `94f3847` corrected the fixture counter and mutation-history collision checks.
- `94f3847`: all five independently compiled packages and both 3,925,188,608-byte
  ISOs matched. ISO SHA-256:
  `e46cb42ed197676369ca7d6da278e0b4478918f8af937c25fbdc8d7d23a410ad`.
  Audit, native and packaged checks passed. Both actual Calamares installs reached
  the successful finished page, but the UI adapter assumed a nested `lsblk` result
  and `[null]` mount lists. Its encrypted receipt check also confused the outer
  LUKS UUID with the decrypted Btrfs UUID.
- Corrected-adapter diagnostics passed the plain install and two enforcing cold
  boots, then encrypted adoption on an independent child of the real UI-installed
  disk. The encrypted original disk hash remained unchanged. Those checks informed
  `518ffed`; they do not replace this revision's final builds and fresh acceptance.
- Diagnostic service-launch, archive-symlink and transfer failures are retained.
  The boot-content checker now resolves absolute links inside the image root.
  Native launchers wait for their guest's actual exit. A failed local upload was
  replaced with a hash-pinned transfer restricted to the two validator VMs; its
  temporary endpoint and rules were removed afterward.

The original Phase 5 LIVE image already contained native AMD, Intel and Nouveau
Vulkan packages. Its separate installed payload selected software Vulkan. The
historical [Phase 5 report](phase5-acceptance.md) is unchanged.

## Costs, shutdown and remaining scope

Window: `2026-10-15T15:12:10Z` through `2026-10-16T03:12:10Z` at the latest.
New compute plus active storage is capped at $25, with $5 reserved for completion.
The guard pauses task resources at the $20 work allowance or deadline. Allocated
rates were rechecked against [Freestyle's pricing](https://www.freestyle.sh/docs/vms/pricing-and-limits);
allowances and credits are not deducted from the conservative ledger.

Final new compute plus active-storage upper bound: **$6.760684**
(**$6.77**, rounded upward to cents). This includes retained failed attempts and
conservative intervals ending only when pause was observed. The $5 reserve was
not needed. See [ledger](evidence/next-candidate-518ffed/budget-final.json).

Separate costs at the recorded checkpoint:

- New paused storage: $0.140932 accrued outside that cap.
- Prior Astraeus paused storage during this window: $0.376106, also excluded.
- Network: not reconciled by the available VM API; published rate is $0.02/GB
  crossing the datacenter boundary before allowances. Do not read the ledger as
  a complete invoice.
- Model/API charges: not metered by the cloud VM API and not included.

At `2026-10-15T23:44:39.905Z`, all seven new VMs and all eight prior Astraeus
VMs were confirmed paused. Their automatic restart is disabled. Prior VM runtime
counters were unchanged. Temporary transfer listeners were stopped and their
specific inbound rules removed; retained rules are outbound access. No retained
resource, disk or failure evidence was deleted. The independent budget guard
reported finished at `2026-10-15T23:44:45.044Z` after this confirmed pause state.

Paused storage continues accruing: 448 GiB new ($0.924672/day) and 512 GiB prior
($1.056768/day), before allowances. Unrelated cloud resources were not changed.
The [final inventory](evidence/next-candidate-518ffed/resource-inventory-final.json)
records each retained VM and its observed state.

Physical USB/GPU testing, the full GameMode self-test, physical installation,
production signing, trusted distribution and a public release remain unqualified.
The unsigned setup ISO cannot boot under the owner's reported factory Secure
Boot-on policy. No firmware change, USB flashing, host reboot, disk installation
or GPU passthrough was authorized or performed.
