# Third-party notices

The root MIT license covers first-party work only. Preserve these independent notices and terms when redistributing:

| Component | Origin and license | Distribution |
| --- | --- | --- |
| Original Hermes3D reference/legacy room code | Luke The Dev, MIT; [retained notice](app/HERMES3D-LICENSE.txt) | Notice retained for inherited parts; current procedural room is original |
| Hermes agent/Desktop/SDK and character inspiration | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent), MIT; [notice](licenses-nous.txt) | Built/installed separately, exact source pins in dependencies.json |
| Camera to Blender | Siddharth Ahuja, [upstream](https://github.com/ahujasid/camera-to-blender), MIT | Adapted sources in integrations/object-studio with original LICENSE |
| Poly Haven wood/plaster maps | [CC0](https://polyhaven.com/license) | Included, per-file hashes/provenance in assets-manifest.json |
| Godot | [godotengine/godot](https://github.com/godotengine/godot), MIT and bundled third-party notices | Separate checksum-verified editor download |
| WiVRn | [WiVRn/WiVRn](https://github.com/WiVRn/WiVRn), GPL-3.0 | Separately installed OpenXR runtime, not linked/bundled |
| Blender/bpy | [Blender](https://www.blender.org/about/license/), GPL | Separate authoring tool; no binary bundled |
| trellis.cpp | [pwilkin/trellis.cpp](https://github.com/pwilkin/trellis.cpp), MIT plus upstream dependency terms | Separate checksum-verified runtime download |
| GGUF models | [ilintar/trellis2-gguf](https://huggingface.co/ilintar/trellis2-gguf) | Not bundled; model card says license “other”, refers to source components |
| Google model-viewer | [google/model-viewer](https://github.com/google/model-viewer), Apache-2.0 | Optional browser UI loads version 4.1.0 externally |
| Hermes SSH | [Adolanium/hermes-ssh](https://github.com/Adolanium/hermes-ssh) | Not vendored: no standalone license file found at reviewed revision; install upstream |

Python runtime/transitive package versions and hashes are listed in the three requirements locks. Their wheel/source distributions retain their individual licenses. Node/Electron and Hermes's own dependencies remain governed by the pinned upstream workspace lock and notices; this project does not relicense them.

No Nous, Meta, Epic or other third-party trademark ownership or endorsement is claimed. Purchased Unreal/MetaHuman assets and private runtime data are excluded. See docs/ASSETS.md for generated-image and geometry provenance.
