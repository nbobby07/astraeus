# Corrected signed live-media acceptance

Runtime ec3641b, candidate ISO SHA256 2bfc2f021c2bbe0a31de19339909dea45ede0452aef8f5946cb740f3a6ad55ca. All six media cases passed: trusted owner-enrolled boot plus untrusted, tampered, unsigned, root-tampered and disabled-Secure-Boot refusals. Negative passes require actual refusal evidence and absence of verified live desktop markers.

Trusted recovery boot verified the RAM-root hash, exact production CLI and desktop binaries, actual enforcing firmware and baseline owner enrollment. The actual Plasma-launched GUI ran as ordinary live UID 1000. Screenshots show the live-session warning, package search, KCalc staging, a resolved review separating KCalc from libmpc, an explicit live blocker and disabled Authenticate and apply. The harness separately verified that CLI/GUI inspection and privileged live refusal left package, configuration, management, history and request state unchanged.

All 134 public exported files verified locally. The immutable builder manifest retains its prequalification field; completed acceptance is recorded separately in these six actual result files. No physical USB or PC testing is claimed.

A redundant remote B ISO was retired only after full rehashes of both sealed local images and both remote images against the independent CMP0 proof. The receipt is retained. Remote A, local A/B images, all build and acceptance evidence, original development work and signed USB artifacts remain preserved.
