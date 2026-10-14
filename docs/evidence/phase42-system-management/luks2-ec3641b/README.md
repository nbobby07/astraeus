# Corrected LUKS2 baseline and CLI acceptance

Frozen runtime ec3641b, matching candidate A/B ISO 2bfc2f021c2bbe0a31de19339909dea45ede0452aef8f5946cb740f3a6ad55ca. A fresh LUKS2 installation passed two distinct cold boots with actual SecureBoot=true and SetupMode=false. Both boots used observed LUKS prompts and actual tester SDDM login, and the harness verified active Wayland sessions. The session-startup screenshot shows Plasma loading, not a separate Control Center acceptance result.

Setup uses the previously approved initial SetupMode provisioning flow with production candidate payload and installer helpers; this is not Calamares UI or first-install Secure Boot acceptance. Management and recovery tests enforce Secure Boot.

The encrypted CLI run passed all 12 lifecycle gates: identity and installed trust, ordinary-user read-only access, malformed intent rejection, unprivileged submission refusal, stale plan rejection, actual install and removal, pending-boot blocking, both new-boot confirmations, retained transaction snapshots/history and unchanged personal-file sentinel. All 132 public baseline files and all 285 public CLI files verified locally.

The encrypted baseline owner certificate SHA256 is afeff872533e481efe6457ebb4b99560d11b3b932195a4b4b3505394e1e08dec. The matching signed RAM recovery medium is 4,294,967,296 bytes, SHA256 608ac8c67b93b7a04bd92e90c37c551578c4d8b097c793d642dd54f3105a94f2, with no private key embedded. Its enforcing encrypted recovery exercise is pending in the separate fault suite; the build manifest alone is not qualification.

Encrypted fault recovery and installed GUI acceptance remain required. No credentials, private keys, guest disks or NVRAM are exported. Physical testing remains deferred.
