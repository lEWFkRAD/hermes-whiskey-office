"""Prepare the generated, realistic Hermes mesh for the private Godot office.

Run in an isolated local bpy Python process. No hosts or app processes are touched.
"""
import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "assets/conversions/hermes-companion-v1/final.glb"
RENDERS = ROOT / "renders"
OUT = ROOT / "app/assets/hermes-companion.glb"
BLEND = ROOT / "assets/hermes-companion.blend"
REPORT = ROOT / "companion-report.json"


def look_at(obj, point):
    obj.rotation_euler = (Vector(point) - obj.location).to_track_quat("-Z", "Y").to_euler()


def stage():
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 700
    scene.render.resolution_y = 700
    scene.render.resolution_percentage = 100
    scene.world.color = (0.19, 0.19, 0.19)
    scene.view_settings.view_transform = "AgX"
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -0.0005))
    floor = bpy.context.object
    floor.name = "QA_Floor"
    mat = bpy.data.materials.new("QA_Grey")
    mat.diffuse_color = (0.25, 0.27, 0.29, 1)
    floor.data.materials.append(mat)
    for name, loc, energy, size in [
        ("QA_Key", (-2.6, -3.0, 3.1), 420, 3.0),
        ("QA_Fill", (2.0, -1.0, 2.0), 220, 2.5),
        ("QA_Rim", (1.0, 2.5, 2.9), 300, 2.5),
    ]:
        bpy.ops.object.light_add(type="AREA", location=loc)
        light = bpy.context.object
        light.name = name
        light.data.energy = energy
        light.data.shape = "DISK"
        light.data.size = size
        look_at(light, (0, 0, 1.0))
    bpy.ops.object.camera_add(location=(0, -3.5, 1.0))
    cam = bpy.context.object
    cam.name = "QA_Camera"
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 1.94
    scene.camera = cam
    return cam


def render(cam, file, location=(0, -3.5, 1.0), target=(0, 0, 0.85), scale=1.94):
    cam.location = location
    cam.data.ortho_scale = scale
    look_at(cam, target)
    bpy.context.scene.render.filepath = str(RENDERS / file)
    bpy.ops.render.render(write_still=True)


def import_source():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(RAW))
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    mesh = bpy.context.object
    mesh.name = "Hermes_Companion_Mesh"
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bounds = [mesh.matrix_world @ v.co for v in mesh.data.vertices]
    low = Vector(tuple(min(v[i] for v in bounds) for i in range(3)))
    high = Vector(tuple(max(v[i] for v in bounds) for i in range(3)))
    factor = 1.70 / (high.z - low.z)
    center = Vector(((high.x + low.x) * 0.5, (high.y + low.y) * 0.5, low.z))
    for vert in mesh.data.vertices:
        vert.co = (mesh.matrix_world @ vert.co - center) * factor
    mesh.matrix_world.identity()
    mesh.data.update()
    bpy.context.view_layer.update()
    for poly in mesh.data.polygons:
        poly.use_smooth = True
    return mesh


def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def interpolate(points, z):
    if z <= points[0][0]:
        return points[0][1]
    for (za, a), (zb, b) in zip(points, points[1:]):
        if z <= zb:
            return a + (b - a) * (z - za) / (zb - za)
    return points[-1][1]


def replace_head(body, source, target_height=0.325, center_y=0.02, photo=True):
    """Fit a separate detailed reconstruction while retaining the body collar."""
    import bmesh
    source = Path(source).resolve()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    existing = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(source))
    parts = [o for o in bpy.data.objects if o not in existing and o.type == "MESH"]
    assert parts, "Head source contains no mesh"
    bpy.ops.object.select_all(action="DESELECT")
    for part in parts:
        part.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    if len(parts) > 1:
        bpy.ops.object.join()
    head = bpy.context.object
    head.name = "Hermes_Detailed_Head_Source"
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    raw_points = [head.matrix_world @ v.co for v in head.data.vertices]
    low = Vector(tuple(min(v[i] for v in raw_points) for i in range(3)))
    high = Vector(tuple(max(v[i] for v in raw_points) for i in range(3)))
    factor = target_height / (high.z - low.z)
    center = Vector(((low.x + high.x) * 0.5, (low.y + high.y) * 0.5, high.z))
    for vertex in head.data.vertices:
        vertex.co = (head.matrix_world @ vertex.co - center) * factor + Vector((0, center_y, 1.70))
    head.matrix_world.identity()
    head.data.update()
    for material in head.data.materials:
        if material:
            material.name = "Hermes_Detailed_Head_Natural"
    marker = head.vertex_groups.new(name="Detailed_Head_Source")
    marker.add(list(range(len(head.data.vertices))), 1.0, "REPLACE")
    projection = project_refined_head(head, source.parent / "cutout.png", target_height, center_y) if photo else None

    # Cut above the original collar; remove the low back/side hair remnants.
    # The new short neck tucks inside the preserved blouse collar.
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bpy.context.view_layer.objects.active = body
    geometry = list(bm.verts) + list(bm.edges) + list(bm.faces)
    bmesh.ops.bisect_plane(bm, geom=geometry, dist=0.00001, plane_co=(0, 0, 1.442), plane_no=(0, 0, 1), clear_outer=True, clear_inner=False)
    remnants = []
    for face in bm.faces:
        center = face.calc_center_median()
        inside_neck = center.z > 1.407 and center.x * center.x + (center.y - 0.02) ** 2 < 0.058 ** 2
        if inside_neck:
            remnants.append(face)
    bmesh.ops.delete(bm, geom=remnants, context="FACES")
    bm.to_mesh(body.data)
    bm.free()
    body.data.update()
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    head.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    return {
        "raw_source": str(source),
        "raw_sha256": source_hash,
        "raw_preserved": hashlib.sha256(source.read_bytes()).hexdigest() == source_hash,
        "fit_height_m": target_height,
        "fit_center_y_blender": center_y,
        "fit_top_z_m": 1.70,
        "body_head_cut_z_m": 1.442,
        "raw_head_bounds": {"min": list(low), "max": list(high)},
        "photo_projection": projection,
        "weights": "Refined face, hair, headset and short neck weighted rigidly to Head; neck tucks inside preserved blouse collar.",
    }


def project_refined_head(head, reference, target_height, center_y):
    """Transfer the unchanged high-resolution photo to frontal head UVs."""
    import numpy as np
    source_image = bpy.data.images.load(str(reference), check_existing=True)
    width, height = source_image.size
    pixels = np.array(source_image.pixels[:], dtype=np.float32).reshape((height, width, 4))
    yy, xx = np.where(pixels[:, :, 3] > 0.5)
    x0, x1, y0, y1 = int(xx.min()), int(xx.max()) + 1, int(yy.min()), int(yy.max()) + 1
    model_x0 = min(v.co.x for v in head.data.vertices)
    model_x1 = max(v.co.x for v in head.data.vertices)
    projected = source_image.copy()
    projected.name = "Hermes_Head_Photo_2K"
    projected.scale(2048, 2048)
    material = bpy.data.materials.new("Hermes_Detailed_Head_Photo")
    material.use_nodes = True
    material.node_tree.nodes.clear()
    nodes = material.node_tree.nodes
    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.uv_map = "Hermes_Head_Photo_UV"
    image_node = nodes.new("ShaderNodeTexImage")
    image_node.image = projected
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.6
    shader.inputs["Specular IOR Level"].default_value = 0.25
    output = nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(uv_node.outputs["UV"], image_node.inputs["Vector"])
    material.node_tree.links.new(image_node.outputs["Color"], shader.inputs["Base Color"])
    material.node_tree.links.new(shader.outputs[0], output.inputs["Surface"])
    layer = head.data.uv_layers.new(name="Hermes_Head_Photo_UV")
    for loop in head.data.loops:
        point = head.data.vertices[loop.vertex_index].co
        u = (x0 + (point.x - model_x0) / (model_x1 - model_x0) * (x1 - x0)) / width
        v = (y0 + (point.z - (1.70 - target_height)) / target_height * (y1 - y0)) / height
        layer.data[loop.index].uv = (u, v)
    slot = len(head.data.materials)
    head.data.materials.append(material)
    count = 0
    for face in head.data.polygons:
        center = sum((head.data.vertices[i].co for i in face.vertices), Vector()) / len(face.vertices)
        if center.y < center_y + 0.012:
            face.material_index = slot
            count += 1
    return {"source": str(reference), "source_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(), "source_size": [width, height], "alpha_bounds_bottom_up": [x0, y0, x1, y1], "derived_texture_size": [2048, 2048], "projected_source_faces": count, "method": "Frontal planar UV transfer of unchanged source pixels; original inferred texture retained on back surfaces."}


def project_original_face(mesh):
    """QA fallback: project the unchanged input cutout onto frontal head faces.

    This is a native mesh UV/material operation. No source raster is edited.
    It is not part of the default build and must pass visual inspection first.
    """
    reference = RAW.parent / "cutout.png"
    photo = bpy.data.images.load(str(reference), check_existing=True)
    material = bpy.data.materials.new("Hermes_QA_Front_Photoprojection")
    material.use_nodes = True
    material.node_tree.nodes.clear()
    nodes = material.node_tree.nodes
    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.uv_map = "Hermes_Photo_Front_UV"
    image_node = nodes.new("ShaderNodeTexImage")
    image_node.image = photo
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.6
    shader.inputs["Specular IOR Level"].default_value = 0.25
    output = nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(uv_node.outputs["UV"], image_node.inputs["Vector"])
    material.node_tree.links.new(image_node.outputs["Color"], shader.inputs["Base Color"])
    material.node_tree.links.new(shader.outputs[0], output.inputs["Surface"])
    layer = mesh.data.uv_layers.new(name="Hermes_Photo_Front_UV")
    # Measured unedited cutout alpha bounds are x538..1021, y68..1490.
    for loop in mesh.data.loops:
        vertex = mesh.data.vertices[loop.vertex_index].co
        layer.data[loop.index].uv = ((vertex.x / 1.7 * 1422 + 779.5) / 1558, (vertex.z / 1.7 * 1422 + 68) / 1558)
    slot = len(mesh.data.materials)
    mesh.data.materials.append(material)
    count = 0
    for face in mesh.data.polygons:
        center = sum((mesh.data.vertices[i].co for i in face.vertices), Vector()) / len(face.vertices)
        if center.z > 1.407 and center.y < 0.035 and abs(center.x) < 0.165:
            face.material_index = slot
            count += 1
    return count


def optimize(mesh):
    import bmesh
    original_faces = len(mesh.data.polygons)
    bpy.context.view_layer.objects.active = mesh
    mesh.select_set(True)
    # glTF duplicates vertices at UV seams. Collapse decimation on disconnected
    # UV islands opens hairline cracks; weld geometry first while retaining each
    # face-corner UV. This avoids background-colored speckles in Godot.
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    topology = {"vertices_before_weld": len(bm.verts), "boundary_edges_before_weld": sum(e.is_boundary for e in bm.edges)}
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.00001)
    bm.normal_update()
    topology.update(vertices_after_weld=len(bm.verts), boundary_edges_after_weld=sum(e.is_boundary for e in bm.edges))
    bm.to_mesh(mesh.data)
    bm.free()
    topology["mesh_validation_repaired"] = mesh.data.validate(verbose=False, clean_customdata=True)
    mesh.data.update()
    mesh["topology_repair"] = json.dumps(topology)
    if mesh.data.has_custom_normals:
        mesh.data.normals_split_custom_set([(0, 0, 0)] * len(mesh.data.loops))
    modifier = mesh.modifiers.new("Character_Budget_90000_Triangles", "DECIMATE")
    modifier.ratio = min(1.0, 90000.0 / len(mesh.data.polygons))
    modifier.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    mesh.data.validate(verbose=False, clean_customdata=True)
    # Decimation may move extrema by a fraction of a millimeter. Reground the
    # finished mesh exactly after reduction, then fit the measured body rig.
    bottom = min(v.co.z for v in mesh.data.vertices)
    top = max(v.co.z for v in mesh.data.vertices)
    refit = 1.70 / (top - bottom)
    for vertex in mesh.data.vertices:
        vertex.co.z = (vertex.co.z - bottom) * refit
    # The reconstruction has metallic response on cloth and skin. Use a neutral,
    # nonmetallic material with restrained highlights; retain its original color UV.
    for material in mesh.data.materials:
        if not material or not material.use_nodes:
            continue
        is_head = material.name.startswith("Hermes_Detailed_Head")
        if not is_head:
            material.name = "Hermes_Natural_Cloth_Skin"
        for node in material.node_tree.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue
            for name, value in [("Metallic", 0.0), ("Roughness", 0.55 if is_head else 0.68), ("Specular IOR Level", 0.3 if is_head else 0.28)]:
                socket = node.inputs.get(name)
                if socket:
                    for link in list(socket.links):
                        material.node_tree.links.remove(link)
                    socket.default_value = value
    for poly in mesh.data.polygons:
        poly.use_smooth = True
    return original_faces


def make_armature(mesh):
    armature = bpy.data.armatures.new("Hermes_Humanoid")
    rig = bpy.data.objects.new("Hermes_Rig", armature)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bones = {
        "Root": ((0, 0, 0), (0, 0, 0.15), None, False),
        "Hips": ((0, 0.015, 0.82), (0, 0.015, 0.99), "Root", True),
        "Spine": ((0, 0.015, 0.99), (0, 0.015, 1.17), "Hips", True),
        "Chest": ((0, 0.015, 1.17), (0, 0.019, 1.365), "Spine", True),
        "Neck": ((0, 0.019, 1.365), (0, 0.027, 1.455), "Chest", True),
        "Head": ((0, 0.027, 1.455), (0, 0.027, 1.665), "Neck", True),
    }
    for side, s in [("L", 1), ("R", -1)]:
        shoulder = (s * 0.16, 0.012, 1.354)
        elbow = (s * 0.22, 0.005, 1.105)
        wrist = (s * 0.252, -0.058, 0.855)
        hand_end = (s * 0.265, -0.075, 0.777)
        hip = (0.09, 0.025, 0.88) if s > 0 else (-0.104, 0.018, 0.88)
        knee = (0.128, 0.014, 0.49) if s > 0 else (-0.112, 0.012, 0.49)
        ankle = (0.19, 0.025, 0.10) if s > 0 else (-0.112, 0.025, 0.10)
        toe = (ankle[0], -0.089, 0.043)
        bones.update({
            f"Clavicle.{side}": ((s * 0.02, 0.019, 1.347), shoulder, "Chest", True),
            f"UpperArm.{side}": (shoulder, elbow, f"Clavicle.{side}", True),
            f"ForeArm.{side}": (elbow, wrist, f"UpperArm.{side}", True),
            f"Hand.{side}": (wrist, hand_end, f"ForeArm.{side}", True),
            f"Thigh.{side}": (hip, knee, "Hips", True),
            f"Shin.{side}": (knee, ankle, f"Thigh.{side}", True),
            f"Foot.{side}": (ankle, toe, f"Shin.{side}", True),
        })
    for name, (head, tail, parent, deform) in bones.items():
        bone = armature.edit_bones.new(name)
        bone.head = head
        bone.tail = tail
        bone.use_deform = deform
        if parent:
            bone.parent = armature.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    rig.show_in_front = True
    rig.data.display_type = "STICK"
    mesh.parent = rig
    modifier = mesh.modifiers.new("Hermes_Humanoid_Skin", "ARMATURE")
    modifier.object = rig
    modifier.use_deform_preserve_volume = False  # Match glTF/Godot linear skinning.
    return rig, bones


def skin(mesh, rig):
    marker = mesh.vertex_groups.get("Detailed_Head_Source")
    head_vertices = set()
    if marker:
        head_vertices = {v.index for v in mesh.data.vertices if any(g.group == marker.index and g.weight > 0.5 for g in v.groups)}
    groups = {b.name: mesh.vertex_groups.new(name=b.name) for b in rig.data.bones if b.use_deform}
    stats = {"unweighted_vertices": 0, "maximum_influences": 0, "maximum_weight_sum_error": 0.0}
    for vertex in mesh.data.vertices:
        if vertex.index in head_vertices:
            groups["Head"].add([vertex.index], 1.0, "REPLACE")
            stats["maximum_influences"] = max(stats["maximum_influences"], 1)
            continue
        x, y, z = vertex.co
        side = "L" if x >= 0 else "R"
        weights = {}

        def add(name, weight):
            if weight > 0.00001:
                weights[name] = weights.get(name, 0.0) + weight

        # Measured lateral boundaries separate sleeves from the waist/hips.
        boundary = interpolate([(0.74, 0.213), (0.88, 0.200), (1.0, 0.18), (1.15, 0.163), (1.31, 0.145), (1.39, 0.15)], z)
        arm_share = smoothstep(boundary - 0.013, boundary + 0.015, abs(x))
        arm_share *= smoothstep(0.72, 0.765, z) * (1.0 - smoothstep(1.365, 1.415, z))
        if arm_share > 0.00001:
            upper = smoothstep(1.045, 1.165, z)
            clavicle = smoothstep(1.30, 1.38, z)
            hand = 1.0 - smoothstep(0.832, 0.883, z)
            add(f"Clavicle.{side}", arm_share * upper * clavicle)
            add(f"UpperArm.{side}", arm_share * upper * (1.0 - clavicle))
            add(f"ForeArm.{side}", arm_share * (1.0 - upper) * (1.0 - hand))
            add(f"Hand.{side}", arm_share * (1.0 - upper) * hand)

        body_share = 1.0 - arm_share
        leg_share = (1.0 - smoothstep(0.825, 0.96, z)) * body_share
        if leg_share > 0.00001:
            thigh = smoothstep(0.425, 0.565, z)
            foot = 1.0 - smoothstep(0.08, 0.165, z)
            add(f"Thigh.{side}", leg_share * thigh)
            add(f"Shin.{side}", leg_share * (1.0 - thigh) * (1.0 - foot))
            add(f"Foot.{side}", leg_share * (1.0 - thigh) * foot)

        trunk = body_share - leg_share
        head_start = 1.400 if y > 0.06 else 1.421
        head = smoothstep(head_start, 1.475, z)
        neck = smoothstep(1.35, 1.419, z) * (1.0 - head)
        chest = smoothstep(1.08, 1.215, z) * (1.0 - head - neck)
        spine = smoothstep(0.955, 1.08, z) * (1.0 - head - neck - chest)
        hips = max(0.0, 1.0 - head - neck - chest - spine)
        for name, value in [("Head", head), ("Neck", neck), ("Chest", chest), ("Spine", spine), ("Hips", hips)]:
            add(name, trunk * value)
        strongest = sorted(weights.items(), key=lambda item: item[1], reverse=True)[:4]
        total = sum(w for _, w in strongest)
        if total <= 0:
            stats["unweighted_vertices"] += 1
            strongest = [("Hips", 1.0)]
            total = 1.0
        for name, weight in strongest:
            groups[name].add([vertex.index], weight / total, "REPLACE")
        stats["maximum_influences"] = max(stats["maximum_influences"], len(strongest))
        stats["maximum_weight_sum_error"] = max(stats["maximum_weight_sum_error"], abs(sum(w / total for _, w in strongest) - 1.0))
    if marker:
        mesh.vertex_groups.remove(marker)
    stats["detailed_head_rigid_vertices"] = len(head_vertices)
    return stats


def global_delta(rig, name, angles):
    """Small anatomical rotations, expressed in Blender world axes at rest."""
    pose = rig.pose.bones[name]
    inverse_rest = rig.data.bones[name].matrix_local.to_quaternion().inverted()
    q = Quaternion()
    for axis, degrees in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), angles):
        if degrees:
            q = q @ Quaternion(inverse_rest @ Vector(axis), math.radians(degrees))
    pose.rotation_mode = "QUATERNION"
    pose.rotation_quaternion = q


def action_curves(action):
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                yield from bag.fcurves


def animate(rig):
    scene = bpy.context.scene
    scene.render.fps = 24
    rig.animation_data_create()
    actions = []
    for name, duration in [("Hermes_Idle", 8), ("Hermes_Talk", 6)]:
        action = bpy.data.actions.new(name)
        action.use_fake_user = True
        rig.animation_data.action = action
        end = duration * 24
        for frame in range(0, end + 1, 6):
            phase = 2.0 * math.pi * frame / end
            breath = math.sin(phase * 2.0)
            attention = math.sin(phase)
            gesture = 0.5 - 0.5 * math.cos(phase)
            for pose in rig.pose.bones:
                pose.rotation_mode = "QUATERNION"
                pose.rotation_quaternion = (1, 0, 0, 0)
                pose.location = (0, 0, 0)
                pose.scale = (1, 1, 1)
            global_delta(rig, "Spine", (0, 0.08 * attention, 0.08 * attention))
            global_delta(rig, "Chest", (0.12 * breath, 0, 0.15 * attention))
            # Rigid head motion only. There are no false lip-sync or gaze claims.
            global_delta(rig, "Neck", (-0.3, 0, 0.35 * attention))
            global_delta(rig, "Head", (-1.0 + 0.35 * breath, 0.2 * attention, 2.0 * attention))
            global_delta(rig, "UpperArm.L", (-1.0, 3.0, 0))
            global_delta(rig, "UpperArm.R", (0, -2.0, 0))
            global_delta(rig, "ForeArm.L", (-12.0 + 0.4 * breath, 0, -1.5))
            global_delta(rig, "ForeArm.R", (-8.0 + 0.35 * breath, 0, 1.0))
            global_delta(rig, "Hand.L", (1.5, 0, -1.0))
            global_delta(rig, "Hand.R", (1.0, 0, 1.0))
            if name == "Hermes_Talk":
                global_delta(rig, "UpperArm.L", (-3.0 - 2.5 * gesture, 2.0, -1.5 * gesture))
                global_delta(rig, "ForeArm.L", (-18.0 - 17.0 * gesture, 0, -4.0 * gesture))
                global_delta(rig, "Hand.L", (-1.5 * gesture, 2.0 * gesture, -4.0 * gesture))
                global_delta(rig, "Head", (-1.0 + 0.75 * breath, 0.2 * attention, 1.0 + 2.0 * attention))
            for pose in rig.pose.bones:
                pose.keyframe_insert(data_path="rotation_quaternion", frame=frame, group=pose.name)
        for curve in action_curves(action):
            for point in curve.keyframe_points:
                point.interpolation = "BEZIER"
                point.handle_left_type = "AUTO_CLAMPED"
                point.handle_right_type = "AUTO_CLAMPED"
        track = rig.animation_data.nla_tracks.new()
        track.name = name
        strip = track.strips.new(name, 0, action)
        strip.name = name
        track.mute = True
        actions.append(action)
    rig.animation_data.action = actions[0]
    scene.frame_start = 0
    scene.frame_end = 192
    scene.frame_set(0)
    return actions


def mesh_bounds(mesh):
    verts = [mesh.matrix_world @ v.co for v in mesh.data.vertices]
    return {"min": [min(v[i] for v in verts) for i in range(3)], "max": [max(v[i] for v in verts) for i in range(3)]}


def check_animation(mesh, rig, actions):
    """Numerical deformation sanity check across both actual skinned clips."""
    import numpy as np
    rest = np.array([v.co[:] for v in mesh.data.vertices])
    feet = rest[:, 2] < 0.12
    results = {}
    for action in actions:
        rig.animation_data.action = action
        end = int(action.frame_range[1])
        all_lows, all_highs, foot_drift, displacement = [], [], 0.0, 0.0
        start_vertices = None
        max_loop_gap = 0.0
        for frame in range(0, end + 1, 12):
            bpy.context.scene.frame_set(frame)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated = mesh.evaluated_get(depsgraph)
            data = evaluated.to_mesh()
            points = np.array([v.co[:] for v in data.vertices])
            assert np.isfinite(points).all(), "Nonfinite deformed vertex"
            all_lows.append(points.min(axis=0).tolist())
            all_highs.append(points.max(axis=0).tolist())
            foot_drift = max(foot_drift, float(np.max(np.linalg.norm(points[feet] - rest[feet], axis=1))))
            displacement = max(displacement, float(np.max(np.linalg.norm(points - rest, axis=1))))
            if start_vertices is None:
                start_vertices = points.copy()
            if frame == end:
                max_loop_gap = float(np.max(np.linalg.norm(points - start_vertices, axis=1)))
            evaluated.to_mesh_clear()
        assert foot_drift < 0.0001, "Standing feet move unexpectedly"
        assert max_loop_gap < 0.0001, "Loop is discontinuous"
        results[action.name] = {
            "duration_seconds": end / 24,
            "sampled_every_frames": 12,
            "maximum_foot_displacement_m": foot_drift,
            "maximum_vertex_displacement_m": displacement,
            "loop_endpoint_maximum_gap_m": max_loop_gap,
            "all_samples_finite": True,
            "sampled_bounds_min": np.array(all_lows).min(axis=0).tolist(),
            "sampled_bounds_max": np.array(all_highs).max(axis=0).tolist(),
        }
    rig.animation_data.action = actions[0]
    bpy.context.scene.frame_set(0)
    return results


def export(mesh, rig, actions):
    OUT.parent.mkdir(exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    # NLA tracks preserve the two user-facing clip names. Export each track
    # independently; these tracks are muted only while inspecting one active clip.
    rig.animation_data.action = None
    for track in rig.animation_data.nla_tracks:
        track.mute = False
    bpy.ops.export_scene.gltf(
        filepath=str(OUT), export_format="GLB", use_selection=True,
        export_animations=True, export_animation_mode="NLA_TRACKS",
        export_skins=True, export_yup=True, export_apply=False,
        export_all_influences=False, export_force_sampling=True,
        export_anim_slide_to_zero=True, export_extras=True,
    )
    for track in rig.animation_data.nla_tracks:
        track.mute = True
    rig.animation_data.action = actions[0]
    bpy.context.scene.frame_set(0)
    binary = OUT.read_bytes()
    size = struct.unpack_from("<I", binary, 12)[0]
    gltf = json.loads(binary[20:20 + size])
    names = [a.get("name") for a in gltf.get("animations", [])]
    assert set(names) == {"Hermes_Idle", "Hermes_Talk"}, names
    assert gltf.get("skins"), "Missing exported skin"
    return gltf


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--inspect", action="store_true")
    p.add_argument("--validate-export", action="store_true")
    p.add_argument("--head", type=Path)
    p.add_argument("--head-height", type=float, default=0.325)
    p.add_argument("--head-center-y", type=float, default=0.02)
    p.add_argument("--no-head-photo", action="store_true")
    args = p.parse_args()
    RENDERS.mkdir(exist_ok=True)
    if args.validate_export:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        bpy.ops.import_scene.gltf(filepath=str(OUT))
        imported_mesh = next(o for o in bpy.context.scene.objects if o.type == "MESH")
        rig = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
        names = [a.name for a in bpy.data.actions]
        assert any(n.startswith("Hermes_Idle") for n in names), names
        assert any(n.startswith("Hermes_Talk") for n in names), names
        # Reimport uses NLA clips and preserves actual skeletal animation, which
        # confirms the file contains more than animation names in metadata.
        for track in rig.animation_data.nla_tracks:
            track.mute = True
        idle = next(a for a in bpy.data.actions if a.name.startswith("Hermes_Idle"))
        rig.animation_data.action = idle
        if idle.slots:
            rig.animation_data.action_slot = idle.slots[0]
        bpy.context.scene.frame_set(24)
        cam = stage()
        render(cam, "companion-reimport-check.png", (0.25, -3.5, 1.05))
        verification = {
            "animation_names": names,
            "armatures": 1,
            "bones": len(rig.data.bones),
            "vertices": len(imported_mesh.data.vertices),
            "triangles": len(imported_mesh.data.polygons),
            "armature_modifiers": [m.name for m in imported_mesh.modifiers if m.type == "ARMATURE"],
            "reimport_render": "renders/companion-reimport-check.png",
        }
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        report["isolated_glb_reimport_verification"] = verification
        REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(verification, indent=2), flush=True)
        return
    mesh = import_source()
    source_report = {
        "raw_sha256": hashlib.sha256(RAW.read_bytes()).hexdigest(),
        "vertices": len(mesh.data.vertices),
        "topology_repair": json.loads(mesh.get("topology_repair", "{}")),
        "faces": len(mesh.data.polygons),
        "bounds": [list(mesh.dimensions)],
        "images": [{"name": i.name, "size": list(i.size)} for i in bpy.data.images],
        "materials": [m.name for m in bpy.data.materials],
    }
    if args.inspect:
        print(json.dumps(source_report, indent=2), flush=True)
        cam = stage()
        render(cam, "companion-inspect-front.png")
        render(cam, "companion-inspect-back.png", (0, 3.5, 1.0))
        return

    head_report = replace_head(mesh, args.head, args.head_height, args.head_center_y, not args.no_head_photo) if args.head else None
    original_faces = optimize(mesh)
    rig, bones = make_armature(mesh)
    weight_report = skin(mesh, rig)
    actions = animate(rig)
    animation_report = check_animation(mesh, rig, actions)
    rig["character"] = "Hermes — realistic adult companion from generated source"
    rig["front_direction"] = "Godot +Z; Blender -Y"
    rig["intended_height_m"] = 1.70
    rig["source_sha256"] = source_report["raw_sha256"]
    rig["rig_scope"] = "Measured 20-bone body rig; subtle standing clips, no lip sync or finger articulation."
    gltf = export(mesh, rig, actions)
    cam = stage()
    rig.animation_data.action = actions[0]
    bpy.context.scene.frame_set(0)
    render(cam, "companion-idle-front.png")
    render(cam, "companion-idle-face.png", (0.25, -2.5, 1.53), (0, 0, 1.52), 0.58)
    rig.animation_data.action = actions[1]
    bpy.context.scene.frame_set(72)
    render(cam, "companion-talk-three-quarter.png", (1.6, -3.5, 1.20), (0, 0, 0.85), 1.94)
    rig.animation_data.action = actions[0]
    bpy.context.scene.frame_set(0)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND))
    report = {
        "character": "Realistic adult Hermes companion",
        "raw_source": str(RAW.relative_to(ROOT)),
        "raw_sha256": source_report["raw_sha256"],
        "raw_preserved": hashlib.sha256(RAW.read_bytes()).hexdigest() == source_report["raw_sha256"],
        "output": str(OUT.relative_to(ROOT)),
        "output_bytes": OUT.stat().st_size,
        "output_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "blend": str(BLEND.relative_to(ROOT)),
        "blender_version": bpy.app.version_string,
        "render_device": "CPU",
        "render_resolution": [700, 700],
        "render_samples": 16,
        "source_triangles": source_report["faces"],
        "combined_source_triangles": original_faces,
        "triangles": len(mesh.data.polygons),
        "vertices": len(mesh.data.vertices),
        "topology_repair": json.loads(mesh.get("topology_repair", "{}")),
        "rest_bounds_blender": mesh_bounds(mesh),
        "physical_height_m": 1.70,
        "front": "Godot +Z / Blender -Y",
        "texture_sizes": [list(i.size) for i in bpy.data.images if i.name.startswith("Image_")],
        "materials": "Original 2K base color and UV preserved. Removed generated metallic/roughness responses; metallic 0. Body roughness 0.68/specular IOR level 0.28, detailed head (if supplied) roughness 0.55/specular 0.30.",
        "detailed_head": head_report,
        "armature": {"total_bones": len(bones), "deform_bones": len(bones) - 1, "weight_method": "Measured anatomical compartments with smooth shoulder/elbow/wrist/spine/neck blends, normalized strongest four influences; glTF linear skinning.", **weight_report},
        "animations": animation_report,
        "exported_animation_names": [a.get("name") for a in gltf["animations"]],
        "exported_skin_count": len(gltf["skins"]),
        "views": ["renders/companion-idle-front.png", "renders/companion-idle-face.png", "renders/companion-talk-three-quarter.png"],
        "limitations": [
            "Single-image mesh reconstruction is softer than the source photograph at the face and hands.",
            "Body rig is intended for the included restrained standing loops, not general-purpose motion retargeting.",
            "No mouth shapes, eye articulation, finger bones, lip sync, seated work, or keyboard contact animation.",
            "Back surfaces are inferred by the reconstruction model.",
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
