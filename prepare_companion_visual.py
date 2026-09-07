"""Isolated visual candidate using source-photo UVs; preserves the installed rig."""
from pathlib import Path
import os
import tempfile
import inspect
import sys
import prepare_companion_experimental as build
import bpy

root = Path(__file__).resolve().parent
candidate = root / 'assets/visual-candidate'
for folder in ('app/assets', 'renders', 'temporary'):
    (candidate/folder).mkdir(parents=True, exist_ok=True)
os.environ['TMP'] = os.environ['TEMP'] = str(candidate/'temporary')
tempfile.tempdir = str(candidate/'temporary')
bpy.context.preferences.filepaths.temporary_directory = str(candidate/'temporary')
build.OUT = candidate/'app/assets/hermes-companion.glb'
build.BLEND = candidate/'hermes-companion.blend'
build.RENDERS = candidate/'renders'
build.REPORT = candidate/'companion-report.json'
original_projection = build.project_refined_head

def projected_head(*args, **kwargs):
    report = original_projection(*args, **kwargs)
    image = bpy.data.images.get('Hermes_Head_Photo_2K')
    if image:
        image.filepath_raw = str(candidate/'hermes-head-projected.png')
        image.file_format = 'PNG'
        image.save()
        image.pack()
        # Transparent cutout margins are not skin. Keep the inferred UVs on
        # silhouettes and the collar seam instead of projecting white margins.
        import numpy as np
        head = args[0]
        width, height = image.size
        pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape(height, width, 4)
        layer = head.data.uv_layers['Hermes_Head_Photo_UV']
        slot = len(head.data.materials) - 1
        for face in head.data.polygons:
            if face.material_index != slot: continue
            keep = True
            for loop_index in face.loop_indices:
                uv = layer.data[loop_index].uv
                x = min(width-1, max(0, int(uv.x*width)))
                y = min(height-1, max(0, int(uv.y*height)))
                if pixels[y, x, 3] < .96: keep = False
            if not keep: face.material_index = 0
    return report

build.project_refined_head = projected_head
# Retain the previously verified collar cut and hair-remnant rules. Only the
# head UV/material detail differs from that fit; no exposed cut at the neck.
source = inspect.getsource(build.replace_head)
source = source.replace('1.442', '1.422')
source = source.replace('inside_neck = center.z > 1.407 and center.x * center.x + (center.y - 0.02) ** 2 < 0.058 ** 2\n        if inside_neck:',
    'rear_hair = center.z > 1.386 and abs(center.x) < 0.135 and center.y > 0.045\n        side_hair = center.z > 1.402 and 0.065 < abs(center.x) < 0.137 and center.y > -0.006\n        if rear_hair or side_hair:')
assert 'if rear_hair or side_hair:' in source
exec(compile(source, str(Path(__file__)), 'exec'), build.__dict__)
if '--head' not in sys.argv and '--validate-export' not in sys.argv:
    sys.argv.extend(['--head', str(root/'assets/conversions/hermes-head-fast-v1/final.glb')])
build.main()
