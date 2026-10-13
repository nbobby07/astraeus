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

## Desktop protocol

The desktop-facing `system ... --json` commands return objects with
`schema_version: 1`. Machine
output is on stdout; process failures use a nonzero exit code and stderr. A
successful preview can still be blocked: consumers must inspect `executable`
and `blockers`, not infer permission to apply from the process exit code.

| Command | Response fields used by the desktop |
| --- | --- |
| `system status --json` | `configuration`, `configuration_available`, `drift`, `live`, `active_operation`, `reboot_required`, `recovery_required`, `health`, `security` |
| `system features --json` | `features`, with each feature's ID, title, packages and supported flag |
| `system packages search/details/installed ... --json` | `packages`, containing name, version, description, repository, installed version, protection and selection flags |
| `system export/adopt --json` | `configuration` and its serialized `toml` |
| `system parse --stdin --json` | The same configuration response, after validating TOML from stdin |
| `system plan/diff --stdin --json` | `plan_id`, `executable`, `plan`, `blockers`, `warnings`, after resolving a JSON configuration from stdin |
| `system submit --json` | `operation_id`, `state`, nullable `transaction` and `error` |
| `system operation <id> --json` | The same operation shape, including the durable transaction once linked |

Package details appear inline in the Software results. Exact-name `details`
queries and search results use the same `PackageInfo` fields; there is no separate
set of hidden details. Configuration schema 1 accepts `packages`, `gaming` and
`providers`, with omitted collections defaulting to empty. Unknown fields,
duplicate requests and unsupported versions are rejected. Both the configuration
and submission input are limited to 256 KiB.

The reviewed `plan_id` is an opaque `sha256:` digest. A submission contains only
`schema_version`, `config` and `expected_plan`. It cannot supply commands,
repository URLs, package-file paths or privileged output paths. The worker
re-resolves under the authoritative locks and rejects a changed plan. An otherwise
eligible no-op preview has `executable: false`, an intact plan and no blockers; the GUI disables
Apply, while a repeated CLI apply can return success without creating a mutation.

The existing `history --json` command retains its array format for compatibility.
Its transaction records carry their own `schema_version`; new records and managed
execution plans use version 2, and the history reader accepts existing version 1
records. An empty history is `[]`, not a new response envelope. Management state
and `SystemConfig` use schema 1 independently of the snapshot management protocol
version 2. These version numbers describe different formats and must not be
substituted for one another.

Operation IDs contain 32 lowercase hexadecimal characters. `awaiting_boot` means
the transaction has reached its boot check, not verified success. The worker can
still be finishing its final bookkeeping; callers must let the service exit.
Only `succeeded` becomes **Verified complete**; `rollback_required` requires the
offline recovery procedure. Clients must not retry a submission automatically or
replay it after reboot.

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
