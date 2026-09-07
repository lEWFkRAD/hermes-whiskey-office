extends Node3D
## Local rendition only. Original geometry, files and application state remain authoritative.
signal window_requested
signal source_requested
signal window_restored(surface: Node3D)
signal window_focused(surface: Node3D)
const CENTER := Vector3(-0.25, 0, -0.35)
const OBJECT_SHADER := """
shader_type spatial;
render_mode unshaded, blend_mix, cull_back, shadows_disabled;
varying vec3 local_position;
void vertex() { local_position = VERTEX; }
void fragment() {
    float edge = pow(1.0 - abs(dot(normalize(NORMAL), normalize(VIEW))), 2.4);
    float scan = smoothstep(0.72, 1.0, sin(local_position.y * 190.0 - TIME * 0.9));
    ALBEDO = vec3(0.055, 0.65, 0.82);
    EMISSION = vec3(0.06, 0.72, 0.95) * (0.30 + edge * 1.2 + scan * 0.17);
    ALPHA = clamp(0.18 + edge * 0.62 + scan * 0.13, 0.0, 0.9);
}
"""
const SCREEN_SHADER := """
shader_type spatial;
render_mode unshaded, blend_mix, cull_disabled, shadows_disabled;
uniform sampler2D live_texture : source_color, filter_linear;
uniform bool readable = false;
void fragment() {
    vec4 original = texture(live_texture, UV);
    float luminance = dot(original.rgb, vec3(0.2126, 0.7152, 0.0722));
    vec3 cyan = vec3(0.03, 0.78, 0.95) * (0.10 + luminance * 1.35);
    float line = 0.96 + 0.04 * sin(UV.y * 1250.0 - TIME * 0.7);
    ALBEDO = readable ? original.rgb : cyan * line;
    EMISSION = readable ? vec3(0.0) : cyan * 0.12;
    ALPHA = original.a * (readable ? 1.0 : 0.94);
}
"""
var choices: Array[Dictionary] = []
var selected := -1
var readable := false
var turning := false
var size_factor := 1.0
var source_name := "Podium ready"
var projection: Node3D
var live_window: Node3D
var _window_rest := Transform3D.IDENTITY
var _window_scale := 1.0
var _window_spatial := true
var _window_material: Material
var _mesh_materials: Dictionary = {}
var _loader: Callable
var _head: Node3D
var _object_material: ShaderMaterial
var _screen_material: ShaderMaterial
var _rings: Node3D
var _label: Label3D
var _status: Label
var _picker: OptionButton
var _file_picker: FileDialog
var _flat: MeshInstance3D
var _flat_texture: Texture2D
var _file_path := ""
var _file_stamp := 0
var _file_hash := ""
var _poll := 0.0
var _document: SubViewport
var _mouse_pressed := false

func setup(head: Node3D, loader: Callable, desktop_ui := true) -> void:
	_head = head
	_loader = loader
	_object_material = shader_material(OBJECT_SHADER)
	_screen_material = shader_material(SCREEN_SHADER)
	for path in ["res://office-assemblies.json", "res://hologram-catalogue.json"]:
		var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
		var rows: Array = value.get("assemblies", []) if value is Dictionary else (value if value is Array else [])
		for row: Dictionary in rows:
			if row.get("library_path") and row.get("id") != "hologram-podium": choices.append(row)
	build_optics()
	if desktop_ui: build_toolbar()

static func shader_material(code: String) -> ShaderMaterial:
	var shader := Shader.new()
	shader.code = code
	var material := ShaderMaterial.new()
	material.shader = shader
	return material

func build_optics() -> void:
	_rings = Node3D.new()
	add_child(_rings)
	var glow := StandardMaterial3D.new()
	glow.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	glow.albedo_color = Color("37cddc")
	glow.emission_enabled = true
	glow.emission = Color("22a5d1")
	glow.emission_energy_multiplier = 0.8
	for radius in [0.30, 0.405]:
		var mesh := MeshInstance3D.new()
		var ring := TorusMesh.new()
		ring.inner_radius = radius - 0.003
		ring.outer_radius = radius + 0.003
		ring.rings = 64
		ring.ring_segments = 8
		mesh.mesh = ring
		mesh.material_override = glow
		mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		mesh.position = CENTER + Vector3(0, 0.666, 0)
		_rings.add_child(mesh)
	_rings.hide()
	_label = Label3D.new()
	_label.position = CENTER + Vector3(0, 0.76, 0.49)
	_label.font_size = 26
	_label.pixel_size = 0.0011
	_label.modulate = Color("92dee8")
	_label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	_label.text = "THE PODIUM"
	add_child(_label)

func build_toolbar() -> void:
	var layer := CanvasLayer.new()
	layer.layer = 21
	add_child(layer)
	var stack := VBoxContainer.new()
	stack.position = Vector2(24, 155)
	layer.add_child(stack)
	var bar := HBoxContainer.new()
	stack.add_child(bar)
	_picker = OptionButton.new()
	_picker.custom_minimum_size.x = 200
	for spec in choices: _picker.add_item(str(spec.name))
	bar.add_child(_picker)
	for title in ["Project", "Live window", "Open file", "Rotate", "−", "+", "Readable", "Clear", "Work in window"]:
		var button := Button.new()
		button.text = title
		bar.add_child(button)
		button.pressed.connect(func() -> void:
			match title:
				"Project": open_index(_picker.selected)
				"Live window": window_requested.emit()
				"Open file": choose_file()
				"Rotate": turning = not turning
				"−": resize(0.87)
				"+": resize(1.15)
				"Readable": set_readable(not readable)
				"Clear": clear()
				"Work in window": source_requested.emit()
		)
	_status = Label.new()
	_status.add_theme_font_size_override("font_size", 15)
	stack.add_child(_status)
	update_caption()

func update_caption(extra := "") -> void:
	var message := source_name + (" · Full color" if readable else " · Hologram")
	if not extra.is_empty(): message += " · " + extra
	if _status: _status.text = message
	if _label: _label.text = source_name.left(70)

func select_next(direction := 1) -> bool:
	return open_index(posmod(selected + direction, choices.size())) if not choices.is_empty() else false

func open_index(index: int) -> bool:
	if index < 0 or index >= choices.size(): return false
	var candidate: Node3D = _loader.call(str(choices[index].library_path))
	if not candidate:
		update_caption("Could not load this model")
		return false
	if not present_model(candidate, str(choices[index].name)): return false
	selected = index
	if _picker: _picker.select(index)
	return true

static func model_bounds(node: Node3D) -> AABB:
	var result := AABB()
	var started := false
	var inverse := node.global_transform.affine_inverse()
	var nodes: Array = node.find_children("*", "MeshInstance3D", true, false)
	if node is MeshInstance3D: nodes.append(node)
	for mesh: MeshInstance3D in nodes:
		if not mesh.mesh: continue
		var bounds: AABB = (inverse * mesh.global_transform) * mesh.get_aabb()
		result = result.merge(bounds) if started else bounds
		started = true
	return result

func present_model(candidate: Node3D, title: String) -> bool:
	# Candidate is an independent library/import instance, never the source room node.
	var holder := Node3D.new()
	add_child(holder)
	holder.add_child(candidate)
	var bounds := model_bounds(candidate)
	var largest := maxf(bounds.size.x, maxf(bounds.size.y, bounds.size.z))
	if not is_finite(largest) or largest < 0.00001:
		holder.queue_free()
		update_caption("Model has no finite visible geometry")
		return false
	clear()
	projection = holder
	var fit := minf(1.05 / maxf(maxf(bounds.size.x, bounds.size.z), 0.001), 0.95 / maxf(bounds.size.y, 0.001))
	candidate.scale = Vector3.ONE * fit
	candidate.position = -bounds.get_center() * fit
	projection.position = CENTER + Vector3(0, 1.26, 0)
	var nodes: Array = candidate.find_children("*", "MeshInstance3D", true, false)
	if candidate is MeshInstance3D: nodes.append(candidate)
	for mesh: MeshInstance3D in nodes:
		_mesh_materials[mesh] = mesh.material_override
		mesh.material_override = _object_material
		mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	for player: AnimationPlayer in candidate.find_children("*", "AnimationPlayer", true, false):
		for animation in player.get_animation_list():
			if animation != "RESET":
				player.play(animation)
				break
	source_name = title
	_rings.show()
	set_readable(readable)
	return true

func take_model() -> Node3D:
	if not is_instance_valid(projection) or not projection.has_meta("fabricated_id"): return null
	# Detach this presentation only; immutable output and other room items stay.
	for mesh: MeshInstance3D in _mesh_materials:
		if is_instance_valid(mesh):
			mesh.material_override = _mesh_materials[mesh]
			mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	var item := projection
	projection = null
	remove_child(item)
	clear()
	return item

func project_window(surface: Node3D) -> bool:
	if not is_instance_valid(surface) or not surface.is_open():
		update_caption("Open a window first, then choose Live window")
		return false
	clear()
	live_window = surface
	live_window.set_meta("podium_projected", true)
	live_window.release_input()
	_window_rest = surface.global_transform
	_window_scale = surface.get_panel_scale()
	_window_spatial = surface.get_spatial_visible()
	_window_material = surface._panel.material_override
	var target := Transform3D(Basis.IDENTITY, CENTER + Vector3(0, 1.36, 0))
	var direction := _head.global_position - target.origin
	direction.y = 0
	if direction.length() > 0.01: target.basis = Basis.looking_at(-direction.normalized())
	surface.set_panel_scale(0.80)
	surface.move_panel(target)
	surface.set_spatial_visible(true)
	surface._panel.material_override = _screen_material
	source_name = surface.window_title + " · Live"
	_rings.show()
	set_readable(readable)
	refresh_window()
	return true

func refresh_window() -> void:
	if not is_instance_valid(live_window): return
	if not live_window.is_open():
		clear()
		return
	_screen_material.set_shader_parameter("live_texture", live_window.texture)
	update_caption("" if live_window.connected else live_window.reason)

func set_readable(value: bool) -> void:
	readable = value
	_screen_material.set_shader_parameter("readable", value)
	for mesh: MeshInstance3D in _mesh_materials:
		if is_instance_valid(mesh): mesh.material_override = _mesh_materials[mesh] if value else _object_material
	update_caption()

func resize(factor: float) -> void:
	if not is_finite(factor) or factor <= 0: return
	size_factor = clampf(size_factor * factor, 0.55, 1.7)
	if is_instance_valid(projection): projection.scale = Vector3.ONE * size_factor
	if is_instance_valid(live_window): live_window.set_panel_scale(0.8 * size_factor)

func clear() -> void:
	if is_instance_valid(live_window):
		live_window.release_input()
		live_window._panel.material_override = _window_material
		live_window.set_panel_scale(_window_scale)
		live_window.move_panel(_window_rest)
		live_window.set_spatial_visible(_window_spatial)
		live_window.set_meta("podium_projected", false)
		window_restored.emit(live_window)
	live_window = null
	_window_material = null
	if is_instance_valid(projection):
		remove_child(projection)
		projection.queue_free()
	projection = null
	_flat = null
	_flat_texture = null
	if is_instance_valid(_document): _document.queue_free()
	_document = null
	_mesh_materials.clear()
	_screen_material.set_shader_parameter("live_texture", null)
	_file_path = ""
	_file_stamp = 0
	_file_hash = ""
	turning = false
	size_factor = 1.0
	_mouse_pressed = false
	source_name = "Podium ready"
	if _rings: _rings.hide()
	update_caption()

func choose_file() -> void:
	if is_instance_valid(live_window): live_window.release_input()
	_mouse_pressed = false
	if not _file_picker:
		_file_picker = FileDialog.new()
		_file_picker.access = FileDialog.ACCESS_FILESYSTEM
		_file_picker.file_mode = FileDialog.FILE_MODE_OPEN_FILE
		_file_picker.filters = PackedStringArray(["*.glb ; 3D model", "*.png, *.jpg, *.jpeg ; Images", "*.txt, *.md, *.json, *.csv ; Text artifacts"])
		_file_picker.title = "Project a file · PDF / Office documents: use Live window"
		add_child(_file_picker)
		_file_picker.file_selected.connect(load_file)
	_file_picker.popup_centered(Vector2i(1000, 700))

func load_file(path: String) -> bool:
	var file := FileAccess.open(path, FileAccess.READ)
	if not file or file.get_length() > 64 * 1024 * 1024:
		update_caption("File unavailable or exceeds 64 MB")
		return false
	var extension := path.get_extension().to_lower()
	if extension == "glb":
		var document := GLTFDocument.new()
		var state := GLTFState.new()
		if document.append_from_file(path, state) != OK:
			update_caption("Could not read GLB")
			return false
		var model := document.generate_scene(state) as Node3D
		if not model or not present_model(model, path.get_file()): return false
	elif extension in ["png", "jpg", "jpeg"]:
		var image := Image.new()
		if image.load(path) != OK or image.get_width() > 8192 or image.get_height() > 8192:
			update_caption("Image unavailable or exceeds 8192 pixels")
			return false
		present_texture(ImageTexture.create_from_image(image), path.get_file())
	elif extension in ["txt", "md", "json", "csv"]:
		if file.get_length() > 128 * 1024:
			update_caption("Text exceeds 128 KB; project its application window")
			return false
		present_text(file.get_as_text(), path.get_file())
	else:
		update_caption("Open this document in its app, then choose Live window")
		return false
	_file_path = path
	_file_stamp = FileAccess.get_modified_time(path)
	_file_hash = FileAccess.get_sha256(path)
	return true

func present_texture(texture: Texture2D, title: String) -> void:
	clear()
	projection = Node3D.new()
	add_child(projection)
	projection.position = CENTER + Vector3(0, 1.35, 0)
	var direction := _head.global_position - projection.global_position
	direction.y = 0
	if direction.length() > 0.01: projection.basis = Basis.looking_at(-direction.normalized())
	_flat = MeshInstance3D.new()
	var quad := QuadMesh.new()
	var aspect := float(texture.get_width()) / maxf(texture.get_height(), 1)
	quad.size = Vector2(minf(1.4, 0.95 * aspect), minf(0.95, 1.4 / aspect))
	_flat.mesh = quad
	_flat.material_override = _screen_material
	_flat.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	projection.add_child(_flat)
	_flat_texture = texture
	_screen_material.set_shader_parameter("live_texture", texture)
	source_name = title
	_rings.show()
	set_readable(readable)

func present_text(text: String, title: String) -> void:
	var viewport := SubViewport.new()
	viewport.size = Vector2i(1000, 1100)
	viewport.disable_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(viewport)
	var background := ColorRect.new()
	background.color = Color("101c25")
	background.size = Vector2(viewport.size)
	viewport.add_child(background)
	var label := Label.new()
	label.position = Vector2(45, 38)
	label.size = Vector2(910, 1020)
	label.add_theme_font_size_override("font_size", 25)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.text = title + "\n\n" + text.left(2200) + ("\n\n[Preview truncated · use Live window for the full document]" if text.length() > 2200 else "")
	viewport.add_child(label)
	present_texture(viewport.get_texture(), title)
	_document = viewport

func mouse_input(event: InputEvent, camera: Camera3D) -> bool:
	if not is_instance_valid(live_window): return false
	if not event is InputEventMouse: return false
	var origin := camera.project_ray_origin(event.position)
	var direction := camera.project_ray_normal(event.position)
	var hit: bool = live_window.ray_distance(origin, direction) < INF
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_LEFT:
			if event.pressed and not hit: return false
			if event.pressed: window_focused.emit(live_window)
			_mouse_pressed = event.pressed
		elif hit and event.pressed and event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]:
			live_window.scroll(-1 if event.button_index == MOUSE_BUTTON_WHEEL_UP else 1)
			return true
	live_window.point(origin, direction, _mouse_pressed)
	return hit or _mouse_pressed

func _process(delta: float) -> void:
	if live_window != null and not is_instance_valid(live_window): clear()
	if is_instance_valid(live_window): refresh_window()
	if turning and is_instance_valid(projection): projection.rotate_y(delta * 0.25)
	_poll += delta
	if _poll >= 1.0:
		_poll = 0
		if not _file_path.is_empty():
			if not FileAccess.file_exists(_file_path):
				update_caption("Source missing · last preview retained")
			else:
				var stamp := FileAccess.get_modified_time(_file_path)
				# Godot timestamps have one-second granularity. Recheck bytes while
				# a write is recent so same-size edits within that second survive.
				var recent := absf(Time.get_unix_time_from_system() - float(stamp)) < 3.0
				var changed := stamp != _file_stamp or recent
				if changed and FileAccess.get_sha256(_file_path) != _file_hash:
					var saved_turn := turning
					var saved_size := size_factor
					if load_file(_file_path):
						turning = saved_turn
						resize(saved_size)
