"""Preserve semantic parts while producing a bounded number of room draw calls.

Source objects remain individually editable in room-parts.blend. Export evaluates
and triangulates each part once; those same triangles form the parts GLB and the
assembly/material runtime batches. Books and bottles are real child assemblies,
but share their case's render_group. Their source identity is not a draw call.

All manifest transforms are column-major local-to-parent matrices in Godot's
right-handed Y-up coordinates, in meters. Bounds are world-space unless named
local_bounds. A library root is neutral; its assembly.world_transform places it
back into the room. library_parts and runtime_nodes include the whole subtree.
"""
from collections import defaultdict
from contextlib import contextmanager
import json
from pathlib import Path
import re

import bpy
from mathutils import Matrix, Vector


TO_GODOT = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
TO_BLENDER = TO_GODOT.inverted()


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def matrix_list(matrix):
    return [float(matrix[row][column]) for column in range(4) for row in range(4)]


def godot_matrix(matrix):
    return TO_GODOT @ matrix @ TO_BLENDER


def bounds(points):
    if not points:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0]}
    return {"min": [min(p[i] for p in points) for i in range(3)],
            "max": [max(p[i] for p in points) for i in range(3)]}


class AssemblyRegistry:
    def __init__(self):
        self.assemblies = {}
        self.parts = {}
        self.anchors = {}
        self.current = None
        self._counts = defaultdict(int)

    def activate(self, identifier, name=None, origin=(0, 0, 0), role=None,
                 parent_id="office", render_group=None, library=False):
        """Select an explicit semantic scope; origin is always room/world space."""
        if identifier in self.assemblies:
            self.current = identifier
            return self.assemblies[identifier]["object"]
        if not identifier or identifier != slug(identifier):
            raise ValueError("Assembly IDs must be stable lowercase slugs: " + identifier)
        if parent_id is not None and parent_id not in self.assemblies:
            raise ValueError("Unknown assembly parent: " + parent_id)
        if render_group is not None and render_group not in self.assemblies:
            raise ValueError("Unknown render group: " + render_group)
        ob = bpy.data.objects.new("assembly::" + identifier, None)
        bpy.context.collection.objects.link(ob)
        ob.empty_display_type = "PLAIN_AXES"
        ob.empty_display_size = .10
        if parent_id is not None:
            ob.parent = self.assemblies[parent_id]["object"]
        target = TO_BLENDER @ Vector(origin)
        # Assembly parents have translation-only transforms during construction.
        parent_origin = self.assemblies[parent_id]["origin"] if parent_id else (0, 0, 0)
        ob.location = TO_BLENDER @ (Vector(origin) - Vector(parent_origin))
        render_group = render_group or identifier
        ob["office_assembly_id"] = identifier
        ob["semantic_role"] = role or identifier
        ob["render_group"] = render_group
        self.assemblies[identifier] = dict(
            id=identifier, name=name or identifier.replace("-", " ").title(),
            parent_id=parent_id, semantic_role=role or identifier,
            object=ob, origin=tuple(origin), render_group=render_group,
            library=library, part_ids=[], child_ids=[],
        )
        if parent_id:
            self.assemblies[parent_id]["child_ids"].append(identifier)
        self.current = identifier
        return ob

    @contextmanager
    def assembly(self, *args, **kwargs):
        previous = self.current
        ob = self.activate(*args, **kwargs)
        try:
            yield ob
        finally:
            self.current = previous

    def part(self, ob, name=None, part_id=None, role=None):
        if self.current is None:
            raise RuntimeError("Geometry created outside an assembly scope")
        assembly = self.assemblies[self.current]
        name = name or ob.name
        base = slug(part_id or name)
        self._counts[(self.current, base)] += 1
        count = self._counts[(self.current, base)]
        identifier = self.current + "/" + base
        if part_id and count != 1:
            raise ValueError("Duplicate explicit part ID: " + identifier)
        if not part_id:
            identifier += "-" + str(count).zfill(3)
        # Primitives are authored in world space. Keep their orientation/scale;
        # translating into the parent frame avoids an implicit parent inverse.
        ob.parent = assembly["object"]
        ob.location -= TO_BLENDER @ Vector(assembly["origin"])
        ob.name = "part::" + identifier
        ob["office_part_id"] = identifier
        ob["office_assembly_id"] = self.current
        ob["semantic_role"] = role or slug(name)
        ob["render_group"] = assembly["render_group"]
        self.parts[identifier] = dict(id=identifier, name=name, assembly_id=self.current,
                                      semantic_role=role or slug(name), object=ob,
                                      render_group=assembly["render_group"])
        assembly["part_ids"].append(identifier)
        return ob

    def anchor(self, identifier, position, assembly_id=None, **metadata):
        assembly_id = assembly_id or self.current
        if identifier in self.anchors:
            raise ValueError("Duplicate anchor: " + identifier)
        origin = self.assemblies[assembly_id]["origin"]
        local = Matrix.Translation(Vector(position) - Vector(origin))
        self.anchors[identifier] = dict(assembly_id=assembly_id,
                                      transform=matrix_list(local),
                                      position=list(position), **metadata)

    def subtree(self, identifier):
        result = [identifier]
        for child in self.assemblies[identifier]["child_ids"]:
            result.extend(self.subtree(child))
        return result

    def subtree_parts(self, identifier):
        return [part for child in self.subtree(identifier)
                for part in self.assemblies[child]["part_ids"]]

    @staticmethod
    def _export(path, objects):
        path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.object.select_all(action="DESELECT")
        for ob in objects:
            ob.select_set(True)
        bpy.ops.export_scene.gltf(
            filepath=str(path), export_format="GLB", use_selection=True,
            export_texcoords=True, export_normals=True, export_materials="EXPORT",
            export_cameras=False, export_lights=False, export_yup=True,
            export_extras=True, export_animations=False,
        )

    def export(self, root):
        """Write editable source, inspectable libraries and runtime room in order.

        This deliberately mutates only the current Blender scene after saving the
        editable source. Call it once, at the end of deterministic construction.
        """
        root = Path(root)
        assets = root / "assets"
        runtime_assets = root / "app" / "assets"
        for directory in (assets, runtime_assets):
            directory.mkdir(parents=True, exist_ok=True)
        bpy.context.view_layer.update()
        unregistered = [o.name for o in bpy.context.scene.objects
                        if o.type in {"MESH", "FONT"} and "office_part_id" not in o]
        if unregistered:
            raise RuntimeError("Unowned source geometry: " + ", ".join(unregistered[:8]))
        bpy.ops.wm.save_as_mainfile(filepath=str(assets / "room-parts.blend"))
        depsgraph = bpy.context.evaluated_depsgraph_get()
        manifest_parts = []
        geometry = {}
        batches = {}
        for index, part in enumerate(self.parts.values()):
            ob = part["object"]
            evaluated = ob.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
            mesh.calc_loop_triangles()
            if len(mesh.materials) != 1:
                raise RuntimeError("Source part needs exactly one material: " + part["id"])
            # Evaluated dependency-graph IDs can expire when the source objects
            # are replaced. Keep the original datablock across that boundary.
            material = bpy.data.materials[mesh.materials[0].name]
            vertices = [tuple(v.co) for v in mesh.vertices]
            faces = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
            uv_layer = mesh.uv_layers.active
            uvs = [tuple(uv_layer.data[loop].uv) if uv_layer else (0, 0)
                   for tri in mesh.loop_triangles for loop in tri.loops]
            smooth = [mesh.polygons[tri.polygon_index].use_smooth
                      for tri in mesh.loop_triangles]
            world = ob.matrix_world.copy()
            world_godot = godot_matrix(world)
            local_points = [tuple(TO_GODOT @ Vector(v)) for v in vertices]
            world_points = [tuple(world_godot @ Vector(v)) for v in local_points]
            evaluated.to_mesh_clear()
            group_id = part["render_group"]
            node_name = "batch::" + group_id + "::" + material.name
            owner_matrix = self.assemblies[group_id]["object"].matrix_world
            to_owner = owner_matrix.inverted() @ world
            batch = batches.setdefault((group_id, material.name), dict(
                name=node_name, material=material, vertices=[], faces=[], uvs=[], smooth=[], part_ids=[]))
            offset = len(batch["vertices"])
            batch["vertices"].extend(tuple(to_owner @ Vector(v)) for v in vertices)
            batch["faces"].extend(tuple(offset + i for i in face) for face in faces)
            batch["uvs"].extend(uvs)
            batch["smooth"].extend(smooth)
            batch["part_ids"].append(part["id"])
            geometry[part["id"]] = dict(vertices=vertices, faces=faces, uvs=uvs,
                                         smooth=smooth, material=material,
                                         world_points=world_points)
            manifest_parts.append(dict(
                id=part["id"], name=part["name"], assembly_id=part["assembly_id"],
                semantic_role=part["semantic_role"], source_node=ob.name,
                render_group=group_id, runtime_node=node_name,
                transform=matrix_list(godot_matrix(ob.matrix_local)),
                world_transform=matrix_list(world_godot),
                bounds=bounds(world_points), local_bounds=bounds(local_points),
                triangles=len(faces), materials=[material.name],
            ))
            if index % 500 == 0:
                print("Preserving part", index, "/", len(self.parts), flush=True)

        # Replace source geometry only after its editable .blend is safely saved.
        # Keep all assembly parents/transforms and stable object metadata.
        retired = []
        for index, part in enumerate(self.parts.values()):
            old = part["object"]
            data = geometry[part["id"]]
            parent, transform, name = old.parent, old.matrix_basis.copy(), old.name
            metadata = dict(old.items())
            old.name = "retired::" + str(index)
            retired.append(old)
            ob = self._mesh_object(name, data)
            ob.parent, ob.matrix_basis = parent, transform
            for key, value in metadata.items():
                ob[key] = value
            part["object"] = ob
            if index % 500 == 0:
                print("Triangulated part", index, "/", len(self.parts), flush=True)
        bpy.data.batch_remove(ids=retired)
        bpy.context.view_layer.update()
        source_objects = ([assembly["object"] for assembly in self.assemblies.values()]
                          + [part["object"] for part in self.parts.values()])
        self._export(assets / "room-parts.glb", source_objects)

        manifest_assemblies = []
        reviewable = []
        for assembly in self.assemblies.values():
            identifier = assembly["id"]
            ob = assembly["object"]
            part_ids = self.subtree_parts(identifier)
            points = [point for part_id in part_ids for point in geometry[part_id]["world_points"]]
            inverse = godot_matrix(ob.matrix_world).inverted()
            # Logical books/bottles share the enclosing case batch. Their own
            # node does not claim sibling geometry or parent-owned batches.
            groups = set(self.subtree(identifier))
            runtime_nodes = sorted(batch["name"] for (owner, _), batch in batches.items() if owner in groups)
            library_path = None
            if assembly["library"]:
                library_path = "res://assets/library/" + identifier + ".glb"
                parent, transform = ob.parent, ob.matrix_basis.copy()
                ob.parent = None
                ob.matrix_basis = Matrix.Identity(4)
                bpy.context.view_layer.update()
                objects = ([self.assemblies[child]["object"] for child in self.subtree(identifier)]
                           + [self.parts[part_id]["object"] for part_id in part_ids])
                self._export(runtime_assets / "library" / (identifier + ".glb"), objects)
                ob.parent, ob.matrix_basis = parent, transform
                bpy.context.view_layer.update()
                reviewable.append(identifier)
            manifest_assemblies.append(dict(
                id=identifier, name=assembly["name"], parent_id=assembly["parent_id"],
                semantic_role=assembly["semantic_role"], source_node=ob.name,
                runtime_node=ob.name, runtime_nodes=runtime_nodes,
                render_group=assembly["render_group"],
                transform=matrix_list(godot_matrix(ob.matrix_local)),
                world_transform=matrix_list(godot_matrix(ob.matrix_world)),
                bounds=bounds(points), local_bounds=bounds([tuple(inverse @ Vector(p)) for p in points]),
                part_ids=assembly["part_ids"], child_ids=assembly["child_ids"],
                subtree_part_ids=part_ids, library_path=library_path,
                library_root=ob.name if library_path else None,
                library_parts={pid: self.parts[pid]["object"].name for pid in part_ids} if library_path else {},
            ))

        for part in self.parts.values():
            bpy.data.objects.remove(part["object"], do_unlink=True)
        runtime_objects = [a["object"] for a in self.assemblies.values()]
        for (owner, material_name), batch in sorted(batches.items()):
            ob = self._mesh_object(batch["name"], batch)
            ob.parent = self.assemblies[owner]["object"]
            ob["office_assembly_id"] = owner
            ob["render_group"] = owner
            ob["office_batch_id"] = batch["name"]
            ob["material_name"] = material_name
            ob["source_part_count"] = len(batch["part_ids"])
            runtime_objects.append(ob)
        bpy.context.view_layer.update()
        self._export(runtime_assets / "whiskey-room.glb", runtime_objects)
        bpy.ops.wm.save_as_mainfile(filepath=str(assets / "room.blend"))
        manifest = dict(
            schema_version=1, units="meters", coordinate_system="Godot Y-up right-handed",
            transform_convention="column-major local-to-parent",
            source_glb="assets/room-parts.glb", source_blend="assets/room-parts.blend",
            runtime_glb="app/assets/whiskey-room.glb",
            assemblies=manifest_assemblies, parts=manifest_parts, anchors=self.anchors,
            reviewable_assemblies=reviewable,
            inventory=dict(assemblies=len(self.assemblies), parts=len(self.parts),
                           runtime_batches=len(batches), triangles=sum(p["triangles"] for p in manifest_parts),
                           materials=sorted({material for p in manifest_parts for material in p["materials"]})),
            notes=["Editable source hierarchy is preserved before evaluated geometry batching.",
                   "Source GLB and runtime batches reuse exactly the same triangulated part geometry.",
                   "Books and bottles have individual source assemblies; their enclosing furniture owns runtime batches.",
                   "Library roots are neutral; apply the assembly world_transform to reassemble them in the room.",
                   "Part bounds and semantic roles describe physical geometry, not automatic UI actions."],
        )
        (root / "app" / "office-assemblies.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    @staticmethod
    def _mesh_object(name, data):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(data["vertices"], [], data["faces"])
        mesh.update()
        mesh.materials.append(data["material"])
        layer = mesh.uv_layers.new(name="UVMap")
        for loop, uv in zip(layer.data, data["uvs"]):
            loop.uv = uv
        for polygon, smooth in zip(mesh.polygons, data["smooth"]):
            polygon.use_smooth = smooth
        ob = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(ob)
        return ob
