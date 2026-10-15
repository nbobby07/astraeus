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

Run real media gates sequentially for the newly built image, using separate output directories for `trusted`, `untrusted`, `unsigned`, `tampered`, `root-tampered` and `disabled`:

```sh
python3 scripts/validate/phase42-recovery-check.py trusted --gui-handoff \
  --build /home/ubuntu/p42/recovery-plain --baseline /home/ubuntu/p42/base-plain \
  --output /home/ubuntu/p42/recovery-check-plain/trusted \
  --ovmf-code /usr/share/OVMF/OVMF_CODE_4M.secboot.fd \
  --pristine-vars /usr/share/OVMF/OVMF_VARS_4M.fd \
  --source-commit FULL_CANDIDATE_COMMIT --iso-sha256 CANDIDATE_SHA256
```

These checks attach no installed OS disk. They use copied baseline VARS, except the deliberately disabled and different-owner cases, which create separate test VARS from the exact pristine template digest recorded by the baseline. A trusted boot waits for the live command channel described in `attention.json`, then verifies the firmware db certificate, live CLI, verified RAM copy and ephemeral root. Refusal cases require actual firmware rejection or a guard refusal followed by poweroff. Timeout never passes. Screenshots, serial logs, commands and mutation hashes remain; successful disposable mutation copies are removed to conserve validation storage. SIGTERM follows the owned-QEMU cleanup path. Each result covers only its named case and candidate.

The trusted case also verifies the exact packaged Control Center hash and runs real ordinary-user CLI status, feature/package inspection and blocked planning, plus an explicitly refused privileged live submission. Package versions, reasons, configuration, history and operation files must remain unchanged. None of these live-management results come from the unsigned setup ISO.

With `--gui-handoff`, the runner then stops using the command channel and publishes `attention.json` stage `trusted-recovery-gui`. The root validation controller may use that socket to drive the actual visible, packaged Control Center as the live desktop user. It must capture evidence of readable inspection, the live warning, blocked review and disabled Apply. Only after those observations should it atomically publish `gui-complete.json` in the case output directory:

```json
{
  "schema_version": 1,
  "source_commit": "FULL_RUNTIME_COMMIT",
  "distroctl_sha256": "EXACT_CANDIDATE_CLI_SHA256",
  "desktop_sha256": "EXACT_CANDIDATE_GUI_SHA256",
  "live": true,
  "firmware": {"SecureBoot": true, "SetupMode": false},
  "checks": {"inspection_visible": true, "live_warning_visible": true, "review_blocked": true, "apply_disabled": true},
  "evidence": [{"path": "gui/overview.png", "sha256": "ACTUAL_SCREENSHOT_SHA256"}]
}
```

The controller must supply actual observations and file hashes, never a synthesized pass receipt. Evidence paths must remain inside the case directory. The runner rechecks unchanged managed system state before shutting down. Without this flag, GUI acceptance is explicitly `NOT RUN` even when media and CLI checks pass.
