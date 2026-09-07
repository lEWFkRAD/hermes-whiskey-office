# People behind the workspace

This project builds on other people's work. They deserve visible credit alongside their software, research and artwork. The names below credit the stated contributions; they do not imply that these people worked on, reviewed or endorsed Whiskey Office.

## Hermes and the original spatial work

- **The Nous Research Hermes team and community** created the agent, Desktop, HUD, TUI and plugin SDK that this room presents. Thanks to [teknium1](https://github.com/teknium1), [OutThisLife](https://github.com/OutThisLife), [kshitijk4poor](https://github.com/kshitijk4poor), [benbarclay](https://github.com/benbarclay) and the [full Hermes contributor community](https://github.com/NousResearch/hermes-agent/graphs/contributors). These are upstream contributor credits, not a claim that those individuals authored a particular interface or illustration. [Project](https://github.com/NousResearch/hermes-agent) · [retained license](licenses-nous.txt).
- **Luke The Dev ([iamlukethedev](https://github.com/iamlukethedev))** — [Hermes3D](https://github.com/iamlukethedev/Hermes3D), the reference/legacy source used by the earlier room. Its [original copyright notice](app/HERMES3D-LICENSE.txt) is preserved. The current procedural whiskey-room furniture is a later addition, not work attributed to Luke.
- **[Adolanium](https://github.com/Adolanium)** — [Hermes SSH](https://github.com/Adolanium/hermes-ssh), the optional SSH workspace plugin. The creator's public handle is used because no personal name is published in the profile we checked. The plugin is installed from upstream, not redistributed here.

## Image-to-object pipeline

- **Siddharth Ahuja ([ahujasid](https://github.com/ahujasid))** — [Camera to Blender](https://github.com/ahujasid/camera-to-blender), the original photo-to-3D relay, browser application and Blender add-on on which the included Object Studio adaptation is based. His name is preserved in the [upstream MIT notice](integrations/object-studio/LICENSE) and add-on metadata. Durable jobs, recovery and this office integration are subsequent project changes.
- **Piotr Wilkin ([pwilkin](https://github.com/pwilkin), [ilintar](https://huggingface.co/ilintar))** — [trellis.cpp](https://github.com/pwilkin/trellis.cpp) and the [GGUF model distribution](https://huggingface.co/ilintar/trellis2-gguf) used by the optional renderer. Thanks also to the [runtime's contributors](https://github.com/pwilkin/trellis.cpp/graphs/contributors).
- **Jianfeng Xiang, Xiaoxue Chen, Sicheng Xu, Ruicheng Wang, Zelong Lv, Yu Deng, Hongyuan Zhu, Yue Dong, Hao Zhao, Nicholas Jing Yuan and Jiaolong Yang** — the [TRELLIS.2 research authors](https://github.com/microsoft/TRELLIS.2#-citation), whose work underlies the 3D generation technology. Runtime ports and converted weights are distinct contributions from the original research/model.

## Texture artists

| People | Contribution | Where used |
| --- | --- | --- |
| **Dario Barresi** — baking; **Dimitrios Savva** — photography; **Rico Cilliers** — tiling | [Dark Wood, Poly Haven](https://polyhaven.com/a/dark_wood) | `app/assets/pbr/dark_wood_*` |
| **Rob Tuytel** | [White Plaster 02, Poly Haven](https://polyhaven.com/a/white_plaster_02) | `app/assets/pbr/white_plaster_02_*` |

These creators are credited even though the textures' CC0 license does not require attribution. Their names and roles also travel with the individual entries in [assets-manifest.json](assets-manifest.json). Thanks to the wider [Poly Haven team](https://polyhaven.com/about-contact), contributors and patrons for maintaining the library.

## Tools and their communities

Thanks to the developers, maintainers, artists, documenters and testers behind [Godot](https://github.com/godotengine/godot/blob/master/AUTHORS.md), [Blender](https://www.blender.org/about/credits/), [WiVRn](https://github.com/WiVRn/WiVRn/graphs/contributors), [Monado](https://monado.freedesktop.org/), [OpenXR](https://www.khronos.org/openxr/), [GGML](https://github.com/ggml-org/ggml/graphs/contributors), [model-viewer](https://github.com/google/model-viewer/graphs/contributors), and the Python, Node.js, Electron, GNOME/AT-SPI, X11, OpenSSH and Remmina ecosystems. The [dependency manifest](dependencies.json), package locks and [third-party notices](THIRD_PARTY_NOTICES.md) identify the components; upstream author lists retain the broader credit that a short page cannot enumerate fairly.

## Work specific to this project

**[lEWFkRAD](https://github.com/lEWFkRAD)** provides the workspace concept, product direction and maintenance. Implementation, procedural modeling, tests and documentation were developed with AI assistance, including OpenAI Codex; the generated source images and landscape used OpenAI image generation. Generated pictures are not credited as photographs taken by a human artist, and generated geometry is not credited as an upstream author's hand-modeled asset.

The companion design draws on the Hermes project's character artwork. The individual illustrator was not established from the available provenance; we credit the source project without guessing an artist's identity. Human likeness scanning and purchased Hannah/MetaHuman content are not part of the published assets.

## Keeping credit accurate

Use public names or handles chosen by contributors. Preserve original authors and copyright holders when adapting work; describe the adaptation separately. New source, research, assets and substantial references must add the creator, contribution, upstream link and applicable license here and in the relevant asset/source record. Do not add people as Git co-authors of commits they did not author.

Corrections and preferred attribution are welcome through a repository issue or PR. This is an acknowledgement, not a change to anyone's copyright or license. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the legal notices.
