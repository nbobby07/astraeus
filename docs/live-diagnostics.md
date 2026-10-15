# First live-session evidence

Run this as the ordinary Plasma desktop user. This is a diagnostic snapshot, not
physical hardware acceptance. Fixtures and VM results do not qualify a physical
7800X3D, RTX 5070, or any other machine.

## Collect

Choose an existing writable parent on an evidence USB or in the live session.
The final directory must be new, absolute and free of symlink components or `..`.
The collector refuses root, creates no parent directories, and never overwrites
an earlier run. A live-session directory disappears at shutdown. Copy the results
to your chosen evidence medium before then. Do not mount personal Windows volumes.

For a source copy (Python 3.11+, standard library only):

```sh
python3 /path/to/collect-live-evidence.py --output /path/to/evidence/run-1 \
  --image-source-commit c38209c523e308d23ff622b32d9cd0ed42682962 \
  --image-sha256 174197f2878e8bb03ddef517878550ebfa4f16ede30a50c177c06a905fac0c6c
```

Those identity arguments describe only the existing candidate listed in
[release readiness](release-readiness.md). Use the actual build manifest and
verified ISO hash for a different candidate. They are operator assertions, not
an automatic verification of the running image. Omitting them records unavailable
identity. The collector's own SHA-256 and distroctl's binary SHA-256 (when exposed
by performance status) distinguish the tools from the asserted image source.
The compiled `distroctl info` metadata does not contain a runtime Git SHA.

When packaged, replace `python3 /path/to/collect-live-evidence.py` with
`astraeus-collect-live-evidence`. The old candidate ISO does not contain this new
command. Carry the script on the selected evidence medium and invoke it directly;
do not install packages into the live session to obtain it.

`public.json` contains schema-1 projections of:

- `distroctl info`, `status`, `hardware`, `graphics`, and `performance status`,
  each with `--json`. Hardware includes CPU counts, RAM, GPU PCI vendor/device
  IDs, recognized kernel drivers, boot-VGA and UEFI/VM observations.
- The existing 64-bit and 32-bit Vulkan helpers, each run once. Their schema-1
  results retain numeric device/driver IDs, software classification and rendering
  state. Graphics inventory is collected without `--probe`; correlate the separate
  helper results yourself. Package presence and a visible desktop prove no GPU
  acceleration. These are brief rendering probes, not benchmarks.
- A fixed package-version selection, including kernel, firmware, Mesa, Vulkan,
  NVIDIA and Plasma packages. Missing packages are explicitly unavailable; a
  nonzero `pacman -Q` exit can still yield useful partial versions.
- Failed system services, using `systemctl --failed --type=service`. Known
  desktop/live service names are retained. Other valid failed rows are counted
  under `withheld_names`; descriptions and custom/instance names are excluded.
  A failed query produces no empty-list success claim. User services are not queried.

Each command has its fixed argv, actual exit code (null when not launched),
elapsed seconds, outcome, projected data and unavailable field paths. Timeout
and output-limit results discard partial output. Malformed JSON or an unsupported
schema is reported without raw text. Null, invalid and missing selected fields
are listed as unavailable. Nothing here asserts that a successful process means
the hardware passed. Check the helper status and rendering fields too.

Each of nine commands is bounded to 30 seconds and 1 MiB of combined output.
Timeout/output overflow kills the launched process group, including inherited-pipe
descendants. Cleanup waits at most two additional seconds per command. An
unkillable kernel wait is recorded as `cleanup_timeout` with no invented exit;
the OS may retain that process until the kernel operation returns. A normal run
takes seconds; the query budget including cleanup is about five minutes.
No sudo, benchmarks, performance recording, installation, configuration changes,
disk/firmware writes, uploads or VM harness invocation occur.

## Privacy and limits

Only `public.json` is intended for review and possible sharing. Raw command output,
stderr, journals, dmesg, environment values, network details, storage identifiers,
DMI strings and arbitrary CPU/GPU model strings are not published. Custom version
suffixes are omitted rather than risking local host/user names. Numeric GPU IDs
remain useful even when the display name is absent. Unknown fields from future
schemas are ignored; selected unavailable fields stay null, never invented.

`private/` is the redirected HOME/cache location for child processes. Shader caches
are disabled, but driver implementations may still leave private files there.
Do not share that directory. The collector does not offer raw-log collection.
If you separately choose to retain raw diagnostics or photographs, store them
privately and review them for serial numbers, MACs, SSIDs, usernames, hostnames,
secrets and personal log text before sharing. Review `public.json` too, especially
operator-supplied identity. No automatic upload or archive is produced.

The directory uses mode 0700 and new files use a restrictive umask. FAT/exFAT media
may not enforce Unix permissions; physical custody still matters. Choose a trusted
parent directory that other users cannot replace while collection runs. Probes run
installed local tools/drivers in your desktop environment, not a filesystem sandbox;
the collector redirects caches and performs no intentional writes elsewhere.
Missing access, tools, firmware or drivers stay unavailable. Collection cannot
diagnose a failure before userspace or an inaccessible desktop; retain a private
photo and a short manual symptom record instead. An interrupted run may leave an
incomplete directory; use a new name to retry. Exit 0 means the report was written,
not that observations passed. Exit 2 means invocation/destination failure; 130 is
interruption. Do not weaken VM-only guards to obtain additional data.

## Owner checklist: 7800X3D / RTX 5070

1. Confirm the exact image and checksum from its build handoff. On Windows, use
   `Get-FileHash -Algorithm SHA256 -LiteralPath 'C:/path/to/candidate.iso'` and compare
   the full digest and length. Keep identity separate from the collector revision.
2. Select the intended USB by model and capacity in Rufus. Writing erases that USB.
   Use raw/**DD Image mode**, not extraction/ISO mode or an added boot manager.
   Verify a readback of the ISO-length bytes against the ISO before booting and
   after testing. DD mode alone is not readback proof; Windows can alter exposed
   partitions. Investigate mismatches. See the [Rufus FAQ](https://github.com/pbatard/rufus/wiki/FAQ#im-using-an-iso-with-a-checksum-validation-test-and-the-test-fails-despite-using-dd-mode-in-rufus).
3. Owner-reported state is **Secure Boot ON, BitLocker OFF**. Recheck locally before
   booting. The candidate is unsigned and has no factory-trusted shim. Rufus does
   not grant it factory Secure Boot support. With enforcement ON, expect refusal.
   Postpone, or separately choose a temporary manual enforcement change and restore
   it afterward. The collector never changes firmware. Keep factory keys intact;
   do not clear/enroll keys or use disposable OVMF keys. See [Microsoft's Secure Boot
   explanation](https://learn.microsoft.com/en-us/windows/security/operating-system-security/system-security/secure-the-windows-10-boot-process).
4. Use the one-time UEFI boot menu and stay **live-only**. Do not start Calamares,
   mount internal/personal volumes, install packages or run recovery/install
   harnesses. Manually note display/Plasma, keyboard/mouse, audio and basic network
   usability without SSIDs or addresses. No firmware updates or disk changes.
5. Run the collector in the desktop terminal and retain `public.json` on the chosen
   evidence medium. Inspect unavailable data, process exits, helper rendering and
   software flags. The existing candidate selects software Vulkan; it establishes
   no RTX 5070 acceleration or gaming claim. Keep photos/raw diagnostics private.
6. Use Plasma's normal shutdown, wait for power-off, remove live media, restore any
   separately chosen temporary Secure Boot policy change, and confirm normal Windows
   boot. Verify the evidence was saved. Do not claim acceptance from these fixtures
   or from merely reaching the desktop.

## Packaging and checks

The existing source-archive staging includes this script and document. The distroctl
package installs `/usr/bin/astraeus-collect-live-evidence` and
`/usr/share/doc/distroctl/live-diagnostics.md`. Python is already a distroctl runtime
dependency. Complete observations need the existing distroctl package with its two
Vulkan helper binaries, pacman and systemd. Missing tools do not stop other queries.
No new dependency or separate ISO is required for carrying the source script.
Shipping it inside future media requires the normal package rebuild and image
qualification; adding packaging entries does not change an existing ISO.

```sh
python3 -m unittest discover -s tests -p test_live_diagnostics.py -v
```

Fixtures test missing/partial/malformed data, public privacy, destination refusal,
and archive packaging. Linux tests additionally run bounded child processes to
check missing tools, nonzero exits, stderr/output limits, timeouts and descendant
cleanup. These checks do not exercise the physical GPU, USB writer or firmware.
