# Astraeus Control Center

The native Qt 6/Kirigami application provides Overview, Software, Configuration,
Activity, and a shared review screen. Run `astraeus-control-center` as the ordinary
desktop user. The application uses the same JSON CLI as terminal workflows.
It does not resolve packages or write privileged configuration itself.

Software selections and imported or adopted configuration create an unapplied
draft. Review shows package changes, dependency resolution, provenance, download
size, warnings, and blockers. Authentication happens only when applying that
reviewed plan. Export saves the currently accepted system configuration, not the
unapplied draft. Configuration imports are bounded to 256 KiB and read as the user.
In a terminal, `distroctl system export > system.toml` writes importable TOML;
`system adopt` prints a TOML draft. Add `--json` for the versioned desktop contract.

`pkexec` authenticates the narrow `distroctl system submit` command. Its policy
requires administrator authentication on every invocation from an active session.
The GUI supplies desired configuration and the expected plan digest on stdin.
The backend validates them again and starts the non-enabled
`astraeus-apply@.service` template. That service runs the same trusted distroctl
coordinator and exits after the operation. There is no persistent GUI daemon,
boot-time replay, or privileged graphical process.

Closing the window after submission does not cancel package mutation. Reopening
discovers the active operation from system status and polls its receipt and public
transaction history. Progress reflects durable phases, not an invented percentage.
Applying packages is not final success: `awaiting_boot` remains Restart required
until existing boot confirmation verifies the resulting system. Recovery remains
an explicit offline procedure; the app links to the installed recovery guide.

Live sessions support inspection and planning only. Protected package refusal,
pending reboot, unsupported features, authentication cancellation, unavailable
observations, and invalid backend replies are shown explicitly. Untrusted package
descriptions and diagnostics are rendered as plain text.

Build and test in a Qt 6.8+ Linux development environment with Kirigami installed:

```sh
cmake -S apps/control-center -B .build/control-center -G Ninja -DBUILD_TESTING=ON
cmake --build .build/control-center
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software ctest --test-dir .build/control-center --output-on-failure
```

The package build produces separate `distroctl` and `astraeus-control-center`
packages from one deterministic source archive. The CLI uses its native-alpm
feature in shipped Linux packages. GUI tests use a private mock executable passed
only through the C++ test constructor; production exposes no executable override.
The image pipeline includes the GUI in both installed and live package lists.

Unit tests cover read-only startup, draft invalidation, malformed and future JSON,
live-session refusal, authentication cancellation and denial, apply/result flow,
configuration import/export, keyboard review, and pending-versus-confirmed state.
Actual polkit prompts, worker survival, package mutation, reboot and recovery must
also pass the disposable installed-VM acceptance matrix. These unit tests do not
establish that acceptance or physical hardware compatibility.

Review fixtures under `apps/control-center/tests/fixtures` are serialized by
`tests/plan_fixture.rs` using the real Rust `ExecutionPlan` and management types.
The generator calls the model's validation before writing each executable plan.
Package sizes and hashes in those fixtures are synthetic test data, never runtime
or repository evidence. A blocked fixture keeps a complete plan but disables
execution. The native bridge rejects missing nested fields, mismatched target
lists, configuration disagreement, unsupported plan schemas, and any mutation
without both snapshot and boot-regeneration requirements before authentication.
Unavailable saved configuration leaves health/security observations visible but
disables editing and application until the recovery state is resolved.
