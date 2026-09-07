extends Node3D
## Native office renderer. Context snapshots remain read-only for clients.
## Explicit, validated actions are applied by the running scene and acknowledged.

const CREAM := Color("f0e4cf")
const MUTED := Color("bcae97")
const GOLD := Color("c6a56b")
const INK := Color("171b19")
const STATE_FILES := {
	"agents": "quest-agents.json", "kanban": "vr-kanban.json",
	"voice": "vr-voice-state.json", "request": "vr-voice-request.json"
}
const BUSY_VOICE := ["loading", "listening", "transcribing", "thinking", "speaking"]
const AGENT_MAX_AGE := 120.0
const KANBAN_MAX_AGE := 20.0
const DEFAULT_VIEWS := [
	{"name": "The room", "position": [3.55, 1.7, 4.75], "target": [-0.35, 1.15, -2.1]},
	{"name": "At the desk", "position": [-0.15, 1.3, -0.82], "target": [0.4, 1.23, -2.4]},
	{"name": "By the fire", "position": [-3.15, 1.3, 1.75], "target": [-0.2, 1.25, -3.6]},
	{"name": "The collection", "position": [2.8, 1.65, 1.95], "target": [4.3, 1.4, -2.1]}
]

var layout: Dictionary = {}
var state_dir: String
var camera: Camera3D
var xr_camera: XRCamera3D
var xr_origin: XROrigin3D
var xr_active := false
var controllers: Array[XRController3D] = []
var trigger_was_down := false
var trigger_voice = preload("res://trigger_voice.gd").new()
var xr_snap_armed := true
var xr_view_button_was_down := false
var xr_desk_view := false
var companion: Node3D
var companion_base := Vector3.ZERO
var companion_yaw := 0.0
var animation_player: AnimationPlayer
var current_animation := ""
var asset_results: Dictionary = {}
var agent_snapshot: Dictionary = {}
var voice_snapshot: Dictionary = {}
var agent_status := "offline"
var agent_title := "Hermes offline"
var agent_task := "No agent state available."
var voice_title := "Voice offline"
var voice_message := "The local voice bridge has not reported a state."
var request_pending := false
var request_stamp := 0.0
var last_request_tick := -100.0
var kanban_summary := "Task board unavailable"
var grouped_tasks: Dictionary = {"TODO": [], "RUNNING": [], "REVIEW": [], "DONE": []}
var refresh_time := 0.0
var elapsed := 0.0
var screen_labels: Dictionary = {}
var desktop_labels: Dictionary = {}
var voice_button: Button
var details_panel: PanelContainer
var hud: CanvasLayer
var screen_root: Node3D
var view_name := "The room"
var walking_height := 1.65
var capture_path := ""
var capture_delay := 3.0
var capture_started := false
var quit_after_capture := false
var validate_only := false
var starting_view := 0
var automation_started_msec := 0
var automation_finished := false
var office_client
var workbench
var xr_panel
var open_workbench_on_start := false
var pending_message_id := ""
var local_ui_error := ""
var sharing_frame := false
var last_draft := ""
var xr_close_was_down := false
var xr_desk_was_down := false
var pinch_was_down := false
var passthrough_active := false
var room_environment: WorldEnvironment
var room_models: Array[Node3D] = []
var hand_pointer
var left_hand_pointer
var xr_feedback
var controller_grips: Array[XRController3D] = []
var desktop_surface
var office_windows
var desktop_preview: Control
var desktop_grab := false
var desktop_hand_scale_distance := 0.0
var desktop_hand_scale := 1.0
var desktop_scroll_elapsed := 0.0
var desktop_tracking_source := ""
var wrist_controls
var visual_materials = preload("res://office_materials.gd").new()
var desk_material: StandardMaterial3D
var desk_image_quad: QuadMesh
var desk_aperture := Vector2(1.15, 0.65)
var desk_fallback: SubViewport
var desk_connection: Label
var assembly_review
var review_camera_transform := Transform3D.IDENTITY
var review_camera_saved := false
var review_previous_view := "The room"
var room_control_hint: Label
var hologram
var fabricator
var control_tips

func _enter_tree() -> void:
	automation_started_msec = Time.get_ticks_msec()

func _ready() -> void:
	parse_arguments()
	var loaded: Variant = read_json("res://office-layout.json")
	if loaded is Dictionary:
		layout = loaded
	state_dir = resolve_state_directory()
	load_room_assets()
	if validate_only:
		# Asset and contract checks need no rendering, viewport textures, UI, or XR.
		# Avoid GPU setup and frame awaits in the headless validation path.
		refresh_snapshots()
		validate_scene.call_deferred()
		return
	build_environment()
	build_artwork()
	build_loading_bay_labels()
	build_camera_rig()
	build_desk_display()
	build_desktop_hud()
	build_workbench()
	build_hologram_podium()
	control_tips = load("res://office_tutorial.gd").new()
	add_child(control_tips)
	control_tips.setup(xr_camera if xr_active else camera, OS.get_environment("HERMES_OFFICE_DATA_DIR"))
	var awareness: Node = load("res://office_awareness.gd").new()
	add_child(awareness)
	awareness.setup(self)
	var scene_commands: Node = load("res://office_scene_commands.gd").new()
	add_child(scene_commands)
	scene_commands.setup(self, awareness.path.get_base_dir() if not awareness.path.is_empty() else "", awareness.instance)
	if OS.get_environment("HERMES_OFFICE_PARTS_PREVIEW") == "1": build_assembly_review()
	refresh_snapshots()
	if wrist_controls and OS.get_environment("HERMES_OFFICE_WRIST_PREVIEW") == "1":
		wrist_controls.preview.call_deferred()
	if OS.get_environment("HERMES_OFFICE_PARTS_PREVIEW") == "1":
		preview_assembly.call_deferred()
	if office_windows and OS.get_environment("HERMES_OFFICE_WINDOWS_PREVIEW") == "1":
		preview_windows.call_deferred()
	if office_windows and OS.get_environment("HERMES_OFFICE_BAY_PREVIEW") == "1":
		preview_loading_bay.call_deferred()
	if OS.get_environment("HERMES_OFFICE_HOLOGRAM_PREVIEW") != "":
		preview_hologram.call_deferred()
	if OS.get_environment("HERMES_PODIUM_PREVIEW") != "":
		preview_fabricator.call_deferred()

func preview_fabricator() -> void:
	await get_tree().create_timer(3.0).timeout
	fabricator.refresh()
	if OS.get_environment("HERMES_PODIUM_PREVIEW") == "fabricating": return
	if not fabricator.next_output(): return
	if OS.get_environment("HERMES_PODIUM_PREVIEW") == "picked-up":
		var item: Node3D = hologram.projection
		var pose := Transform3D(Basis.IDENTITY, item.global_position + Vector3(0, 0, 1.2))
		if fabricator.grab_input(pose, Vector3.FORWARD, true):
			pose.origin += Vector3(0.8, 0.15, 0.10)
			pose.basis = Basis(Vector3.UP, 0.3)
			fabricator.grab_input(pose, Vector3.FORWARD, true)
			fabricator.grab_input(pose, Vector3.FORWARD, false)

func build_hologram_podium() -> void:
	hologram = load("res://office_hologram.gd").new()
	add_child(hologram)
	hologram.setup(xr_camera if xr_active else camera, func(path: String) -> Node3D:
		var model := model_instance(path)
		if model: refine_room_materials(model)
		return model
	, not xr_active)
	fabricator = load("res://office_fabricator.gd").new()
	add_child(fabricator)
	fabricator.setup(hologram, xr_camera if xr_active else camera, not xr_active)
	hologram.window_requested.connect(project_active_window)
	hologram.window_focused.connect(func(surface: Node3D) -> void:
		if not office_windows: return
		for id in office_windows.surfaces:
			if office_windows.surfaces[id] == surface: office_windows.focus_window(id)
	)
	hologram.source_requested.connect(func() -> void:
		hologram.clear()
		if office_windows: office_windows.open_window(office_windows.active_id)
	)
	hologram.window_restored.connect(func(surface: Node3D) -> void:
		if not office_windows: return
		for id in office_windows.surfaces:
			if office_windows.surfaces[id] == surface and office_windows.native_windows.has(id) and surface.is_open():
				office_windows.native_windows[id].show()
	)

func project_active_window() -> void:
	if not hologram or not office_windows: return
	var id: String = office_windows.active_id
	if not office_windows.active() or not office_windows.active().is_open():
		if not office_windows.open_window(id): return
	if hologram.project_window(office_windows.active()):
		if office_windows.native_windows.has(id): office_windows.native_windows[id].hide()
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE

func preview_hologram() -> void:
	var mode := OS.get_environment("HERMES_OFFICE_HOLOGRAM_PREVIEW")
	if mode == "window":
		await get_tree().create_timer(1.0).timeout
		project_active_window()
	elif mode == "document":
		hologram.present_text("Shared work\n\nFORGE / SHATNER / ONYX\n\nAn artifact stays in its source application.\nThe podium changes its visual presentation.\n\nOpen a model, image or text file here.\nUse Live window for documents and tables.\n\nReadable restores full color.\nClear returns the window to its original place.", "Podium guide · preview fixture")
	else:
		for index in hologram.choices.size():
			if str(hologram.choices[index].id) == "desk":
				hologram.open_index(index)
				break

func build_loading_bay_labels() -> void:
	for index in 3:
		var plate := Label3D.new()
		plate.text = ["FORGE", "SHATNER", "ONYX"][index]
		plate.font_size = 28
		plate.pixel_size = 0.0014
		plate.modulate = Color("e3c88c")
		plate.position = Vector3(0.70 + index * 0.65, 0.90, 1.94)
		add_child(plate)

func preview_loading_bay() -> void:
	await get_tree().create_timer(1.0).timeout
	office_windows.open_window("loading-bay")

func preview_windows() -> void:
	await get_tree().create_timer(1.0).timeout
	for id in ["hermes", "remote-1", "remote-2"]: office_windows.open_window(id)
	office_windows.arrange()

func parse_arguments() -> void:
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--capture="):
			capture_path = argument.trim_prefix("--capture=")
		elif argument.begins_with("--capture-delay="):
			capture_delay = clampf(argument.trim_prefix("--capture-delay=").to_float(), 0.5, 40.0)
		elif argument.begins_with("--view="):
			starting_view = maxi(argument.trim_prefix("--view=").to_int() - 1, 0)
		elif argument == "--quit-after-capture":
			quit_after_capture = true
		elif argument == "--validate":
			validate_only = true
		elif argument == "--workbench":
			open_workbench_on_start = true

func resolve_state_directory() -> String:
	var explicit := OS.get_environment("HERMES_STATE_DIR")
	if not explicit.is_empty():
		return explicit
	if OS.get_name() == "Windows":
		return OS.get_environment("USERPROFILE").path_join(".hermes")
	return OS.get_environment("HOME").path_join(".hermes")

func state_path(kind: String) -> String:
	return state_dir.path_join(str(STATE_FILES[kind]))

func read_json(path: String) -> Variant:
	if not FileAccess.file_exists(path):
		return null
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null or file.get_length() > 4 * 1024 * 1024:
		return null
	var parser := JSON.new()
	if parser.parse(file.get_as_text()) != OK:
		return null
	return parser.data

func file_age(path: String) -> float:
	if not FileAccess.file_exists(path):
		return INF
	return maxf(0.0, Time.get_unix_time_from_system() - float(FileAccess.get_modified_time(path)))

func vector(value: Variant, fallback := Vector3.ZERO) -> Vector3:
	if value is Array and value.size() >= 3:
		return Vector3(float(value[0]), float(value[1]), float(value[2]))
	return fallback

func place_model(model: Node3D, spec: Dictionary) -> void:
	model.position = vector(spec.get("position", []))
	model.rotation_degrees = vector(spec.get("rotation_degrees", []))
	model.scale = Vector3.ONE * float(spec.get("scale", 1.0))

func model_instance(path: String) -> Node3D:
	if not FileAccess.file_exists(path):
		asset_results[path] = "missing"
		push_warning("Office asset missing: " + path)
		return null
	# Imported PackedScenes are fast. Runtime glTF also allows a copied GLB to
	# open on the first launch before the editor has generated an import cache.
	var model: Node3D
	if ResourceLoader.exists(path, "PackedScene"):
		var scene := ResourceLoader.load(path, "PackedScene") as PackedScene
		if scene:
			model = scene.instantiate() as Node3D
	if model == null:
		var document := GLTFDocument.new()
		var state := GLTFState.new()
		if document.append_from_file(ProjectSettings.globalize_path(path), state) == OK:
			model = document.generate_scene(state) as Node3D
	asset_results[path] = "loaded" if model else "failed"
	return model

func load_room_assets() -> void:
	var room := model_instance("res://assets/whiskey-room.glb")
	if room:
		room.name = "WhiskeyRoomAsset"
		refine_room_materials(room)
		add_child(room)
		room_models.append(room)
	var decorations := model_instance("res://assets/office-decorations.glb")
	if decorations:
		decorations.name = "BotanicalListeningCollection"
		refine_room_materials(decorations)
		add_child(decorations)
		room_models.append(decorations)
	var body := model_instance("res://assets/hermes-companion.glb")
	if body:
		companion = Node3D.new()
		companion.name = "HermesCompanion"
		add_child(companion)
		companion.add_child(body)
		var spec: Dictionary = layout.get("companion", {"position": [1.65, 0, -1.7]})
		place_model(companion, spec)
		companion_base = companion.position
		companion_yaw = companion.rotation.y
		animation_player = find_animation_player(body)
		play_matching_animation(["Hermes_Idle", "Idle", "idle"])
	for spec in layout.get("chairs", []):
		if not spec is Dictionary:
			continue
		if validate_only and asset_results.get("res://assets/club-chair.glb", "") == "loaded":
			continue
		var chair := model_instance("res://assets/club-chair.glb")
		if chair:
			add_child(chair)
			place_model(chair, spec)
			room_models.append(chair)

func refine_room_materials(node: Node) -> void:
	if node is MeshInstance3D:
		var mesh_node := node as MeshInstance3D
		for surface in range(mesh_node.mesh.get_surface_count()):
			var source := mesh_node.get_active_material(surface) as StandardMaterial3D
			if source: mesh_node.set_surface_override_material(surface, visual_materials.refine(source))
	for child in node.get_children():
		refine_room_materials(child)

func find_animation_player(node: Node) -> AnimationPlayer:
	if node is AnimationPlayer:
		return node as AnimationPlayer
	for child in node.get_children():
		var found := find_animation_player(child)
		if found:
			return found
	return null

func play_matching_animation(candidates: Array) -> void:
	if not animation_player:
		return
	for candidate in candidates:
		for available in animation_player.get_animation_list():
			if str(available).get_file().to_lower() == str(candidate).to_lower():
				if current_animation != str(available):
					animation_player.get_animation(available).loop_mode = Animation.LOOP_LINEAR
					animation_player.play(available, 0.4)
					current_animation = str(available)
				return

func build_environment() -> void:
	var world := WorldEnvironment.new()
	room_environment = world
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color("1d211f")
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_sky_contribution = 0.0
	env.ambient_light_color = Color("c2cbd1")
	env.ambient_light_energy = float(layout.get("ambient_energy", 0.36))
	env.reflected_light_source = Environment.REFLECTION_SOURCE_BG
	env.tonemap_mode = Environment.TONE_MAPPER_AGX
	env.tonemap_exposure = 1.4
	env.tonemap_white = 6.0
	if RenderingServer.get_current_rendering_method() == "forward_plus":
		env.sdfgi_enabled = bool(layout.get("sdfgi_enabled", false))
		env.sdfgi_cascades = 4
		env.sdfgi_min_cell_size = 0.12
		env.sdfgi_read_sky_light = false
		env.sdfgi_use_occlusion = true
		env.sdfgi_bounce_feedback = 0.45
		env.ssao_enabled = true
		env.ssao_radius = 0.4
		env.ssao_intensity = 1.1
		env.ssao_power = 1.25
		env.ssao_light_affect = 0.05
		env.ssil_enabled = true
		env.ssil_radius = 2.0
		env.ssil_intensity = 0.35
		env.glow_enabled = true
		env.glow_intensity = 0.18
		env.glow_bloom = 0.06
	world.environment = env
	add_child(world)
	for spec in layout.get("lights", []):
		var lamp := OmniLight3D.new()
		lamp.name = str(spec.get("name", "Practical"))
		lamp.position = vector(spec.get("position", []))
		lamp.light_color = Color(str(spec.get("color", "ffe0ac")))
		lamp.light_energy = float(spec.get("energy", 0.8))
		lamp.light_size = float(spec.get("size", 0.45))
		lamp.light_specular = float(spec.get("specular", 0.35))
		lamp.omni_range = float(spec.get("range", 4.0))
		lamp.omni_attenuation = 1.25
		lamp.shadow_enabled = bool(spec.get("shadow", false))
		lamp.shadow_bias = 0.04
		add_child(lamp)
	var window_fill := SpotLight3D.new()
	window_fill.name = "CoolEveningWindowFill"
	window_fill.position = Vector3(-4.3, 2.7, 2.8)
	window_fill.light_color = Color("b9cad0")
	window_fill.light_energy = 1.7
	window_fill.light_specular = 0.3
	window_fill.light_size = 1.0
	window_fill.shadow_enabled = true
	window_fill.spot_range = 11.0
	window_fill.spot_angle = 67.0
	window_fill.spot_attenuation = 0.8
	add_child(window_fill)
	window_fill.look_at(Vector3(0.0, 0.9, -1.5))
	# Interior probe captures the actual furnished room. The box projection
	# anchors brass, glass and polished walnut reflections to the room bounds.
	var probe := ReflectionProbe.new()
	probe.name = "WhiskeyRoomReflection"
	probe.position = Vector3(0.0, 1.8, 0.0)
	probe.size = Vector3(10.0, 3.6, 12.0)
	probe.interior = true
	probe.box_projection = true
	probe.enable_shadows = true
	probe.ambient_mode = ReflectionProbe.AMBIENT_ENVIRONMENT
	probe.intensity = 0.9
	probe.max_distance = 18.0
	probe.update_mode = ReflectionProbe.UPDATE_ONCE
	add_child(probe)

func build_artwork() -> void:
	var painting := MeshInstance3D.new()
	painting.name = "HighlandLochPainting"
	var canvas := QuadMesh.new()
	canvas.size = Vector2(2.10, 2.10 * 829.0 / 1897.0)
	painting.mesh = canvas
	painting.position = Vector3(0, 2.42, -5.65)
	var finish := StandardMaterial3D.new()
	finish.albedo_texture = visual_materials.texture("res://assets/pbr/highland-loch-painting.png")
	finish.roughness = 0.95
	finish.metallic_specular = 0.15
	finish.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	painting.material_override = finish
	add_child(painting)
	room_models.append(painting)

func build_camera_rig() -> void:
	xr_origin = XROrigin3D.new()
	xr_origin.name = "XROrigin"
	add_child(xr_origin)
	xr_camera = XRCamera3D.new()
	xr_camera.name = "Head"
	xr_camera.near = 0.06
	xr_camera.far = 60.0
	xr_origin.add_child(xr_camera)
	for hand in ["left_hand", "right_hand"]:
		var controller := XRController3D.new()
		controller.tracker = StringName(hand)
		controller.pose = &"aim"
		xr_origin.add_child(controller)
		controllers.append(controller)
		var grip := XRController3D.new()
		grip.tracker = StringName(hand)
		grip.pose = &"grip"
		xr_origin.add_child(grip)
		controller_grips.append(grip)
	xr_feedback = load("res://xr_feedback.gd").new()
	add_child(xr_feedback)
	xr_feedback.setup()
	camera = Camera3D.new()
	camera.name = "DesktopCamera"
	camera.fov = 65.0
	camera.near = 0.05
	camera.far = 60.0
	add_child(camera)
	var forced := OS.get_environment("HERMES_DESKTOP_PREVIEW") == "1" or validate_only or not capture_path.is_empty()
	if not forced and DisplayServer.get_name() != "headless":
		var interface := XRServer.find_interface("OpenXR")
		if interface and interface.initialize():
			xr_active = true
			get_viewport().use_xr = true
			xr_origin.position = Vector3(0, 0, 2.8)
			xr_camera.current = true
			DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	if not xr_active:
		camera.current = true
		set_view(starting_view)

func set_view(index: int) -> void:
	var viewpoints: Array = layout.get("viewpoints", DEFAULT_VIEWS)
	if viewpoints.is_empty():
		viewpoints = DEFAULT_VIEWS
	var view: Dictionary = viewpoints[clampi(index, 0, viewpoints.size() - 1)]
	view_name = str(view.get("name", "The room"))
	var pos := vector(view.get("position", []), Vector3(3.55, 1.7, 4.75))
	var target := vector(view.get("target", []), Vector3(0, 1, -2))
	if xr_active:
		xr_origin.rotation.y = atan2(pos.x - target.x, pos.z - target.z)
		# Place the tracked head, not the tracking origin, at the chosen spot.
		# This also works after room-scale steps away from the origin.
		var head := xr_camera.global_position
		xr_origin.global_position += Vector3(pos.x - head.x, 0.0, pos.z - head.z)
		xr_desk_view = index == 1
	else:
		camera.look_at_from_position(pos, target)
		walking_height = pos.y
	update_hud()

func serif_font() -> SystemFont:
	var font := SystemFont.new()
	font.font_names = PackedStringArray(["Georgia", "Liberation Serif", "DejaVu Serif"])
	return font

func label_text(text: String, size: int, color: Color = CREAM) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_color", color)
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return label

func panel_style(color: Color, border := Color("796343"), padding := 16) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.border_color = border
	style.set_border_width_all(1)
	style.set_corner_radius_all(4)
	style.content_margin_left = padding
	style.content_margin_right = padding
	style.content_margin_top = padding
	style.content_margin_bottom = padding
	return style

func desk_separator() -> ColorRect:
	var line := ColorRect.new()
	line.custom_minimum_size.y = 3.0
	line.color = Color("605440")
	line.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return line

func build_desk_display() -> void:
	if OS.get_environment("HERMES_OFFICE_INTEGRATION") != "acp":
		build_live_desk_monitor()
		return
	var spec: Dictionary = layout.get("desk_display", {"position": [-0.25, 1.10, -2.36], "rotation_degrees": [0, 0, 0]})
	screen_root = Node3D.new()
	screen_root.name = "DeskCompanionDisplay"
	place_model(screen_root, spec)
	add_child(screen_root)
	var screen_size := Vector2(float(spec.get("width", 1.15)), float(spec.get("height", 0.65)))
	var viewport := SubViewport.new()
	viewport.name = "TaskDisplayViewport"
	viewport.size = Vector2i(1280, 800)
	viewport.transparent_bg = false
	viewport.disable_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	screen_root.add_child(viewport)
	var background := ColorRect.new()
	background.color = INK
	background.size = Vector2(1280, 800)
	viewport.add_child(background)
	var margin := MarginContainer.new()
	margin.position = Vector2(50, 36)
	margin.size = Vector2(1180, 728)
	viewport.add_child(margin)
	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation", 12)
	margin.add_child(content)
	var heading := label_text("HERMES  /  YOUR WORKSPACE", 25, GOLD)
	content.add_child(heading)
	var status := label_text("Hermes offline", 45)
	status.add_theme_font_override("font", serif_font())
	content.add_child(status)
	screen_labels["agent"] = status
	var task := label_text("No agent state available.", 27, MUTED)
	task.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	task.custom_minimum_size.y = 65
	task.max_lines_visible = 2
	content.add_child(task)
	screen_labels["task"] = task
	content.add_child(desk_separator())
	var board_state := label_text("Task board unavailable", 22, MUTED)
	content.add_child(board_state)
	screen_labels["board"] = board_state
	var columns := HBoxContainer.new()
	columns.add_theme_constant_override("separation", 25)
	columns.custom_minimum_size.y = 205
	content.add_child(columns)
	for column in ["TODO", "RUNNING", "REVIEW", "DONE"]:
		var stack := VBoxContainer.new()
		stack.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		columns.add_child(stack)
		stack.add_child(label_text(str(column), 22, GOLD))
		var tasks := label_text("—", 25)
		tasks.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		tasks.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		stack.add_child(tasks)
		screen_labels[column] = tasks
	content.add_child(desk_separator())
	var voice := label_text("Voice offline", 27, GOLD)
	content.add_child(voice)
	screen_labels["voice"] = voice
	var message := label_text("The local voice bridge has not reported a state.", 25, MUTED)
	message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	message.max_lines_visible = 2
	content.add_child(message)
	screen_labels["message"] = message
	var quad := QuadMesh.new()
	quad.size = screen_size
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_texture = viewport.get_texture()
	material.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS
	material.cull_mode = BaseMaterial3D.CULL_DISABLED
	quad.material = material
	var surface := MeshInstance3D.new()
	surface.name = "DisplaySurface"
	surface.mesh = quad
	surface.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	screen_root.add_child(surface)
	var body := StaticBody3D.new()
	body.add_to_group("voice_display")
	screen_root.add_child(body)
	var collision := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = Vector3(screen_size.x, screen_size.y, 0.035)
	collision.shape = shape
	body.add_child(collision)

func build_live_desk_monitor() -> void:
	var spec: Dictionary = layout.get("desk_display", {})
	screen_root = Node3D.new()
	screen_root.name = "LiveHermesMonitor"
	place_model(screen_root, spec)
	add_child(screen_root)
	var size := Vector2(float(spec.get("width", 1.15)), float(spec.get("height", 0.65)))
	desk_aperture = size
	desk_fallback = SubViewport.new()
	desk_fallback.size = Vector2i(1280, 800)
	desk_fallback.disable_3d = true
	desk_fallback.render_target_update_mode = SubViewport.UPDATE_ONCE
	screen_root.add_child(desk_fallback)
	var backdrop := ColorRect.new()
	backdrop.color = INK
	backdrop.size = Vector2(1280, 800)
	desk_fallback.add_child(backdrop)
	desk_connection = label_text("Connecting to Hermes…\n\nSelect the monitor to work", 32, CREAM)
	desk_connection.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	desk_connection.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	desk_connection.size = Vector2(1200, 720)
	desk_connection.position = Vector2(40, 40)
	desk_connection.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	desk_fallback.add_child(desk_connection)
	desk_material = StandardMaterial3D.new()
	desk_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	desk_material.albedo_texture = desk_fallback.get_texture()
	desk_material.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR
	var surface := MeshInstance3D.new()
	var quad := QuadMesh.new()
	desk_image_quad = quad
	quad.size = Vector2(minf(size.x, size.y * 1.6), minf(size.y, size.x / 1.6))
	surface.mesh = quad
	surface.material_override = desk_material
	surface.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	screen_root.add_child(surface)
	var surround := MeshInstance3D.new()
	var surround_quad := QuadMesh.new()
	surround_quad.size = size
	surround.mesh = surround_quad
	surround.position.z = -0.001
	var surround_material := StandardMaterial3D.new()
	surround_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	surround_material.albedo_color = Color("080808")
	surround.material_override = surround_material
	surround.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	screen_root.add_child(surround)
	var body := StaticBody3D.new()
	body.add_to_group("voice_display")
	screen_root.add_child(body)
	var collision := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = Vector3(size.x, size.y, 0.035)
	collision.shape = shape
	body.add_child(collision)

func update_desk_monitor() -> void:
	if not desk_material or not desktop_surface: return
	if desktop_surface.connected and desktop_surface.texture:
		desk_material.albedo_texture = desktop_surface.texture
		var aspect: float = float(desktop_surface.frame_size.x) / float(desktop_surface.frame_size.y)
		desk_image_quad.size = Vector2(minf(desk_aperture.x, desk_aperture.y * aspect), minf(desk_aperture.y, desk_aperture.x / aspect))
	else:
		desk_material.albedo_texture = desk_fallback.get_texture()
		var message: String = desktop_surface.reason + "\n\nSelect the monitor to work"
		if desk_connection.text != message:
			desk_connection.text = message
			desk_fallback.render_target_update_mode = SubViewport.UPDATE_ONCE

func build_desktop_hud() -> void:
	hud = CanvasLayer.new()
	hud.name = "DesktopInterface"
	hud.visible = not xr_active
	add_child(hud)
	var root := Control.new()
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	hud.add_child(root)
	var brand := VBoxContainer.new()
	brand.position = Vector2(38, 32)
	root.add_child(brand)
	brand.add_child(label_text("H E R M E S", 15, GOLD))
	var title := label_text("The Whiskey Room", 35)
	title.add_theme_font_override("font", serif_font())
	title.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.65))
	title.add_theme_constant_override("shadow_offset_y", 2)
	brand.add_child(title)
	var location := label_text(view_name, 14, MUTED)
	brand.add_child(location)
	desktop_labels["view"] = location
	var badge := PanelContainer.new()
	badge.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	badge.position = Vector2(-353, 32)
	badge.custom_minimum_size = Vector2(315, 70)
	badge.add_theme_stylebox_override("panel", panel_style(Color(0.07, 0.09, 0.08, 0.92)))
	root.add_child(badge)
	var status_stack := VBoxContainer.new()
	badge.add_child(status_stack)
	var status := label_text(agent_title, 16)
	status_stack.add_child(status)
	desktop_labels["agent"] = status
	var voice := label_text(voice_title, 13, MUTED)
	status_stack.add_child(voice)
	desktop_labels["voice"] = voice
	var controls := VBoxContainer.new()
	controls.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_LEFT)
	controls.position = Vector2(38, -79)
	root.add_child(controls)
	room_control_hint = label_text("WASD  Walk     Mouse  Look     F  Desk     1–4  Views", 14)
	controls.add_child(room_control_hint)
	controls.add_child(label_text("Click  Look around     Esc  Release     Tab  Hermes     F9  Tool wheel", 13, MUTED))
	var actions := HBoxContainer.new()
	actions.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_RIGHT)
	actions.position = Vector2(-535, -82)
	actions.custom_minimum_size = Vector2(497, 48)
	root.add_child(actions)
	var work_button := Button.new()
	work_button.text = "Work with Hermes"
	work_button.custom_minimum_size = Vector2(174, 48)
	work_button.pressed.connect(func() -> void: show_workbench(true))
	actions.add_child(work_button)
	voice_button = Button.new()
	voice_button.text = "Speak to Hermes   ·   Space"
	voice_button.custom_minimum_size = Vector2(315, 48)
	voice_button.add_theme_font_size_override("font_size", 16)
	voice_button.add_theme_color_override("font_color", CREAM)
	voice_button.add_theme_stylebox_override("normal", panel_style(Color("243027"), GOLD, 12))
	voice_button.add_theme_stylebox_override("hover", panel_style(Color("344437"), CREAM, 12))
	voice_button.add_theme_stylebox_override("pressed", panel_style(Color("17241d"), GOLD, 12))
	voice_button.pressed.connect(request_voice_turn)
	actions.add_child(voice_button)
	details_panel = PanelContainer.new()
	details_panel.set_anchors_and_offsets_preset(Control.PRESET_CENTER_RIGHT)
	details_panel.position = Vector2(-433, -200)
	details_panel.custom_minimum_size = Vector2(395, 400)
	details_panel.add_theme_stylebox_override("panel", panel_style(Color(0.065, 0.08, 0.067, 0.97), GOLD, 22))
	details_panel.visible = false
	root.add_child(details_panel)
	var details := VBoxContainer.new()
	details.add_theme_constant_override("separation", 13)
	details_panel.add_child(details)
	details.add_child(label_text("THE WORK AT HAND", 15, GOLD))
	var current_task := label_text(agent_task, 17)
	current_task.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	current_task.custom_minimum_size.x = 350
	details.add_child(current_task)
	desktop_labels["task"] = current_task
	details.add_child(HSeparator.new())
	var board := label_text(kanban_summary, 13, MUTED)
	details.add_child(board)
	desktop_labels["board"] = board
	var task_list := label_text("", 15)
	task_list.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	task_list.custom_minimum_size.x = 350
	details.add_child(task_list)
	desktop_labels["tasks"] = task_list
	details.add_child(HSeparator.new())
	var message := label_text(voice_message, 14, MUTED)
	message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	message.custom_minimum_size.x = 350
	details.add_child(message)
	desktop_labels["message"] = message

func build_workbench() -> void:
	if OS.get_environment("HERMES_OFFICE_INTEGRATION") != "acp":
		build_existing_desktop()
		return
	office_client = load("res://office_client.gd").new()
	office_client.state_changed.connect(on_office_state)
	if xr_active:
		hand_pointer = load("res://hand_pointer.gd").new()
		add_child(hand_pointer)
		xr_panel = load("res://xr_workbench.gd").new()
		add_child(xr_panel)
		xr_panel.setup(xr_camera)
		workbench = xr_panel.widget
	else:
		workbench = load("res://workbench.gd").new()
		hud.add_child(workbench)
		workbench.setup()
		workbench.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		workbench.offset_left = 95
		workbench.offset_right = -95
		workbench.offset_top = 130
		workbench.offset_bottom = -108
		workbench.visible = false
	workbench.message_submitted.connect(send_office_message)
	workbench.session_selected.connect(func(id: String) -> void: office_command("session.select", {"id": id}))
	workbench.new_session_requested.connect(func() -> void: office_command("session.new"))
	workbench.voice_requested.connect(request_voice_turn)
	workbench.close_requested.connect(func() -> void: show_workbench(false))
	workbench.refresh_requested.connect(func() -> void: office_command("connection.refresh"))
	workbench.cancel_requested.connect(func() -> void: office_command("turn.cancel"))
	workbench.permission_replied.connect(func(id: String, option: String) -> void: office_command("permission.reply", {"id": id, "option_id": option}))
	workbench.share_view_requested.connect(share_office_view)
	workbench.passthrough_requested.connect(set_passthrough)
	if FileAccess.file_exists("user://office-draft.txt"):
		last_draft = FileAccess.get_file_as_string("user://office-draft.txt")
		workbench.update_state({"pending_message": last_draft})
	add_child(office_client)
	if open_workbench_on_start:
		show_workbench(true)

func build_existing_desktop() -> void:
	desktop_surface = load("res://desktop_surface.gd").new()
	add_child(desktop_surface)
	desktop_surface.setup(OS.get_environment("HERMES_DESKTOP_IPC_DIR"), xr_camera if xr_active else camera)
	desktop_surface.set_mirror_enabled(true)
	desktop_surface.frame_updated.connect(update_desk_monitor)
	desktop_surface.connection_changed.connect(func(_connected: bool, _reason: String) -> void: update_desk_monitor())
	var spatial_preview := OS.get_environment("HERMES_OFFICE_SPATIAL_PREVIEW") == "1"
	desktop_surface.set_spatial_visible(xr_active or spatial_preview)
	desktop_surface.panel_closed.connect(func() -> void:
		desktop_grab = false
		desktop_tracking_source = ""
		if desktop_preview: desktop_preview.hide()
	)
	desktop_surface.state_changed.connect(func(_state: Dictionary) -> void: update_hud())
	desktop_surface.command_failed.connect(func(message: String) -> void:
		local_ui_error = message
		update_hud()
	)
	desktop_surface.command_message.connect(func(message: String) -> void:
		local_ui_error = message
		update_hud()
	)
	desktop_surface.share_view_requested.connect(share_office_view)
	desktop_surface.passthrough_requested.connect(func() -> void: set_passthrough(not passthrough_active))
	wrist_controls = load("res://wrist_controls.gd").new()
	add_child(wrist_controls)
	wrist_controls.setup(xr_camera if xr_active else camera)
	wrist_controls.action_requested.connect(handle_wrist_action)
	office_windows = load("res://office_windows.gd").new()
	add_child(office_windows)
	office_windows.setup(desktop_surface, xr_camera if xr_active else camera, xr_active or spatial_preview)
	office_windows.sources_changed.connect(wrist_controls.set_sources)
	office_windows.control_input.connect(_input)
	office_windows.menu_open = func() -> bool: return wrist_controls.dial.is_open()
	office_windows.menu_capturing = func() -> bool: return wrist_controls.is_capturing()
	wrist_controls.set_sources(office_windows.sources.values())
	office_windows.focus_changed.connect(func(_id: String) -> void:
		desktop_grab = false
		desktop_tracking_source = ""
	)
	if xr_active:
		hand_pointer = load("res://hand_pointer.gd").new()
		add_child(hand_pointer)
		left_hand_pointer = load("res://hand_pointer.gd").new()
		left_hand_pointer.tracker_path = &"/user/hand_tracker/left"
		add_child(left_hand_pointer)
	if not xr_active and not spatial_preview and not office_windows:
		desktop_preview = PanelContainer.new()
		hud.add_child(desktop_preview)
		desktop_preview.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		desktop_preview.offset_left = 55
		desktop_preview.offset_right = -55
		desktop_preview.offset_top = 125
		desktop_preview.offset_bottom = -108
		var stack := VBoxContainer.new()
		desktop_preview.add_child(stack)
		var tools := HBoxContainer.new()
		tools.add_theme_constant_override("separation", 12)
		stack.add_child(tools)
		for item in [["Desktop", func() -> void: desktop_surface.send_command("focus_desktop", {})], ["Hermes HUD", toggle_desktop_hud], ["TUI", func() -> void: desktop_surface.send_command("launch_tui", {})], ["Share office view", share_office_view], ["Return to office · F10", func() -> void: show_workbench(false)]]:
			var button := Button.new()
			button.text = str(item[0])
			button.custom_minimum_size.y = 38
			button.focus_mode = Control.FOCUS_NONE
			button.pressed.connect(item[1])
			tools.add_child(button)
		var surface_status := label_text("Starting Hermes Desktop…", 14, MUTED)
		stack.add_child(surface_status)
		desktop_labels["surface_status"] = surface_status
		var preview: TextureRect = desktop_surface.create_preview()
		preview.size_flags_vertical = Control.SIZE_EXPAND_FILL
		preview.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		stack.add_child(preview)
		desktop_preview.hide()
	if voice_button:
		voice_button.text = "Dictate a draft · Space"
	if open_workbench_on_start: show_workbench(true)

func toggle_desktop_hud() -> void:
	if not desktop_surface: return
	show_workbench(true)
	for key in ["Control_L", "Shift_L", "h"]:
		desktop_surface.send_command("key", {"keysym": key, "pressed": true})
	for key in ["h", "Shift_L", "Control_L"]:
		desktop_surface.send_command("key", {"keysym": key, "pressed": false})

func handle_wrist_action(action: String) -> void:
	if control_tips and action.begins_with("tutorial_"):
		var topic := action.trim_prefix("tutorial_")
		if topic in ["on", "off"]: control_tips.set_tips_enabled(topic == "on")
		else: control_tips.request_tip(topic)
		return
	if hologram and action.begins_with("hologram_"):
		if office_windows: office_windows.release_all()
		match action:
			"hologram_next": hologram.select_next(1)
			"hologram_previous": hologram.select_next(-1)
			"hologram_window": project_active_window()
			"hologram_rotate": hologram.turning = not hologram.turning
			"hologram_larger": hologram.resize(1.15)
			"hologram_smaller": hologram.resize(0.87)
			"hologram_readable": hologram.set_readable(not hologram.readable)
			"hologram_clear": hologram.clear()
			"hologram_source": hologram.source_requested.emit()
			"hologram_file":
				if not xr_active: hologram.choose_file()
			"hologram_view": set_view(8)
			"hologram_reset":
				hologram.resize(1.0 / hologram.size_factor)
				hologram.turning = false
		return
	if fabricator and action.begins_with("fabricate_"):
		match action:
			"fabricate_image": fabricator.next_image()
			"fabricate_render": fabricator.render_image()
			"fabricate_quality": fabricator.toggle_quality()
			"fabricate_ready": fabricator.next_output()
			"fabricate_return": fabricator.return_held()
		return
	if not desktop_surface: return
	if office_windows and action.begins_with("window_"):
		office_windows.release_all()
		if action.begins_with("window_source_"):
			office_windows.open_window(action.trim_prefix("window_source_"))
		else:
			match action:
				"window_next": office_windows.cycle(1)
				"window_previous": office_windows.cycle(-1)
				"window_arrange": office_windows.arrange()
				"window_hide": office_windows.close_window()
				"window_reopen": office_windows.reopen()
				"window_disconnect": office_windows.disconnect_window()
				"window_keyboard":
					if office_windows.active(): office_windows.active().set_keyboard_visible(true)
				"window_larger", "window_smaller":
					if office_windows.active():
						var surface = office_windows.active()
						surface.set_panel_scale(surface.get_panel_scale() * (1.15 if action == "window_larger" else 0.87))
				"window_recenter":
					if office_windows.active(): office_windows.active().open_panel(true)
		return
	desktop_surface.release_input()
	if action.begins_with("nav_"):
		show_workbench(true)
		desktop_surface.send_command("navigate_hermes", {"destination": action.trim_prefix("nav_")})
		return
	match action:
		"parts_next", "parts_previous":
			open_assembly_review(1 if action == "parts_next" else -1)
		"parts_explode", "parts_assemble":
			if not assembly_review.is_open(): open_assembly_review()
			assembly_review.set_exploded(action == "parts_explode")
		"parts_close": assembly_review.close_review()
		"desktop", "recenter":
			show_workbench(true)
			if action == "desktop": desktop_surface.send_command("focus_desktop", {})
		"hud": toggle_desktop_hud()
		"voice": request_voice_turn()
		"voice_call":
			show_workbench(true)
			desktop_surface.send_command("navigate_hermes", {"destination": "voice"})
		"voice_stop":
			show_workbench(true)
			desktop_surface.send_command("navigate_hermes", {"destination": "end_voice"})
		"tui":
			show_workbench(true)
			desktop_surface.send_command("launch_tui", {})
		"keyboard":
			show_workbench(true)
			desktop_surface.set_keyboard_visible(true)
		"larger", "smaller":
			show_workbench(true)
			desktop_surface.scale_panel(1.15 if action == "larger" else 1.0 / 1.15)
		"share": share_office_view()
		"passthrough": set_passthrough(not passthrough_active)
		"hide_panel": show_workbench(false)
		"view_desk", "view_fire", "view_bar", "view_arrival":
			show_workbench(false)
			set_view({"view_desk": 1, "view_fire": 2, "view_bar": 3, "view_arrival": 0}[action])

func workbench_open() -> bool:
	if office_windows: return office_windows.any_open()
	if desktop_surface: return desktop_surface.is_open()
	return xr_panel.is_open() if xr_panel else workbench != null and workbench.visible

func show_workbench(opened: bool) -> void:
	if opened and assembly_review and assembly_review.is_open(): assembly_review.close_review()
	if desktop_surface:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
		if office_windows:
			if opened: office_windows.open_window("hermes")
			else: office_windows.close_window()
		elif opened: desktop_surface.open_panel()
		else:
			desktop_surface.close_panel()
			desktop_grab = false
			desktop_tracking_source = ""
		if desktop_preview:
			desktop_preview.visible = opened
			if opened: desktop_surface.preview_control.grab_focus()
		if details_panel: details_panel.visible = false
		return
	if not workbench: return
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	if xr_panel:
		if opened: xr_panel.open_panel()
		else: xr_panel.close_panel()
	else:
		workbench.visible = opened
	if opened and not xr_active: workbench.focus_compose()
	if details_panel: details_panel.visible = false
	save_office_draft()

func build_assembly_review() -> void:
	if room_models.is_empty() or not FileAccess.file_exists("res://office-assemblies.json"): return
	assembly_review = load("res://office_assembly_review.gd").new()
	add_child(assembly_review)
	assembly_review.setup(room_models[0], func(path: String) -> Node3D:
		var model := model_instance(path)
		if model: refine_room_materials(model)
		return model
	)
	assembly_review.selection_changed.connect(func(spec: Dictionary) -> void:
		if screen_root: screen_root.visible = not passthrough_active and str(spec.id) not in ["desk", "monitor"]
		if room_control_hint: room_control_hint.text = "← →  Choose furniture     Space  Separate / Reassemble     Esc  Finish"
		if xr_active: return
		assembly_review._label.hide()
		view_name = str(spec.name) + " · Parts review"
		if desktop_labels.has("view"): desktop_labels["view"].text = view_name
		var low: Array = spec.bounds.min
		var high: Array = spec.bounds.max
		var center: Vector3 = Vector3((low[0]+high[0])*0.5, (low[1]+high[1])*0.5, (low[2]+high[2])*0.5) + assembly_review.review_offset
		var extent := Vector3(high[0]-low[0], high[1]-low[1], high[2]-low[2])
		var approach := Vector3(-center.x * 0.6, 0.4, maxf(0.8, -center.z)).normalized()
		if extent.y < extent.x * 0.4: approach = Vector3(-center.x * 0.2, 1.1, 1.3).normalized()
		camera.position = center + approach * maxf(0.7, extent.length() * 1.15)
		camera.look_at(center, Vector3.UP)
	)
	assembly_review.review_closed.connect(func() -> void:
		view_name = review_previous_view
		if screen_root: screen_root.visible = not passthrough_active
		if room_control_hint: room_control_hint.text = "WASD  Walk     Mouse  Look     F  Desk     1–4  Views"
		if desktop_labels.has("view"): desktop_labels["view"].text = view_name
		if review_camera_saved and not xr_active:
			camera.transform = review_camera_transform
		review_camera_saved = false
	)

func open_assembly_review(direction := 1) -> void:
	if not assembly_review: return
	show_workbench(false)
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	if not assembly_review.is_open(): review_previous_view = view_name
	if not assembly_review.is_open() and not xr_active:
		review_camera_transform = camera.transform
		review_camera_saved = true
	assembly_review.select_next(direction)

func preview_assembly() -> void:
	if not assembly_review: return
	var requested := OS.get_environment("HERMES_OFFICE_PARTS_ASSEMBLY")
	for i in assembly_review.choices.size():
		if str(assembly_review.choices[i].id) == requested: assembly_review.selected = i - 1
	open_assembly_review()
	assembly_review.set_exploded(OS.get_environment("HERMES_OFFICE_PARTS_EXPLODED") == "1")

func office_command(method: String, params: Dictionary = {}) -> String:
	if not office_client: return ""
	local_ui_error = ""
	var id: String = office_client.send_command(method, params)
	if id.is_empty():
		local_ui_error = "Hermes is not ready for that action. Open Connection for details."
	elif method in ["message.send", "voice.record", "session.new", "session.select"]:
		var pending: Dictionary = office_client.state.duplicate(true)
		pending["busy"] = true
		workbench.update_state(pending)
	return id

var pending_share_image := ""

func send_office_message(text: String) -> void:
	var params := {"text": text}
	if not pending_share_image.is_empty(): params["image_name"] = pending_share_image
	pending_message_id = office_command("message.send", params)
	if not pending_message_id.is_empty(): pending_share_image = ""
	if pending_message_id.is_empty(): workbench.acknowledge_message(false)

func on_office_state(state: Dictionary) -> void:
	if not workbench: return
	var view: Dictionary = state.duplicate(true)
	view["tasks"] = grouped_tasks
	view["voice_title"] = str(state.get("voice_status", "Microphone idle"))
	view["voice_message"] = str(state.get("voice_message", "Speak records one turn from the enabled Quest microphone."))
	view["controls_summary"] = "Quest: left stick moves; right stick turns. A focuses Hermes; B backs out or hides the active window; X opens window overview; Y opens quick controls. Trigger selects, grip grabs a pointed target. In menus, use right stick or wrist rotation, then hold and release trigger/pinch. Dictate records a draft; Send requests a reply."
	view["senses_summary"] = "Virtual view: Share view sends one headset-aligned office frame into this conversation. Microphone: one explicit voice turn at a time. Physical cameras: not exposed by this WiVRn connection. Passthrough can display your room only when the runtime supports it; it does not grant Hermes camera access."
	if not local_ui_error.is_empty(): view["error"] = local_ui_error
	var ack: Dictionary = state.get("last_command", {})
	if not pending_message_id.is_empty() and str(ack.get("id", "")) == pending_message_id:
		var accepted := str(ack.get("status", "")) in ["accepted", "completed"]
		workbench.acknowledge_message(accepted)
		pending_message_id = ""
	if str(state.get("connection", {}).get("status", "offline")) in ["offline", "incompatible"] and not pending_message_id.is_empty():
		workbench.acknowledge_message(false)
		pending_message_id = ""
	workbench.update_state(view)
	update_hud()

func save_office_draft() -> void:
	if not workbench: return
	var draft: String = workbench.draft_text()
	if draft == last_draft: return
	var file := FileAccess.open("user://office-draft.txt", FileAccess.WRITE)
	if file:
		file.store_string(draft)
		file.close()
		last_draft = draft

func share_office_view() -> void:
	if sharing_frame: return
	if not desktop_surface and (not office_client or bool(office_client.state.get("busy", false))): return
	if desktop_surface and not desktop_surface.connected: return
	if passthrough_active:
		local_ui_error = "Physical camera images are not exposed by the current WiVRn connection. Return to the office to share its virtual view."
		if office_client: on_office_state(office_client.state)
		update_hud()
		return
	var caps: Dictionary = office_client.state.get("connection", {}).get("capabilities", {}) if office_client else {"images": true}
	if not bool(caps.get("images", false)):
		local_ui_error = "This Hermes connection does not accept images."
		on_office_state(office_client.state)
		return
	sharing_frame = true
	var capture := SubViewport.new()
	capture.size = Vector2i(1024, 768)
	capture.world_3d = get_world_3d()
	capture.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(capture)
	var eye := Camera3D.new()
	capture.add_child(eye)
	eye.global_transform = xr_camera.global_transform if xr_active else camera.global_transform
	eye.fov = 85.0 if xr_active else camera.fov
	eye.near = 0.05
	eye.current = true
	# Explicit Share view includes visible work surfaces, as the user sees them.
	# The capture is never displayed inside this viewport, so no feedback loop.
	await get_tree().process_frame
	await RenderingServer.frame_post_draw
	var frame := capture.get_texture().get_image()
	var name := "office-view-%s.png" % Time.get_ticks_usec()
	var directory: String = OS.get_environment("HERMES_DESKTOP_IPC_DIR").path_join("captures") if desktop_surface else office_client.ipc_dir.path_join("captures")
	var saved := ERR_CANT_CREATE
	if frame and not frame.is_empty() and DirAccess.dir_exists_absolute(directory):
		saved = frame.save_png(directory.path_join(name))
	capture.queue_free()
	sharing_frame = false
	if saved != OK:
		local_ui_error = "The virtual view could not be captured. No image was sent."
		if office_client: on_office_state(office_client.state)
		return
	if desktop_surface:
		var queued: String = desktop_surface.send_command("clipboard_image", {"image_name": name})
		if not queued.is_empty(): local_ui_error = "Office image queued for the focused Hermes composer. Review the attachment before sending."
		update_hud()
		return
	pending_share_image = name
	local_ui_error = "View attached. Send a message when you want Hermes to respond."
	on_office_state(office_client.state)

func set_passthrough(enabled: bool) -> void:
	var runtime := XRServer.find_interface("OpenXR")
	var supported := runtime != null and runtime.is_initialized()
	var mode := XRInterface.XR_ENV_BLEND_MODE_ALPHA_BLEND if enabled else XRInterface.XR_ENV_BLEND_MODE_OPAQUE
	if supported: supported = mode in runtime.get_supported_environment_blend_modes() and runtime.set_environment_blend_mode(mode)
	if not supported:
		local_ui_error = "Passthrough is unavailable in this runtime. The current view remains unchanged."
		if office_client: on_office_state(office_client.state)
		update_hud()
		return
	get_viewport().transparent_bg = enabled
	passthrough_active = enabled
	for model in room_models: model.visible = not enabled
	if screen_root: screen_root.visible = not enabled
	if room_environment: room_environment.environment.background_mode = Environment.BG_CLEAR_COLOR if enabled else Environment.BG_COLOR

func board_column(status: String) -> String:
	match status.to_lower():
		"running", "working", "in_progress", "in-progress": return "RUNNING"
		"review", "blocked", "waiting": return "REVIEW"
		"done", "complete", "completed", "archived": return "DONE"
		_: return "TODO"

func refresh_agent_state() -> void:
	agent_snapshot = {}
	agent_status = "offline"
	agent_title = "Hermes offline"
	agent_task = "No agent state available."
	var parsed: Variant = read_json(state_path("agents"))
	if parsed is not Array or parsed.is_empty():
		return
	# A different named agent is never silently relabeled as Hermes.
	for candidate in parsed:
		if candidate is Dictionary and str(candidate.get("id", "")).to_lower() in ["hermes", "orchestrator"]:
			agent_snapshot = candidate
			break
	if agent_snapshot.is_empty():
		agent_task = "Hermes is not present in the agent snapshot."
		return
	agent_status = str(agent_snapshot.get("status", "unknown")).to_lower()
	agent_task = str(agent_snapshot.get("task", "No current task reported.")).left(240)
	if file_age(state_path("agents")) > AGENT_MAX_AGE:
		agent_title = "Hermes state out of date"
		agent_status = "stale"
		agent_task = "Last task: " + agent_task
		return
	agent_title = "Hermes · " + agent_status.replace("_", " ")
	if agent_status == "offline":
		agent_title = "Hermes offline"

func refresh_kanban() -> void:
	grouped_tasks = {"TODO": [], "RUNNING": [], "REVIEW": [], "DONE": []}
	kanban_summary = "Task board unavailable"
	var parsed: Variant = read_json(state_path("kanban"))
	if parsed is not Array:
		return
	var count := 0
	for entry in parsed:
		if entry is not Dictionary:
			continue
		var status := str(entry.get("status", entry.get("column", "todo")))
		var title := str(entry.get("title", entry.get("name", entry.get("task", "Untitled task"))))
		grouped_tasks[board_column(status)].append(title.left(120))
		count += 1
	var age := file_age(state_path("kanban"))
	kanban_summary = "%d tasks · snapshot updated %s" % [count, age_label(age)]
	if age > KANBAN_MAX_AGE:
		kanban_summary = "%d tasks · board snapshot out of date" % count

func age_label(age: float) -> String:
	if age < 5: return "just now"
	if age < 60: return "%ds ago" % int(age)
	if age < 3600: return "%dm ago" % int(age / 60.0)
	if age < 86400: return "%dh ago" % int(age / 3600.0)
	return "%dd ago" % int(age / 86400.0)

func refresh_voice_state() -> void:
	voice_snapshot = {}
	voice_title = "Voice offline"
	voice_message = "The local voice bridge has not reported a state."
	var parsed: Variant = read_json(state_path("voice"))
	if parsed is Dictionary:
		voice_snapshot = parsed
		var status := str(parsed.get("status", "unknown")).to_lower()
		var age := file_age(state_path("voice"))
		voice_title = "Voice · " + status
		voice_message = str(parsed.get("message", "No voice message reported.")).left(240)
		# The existing bridge does not heartbeat while ready. Report the age;
		# never claim that an old snapshot proves the process is still running.
		if age > 120.0:
			voice_title = "Voice unverified · last report: " + status
			voice_message = "Last update %s. %s" % [age_label(age), voice_message]
		if request_pending and float(parsed.get("updated", 0)) >= request_stamp:
			request_pending = false
	if request_pending:
		if elapsed - last_request_tick < 12.0:
			voice_title = "Voice request sent"
			voice_message = "Waiting for the local bridge to acknowledge."
		else:
			request_pending = false
			voice_title = "Voice did not acknowledge"
			voice_message = "The request was written, but the bridge did not report a new state."

func refresh_snapshots() -> void:
	refresh_agent_state()
	refresh_kanban()
	refresh_voice_state()
	update_hud()

func update_hud() -> void:
	var shown_agent := agent_title
	var shown_voice := voice_title
	var shown_task := agent_task
	var shown_voice_message := voice_message
	if desktop_surface:
		shown_agent = "Hermes Desktop" if desktop_surface.connected else "Hermes Desktop · connecting"
		shown_task = desktop_surface.reason if not desktop_surface.connected else "Your existing Hermes app, with its conversations, tools and settings."
		shown_voice = "Voice in Hermes"
		shown_voice_message = "Use the microphone in Hermes. HUD shares desktop context; Share office view attaches one virtual scene image."
		if desktop_labels.has("surface_status"):
			desktop_labels["surface_status"].text = local_ui_error if not local_ui_error.is_empty() else ("Your existing Hermes app · F10 returns to the room" if desktop_surface.connected else desktop_surface.reason)
	elif office_client:
		var state: Dictionary = office_client.state
		var connection: Dictionary = state.get("connection", {})
		shown_agent = "Hermes · working" if bool(state.get("busy", false)) else str(connection.get("label", "Connecting to Hermes"))
		shown_voice = "Mic · " + str(state.get("voice_status", "idle"))
		shown_voice_message = str(state.get("voice_message", "Speak records one turn. Share view sends one virtual office frame."))
		shown_task = "Open Work with Hermes to begin a conversation."
		var conversation: Array = state.get("messages", [])
		for index in range(conversation.size() - 1, -1, -1):
			if conversation[index] is Dictionary and conversation[index].get("role", "") == "user":
				shown_task = str(conversation[index].get("content", "")).left(240)
				break
	for labels in [screen_labels, desktop_labels]:
		if labels.has("agent"): labels["agent"].text = shown_agent
		if labels.has("task"): labels["task"].text = shown_task
		if labels.has("board"): labels["board"].text = kanban_summary
		if labels.has("voice"): labels["voice"].text = shown_voice
		if labels.has("message"): labels["message"].text = shown_voice_message
	if desktop_labels.has("view"):
		desktop_labels["view"].text = view_name
	var expanded: Array[String] = []
	for column in ["TODO", "RUNNING", "REVIEW", "DONE"]:
		var tasks: Array = grouped_tasks[column]
		var short_lines: Array[String] = []
		for task in tasks.slice(0, 2):
			short_lines.append("• " + str(task).left(58))
		if tasks.size() > 2:
			short_lines.append("+ %d more" % (tasks.size() - 2))
		if screen_labels.has(column):
			screen_labels[column].text = "—" if short_lines.is_empty() else "\n".join(short_lines)
		if not tasks.is_empty():
			expanded.append(str(column) + "  ·  " + str(tasks.size()))
			for task in tasks.slice(0, 2):
				expanded.append("  " + str(task).left(75))
	if desktop_labels.has("tasks"):
		desktop_labels["tasks"].text = "No tasks in this snapshot." if expanded.is_empty() and kanban_summary != "Task board unavailable" else "\n".join(expanded)
	if voice_button:
		if desktop_surface:
			voice_button.disabled = not desktop_surface.connected
		elif office_client:
			voice_button.disabled = bool(office_client.state.get("busy", false)) or not bool(office_client.state.get("connection", {}).get("capabilities", {}).get("voice", false)) or str(office_client.state.get("selected_session", "")).is_empty()
		else:
			voice_button.disabled = request_pending or str(voice_snapshot.get("status", "")).to_lower() in BUSY_VOICE
		voice_button.tooltip_text = shown_voice_message

func request_voice_turn() -> void:
	if desktop_surface:
		show_workbench(true)
		desktop_surface.send_command("navigate_hermes", {"destination": "dictate"})
		return
	if office_client:
		office_command("voice.record")
		return
	if elapsed - last_request_tick < 1.0 or request_pending:
		return
	if str(voice_snapshot.get("status", "")).to_lower() in BUSY_VOICE:
		return
	if voice_snapshot.is_empty() or not DirAccess.dir_exists_absolute(state_dir):
		voice_title = "Voice offline"
		voice_message = "The local voice bridge is unavailable."
		update_hud()
		return
	var file := FileAccess.open(state_path("request"), FileAccess.WRITE)
	if file == null:
		voice_title = "Voice request could not be written"
		voice_message = "The existing bridge request file is not writable."
		update_hud()
		return
	request_stamp = Time.get_unix_time_from_system()
	file.store_string(JSON.stringify({"requested": request_stamp}))
	file.close()
	last_request_tick = elapsed
	request_pending = true
	voice_title = "Voice request sent"
	voice_message = "Waiting for the local bridge to acknowledge."
	update_hud()

func _input(event: InputEvent) -> void:
	if fabricator and not xr_active and fabricator.mouse_held and event is InputEventMouseButton and not event.pressed:
		fabricator.mouse_input(event, camera)
		get_viewport().set_input_as_handled()
		return
	if hologram and is_instance_valid(hologram._file_picker) and hologram._file_picker.visible: return
	if hologram and not xr_active and event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and not event.pressed and hologram._mouse_pressed:
		hologram.mouse_input(event, camera)
	if wrist_controls and wrist_controls.input(event):
		if office_windows: office_windows.release_all()
		elif desktop_surface: desktop_surface.release_input()
		get_viewport().set_input_as_handled()
		return
	if assembly_review and assembly_review.input(event):
		get_viewport().set_input_as_handled()
		return
	if desktop_surface and workbench_open() and event is InputEventKey:
		if event.physical_keycode == KEY_F10:
			if event.pressed: show_workbench(false)
		else:
			active_desktop().key_event(event)
		get_viewport().set_input_as_handled()

func _unhandled_input(event: InputEvent) -> void:
	if hologram and is_instance_valid(hologram._file_picker) and hologram._file_picker.visible: return
	if fabricator and not xr_active and fabricator.mouse_input(event, camera):
		get_viewport().set_input_as_handled()
		return
	if hologram and not xr_active and hologram.mouse_input(event, camera):
		get_viewport().set_input_as_handled()
		return
	if workbench_open():
		if desktop_surface and event is InputEventKey: active_desktop().key_event(event)
		return
	if event is InputEventKey and event.pressed and not event.echo:
		match event.physical_keycode:
			KEY_ESCAPE:
				Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
			KEY_F:
				set_view(1)
			KEY_1, KEY_2, KEY_3, KEY_4:
				set_view(int(event.physical_keycode) - KEY_1)
			KEY_TAB:
				show_workbench(true)
			KEY_F8:
				open_assembly_review()
			KEY_SPACE:
				request_voice_turn()
	if xr_active:
		return
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		camera.rotation.y -= event.relative.x * 0.0021
		camera.rotation.x = clampf(camera.rotation.x - event.relative.y * 0.0021, -1.3, 1.3)
		camera.rotation.z = 0.0
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
		if clicked_display(event.position):
			show_workbench(true)
		else:
			Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

func clicked_display(mouse_position: Vector2) -> bool:
	var cursor := mouse_position
	if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		cursor = get_viewport().get_visible_rect().size * 0.5
	var ray_from := camera.project_ray_origin(cursor)
	var ray_to := ray_from + camera.project_ray_normal(cursor) * 8.0
	var query := PhysicsRayQueryParameters3D.create(ray_from, ray_to)
	var hit := get_world_3d().direct_space_state.intersect_ray(query)
	return not hit.is_empty() and hit["collider"].is_in_group("voice_display")

func allowed_position(pos: Vector3) -> bool:
	var bounds: Array = layout.get("walk_bounds", [-4.45, 4.45, -5.45, 5.35])
	if pos.x < float(bounds[0]) or pos.x > float(bounds[1]) or pos.z < float(bounds[2]) or pos.z > float(bounds[3]):
		return false
	for rectangle in layout.get("walk_obstacles", []):
		if pos.x > float(rectangle[0]) and pos.x < float(rectangle[1]) and pos.z > float(rectangle[2]) and pos.z < float(rectangle[3]):
			return false
	if companion and Vector2(pos.x - companion_base.x, pos.z - companion_base.z).length() < 0.44:
		return false
	return true

func move_desktop(delta: float) -> void:
	if xr_active or workbench_open() or Input.mouse_mode != Input.MOUSE_MODE_CAPTURED:
		return
	var axes := Vector2.ZERO
	if Input.is_physical_key_pressed(KEY_W): axes.y -= 1
	if Input.is_physical_key_pressed(KEY_S): axes.y += 1
	if Input.is_physical_key_pressed(KEY_A): axes.x -= 1
	if Input.is_physical_key_pressed(KEY_D): axes.x += 1
	if axes == Vector2.ZERO:
		return
	var speed := 3.0 if Input.is_physical_key_pressed(KEY_SHIFT) else 1.65
	var direction := camera.global_basis * Vector3(axes.x, 0, axes.y)
	direction.y = 0
	direction = direction.normalized() * speed * minf(delta, 0.1)
	camera.position = slide_walk_position(camera.position, direction)
	walking_height = lerpf(walking_height, 1.65, minf(delta * 2.0, 1.0))
	camera.position.y = walking_height

func slide_walk_position(start: Vector3, displacement: Vector3) -> Vector3:
	# Both desktop and stick locomotion use the same bounded path. Small steps
	# prevent a long frame from passing through a desk or a narrow obstacle.
	var flat := Vector3(displacement.x, 0.0, displacement.z)
	var steps := clampi(int(ceil(flat.length() / 0.08)), 1, 128)
	var step := flat / float(steps)
	var result := start
	for index in range(steps):
		var candidate := result + Vector3(step.x, 0, 0)
		if allowed_position(candidate): result.x = candidate.x
		candidate = result + Vector3(0, 0, step.z)
		if allowed_position(candidate): result.z = candidate.z
	return result

func snap_turn_transform(origin: Transform3D, head_pivot: Vector3, angle: float) -> Transform3D:
	var turn := Basis(Vector3.UP, angle)
	return Transform3D(turn * origin.basis, head_pivot + turn * (origin.origin - head_pivot))

func move_xr(delta: float) -> void:
	if not xr_active or controllers.size() < 2:
		return
	var left := controllers[0]
	var right := controllers[1]
	apply_xr_locomotion(left.get_vector2("primary") if left.get_is_active() else Vector2.ZERO, right.get_vector2("primary") if right.get_is_active() else Vector2.ZERO, delta, wrist_controls and wrist_controls.is_capturing())

func apply_xr_locomotion(stick: Vector2, turn_stick: Vector2, delta: float, selecting_menu: bool) -> void:
	# Window visibility never owns locomotion. A menu owns only the right stick.
	var strength := clampf((stick.length() - 0.18) / 0.82, 0.0, 1.0)
	if strength > 0.0:
		# OpenXR stick +Y is forward. Flatten the headset direction so looking
		# down cannot make locomotion dive into the floor or slow unpredictably.
		var heading := -xr_camera.global_basis.z
		heading.y = 0.0
		if heading.length_squared() < 0.01:
			heading = -xr_origin.global_basis.z
			heading.y = 0.0
		heading = heading.normalized()
		var rightward := heading.cross(Vector3.UP)
		var axes := stick.normalized()
		var motion := (rightward * axes.x + heading * axes.y) * strength * 1.35 * minf(delta, 0.1)
		var head := xr_camera.global_position
		var target := slide_walk_position(head, motion)
		xr_origin.global_position += target - head
	if selecting_menu:
		xr_snap_armed = false # require neutral after closing a thumbstick menu
		return
	var snap_axis := turn_stick.x
	if absf(snap_axis) < 0.3:
		xr_snap_armed = true
	elif absf(snap_axis) > 0.7 and xr_snap_armed:
		xr_snap_armed = false
		var angle := -signf(snap_axis) * deg_to_rad(30.0)
		xr_origin.global_transform = snap_turn_transform(xr_origin.global_transform, xr_camera.global_position, angle)

func update_trigger_dictation(hand: Dictionary, right: XRController3D, left: XRController3D) -> bool:
	# Resolve this frame's actual ray, not last frame's hovered-window cache.
	var aimed := false
	var origin := right.global_position
	var direction := -right.global_basis.z
	if office_windows:
		aimed = not office_windows.target_at(origin, direction).is_empty()
	elif desktop_surface:
		aimed = desktop_surface.get_spatial_visible() and is_finite(desktop_surface.ray_distance(origin, direction))
	var menu_active: bool = wrist_controls != null and wrist_controls.is_capturing()
	menu_active = menu_active or left.is_button_pressed("by_button") or left.is_button_pressed("ax_button")
	var gripping: bool = desktop_grab or right.get_float("grip") > 0.7 or (fabricator != null and fabricator.held != null)
	var available: bool = desktop_surface != null and desktop_surface.connected and right.get_is_active() and not bool(hand.get("valid", false))
	var cancel := right.is_button_pressed("by_button") or right.is_button_pressed("ax_button")
	var gesture: Dictionary = trigger_voice.update(right.get_float("trigger"), available, aimed, menu_active, gripping, cancel)
	if gesture.start:
		if office_windows: office_windows.release_all()
		request_voice_turn() # Existing native Dictate path; never synthesizes Send.
		if control_tips: control_tips.request_tip("trigger_voice")
	if gesture.consumed:
		trigger_was_down = right.get_float("trigger") > 0.72
	return gesture.consumed

func update_xr_interaction(delta: float) -> void:
	if not xr_active or controllers.size() < 2:
		trigger_voice.update(0.0, false, false, false, false, false)
		return
	var right := controllers[1]
	var left := controllers[0]
	var hand: Dictionary = hand_pointer.sample(xr_origin) if hand_pointer else {}
	update_xr_feedback(hand, right, left)
	if update_trigger_dictation(hand, right, left): return
	if office_windows and wrist_controls and not wrist_controls.is_capturing():
		var rows: Array = []
		for id: String in office_windows.surfaces:
			if office_windows.surfaces[id].is_open(): rows.append(office_windows.sources[id])
		wrist_controls.set_open_windows(rows)
	if control_tips:
		var aimed_window: bool = office_windows != null and not str(office_windows.pointed_id).is_empty()
		control_tips.update_context(bool(hand.get("valid", false)), right.get_is_active(), wrist_controls != null and wrist_controls.dial.is_open(), aimed_window, delta)
	# Object grip owns only a hit on a completed model; ordinary window and
	# wrist gestures retain their original path. Release/lost tracking is consumed.
	if fabricator:
		var hand_valid := bool(hand.get("valid", false))
		var valid := hand_valid or right.get_is_active()
		var pose := right.global_transform
		var direction := -right.global_basis.z
		var gripping := right.get_float("grip") > 0.7
		if hand_valid:
			pose = Transform3D(hand.get("wrist_basis", Basis.IDENTITY), hand["origin"])
			direction = hand["direction"]
			gripping = bool(hand.get("pinching", false))
		var menu_active: bool = wrist_controls and wrist_controls.is_capturing()
		fabricator.ray_limit = 4.0
		if office_windows:
			for surface: Node3D in office_windows.surfaces.values():
				if surface.is_open() and surface.get_spatial_visible():
					fabricator.ray_limit = minf(fabricator.ray_limit, surface.ray_distance(pose.origin, direction))
		if fabricator.held or not menu_active:
			if fabricator.grab_input(pose, direction, gripping, valid):
				if office_windows: office_windows.release_all()
				pinch_was_down = bool(hand.get("pinching", false))
				trigger_was_down = right.get_float("trigger") > 0.72
				return
	if wrist_controls and wrist_controls.update_xr(hand, right, left, delta):
		if office_windows: office_windows.release_all()
		if active_desktop(): active_desktop().end_move()
		desktop_grab = false
		desktop_grip_was_down = true
		trigger_was_down = right.get_float("trigger") > 0.72
		pinch_was_down = bool(hand.get("pinching", false))
		xr_view_button_was_down = right.is_button_pressed("ax_button")
		xr_close_was_down = right.is_button_pressed("by_button")
		xr_desk_was_down = left.is_button_pressed("ax_button")
		return
	var menu := right.is_button_pressed("ax_button")
	if menu and not xr_view_button_was_down:
		show_workbench(true)
		if desktop_surface: desktop_surface.send_command("focus_desktop", {})
	xr_view_button_was_down = menu
	var close := right.is_button_pressed("by_button")
	if close and not xr_close_was_down:
		if control_tips and control_tips.dismiss(): pass
		elif office_windows: office_windows.close_window()
		else: show_workbench(false)
	xr_close_was_down = close
	var desk := left.is_button_pressed("ax_button")
	if desk and not xr_desk_was_down:
		if wrist_controls:
			var open_rows: Array = []
			if office_windows:
				for id: String in office_windows.surfaces:
					if office_windows.surfaces[id].is_open(): open_rows.append(office_windows.sources[id])
			wrist_controls.set_open_windows(open_rows)
			wrist_controls.open_controller(right, "overview")
			if office_windows: office_windows.release_all()
			desktop_grab = false
			desktop_grip_was_down = true
			xr_desk_was_down = desk
			trigger_was_down = right.get_float("trigger") > 0.72
			return
	xr_desk_was_down = desk
	var pressed := right.get_float("trigger") > 0.72
	if desktop_surface:
		update_desktop_xr(hand, right, left, pressed)
		trigger_was_down = pressed
		return
	if bool(hand.get("valid", false)):
		var pinching := bool(hand.get("pinching", false))
		if workbench_open() and xr_panel:
			xr_panel.point(hand["origin"], hand["direction"], pinching)
		pinch_was_down = pinching
		trigger_was_down = pressed
		return
	pinch_was_down = false
	if workbench_open() and xr_panel:
		xr_panel.point(right.global_position, -right.global_basis.z if right.get_is_active() else Vector3.ZERO, pressed)
	trigger_was_down = pressed

func active_desktop():
	return office_windows.active() if office_windows else desktop_surface

func update_xr_feedback(hand: Dictionary, right: XRController3D, left: XRController3D) -> void:
	if not xr_feedback: return
	var left_hand: Dictionary = left_hand_pointer.sample(xr_origin) if left_hand_pointer else {}
	var hands := [left_hand, hand]
	for side in 2:
		var device: XRController3D = controller_grips[side] if controller_grips.size() == 2 else controllers[side]
		xr_feedback.tracked_body(side, hands[side], device.get_is_active(), device.global_transform)
	var hand_valid := bool(hand.get("valid", false))
	var origin: Vector3 = hand["origin"] if hand_valid else right.global_position
	var direction: Vector3 = hand["direction"] if hand_valid else -right.global_basis.z
	var distance := INF
	var title := ""
	if office_windows:
		for surface: Node3D in office_windows.surfaces.values():
			if not surface.is_open() or not surface.get_spatial_visible(): continue
			var hit: float = surface.ray_distance(origin, direction)
			if hit < distance:
				distance = hit
				title = surface.window_title
	if fabricator:
		fabricator.ray_limit = minf(distance, 4.0)
		var item: Node3D = fabricator.pick(origin, direction)
		if item:
			var bounds: AABB = item.global_transform * hologram.model_bounds(item)
			var hit: Variant = bounds.grow(0.035).intersects_ray(origin, direction.normalized())
			if hit is Vector3:
				distance = origin.distance_to(hit)
				title = "Grip to pick up"
	var pressed := bool(hand.get("pinching", false)) if hand_valid else right.get_float("trigger") > 0.72 or right.get_float("grip") > 0.7
	xr_feedback.aim(hand_valid or right.get_is_active(), origin, direction, distance, title, pressed, wrist_controls != null and wrist_controls.is_capturing())

var desktop_grip_was_down := false

func update_desktop_xr(hand: Dictionary, right: XRController3D, left: XRController3D, pressed: bool) -> void:
	var surface = active_desktop()
	var hand_valid := bool(hand.get("valid", false))
	var pinching := hand_valid and bool(hand.get("pinching", false))
	pinch_was_down = pinching
	if not workbench_open():
		desktop_grip_was_down = true
		return
	surface = active_desktop()
	var source := "hand" if hand_valid else ("controller" if right.get_is_active() else "none")
	if source != desktop_tracking_source:
		surface.release_input()
		desktop_tracking_source = source
	if source == "none":
		surface.end_move()
		if office_windows: office_windows.release_all()
		else: surface.release_input()
		desktop_grab = false
		desktop_grip_was_down = true
		return
	var left_hand: Dictionary = left_hand_pointer.sample(xr_origin) if left_hand_pointer else {}
	var both_hands := hand_valid and bool(left_hand.get("valid", false)) and pinching and bool(left_hand.get("pinching", false))
	var gripping := both_hands or (not hand_valid and right.get_is_active() and right.get_float("grip") > 0.7)
	var fresh_grip := gripping and not desktop_grip_was_down
	desktop_grip_was_down = gripping
	if gripping:
		var grip_transform := right.global_transform
		var separation := 0.0
		if both_hands:
			grip_transform = Transform3D(Basis.IDENTITY, (hand["origin"] + left_hand["origin"]) * 0.5)
			separation = hand["origin"].distance_to(left_hand["origin"])
		if not desktop_grab:
			if fresh_grip:
				var ray_origin: Vector3 = hand["origin"] if hand_valid else right.global_position
				var ray_direction: Vector3 = hand["direction"] if hand_valid else -right.global_basis.z
				if office_windows:
					desktop_grab = office_windows.begin_targeted_move(ray_origin, ray_direction, grip_transform)
					surface = active_desktop()
				elif is_finite(surface.ray_distance(ray_origin, ray_direction)):
					desktop_grab = surface.begin_move(grip_transform)
				if desktop_grab:
					desktop_hand_scale_distance = separation
					desktop_hand_scale = surface.get_panel_scale()
		else:
			surface.update_move(grip_transform)
			if both_hands and desktop_hand_scale_distance > 0.08:
				surface.set_panel_scale(desktop_hand_scale * separation / desktop_hand_scale_distance)
		return
	if desktop_grab:
		surface.end_move()
		surface.release_input()
		desktop_grab = false
	if office_windows:
		if hand_valid: office_windows.point(hand["origin"], hand["direction"], pinching)
		else: office_windows.point(right.global_position, -right.global_basis.z if right.get_is_active() else Vector3.ZERO, pressed)
		surface = active_desktop()
	elif hand_valid:
		surface.point(hand["origin"], hand["direction"], pinching)
	else:
		surface.point(right.global_position, -right.global_basis.z if right.get_is_active() else Vector3.ZERO, pressed)
	if office_windows and office_windows.pointed_id != office_windows.active_id: return
	if not hand_valid and right.get_is_active() and elapsed - desktop_scroll_elapsed > 0.12:
		var axis := right.get_vector2("primary").y
		if absf(axis) > 0.35 and absf(axis) > absf(right.get_vector2("primary").x):
			surface.scroll(-signf(axis))
			desktop_scroll_elapsed = elapsed

func animate_presence(delta: float) -> void:
	if not companion:
		return
	# A static sculpt gets only subtle presence motion. This does not synthesize
	# typing, lipsync, or claim that a nonexistent skeleton is animated.
	companion.position.y = companion_base.y + sin(elapsed * 1.6) * 0.0018
	var viewer := xr_camera.global_position if xr_active else camera.global_position
	var offset := viewer - companion.global_position
	var desired_yaw := atan2(offset.x, offset.z)
	var turn := clampf(wrapf(desired_yaw - companion_yaw, -PI, PI), -0.32, 0.32)
	companion.rotation.y = lerp_angle(companion.rotation.y, companion_yaw + turn, minf(delta * 0.5, 1.0))
	var speaking: bool = str(office_client.state.get("voice_status", "")) == "speaking" if office_client else not desktop_surface and str(voice_snapshot.get("status", "")).to_lower() == "speaking" and file_age(state_path("voice")) < 120.0
	if speaking:
		play_matching_animation(["Hermes_Talk", "Talk", "talk"])
	else:
		play_matching_animation(["Hermes_Idle", "Idle", "idle"])

func _process(delta: float) -> void:
	var automation_age := float(Time.get_ticks_msec() - automation_started_msec) / 1000.0
	if (validate_only or (not capture_path.is_empty() and quit_after_capture)) and not automation_finished and automation_age >= maxf(14.0, capture_delay + 5.0):
		push_error("Office automation exceeded its 14-second scene deadline.")
		automation_finished = true
		get_tree().quit(3)
		return
	if validate_only:
		return
	elapsed += delta
	refresh_time += delta
	if refresh_time >= 2.0:
		refresh_time = 0.0
		refresh_snapshots()
		save_office_draft()
	if wrist_controls and not xr_active: wrist_controls.update_desktop(delta)
	if control_tips and not xr_active and (not control_tips.pending.is_empty() or not control_tips.current.is_empty()):
		control_tips.update_context(false, true, wrist_controls != null and wrist_controls.dial.is_open(), false, delta)
	update_xr_interaction(delta)
	move_desktop(delta)
	move_xr(delta)
	animate_presence(delta)
	if not capture_path.is_empty() and not capture_started and automation_age >= capture_delay:
		capture_started = true
		capture_frame.call_deferred()

func validate_scene() -> void:
	automation_finished = true
	var missing := false
	var clips: Dictionary = {}
	for clip in ["Hermes_Idle", "Hermes_Talk"]:
		play_matching_animation([clip])
		if animation_player and current_animation.get_file() == clip:
			clips[clip] = {"length": animation_player.get_animation(current_animation).length, "loop": animation_player.get_animation(current_animation).loop_mode == Animation.LOOP_LINEAR}
		else:
			missing = true
	play_matching_animation(["Hermes_Idle"])
	for required in ["res://assets/whiskey-room.glb", "res://assets/office-decorations.glb", "res://assets/hermes-companion.glb", "res://assets/club-chair.glb"]:
		if asset_results.get(required, "missing") != "loaded":
			missing = true
	print("HERMES_VALIDATION " + JSON.stringify({
		"assets": asset_results, "state_directory": state_dir,
		"agent_status": agent_status, "agent_title": agent_title,
		"kanban": kanban_summary, "voice": voice_title,
		"skeleton_animation_player": animation_player != null,
		"animations": clips,
		"xr_active": xr_active, "scene_ready": true,
		"voice_request_written": false
	}))
	get_tree().quit(2 if missing else 0)

func capture_frame() -> void:
	if DisplayServer.get_name() == "headless":
		push_error("Screenshot capture needs a rendering display; use --validate for headless checks.")
		get_tree().quit(3)
		return
	await RenderingServer.frame_post_draw
	if automation_finished:
		return
	var captured := get_viewport().get_texture().get_image()
	if captured == null or captured.is_empty():
		push_error("Rendered viewport returned no image.")
		get_tree().quit(3)
		return
	var destination := capture_path
	if not destination.is_absolute_path():
		destination = ProjectSettings.globalize_path("res://" + destination)
	var result := captured.save_png(destination)
	automation_finished = true
	print("HERMES_CAPTURE " + JSON.stringify({"path": destination, "result": result, "width": captured.get_width(), "height": captured.get_height(), "renderer": RenderingServer.get_current_rendering_method(), "fps_at_capture": Engine.get_frames_per_second(), "draw_calls": Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME), "primitives": Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME), "animation": current_animation, "animation_playing": animation_player != null and animation_player.is_playing(), "scene_elapsed_seconds": elapsed}))
	if quit_after_capture:
		get_tree().quit(0 if result == OK else 3)
