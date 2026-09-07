extends Node3D
## Local, nonmodal coaching. Never sends actions, captures input, or follows the head.
const TIPS := {
	"hands": ["Open your hand menu", "Raise your right hand. Extend index and middle\nfingers; curl ring and little fingers.\nHold briefly to open the glowing rings."],
	"hand_menu": ["Twist, pinch, release", "Gently twist your wrist to choose a function.\nPinch thumb and index, hold briefly, then release.\nLower and relax your hand to close the menu."],
	"hand_windows": ["Point to work", "Point and pinch to select a window control.\nAim at a window and pinch with both hands\nto move it; spread your hands to resize."],
	"controllers": ["Your controller shortcuts", "Left stick walks. Right stick snap-turns.\nA focuses Hermes. B goes back. X shows windows.\nY opens the menu. Grip grabs a pointed target."],
	"controller_menu": ["Choose from the wheel", "Use the right stick or gently twist your wrist.\nHold the trigger briefly, then release to confirm.\nB closes the menu. Left stick still walks."],
	"voice": ["Talk when you choose", "Dictate records into a draft. Send asks for a reply.\nEnd voice stops recording or conversation.\nContinuous conversation is a separate choice."],
}
const SHOW_SECONDS := 12.0
const GAP_SECONDS := 8.0
var enabled := true
var seen: Dictionary = {}
var current := ""
var remaining := 0.0
var cooldown := 2.0
var candidate := ""
var stable := 0.0
var pending := ""
var head: Node3D
var storage := ""
var title_label: Label3D
var body_label: Label3D
var footer_label: Label3D

func setup(viewer: Node3D, data_directory: String, draw_card := true) -> void:
	head = viewer
	if not data_directory.is_empty():
		storage = data_directory.path_join("control-tips.json")
		if FileAccess.file_exists(storage):
			var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(storage))
			if value is Dictionary and value.get("version") == 1:
				enabled = value.get("enabled", true) == true
				if value.get("seen") is Dictionary:
					for key in value.seen:
						if TIPS.has(key) and value.seen[key] == true: seen[key] = true
	if draw_card: build_card()
	hide()

func build_card() -> void:
	var panel := MeshInstance3D.new()
	var quad := QuadMesh.new()
	quad.size = Vector2(0.90, 0.37)
	panel.mesh = quad
	panel.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = Color("12252a")
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	material.render_priority = 5
	material.no_depth_test = true
	panel.material_override = material
	add_child(panel)
	title_label = make_label(30, Color("9eeafa"), 0.12)
	body_label = make_label(24, Color("f0e4cf"), 0.007)
	footer_label = make_label(18, Color("beaa87"), -0.14)
	footer_label.text = "Fades in 12s · B hides · Replay or disable: Senses → Help"

func make_label(size: int, color: Color, y: float) -> Label3D:
	var label := Label3D.new()
	label.font_size = size
	label.pixel_size = 0.001
	label.modulate = color
	label.outline_size = 0
	label.no_depth_test = true
	label.render_priority = 6
	label.position = Vector3(0, y, 0.003)
	add_child(label)
	return label

func save_preferences() -> void:
	if storage.is_empty(): return
	DirAccess.make_dir_recursive_absolute(storage.get_base_dir())
	var file := FileAccess.open(storage + ".tmp", FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify({"version": 1, "enabled": enabled, "seen": seen}))
		file.close()
		DirAccess.rename_absolute(storage + ".tmp", storage)

func dismiss() -> bool:
	var was_visible := not current.is_empty()
	current = ""
	remaining = 0.0
	hide()
	if was_visible: cooldown = GAP_SECONDS
	return was_visible

func request_tip(id: String) -> void:
	if not TIPS.has(id): return
	dismiss()
	pending = id # Explicit Help can preview a tip even with automatic tips disabled.
	cooldown = 0.0

func set_tips_enabled(value: bool) -> void:
	enabled = value
	pending = ""
	dismiss()
	if value: seen.clear()
	cooldown = 1.0
	save_preferences()

func present_tip(id: String) -> void:
	if not TIPS.has(id) or not is_instance_valid(head): return
	current = id
	remaining = SHOW_SECONDS
	seen[id] = true
	save_preferences()
	# Place once in world space, below and to the left of the initial gaze.
	# It stays put when the wearer turns or moves.
	global_transform = Transform3D(head.global_basis, head.global_position + head.global_basis * Vector3(-0.52, -0.28, -1.35))
	if title_label:
		title_label.text = TIPS[id][0]
		body_label.text = TIPS[id][1]
	show()

func update_context(hand_valid: bool, controller_valid: bool, menu_open: bool, window_targeted: bool, delta: float) -> void:
	var dt := clampf(delta, 0.0, 0.1)
	if not hand_valid and not controller_valid:
		# Tracking loss is quiet; it must not consume a tip or dismiss preference.
		hide()
		stable = 0.0
		return
	if not current.is_empty():
		if current == "hands" and hand_valid and menu_open and not seen.has("hand_menu"):
			present_tip("hand_menu")
			return
		remaining -= dt
		visible = true
		if remaining <= 0.0: dismiss()
		return
	cooldown = maxf(0.0, cooldown - dt)
	if not pending.is_empty() and not menu_open and cooldown <= 0.0:
		var id := pending
		pending = ""
		present_tip(id)
		return
	if not enabled or cooldown > 0.0: return
	var id := "hand_menu" if hand_valid and menu_open else "controller_menu" if menu_open else "hand_windows" if hand_valid and window_targeted else "hands" if hand_valid else "controllers"
	if id != candidate:
		candidate = id
		stable = 0.0
	stable += dt
	if stable >= 1.0 and not seen.has(id): present_tip(id)
