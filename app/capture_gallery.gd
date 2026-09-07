extends SceneTree
## Native screenshot fixture. No integration processes, devices or agent turns.
## godot --path app --xr-mode off --audio-driver Dummy --script res://capture_gallery.gd -- --gallery-output=/absolute/output
var office: Node3D
var destination := ""
var shots: Array[Dictionary] = []

func _initialize() -> void:
	run.call_deferred()

func hide_overlays(node: Node) -> void:
	if node is CanvasLayer: node.visible = false
	for child in node.get_children(): hide_overlays(child)

func shoot(name: String, position: Vector3, target: Vector3, fov: float) -> void:
	office.camera.global_position = position
	office.camera.look_at(target, Vector3.UP)
	office.camera.fov = fov
	await create_timer(5.0).timeout
	await RenderingServer.frame_post_draw
	var picture := root.get_texture().get_image()
	var path := destination.path_join(name + ".png")
	if picture == null or picture.is_empty() or picture.save_png(path) != OK:
		push_error("Gallery capture failed: " + name)
		quit(2)
		return
	shots.append({"file": name + ".png", "width": picture.get_width(), "height": picture.get_height(),
		"camera_position_m": [position.x, position.y, position.z], "camera_target_m": [target.x, target.y, target.z],
		"vertical_fov_degrees": fov, "renderer": RenderingServer.get_current_rendering_method(),
		"native_capture": true, "post_processing": "none", "headset_capture": false})
	print("GALLERY_CAPTURE " + name)

func run() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--gallery-output="): destination = arg.trim_prefix("--gallery-output=")
	if not destination.is_absolute_path() or DisplayServer.get_name() == "headless":
		push_error("Use a rendering display and an absolute --gallery-output directory.")
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(destination)
	var scratch := destination.path_join("private-fixture-" + str(OS.get_process_id()))
	DirAccess.make_dir_recursive_absolute(scratch)
	# All state is isolated before loading the room. This script launches Godot
	# directly, never office_launcher.py, Hermes, a desktop bridge or a renderer worker.
	for key in ["HERMES_STATE_DIR", "HERMES_OFFICE_DATA_DIR", "HERMES_PODIUM_DATA_DIR",
		"HERMES_DESKTOP_IPC_DIR", "HERMES_WINDOWS_IPC_DIR", "HERMES_OFFICE_BRIDGE_DIR", "HERMES_PODIUM_IPC_DIR"]:
		OS.set_environment(key, scratch.path_join(key.to_lower()))
	for key in ["HERMES_OFFICE_WRIST_PREVIEW", "HERMES_OFFICE_WINDOWS_PREVIEW", "HERMES_OFFICE_BAY_PREVIEW",
		"HERMES_OFFICE_PARTS_PREVIEW", "HERMES_OFFICE_HOLOGRAM_PREVIEW", "HERMES_PODIUM_PREVIEW"]:
		OS.set_environment(key, "")
	OS.set_environment("HERMES_DESKTOP_PREVIEW", "1")
	root.size = Vector2i(2560, 1440)
	root.content_scale_size = Vector2i(2560, 1440)
	office = load("res://main.tscn").instantiate()
	root.add_child(office)
	hide_overlays(office)
	Input.mouse_mode = Input.MOUSE_MODE_HIDDEN
	await create_timer(4.0).timeout
	await shoot("01-whiskey-room", Vector3(3.15, 1.85, 4.7), Vector3(-0.35, 1.25, -1.8), 62.0)
	await shoot("02-hermes-at-the-desk", Vector3(2.15, 1.65, 1.55), Vector3(1.35, 1.05, -1.85), 46.0)
	await shoot("03-listening-corner", Vector3(-1.85, 1.5, -0.85), Vector3(-4.1, 0.95, -3.0), 51.0)
	await shoot("04-vinyl-and-valves", Vector3(2.55, 1.65, 2.55), Vector3(4.3, 0.94, 1.7), 49.0)
	await shoot("05-planted-lounge", Vector3(1.66, 1.65, 5.12), Vector3(-2.4, 0.96, 2.15), 59.0)
	for index in office.hologram.choices.size():
		if str(office.hologram.choices[index].id) == "desk":
			office.hologram.open_index(index)
			break
	office.hologram.resize(0.7)
	await shoot("06-hologram-podium", Vector3(1.9, 1.85, 1.55), Vector3(-0.25, 1.03, -0.35), 56.0)
	office.hologram.clear()
	office.camera.global_position = Vector3(2.8, 1.68, 3.4)
	office.camera.look_at(Vector3(-0.1, 1.22, -2.25), Vector3.UP)
	office.camera.fov = 62.0
	OS.set_environment("HERMES_OFFICE_RING_PREVIEW", "1")
	office.wrist_controls.preview()
	await shoot("07-wrist-interface", office.camera.global_position, Vector3(-0.1, 1.22, -2.25), 62.0)
	shots[-1]["interaction_fixture"] = "Built-in simulated wrist pose; not physical hand-tracking acceptance"
	var receipt := FileAccess.open(destination.path_join("capture-manifest.json"), FileAccess.WRITE)
	receipt.store_string(JSON.stringify({"schema": 1, "screenshots": shots,
		"presentation": "Native application scene, hidden desktop overlays, isolated empty workspace; no image editing",
		"model_calls": 0, "microphone_or_camera_capture": false}, "  ") + "\n")
	receipt.close()
	quit(0)
