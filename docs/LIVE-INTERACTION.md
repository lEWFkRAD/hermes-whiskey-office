# Working with hands, controllers and Hermes

The quick menu contains Hermes, Dictate, Windows, Podium, File tray, Discuss view, Voice & room, and Help. Capabilities opens the existing Hermes tools page; its own UI owns plugins, MCP and skills. Expanded wheels stay stationary and use two to eight sectors, so submenus need no filler. Paused image rendering is visibly disabled.

Tracked hands have a joint skeleton. Controllers have a simple grip marker, distinct from the aim pose. The right pointer ends at the nearest interactive window or pickup target and names it. Cyan means pointing, green means a target, amber means a press/grip. Tracking loss hides these visuals. An open wrist menu owns selection and suppresses the desktop beam; its ring and selected sector provide feedback instead. This is functional feedback, not a photoreal hand or Quest controller model.

Left stick walks; right stick turns, or selects a menu sector while the wheel is open. Trigger selects, grip grabs an explicit target, A restores Hermes Desktop, B backs out, X opens window overview, and Y opens the quick menu. Two-hand pinches move/resize a targeted window. Locomotion stays available with windows open.

## Desktop and HUD recovery

Mapping a hidden Electron window directly can produce a white panel while Hermes remains in HUD mode. Desktop focus now uses Hermes's actual **Exit HUD mode** control before raising the window. It does not send or clear the draft. Terminal raises an already-running TUI again instead of silently returning.

## Explicit objects in the live scene

The TUI workspace guide documents `app/scene_tool.py`. When asked to create a simple object, Hermes can run:

```sh
python3 /path/to/office/app/scene_tool.py sphere --label 'Red ball' --color ff2a2a --radius 0.09
```

The command binds to a fresh running scene instance. Only the live scene can acknowledge success after creating the ball on its podium. The ball uses the existing targeted pickup and return controls. An occupied podium is rejected; `--replace` requires an explicit request to replace the presentation. A timeout is unconfirmed and must not be blindly retried.

Supported shapes are spheres and boxes. They use procedural geometry and work with AI image/mesh generation paused. These objects are currently session scoped; they are not exported GLBs. The context snapshot is read-only for agents. Launching a separate Godot scene or editing that snapshot cannot place an object in the live office.

Tests cover variable menu sectors, tracking loss, target feedback, HUD restoration, explicit scene receipts, expiration, instance mismatch, duplicate requests, physical primitive dimensions, pickup and return. Synthetic visual previews and real Desktop/HUD/TUI captures are separate from physical Quest acceptance. Hand fit, comfort, and added frame cost still require headset testing.
