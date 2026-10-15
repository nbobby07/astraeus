# Frozen runtime 6d10954, clean A

Clean A completed with 158 native Rust passes and five normal-run skips, plus 21 controller and 13 QML passes. Installed XZ and final live Zstd compression completed. All 151 source blobs and Cargo.lock match frozen Git. All 49 non-ISO export entries were verified locally. The full image audit passed; all seven audit-export files were verified locally.

- ISO: 3,783,223,296 bytes; SHA256 `13709ebc3213061daabf2a29db6911520e477e8608d26231ebd8018955629148`.
- Thin archive: 52,867,427 bytes; SHA256 `030d2dc5977f4c29bf0da1beda087f1123b16d50d96b73574a524bc1ae98cbcf`.
- Audit archive: 8,923 bytes; SHA256 `3297868ac3673d4d1e2376970f7db4734cd023655aa6b9b7bd15d4f06556d3c4`.

Both independent builds completed and their full ISO bytes compare equal. All five independently compiled packages, source packaging and seven build-input/manifests also match. Both normal Arch checks passed 158 Rust tests with five skips, plus 21 controller and 13 QML checks.

The complete A ISO was downloaded in 29 checked chunks, with one recorded network retry, and its full hash matches. It is read-only locally. B was independently built and compared remotely; its identical bytes are represented by a read-only local hardlink after that comparison, rather than a second download. Both closed build disks were retired after verified evidence exports.

Fresh plain/LUKS2 management, installed GUI and recovery acceptance are not implied by these image checks. Original keyring and firmware messages remain in the raw A build log.
