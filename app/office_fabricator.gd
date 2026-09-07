extends Node3D
## Image conversion is external work. Only complete, hash-checked GLBs become objects.
const Podium = preload("res://office_hologram.gd")
var podium: Node3D
var head: Node3D
var ipc := ""
var data := ""
var jobs: Array = []
var seen: Dictionary = {}
var placements: Dictionary = {}
var objects: Dictionary = {}
var held: Node3D
var grip_offset := Transform3D.IDENTITY
var grip_down := false
var mouse_held := false
var mouse_depth := 1.0
var last_picked := ""
var ray_limit := 4.0
var elapsed := 0.0
var selected_image := ""
var image_index := -1
var output_index := -1
var presented_id := ""
var restored_session := false
var preset := "fast"
var note := "Open an image or choose Next image from the Loading Bay Inbox"
var status_label: Label
var spatial_label: Label3D

func setup(projector: Node3D, camera: Node3D, desktop_ui: bool) -> void:
	podium = projector
	head = camera
	ipc = OS.get_environment("HERMES_PODIUM_IPC_DIR")
	data = OS.get_environment("HERMES_PODIUM_DATA_DIR")
	if not data.is_empty():
		var saved: Variant = JSON.parse_string(FileAccess.get_file_as_string(data.path_join("placements.json"))) if FileAccess.file_exists(data.path_join("placements.json")) else {}
		if saved is Dictionary:
			seen = saved.get("seen", {})
			placements = saved.get("placements", {})
			presented_id = str(saved.get("presented", ""))
	spatial_label = Label3D.new()
	spatial_label.position = Podium.CENTER + Vector3(0, 0.70, 0.52)
	spatial_label.font_size = 21
	spatial_label.pixel_size = 0.001
	spatial_label.modulate = Color("d6e8ce")
	spatial_label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	add_child(spatial_label)
	if desktop_ui:
		var layer := CanvasLayer.new()
		layer.layer = 21
		add_child(layer)
		var stack := VBoxContainer.new()
		stack.position = Vector2(24, 218)
		layer.add_child(stack)
		var bar := HBoxContainer.new()
		stack.add_child(bar)
		for title in ["Next image", "Render image", "Fast / Detailed", "Ready objects", "Return object"]:
			var button := Button.new()
			button.text = title
			bar.add_child(button)
			button.pressed.connect(func() -> void:
				match title:
					"Next image": next_image()
					"Render image": render_image()
					"Fast / Detailed": toggle_quality()
					"Ready objects": next_output()
					"Return object": return_held()
			)
		status_label = Label.new()
		status_label.add_theme_font_size_override("font_size", 14)
		stack.add_child(status_label)
	paint()

func paint() -> void:
	if status_label: status_label.text = note.left(150) + " · " + preset.capitalize()
	if spatial_label: spatial_label.text = note.left(88)

func toggle_quality() -> void:
	preset = "detailed" if preset == "fast" else "fast"
	note = preset.capitalize() + " selected · choose Render image to start"
	paint()

func next_image() -> bool:
	var inbox := OS.get_environment("HERMES_OFFICE_DATA_DIR").path_join("loading-bay/Inbox")
	var candidates: Array[String] = []
	for name in DirAccess.get_files_at(inbox):
		if name.get_extension().to_lower() in ["png", "jpg", "jpeg"]: candidates.append(inbox.path_join(name))
	candidates.sort()
	if candidates.is_empty():
		note = "Put a PNG or JPEG in Loading Bay → Inbox, or use Open file"
		paint()
		return false
	image_index = posmod(image_index + 1, candidates.size())
	selected_image = candidates[image_index]
	var loaded: bool = podium.load_file(selected_image)
	note = selected_image.get_file() + " · Render image to build it" if loaded else "Could not preview image"
	paint()
	return loaded

func render_image() -> bool:
	# Open file has already previewed the exact user-selected image.
	var source: String = podium._file_path
	if source.get_extension().to_lower() not in ["png", "jpg", "jpeg"]:
		note = "Preview an image first, then Render image"
		paint()
		return false
	if ipc.is_empty() or not DirAccess.dir_exists_absolute(ipc.path_join("commands")):
		note = "Image pipeline is unavailable in this session"
		paint()
		return false
	var id := Crypto.new().generate_random_bytes(16).hex_encode()
	var path := ipc.path_join("commands/" + id)
	var file := FileAccess.open(path + ".tmp", FileAccess.WRITE)
	if not file: return false
	file.store_string(JSON.stringify({"action": "render", "id": id, "image": source, "preset": preset}))
	file.close()
	if DirAccess.rename_absolute(path + ".tmp", path + ".json") != OK: return false
	selected_image = source
	note = "Render requested · image stays here until the model is ready"
	paint()
	return true

func valid_output(row: Dictionary) -> bool:
	var id := str(row.get("id", ""))
	var path := str(row.get("path", ""))
	return row.get("phase") == "ready" and id.length() == 32 and not data.is_empty() and path == data.path_join("jobs/" + id + "/final.glb") and FileAccess.file_exists(path) and FileAccess.get_sha256(path) == str(row.get("sha256", ""))

func present_output(row: Dictionary) -> bool:
	if held or not valid_output(row): return false
	var id := str(row.id)
	if not podium.load_file(str(row.path)): return false
	# Completed artifacts are immutable. No hot reload may replace a held copy.
	podium._file_path = ""
	podium.projection.set_meta("fabricated_id", id)
	podium.source_name = str(row.label) + " · Ready to pick up"
	podium.update_caption()
	if objects.has(id) and is_instance_valid(objects[id]):
		objects[id].queue_free()
	objects.erase(id)
	placements.erase(id)
	seen[id] = true
	presented_id = id
	save_layout()
	note = "Ready · point and grip / pinch to pick up; release to place"
	paint()
	return true

func next_output() -> bool:
	var ready: Array = jobs.filter(func(row: Dictionary) -> bool: return row.get("phase") == "ready")
	if ready.is_empty():
		note = "No completed objects yet"
		paint()
		return false
	output_index = posmod(output_index + 1, ready.size())
	return present_output(ready[output_index])

static func encode_transform(value: Transform3D) -> Array:
	var result: Array = []
	for vector in [value.basis.x, value.basis.y, value.basis.z, value.origin]:
		result.append_array([vector.x, vector.y, vector.z])
	return result

static func decode_transform(value: Variant) -> Transform3D:
	if not value is Array or value.size() != 12: return Transform3D.IDENTITY
	for number in value:
		if not (number is float or number is int) or not is_finite(float(number)): return Transform3D.IDENTITY
	return Transform3D(Basis(Vector3(value[0], value[1], value[2]), Vector3(value[3], value[4], value[5]), Vector3(value[6], value[7], value[8])), Vector3(value[9], value[10], value[11]))

func save_layout() -> void:
	if data.is_empty(): return
	var path := data.path_join("placements.json")
	var file := FileAccess.open(path + ".tmp", FileAccess.WRITE)
	if not file: return
	file.store_string(JSON.stringify({"seen": seen, "placements": placements, "presented": presented_id}))
	file.close()
	DirAccess.rename_absolute(path + ".tmp", path)

func refresh() -> void:
	if ipc.is_empty() or not FileAccess.file_exists(ipc.path_join("status.json")): return
	var state: Variant = JSON.parse_string(FileAccess.get_file_as_string(ipc.path_join("status.json")))
	if not state is Dictionary: return
	jobs = state.get("jobs", [])
	if not restored_session:
		restored_session = true
		for row: Dictionary in jobs:
			if str(row.get("id")) == presented_id and not placements.has(presented_id) and not is_instance_valid(podium.projection) and not is_instance_valid(podium.live_window):
				present_output(row)
	var active := false
	for row: Dictionary in jobs:
		if row.get("phase") in ["queued", "processing", "submitting", "uncertain"]:
			active = true
			note = str(row.get("connection_note", row.get("stage", "Rendering")))
		if row.get("phase") != "ready": continue
		var id := str(row.id)
		if placements.has(id) and not objects.has(id) and valid_output(row):
			var document := GLTFDocument.new()
			var gltf := GLTFState.new()
			if document.append_from_file(str(row.path), gltf) == OK:
				var model := document.generate_scene(gltf) as Node3D
				if model:
					var item := Node3D.new()
					add_child(item)
					item.add_child(model)
					var bounds := Podium.model_bounds(model)
					var fit := minf(1.05 / maxf(maxf(bounds.size.x, bounds.size.z), 0.001), 0.95 / maxf(bounds.size.y, 0.001))
					model.scale = Vector3.ONE * fit
					model.position = -bounds.get_center() * fit
					item.set_meta("fabricated_id", id)
					item.global_transform = decode_transform(placements[id])
					objects[id] = item
		elif not seen.has(id) and not held:
			# Don't steal an unrelated live window or another model presentation.
			if not is_instance_valid(podium.projection) and not is_instance_valid(podium.live_window) or podium._file_path == selected_image and not selected_image.is_empty():
				present_output(row)
			else:
				note = "Object ready · choose Ready objects when the podium is free"
	if Time.get_unix_time_from_system() - float(state.get("updated_at", 0)) > 12:
		note = "Pipeline disconnected · jobs and objects are saved"
	elif not active and jobs.is_empty(): note = str(state.get("message", note))
	elif not active and not jobs.is_empty() and jobs.back().get("phase") in ["failed", "busy", "cancelled"]:
		note = str(jobs.back().get("stage", "Render did not complete"))
	paint()

func pick(origin: Vector3, direction: Vector3) -> Node3D:
	if not origin.is_finite() or not direction.is_finite() or direction.length_squared() < 0.9: return null
	var candidates: Array = objects.values()
	if is_instance_valid(podium.projection) and podium.projection.has_meta("fabricated_id"): candidates.append(podium.projection)
	var closest := ray_limit
	var result: Node3D
	for item: Node3D in candidates:
		if not is_instance_valid(item): continue
		var bounds: AABB = item.global_transform * Podium.model_bounds(item)
		var hit: Variant = bounds.grow(0.035).intersects_ray(origin, direction.normalized())
		if hit is Vector3:
			var distance := origin.distance_to(hit)
			if distance < closest:
				closest = distance
				result = item
	return result

func begin_grab(pose: Transform3D, direction: Vector3) -> bool:
	if held or not pose.is_finite() or absf(pose.basis.determinant()) < 0.001: return false
	var item := pick(pose.origin, direction)
	if not item: return false
	if item == podium.projection:
		var saved := item.global_transform
		item = podium.take_model()
		add_child(item)
		item.global_transform = saved
		objects[str(item.get_meta("fabricated_id"))] = item
		presented_id = ""
	held = item
	last_picked = str(item.get_meta("fabricated_id"))
	grip_offset = pose.affine_inverse() * item.global_transform
	note = "Holding object · move / rotate your hand; release to place"
	paint()
	return true

func end_grab() -> void:
	if is_instance_valid(held):
		placements[str(held.get_meta("fabricated_id"))] = encode_transform(held.global_transform)
		save_layout()
	held = null
	note = "Object placed · grip it again to move it"
	paint()

func grab_input(pose: Transform3D, direction: Vector3, pressed: bool, valid := true) -> bool:
	var was_holding := is_instance_valid(held)
	if not valid or not pose.is_finite() or absf(pose.basis.determinant()) < 0.001:
		if was_holding: end_grab()
		grip_down = true # Tracking return must release before a fresh grab.
		return was_holding
	if pressed and not grip_down: begin_grab(pose, direction)
	grip_down = pressed
	if is_instance_valid(held):
		if pressed: held.global_transform = pose * grip_offset
		else: end_grab()
		return true
	return was_holding

func return_held() -> void:
	var id := str(held.get_meta("fabricated_id")) if held else last_picked
	if id.is_empty() and not objects.is_empty(): id = str(objects.keys().back())
	if held: end_grab()
	for row: Dictionary in jobs:
		if str(row.id) == id: present_output(row)

func _exit_tree() -> void:
	if held: end_grab()

func mouse_input(event: InputEvent, camera: Camera3D) -> bool:
	if not event is InputEventMouse: return false
	var origin := camera.project_ray_origin(event.position)
	var direction := camera.project_ray_normal(event.position)
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed:
			var item := pick(origin, direction)
			if not item: return false
			mouse_depth = origin.distance_to(item.global_position)
			mouse_held = begin_grab(Transform3D(camera.global_basis, origin + direction * mouse_depth), direction)
			# Begin from the original ray so the selected box remains selectable.
			if not mouse_held: mouse_held = begin_grab(Transform3D(camera.global_basis, origin), direction)
			if mouse_held: grip_offset = Transform3D(camera.global_basis, origin + direction * mouse_depth).affine_inverse() * held.global_transform
		elif mouse_held:
			end_grab()
			mouse_held = false
			return true
	if mouse_held and held:
		held.global_transform = Transform3D(camera.global_basis, origin + direction * mouse_depth) * grip_offset
	return mouse_held

func _process(delta: float) -> void:
	if restored_session and not presented_id.is_empty() and not is_instance_valid(podium.projection):
		presented_id = ""
		save_layout()
	elapsed += delta
	if elapsed >= 1.0:
		elapsed = 0
		refresh()

func _notification(what: int) -> void:
	if what == NOTIFICATION_APPLICATION_FOCUS_OUT and held:
		end_grab()
		mouse_held = false
		grip_down = true
