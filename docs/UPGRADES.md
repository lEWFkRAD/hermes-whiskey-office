# Updates and release acceptance

Keep the room independent of Hermes's release cadence. Desktop, backend, plugin and Godot versions are separately recorded in `dependencies.json`; Python locks contain exact versions and distribution hashes. Dependencies are installed from their upstreams, not copied from a personal machine.

1. Make an isolated checkout/candidate. Keep the previous accepted installation and back up Hermes data through its supported backup mechanism before migrations.
2. Change one dependency/version at a time. Update the manifest, immutable source pins and relevant locks together. Never follow `latest` in a release launcher.
3. Run offline CI, including navigation and runtime-guard regression tests, source/privacy checks, model asset validation and dependency audits.
4. Build the selected Desktop, run actual Desktop acceptance and inspect all captures. Test text, queued screenshots, dictation, End voice and TUI with synthetic data. Real model/audio acceptance is separate and operator initiated.
5. Reaccept the exact binary, app payload, backend commit, plugin set and navigation code. Run `runtime_guard.py`. Promote only the accepted candidate.
6. Test on physical Quest before claiming controller/audio/performance acceptance. Record environment and measured limits.

Normal startup rejects mismatched receipts/binaries/backend/navigation/plugin code. This catches drift; it does not guarantee every upstream change is compatible. It does not attest a backend's uncommitted edits, provider configuration or database schema. A backend migration may prevent simple app-directory rollback; restore its compatible data/runtime through upstream guidance.

For public releases, use a reviewed PR and passing required checks. Tag the accepted commit, publish notes distinguishing CI from hardware/live acceptance, and produce any release archive from Git-tracked files. Never attach private acceptance screenshots or operational receipts. The first public snapshot is experimental source, not a headset-certified binary.
