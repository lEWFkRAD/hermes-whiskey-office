extends Node
## The running scene is the sole writer of truth and action receipts.
## This narrow local tool accepts primitives, never code, file paths or prompts.
var office: Node
var workspace := ""
var instance := ""
var age := 0.0
var handled: Dictionary = {}

func setup(owner_office: Node, directory: String, scene_instance: String) -> void:
	office = owner_office
	workspace = directory
	instance = scene_instance
	if workspace.is_empty(): return
	for folder in [".scene-commands", ".scene-results"]:
		DirAccess.make_dir_recursive_absolute(workspace.path_join(folder))

static func validate(row: Dictionary, expected_instance: String, now: float) -> String:
	if row.get("schema") != 1 or row.get("instance") != expected_instance: return "Wrong scene instance"
	var id := str(row.get("id", ""))
	if id.length() != 32 or not id.is_valid_hex_number(): return "Invalid request ID"
	var expires: Variant = row.get("expires_at")
	if not (expires is float or expires is int) or not is_finite(expires) or expires < now or expires > now + 30: return "Expired or invalid request"
	if row.get("action") != "primitive" or row.get("shape") not in ["sphere", "box"]: return "Unsupported shape action"
	var radius: Variant = row.get("radius")
	if not (radius is float or radius is int) or not is_finite(radius) or radius < 0.02 or radius > 0.5: return "Radius must be 0.02 to 0.5 meters"
	var color := str(row.get("color", ""))
	if color.length() != 6 or not color.is_valid_hex_number(): return "Expected six-digit RGB color"
	if not row.get("label") is String or row.label.is_empty() or row.label.length() > 80: return "Expected a short label"
	if not row.get("replace", false) is bool: return "Invalid replace flag"
	return ""

func execute(row: Dictionary, now: float) -> Dictionary:
	var error := validate(row, instance, now)
	if not error.is_empty(): return {"status": "error", "error": error}
	var id: String = row.id
	if handled.has(id): return handled[id]
	var projector: Node3D = office.hologram
	var fabricator: Node3D = office.fabricator
	if not projector or not fabricator: return {"status": "error", "error": "Podium is unavailable"}
	if is_instance_valid(fabricator.held): return {"status": "error", "error": "Finish placing the held object first"}
	if not row.get("replace", false) and (is_instance_valid(projector.projection) or is_instance_valid(projector.live_window)):
		return {"status": "error", "error": "Podium is occupied; use --replace only when requested"}
	var model := MeshInstance3D.new()
	var mesh: PrimitiveMesh
	if row.shape == "sphere":
		var sphere := SphereMesh.new()
		sphere.radius = row.radius
		sphere.height = row.radius * 2.0
		mesh = sphere
	else:
		var box := BoxMesh.new()
		box.size = Vector3.ONE * float(row.radius) * 2.0
		mesh = box
	model.mesh = mesh
	var material := StandardMaterial3D.new()
	material.albedo_color = Color("#" + str(row.color))
	material.roughness = 0.32
	model.material_override = material
	if not projector.present_model(model, row.label):
		model.queue_free()
		return {"status": "error", "error": "Podium refused the model"}
	projector.projection.set_meta("fabricated_id", id)
	projector.projection.set_meta("scene_primitive", true)
	projector.projection.set_meta("scene_label", row.label)
	# Keep the requested physical size; asset presentations ordinarily fit to 1m.
	var child: Node3D = projector.projection.get_child(0)
	child.scale = Vector3.ONE
	child.position = Vector3.ZERO
	projector.set_readable(true)
	fabricator.note = str(row.label) + " ready · point and grip to pick up"
	fabricator.paint()
	var result := {"status": "done", "object_id": id, "label": row.label, "shape": row.shape, "scene_instance": instance, "position_m": [projector.projection.global_position.x, projector.projection.global_position.y, projector.projection.global_position.z]}
	handled[id] = result
	return result

func poll() -> void:
	if workspace.is_empty(): return
	var folder := workspace.path_join(".scene-commands")
	var count := 0
	for name in DirAccess.get_files_at(folder):
		if not name.ends_with(".json") or name.length() != 37 or not name.trim_suffix(".json").is_valid_hex_number(): continue
		count += 1
		if count > 8: break
		var path := folder.path_join(name)
		var file := FileAccess.open(path, FileAccess.READ)
		if not file: continue
		var row: Variant = JSON.parse_string(file.get_as_text()) if file.get_length() <= 2048 else null
		file.close()
		var result := {"status": "error", "error": "Malformed request"}
		if row is Dictionary and row.get("id") == name.trim_suffix(".json"):
			result = execute(row, Time.get_unix_time_from_system())
		result["id"] = name.trim_suffix(".json")
		result["updated_at"] = Time.get_unix_time_from_system()
		var receipt := workspace.path_join(".scene-results/" + name)
		var output := FileAccess.open(receipt + ".tmp", FileAccess.WRITE)
		if output:
			output.store_string(JSON.stringify(result))
			output.close()
			DirAccess.rename_absolute(receipt + ".tmp", receipt)
			DirAccess.remove_absolute(path)

func _process(delta: float) -> void:
	age += delta
	if age >= 0.1:
		age = 0.0
		poll()
