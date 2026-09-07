#!/usr/bin/env bash
set -euo pipefail
office_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${HERMES_OFFICE_ACCEPTANCE_RUN:-0}" != "1" ]]; then
    python3 "$office_root/runtime_guard.py"
fi
# Launch the actual installed Hermes app on the display owned by desktop_bridge.
# User data for window placement is private; Hermes conversations remain shared.
office_data="${HERMES_OFFICE_DATA_DIR:-$HOME/.local/share/hermes-whiskey-office}"
runtime_dir="/run/user/$(id -u)"
if [[ -d "$runtime_dir" && -O "$runtime_dir" ]]; then
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-$runtime_dir}"
    if [[ -S "$runtime_dir/pulse/native" ]]; then
        export PULSE_SERVER="${PULSE_SERVER:-unix:$runtime_dir/pulse/native}"
    fi
fi
hermes_root="${HERMES_OFFICE_DESKTOP_ROOT:-$HOME/.local/share/hermes-whiskey-office/vendor/hermes-v2026.8.31}"
hermes_app="${HERMES_OFFICE_DESKTOP_BIN:-$hermes_root/apps/desktop/release/linux-unpacked/Hermes}"
if [[ ! -x "$hermes_app" ]]; then
    echo 'The existing Hermes Desktop executable is unavailable.' >&2
    exit 2
fi
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_DESKTOP_USER_DATA_DIR="$office_data/desktop-ui"
export HERMES_DESKTOP_HERMES_ROOT="${HERMES_OFFICE_BACKEND_ROOT:-$HOME/.hermes/hermes-agent}"
export HERMES_DESKTOP_PYTHON="$HERMES_DESKTOP_HERMES_ROOT/venv/bin/python"
export HERMES_DESKTOP_CWD="$office_data/workspace"
export HERMES_DESKTOP_DISABLE_GPU=1
export HERMES_DESKTOP_CDP_PORT=off
export HERMES_DESKTOP_SKIP_QUIT_CONFIRM=1
export ELECTRON_OZONE_PLATFORM_HINT=x11
export PATH="$HOME/.local/bin:$PATH"
unset HERMES_DESKTOP_DEV_SERVER
mkdir -p "$HERMES_DESKTOP_USER_DATA_DIR" "$HERMES_DESKTOP_CWD"
chmod 700 "$HERMES_DESKTOP_USER_DATA_DIR"
# Keep the Electron sandbox enabled. Fix the supported upstream installation
# if the platform cannot initialize its sandbox.
exec "$hermes_app" --ozone-platform=x11 --force-dark-mode --force-renderer-accessibility "$@"
