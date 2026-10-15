# Signed RAM recovery and live inspection, runtime 6d10954

The trusted second attempt passed with Secure Boot enabled and Setup Mode disabled. The ordinary live user opened the packaged Control Center, searched KCalc, selected it, and reviewed KCalc plus libmpc. The live explanation and disabled apply action were visible. CLI inspection/planning and privileged apply refusal passed, and managed state remained unchanged.

All five negative cases passed: wrong key, modified EFI, unsigned EFI, modified root filesystem, and disabled Secure Boot. The first trusted attempt timed out waiting for its final GUI evidence and remains a recorded failure. It is not counted as a pass.

The 203-file public archive is retained locally as `media-6d-evidence.tar.gz`, 5,709,684 bytes, SHA256 `cec32a16cab94c54095a012e32e88f1490ebdd84052b450ea9024d55b1adcf59`. Every exported file was verified after download. This directory selects the result receipts and five actual GUI captures; `full-export-index.json` identifies all exported files. Private keys and credentials are excluded.

This qualifies these media tests only. Installed GUI, LUKS2, and complete fault/recovery acceptance remain required. Physical gaming qualification remains deferred.
