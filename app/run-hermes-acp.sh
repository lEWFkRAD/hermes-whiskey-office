#!/usr/bin/env bash
set -euo pipefail
office_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Public ACP entry point, without the snap launcher's unrelated service setup.
# Resolve one installed revision for the lifetime of this process.
if [[ -d /snap/hermes-agent/current ]]; then
    snap_root="$(readlink -f /snap/hermes-agent/current)"
    export PYTHONPATH="$snap_root/lib/python3.12/site-packages:$office_dir/.acp-deps${PYTHONPATH:+:$PYTHONPATH}"
    export PATH="$snap_root/bin:$PATH"
    export PLAYWRIGHT_BROWSERS_PATH="$snap_root/usr/share/ms-playwright"
    exec "$snap_root/bin/python3" -m acp_adapter "$@"
fi
exec "${HERMES_OFFICE_HERMES_BIN:-hermes}" acp "$@"
