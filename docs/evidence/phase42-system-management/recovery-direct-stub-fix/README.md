# Offline recovery from a direct UKI

Runtime `6d10954` passed metadata-only apply, unchanged package and reason maps,
same-boot confirmation refusal, and successful confirmation after a new enforcing
boot. Its offline restore then failed at `bootctl` before switching the root.
The signed RAM recovery medium boots a UKI directly and does not publish the
boot-loader `LoaderInfo` variable.

The snapshot backend now explicitly passes `--variables=yes` when clearing its
existing fixed OneShot, Default and Preferred loader preferences. Authorization,
offline layout checks, trust checks, locks and error propagation remain active.
This does not change Secure Boot keys. Systemd 262's
[exact implementation](https://github.com/systemd/systemd/blob/v262/src/bootctl/bootctl-util.c#L37-L73)
supports this explicit EFI-variable operation independently of `LoaderInfo`.

The new regression failed before the fix with the same boot-loader error. The
complete Windows workspace passed 142 tests and Clippy; the Linux native
workspace passed 159 tests with five fixture skips and Clippy. The raw Linux
logs are included. Corrected packaged images and fresh installed recovery tests
remain required; this directory does not claim VM qualification of the fix.

The first trial also exposed an overly specific same-boot error expectation in
the harness. Commit `23ab305` fixed that expectation and added durable-history
checks. The second trial passed that check. Both trial failures are preserved.

The complete 215-file public export is retained locally as
`faults-6d-evidence.tar.gz`, 7,577,815 bytes, SHA256
`ae83948e23f079275812b66674924c8211ea22483b63b9b2dc2c2cd80d5feaf1`.
Every exported file was verified after download. Selected matrix records, actual
recovery desktop captures and the full export index are included here. Private
keys and credentials are excluded.
