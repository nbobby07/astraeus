# Distribution bootstrap

Phase 0 source foundation for an Arch-derived, x86-64, UEFI-only operating system.
The temporary identity lives in `distro/branding/project.toml`. The Phase 0 image
passed independent ISO byte comparison and UEFI/KVM Plasma Wayland validation.
See the [validation record](docs/validation.md) for exact artifacts and limits.
This remains version 0.0.1 validation media.

Implemented: Rust workspace, read-only `distroctl`, typed release metadata,
ArchISO profile for Plasma Wayland, signed local package repository tooling,
locked Arch snapshot inputs, source packaging, build automation and boot checks.
No installer, transaction engine, tuning daemon or GUI control center exists yet.

```sh
cargo test --workspace --locked
cargo run --locked -p distroctl -- info --json
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

All generated artifacts belong in `.build/` or `out/`, both ignored by Git.
The build refuses to reuse its output directory. Retain failed work for diagnosis
and choose a new output path when retrying.
