# Candidate recovery validation adapter

This validation code was added after the frozen candidate source archive. It adapts the tested RAM verification guard from the separate Secure Live worktree. It never imports that worktree, uses its USB artifacts, or enrolls firmware keys.

Run only after the new image A and an accepted fresh baseline exist:

```sh
python3 scripts/validate/phase42-recovery.py \
  --iso /path/to/candidate-A.iso --iso-sha256 CANDIDATE_SHA256 \
  --source-commit FULL_CANDIDATE_COMMIT \
  --baseline /home/ubuntu/p42/base-plain \
  --key /root/p42-plain-private/db.key \
  --output /home/ubuntu/p42/recovery-plain
```

Repeat separately with the LUKS2 baseline and its distinct db key. The builder reads the public certificate from the selected baseline and requires the private key to match it. It checks baseline source/ISO/CLI identities against the candidate and never accepts an older qualification.

The output `recovery.img` is a raw GPT disk with one FAT32 ESP starting at 1 MiB. It is at least 4 GiB and grows to a MiB boundary only if the verified root filesystem and UKI need more room. A single SquashFS larger than the FAT32 file limit is refused. The private key never enters the image. Extracted root filesystem staging is deleted only after the actual FAT image bytes have been checked against its digest.

Attach it as a separate **read-only** QEMU drive, bootindex 1. Keep the UUID-bound disposable installed disk at bootindex 2. Reuse the selected baseline's VARS and secure OVMF CODE. Do not enroll another key or modify firmware policy to make recovery boot. At least `manifest.minimum_ram_gib` RAM is required because the filesystem must be copied into RAM before verification.

`manifest.json` schema 1 has kind `phase42-ram-verified-recovery` and binds `source_commit`, `iso_sha256`, `image_sha256`, `image_bytes`, `rootfs_sha256`, `rootfs_bytes`, `uki_sha256`, `certificate_sha256`, `distroctl_sha256`, `command_line`, `minimum_ram_gib`, the builder digest and the originating guard digest. `qualified` stays false: building and mock tests do not qualify a boot.

The fault runner must observe the serial marker `ASTRAEUS_SECURE_LIVE_OK: SecureBoot=1 SetupMode=0 rootfs=verified-in-RAM`, the packaged live desktop marker, real firmware state and the exact live CLI hash before mounting the installed root. It must separately exercise unsigned/tampered UKI, altered SquashFS and disabled Secure Boot refusal. Authentication failure powers off without an escape shell.

Pure checks: `python3 -m unittest discover -s tests -p test_phase42_recovery.py -v`. They do not open disks, mount filesystems or boot a VM. No build or runtime test has been performed yet.
