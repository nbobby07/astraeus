# Corrected candidate ec3641b, independent A and B

Clean A completed successfully and shut down. The complete read-only builder inspection and thin export were verified locally before retiring its disposable builder disk. All 151 source files and Cargo.lock match the frozen Git objects. The 691 live and 736 installed package records exactly match their manifests.

The package build passed 159 native Rust tests with five normal-run fixture skips, 21 Qt controller checks and 13 QML checks. Separate privileged host fixture results are recorded in the recovery-direct-stub-fix evidence.

The complete image audit passed, including compressed source/repository contents, public trust inputs, ordinary-user access checks and absence of private signing keys. Its seven exported files were all verified locally. Result SHA256: `7ea90d8ea46ffed217900218d2186207dcde4cfd501ccfc272070493b29c4141`.

The ISO is 3,783,227,392 bytes, SHA256 `2bfc2f021c2bbe0a31de19339909dea45ede0452aef8f5946cb740f3a6ad55ca`. Full local ISO transport completed with normal TLS verification, and the full file hash verified. Source archive: 7,605,028 bytes, SHA256 `c4fa142ecb8087090fa03da7c51eaa8e534a4ce10164654243ee97669543c96d`.

The first evidence collector retained a stale 6d cache-extraction path and refused the new candidate. The scoped replacement reused partial public files only after full hash equality, rehashed all 789 upstream archives and signatures, and detached its read-only NBD attachment. No image bytes changed. Existing staging keyring warnings remain in the build log; the final repository/access audit passed.

Independent B completed successfully. Full remote byte comparison exited 0 for both 3,783,227,392-byte ISOs. Five independently built packages, seven manifests and the generated source archive match. Both local image identities and thin exports verified; B uses a local hard link only after the independent remote comparison, as recorded in its deduplication receipt. Both disposable builder disks were retired after evidence verification. The fresh plain baseline passed two enforcing boots and all eight metadata-only lifecycle and offline recovery gates; see the plain-metadata-ec3641b evidence. The full milestone, installed GUI, LUKS2 and physical hardware remain unqualified.
