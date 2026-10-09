# Phase 4 gaming platform handoff

Branch `phase4/gaming` starts at `2e4c1725e6ad9d70654ca32158cf524feabfc91f`.
This is the gaming planner and diagnostics implementation, not Phase 4 acceptance.
Work is isolated in the Codex `phase4-gaming/operating-system` worktree. No GPU,
Freestyle, boot, signing, transaction or repository-configuration files are changed.

## What users can do now

```sh
distroctl gaming --help
distroctl gaming doctor
distroctl gaming status --json
distroctl gaming enable core --dry-run
distroctl gaming enable tools --dry-run --json
distroctl gaming disable tools --dry-run
distroctl gaming mangohud-config
```

The first-run flow explains the feature, inspects prerequisites, and shows direct
package requests with pinned versions, current installed versions and blockers.
It does not install anything. `enable` and `disable` without `--dry-run` print
the proposal and exit 1, even as root and even if packages are already present.
The JSON proposal always has `executable: false`. Dry-run exits 0 when a proposal
can be produced; that means inspection succeeded, not that setup is possible.
Unknown features/flags and duplicate flags exit 1. Status/doctor exit 0 for a
successfully produced report even when observations are missing or unsupported.
Neither command starts processes other than read-only pacman queries.

After targeted transactions are integrated, the remaining flow is: review the
resolved transaction, install through the existing snapshot/boot coordinator,
complete its required boot confirmation, rerun doctor as the desktop user, open
Steam, let Steam initialize its runtime, then choose compatible games and Proton.
Until that integration exists, this branch cannot complete the install-to-play flow.

## Optional package design

The base OS package lists are unchanged. The embedded
[gaming catalog](../crates/distroctl/src/gaming/catalog.json) records direct
requests, dependencies/providers, package SHA-256, exact versions and database
hashes from the **2026/10/01** archive. `scripts/gaming_catalog.py` independently
downloads bounded repository databases over HTTPS, checks their pinned hashes,
then compares every selected package record. It never extracts or runs packages.
Core/extra hashes match the existing archive lock. The additional multilib hash is
`17e1a87e6ecd932e053e6553187a468820c9dbc2e3a0954162f7ca349c4d47cf`.

| Feature | Direct requests | Scope |
| --- | --- | --- |
| core (default) | steam, steam-devices, lib32-glibc, lib32-gcc-libs, lib32-alsa-plugins, lib32-pipewire, xorg-xwayland | Native Steam bootstrap, controller policy and selected explicit runtime prerequisites |
| tools | gamescope, mangohud, lib32-mangohud, gamemode, lib32-gamemode | Optional tools, also selectable individually |
| gamescope | gamescope | Nested compositor |
| mangohud | mangohud, lib32-mangohud | Optional 64/32-bit overlay |
| gamemode | gamemode, lib32-gamemode | Upstream temporary performance requests |
| lutris | lutris | Optional native launcher; Wine/runners remain separate |
| heroic | com.heroicgameslauncher.hgl (user Flatpak proposal) | No native archive package or automatic remote installation |
| streaming | obs-studio, xdg-desktop-portal-kde | Optional OBS with KDE portal integration |

Verified archive versions include Steam/steam-devices `1.0.0.87-3`, Gamescope
`3.16.31-1`, MangoHud/lib32-mangohud `0.8.4-1`, GameMode `1.8.2-3`, lib32-gamemode
`1.8.2-1`, Lutris `0.5.22-2` and OBS `32.2.2-1`. These are archive records, not
claims of current upstream releases. The archived Gamescope dependency is
`xorg-server-xwayland`, provided by the actual package `xorg-xwayland`; the catalog
retains that relationship rather than guessing a package name from the dependency.

Direct requests are **not** a transitive package solution. Steam's complete
dependency list is retained in the catalog, including its required 32-bit runtime,
Vulkan and GL virtual providers. Graphics selects the vendor ICDs, 32-bit GL
providers and Vulkan loaders. This branch does not choose a driver or change
multilib configuration. Tools do not implicitly request Steam. Optional launcher
selection does not imply any particular downloaded game runner is installed.

The native Steam package uses the Steam Runtime. No `steam-native-runtime`,
`STEAM_RUNTIME=0`, global `LD_PRELOAD`, automatic Wine fork, or unofficial client
is introduced. XWayland package presence plus advertised DISPLAY/session bus is
only configuration evidence. Connecting to the display and launching the client
still require testing. `steam-devices` provides upstream controller rules; no
world-writable devices, automatic group changes or controller-access claims.

## Transaction and repository boundary

`distro-transactions::pacman::Pacman` resolves/applies synchronized upgrades only.
It cannot safely accept arbitrary add/remove targets. The gaming code does not
call `apply`, `download`, refresh pacman metadata, invoke sudo, or install Flatpaks.
Its package query reuses the existing machine-output parser. Missing/corrupt or
inaccessible observations stay unknown. Repository names alone do not authenticate
signature policy, archive dates or local database content.

Integration requires a full target-aware dependency/provider/conflict resolver,
installed-version constraints and explicit install reasons, resolved package
hashes/sizes, signature policy verification, and execution through the current
MutationGuard, pre/post snapshots, signed boot generation and confirmation flow.
Keep the current systemd/bootloader/coordinator update refusals. Do not translate
these proposals into direct `pacman -S` or `-R` commands.

Disable cannot infer ownership from package presence. Before real removal it needs
a feature/install-reason ledger, reverse-dependency checks and a reviewed removal
set. Shared packages and manual installs must survive. Steam libraries, prefixes,
user settings and user Flatpaks are never part of an OS-feature removal proposal.

## Proton and GE

Prefer [Steam-managed Proton](https://github.com/ValveSoftware/Proton). Select the
version in Steam's compatibility settings or per-game Properties > Compatibility.
Steam owns download, update and runtime selection. No Steam credentials are read,
requested, stored, or used in unit tests. No client configuration is edited.

Discovery checks native Steam roots under XDG_DATA_HOME, `~/.local/share/Steam`,
`~/.steam/root` and `~/.steam/steam`, deduplicating canonical tool directories.
Bounded `steamapps/libraryfolders.vdf` metadata supplies additional library paths.
Default libraries use `steamapps/common/Proton*`; user builds use
`compatibilitytools.d/*`. A launcher file and parsed tool/compatibility manifest
are needed. An optional bounded `version` file is reported verbatim in JSON.
No metadata or launcher is executed. Names/versions never establish authenticity.
GE classification is a directory naming hint, explicitly marked unverified.

Metadata limits: 256 KiB regular files, 8,192 VDF tokens, depth 12, and 2,048
entries per inspected directory. Malformed metadata, unreadable paths and limits
produce issues. Final metadata symlinks and linked game/tool entries are skipped.
Normal Steam root/library links work; unsupported discovery layouts can be checked
manually in Steam. Flatpak Steam, symlinked compatibility tools and nonstandard
tool directory names are not covered. Missing evidence never verifies Proton.
Root and unknown-UID invocations skip user metadata. Run doctor as the desktop user.

GE remains optional. Use the established
[GE release channel](https://github.com/GloriousEggroll/proton-ge-custom/releases)
and its documented user-owned Steam installation mechanism. This branch has no GE
downloader and pins no disappearing version. For an independently acquired build,
verify the exact upstream repository/release, HTTPS origin, asset name and the
release-provided checksum before extraction; retain the tag, asset SHA-256 and
verification record outside the ISO. A checksum from the same release is integrity
evidence, not an independent publisher signature. Reject path traversal, absolute
paths, special files and escaping links when extracting into a new user directory.
An established tool manager may perform those steps under its own documented trust
policy. Restart Steam and select the build per game. Local discovery still cannot
authenticate that installation or verify its runtime.

Native Linux games avoid Windows translation but can have their own runtime
requirements. Proton-compatible Windows games need actual game-specific testing.
Games with anti-cheat restrictions, unsupported DRM/launchers, and untested games
must remain separate compatibility categories. Astraeus cannot bypass those
restrictions. Steam-managed content, shader caches, prefixes, user GE builds and
Flatpak updates can change independently of the OS snapshot or reproducible ISO.

## Optional tools

Gamescope stays opt-in. For a nested trial use the per-game launch option:

```text
gamescope -w 1280 -h 720 -r 60 -- %command%
```

This requests an internal resolution and nested refresh limit, not a physical
monitor mode. Output scaling can be set separately with upstream `-W`/`-H` after
checking that installed version's help. Nested X11/Wayland operation still needs
working Vulkan and appropriate driver support. Hybrid routing, NVIDIA behavior,
modifiers, display timing, VRR and HDR need hardware-specific validation. Gamescope
does not make HDR work by being installed. No HDR flags or compositor replacement
are defaults. See [upstream Gamescope](https://github.com/ValveSoftware/gamescope).

MangoHud supports optional Vulkan/OpenGL overlays. `gaming mangohud-config` prints
a minimal FPS, frame-time, GPU/CPU and top-left placement template. The user may
review it and copy it into `$XDG_CONFIG_HOME/MangoHud/MangoHud.conf` (normally
`~/.config/MangoHud/MangoHud.conf`); existing configuration is never overwritten.
Doctor only reports readability, leaving option interpretation to MangoHud.
Use `mangohud %command%` for one game. Some OpenGL applications need the upstream
`--dlsym` path; test rather than forcing global preload. Vulkan and OpenGL tests
must cover each installed architecture. Flatpak games require matching sandbox
extensions, not simply the host overlay packages. See
[MangoHud's configuration and usage](https://github.com/flightlessmango/MangoHud).

GameMode uses its upstream user-session service and `gamemoderun %command%`.
No custom Astraeus daemon, permanent CPU governor change, GPU clock setting,
overclock, or systemwide policy is installed. The separate runtime procedure may
run `gamemoded -t`, which temporarily exercises upstream behavior and therefore
does not belong in read-only doctor. Revert a game's opt-in by removing the launch
option. See [upstream GameMode](https://github.com/FeralInteractive/gamemode).

Heroic's [own installation documentation](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher#flatpak)
points to `com.heroicgameslauncher.hgl` on Flathub. This establishes the candidate
distribution, not the trust of a locally configured remote. Before any future
install integration, review the official HTTPS remote, signature verification,
app ID, origin, commit, permissions and runtime, then record the installed commit.
Never trust a remote merely because it is named `flathub`. Do not use `--no-gpg-verify`.
The base includes Flatpak but configures no reviewed remote; automatic Heroic
installation stays blocked. Lutris and OBS remain native archive proposals.
OBS capture/encoder support, optional plugins and sandbox overlays need their own
runtime evidence; the preset promises none of them.

## Structured observations and integration

`distroctl::gaming::GraphicsProvider::readiness() -> Graphics` is the narrow
adapter for the graphics worktree. Supply acceleration, Vulkan 64/32, VRR and HDR
checks. Each has `state`, `runtime` and an evidence/scope `detail`. Do not duplicate
vendor detection in gaming. Installed loaders alone cannot verify a working ICD;
software rendering cannot verify hardware acceleration. Details should identify
the tested GPU, architecture, session, command and evidence location. The CLI
currently uses `UnavailableGraphics`, so it reports unknown even if a driver is
installed. Replace that provider at the two CLI collection sites during integration.

Report and proposal JSON have schema version 1. Machine-readable schemas are
[status.schema.json](../crates/distroctl/src/gaming/status.schema.json) and
[plan.schema.json](../crates/distroctl/src/gaming/plan.schema.json).
Consumers should accept additive fields, inspect blockers, and handle unknowns.

| State | Meaning |
| --- | --- |
| not_installed | Explicit absence in the inspected package/filesystem scope |
| installed | Package or tool files observed; execution untested |
| configured | Readable config or advertised session prerequisites; not runtime proof |
| runtime_verified | Provider has actual execution evidence for this check |
| unsupported | Known unsuitable context, such as a headless Steam session |
| unknown | Missing, inaccessible, unconnected or insufficient observations |

`runtime` separately reports `untested`, `passed` or `failed`. The built-in probe
never assigns a runtime pass or failure from mere file presence. A missing Steam
launcher remains a separate missing-file check even when its package is installed.
Session environment variables cannot establish display authentication. Controller
access and Steam Runtime stay unknown pending execution. No overall ready boolean
or success checkmark is produced. Human output escapes control characters in
untrusted diagnostics; JSON retains structured data rather than terminal strings.

## Tests, ownership and remaining acceptance

Host tests cover optional feature resolution, missing/failed/unknown graphics,
32-bit dependencies, Steam missing/broken, headless/incomplete sessions, Steam/GE
metadata, extra libraries, bounded parsing, unsafe metadata links, tool presence,
configuration, package-query failures, blocked plans, JSON contracts and CLI exits.
No test installs Steam or needs credentials. Archive verification proves package
metadata availability only, not that all dependencies can be installed together.

Host results on 2026-10-08:

| Check | Windows | Linux (WSL, unprivileged) |
| --- | --- | --- |
| `cargo test --workspace --locked` | 86 passed | 94 passed, 1 privileged loopback test ignored |
| `cargo fmt --all --check` | passed | passed |
| `cargo clippy --workspace --all-targets --locked -- -D warnings` | passed | passed |
| `python3 -m unittest discover -s tests -v` | 61 passed, 36 platform/tool skips | 71 passed, 26 platform/tool skips |

The final metadata hardening was also retested in the Linux distroctl suite.
The online catalog check verified all three database hashes and all 15 package
records. Both Draft 2020-12 JSON schemas were checked with jsonschema 4.26.0, then
used to validate 18 actual CLI documents: status, doctor and both operations for
all eight features. JSON contract tests remain dependency-free in the Rust suite.
Linux skips include root-only archive resolution and absent signing/EFI tools;
these are not passing runtime or trusted-boot acceptance results.

The worktree adds a public module and a small dispatch/help change in distroctl.
Those `src/lib.rs` and `src/main.rs` lines are the expected overlap with the graphics
branch. No Cargo manifest/lockfile, base package list, pacman configuration, shared
architecture/roadmap, or runtime-validation harness edits are needed. The gaming
catalog is included by the existing deterministic source packaging rule for crates.
No network query happens at build time. New source changes ISO bytes as expected;
the full independent ISO reproducibility gate must be repeated by integration.

See [gaming runtime test design](gaming-runtime-tests.md) for the acceptance owner's
next steps. Real Steam startup, Proton execution, physical 64/32-bit graphics,
controller input, Gamescope, overlays, GameMode and OBS capture remain unvalidated.
Targeted transactions, authenticated GE acquisition, Flatpak installation, broad
discovery layouts, a Control Center and all Phase 5 work remain deferred.
