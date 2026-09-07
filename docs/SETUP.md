# Setup

The supported live integration is a normal Linux desktop user, Python 3.12, X11/Xvfb and Godot 4.7.2. A working desktop session, D-Bus and AT-SPI are required. Node 22.22.0 builds the pinned Hermes Desktop. Windows/macOS are room-preview paths, not supported live capture hosts.

## 1. Dependencies and preview

Run `bash tools/bootstrap-linux.sh --system` on Ubuntu/Debian, activate `.venv`, then `python tools/fetch_godot.py`. Set `HERMES_GODOT_BIN` to the absolute path printed. The bootstrap's explicit `--system` option runs apt; without it, only the project venv is created. AT-SPI is provided by the distro's `python3-pyatspi` through system site packages.

Start a room-only preview with `$HERMES_GODOT_BIN --path app --xr-mode off`. No Hermes installation is needed for that preview. Run `python tools/test.py` for offline verification.

## 2. Hermes

Install/configure [Hermes using its official instructions](https://github.com/NousResearch/hermes-agent), including your chosen model and voice provider. The baseline backend is commit `693641aa8b4359c602283bdbbc14041e03bc47bc` (v0.21.0). This repository does not distribute provider credentials or install/update the backend automatically.

Set `HERMES_OFFICE_BACKEND_ROOT` if the backend is elsewhere than `~/.hermes/hermes-agent`; it must contain `venv/bin/python`. Use the backend's own setup tooling for its Python/model/audio dependencies.

Run `python tools/stage_hermes_desktop.py` to build official Desktop `v2026.8.31`, pinned to `29112bef099274229cadff79cdff7bf7b99c4b77`. It runs upstream `npm ci` and packaging inside a private vendor directory and records binary/payload hashes. It does not launch or update the backend. Install Node/npm first. Electron must have a working sandbox for your OS; use the supported upstream installation rather than disabling it.

## 3. Context and acceptance

`python tools/install_context_plugin.py` installs the included office context plugin and records the local plugin set. Enable **Office context** in Hermes, then close/restart the app. The installer refuses to overwrite differing code. Additional plugins are optional and must be independently reviewed. [Hermes SSH](https://github.com/Adolanium/hermes-ssh) is upstream-installed, not vendored here; its remote workspace credential behavior differs from a plain SSH terminal.

Run these from the repository root in your Linux desktop session:

```bash
python app/smoke_desktop_bridge.py
python tools/accept_desktop.py
# Inspect every listed image: actual startup, draft typing, queued image, HUD,
# TUI, return to Desktop and all navigation destinations.
python tools/accept_desktop.py --reviewed
python app/runtime_guard.py
HERMES_DESKTOP_PREVIEW=1 bash app/run-pcvr.sh
```

Smoke acceptance interacts with the real application but does not send model prompts, record audio or approve actions. It creates local captures/receipts ignored by Git. `--reviewed` is your attestation after inspection, not an automated visual judgment. Normal startup refuses missing or changed acceptance. Do not ship someone else's receipts or use acceptance-mode overrides as a daily launcher.

## 4. Quest 3

Install and pair [WiVRn](https://github.com/WiVRn/WiVRn) using its instructions; it provides the OpenXR runtime and headset audio path. Choose it as your active runtime. Start WiVRn on Quest, then run `bash app/run-pcvr.sh`. With no active runtime the launcher selects a desktop preview. Runtime/driver setup is system-specific and is not installed by this project.

Validate movement while windows are open, snap turn rearming after menus, targeted grabs, cancel/release, two-hand resizing, ring/menu stability, four/eight-window readability, and audio start/stop. Measure sustained stereo frame time at the chosen headset refresh rate and motion/input latency. The offline test suite cannot accept these for you. See README for current unverified features.

## 5. Multiple machines and shared files

Office state defaults to `~/.local/share/hermes-whiskey-office`; override with `HERMES_OFFICE_DATA_DIR`. Copy/edit `examples/window-sources.json` into that data directory. Commands require absolute executable paths. Only configure machines and accounts you control or are authorized to use.

For terminals, configure your own SSH alias using `examples/ssh-config`, verify the server fingerprint independently, then test `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes office-workstation`. Keep keys local; do not turn off host checking. Remmina manages its own RDP/VNC connection setup.

Loading Bay opens the existing file manager on Inbox/Shelf/Work. Its Python API supports immutable files, checkouts and conflict-preserving returns. It is not an automatic multi-machine sync daemon. Transfer files through your authenticated transport, preserving hashes and explicit checkouts; configure shared storage according to your environment.

## 6. Image-to-object

Follow [Object Studio setup](../integrations/object-studio/README.md). Set `HERMES_OBJECT_STUDIO_URL` to its loopback URL (possibly an SSH tunnel) before launching the office. No server job starts until you explicitly select an image and request a render. `HERMES_PODIUM_DISABLE=1` disables the worker. Existing GLBs, text/images and live windows can use the podium without a renderer service.
