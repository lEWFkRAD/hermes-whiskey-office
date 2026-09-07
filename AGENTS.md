# Working in this repository

Read README.md and CONTRIBUTING.md. Keep private runtime state, personal machine details and logs out of Git. Follow docs/ARCHITECTURE.md invariants. Never fabricate acceptance evidence or change tests merely to hide a regression.

Use the smallest relevant tests during development, then run tools/test.py and tools/public_audit.py before proposing a release. Report untested physical hardware honestly. Do not start model turns, microphone/camera capture, GPU inference, remote services or credential synchronization as part of ordinary CI or inspection.

Keep external dependency licenses and asset provenance. Do not alter the user's global Hermes installation, model routing or remote services to make tests pass. Do not disable Electron sandboxing or SSH host verification. Changes to runtime acceptance need direct review and regression tests.
