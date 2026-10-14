Independent B of runtime `0c938b9` failed before image production.
The original output and export index are retained. This is a failing build gate.

The confirmation test encountered a retained flock after its prior session ended.
Two deterministic regressions reproduced descriptor inheritance in history and
snapshot guards. Runtime fix `f8c55b2` explicitly releases their owned locks at
scope exit and preserves database-before-unlock ordering. It does not unlink locks
or weaken contention checks. Both regressions also verify live-owner exclusion.

Windows and Linux native Rust/Clippy checks passed afterward. Thirty native
transaction unit runs with 16 test threads passed, including the actual child
process that had made the earlier confirmation test vulnerable to this race.
New images and fresh VM acceptance remain required.
