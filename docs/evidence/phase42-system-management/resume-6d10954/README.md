# Frozen-source build resume attempt

Source `6d10954a501f5b65d5b38ed680d7efb681c28112` was frozen and verified locally. No upload, new builder, or production image completed.

The first start response reported running; subsequent read-only responses reported paused, with provider total runtime increasing from 55510 to 55511 seconds. A bounded second start request timed out after 90 seconds. The subsequent idle-timeout update returned `INTERNAL_ERROR: Internal server error`. That error was observed in CLI stderr; the empty stdout is retained as `resume-idle-update.json`. Its cause remains unconfirmed.

Final responses confirm both task validators paused and the original idle timeout still 600 seconds. The budget receipt conservatively includes the complete attempted-resume wall interval. `index.json` records raw receipt sizes and hashes. These receipts are infrastructure failure evidence, not image acceptance.

The existing replacement subsequently resumed and was resized within the current plan. Upload errors are retained. Direct upstream preparation then verified the exact original Arch base hash and signature. `replacement-setup.json` and `replacement-launch-A.json` record the new frozen-source builder launch. No completed image or VM acceptance is claimed. Decoder reconstruction matches all 57 authenticated members and nine signed archives; its receipt comparison is retained.
