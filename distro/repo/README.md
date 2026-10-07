# Curated repository

The repository name is `distro`, independent of the temporary product name. It
precedes Arch `core` and `extra`. Phase 0 contains only `distroctl`; no upstream
packages are rebuilt or overridden.

`scripts/publish-repo.sh` makes a new local repository from signed package files.
It verifies each signature against the explicitly selected primary fingerprint,
then signs the database with `repo-add`. It never uploads or publishes remotely.
Output must be a new directory. Keep the package, detached signature, database,
database signature, exported public key and `SHA256SUMS` together.

Build verification uses an isolated pacman keyring. The repository's fingerprint
is supplied separately from its public key, not inferred as an authorization to
trust whatever key happens to be there. Build and live configurations require
signed custom databases and packages. Arch retains its upstream policy of
required package signatures and optional database signatures.

Do not commit secret keys. Local test keys are not release signing keys. See
[security](../../docs/security.md) for trust, rotation, and release gates.
