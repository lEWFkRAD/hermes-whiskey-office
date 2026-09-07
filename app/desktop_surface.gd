extends Node3D
signal panel_closed
## Displays the existing Hermes desktop. This shell never constructs chat UI.
## The capture process owns the private IPC directory and atomically publishes
## status.json/frame.png. Commands are atomically queued, bound to its instance.
## Caller owns keyboard/locomotion focus and supplies tracked rays every frame.

signal connection_changed(connected: bool, reason: String)
signal frame_updated
signal command_failed(reason: String)
signal command_message(message: String)
signal state_changed(state: Dictionary)
signal share_view_requested
signal passthrough_requested

const RayMapping = preload("res://xr_workbench.gd")
const PROTOCOL_VERSION := 1
const PANEL_WIDTH := 1.6
const PANEL_DISTANCE := 1.35
const MIN_SCALE := 0.6
const MAX_SCALE := 1.8
const STALE_SECONDS := 4.0
const MISS := Vector2(-1.0, -1.0)
const POLL_SECONDS := 1.0 / 60.0

var texture: ImageTexture
var preview_control: TextureRect
var status: Dictionary = {}
var state: Dictionary = {}
var connected := false
var _mirror_enabled := false
var reason := "Waiting for Hermes desktop"
var frame_size := Vector2i(1280, 800)
var panel_size := Vector2(1.6, 1.0)
var _ipc := ""
var _head: Node3D
var _spatial_visuals: Node3D
var _spatial_visible := true
var _panel: MeshInstance3D
var _material: StandardMaterial3D
var _cursor: MeshInstance3D
var _status_label: Label3D
var _built := false
var _opened := false
var _instance_id := ""
var _last_frame_id := -1
var _frame_instance := ""
var _poll_elapsed := POLL_SECONDS
var _serial := 0
var _last_position := Vector2.ZERO
var _last_motion_tick := -100000
var _button_down := false
var _pressed_buttons: Dictionary = {}
var _held_keys: Dictionary = {}
var _trigger_was_pressed := false
var _must_release := true
var _moving := false
var _move_offset := Transform3D.IDENTITY
var _panel_scale := 1.0
var _last_command_id := ""
var _last_result_id := ""
var _feedback_label: Label3D
var _feedback_until := 0
var _shell_viewport: SubViewport
var _shell_quad: MeshInstance3D
var _shell: VBoxContainer
var _keyboard: VBoxContainer
var _keyboard_visible := false
var _shell_button_down := false
var _shell_last_position := Vector2(-32, -32)
var _shift := false
var _letter_buttons: Array[Button] = []
var hermes_controls := true
var window_title := "Hermes · Forge"
var _identity_label: Label3D
var _has_placement := false

func setup(ipc: String, head: Node3D) -> void:
	_ipc = ipc if not ipc.is_empty() else OS.get_environment("HERMES_DESKTOP_IPC_DIR")
	_head = head
	if _built:
		return
	_built = true
	name = "HermesDesktopSurface"
	_spatial_visuals = Node3D.new()
	_spatial_visuals.name = "SpatialVisuals"
	add_child(_spatial_visuals)
	_panel = MeshInstance3D.new()
	_panel.name = "ExistingHermesDesktop"
	var quad := QuadMesh.new()
	quad.size = panel_size
	_panel.mesh = quad
	_panel.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	_material = StandardMaterial3D.new()
	_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	# Preserve source alpha when the capture process supplies an RGBA frame.
	# Converting an opaque screen capture to RGBA cannot recover window alpha.
	_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	_material.albedo_color = Color("161419")
	_material.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR
	_panel.material_override = _material
	_spatial_visuals.add_child(_panel)
	_status_label = Label3D.new()
	_status_label.name = "DesktopConnectionStatus"
	_status_label.position.z = 0.008
	_status_label.font_size = 30
	_status_label.pixel_size = 0.0015
	_status_label.modulate = Color("ecd6ab")
	_status_label.text = reason
	_spatial_visuals.add_child(_status_label)
	_feedback_label = Label3D.new()
	_feedback_label.name = "HermesActionFeedback"
	_feedback_label.position = Vector3(0, panel_size.y * 0.5 + 0.075, 0.01)
	_feedback_label.font_size = 25
	_feedback_label.pixel_size = 0.0012
	_feedback_label.width = 1150
	_feedback_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_feedback_label.modulate = Color("ecd6ab")
	_feedback_label.hide()
	_spatial_visuals.add_child(_feedback_label)
	command_failed.connect(show_action_feedback)
	command_message.connect(show_action_feedback)
	_cursor = MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = 0.004
	sphere.height = 0.008
	sphere.radial_segments = 12
	sphere.rings = 6
	_cursor.mesh = sphere
	_cursor.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var cursor_material := StandardMaterial3D.new()
	cursor_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	cursor_material.albedo_color = Color("f3cc83")
	_cursor.material_override = cursor_material
	_spatial_visuals.add_child(_cursor)
	_cursor.hide()
	_build_shell()
	_identity_label = Label3D.new()
	_identity_label.text = window_title
	_identity_label.position = Vector3(0, panel_size.y * 0.5 + 0.055, 0)
	_identity_label.font_size = 28
	_identity_label.pixel_size = 0.0015
	_identity_label.outline_size = 8
	_spatial_visuals.add_child(_identity_label)
	set_spatial_visible(_spatial_visible)
	hide()

## Hide only the room-space meshes. The logical open state, preview, texture
## polling, focus, and queued input are unchanged. Use false for 2D preview.
func set_spatial_visible(value: bool) -> void:
	_spatial_visible = value
	if is_instance_valid(_spatial_visuals):
		_spatial_visuals.visible = value
	if is_instance_valid(_shell_viewport):
		_shell_viewport.render_target_update_mode = SubViewport.UPDATE_WHEN_VISIBLE if value else SubViewport.UPDATE_DISABLED

func get_spatial_visible() -> bool:
	return _spatial_visible

func set_mirror_enabled(value: bool) -> void:
	# A passive room monitor requests frames only. It never opens the panel,
	# acquires keyboard focus, or enables pointer/keyboard forwarding.
	_mirror_enabled = value
	if value: _poll_elapsed = POLL_SECONDS

func frame_demand() -> bool:
	return _mirror_enabled or is_open() or (is_instance_valid(preview_control) and preview_control.is_visible_in_tree())

func _build_shell() -> void:
	_shell_viewport = SubViewport.new()
	_shell_viewport.size = Vector2i(1280, 360)
	_shell_viewport.disable_3d = true
	_shell_viewport.transparent_bg = false
	_shell_viewport.handle_input_locally = true
	_shell_viewport.render_target_update_mode = SubViewport.UPDATE_WHEN_VISIBLE
	add_child(_shell_viewport)
	var background := ColorRect.new()
	background.color = Color("221e1b")
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_shell_viewport.add_child(background)
	_shell = VBoxContainer.new()
	_shell.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_shell.add_theme_constant_override("separation", 8)
	_shell_viewport.add_child(_shell)
	var toolbar := HBoxContainer.new()
	toolbar.add_theme_constant_override("separation", 8)
	_shell.add_child(toolbar)
	var toggle := _shell_button("Keyboard")
	toggle.pressed.connect(func() -> void: set_keyboard_visible(not _keyboard_visible))
	toolbar.add_child(toggle)
	var desktop_button := _shell_button("Desktop")
	desktop_button.pressed.connect(func() -> void: send_command("focus_desktop", {}))
	toolbar.add_child(desktop_button)
	var hud_button := _shell_button("HUD")
	hud_button.pressed.connect(toggle_hud)
	toolbar.add_child(hud_button)
	var tui_button := _shell_button("TUI")
	tui_button.pressed.connect(func() -> void: send_command("launch_tui", {}))
	toolbar.add_child(tui_button)
	hud_button.visible = hermes_controls
	tui_button.visible = hermes_controls
	var share := _shell_button("Share view")
	share.pressed.connect(func() -> void: share_view_requested.emit())
	toolbar.add_child(share)
	share.visible = hermes_controls
	var passthrough := _shell_button("Passthrough")
	passthrough.pressed.connect(func() -> void: passthrough_requested.emit())
	toolbar.add_child(passthrough)
	var hide_button := _shell_button("Close")
	hide_button.pressed.connect(close_panel)
	toolbar.add_child(hide_button)
	_keyboard = VBoxContainer.new()
	_keyboard.add_theme_constant_override("separation", 6)
	_shell.add_child(_keyboard)
	for row_text: String in ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,./"]:
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 6)
		_keyboard.add_child(row)
		for character_index: int in range(row_text.length()):
			var character := row_text.substr(character_index, 1)
			var key := _shell_button(character)
			key.set_meta("character", character)
			key.pressed.connect(func() -> void: send_text(key.text))
			row.add_child(key)
			_letter_buttons.append(key)
	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 6)
	_keyboard.add_child(actions)
	var shift := _shell_button("Shift")
	shift.toggle_mode = true
	shift.toggled.connect(_set_shift)
	actions.add_child(shift)
	var space := _shell_button("Space")
	space.pressed.connect(func() -> void: send_text(" "))
	actions.add_child(space)
	for key_spec: Array in [["Backspace", "BackSpace"], ["Enter", "Return"], ["Tab", "Tab"], ["Esc", "Escape"]]:
		var key := _shell_button(str(key_spec[0]))
		var keysym := str(key_spec[1])
		key.pressed.connect(func() -> void: tap_key(keysym))
		actions.add_child(key)
	_shell_quad = MeshInstance3D.new()
	_shell_quad.mesh = QuadMesh.new()
	_shell_quad.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_texture = _shell_viewport.get_texture()
	material.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR
	_shell_quad.material_override = material
	_spatial_visuals.add_child(_shell_quad)
	set_keyboard_visible(false)

func _shell_button(title: String) -> Button:
	var button := Button.new()
	button.text = title
	button.custom_minimum_size = Vector2(60, 52)
	button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	button.add_theme_font_size_override("font_size", 27)
	button.focus_mode = Control.FOCUS_NONE
	return button

func toggle_hud() -> void:
	for key in ["Control_L", "Shift_L", "h"]:
		send_command("key", {"keysym": key, "pressed": true})
	for key in ["h", "Shift_L", "Control_L"]:
		send_command("key", {"keysym": key, "pressed": false})

func _set_shift(value: bool) -> void:
	_shift = value
	var lower := "1234567890',./"
	var upper := "!@#$%^&*()\";:?"
	for button: Button in _letter_buttons:
		var character := str(button.get_meta("character"))
		var special := lower.find(character)
		button.text = upper.substr(special, 1) if value and special >= 0 else (character.to_upper() if value else character)

func set_keyboard_visible(value: bool) -> void:
	_keyboard_visible = value
	if not is_instance_valid(_shell_quad):
		return
	_keyboard.visible = value
	_shell_viewport.size = Vector2i(1280, 360 if value else 60)
	var height := PANEL_WIDTH * float(_shell_viewport.size.y) / 1280.0
	(_shell_quad.mesh as QuadMesh).size = Vector2(PANEL_WIDTH, height)
	_shell_quad.position = Vector3(0, -panel_size.y * 0.5 - height * 0.5 - 0.015, 0)

## Caller adds this actual-image preview to a desktop Control container.
## KEEP_ASPECT_CENTERED mapping excludes letterbox bars from input.
func create_preview() -> TextureRect:
	if is_instance_valid(preview_control):
		return preview_control
	preview_control = TextureRect.new()
	preview_control.name = "HermesDesktopPreview"
	preview_control.texture = texture
	preview_control.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	preview_control.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	preview_control.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	preview_control.size_flags_vertical = Control.SIZE_EXPAND_FILL
	preview_control.custom_minimum_size = Vector2(640, 400)
	preview_control.focus_mode = Control.FOCUS_ALL
	preview_control.mouse_filter = Control.MOUSE_FILTER_STOP
	preview_control.gui_input.connect(_on_preview_input)
	preview_control.mouse_exited.connect(release_input)
	preview_control.focus_exited.connect(release_input)
	preview_control.visibility_changed.connect(func() -> void:
		if not preview_control.is_visible_in_tree():
			release_input()
	)
	return preview_control

func open_panel(recenter := true) -> void:
	if not _built:
		return
	if (recenter or not _has_placement) and is_instance_valid(_head) and _head.is_inside_tree():
		var orientation := _head.global_basis.orthonormalized()
		global_transform = Transform3D(orientation.scaled(Vector3.ONE * _panel_scale), _head.global_position - orientation.z * PANEL_DISTANCE)
	_has_placement = true
	_opened = true
	_must_release = true
	_trigger_was_pressed = false
	show()
	_poll_elapsed = POLL_SECONDS

func close_panel() -> void:
	release_input()
	_opened = false
	_moving = false
	_must_release = true
	_trigger_was_pressed = false
	hide()
	panel_closed.emit()

func set_window_active(active: bool) -> void:
	if _identity_label:
		_identity_label.modulate = Color("ffe2a6") if active else Color("a8d8e1")
	if not active: release_input()

func ray_distance(origin: Vector3, direction: Vector3) -> float:
	if not is_open() or not origin.is_finite() or not direction.is_finite() or direction.length_squared() < 0.000001: return INF
	var nearest := INF
	for node in [_panel, _shell_quad]:
		if not is_instance_valid(node): continue
		var size_meters: Vector2 = node.mesh.size
		if ray_to_uv(node.global_transform, origin, direction, size_meters) == MISS: continue
		var normal: Vector3 = node.global_basis.z.normalized()
		var denom: float = normal.dot(direction.normalized())
		if absf(denom) > 0.000001:
			var distance: float = normal.dot(node.global_position-origin) / denom
			if distance >= 0: nearest = minf(nearest, distance)
	return nearest

func open() -> void:
	open_panel()

func close() -> void:
	close_panel()

func is_open() -> bool:
	return _opened and is_visible_in_tree()

static func status_error(value: Dictionary, now: float) -> String:
	if value.is_empty():
		return "Waiting for Hermes desktop"
	if int(value.get("protocol_version", 0)) != PROTOCOL_VERSION:
		return "Desktop connection version is unsupported"
	if str(value.get("instance_id", "")).is_empty():
		return "Desktop connection has no active instance"
	var timestamp := float(value.get("updated_at_unix", 0.0))
	if not is_finite(timestamp) or timestamp <= 0.0 or now - timestamp > STALE_SECONDS or timestamp - now > 60.0:
		return "Hermes desktop connection is stale"
	if not bool(value.get("connected", false)):
		return str(value.get("error", "")) if not str(value.get("error", "")).is_empty() else "Hermes desktop is disconnected"
	var width := int(value.get("width", 0))
	var height := int(value.get("height", 0))
	if width < 1 or height < 1 or width > 8192 or height > 8192:
		return "Desktop frame size is invalid"
	return ""

func _process(delta: float) -> void:
	if is_instance_valid(_feedback_label) and Time.get_ticks_msec() >= _feedback_until:
		_feedback_label.hide()
	_poll_elapsed += delta
	if _poll_elapsed < POLL_SECONDS:
		return
	_poll_elapsed = 0.0
	poll_frame()

func poll_frame() -> void:
	var next: Dictionary = {}
	if not _ipc.is_empty() and FileAccess.file_exists(_ipc.path_join("status.json")):
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(_ipc.path_join("status.json")))
		if parsed is Dictionary:
			next = parsed
	status = next
	var problem := status_error(status, Time.get_unix_time_from_system())
	if not problem.is_empty():
		_set_connection(false, problem)
		return
	var result: Variant = status.get("last_command", {})
	if result is Dictionary and not str(result.get("id", "")).is_empty() and str(result.get("id", "")) != _last_result_id:
		_last_result_id = str(result["id"])
		if result.get("status") == "error": command_failed.emit(str(result.get("error", "Hermes action unavailable")))
		elif result.get("status") == "done" and not str(result.get("message", "")).is_empty(): command_message.emit(str(result["message"]))
	var next_instance := str(status.get("instance_id", ""))
	if next_instance != _instance_id:
		release_input()
		_instance_id = next_instance
		_last_frame_id = -1
		_frame_instance = ""
		_must_release = true
	var frame_id := int(status.get("frame_id", -1))
	if frame_id < 0:
		_set_connection(false, "Waiting for a desktop frame")
		return
	var display_visible := frame_demand()
	if not display_visible and texture != null:
		_set_connection(_frame_instance == _instance_id, "" if _frame_instance == _instance_id else "Waiting for a desktop frame")
		return
	if frame_id != _last_frame_id:
		var image := Image.new()
		var frame_path := _ipc.path_join("frame.png")
		if not FileAccess.file_exists(frame_path) or image.load(frame_path) != OK or image.is_empty():
			_set_connection(false, "Desktop frame is unavailable")
			return
		if image.get_width() != int(status.get("width", 0)) or image.get_height() != int(status.get("height", 0)):
			_set_connection(false, "Waiting for the resized desktop frame")
			return
		image.convert(Image.FORMAT_RGBA8)
		if texture == null:
			texture = ImageTexture.create_from_image(image)
		elif texture.get_width() == image.get_width() and texture.get_height() == image.get_height():
			texture.update(image)
		else:
			texture.set_image(image)
		frame_size = image.get_size()
		panel_size = Vector2(PANEL_WIDTH, PANEL_WIDTH * float(frame_size.y) / float(frame_size.x))
		set_keyboard_visible(_keyboard_visible)
		if is_instance_valid(_panel):
			(_panel.mesh as QuadMesh).size = panel_size
			_material.albedo_texture = texture
			_material.albedo_color = Color.WHITE
		if is_instance_valid(preview_control):
			preview_control.texture = texture
		_last_frame_id = frame_id
		_frame_instance = _instance_id
		frame_updated.emit()
	_set_connection(_frame_instance == _instance_id, "" if _frame_instance == _instance_id else "Waiting for a desktop frame")

func show_action_feedback(message: String) -> void:
	if not is_instance_valid(_feedback_label): return
	_feedback_label.text = message.left(500)
	_feedback_until = Time.get_ticks_msec() + 10000
	_feedback_label.visible = not message.is_empty()

func _set_connection(value: bool, message: String) -> void:
	if not hermes_controls:
		message = message.replace("existing Hermes desktop", "remote client").replace("Hermes desktop", "Remote client")
	if connected and not value:
		release_input()
	var changed := connected != value or reason != message
	connected = value
	reason = message
	if is_instance_valid(_status_label):
		_status_label.text = message
		_status_label.visible = not value
	if is_instance_valid(preview_control):
		preview_control.tooltip_text = message
		preview_control.modulate = Color.WHITE if value else Color(0.45, 0.45, 0.45)
	if changed:
		connection_changed.emit(value, message)
	state = status.duplicate(true)
	state["connected"] = value
	state["error"] = message
	state_changed.emit(state)

static func ray_to_uv(panel_transform: Transform3D, ray_origin: Vector3, ray_direction: Vector3, size_meters := Vector2(1.6, 1.0)) -> Vector2:
	return RayMapping.ray_to_uv(panel_transform, ray_origin, ray_direction, size_meters)

## Caller must call on misses/tracking loss as well as successful rays.
func point(ray_origin: Vector3, ray_direction: Vector3, pressed: bool) -> bool:
	var new_press := pressed and not _trigger_was_pressed
	_trigger_was_pressed = pressed
	if not pressed:
		_must_release = false
	if not is_open() or _moving:
		_release_pointer()
		_release_shell_pointer()
		return false
	if not connected:
		_release_pointer()
		return _point_shell(ray_origin, ray_direction, pressed, new_press)
	var uv := ray_to_uv(global_transform, ray_origin, ray_direction, panel_size)
	if uv == MISS:
		_release_pointer()
		return _point_shell(ray_origin, ray_direction, pressed, new_press)
	_release_shell_pointer()
	var pixel := (uv * Vector2(frame_size)).clamp(Vector2.ZERO, Vector2(frame_size) - Vector2.ONE).floor()
	if is_instance_valid(_cursor):
		_cursor.position = Vector3((uv.x - 0.5) * panel_size.x, (0.5 - uv.y) * panel_size.y, 0.006)
		_cursor.show()
	_send_motion(pixel)
	if _button_down and not pressed:
		_send_button(pixel, 1, false)
	elif new_press and not _must_release:
		_send_button(pixel, 1, true)
	return true

func _point_shell(ray_origin: Vector3, ray_direction: Vector3, pressed: bool, new_press: bool) -> bool:
	if not is_instance_valid(_shell_quad):
		return false
	var size_meters := (_shell_quad.mesh as QuadMesh).size
	var uv := ray_to_uv(_shell_quad.global_transform, ray_origin, ray_direction, size_meters)
	if uv == MISS:
		_release_shell_pointer()
		return false
	var pixel := (uv * Vector2(_shell_viewport.size)).clamp(Vector2.ZERO, Vector2(_shell_viewport.size) - Vector2.ONE)
	var motion := InputEventMouseMotion.new()
	motion.position = pixel
	motion.global_position = pixel
	motion.relative = pixel - _shell_last_position
	motion.button_mask = MOUSE_BUTTON_MASK_LEFT if _shell_button_down else 0
	_shell_viewport.notify_mouse_entered()
	_shell_viewport.push_input(motion, true)
	_shell_last_position = pixel
	if (_shell_button_down and not pressed) or (new_press and not _must_release):
		var button := InputEventMouseButton.new()
		button.position = pixel
		button.global_position = pixel
		button.button_index = MOUSE_BUTTON_LEFT
		button.pressed = pressed
		button.button_mask = MOUSE_BUTTON_MASK_LEFT if pressed else 0
		_shell_button_down = pressed
		_shell_viewport.push_input(button, true)
	if is_instance_valid(_cursor):
		_cursor.position = _shell_quad.position + Vector3((uv.x - 0.5) * size_meters.x, (0.5 - uv.y) * size_meters.y, 0.006)
		_cursor.show()
	return true

func _release_shell_pointer() -> void:
	if is_instance_valid(_shell_viewport) and _shell_button_down:
		var button := InputEventMouseButton.new()
		button.position = Vector2(-32, -32)
		button.global_position = button.position
		button.button_index = MOUSE_BUTTON_LEFT
		button.pressed = false
		_shell_viewport.push_input(button, true)
		_shell_viewport.notify_mouse_exited()
	_shell_button_down = false

func _send_motion(pixel: Vector2, force := false) -> void:
	var tick := Time.get_ticks_msec()
	if not force and (pixel == _last_position or tick - _last_motion_tick < 40):
		return
	_last_position = pixel
	_last_motion_tick = tick
	_emit_command({"type": "pointer_move", "x": int(pixel.x), "y": int(pixel.y)})

func _send_button(pixel: Vector2, button: int, pressed: bool) -> void:
	_send_motion(pixel, true)
	if _emit_command({"type": "pointer_button", "x": int(pixel.x), "y": int(pixel.y), "button": button, "pressed": pressed}):
		if pressed:
			_pressed_buttons[button] = true
		else:
			_pressed_buttons.erase(button)
	_button_down = _pressed_buttons.has(1)

func _release_pointer() -> void:
	if not _pressed_buttons.is_empty():
		# The capture process moves into its reserved gutter before releasing.
		# An ordinary mouse-up at the old pixel could activate Send or Allow
		# when tracking disappears. Only a valid in-panel release completes it.
		_emit_command({"type": "pointer_cancel"})
		_last_position = MISS
		_last_motion_tick = -100000
	_pressed_buttons.clear()
	_button_down = false
	if is_instance_valid(_cursor):
		_cursor.hide()

func release_input() -> void:
	_release_pointer()
	_release_shell_pointer()
	for keysym: Variant in _held_keys.keys():
		_emit_command({"type": "key", "keysym": str(keysym), "pressed": false})
	_held_keys.clear()
	_must_release = true

func scroll(steps: float) -> void:
	if connected and is_finite(steps) and steps != 0.0:
		_emit_command({"type": "pointer_wheel", "x": int(_last_position.x), "y": int(_last_position.y), "delta_y": clampf(steps, -10.0, 10.0)})

func send_text(text: String) -> bool:
	return not text.is_empty() and text.length() <= 16384 and _emit_command({"type": "text", "text": text})

## Shell keyboards call tap_key; physical keyboard forwarding uses key_event.
func tap_key(keysym: String) -> void:
	if _emit_command({"type": "key", "keysym": keysym, "pressed": true}):
		_emit_command({"type": "key", "keysym": keysym, "pressed": false})

static func event_keysym(event: InputEventKey) -> String:
	var special := {
		KEY_ESCAPE: "Escape", KEY_TAB: "Tab", KEY_BACKTAB: "ISO_Left_Tab",
		KEY_BACKSPACE: "BackSpace", KEY_ENTER: "Return", KEY_KP_ENTER: "KP_Enter",
		KEY_INSERT: "Insert", KEY_DELETE: "Delete", KEY_HOME: "Home", KEY_END: "End",
		KEY_LEFT: "Left", KEY_RIGHT: "Right", KEY_UP: "Up", KEY_DOWN: "Down",
		KEY_PAGEUP: "Prior", KEY_PAGEDOWN: "Next", KEY_SHIFT: "Shift_L",
		KEY_CTRL: "Control_L", KEY_ALT: "Alt_L", KEY_META: "Super_L",
		KEY_CAPSLOCK: "Caps_Lock", KEY_SPACE: "space"
	}
	if special.has(event.keycode):
		return str(special[event.keycode])
	if event.keycode >= KEY_F1 and event.keycode <= KEY_F12:
		return "F%d" % (int(event.keycode) - KEY_F1 + 1)
	# X keysyms accept Uxxxx for Unicode. Use the unshifted logical key so
	# separately forwarded Shift/Ctrl retain their ordinary desktop behavior.
	if event.keycode >= 32 and event.keycode <= 126:
		var character := String.chr(event.keycode).to_lower()
		return character if character.is_valid_identifier() or character.is_valid_int() else "U%04X" % character.unicode_at(0)
	return "U%04X" % event.unicode if event.unicode >= 32 else ""

func key_event(event: InputEventKey) -> bool:
	var keysym := event_keysym(event)
	if keysym.is_empty() or not connected:
		return false
	if _emit_command({"type": "key", "keysym": keysym, "pressed": event.pressed}):
		if event.pressed:
			_held_keys[keysym] = true
		else:
			_held_keys.erase(keysym)
		return true
	return false

static func preview_to_pixel(position_2d: Vector2, control_size: Vector2, image_size: Vector2i) -> Vector2:
	if control_size.x <= 0.0 or control_size.y <= 0.0 or image_size.x < 1 or image_size.y < 1:
		return MISS
	var factor := minf(control_size.x / float(image_size.x), control_size.y / float(image_size.y))
	var displayed := Vector2(image_size) * factor
	var offset := (control_size - displayed) * 0.5
	var uv := (position_2d - offset) / displayed
	if uv.x < 0.0 or uv.x > 1.0 or uv.y < 0.0 or uv.y > 1.0:
		return MISS
	return (uv * Vector2(image_size)).clamp(Vector2.ZERO, Vector2(image_size) - Vector2.ONE).floor()

func _on_preview_input(event: InputEvent) -> void:
	if event is InputEventKey:
		if key_event(event):
			preview_control.accept_event()
		return
	if not connected or not event is InputEventMouse:
		return
	var pixel := preview_to_pixel(event.position, preview_control.size, frame_size)
	if pixel == MISS:
		_release_pointer()
		return
	if event is InputEventMouseMotion:
		_send_motion(pixel)
	elif event is InputEventMouseButton:
		preview_control.grab_focus()
		_send_motion(pixel, true)
		if event.button_index == MOUSE_BUTTON_WHEEL_UP and event.pressed:
			scroll(-event.factor)
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN and event.pressed:
			scroll(event.factor)
		elif event.button_index in [MOUSE_BUTTON_LEFT, MOUSE_BUTTON_RIGHT, MOUSE_BUTTON_MIDDLE]:
			var button := 1 if event.button_index == MOUSE_BUTTON_LEFT else (3 if event.button_index == MOUSE_BUTTON_RIGHT else 2)
			_send_button(pixel, button, event.pressed)
	preview_control.accept_event()

func _emit_command(command: Dictionary) -> bool:
	if not connected or _ipc.is_empty() or _instance_id.is_empty() or not status_error(status, Time.get_unix_time_from_system()).is_empty():
		return false
	_serial += 1
	var id := "%020d-%08d-%08d" % [int(Time.get_unix_time_from_system() * 1000000.0), OS.get_process_id(), _serial]
	var payload := command.duplicate(true)
	payload["id"] = id
	payload["protocol_version"] = PROTOCOL_VERSION
	payload["instance_id"] = _instance_id
	payload["created_at_unix"] = Time.get_unix_time_from_system()
	var directory := _ipc.path_join("commands")
	var temporary := directory.path_join(id + ".tmp")
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		command_failed.emit("Desktop input queue is unavailable")
		return false
	file.store_string(JSON.stringify(payload))
	file.close()
	if DirAccess.rename_absolute(temporary, directory.path_join(id + ".json")) != OK:
		DirAccess.remove_absolute(temporary)
		command_failed.emit("Desktop input could not be queued")
		return false
	_last_command_id = id
	return true

func send_command(type: String, params: Dictionary = {}) -> String:
	var command := params.duplicate(true)
	command["type"] = type
	return _last_command_id if _emit_command(command) else ""

## Call grip movement separately from point(); a UI pinch never moves the panel.
func begin_move(grip_transform: Transform3D) -> bool:
	if not is_open() or not grip_transform.is_finite() or absf(grip_transform.basis.determinant()) < 0.000001:
		return false
	release_input()
	_moving = true
	_move_offset = grip_transform.affine_inverse() * global_transform
	return true

func update_move(grip_transform: Transform3D) -> void:
	if _moving and grip_transform.is_finite() and absf(grip_transform.basis.determinant()) > 0.000001:
		move_panel(grip_transform * _move_offset)

func end_move() -> void:
	_moving = false
	_must_release = true

func move_panel(new_transform: Transform3D) -> void:
	if not new_transform.is_finite() or absf(new_transform.basis.determinant()) < 0.000001:
		return
	global_transform = Transform3D(new_transform.basis.orthonormalized().scaled(Vector3.ONE * _panel_scale), new_transform.origin)

func set_panel_scale(value: float) -> void:
	if not is_finite(value):
		return
	_panel_scale = clampf(value, MIN_SCALE, MAX_SCALE)
	global_basis = global_basis.orthonormalized().scaled(Vector3.ONE * _panel_scale)

func scale_panel(factor: float) -> void:
	if factor > 0.0 and is_finite(factor):
		set_panel_scale(_panel_scale * factor)

func get_panel_scale() -> float:
	return _panel_scale

func _exit_tree() -> void:
	release_input()
