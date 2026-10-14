# Fresh plain installation and CLI lifecycle

Runtime `6d10954`, using the independently reproduced ISO with SHA256 `13709ebc3213061daabf2a29db6911520e477e8608d26231ebd8018955629148`.

The candidate payload and production provisioning installed a fresh plain Btrfs VM. The approved initial installation used pristine SetupMode variables. Two subsequent cold boots enforced Secure Boot, verified the maintained UKI and reached actual SDDM/Plasma logins. This does not claim Calamares UI acceptance.

A separate disposable overlay passed all 12 CLI lifecycle gates with KCalc: candidate identity, ordinary-user read-only commands, invalid configuration, unauthenticated submission refusal, stale-plan refusal, complete install plan, real worker installation, pending-boot block, new-boot installation confirmation, real removal, new-boot removal confirmation, and history/personal-file preservation.

The complete 380-file public export is retained locally as `plain-6d-evidence.tar.gz`, 10,473,039 bytes, SHA256 `3f9be1c9c656d3c424008fb580299fe2a697ac08987967c204fca7b9e4a6167c`. Every indexed file was verified locally. Private keys, credentials and VM disks are excluded from this public archive. Base disks and private credentials remain on the validator for the remaining tests.

LUKS2, installed GUI, metadata/fault and recovery acceptance remain pending. Physical hardware is unqualified.
