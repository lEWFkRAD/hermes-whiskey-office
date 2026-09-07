extends Node
## One input owner, many independent surfaces. Source commands stay in the launcher.
signal sources_changed(rows: Array)
signal focus_changed(source_id: String)
signal control_input(event: InputEvent)
const Surface = preload("res://desktop_surface.gd")
var surfaces: Dictionary = {}
var sources: Dictionary = {}
var native_windows: Dictionary = {}
var active_id := "hermes"
var last_closed := ""
var _head: Node3D
var _spatial := false
var _ipc := ""
var _instance := ""
var _serial := 0
var _elapsed := 1.0
var _pressed := false
var _capture_id := ""
var _hidden_for_capture: Array = []
var _capture_active := ""
var _source_picker: OptionButton
var _status: Label
var _toolbar: CanvasLayer
var menu_open: Callable
var menu_capturing: Callable
var _menu_hidden: Array = []
var _layout_path := ""
var _saved_windows: Dictionary = {}
var _restore_open_ids: Array = []
var _restore_focus := ""
var _last_layout := ""

func setup(primary: Node3D, head: Node3D, spatial: bool) -> void:
	_head = head
	_spatial = spatial
	if not spatial: get_viewport().gui_embed_subwindows = true
	_ipc = OS.get_environment("HERMES_WINDOWS_IPC_DIR")
	sources.hermes = {"id": "hermes", "title": "Hermes", "machine": "Forge", "kind": "hermes"}
	register("hermes", primary)
	var data := OS.get_environment("HERMES_OFFICE_DATA_DIR")
	if not data.is_empty() and DirAccess.dir_exists_absolute(data):
		_layout_path = data.path_join("window-layout.json")
		load_layout()
	if not spatial: build_toolbar()
	read_sources()
	refresh_toolbar()

func build_toolbar() -> void:
	_toolbar = CanvasLayer.new()
	_toolbar.layer = 20
	add_child(_toolbar)
	var bar := HBoxContainer.new()
	bar.position = Vector2(24, 118)
	_toolbar.add_child(bar)
	_source_picker = OptionButton.new()
	bar.add_child(_source_picker)
	var bay := Button.new()
	bay.text = "Loading Bay"
	bar.add_child(bay)
	bay.pressed.connect(func() -> void: open_window("loading-bay"))
	for action in ["Open", "Next", "Arrange", "Hide", "Reopen", "Disconnect"]:
		var button := Button.new()
		button.text = action
		bar.add_child(button)
		button.pressed.connect(func() -> void:
			match action:
				"Open": open_window(str(_source_picker.get_item_metadata(_source_picker.selected)))
				"Next": cycle(1)
				"Arrange": arrange()
				"Hide": close_window()
				"Reopen": reopen()
				"Disconnect": disconnect_window()
		)
	_status = Label.new()
	bar.add_child(_status)

func refresh_toolbar() -> void:
	if not _source_picker: return
	var selected := _source_picker.selected
	_source_picker.clear()
	for id in sources:
		_source_picker.add_item(str(sources[id].title) + " · " + str(sources[id].machine))
		_source_picker.set_item_metadata(_source_picker.item_count-1, id)
	_source_picker.select(clampi(selected, 0, _source_picker.item_count-1))

func register(id: String, surface: Node3D) -> void:
	surfaces[id] = surface
	surface.set_spatial_visible(_spatial)
	surface.panel_closed.connect(func() -> void:
		last_closed = id
		if native_windows.has(id): native_windows[id].hide()
		if active_id == id: cycle(1)
	)
	if not _spatial:
		var window := Window.new()
		window.title = str(sources[id].title) + " · " + str(sources[id].machine)
		window.size = Vector2i(960, 640)
		window.min_size = Vector2i(640, 440)
		window.position = Vector2i(110 + surfaces.size()*28, 145 + surfaces.size()*22)
		window.visible = false
		add_child(window)
		var stack := VBoxContainer.new()
		window.add_child(stack)
		stack.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		var caption := Label.new()
		caption.text = window.title + "  ·  Close hides this window; the connection remains open"
		caption.add_theme_font_size_override("font_size", 14)
		stack.add_child(caption)
		var preview: TextureRect = surface.create_preview()
		preview.custom_minimum_size = Vector2(300, 180)
		preview.size_flags_vertical = Control.SIZE_EXPAND_FILL
		preview.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		stack.add_child(preview)
		window.close_requested.connect(func() -> void: close_window(id))
		window.focus_entered.connect(func() -> void: focus_window(id))
		window.window_input.connect(func(event: InputEvent) -> void:
			if event is InputEventKey and (event.physical_keycode in [KEY_F9, KEY_F10] or (menu_capturing.is_valid() and menu_capturing.call())):
				control_input.emit(event)
				window.set_input_as_handled()
		)
		native_windows[id] = window

func active():
	return surfaces.get(active_id)

func any_open() -> bool:
	for surface in surfaces.values():
		if surface.is_open(): return true
	return false

func focus_window(id: String) -> void:
	if not surfaces.has(id) or not surfaces[id].is_open(): return
	if id != active_id:
		var previous = active()
		if previous:
			previous.end_move()
			previous.set_window_active(false)
		active_id = id
		focus_changed.emit(id)
	surfaces[id].set_window_active(true)

func open_window(id: String) -> bool:
	if not sources.has(id): return false
	if not surfaces.has(id):
		if surfaces.size() >= 8:
			if active(): active().show_action_feedback("Eight windows are open. Disconnect a remote client to free a slot.")
			return false
		var surface = Surface.new()
		surface.hermes_controls = false
		surface.window_title = str(sources[id].title) + " · " + str(sources[id].machine)
		add_child(surface)
		surface.setup(str(sources[id].ipc_dir), _head)
		surface.passthrough_requested.connect(func() -> void: surfaces.hermes.passthrough_requested.emit())
		register(id, surface)
	var surface = surfaces[id]
	var first: bool = not surface._has_placement
	if id != "hermes": request("open", id)
	surface.open_panel(false)
	if first and _saved_windows.has(id):
		var saved: Dictionary = _saved_windows[id]
		var values: Array = saved.pose
		var orientation := Basis(Vector3(values[0], values[1], values[2]), Vector3(values[3], values[4], values[5]), Vector3(values[6], values[7], values[8]))
		surface.set_panel_scale(float(saved.scale))
		surface.move_panel(Transform3D(orientation, Vector3(values[9], values[10], values[11])))
	elif first and surfaces.size() > 1:
		var offset := float(surfaces.size()-1)
		surface.global_position += _head.global_basis.x * (0.35 * offset)
	focus_window(id)
	if native_windows.has(id) and not surface.get_meta("podium_projected", false):
		native_windows[id].show()
		native_windows[id].grab_focus()
	return true

func close_window(id: String = "") -> void:
	if id.is_empty(): id = active_id
	if surfaces.has(id): surfaces[id].close_panel()

func disconnect_window(id: String = "") -> void:
	if id.is_empty(): id = active_id
	if id == "hermes":
		close_window(id)
		return
	close_window(id)
	request("disconnect", id)
	if native_windows.has(id):
		native_windows[id].queue_free()
		native_windows.erase(id)
	if surfaces.has(id):
		surfaces[id].queue_free()
		surfaces.erase(id)
	_saved_windows.erase(id)
	_restore_open_ids.erase(id)
	save_layout()

func reopen() -> bool:
	return open_window(last_closed) if not last_closed.is_empty() else open_window("hermes")

func cycle(direction: int) -> void:
	var ids: Array = []
	for id in surfaces:
		if surfaces[id].is_open(): ids.append(id)
	if ids.is_empty(): return
	var index: int = ids.find(active_id)
	var next := str(ids[posmod(index + direction, ids.size())])
	focus_window(next)
	if native_windows.has(next): native_windows[next].grab_focus()

func arrange() -> void:
	var ids: Array = []
	for id in surfaces:
		if surfaces[id].is_open(): ids.append(id)
	for index in ids.size():
		var surface = surfaces[ids[index]]
		var column := index % 4
		var row := index / 4
		var columns := mini(4, ids.size())
		var offset := float(column) - float(columns-1)*0.5
		var yaw := deg_to_rad(-offset * 30.0)
		var orientation := _head.global_basis.orthonormalized() * Basis(Vector3.UP, yaw)
		var height := (0.55 if ids.size() > 4 else 0.0) - float(row) * 1.1
		var center := _head.global_position - orientation.z * 1.7 + _head.global_basis.y * height
		surface.set_panel_scale(0.55)
		surface.move_panel(Transform3D(orientation, center))
		if native_windows.has(ids[index]):
			var available := get_viewport().get_visible_rect().size - Vector2(40, 155)
			var tile_columns := mini(2, ids.size())
			var tile_rows := ceili(float(ids.size()) / float(tile_columns))
			var tile := Vector2i(available / Vector2(tile_columns, tile_rows))
			native_windows[ids[index]].min_size = Vector2i(320, 220)
			native_windows[ids[index]].size = tile - Vector2i(12, 28)
			native_windows[ids[index]].position = Vector2i(20 + (index % tile_columns)*tile.x, 135 + (index / tile_columns)*tile.y)

func release_all() -> void:
	pointed_id = ""
	for surface in surfaces.values():
		surface.end_move()
		surface.release_input()
	_capture_id = ""
	_pressed = true # require the observed release before another XR selection

func hide_for_capture() -> void:
	_hidden_for_capture.clear()
	_capture_active = active_id
	if _toolbar: _toolbar.hide()
	for surface in surfaces.values():
		if surface.visible:
			_hidden_for_capture.append(surface)
			surface.hide()
	for window in native_windows.values():
		if window.visible:
			_hidden_for_capture.append(window)
			window.hide()

func restore_after_capture() -> void:
	for node in _hidden_for_capture:
		if is_instance_valid(node): node.show()
	_hidden_for_capture.clear()
	if _toolbar: _toolbar.show()
	focus_window(_capture_active)

var pointed_id := ""

func target_at(origin: Vector3, direction: Vector3) -> String:
	var nearest := INF
	var hit := ""
	for id in surfaces:
		var distance: float = surfaces[id].ray_distance(origin, direction)
		if distance < nearest:
			nearest = distance
			hit = id
	return hit

func begin_targeted_move(origin: Vector3, direction: Vector3, pose: Transform3D) -> bool:
	var hit := target_at(origin, direction)
	if hit.is_empty(): return false
	release_all()
	focus_window(hit)
	return surfaces[hit].begin_move(pose)

func point(origin: Vector3, direction: Vector3, pressed: bool) -> void:
	var hit := target_at(origin, direction)
	pointed_id = hit
	if pressed and not _pressed:
		_capture_id = hit
		if not hit.is_empty(): focus_window(hit)
	var owner := _capture_id if pressed or _pressed else hit
	for id in surfaces:
		if id == owner:
			surfaces[id].point(origin, direction, pressed)
		elif not pressed:
			surfaces[id].point(origin, Vector3.ZERO, false)
	if not pressed: _capture_id = ""
	_pressed = pressed

func request(kind: String, id: String) -> void:
	if _ipc.is_empty() or _instance.is_empty(): return
	_serial += 1
	var request_id := "window-%d-%d" % [Time.get_ticks_usec(), _serial]
	var value := {"protocol_version": 1, "instance_id": _instance, "id": request_id, "created_at_unix": Time.get_unix_time_from_system(), "type": kind, "source_id": id}
	var target := _ipc.path_join("commands").path_join(request_id + ".json")
	var file := FileAccess.open(target + ".tmp", FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(value))
		file.close()
		DirAccess.rename_absolute(target + ".tmp", target)

func read_sources() -> void:
	var path := _ipc.path_join("windows.json")
	if _ipc.is_empty() or not FileAccess.file_exists(path): return
	var file := FileAccess.open(path, FileAccess.READ)
	if not file or file.get_length() > 131072: return
	var value: Variant = JSON.parse_string(file.get_as_text())
	if not value is Dictionary or value.get("protocol_version") != 1 or not value.get("sources") is Array: return
	var stamp := float(value.get("updated_at_unix", 0))
	if not is_finite(stamp) or absf(Time.get_unix_time_from_system()-stamp) > 5: return
	_instance = str(value.get("instance_id", ""))
	var changed := false
	for row: Variant in value.sources:
		if not row is Dictionary or not row.get("id") is String: continue
		var id := str(row.id)
		if id == "hermes": continue
		# Hermes + 31 configured sources + the built-in loading bay.
		if not sources.has(id) and sources.size() >= 33: continue
		if not row.get("ipc_dir") is String or not row.get("title") is String or not row.get("machine") is String: continue
		if str(row.ipc_dir).simplify_path() != _ipc.path_join(id).simplify_path() or id.contains("/") or id.contains("..") or id.contains("\\"): continue
		if not sources.has(id): changed = true
		sources[id] = row
	if _status:
		var row: Dictionary = sources.get(active_id, {})
		_status.text = str(row.get("error", ""))
	if changed:
		refresh_toolbar()
		sources_changed.emit(sources.values())

func _process(delta: float) -> void:
	if menu_open.is_valid():
		if menu_open.call():
			for id in native_windows:
				if native_windows[id].visible:
					_menu_hidden.append(id)
					native_windows[id].hide()
		elif not _menu_hidden.is_empty():
			var target := active_id
			for id in _menu_hidden:
				if native_windows.has(id) and surfaces[id].is_open() and not surfaces[id].get_meta("podium_projected", false): native_windows[id].show()
			_menu_hidden.clear()
			focus_window(target)
			if native_windows.has(target) and surfaces[target].is_open() and not surfaces[target].get_meta("podium_projected", false): native_windows[target].grab_focus()
	_elapsed += delta
	if _elapsed >= 0.5:
		_elapsed = 0
		read_sources()
		restore_windows()
		save_layout()

func load_layout() -> void:
	if _layout_path.is_empty() or not FileAccess.file_exists(_layout_path): return
	var file := FileAccess.open(_layout_path, FileAccess.READ)
	if not file or file.get_length() > 65536: return
	var data: Variant = JSON.parse_string(file.get_as_text())
	if not data is Dictionary or data.get("schema") != 1 or not data.get("windows") is Array or data.windows.size() > 32: return
	_saved_windows.clear()
	_restore_open_ids.clear()
	for row: Variant in data.windows:
		if not row is Dictionary or not row.get("id") is String or not row.get("open") is bool or not row.get("pose") is Array or row.pose.size() != 12: continue
		if row.id.is_empty() or row.id.length() > 48: continue
		var valid := true
		for value: Variant in row.pose:
			if not (value is float or value is int) or not is_finite(float(value)) or absf(float(value)) > 100: valid = false
		if not (row.get("scale") is float or row.get("scale") is int) or not is_finite(float(row.scale)): continue
		if not valid: continue
		var p: Array = row.pose
		var basis := Basis(Vector3(p[0], p[1], p[2]), Vector3(p[3], p[4], p[5]), Vector3(p[6], p[7], p[8]))
		if basis.determinant() < 0.00001: continue
		_saved_windows[row.id] = {"id": row.id, "open": row.open, "pose": row.pose, "scale": clampf(float(row.scale), 0.6, 1.8)}
		if row.open: _restore_open_ids.append(row.id)
	_restore_focus = str(data.get("active", "hermes"))

func restore_windows() -> void:
	if _instance.is_empty() or _restore_open_ids.is_empty(): return
	# Source commands come only from current local configuration, never this file.
	for id: String in _restore_open_ids.duplicate():
		if sources.has(id) and (surfaces.has(id) or surfaces.size() < 8):
			open_window(id)
			_restore_open_ids.erase(id)
	if _restore_open_ids.is_empty(): focus_window(_restore_focus)

func save_layout() -> void:
	if _layout_path.is_empty() or _instance.is_empty(): return
	for id: String in surfaces:
		if id in _restore_open_ids: continue
		var surface = surfaces[id]
		if not surface._has_placement or surface.get_meta("podium_projected", false): continue
		var pose: Transform3D = surface.global_transform
		var b := pose.basis.orthonormalized()
		_saved_windows[id] = {"id": id, "open": surface.is_open(), "scale": surface.get_panel_scale(), "pose": [b.x.x,b.x.y,b.x.z,b.y.x,b.y.y,b.y.z,b.z.x,b.z.y,b.z.z,pose.origin.x,pose.origin.y,pose.origin.z]}
	var encoded := JSON.stringify({"schema": 1, "active": active_id, "windows": _saved_windows.values()})
	if encoded == _last_layout: return
	var file := FileAccess.open(_layout_path + ".tmp", FileAccess.WRITE)
	if not file: return
	file.store_string(encoded)
	file.close()
	if DirAccess.rename_absolute(_layout_path + ".tmp", _layout_path) == OK: _last_layout = encoded
