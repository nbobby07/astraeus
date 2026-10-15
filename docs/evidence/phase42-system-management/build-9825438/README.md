Both clean builds of runtime `9825438d275c3037fcb41fbd768eebc71ef3f38c`
produced 3,645,478,912-byte ISOs with SHA256
`558475af3eb219277786ded7379e1c80a12557064b2e26e245648f355011bb16`.
The remote full-file comparison returned zero. All five independently built
package archives, generated package source archives, input records and package
manifests also match. Each build passed 156 native Rust tests, with five normal-run
fixture skips, and 21 controller plus 13 QML tests.

These compact receipts come from the retained build evidence. The native summaries
are derived from exact build logs, with their hashes and original archive identities
recorded. Both images consume A's signed repository; independent package equality
is checked separately. After the actual remote comparison, the verified identical
B content was represented locally by a read-only hardlink to A. Its deduplication
receipt makes that limitation explicit.

The full A content audit applies to both identical images. It checks signatures,
packaged identities, owner-key absence, accounts and the exact five public repository
metadata files in both compressed roots. GnuTLS's exact public upstream test
constants remain explicitly classified. The audit result binds the new signer
comparison, source, inputs and auditor hashes. These build gates do not establish
the remaining installed management, authorization, reboot or recovery acceptance.

The disposable repository signing key expires on 2026-10-15 at 05:17:30 UTC.
These are validation candidates, not a stable release. Physical PC and USB testing
remain deferred. Historical failures and superseded evidence are preserved.
