extends Node
## Bounded virtual-scene facts. No screen contents, audio or camera samples.
var office: Node
var path := ""
var instance := str(Time.get_unix_time_from_system()) + "-" + str(OS.get_process_id())
var age := 0.0
var sequence := 0

func setup(root: Node) -> void:
	office = root
	var data := OS.get_environment("HERMES_OFFICE_DATA_DIR")
	if not data.is_empty():
		var workspace := data.path_join("workspace")
		DirAccess.make_dir_recursive_absolute(workspace)
		path = workspace.path_join(".hermes-office-context.json")
		publish()

static func coordinates(value: Vector3) -> Array:
	return [snappedf(value.x, 0.01), snappedf(value.y, 0.01), snappedf(value.z, 0.01)]

func snapshot() -> Dictionary:
	var viewer: Node3D = office.xr_camera if office.xr_active else office.camera
	var windows: Array = []
	if office.office_windows:
		for id: String in office.office_windows.surfaces:
			var surface: Node3D = office.office_windows.surfaces[id]
			if not surface.is_open(): continue
			windows.append({"id": id.left(80), "title": str(surface.window_title).left(120), "connected": surface.connected,
				"position_m": coordinates(surface.global_position), "active": id == office.office_windows.active_id})
	var result := {"schema": 1, "instance": instance, "sequence": sequence,
		"updated_at": Time.get_unix_time_from_system(), "running": true,
		"workspace": path.get_base_dir(), "venue": "Hermes Whiskey Office",
		"mode": "passthrough" if office.passthrough_active else ("VR" if office.xr_active else "desktop preview"),
		"viewer_position_m": coordinates(viewer.global_position), "viewer_forward": coordinates(-viewer.global_basis.z),
		"windows": windows, "pointed_window": str(office.office_windows.pointed_id) if office.office_windows else "",
		"podium": str(office.hologram.source_name).left(120) if office.hologram else "unavailable",
		"render_status": str(office.fabricator.note).left(200) if office.fabricator else "unavailable",
		"physical_camera": "not connected", "microphone": "controlled by Hermes; not observed by scene exporter"}
	return result

func publish() -> void:
	if path.is_empty() or not is_instance_valid(office): return
	sequence += 1
	var file := FileAccess.open(path + ".tmp", FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(snapshot()))
		file.close()
		DirAccess.rename_absolute(path + ".tmp", path)

func _process(delta: float) -> void:
	age += delta
	if age >= 0.5:
		age = 0
		publish()

func _exit_tree() -> void:
	if path.is_empty() or not FileAccess.file_exists(path): return
	var current: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if current is Dictionary and current.get("instance") == instance:
		DirAccess.remove_absolute(path)
