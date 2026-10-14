Runtime c10ac6d passed native Rust158 and Qt21+13 package checks, then
failed final live compression with XZ data error9. A cold compression retry
failed similarly. An earlier retry-wrapper error is retained in the archives.
No candidate from these attempts is accepted. The source/profile inspection
was read-only and matched the frozen source. No kernelOOM or storageerror
was observed; the underlying complete-image failure remains unconfirmed.

Runtime code6d10954 changes live compression to Zstd15, leaving the installed
payload on XZ. Its actual compressor options now run in metadata and complete
fixture image reproducibility tests. FullPython209 suites pass on Windows
and Linux, with the recorded platformskips. Freshproduction builds, audits,
plain/LUKS2 VM lifecycle, GUI and recovery acceptance remain required.

Both validators are paused after failureevidence exports were verified locally.
The original public archives remain outside the repository with their hashes.
