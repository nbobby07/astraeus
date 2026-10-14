# Corrected plain CLI and worker-interruption acceptance

Runtime is ec3641b. Both byte-identical candidate builds passed. The fresh plain CLI run passed all 12 lifecycle gates with Secure Boot enforced. All 257 exported public files verified locally.

The first interruption trial killed both the unit main process and its newly spawned ExecStopPost finalizer with systemctl kill --kill-whom=all. It remained applying and was stopped as a failed trial. Its 194 public evidence files verified locally. The original failed matrix and actual systemd status are retained here.

Validation-only harness ca10b5f targets the main process with SIGKILL. Systemd cleans up the remaining children and runs the finalizer. This tests forced service-main interruption, not an assertion that every child received SIGKILL. The fresh trial passed all 12 gates: actual committed package boundary, competing native writer exclusion, concurrent submission preservation, interrupted durable recovery, no request replay, signed RAM-root recovery, and verified offline restoration. All 159 public evidence files verified locally. The runtime and image bytes did not change.

These results do not qualify the remaining failure/capacity cases, installed GUI, LUKS2, or physical hardware. Full archives exclude credentials, private keys, guest disks and NVRAM.
