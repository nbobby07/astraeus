# Milestones and releases

There is no stable release or public ISO download yet. `0.1.0-dev` now includes
validated package updates and manual offline rollback on the recorded QEMU/KVM
target. It does not promise production support or automatic recovery.

## Source milestones

Annotated tags `phase-0-validated` and `phase-1-validated` identify the historical
source checkpoints. Their validation evidence is in [validation](validation.md).
Later documentation and repository-workflow commits do not change what was
tested. Preserve these tags and commits; do not move them to newer code.

Historical Phase 2 runtime source is `dde0970118ed3003221770d9004bea3147c030ef`, with final
acceptance harness `2bc521943cf616aae1a572858a3ed15007ca8826` and report commit
`31b045018eb21df636d2b623702ef5e195c872f5`. See [Phase 2 acceptance](phase2-integration.md)
for the complete integration history and artifact hashes. Later documentation
commits do not imply that the accepted ISO was rebuilt from those commits.

The hardened source was freshly requalified on 2026-10-08 at runtime commit
`0f984fcc898439c0a3f7c64ae1b7bd16d034e5e1`, whose production inputs match main
`01ed00da86db276c4d3b6a4dd7ab756e367c0741`. The
[requalification report](phase2-security-requalification.md) records the new
reproducible ISO pair, installations, A-G and security checks. This is a development
qualification, not a stable release or a public ISO publication.

Version identity and image build versions live in
`distro/branding/project.toml`; the Cargo workspace version must stay consistent.
Development milestone tags are separate from future `vMAJOR.MINOR.PATCH` releases.

## Publishing an image

A maintainer must complete these steps before publishing an ISO:

1. Select a clean source revision and record its archive hash. Review package
   recipes, archive locks and trust changes, including upstream advisories.
2. Build independently twice from fresh environments with fixed signed inputs.
   Compare ISO bytes and resolved package manifests.
3. Complete the live and installed guest acceptance matrix, including negative
   checks appropriate to the changed behavior. Record the tested source, versions,
   image size/hash, logs and compatibility limits.
4. Use a separately authorized release signing identity. Development validation
   keys are not release keys. Keep private keys and disposable guest disks out of
   release assets.
5. Publish the ISO, signed checksum manifest, public release key/fingerprint,
   source provenance, resolved package manifests and qualification record through
   a download location suitable for the image size. Verify the downloaded bytes
   and signatures before announcing it.

The current ISO is about 3.5 GB and is intentionally absent from Git. GitHub's
automatic source archives are source downloads, not installation media. Host CI
success alone cannot authorize an image release.

Do not create production signing automation until custody, review, rotation,
revocation and recovery are defined. See the [signing model](security.md).
