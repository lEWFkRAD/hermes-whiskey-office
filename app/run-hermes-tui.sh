#!/usr/bin/env bash
set -euo pipefail
office_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
backend="${HERMES_OFFICE_BACKEND_ROOT:-$HOME/.hermes/hermes-agent}"
data="${HERMES_OFFICE_DATA_DIR:-$HOME/.local/share/hermes-whiskey-office}"
mkdir -p "$data/workspace"
python3 "$office_root/office_workspace.py" "$data/workspace"
cd "$data/workspace"
# Use the same accepted backend as Desktop, not a separate PATH/snap launcher.
exec "$backend/venv/bin/python" -c 'from hermes_cli.main import main; main()' --tui "$@"
