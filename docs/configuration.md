# Configuration boundaries

`distro/branding/project.toml` is build/release metadata only. It is compiled into
`distroctl` and rendered into the ISO's identity and boot labels. Renaming the
temporary codename requires editing this file, then rebuilding. Technical names
such as `distroctl`, `distro`, `DISTRO_BOOT` and `/usr/share/distro` remain neutral.

```sh
cargo run --locked -p distroctl -- validate distro/branding/project.toml
cargo run --locked -p distroctl -- info --json
```

Schema 1 rejects unknown fields, unsafe identity tokens, unsupported architecture,
invalid dates and an epoch that differs from archive-date midnight UTC. The version
also matches the workspace version, checked by the Python tests. Bump both for a
new source release. `info` reports compiled metadata, not current machine health.
JSON has the same typed fields as the manifest and contains no invented hardware
or readiness values. All CLI failures return nonzero and write context to stderr.

`archive.lock.json` records the complete repository database hashes and selected
direct package versions, including the image builder/compiler. Database hashes
pin the dependency universe; the real build resolves the transitive closure with
pacman and records `image-packages.txt`. This file is not the future `system.lock`.
Changing dates requires a reviewed lock refresh, package availability check and
new clean build. Do not fall back to current mirrors on archive failure.

Future user `system.toml`, desired state, diff/apply/adopt and lockfile formats are
deferred to Phase 6. Their architectural boundary is documented, but no parser
pretends that enabling encryption or Secure Boot in a file already configures it.

Profile sources under `distro/archiso` contain `@@TOKEN@@` substitutions handled
by the build script. The generated profile contains no unresolved tokens.
ArchISO's own `%ARCH%` and `%ARCHISO_UUID%` tokens intentionally remain for mkarchiso.
The generated live pacman configuration points at a signed repo embedded in the
ISO, never at an absolute path on the build host.
