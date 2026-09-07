"""Independent, standard-library validation of modular office GLB reassembly.

GLB layout, accessor offsets/strides and column-major node transforms follow
https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html. This deliberately
supports the pipeline's static, uncompressed triangle meshes, not arbitrary
animated glTF. It never imports Blender or changes an asset.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import struct
import sys


class AssemblyValidationError(ValueError):
    pass


IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)
TOLERANCE = 0.00001  # ten micrometres; float32 export roundoff, not layout drift
MAX_GLB_BYTES = 512 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise AssemblyValidationError(message)


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, label + " must be a valid integer")
    return value


def vector(value, count, label):
    require(isinstance(value, (list, tuple)) and len(value) == count,
            label + f" must contain {count} numbers")
    require(all(type(v) in (int, float) and math.isfinite(v) for v in value),
            label + " contains a non-finite or invalid number")
    return tuple(float(v) for v in value)


def matrix(value, label):
    value = vector(value, 16, label)
    require(all(abs(value[i] - IDENTITY[i]) <= 1e-8 for i in (3, 7, 11, 15)),
            label + " must be an affine column-major transform")
    a, b, c, d, e, f, g, h, i = (value[n] for n in (0, 4, 8, 1, 5, 9, 2, 6, 10))
    determinant = a * (e*i-f*h) - b * (d*i-f*g) + c * (d*h-e*g)
    require(abs(determinant) > 1e-12, label + " is singular")
    return value


def multiply(a, b):
    return tuple(sum(a[k*4+r] * b[c*4+k] for k in range(4))
                 for c in range(4) for r in range(4))


def transform_point(m, p):
    return tuple(sum(m[k*4+r] * p[k] for k in range(3)) + m[12+r] for r in range(3))


def inverse(m):
    rows = [[m[c*4+r] for c in range(4)] + [float(c == r) for c in range(4)] for r in range(4)]
    for column in range(4):
        pivot = max(range(column, 4), key=lambda row: abs(rows[row][column]))
        require(abs(rows[pivot][column]) > 1e-14, "Assembly transform is singular")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        scale = rows[column][column]
        rows[column] = [value/scale for value in rows[column]]
        for row in range(4):
            if row != column:
                scale = rows[row][column]
                rows[row] = [rows[row][c]-scale*rows[column][c] for c in range(8)]
    return tuple(rows[r][c+4] for c in range(4) for r in range(4))


def close_matrix(actual, expected, label):
    expected = matrix(expected, label)
    require(all(abs(a-b) <= TOLERANCE for a, b in zip(actual, expected)), label + " differs from the GLB node transform")


def node_transform(node, label):
    if "matrix" in node:
        require(not any(k in node for k in ("translation", "rotation", "scale")),
                label + " mixes matrix and TRS transforms")
        return matrix(node["matrix"], label)
    t = vector(node.get("translation", [0, 0, 0]), 3, label + " translation")
    s = vector(node.get("scale", [1, 1, 1]), 3, label + " scale")
    x, y, z, w = vector(node.get("rotation", [0, 0, 0, 1]), 4, label + " rotation")
    require(abs(x*x+y*y+z*z+w*w-1) <= 1e-5, label + " quaternion is not normalized")
    r = (1-2*(y*y+z*z), 2*(x*y+z*w), 2*(x*z-y*w), 0,
         2*(x*y-z*w), 1-2*(x*x+z*z), 2*(y*z+x*w), 0,
         2*(x*z+y*w), 2*(y*z-x*w), 1-2*(x*x+y*y), 0,
         t[0], t[1], t[2], 1)
    return matrix(tuple(r[c*4+row] * s[c] if c < 3 else r[c*4+row]
                        for c in range(4) for row in range(4)), label)


def bounds(points):
    iterator = iter(points)
    first = next(iterator, None)
    require(first is not None, "Mesh geometry is empty")
    low, high = list(first), list(first)
    for point in iterator:
        for axis in range(3):
            low[axis] = min(low[axis], point[axis])
            high[axis] = max(high[axis], point[axis])
    return {"min": low, "max": high}


def checked_bounds(value, label):
    require(isinstance(value, dict), label + " must be a bounds object")
    low, high = vector(value.get("min"), 3, label + " minimum"), vector(value.get("max"), 3, label + " maximum")
    require(all(low[i] <= high[i] for i in range(3)), label + " minimum exceeds maximum")
    return {"min": low, "max": high}


def close_bounds(actual, expected, label):
    expected = checked_bounds(expected, label)
    require(all(abs(actual[key][i] - expected[key][i]) <= TOLERANCE
                for key in ("min", "max") for i in range(3)), label + " differs from actual GLB geometry")


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field: " + key)
        result[key] = value
    return result


def decode_json(data):
    try:
        return json.loads(data, object_pairs_hook=_unique_json,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              AssemblyValidationError("Non-finite JSON constant: " + value)))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AssemblyValidationError("Invalid JSON: " + str(exc)) from None


class GLB:
    def __init__(self, data, label="GLB"):
        self.label = label
        require(isinstance(data, bytes) and 28 <= len(data) <= MAX_GLB_BYTES, label + " size is invalid")
        magic, version, length = struct.unpack_from("<III", data)
        require((magic, version, length) == (0x46546C67, 2, len(data)), label + " has an invalid GLB2 header")
        chunks = []
        offset = 12
        while offset < len(data):
            require(offset + 8 <= len(data), label + " has a truncated chunk header")
            size, kind = struct.unpack_from("<II", data, offset)
            offset += 8
            require(size % 4 == 0 and offset + size <= len(data), label + " has a truncated or unaligned chunk")
            chunks.append((kind, data[offset:offset+size]))
            offset += size
        require([kind for kind, _ in chunks] == [0x4E4F534A, 0x004E4942],
                label + " requires exactly one JSON and one embedded BIN chunk")
        self.doc = decode_json(chunks[0][1])
        self.binary = chunks[1][1]
        self.sha256 = hashlib.sha256(data).hexdigest()
        require(isinstance(self.doc, dict) and self.doc.get("asset", {}).get("version") == "2.0", label + " is not glTF2")
        require(not self.doc.get("skins") and not self.doc.get("animations"), label + " must contain static assembly geometry")
        unsupported = set(self.doc.get("extensionsRequired", [])) - {"KHR_materials_emissive_strength"}
        require(not unsupported, label + " has unsupported required extensions: " + ", ".join(sorted(unsupported)))
        buffers = self.doc.get("buffers", [])
        require(len(buffers) == 1 and "uri" not in buffers[0], label + " must use one embedded buffer")
        declared = integer(buffers[0].get("byteLength"), label + " buffer length")
        require(declared <= len(self.binary) <= declared+3, label + " BIN length differs from its declared buffer")
        self.buffer_length = declared
        self.accessor_cache = {}
        self.position_cache = {}
        self.material_cache = {}
        self.nodes = self.doc.get("nodes", [])
        require(isinstance(self.nodes, list) and 0 < len(self.nodes) <= 20000, label + " node count is invalid")
        self.parents, self.world, self.local = {}, {}, {}
        self.names = defaultdict(list)
        scenes = self.doc.get("scenes", [])
        scene = self.item(scenes, self.doc.get("scene", 0), "scene")
        roots = scene.get("nodes", [])
        require(isinstance(roots, list) and roots, label + " has no active scene roots")
        active = set()
        def visit(index, parent, parent_matrix, depth):
            node = self.item(self.nodes, index, "node")
            require(index not in active and index not in self.parents, label + " has a node cycle or multiple parents")
            require(depth <= 80, label + " node hierarchy is too deep")
            active.add(index)
            self.parents[index] = parent
            require("skin" not in node and not node.get("weights"), label + " has unsupported deformed geometry")
            require("EXT_mesh_gpu_instancing" not in node.get("extensions", {}), label + " has unsupported GPU instances")
            self.local[index] = node_transform(node, label + f" node {index}")
            self.world[index] = multiply(parent_matrix, self.local[index])
            if "name" in node:
                require(isinstance(node["name"], str), label + " node name must be text")
                self.names[node["name"]].append(index)
            children = node.get("children", [])
            require(isinstance(children, list), label + " node children must be a list")
            for child in children:
                visit(child, index, self.world[index], depth+1)
            active.remove(index)
        for root in roots:
            visit(root, None, IDENTITY, 0)
        require(len(self.parents) == len(self.nodes), label + " contains detached nodes outside its active scene")

    @classmethod
    def from_path(cls, path):
        path = Path(path)
        require(path.is_file() and path.stat().st_size <= MAX_GLB_BYTES, "Missing or oversized GLB: " + str(path))
        return cls(path.read_bytes(), path.name)

    def item(self, items, index, label):
        require(isinstance(items, list) and type(index) is int and 0 <= index < len(items),
                self.label + " has an invalid " + label + " index")
        item = items[index]
        require(isinstance(item, dict), self.label + " " + label + " must be an object")
        return item

    def named(self, name):
        require(isinstance(name, str) and len(self.names.get(name, [])) == 1,
                self.label + " must contain exactly one node named " + str(name))
        return self.names[name][0]

    def under(self, node, ancestor):
        while node is not None:
            if node == ancestor:
                return True
            node = self.parents[node]
        return False

    def accessor(self, index, kind):
        key = (index, kind)
        if key in self.accessor_cache:
            return self.accessor_cache[key]
        accessor = self.item(self.doc.get("accessors", []), index, "accessor")
        require("sparse" not in accessor and not accessor.get("normalized"), self.label + " uses an unsupported sparse/normalized accessor")
        types = {"positions": ("VEC3", {5126: ("f", 4)}, 3),
                 "indices": ("SCALAR", {5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4)}, 1)}
        expected, formats, count = types[kind]
        require(accessor.get("type") == expected and accessor.get("componentType") in formats,
                self.label + " has an unsupported " + kind + " accessor")
        fmt, width = formats[accessor["componentType"]]
        view = self.item(self.doc.get("bufferViews", []), accessor.get("bufferView"), "bufferView")
        require(view.get("buffer", 0) == 0 and not view.get("extensions"), self.label + " uses an unsupported buffer view")
        base = integer(view.get("byteOffset", 0), "Buffer offset")
        size = integer(view.get("byteLength"), "Buffer view length")
        start = integer(accessor.get("byteOffset", 0), "Accessor offset")
        length = integer(accessor.get("count"), "Accessor count", 1)
        require(length <= 12000000, self.label + " accessor exceeds the validation limit")
        stride = integer(view.get("byteStride", count*width), "Accessor stride", count*width)
        require(stride % width == 0 and start % width == 0 and base % width == 0,
                self.label + " accessor is misaligned")
        require(base+size <= self.buffer_length and start+(length-1)*stride+count*width <= size,
                self.label + " accessor exceeds its buffer view")
        unpack = struct.Struct("<" + fmt*count).unpack_from
        result = tuple(unpack(self.binary, base+start+i*stride) for i in range(length))
        if kind == "positions":
            require(all(math.isfinite(v) for point in result for v in point), self.label + " has non-finite mesh positions")
            if "min" in accessor or "max" in accessor:
                close_bounds(bounds(result), {"min": accessor.get("min"), "max": accessor.get("max")}, self.label + " POSITION accessor bounds")
        else:
            result = tuple(value[0] for value in result)
        self.accessor_cache[key] = result
        return result

    def material(self, index):
        if index in self.material_cache:
            return self.material_cache[index]
        material = self.item(self.doc.get("materials", []), index, "material")
        name = material.get("name")
        require(isinstance(name, str) and name, self.label + " materials require stable names")
        def texture_signature(index):
            texture = self.item(self.doc.get("textures", []), index, "texture")
            require(not texture.get("extensions"), self.label + " has unsupported texture indirection")
            image = self.item(self.doc.get("images", []), texture.get("source"), "image")
            require("uri" not in image, self.label + " material uses an external image")
            view = self.item(self.doc.get("bufferViews", []), image.get("bufferView"), "image bufferView")
            start = integer(view.get("byteOffset", 0), "Image offset")
            size = integer(view.get("byteLength"), "Image length", 1)
            require(view.get("buffer", 0) == 0 and start+size <= self.buffer_length, self.label + " image exceeds the embedded buffer")
            sampler = self.item(self.doc.get("samplers", []), texture["sampler"], "sampler") if "sampler" in texture else {}
            return {"image_sha256": hashlib.sha256(self.binary[start:start+size]).hexdigest(), "sampler": sampler}
        def normalize(value, parent=""):
            if isinstance(value, dict):
                return {key: texture_signature(item) if key == "index" and parent.lower().endswith("texture")
                        else normalize(item, key) for key, item in value.items() if key not in {"name", "extras"}}
            if isinstance(value, list):
                return [normalize(item, parent) for item in value]
            return value
        signature = hashlib.sha256(json.dumps(normalize(material), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        result = (name, signature)
        self.material_cache[index] = result
        return result

    def primitives(self, node_index):
        node = self.nodes[node_index]
        mesh = self.item(self.doc.get("meshes", []), node.get("mesh"), "mesh")
        primitives = mesh.get("primitives", [])
        require(isinstance(primitives, list) and primitives, self.label + " mesh has no primitives")
        for primitive in primitives:
            require(isinstance(primitive, dict) and primitive.get("mode", 4) == 4 and not primitive.get("targets")
                    and not primitive.get("extensions"), self.label + " requires uncompressed static TRIANGLES")
            position_id = primitive.get("attributes", {}).get("POSITION")
            positions = self.accessor(position_id, "positions")
            key = (node_index, position_id)
            if key not in self.position_cache:
                self.position_cache[key] = tuple(transform_point(self.world[node_index], point) for point in positions)
            positions = self.position_cache[key]
            indices = self.accessor(primitive["indices"], "indices") if "indices" in primitive else tuple(range(len(positions)))
            require(len(indices) % 3 == 0 and all(0 <= i < len(positions) for i in indices), self.label + " triangle indices are invalid")
            yield self.material(primitive.get("material")), positions, indices

    def triangles(self, node_indices):
        for node in node_indices:
            for material, positions, indices in self.primitives(node):
                for offset in range(0, len(indices), 3):
                    yield material, tuple(positions[indices[offset+i]] for i in range(3))

    def mesh_nodes(self):
        return {i for i, node in enumerate(self.nodes) if "mesh" in node}


def triangle_key(triangle):
    vertices = sorted(tuple(round(value/TOLERANCE) for value in point) for point in triangle)
    require(all(abs(value) < 2**63 for point in vertices for value in point), "Geometry exceeds the supported coordinate range")
    return hashlib.blake2b(struct.pack("<9q", *(v for point in vertices for v in point)), digest_size=20).digest()


def geometry_inventory(glb, node_indices):
    triangles = Counter()
    by_material = Counter()
    all_points = []
    signatures = {}
    for material, triangle in glb.triangles(node_indices):
        name, signature = material
        require(name not in signatures or signatures[name] == signature, glb.label + " aliases different materials under " + name)
        signatures[name] = signature
        triangles[(name, triangle_key(triangle))] += 1
        by_material[name] += 1
        all_points.extend(triangle)
    require(triangles, glb.label + " assembly contains no triangles")
    return {"triangles": sum(by_material.values()), "materials": dict(sorted(by_material.items())),
            "material_signatures": signatures, "bounds": bounds(all_points), "faces": triangles}


def equivalent_geometry(source, source_nodes, runtime, runtime_nodes, left, right, label):
    require(left["triangles"] == right["triangles"] and left["materials"] == right["materials"],
            label + " runtime triangle/material inventory differs from its source parts")
    require(left["material_signatures"] == right["material_signatures"], label + " runtime material/embedded texture payload differs from source")
    close_bounds(left["bounds"], right["bounds"], label + " source/runtime bounds")
    if left["faces"] == right["faces"]:
        return
    # Quantized hashing is the fast path. Near a quantization boundary, two
    # float32 exports may differ by much less than the allowed tolerance but
    # round to adjacent bins; compare only unmatched faces geometrically.
    missing = left["faces"] - right["faces"]
    extra = right["faces"] - left["faces"]
    cells = defaultdict(list)
    cell_width = TOLERANCE * 4
    def cell(triangle):
        return tuple(math.floor(sum(p[i] for p in triangle)/3/cell_width) for i in range(3))
    for material, triangle in runtime.triangles(runtime_nodes):
        key = (material[0], triangle_key(triangle))
        if extra[key]:
            extra[key] -= 1
            cells[(material[0], cell(triangle))].append(triangle)
    for material, triangle in source.triangles(source_nodes):
        key = (material[0], triangle_key(triangle))
        if not missing[key]:
            continue
        missing[key] -= 1
        center = cell(triangle)
        found = False
        for delta in itertools.product((-1, 0, 1), repeat=3):
            candidates = cells.get((material[0], tuple(center[i]+delta[i] for i in range(3))), [])
            for index, candidate in enumerate(candidates):
                if any(all(abs(triangle[p][axis] - ordered[p][axis]) <= TOLERANCE
                           for p in range(3) for axis in range(3)) for ordered in itertools.permutations(candidate)):
                    candidates.pop(index)
                    found = True
                    break
            if found:
                break
        require(found, label + " runtime geometry contains missing, displaced or duplicated source triangles")


def stable_id(value, label):
    require(isinstance(value, str) and value.strip() == value and 0 < len(value) <= 160
            and all(ord(c) >= 32 for c in value), label + " must be a nonempty stable ID")
    return value


def records_by_id(records, label):
    require(isinstance(records, list) and records, label + " must be a nonempty list")
    result = {}
    for record in records:
        require(isinstance(record, dict), label + " entries must be objects")
        key = stable_id(record.get("id"), label + " ID")
        require(key not in result, "Duplicate " + label + " ID: " + key)
        stable_id(record.get("semantic_role"), label + " " + key + " semantic role")
        result[key] = record
    return result


def unique_list(value, label):
    require(isinstance(value, list) and all(isinstance(v, str) for v in value), label + " must be a string list")
    require(len(value) == len(set(value)), label + " contains duplicate entries")
    return set(value)


def node_points(glb, node_indices):
    for node in node_indices:
        for _material, positions, indices in glb.primitives(node):
            for index in indices:
                yield positions[index]


def validate_document(document, source, runtime, *, layout=None, libraries=None):
    """Validate v1 manifest against independently decoded source/runtime bytes.

    Hierarchy ownership and complete geometry coverage prove there are no
    detached/unassigned nodes or lost components. They do not prove physical
    contact, watertightness, collision comfort, UVs, normals or visual quality.
    """
    require(isinstance(document, dict) and document.get("schema_version") == 1,
            "office-assemblies schema_version must be 1")
    require(document.get("units") == "meters", "Assembly units must be meters")
    require(document.get("coordinate_system") == "Godot Y-up right-handed", "Unsupported assembly coordinate system")
    require(document.get("transform_convention") == "column-major local-to-parent", "Unsupported assembly transform convention")
    assemblies = records_by_id(document.get("assemblies"), "assembly")
    parts = records_by_id(document.get("parts"), "part")
    require(not set(assemblies) & set(parts), "Assembly and part IDs overlap")
    descendants = {}
    def descendant_ids(key, visiting=()):
        require(key not in visiting, "Assembly hierarchy contains a cycle at " + key)
        if key not in descendants:
            ids = {key}
            for child, record in assemblies.items():
                if record.get("parent_id") == key:
                    ids.update(descendant_ids(child, visiting+(key,)))
            descendants[key] = ids
        return descendants[key]
    source_assembly_nodes = {}
    for key, assembly in assemblies.items():
        parent = assembly.get("parent_id")
        require(parent is None or parent in assemblies, "Assembly " + key + " has an unknown parent")
        expected_children = {child for child, record in assemblies.items() if record.get("parent_id") == key}
        require(unique_list(assembly.get("child_ids"), key + " child_ids") == expected_children,
                "Assembly " + key + " child ownership is inconsistent")
        descendant_ids(key)
        require(assembly.get("source_node") == "assembly::" + key, "Assembly " + key + " source node is not its stable ID")
        source_assembly_nodes[key] = source.named(assembly["source_node"])
    require(len(set(source_assembly_nodes.values())) == len(assemblies), "Assembly source nodes are aliased")
    for key, assembly in assemblies.items():
        node = source_assembly_nodes[key]
        expected_parent = source_assembly_nodes.get(assembly.get("parent_id"))
        require(source.parents[node] == expected_parent, "Assembly " + key + " source parent differs from declared ownership")
        require(source.nodes[node].get("extras", {}).get("office_assembly_id") == key,
                "Assembly " + key + " source node has the wrong assembly identity")
        close_matrix(source.local[node], assembly.get("transform"), key + " local transform")
        close_matrix(source.world[node], assembly.get("world_transform"), key + " world transform")
    source_part_nodes = {}
    batch_parts = defaultdict(list)
    group_parts = defaultdict(list)
    part_report = {}
    for key, part in parts.items():
        owner = part.get("assembly_id")
        require(owner in assemblies, "Part " + key + " has an unknown assembly owner")
        group = part.get("render_group")
        require(group in assemblies, "Part " + key + " has an unknown render group")
        require(part.get("source_node") == "part::" + key, "Part " + key + " source node is not its stable ID")
        node = source.named(part["source_node"])
        require(node not in source_part_nodes.values(), "Part source node is aliased: " + key)
        require(node in source.mesh_nodes() and source.parents[node] == source_assembly_nodes[owner],
                "Part " + key + " is detached from its owning source assembly")
        extras = source.nodes[node].get("extras", {})
        require(extras.get("office_part_id") == key and extras.get("office_assembly_id") == owner
                and extras.get("render_group") == group, "Part " + key + " GLB identity/ownership extras disagree")
        source_part_nodes[key] = node
        close_matrix(source.local[node], part.get("transform"), key + " local transform")
        close_matrix(source.world[node], part.get("world_transform"), key + " world transform")
        inventory = geometry_inventory(source, [node])
        require(integer(part.get("triangles"), key + " triangles", 1) == inventory["triangles"],
                "Part " + key + " triangle count disagrees with its source")
        require(unique_list(part.get("materials"), key + " materials") == set(inventory["materials"]),
                "Part " + key + " material inventory disagrees with its source")
        close_bounds(inventory["bounds"], part.get("bounds"), key + " world bounds")
        local_points = (transform_point(inverse(source.world[node]), p) for p in node_points(source, [node]))
        close_bounds(bounds(local_points), part.get("local_bounds"), key + " local bounds")
        batch_name = part.get("runtime_node")
        runtime_node = runtime.named(batch_name)
        require(runtime_node in runtime.mesh_nodes(), "Part " + key + " runtime binding is not a mesh batch")
        batch_extra = runtime.nodes[runtime_node].get("extras", {})
        require(batch_extra.get("render_group") == group and batch_extra.get("office_assembly_id") == group,
                "Part " + key + " runtime batch belongs to a different render group")
        require(isinstance(batch_name, str) and batch_name.startswith("batch::" + group + "::"),
                "Part " + key + " runtime batch name disagrees with its render group")
        batch_parts[runtime_node].append(key)
        group_parts[group].append(key)
        part_report[key] = {k: inventory[k] for k in ("triangles", "materials", "bounds")}
    require(set(source_part_nodes.values()) == source.mesh_nodes(), "Source GLB has detached/unassigned mesh components")
    require(set(batch_parts) == runtime.mesh_nodes(), "Runtime GLB has detached/unassigned mesh batches")
    assembly_report = {}
    listed_batches = set()
    for key, assembly in assemblies.items():
        own_parts = {pid for pid, part in parts.items() if part["assembly_id"] == key}
        require(unique_list(assembly.get("part_ids"), key + " part_ids") == own_parts,
                "Assembly " + key + " part ownership is inconsistent")
        subtree_parts = [pid for pid, part in parts.items() if part["assembly_id"] in descendants[key]]
        require(subtree_parts, "Assembly " + key + " is empty and not represented by source parts")
        nodes = [source_part_nodes[pid] for pid in subtree_parts]
        actual_bounds = bounds(node_points(source, nodes))
        close_bounds(actual_bounds, assembly.get("bounds"), key + " world bounds")
        inv = inverse(source.world[source_assembly_nodes[key]])
        close_bounds(bounds(transform_point(inv, p) for p in node_points(source, nodes)),
                     assembly.get("local_bounds"), key + " local bounds")
        declared_batches = unique_list(assembly.get("runtime_nodes"), key + " runtime_nodes")
        bound_batches = {parts[pid]["runtime_node"] for pid in subtree_parts}
        require(declared_batches <= bound_batches, "Assembly " + key + " lists a runtime batch outside its semantic subtree")
        listed_batches.update(declared_batches)
        root_name = assembly.get("runtime_node")
        if root_name is not None:
            root_node = runtime.named(root_name)
            require(runtime.nodes[root_node].get("extras", {}).get("office_assembly_id") == key,
                    "Assembly " + key + " runtime root identity is incorrect")
            close_matrix(runtime.world[root_node], assembly.get("world_transform"), key + " runtime world transform")
            require(all(runtime.under(runtime.named(name), root_node) for name in declared_batches),
                    "Assembly " + key + " has detached runtime children")
        assembly_report[key] = {"parts": len(subtree_parts), "triangles": sum(parts[pid]["triangles"] for pid in subtree_parts),
                                "runtime_batches": len(declared_batches), "bounds": actual_bounds}
    require(listed_batches == {runtime.nodes[node]["name"] for node in batch_parts}, "Assembly inventory omits runtime batches")
    batch_report = {}
    for runtime_node, part_ids in batch_parts.items():
        name = runtime.nodes[runtime_node]["name"]
        source_nodes = [source_part_nodes[pid] for pid in part_ids]
        left = geometry_inventory(source, source_nodes)
        right = geometry_inventory(runtime, [runtime_node])
        equivalent_geometry(source, source_nodes, runtime, [runtime_node], left, right, name)
        batch_report[name] = {"source_parts": len(part_ids), "triangles": right["triangles"],
                              "materials": right["materials"], "bounds": right["bounds"]}
    anchors = document.get("anchors", {})
    require(isinstance(anchors, dict), "anchors must be an object")
    for key, anchor in anchors.items():
        stable_id(key, "Anchor ID")
        require(isinstance(anchor, dict) and anchor.get("assembly_id") in assemblies, "Anchor " + key + " has an unknown owner")
        owner = anchor["assembly_id"]
        local = matrix(anchor.get("transform"), "Anchor " + key + " transform")
        world_position = transform_point(source.world[source_assembly_nodes[owner]], local[12:15])
        position = vector(anchor.get("position"), 3, "Anchor " + key + " world position")
        require(all(abs(a-b) <= TOLERANCE for a, b in zip(position, world_position)), "Anchor " + key + " is detached from its assembly transform")
    library_report = _validate_libraries(document, assemblies, parts, source, source_part_nodes, libraries or {})
    if layout is not None:
        _validate_desk_anchors(anchors, layout)
    return {"passed": True, "schema_version": 1, "tolerance_m": TOLERANCE,
            "source_sha256": source.sha256, "runtime_sha256": runtime.sha256,
            "inventory": {"assemblies": len(assemblies), "parts": len(parts), "runtime_batches": len(batch_parts),
                          "triangles": sum(p["triangles"] for p in parts.values()),
                          "materials": sorted({name for part in part_report.values() for name in part["materials"]})},
            "assemblies": assembly_report, "batches": batch_report, "libraries": library_report,
            "checks": ["stable_ids", "source_hierarchy_ownership", "nonsingular_transforms", "declared_bounds",
                       "complete_mesh_coverage", "triangle_material_inventory", "source_runtime_geometry",
                       "material_and_embedded_image_payloads", "anchor_transforms"],
            "limitations": ["Geometry equivalence compares triangle positions within tolerance, not UVs/normals/winding.",
                            "No orphan scene components or missing geometry; physical contact/watertightness and visual quality require separate review."]}


def _validate_desk_anchors(anchors, layout):
    require(isinstance(layout, dict), "Office layout must be an object")
    # IDs are finalized with the modeling manifest; exact supported mapping is
    # explicit so an unrelated anchor cannot masquerade as the desktop mount.
    if "desk_screen" not in anchors:
        raise AssemblyValidationError("Missing desk_screen anchor for the live desktop surface")
    screen = anchors["desk_screen"]
    display = layout.get("desk_display", {})
    wanted = vector(display.get("position"), 3, "Live desk display position")
    require(all(abs(a-b) <= TOLERANCE for a, b in zip(screen["position"], wanted)),
            "Desk screen anchor does not align with the live desktop surface")
    size = vector(screen.get("size"), 2, "Desk screen anchor size")
    require(all(abs(size[i]-display.get(key, -1)) <= TOLERANCE for i, key in enumerate(("width", "height"))),
            "Desk screen anchor dimensions do not match the live desktop surface")


def _validate_libraries(document, assemblies, parts, source, source_part_nodes, libraries):
    # Library-specific bindings are filled by the agreed manifest, not inferred
    # from a mesh name or a runtime material batch.
    reviewable = document.get("reviewable_assemblies", [])
    require(isinstance(reviewable, list) and all(isinstance(v, str) for v in reviewable)
            and len(reviewable) == len(set(reviewable)), "reviewable_assemblies must contain unique assembly IDs")
    report = {}
    for key in reviewable:
        require(key in assemblies, "Unknown reviewable assembly: " + key)
        assembly = assemblies[key]
        require(key in libraries, "Reviewable assembly library was not supplied: " + key)
        library = libraries[key]
        root = library.named(assembly.get("library_root"))
        close_matrix(library.world[root], IDENTITY, key + " library root transform")
        binding = assembly.get("library_parts")
        require(isinstance(binding, dict) and binding, key + " library_parts must bind source part IDs")
        source_root = source.named(assembly["source_node"])
        expected = {pid for pid, node in source_part_nodes.items() if source.under(node, source_root)}
        require(set(binding) == expected, key + " library omits or adds source parts")
        names = list(binding.values())
        require(all(isinstance(name, str) for name in names) and len(names) == len(set(names)), key + " library node bindings are aliased")
        nodes = [library.named(name) for name in names]
        require(set(nodes) == library.mesh_nodes() and all(library.under(n, root) for n in nodes), key + " library contains detached or unassigned mesh components")
        original_world = library.world.copy()
        try:
            placement = matrix(assembly["world_transform"], key + " library placement")
            for node in library.world:
                library.world[node] = multiply(placement, original_world[node])
            library.position_cache.clear()
            for pid, name in binding.items():
                node = library.named(name)
                left = geometry_inventory(source, [source_part_nodes[pid]])
                right = geometry_inventory(library, [node])
                equivalent_geometry(source, [source_part_nodes[pid]], library, [node], left, right, key + " library part " + pid)
        finally:
            library.world = original_world
            library.position_cache.clear()
        report[key] = {"passed": True, "parts": len(binding), "sha256": library.sha256}
    return report


def project_path(root, relative, label, *, resource=False):
    require(isinstance(relative, str) and relative, label + " path is missing")
    if resource:
        require(relative.startswith("res://"), label + " must be a res:// resource path")
        relative = "app/" + relative[6:]
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts, label + " must stay inside the project")
    resolved = root / path
    require(resolved.resolve().is_relative_to(root.resolve()) and not any(p.is_symlink() for p in (resolved, *resolved.parents)),
            label + " path is redirected outside the project")
    return resolved


def validate_files(manifest, root=None, layout=None):
    root = Path(root or Path(__file__).resolve().parent).resolve()
    manifest = Path(manifest)
    document = decode_json(manifest.read_bytes())
    source = GLB.from_path(project_path(root, document.get("source_glb"), "Source GLB"))
    runtime = GLB.from_path(project_path(root, document.get("runtime_glb"), "Runtime GLB"))
    library_glbs = {}
    for assembly in document.get("assemblies", []):
        if assembly.get("id") in document.get("reviewable_assemblies", []):
            library_glbs[assembly["id"]] = GLB.from_path(project_path(root, assembly.get("library_path"), "Library", resource=True))
    layout_data = decode_json(Path(layout).read_bytes()) if layout is not None else None
    report = validate_document(document, source, runtime, layout=layout_data, libraries=library_glbs)
    report["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent
    parser.add_argument("--manifest", type=Path, default=root / "app/office-assemblies.json")
    parser.add_argument("--project-root", type=Path, default=root)
    parser.add_argument("--layout", type=Path, default=root / "app/office-layout.json")
    args = parser.parse_args(argv)
    try:
        report = validate_files(args.manifest, args.project_root, args.layout)
    except (AssemblyValidationError, OSError, KeyError, TypeError, struct.error) as exc:
        report = {"passed": False, "errors": [str(exc)]}
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
