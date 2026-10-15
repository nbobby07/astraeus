# Corrected plain baseline and metadata-only recovery

The fresh `ec3641b` candidate-payload installation passed two distinct cold boots with Secure Boot enabled and Setup Mode disabled, public maintained-UKI verification and actual tester Wayland logins. Initial installation used the approved existing SetupMode flow. This was production provisioning from the candidate payload, not Calamares UI acceptance.

All eight gates of the metadata scenario passed. Selecting the already installed nano package changed configuration and management metadata without changing packages or installation reasons. It created protected pre/post snapshots and a signed generation, refused same-boot confirmation and succeeded after a new enforcing boot.

Deliberate offline restoration booted the matching signed, RAM-verified recovery medium, restored the expected root and UKI, and booted the result. A deliberately wrong but internally consistent management state was rejected during finalization despite unchanged package versions. Correct finalization then verified restoration of packages, reasons, configuration, ownership, lock data and the home sentinel together. The snapshot contained no copied stale pacman lock. These are packaged-production-backend results, with no binary patch.

The 292-file public archive is `plain-metadata-ec-evidence.tar.gz`, 6,946,385 bytes, SHA256 `d0fcf80913b0b046858e7ff7196bba4cac2dfec649b9d028eaa0fb328adba372`. Every file verified after download. Private keys, credentials, VM disks and NVRAM files are excluded. Selected proofs and real QMP captures are retained here; the complete index identifies the rest.

A's complete 3,783,227,392-byte ISO also verified locally as SHA256 `2bfc2f021c2bbe0a31de19339909dea45ede0452aef8f5946cb740f3a6ad55ca` and is read-only. It was downloaded from byte zero in 29 individually verified chunks over normal TLS. No delta or previous image bytes were used.

Independent B is building. The corrected CLI package lifecycle, other seven fault scenarios, full installed GUI and LUKS2 acceptance remain required. This does not qualify the complete milestone or physical gaming hardware.
