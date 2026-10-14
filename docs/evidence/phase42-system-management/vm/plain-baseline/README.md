# Fresh plain baseline

This is the accepted third attempt for runtime `0e8bb00`, using the immutable
`eb6587a1` validation harness. The production payload was installed in SetupMode;
the disposable owner was then enrolled. Two installed cold boots passed with
Secure Boot enforced, real SDDM/Plasma Wayland logins and the original installed
smoke checks. The maintained UKI trust receipts include production signature
and firmware revocation checks.

[baseline.json](baseline.json) binds the ISO, binaries, firmware, owner, sealed
disk and VARS. [result.json](result.json) records the successful run. The two
`boot-*` observations include actual desktop-session and management status output.
Ordinary-user security observations cannot read root-only ESP files; separate
privileged public-verifier receipts establish their signature and trust status.

This evidence does not qualify the Calamares UI, management transactions,
offline recovery, the LUKS2 target or physical graphics. Those gates are tracked
in the [acceptance report](../../../../phase42-acceptance.md).

The complete public archive contains 124 files, totals 6,083,576 bytes and has
SHA256 `17def386a7abf05ce00eb106abf23fa8a0314fb2f0e57ca21ef1a96404812dbf`.
Copied receipts preserve original bytes. No disks, private keys or credentials
are included. `SHA256SUMS` covers this curated directory except itself.
