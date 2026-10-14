# Corrected plain fault suite

All eight scenarios passed, totaling 70 gates, against the frozen ec3641b production backend. Management and recovery boots enforce Secure Boot. Metadata uses the original ec harness; the other seven cases use validation-only ca10b5f. The separate failed interruption injection remains preserved.

Cases: metadata-only lifecycle and wrong-state refusal; forced service-main interruption, competing writer exclusion and no replay; abandoned submission and failed worker start; real package hook failure; signing failure; and actual root, cache and EFI space shortfalls. Mutation failures restore offline through the signed, verified RAM-root medium and verify packages, installation reasons, configuration, ownership, lock data and the home sentinel together. Capacity failures refuse before mutation, remove only their owned test filler, and reboot without replay.

All 976 public exported files verified locally. The archive receipt, full file index, scenario matrices, actual capacity-injection records and offline-restore results are retained here. No credentials, private keys, guest disks or NVRAM are exported. Installed GUI, LUKS2 and formal corrected-media gates remain required; physical hardware remains deferred.
