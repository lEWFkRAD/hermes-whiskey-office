#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
godot_bin="${HERMES_GODOT_BIN:-/opt/godot-4.7.2}"
if [[ ! -x "$godot_bin" ]]; then
    godot_bin="$(command -v godot || command -v godot4 || true)"
fi
if [[ -z "$godot_bin" || ! -x "$godot_bin" ]]; then
    echo "Set HERMES_GODOT_BIN to your Godot 4 executable." >&2
    exit 1
fi
# The installed runtime is used when present. Its absence is a supported
# desktop preview, and this launcher never starts or changes a bridge service.
active_runtime="${HOME}/.config/openxr/1/active_runtime.json"
if [[ "${HERMES_DESKTOP_PREVIEW:-0}" != "1" && -e "$active_runtime" ]]; then
    export XR_RUNTIME_JSON="$(readlink -f "$active_runtime")"
elif [[ "${HERMES_DESKTOP_PREVIEW:-0}" != "1" && -z "${XR_RUNTIME_JSON:-}" ]]; then
    export HERMES_DESKTOP_PREVIEW=1
fi
if [[ "${HERMES_DESKTOP_PREVIEW:-0}" == "1" ]]; then
    exec python3 "$project_dir/office_launcher.py" --godot "$godot_bin" -- --xr-mode off "$@"
fi
exec python3 "$project_dir/office_launcher.py" --godot "$godot_bin" -- "$@"
