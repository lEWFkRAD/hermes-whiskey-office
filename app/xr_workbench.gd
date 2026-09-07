extends Node3D
## World-space presentation only. The caller wires widget signals/state and owns
## the controller ray, locomotion lock, voice transport, and room visibility.
## setup() requires this node and the supplied head to be inside the scene tree.

const Workbench = preload("res://workbench.gd")
const VIEWPORT_SIZE := Vector2i(1280, 800)
const PANEL_SIZE := Vector2(1.28, 0.8)
const PANEL_DISTANCE := 1.15
const MISS := Vector2(-1.0, -1.0)
const OUTSIDE := Vector2(-32.0, -32.0)

var widget
var viewport: SubViewport
var _head: Camera3D
var _cursor: MeshInstance3D
var _built := false
var _opened := false
var _hovering := false
var _button_down := false
var _trigger_was_pressed := false
var _must_release := true
var _last_position := OUTSIDE

func setup(head: Camera3D) -> void:
	_head = head
	if _built:
		return
	_built = true
	name = "XRWorkbench"
	viewport = SubViewport.new()
	viewport.name = "WorkbenchViewport"
	viewport.size = VIEWPORT_SIZE
	viewport.disable_3d = true
	viewport.transparent_bg = true
	viewport.gui_embed_subwindows = true
	viewport.handle_input_locally = true
	viewport.render_target_update_mode = SubViewport.UPDATE_DISABLED
	add_child(viewport)
	widget = Workbench.new()
	viewport.add_child(widget)
	widget.setup()
	widget.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	widget.close_requested.connect(close_panel)

	var panel := MeshInstance3D.new()
	panel.name = "WorkbenchSurface"
	var quad := QuadMesh.new()
	quad.size = PANEL_SIZE
	panel.mesh = quad
	panel.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	material.albedo_texture = viewport.get_texture()
	material.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR
	panel.material_override = material
	add_child(panel)

	_cursor = MeshInstance3D.new()
	_cursor.name = "PointerCursor"
	var sphere := SphereMesh.new()
	sphere.radius = 0.004
	sphere.height = 0.008
	sphere.radial_segments = 12
	sphere.rings = 6
	_cursor.mesh = sphere
	_cursor.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var cursor_material := StandardMaterial3D.new()
	cursor_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	cursor_material.albedo_color = Color("e4bd75")
	_cursor.material_override = cursor_material
	add_child(_cursor)
	_cursor.hide()
	widget.hide()
	hide()

func open_panel() -> void:
	if not _built or not is_instance_valid(_head) or not _head.is_inside_tree():
		return
	# Quad front is local +Z, while the camera looks along local -Z.
	# Position once on opening; it then stays in the world as the head moves.
	var orientation := _head.global_basis.orthonormalized()
	global_transform = Transform3D(orientation, _head.global_position - orientation.z * PANEL_DISTANCE)
	_opened = true
	_must_release = true
	_trigger_was_pressed = false
	widget.show()
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	show()

func close_panel() -> void:
	_release_pointer()
	_opened = false
	_must_release = true
	_trigger_was_pressed = false
	if is_instance_valid(widget):
		widget.hide()
	if is_instance_valid(viewport):
		viewport.gui_release_focus()
		viewport.render_target_update_mode = SubViewport.UPDATE_DISABLED
	hide()

func is_open() -> bool:
	return _opened and is_visible_in_tree()

## Returns normalized top-left UV, or MISS. A panel is one-sided: rays starting
## behind it, parallel rays and hits outside the rectangle cannot activate UI.
static func ray_to_uv(panel_transform: Transform3D, ray_origin: Vector3, ray_direction: Vector3, panel_size: Vector2 = PANEL_SIZE) -> Vector2:
	if not ray_origin.is_finite() or not ray_direction.is_finite() or not panel_size.is_finite():
		return MISS
	if panel_size.x <= 0.0 or panel_size.y <= 0.0 or absf(panel_transform.basis.determinant()) < 0.000001:
		return MISS
	var inverse := panel_transform.affine_inverse()
	var origin := inverse * ray_origin
	var direction := inverse.basis * ray_direction
	if not origin.is_finite() or not direction.is_finite() or origin.z < 0.0 or direction.z >= -0.000001:
		return MISS
	var distance := -origin.z / direction.z
	if distance < 0.0:
		return MISS
	var hit := origin + direction * distance
	var uv := Vector2(hit.x / panel_size.x + 0.5, 0.5 - hit.y / panel_size.y)
	if uv.x < 0.0 or uv.x > 1.0 or uv.y < 0.0 or uv.y > 1.0:
		return MISS
	return uv

## Call every frame, including misses/tracking loss (a zero direction is a miss).
## pressed is the trigger/pinch level. Entering while held never starts a click.
func point(ray_origin: Vector3, ray_direction: Vector3, pressed: bool) -> bool:
	if not is_open():
		_release_pointer()
		return false
	var new_press := pressed and not _trigger_was_pressed
	_trigger_was_pressed = pressed
	if not pressed:
		_must_release = false
	var uv := ray_to_uv(global_transform, ray_origin, ray_direction)
	if uv == MISS:
		_release_pointer()
		return false
	var position_2d := uv * Vector2(VIEWPORT_SIZE)
	# Inclusive geometric edges map to the last valid pixel, not outside it.
	position_2d = position_2d.clamp(Vector2.ZERO, Vector2(VIEWPORT_SIZE) - Vector2.ONE)
	if not _hovering:
		_hovering = true
		_last_position = position_2d
		if is_instance_valid(viewport):
			viewport.notify_mouse_entered()
	if is_instance_valid(_cursor):
		_cursor.position = Vector3((uv.x - 0.5) * PANEL_SIZE.x, (0.5 - uv.y) * PANEL_SIZE.y, 0.006)
		_cursor.show()
	_send_motion(position_2d)
	if _button_down and not pressed:
		_send_button(position_2d, false)
	elif new_press and not _must_release:
		_send_button(position_2d, true)
	return true

func _send_motion(position_2d: Vector2) -> void:
	var event := InputEventMouseMotion.new()
	event.position = position_2d
	event.global_position = position_2d
	event.relative = position_2d - _last_position
	event.button_mask = MOUSE_BUTTON_MASK_LEFT if _button_down else 0
	_last_position = position_2d
	_dispatch_input(event)

func _send_button(position_2d: Vector2, down: bool) -> void:
	_button_down = down
	var event := InputEventMouseButton.new()
	event.position = position_2d
	event.global_position = position_2d
	event.button_index = MOUSE_BUTTON_LEFT
	event.button_mask = MOUSE_BUTTON_MASK_LEFT if down else 0
	event.pressed = down
	_dispatch_input(event)

func _release_pointer() -> void:
	if _hovering or _button_down:
		# Release outside the control so closing/losing tracking cancels a click.
		_send_motion(OUTSIDE)
		if _button_down:
			_send_button(OUTSIDE, false)
		if is_instance_valid(viewport):
			viewport.notify_mouse_exited()
	_hovering = false
	if is_instance_valid(_cursor):
		_cursor.hide()

func _dispatch_input(event: InputEvent) -> void:
	if is_instance_valid(viewport):
		viewport.push_input(event, true)

func _input(event: InputEvent) -> void:
	if is_open() and event is InputEventKey:
		_dispatch_input(event.duplicate() as InputEvent)
		# Polled movement still needs to be suspended by the caller while open.
		get_viewport().set_input_as_handled()

## Compositor passthrough only; this never provides physical camera pixels.
## Caller must also hide the opaque room and use a transparent environment.
func enable_passthrough(interface: XRInterface, enabled: bool) -> bool:
	if interface == null or not interface.is_initialized() or not is_inside_tree():
		return false
	var mode := XRInterface.XR_ENV_BLEND_MODE_ALPHA_BLEND if enabled else XRInterface.XR_ENV_BLEND_MODE_OPAQUE
	if mode not in interface.get_supported_environment_blend_modes():
		return false
	if not interface.set_environment_blend_mode(mode):
		return false
	get_viewport().transparent_bg = enabled
	return true
