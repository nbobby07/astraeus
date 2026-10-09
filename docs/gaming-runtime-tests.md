# Gaming runtime acceptance design

## Integrated candidate procedure

Build the initial installed payload with explicit `--graphics virtio software
--gaming core tools` for the Freestyle virtual target. This uses the existing
signed image pipeline; blocked gaming proposals are not installation operations.
Run `distroctl graphics --probe --json` and `distroctl gaming doctor --probe --json`
as the disposable desktop user. Retain both raw reports and verify matching
architecture, ICD, device and clear/readback evidence. Software results never
qualify a physical GPU. All original runtime and security gates below still apply.

The procedure was exercised on the integrated Freestyle candidate at runtime
`cac8998ad7730e69ae354c3162ef4a0677cfc162`. Results and limitations are in
[Phase 4 acceptance](phase4-acceptance.md); the procedure itself is not proof.
Do not run these tests against the developer's desktop or modify another worktree. Use an
isolated installed Astraeus test system with a suitable GPU and desktop user.
Retain the Phase 3 trusted boot and snapshot requirements. The gaming planner
cannot install the fixture's packages; use the integration owner's reviewed build
payload or a future supported transaction backend, never an unprotected pacman
workaround. No paid games or private credentials are required for host tests.

## Evidence contract

For each test, record source/ISO commit and hashes, package versions, session type,
architecture, GPU/driver/ICD identity from the graphics provider, executable SHA-256,
argv, start/end time, exit status, bounded sanitized output and what was observed
on screen. Record `not_run`, `unsupported`, `failed` or `passed` per check. A timeout
or live process is not a pass; a directory or canned success marker is not execution.
Software Vulkan can test a software path but cannot qualify physical GPU rendering.
Keep raw logs private for review, then publish only sanitized evidence. Do not
collect Steam loginusers/config files, command-line credentials, tokens or cookies.
If a GUI requests authentication, stop at the login screen for the startup test.

## Static installation and session

Run `distroctl gaming status --json` and `doctor --json` as the desktop user. Retain
the original unknown/untested values. Verify package installation and integrity
with read-only upstream queries. Confirm both Vulkan architectures and GL providers
using the graphics owner's probes, including active render-device identity. Do not
infer this from the 64-bit desktop working. Check XWayland/DISPLAY and the user bus,
the controller's actual permissions, and the limits of any VM graphics device.

## Steam client and runtime

Launch the installed `/usr/bin/steam` as the desktop user, once, without credentials
or special runtime-disable flags. It may update its user-owned client/runtime and
use the network. Capture the actual client process tree and a usable login window,
not merely the short-lived bootstrap process. Observe successful runtime setup;
failed downloads, missing libraries, namespace/pressure-vessel errors and a blank
window are failures or incomplete checks. Close Steam normally afterwards.
The login window is enough to qualify client startup, not game launch.

Record client/runtime versions independently from the pacman bootstrap version.
Use the installed runtime's diagnostic tools following
[Valve's runtime reporting guide](https://github.com/ValveSoftware/steam-runtime/blob/master/doc/reporting-steamlinuxruntime-bugs.md),
and sanitize logs before publishing. Steam Runtime inspection never verifies Proton
until an actual Windows executable runs under the selected compatibility tool.

## Native graphics

Use the freely distributable upstream `vkcube` from the reviewed `vulkan-tools`
fixture package and `glxgears` from `mesa-utils` for OpenGL. Their installation is
test-only, not part of Gaming Core. Record the packages selected from the same
archive and executable hashes. Render the actual moving cube/gears in the user
session, capture a frame and identify the renderer. Close the window normally and
record the result. Window creation without rendered content is insufficient.
Repeat with a real 32-bit graphics executable supplied by the graphics validator;
launching 64-bit vkcube twice does not test the 32-bit stack. These are smoke tests,
not games or meaningful performance benchmarks.

The inspected 2026/10/01 extra database contains `vulkan-tools 1.4.357.0-1` and
`mesa-utils 9.0.0-7`. These test-package records were checked separately from the
15-package gaming preset catalog; the validator still needs signed artifacts.

## Windows application through Proton

Use a legally redistributable test executable, such as a locally compiled Win32
GUI sample or the selected Proton distribution's Wine Notepad executable. Record
the source/license or the exact distributed PE file and its hash. Verify it is a
Windows PE executable of the intended architecture. Merely finding `proton` or
invoking `--version` is not a runtime test.

Preferred path when an already prepared offline Steam user profile is available:
add the executable as a non-Steam shortcut, explicitly select the installed
Steam-managed Proton in its compatibility settings, launch it, interact with the
window, close it and retain actual process/exit evidence. Do not add credentials
to the harness or copy an account-bearing profile into source/evidence. If obtaining
Steam-managed runtime/tool content needs authentication, that prerequisite remains
blocked until the operator supplies it through Steam; no account is provisioned
by this branch.

A credential-free diagnostic path can use an already obtained, provenance-checked
Proton build and its matching Steam Linux Runtime. The runtime is determined by
that build's tool manifest, not a hard-coded latest version. Use a fresh disposable
user prefix and the runtime's upstream entrypoint. For distributions exposing
the standard `run` wrapper, the invocation has this shape:

```sh
# All paths must be explicitly selected and reviewed in the disposable test VM.
STEAM_COMPAT_CLIENT_INSTALL_PATH="$steam_root" \
STEAM_COMPAT_DATA_PATH="$new_test_prefix" \
  "$matching_runtime/run" -- "$selected_proton/proton" run "$windows_exe"
```

Verify the installed runtime wrapper's documented arguments before using it.
This is an isolated direct-Proton diagnostic, not a supported replacement for
Steam's game-launch path or evidence of Steam integration. Prefix/runtime creation
is a test mutation outside read-only doctor. Keep logs, prefix location and outcome;
do not overwrite a game prefix. The test must show actual Windows application
behavior, not only prefix files or process creation. A Notepad/GDI test proves
basic Windows execution only. Add a licensed D3D11/D3D12 test application to qualify
DXVK/VKD3D and record the Vulkan renderer; add a real 32-bit PE test separately.
GE is optional and must be tested under its documented runtime path independently.

## Optional tools

Test individually before combining wrappers, using the same working native test:

```sh
gamescope -w 1280 -h 720 -r 60 -- vkcube
mangohud vkcube
mangohud glxgears
gamemoded -t
```

Gamescope needs an actual nested window rendering frames at the requested internal
dimensions, normal child exit and compositor logs identifying the selected GPU.
Failures on unsupported VM/GPU/driver combinations must remain explicit. Requested
refresh is a limit, not measured scanout. HDR/VRR require separate display-specific
acceptance; leave them unknown here.

MangoHud needs a visible changing overlay on Vulkan and OpenGL, plus an actual
32-bit executable with lib32-mangohud. If OpenGL needs `--dlsym`, record that scope.
Compare with the overlay disabled and preserve the user's config. A successful
wrapper invocation without visible overlay is insufficient. Flatpak overlay
extensions require a separate sandbox test.

GameMode's upstream self-test can temporarily alter performance behavior. Run it
only in the disposable session, retain exit/output, and verify requests end and
settings return after the test. Also run `gamemoderun` around the working test and
observe the service request/release. No permanent tuning, custom daemon or GPU
power changes are acceptance steps.

Test a controller with Steam Input in the actual user session; record device/input
events without weakening permissions. For optional OBS, test PipeWire portal
capture in Plasma Wayland and an actual short recording; encoder availability
needs explicit evidence. Heroic/Lutris are optional separate launcher checks,
not part of the minimum Steam pass. Do not run arbitrary community install scripts.

Host fixtures and this procedure do not validate Phase 4. The final integration
must also rerun all existing host checks, trusted update/recovery regressions and
the independent reproducible-ISO comparison after resolving branch overlaps.
