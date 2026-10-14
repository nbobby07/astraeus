# Phase 4.2 build evidence

These receipts cover runtime `0e8bb00e3edc5382fa177bf0017b2f8595ee8229`.
They record image construction, package checks and offline image inspection.
They do not establish installed-VM, Secure Boot management, recovery or physical
hardware acceptance. See the [acceptance report](../../../phase42-acceptance.md)
for those separate gates.

Both images are 3,636,389,888 bytes with SHA256
`2c047e270d6d99e0c0a6a09d81ade25752e4549457052f20d2fbecfa796a3072`.
[comparison.json](comparison.json) records the actual remote `cmp` exit 0 and
matching hashes for all five independently built package archives, manifests,
build inputs and generated package source archives. Both image assemblies use
the same signed repository published by A; independent package equality is a
separate check.

| Receipt | Scope |
| --- | --- |
| [source-identity.json](source-identity.json) | Immutable source revision and archive hash |
| [A-binary-identities.json](A-binary-identities.json) | Packaged CLI/GUI bytes and public repository signer |
| [A closed checks](A-closed-test-evidence.json), [B closed checks](B-closed-test-evidence.json) | 21 controller and 13 QML passes per build; exact manifest coverage of 691 live and 736 installed package records |
| [A native results](A-native-test-summary.json), [B native results](B-native-test-summary.json) | Explicit extracts of original test-summary lines and counts, bound to retained build-log hashes; 156 passed and 5 ignored per build |
| [A local export](A-local-export-verified.json), [B local export](B-local-export-verified.json) | Verified local image/evidence identities |
| [B deduplication](B-content-deduplication.json) | Local B image storage method after independent remote comparison |
| [Image audit result](image-audit/result.json), [summary](image-audit/summary.json), [execution](image-audit/execution.json) | Complete live/installed file scans, package/service identities, signed repository checks and account/state boundaries |
| [Audit controls](image-audit/fixtures.log), [original inventory](image-audit/inventory.json) | Seven passing controls and hashes of the complete retained audit evidence set |
| [Signed package proof](image-audit/signed-package-proof.json), [official source proof](image-audit/public-source-confirmation.json) | Exact GnuTLS file/block matches and verified public benchmark/self-test provenance |

B was independently built and compared on the validator. After byte equality was
proven, its local ISO path was created as a read-only hardlink to verified A
content. B was not downloaded a second time. The separate B comparison and export
receipts preserve that distinction.

The audit retains all detected GnuTLS test-key blocks as hashes and locations.
Its classification is limited to exact signed package files and the matching
constants in the signed upstream source. Changed blocks, extra blocks or copies
elsewhere are not covered. No private or sample key bytes are included here.

Copied receipts retain their original bytes, including line endings. The native
test receipts are labeled extractions, not new test runs. [SHA256SUMS](SHA256SUMS)
covers every file in this directory except itself. The original audit inventory
also names larger or redundant files retained outside this curated subset.
Source paths in receipts identify the validation environment, not published
downloads. Disks, credentials, private keys, cloud authentication data and large
logs/archives are excluded.
