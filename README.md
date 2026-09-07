# Hermes Â· The Whiskey Room

[![CI](https://github.com/lEWFkRAD/hermes-whiskey-office/actions/workflows/ci.yml/badge.svg)](https://github.com/lEWFkRAD/hermes-whiskey-office/actions/workflows/ci.yml)

A warm, furnished spatial workspace for working alongside Hermes. Built with Godot and OpenXR for **Meta Quest 3 through Linux PCVR**, with a desktop preview for development. The room presents the actual Hermes Desktop, HUD and TUI, preserving their conversations, tools, permissions and voice interfaces.

An independent community project built around [Nous Research's Hermes](https://github.com/NousResearch/hermes-agent). This repository does not imply official sponsorship or endorsement.

**Credit to the people who made this possible:** the Hermes team and contributors; **Luke The Dev** (Hermes3D); **Siddharth Ahuja** (Camera to Blender); **Piotr Wilkin** (trellis.cpp/GGUF); **Adolanium** (Hermes SSH); the **TRELLIS.2 researchers**; and texture artists **Dario Barresi, Dimitrios Savva, Rico Cilliers and Rob Tuytel**. [Full credits, their contributions and original projects â†’](CREDITS.md)

## What is here

- A walnut study with editable furniture assemblies, plants, terrariums, turntables, speakers, tube amplifiers, warm lights and a central hologram podium.
- Glowing wrist rings, stationary expanded menus, hand pointing, targeted grabs and controller navigation.
- Multiple application/remote windows, placement recovery, a shared file tray with checkout/conflict handling, and a podium for models, documents and live windows.
- Image-to-object submission, durable job recovery, model delivery and pickup. The adapted Object Studio server and Blender add-on are included; GPU runtime and model weights are separately acquired dependencies.
- Quiet dictation into a draft. Scene changes never ask the model for a reply. Explicit Send starts a turn; continuous voice is a separate choice.
- Optional, bounded virtual scene context through the Hermes plugin SDK; pointing remains a candidate that can be corrected.

## Try the room

Clone normally; the runtime assets are included, with no Git LFS requirement.

```bash
git clone https://github.com/lEWFkRAD/hermes-whiskey-office.git
cd hermes-whiskey-office
python3 tools/fetch_godot.py                 # Linux x86_64, checksum verified
.tools/Godot_v4.7.2-stable_linux.x86_64 --path app --xr-mode off
```

That opens a **room preview**; it does not start Hermes, record audio or connect remote machines. Windows/macOS can open `app/project.godot` using the matching Godot editor; live desktop capture currently requires Linux/X11.

For the complete workspace, follow **[Setup](docs/SETUP.md)**. It covers Linux dependencies, the pinned Hermes Desktop build, local acceptance, context plugin, remote windows and Quest/OpenXR. **[Object Studio](integrations/object-studio/README.md)** covers the optional image-to-3D backend.

## Controls

| Input | Action |
| --- | --- |
| Left stick | Walk, including while windows are open |
| Right stick | Snap turn; select sectors while an expanded menu is open |
| Trigger / hand pinch | Select the pointed target |
| Grip | Grab an explicitly targeted window or generated object |
| A | Focus Hermes |
| B | Back/cancel; hide the active window |
| X | Open-window overview |
| Y | Quick menu |
| Wrist gesture | Extend index/middle, curl ring/little; hold, then twist to choose |
| Expanded menu | Hold pinch/trigger briefly, release to activate |

The Home wheel offers Build, Dictate, End voice, Discuss view, Approvals, Windows, File tray and Senses. On desktop, WASD moves, F9 opens the wheel, arrows select, and hold/release Enter activates. Space starts dictation; use End voice and Send deliberately. Discuss view queues an image including your work windows; it does not send it.

## Development

```bash
bash tools/bootstrap-linux.sh --system     # explicitly installs distro packages
source .venv/bin/activate
python tools/test.py                       # offline Python, Node and Godot tests
python tools/public_audit.py               # tracked-file and asset integrity audit
```

See [CONTRIBUTING](CONTRIBUTING.md), [architecture and invariants](docs/ARCHITECTURE.md), [update acceptance](docs/UPGRADES.md), and [asset provenance](docs/ASSETS.md). CI uses synthetic fixtures and a fake ACP agent: no paid model calls, microphone, camera or SSH secrets. Hardware and live Hermes acceptance remain separate.

## Current limits

This is an experimental PCVR application, **not a standalone Quest APK**. Photorealism and stereo performance are ongoing work. The present character has reconstructed hair/hands and idle/talk clips, not production facial animation. Purchased MetaHuman/Hannah content is not included.

The desktop capture target is 30 Hz, not headset frame rate. Sustained stereo frame time, multi-window input latency, Quest hand/controller comfort and real headset audio still need physical acceptance. The current Linux WiVRn path has no verified passthrough-camera/document-scanning integration. Window recovery restores placements and configured sources, not remote applications' unsaved work. TUI and Desktop retain separate conversations.

## License

First-party code and original assets are offered under [MIT](LICENSE), to the extent rights exist. Third-party notices and asset-specific terms are in [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md). Dependencies retain their own licenses. No private workspace history, credentials, conversation data or purchased Unreal source is included.
