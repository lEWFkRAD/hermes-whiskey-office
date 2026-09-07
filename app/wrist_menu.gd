extends Node3D
## A spatial function selector. Hermes still owns tool/plugin/approval UI.

class DialCanvas extends Control:
	var entries: Array = []
	var selected := 0
	var progress := 0.0
	var angle := 0.0
	var page_title := "Hermes"
	var note := "Twist to browse"
	var font: Font = ThemeDB.fallback_font
	const CENTER := Vector2(384, 370)

	func centered(text: String, at: Vector2, size: int, color: Color) -> void:
		var width := font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, size).x
		draw_string(font, at - Vector2(width * 0.5, 0), text, HORIZONTAL_ALIGNMENT_LEFT, -1, size, color)

	func _draw() -> void:
		if entries.is_empty(): return
		var count := entries.size()
		var step := TAU / count
		for index in count:
			var angle := index * step - PI * 0.5
			var start := angle - step * 0.5 + 0.035
			var finish := angle + step * 0.5 - 0.035
			var shape := PackedVector2Array()
			for tick in 17:
				shape.append(CENTER + Vector2.from_angle(lerpf(start, finish, tick / 16.0)) * 305)
			for tick in 17:
				shape.append(CENTER + Vector2.from_angle(lerpf(finish, start, tick / 16.0)) * 191)
			var active := index == selected
			var enabled := bool(entries[index].get("enabled", true))
			var fill := Color("594526") if active else Color("123e49")
			fill.a = 0.94 if active else 0.88
			if not enabled: fill = Color(0.10, 0.12, 0.14, 0.35)
			draw_colored_polygon(shape, fill)
			var outline := shape.duplicate()
			outline.append(outline[0])
			draw_polyline(outline, Color("ffe2a6") if active else Color(0.49, 0.91, 1.0, 0.64), 3.0 if active else 1.2, true)
			luminous_arc(306, start, finish, Color("ffe2a6") if active else Color(0.49, 0.91, 1.0, 0.7), 3.0 if active else 1.1)
			var location := CENTER + Vector2.from_angle(angle) * 250
			var lines := str(entries[index].get("label", "")).split("\n")
			for line in lines.size():
				centered(lines[line], location + Vector2(0, 8 + line * 24 - (lines.size() - 1) * 12), 22, Color("e6faff") if enabled else Color("748990"))
		luminous_arc(323, 0, TAU, Color(0.49, 0.91, 1.0, 0.55), 1.5)
		for tick in 96:
			var direction := Vector2.from_angle(tick * TAU / 96.0 - PI * 0.5)
			var length := 10.0 if tick % 12 == 0 else (6.0 if tick % 3 == 0 else 3.0)
			draw_line(CENTER + direction * 329, CENTER + direction * (329 + length), Color(0.49, 0.91, 1.0, 0.65), 1.2, true)
		var cursor := Vector2.from_angle(deg_to_rad(self.angle) - PI * 0.5)
		var point := CENTER + cursor * 348
		var tangent := Vector2(-cursor.y, cursor.x)
		draw_colored_polygon(PackedVector2Array([point - cursor * 9, point + cursor * 6 + tangent * 5, point + cursor * 6 - tangent * 5]), Color("ffe2a6"))
		draw_circle(CENTER, 164, Color(0.015, 0.045, 0.065, 0.94))
		luminous_arc(176, 0, TAU, Color(0.49, 0.91, 1.0, 0.5), 1.2)
		if progress > 0:
			luminous_arc(178, -PI * 0.5, -PI * 0.5 + progress * TAU, Color("f7d591"), 5)
		centered(page_title.to_upper(), CENTER + Vector2(0, -78), 15, Color("83dfee"))
		centered(str(entries[clampi(selected, 0, count - 1)].get("label", "")).replace("\n", " "), CENTER + Vector2(0, -28), 33, Color("f0e4cf"))
		var description := str(entries[clampi(selected, 0, count - 1)].get("description", ""))
		var lines := description.split("\n")
		for index in lines.size():
			centered(lines[index], CENTER + Vector2(0, 14 + index * 25), 19, Color("c9bda7"))
		centered(note, CENTER + Vector2(0, 93), 17, Color("e9c68a"))
		centered("PINCH / TRIGGER · HOLD & RELEASE", Vector2(384, 744), 16, Color("cef4ff"))

	func luminous_arc(radius: float, start: float, end: float, color: Color, width: float) -> void:
		# Soft halos stay legible without an expensive full-screen XR bloom pass.
		for halo in [12.0, 6.0]:
			draw_arc(CENTER, radius, start, end, 120, Color(color, color.a * 0.07), width + halo, true)
		draw_arc(CENTER, radius, start, end, 120, color, width, true)

var _viewport: SubViewport
var _canvas: DialCanvas
var _quad: MeshInstance3D
var _head: Node3D
var _last_paint := ""
var _cuff: Node3D
var _cuff_material: StandardMaterial3D
var _tracked := false

func setup(head: Node3D) -> void:
	_head = head
	_viewport = SubViewport.new()
	_viewport.size = Vector2i(768, 768)
	_viewport.disable_3d = true
	_viewport.transparent_bg = true
	_viewport.render_target_update_mode = SubViewport.UPDATE_WHEN_VISIBLE
	add_child(_viewport)
	_canvas = DialCanvas.new()
	_canvas.size = Vector2(768, 768)
	_viewport.add_child(_canvas)
	_quad = MeshInstance3D.new()
	var mesh := QuadMesh.new()
	mesh.size = Vector2(0.48, 0.48)
	_quad.mesh = mesh
	_quad.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	material.albedo_texture = _viewport.get_texture()
	material.no_depth_test = true
	material.render_priority = 100
	material.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR
	_quad.material_override = material
	add_child(_quad)
	_cuff = Node3D.new()
	_cuff.name = "WristLightRings"
	add_child(_cuff)
	_cuff.top_level = true
	_cuff_material = StandardMaterial3D.new()
	_cuff_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	_cuff_material.albedo_color = Color(0.42, 0.88, 1.0, 0.85)
	_cuff_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	_cuff_material.emission_enabled = true
	_cuff_material.emission = Color(0.22, 0.76, 1.0)
	_cuff_material.emission_energy_multiplier = 1.8
	for index in 3:
		var ring := MeshInstance3D.new()
		var torus := TorusMesh.new()
		torus.inner_radius = 0.051 + index * 0.006
		torus.outer_radius = torus.inner_radius + 0.0016
		torus.rings = 48
		torus.ring_segments = 6
		ring.mesh = torus
		ring.position.y = (index - 1) * 0.014
		ring.material_override = _cuff_material
		ring.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		_cuff.add_child(ring)
	hide()

func set_page(title: String, entries: Array) -> void:
	_canvas.page_title = title
	_canvas.entries = entries
	_last_paint = ""
	_canvas.queue_redraw()

func open_near(wrist: Vector3, tracked_hand: bool) -> void:
	if not is_instance_valid(_head) or not wrist.is_finite(): return
	_tracked = tracked_hand
	global_basis = _head.global_basis.orthonormalized()
	if tracked_hand:
		global_position = _target(wrist)
	else:
		global_position = _head.global_position - _head.global_basis.z * 0.90
	_cuff.hide()
	show()

func _target(wrist: Vector3) -> Vector3:
	var target := wrist + _head.global_basis.x * 0.11 + _head.global_basis.y * 0.18
	var depth := (target - _head.global_position).dot(-_head.global_basis.z)
	return target - _head.global_basis.z * maxf(0.0, 0.40 - depth)

func follow_hand(wrist: Vector3, wrist_basis: Basis, delta: float) -> void:
	if not visible or not _tracked or not is_instance_valid(_head): return
	if not wrist.is_finite() or not wrist_basis.is_finite() or wrist_basis.determinant() <= 0.000001 or not is_finite(delta) or delta < 0:
		hide()
		return
	# Expanded controls remain where they opened. Only the glowing cuff follows.
	_cuff.global_transform = Transform3D(wrist_basis.orthonormalized(), wrist)
	_cuff.show()

func present(state: Dictionary) -> void:
	visible = bool(state.get("open", false))
	if not visible: return
	var selected := int(state.get("selected_index", 0))
	var progress := float(state.get("progress", 0.0))
	var angle := float(state.get("dialangle_degrees", 0.0))
	if progress > 0: angle = selected * 45.0
	var note := "Release to select" if progress >= 1.0 else ("Hold pinch / trigger…" if progress > 0.0 else "Twist or right stick")
	_cuff_material.albedo_color = Color(1.0, 0.79, 0.42, 0.95) if progress > 0 else Color(0.42, 0.88, 1.0, 0.85)
	_cuff_material.emission = Color(1.0, 0.6, 0.2) if progress > 0 else Color(0.22, 0.76, 1.0)
	var key := "%s:%s:%s:%s" % [selected, int(progress * 30), int(angle), note]
	if key != _last_paint:
		_canvas.selected = selected
		_canvas.progress = progress
		_canvas.angle = angle
		_canvas.note = note
		_canvas.queue_redraw()
		_last_paint = key
