# Assets and provenance

`assets-manifest.json` lists every shipped GLB/PNG/JPEG with hash, size, origin category and license. CI rejects missing, changed or unlisted assets. Runtime assets are committed directly so a clean clone opens the room.

- `app/assets/whiskey-room.glb`, room libraries and decorations are original procedural work from `build_room.py`, `build_decorations.py` and `modeling/`. These sources preserve semantic components while batching runtime geometry. Use Blender's Python/bpy 5.0.1 for the original authoring baseline; runtime does not require Blender.
- `app/assets/pbr/dark_wood_*` and `white_plaster_02_*` come from [Poly Haven dark wood](https://polyhaven.com/a/dark_wood) and [white plaster 02](https://polyhaven.com/a/white_plaster_02), under [CC0](https://polyhaven.com/license). Their asset license is distinct from this project's MIT code license.
- `highland-loch-painting.png` is an original generated landscape.
- The companion and club chair were generated from original imagegen source images, then converted with the Trellis pipeline and edited/rigged in Blender. Source images/prompts and intermediate GLBs are included under `assets/`; they are not scans of a real person. The companion design was inspired by Hermes's character artwork; no exclusive trademark rights are claimed. The retained upstream Hermes notice applies where appropriate.
- `prepare_companion_visual.py` reconstructs the visual candidate using `prepare_companion_experimental.py`; inspect its outputs before replacing the runtime GLB. It has no lip sync, articulated eyelids or validated seated typing. Do not describe it as a production MetaHuman.

All original generated assets are offered under MIT to the extent the contributor holds applicable rights; AI output may not have exclusive copyright. Purchased Hannah/MetaHuman packages, Unreal project source, upstream model weights, private conversion receipts and personal screenshots are excluded.

## Rebuild

Use a separate authoring environment with Blender/bpy 5.0.1 and its NumPy. From this repository: `python build_room.py --output-root /absolute/candidate --no-render`; `python build_decorations.py` writes decoration source/libraries; `python prepare_chair.py` and the companion scripts rebuild their respective assets. Generators can overwrite authoring outputs, so use a clean candidate and inspect before promotion. Blender binaries/licenses remain upstream dependencies, not bundled here.

When replacing an asset, update its manifest, check geometry/scale/embedded resources and review in native Godot. Keep reusable source parts and raw-asset redistribution rights. Performance has to be measured in stereo on the target headset.
