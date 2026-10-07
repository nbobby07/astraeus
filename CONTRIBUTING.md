# Contributing

Astraeus currently has a validated installation foundation and a planned update
system. Read the [roadmap](docs/roadmap.md) and [architecture](docs/architecture.md)
before proposing work across those boundaries. Open an issue before starting a
large feature or changing the storage, boot or privilege model.

## Development setup

Install Git, rustup and Python 3.11 or later. Clone the repository, then run the
four checks in the README. The pinned Rust toolchain includes rustfmt and Clippy.
Linux additionally needs Bash, `squashfs-tools` and `xorriso` for all host checks.
WSL is useful for Linux fixtures; ISO builds still require the disposable Arch
environment described in [building](docs/building.md).

Enable the repository's commit subject check and message template locally:

```sh
git config --local core.hooksPath .githooks
git config --local commit.template .gitmessage
```

These settings affect this checkout only. Hooks use Python and do not install
dependencies. Existing historical commit subjects are preserved.

## Commits and pull requests

Use a topic branch and keep each commit coherent. New subjects and PR titles use
`type(scope): summary`; the scope is optional. Allowed types are `feat`, `fix`,
`docs`, `refactor`, `test`, `build`, `ci`, `perf`, `chore` and `revert`. Keep the
subject at most 72 characters. A `!` before the colon marks a breaking change;
explain it in the body with `BREAKING CHANGE:`.

```text
fix(hardware): resolve a partition's parent without slaves
docs: record the plain installation boot results
build(calamares): require libparted during configuration
```

Explain the cause or tradeoff when it would not be clear from the diff. Include
the exact checks you ran and their results in the pull request. Update documents
when behavior changes. Add a regression check for a real defect; avoid tests that
only repeat the implementation. Small documentation changes do not need guest
builds.

Pull requests are squash-merged, using their checked title as the commit subject.
Main requires passing Linux/Windows checks and resolved review conversations,
and rejects force pushes and deletion. The initial repository has one maintainer,
so it does not require an approval from a nonexistent second maintainer. Review
is expected when another contributor is available; increase the required review
count when the maintainer group grows. Administrator bypass is disabled.

## Checks and acceptance

CI runs formatting, locked workspace tests, Clippy with warnings denied, Python
regressions and Linux shell syntax checks. It does not build a release ISO or
qualify the installer. Manual workflow dispatch also verifies archived inputs.

Storage, image, account, boot and privilege changes need the relevant tests in
[testing](docs/testing.md). Before declaring a new installation milestone valid:

1. Build twice independently with fixed signed inputs and compare complete ISO bytes.
2. Install through native Calamares to fresh plain and encrypted virtual disks.
3. Remove the ISO and cold boot each installed disk twice.
4. Run all four status/hardware commands as the installed desktop user; check
   Wayland, networking, audio, mount/boot state and failed units on both boots.
5. Retain source and artifact hashes, manifests, logs and actual screenshots.

A repaired test installation is diagnostic evidence. Acceptance needs a fresh
installation of the corrected image.

## Reports and sensitive data

Include a revision, environment, minimal reproduction and expected/observed
behavior. Mark untested assumptions clearly. Remove passwords, private keys,
tokens and personal data before attaching logs or screenshots. Guest disk UUIDs
in the recorded validation are disposable test identifiers.

Report security issues through [private vulnerability reporting](SECURITY.md).
Be direct and respectful in issues and reviews. Discuss the change and its
evidence; personal attacks have no place in the project.
