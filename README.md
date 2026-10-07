# Distribution bootstrap

Phase 1 installation foundation for an Arch-derived, x86-64, UEFI-only operating system.
The temporary identity lives in `distro/branding/project.toml`. The Phase 0 image
passed independent ISO byte comparison and UEFI/KVM Plasma Wayland validation.
See the [validation record](docs/validation.md) for exact artifacts and limits.
Version 0.1.0-dev passed Phase 1 validation: independent byte-identical ISOs,
fresh encrypted/plain Calamares installs, and two disk-only boots of each installed
Plasma Wayland system with all four hardware/status commands and healthy services.
Qualification covers the recorded UEFI/QEMU/KVM target; this is a development build.

Implemented: Rust workspace, read-only `distroctl`, typed release metadata,
ArchISO profile for Plasma Wayland, signed local package repository tooling,
locked Arch snapshot inputs, source packaging, build automation and boot checks.
Phase 1 adds Calamares integration, a separate installed package payload, Btrfs/
optional LUKS2, systemd-boot/UKI provisioning, Rust hardware detection and real
read-only status output. No transaction engine, tuning daemon or control center.

```sh
cargo test --workspace --locked
cargo run --locked -p distroctl -- info --json
cargo run --locked -p distroctl -- status --json
python3 -m unittest discover -s tests -v
python3 scripts/bootstrap.py verify-archive
```

Use `python` on Windows if that is the installed command.

- [Architecture and decisions](docs/architecture.md)
- [Build and sign an ISO](docs/building.md)
- [Configuration boundaries](docs/configuration.md)
- [Security and signing](docs/security.md)
- [Tests and acceptance gates](docs/testing.md)
- [Roadmap](docs/roadmap.md)
- [Validation record](docs/validation.md)
- [Installation](docs/installation.md), [storage](docs/storage.md), [boot](docs/boot.md)

All generated artifacts belong in `.build/` or `out/`, both ignored by Git.
The build refuses to reuse its output directory. Retain failed work for diagnosis
and choose a new output path when retrying.
