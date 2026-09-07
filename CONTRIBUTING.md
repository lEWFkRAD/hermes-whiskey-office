# Contributing

Start with a reproducible bug or a concrete work task. Small fixes can go directly to a pull request; discuss architectural changes, new dependencies and interaction changes in an issue first. Maintainers review PRs before merging. Contributions, including AI-assisted work, remain the submitter's responsibility.

## Workflow

1. Fork and create a branch from `main`. Keep the change focused.
2. Follow `docs/SETUP.md`; run `python tools/test.py` and `python tools/public_audit.py`.
3. Include tests for changed behavior, particularly input targeting, stale context, permissions, subprocess cleanup, recovery and updates.
4. For visuals, include screenshots with synthetic data. For Quest claims, state headset/runtime, hands/controllers, refresh rate, scene/window count and measured frame/input latency. A desktop capture is not headset acceptance.
5. Open a PR with the problem, behavior, tests and remaining limits. Respond to review; maintainers squash merge. Do not force-push shared branches.

## Product rules

- Keep walking and turning predictable. Window/menu changes must not silently remap locomotion.
- Grabs require explicit targets. Menu activation must survive hand jitter and cancel cleanly.
- Context, pointing and scene movement are not instructions to start model turns. Keep draft, inference and committed action distinct.
- Use existing Hermes Desktop/TUI controls and SDKs; do not duplicate their approval UI or auto-accept permissions.
- Freshness/instance checks fail closed. Do not bypass runtime acceptance or retry ambiguous generation submissions.
- Keep local presentation local. Shared semantic changes carry provenance; stale/offline context must be visible.
- Preserve graceful withdrawal: voice/context can stop without guilt, reminders or a duty to dismiss.

## Code, assets and dependencies

Use descriptive names and bounded interfaces. Keep GPU operations, network calls and personal configuration out of offline tests. No private IPs, hostnames, keys, logs, databases, screenshots of real work or runtime receipts in commits. Environment examples use fictional names.

Every new asset needs source/provenance, permission to redistribute raw source, size/geometry budget and a manifest entry. A purchase receipt alone is not permission to publish source assets. Do not add model weights, paid Fab/Unreal content or scraped images. Retain upstream licenses. To update an asset, regenerate its entry in `assets-manifest.json` and inspect the result visually.

Credit people, not only repository names: update `CREDITS.md` with the creator's public name/handle, actual contribution and upstream link. Record asset creators and roles in the manifest, including for CC0 assets. Keep inherited author notices and distinguish your modifications from their work. Do not infer an artist from a Git committer or assign co-authorship to someone who did not author the commit.

Dependency updates change the input spec and regenerate the corresponding hash lock with `uv pip compile --python-version 3.12 --generate-hashes ...`. Run dependency audits and relevant acceptance. Pin GitHub Actions to full commits. Do not use `pull_request_target` to execute PR code or provide secrets to forks.

By submitting, you confirm you have the right to contribute the work under this project's MIT license, with any third-party exceptions clearly identified. No CLA or transfer of copyright is required. Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
