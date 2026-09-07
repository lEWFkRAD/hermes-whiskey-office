extends Node3D
## Optional modeling review; the ordinary room uses material batches. Loading
## one library preserves individual part transforms without taxing normal work.
signal selection_changed(spec: Dictionary)
signal review_closed

var catalogue: Dictionary = {}
var choices: Array[Dictionary] = []
var selected := -1
var exploded := false
var review_offset := Vector3.ZERO
var _room: Node3D
var _library: Node3D
var _loader: Callable
var _parts: Array[Node3D] = []
var _rest: Array[Transform3D] = []
var _hidden: Array[Node3D] = []
var _label: Label3D
var _centers: Dictionary = {}
var _roles: Dictionary = {}

static func matrix(values: Array) -> Transform3D:
	if values.size() != 16: return Transform3D.IDENTITY
	return Transform3D(Basis(Vector3(values[0], values[1], values[2]), Vector3(values[4], values[5], values[6]), Vector3(values[8], values[9], values[10])), Vector3(values[12], values[13], values[14]))

func setup(room: Node3D, loader: Callable) -> void:
	_room = room
	_loader = loader
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://office-assemblies.json"))
	if not parsed is Dictionary: return
	catalogue = parsed
	for part: Dictionary in catalogue.get("parts", []):
		var low: Array = part.bounds.min
		var high: Array = part.bounds.max
		_centers[str(part.id)] = Vector3((low[0]+high[0])*0.5, (low[1]+high[1])*0.5, (low[2]+high[2])*0.5)
		_roles[str(part.id)] = str(part.semantic_role)
	for spec: Dictionary in catalogue.get("assemblies", []):
		if spec.get("library_path") is String and not str(spec.library_path).is_empty():
			choices.append(spec)
	var priority := ["desk", "monitor", "keyboard", "computer", "bookcase-left", "bookcase-right"]
	choices.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		var first := priority.find(str(a.id))
		var second := priority.find(str(b.id))
		return (first if first >= 0 else 100) < (second if second >= 0 else 100)
	)
	_label = Label3D.new()
	_label.font_size = 24
	_label.pixel_size = 0.0013
	_label.modulate = Color("ecd6ab")
	_label.outline_size = 8
	_label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	add_child(_label)
	_label.hide()

func is_open() -> bool:
	return is_instance_valid(_library)

func select_next(direction := 1) -> bool:
	if choices.is_empty(): return false
	return open_index(posmod(selected + direction, choices.size()))

func open_index(index: int) -> bool:
	if index < 0 or index >= choices.size(): return false
	var spec := choices[index]
	var candidate: Node3D = _loader.call(str(spec.library_path))
	if candidate == null: return false
	close_review(false)
	selected = index
	_library = candidate
	add_child(_library)
	_library.transform = matrix(spec.world_transform)
	var bounds: Dictionary = spec.bounds
	var low: Array = bounds.min
	var high: Array = bounds.max
	var extent := Vector3(high[0]-low[0], high[1]-low[1], high[2]-low[2])
	# Lift small pieces clear of the desk while inspecting their undersides.
	# This is local presentation; the source and restored room never move.
	review_offset = Vector3(0, 0.35, 0) if extent.length() < 1.0 else Vector3.ZERO
	_library.position += review_offset
	_collect_parts(_library)
	if _parts.is_empty():
		close_review()
		return false
	var groups: Dictionary = {}
	var library_parts: Dictionary = spec.get("library_parts", {})
	for part: Dictionary in catalogue.get("parts", []):
		if library_parts.has(str(part.id)): groups[str(part.render_group)] = true
	if groups.is_empty(): groups[str(spec.render_group)] = true
	_hide_batches(_room, groups)
	_label.position = Vector3((low[0]+high[0])*0.5, high[1]+0.14, (low[2]+high[2])*0.5) + review_offset
	_label.pixel_size = clampf(extent.length() * 0.00035, 0.00065, 0.0010)
	_update_label()
	_label.show()
	selection_changed.emit(spec)
	return true

func _collect_parts(node: Node) -> void:
	var part_id := identity(node, "office_part_id")
	if node is Node3D and not part_id.is_empty():
		node.set_meta("office_part_id", part_id)
		_parts.append(node)
		_rest.append(node.transform)
	for child in node.get_children(): _collect_parts(child)

func _hide_batches(node: Node, groups: Dictionary) -> void:
	if node is MeshInstance3D and groups.has(identity(node, "render_group")) and node.visible:
		_hidden.append(node)
		node.hide()
	for child in node.get_children(): _hide_batches(child, groups)

static func identity(node: Node, key: String) -> String:
	# Godot 4.7 preserves glTF metadata under the `extras` dictionary. Runtime
	# nodes may also carry normalized metadata; source names are never guessed.
	if node.has_meta(key): return str(node.get_meta(key))
	var extras: Variant = node.get_meta("extras", {})
	return str(extras.get(key, "")) if extras is Dictionary else ""

func set_exploded(value: bool) -> void:
	if not is_open(): return
	# Restore exact stored transforms before calculating offsets; repeated
	# explode/reassemble cycles cannot accumulate floating point drift.
	for i in _parts.size(): _parts[i].transform = _rest[i]
	exploded = value
	if value:
		var spec := choices[selected]
		var low: Array = spec.bounds.min
		var high: Array = spec.bounds.max
		var center := Vector3((low[0]+high[0])*0.5, (low[1]+high[1])*0.5, (low[2]+high[2])*0.5)
		var spread := clampf(Vector3(high[0]-low[0], high[1]-low[1], high[2]-low[2]).length() * 0.14, 0.07, 0.42)
		for i in _parts.size():
			var node := _parts[i]
			var part_id := str(node.get_meta("office_part_id", ""))
			var part_center: Vector3 = _centers.get(part_id, node.global_position)
			var direction := (part_center-center).normalized()
			if direction.length_squared() < 0.01: direction = Vector3.UP
			var displacement := direction * spread
			if str(spec.id) == "keyboard":
				# A keyboard is layered. Keep legends with the keycap layer so a
				# radial explode cannot lift the switch plate over the keys.
				var role := str(_roles.get(part_id, ""))
				if role in ["keyboard_keycap", "keyboard_legend", "keyboard_tactile_marker"]:
					displacement = Vector3((part_center.x-center.x)*0.25, 0.12, (part_center.z-center.z)*0.25)
				elif role == "keyboard_switch_plate": displacement = Vector3.ZERO
				else: displacement = Vector3(0, -0.10, 0)
			node.global_position += displacement
	_update_label()

func _update_label() -> void:
	if selected < 0: return
	_label.text = "%s · %d parts\n%s" % [str(choices[selected].name), _parts.size(), "Separated for review" if exploded else "Assembled"]

func close_review(emit_signal := true) -> void:
	if is_instance_valid(_library):
		remove_child(_library)
		_library.queue_free()
	_library = null
	for node in _hidden:
		if is_instance_valid(node): node.show()
	_hidden.clear()
	_parts.clear()
	_rest.clear()
	exploded = false
	if is_instance_valid(_label): _label.hide()
	if emit_signal: review_closed.emit()

func input(event: InputEvent) -> bool:
	if not is_open() or not event is InputEventKey: return false
	var key: int = event.physical_keycode
	if key not in [KEY_F8, KEY_ESCAPE, KEY_LEFT, KEY_RIGHT, KEY_SPACE]: return false
	if event.pressed and not event.echo:
		match key:
			KEY_ESCAPE, KEY_F8: close_review()
			KEY_LEFT: select_next(-1)
			KEY_RIGHT: select_next(1)
			KEY_SPACE: set_exploded(not exploded)
	return true
