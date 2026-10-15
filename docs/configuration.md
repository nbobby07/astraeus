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
pacman and records `image-packages.txt`. This build lock is separate from the
installed system's `system.lock`.
Changing dates requires a reviewed lock refresh, package availability check and
new clean build. Do not fall back to current mirrors on archive failure.

Phase 4.2 implements `SystemConfig` schema 1 for a selected subset: named
`packages`, supported `gaming` features and explicit `providers`. Omitted
collections default to empty; unknown fields, duplicate requests and unsupported
versions are rejected. Omitting a package does not request removal of everything
outside the selection. Pre-existing applications remain protected, and adoption
produces a draft without taking removal ownership or changing package reasons.

The CLI implements `system plan`, `diff`, `apply`, `adopt` and `export`. Apply
requires the reviewed plan digest, which the native backend rechecks under its
locks. The [Control Center](control-center.md) uses the same backend and adds
configuration import, review and authenticated submission. Live sessions support
inspection and planning only. Installed-VM acceptance is still pending; see the
[Phase 4.2 report](phase42-acceptance.md).

Applied configuration lives at `/etc/astraeus/system.toml`. Ownership state and
`system.lock` live under `/var/lib/astraeus/management` in the snapshotted root.
The lock records resolved package versions, repository and archive hashes, and
provider decisions; it does not make the writable system hermetic. Configuration
changes require snapshots, signed boot artifacts and boot confirmation even when
package versions do not change.

A general configuration language and broader desired-state management remain
deferred to Phase 6. The current schema does not configure encryption, Secure Boot,
services or performance policies by adding settings to this file.

Profile sources under `distro/archiso` contain `@@TOKEN@@` substitutions handled
by the build script. The generated profile contains no unresolved tokens.
ArchISO's own `%ARCH%` and `%ARCHISO_UUID%` tokens intentionally remain for mkarchiso.
The generated live pacman configuration points at a signed repo embedded in the
ISO, never at an absolute path on the build host.
