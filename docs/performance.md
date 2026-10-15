# Performance baselines and diagnostics

Open Performance in Astraeus Control Center, or use `distroctl performance --help`.
All measurement and result commands run as your ordinary desktop user. They do
not request administrator authentication or change system settings.

| Command | Output |
| --- | --- |
| `performance status --json` | Schema 1, context, current sample, baseline blockers |
| `performance record [--duration 1..300] --json` | Bounded event stream; default 60 seconds |
| `performance baseline --json` | Bounded event stream; maximum execution budget 180 seconds |
| `performance list --json` | Schema 1, saved run summaries, explicit unreadable records |
| `performance show <id> --json` | Saved schema-1 report |
| `performance compare <before> <after> --json` | Compatibility, blockers, repetitions, medians, spreads and context changes |
| `performance export <id> --json` | Portable report on stdout; redirect it to a user file |

Run IDs are 32 lowercase hexadecimal characters. Inputs cannot name executable
commands, raw devices or scratch paths. Machine output stays on stdout;
diagnostics go to stderr. Without `--json`, queries print formatted JSON and
long-running commands print progress on stderr followed by the result on stdout.

## Events and saved results

Each stream line is `{schema_version:1,event:<kind>,data:<object>}`. Events are
`started` (ID, kind, requested_seconds), `phase` (name), `sample` and `result`
(the complete report). A nonzero process exit always means failure/cancellation,
even if a malformed producer claims completion. A missing final event never
means success. Samples use monotonic elapsed seconds, percentages, bytes, pages/s,
bytes/s, kHz, degrees Celsius and microwatts with explicit field names.

Reports record context, requested/actual duration, samples, workload definitions,
repetitions, warnings and failure. States are `incomplete`, `completed`,
`cancelled` and `failed`. An incomplete report is published before work begins.
Final publication uses a private temporary file, synchronization and atomic rename.
If final publication fails, the original incomplete report remains inspectable.

Storage is `$XDG_STATE_HOME/astraeus/performance`, falling back to
`$HOME/.local/state/astraeus/performance`. Directories are private, files have
mode 0600, symlinks/hard-linked result files are refused, and a user-owned lock
prevents simultaneous runs for that user. Reports are limited to 2 MiB; saved
samples are spaced to retain roughly 60 observations while live events remain
approximately once per second. Listing over 1000 runs asks the user to archive
old data manually. No automatic deletion or network upload occurs.

Stop/Ctrl+C and normal window closure request cancellation and preserve the result.
The process also stops when its calling GUI dies. SIGKILL or a host crash leaves
the initial incomplete record. Scratch files use Linux unnamed temporary inodes,
so closing the last descriptor reclaims them without deleting any user pathname;
see [open(2), O_TMPFILE](https://man7.org/linux/man-pages/man2/open.2.html).
An unsupported filesystem refuses the scratch test. Kernel I/O stalls can delay
termination; neither a missing final record nor a forced kill becomes completion.

## Fixed workload version 1

The suite observes 15 seconds of idle context, then runs each workload three times
with warm-up/cooldown phases. It usually takes about two minutes. CPU and memory
repetitions run for ten seconds; a scratch repetition must finish within ten
seconds. The complete suite has a 180-second execution budget.

* SHA-256 throughput: up to four threads, 4 MiB of total input buffers.
* Memory copy: two 64 MiB buffers, checked after each repetition.
* Filesystem sync/read: write one 128 MiB unnamed file, synchronize it, read it back
  and verify its checksum; repeat three times. Throughput counts write plus read
  bytes and includes synchronization and verification overhead.

Baselines require an installed managed system, at least 1 GiB available memory
and scratch free space, and no active package operation, pending reboot or
recovery requirement. These conditions are checked again during execution.
Reported temperatures within 5 C of a sensor's critical threshold stop the run.
Missing thermal sensors remain unavailable and do not imply cool hardware.
Passive recording is available in live sessions. The GUI also prevents applying
package changes while its measurement is active; it never changes worker policy.

## Interpreting results

Comparisons require completed baseline runs with the same workload definitions,
architecture, CPU model/count, memory capacity and virtualization class. Unknown
CPU model or virtualization classification blocks comparison. Different kernels,
binaries, governors, power context and graphics observations are shown alongside
results, since these differences may be the subject of an experiment.

Three repetitions provide descriptive medians and spreads, not statistical proof
of improvement. Zero denominators yield unavailable percentages. Background
activity, temperature, filesystem caching and virtualization affect measurements.
Matching CPU models do not prove two reports came from the same physical machine.
Software rendering and VM measurements never establish physical GPU performance.
No aggregate gaming score, sustained stress qualification or automatic tuning is
included. Exports omit hostnames, serials, usernames and process command lines.
