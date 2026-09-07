extends SceneTree
## godot --headless --path app --script res://test_desktop_surface.gd
const Surface = preload("res://desktop_surface.gd")
var failures: Array[String] = []

class InputProbe:
	extends "res://desktop_surface.gd"
	var commands: Array[Dictionary] = []
	func _emit_command(command: Dictionary) -> bool:
		commands.append(command.duplicate(true))
		return connected
	func buttons() -> Array[Dictionary]:
		var result: Array[Dictionary] = []
		for command: Dictionary in commands:
			if command.get("type") == "pointer_button":
				result.append(command)
		return result
	func cancels() -> int:
		var result := 0
		for command: Dictionary in commands:
			if command.get("type") == "pointer_cancel":
				result += 1
		return result

func check(value: bool, message: String) -> void:
	if not value:
		failures.append(message)

func _initialize() -> void:
	call_deferred("run_checks")

func run_checks() -> void:
	var fresh := {"protocol_version": 1, "instance_id": "native-test", "connected": true, "updated_at_unix": 100.0, "width": 1280, "height": 800, "frame_id": 1}
	check(Surface.status_error(fresh, 102.0).is_empty(), "Fresh supported status permits input")
	check(not Surface.status_error(fresh, 105.0).is_empty(), "Expired heartbeat blocks stale input")
	var other := fresh.duplicate()
	other["protocol_version"] = 2
	check(not Surface.status_error(other, 100.0).is_empty(), "Unknown protocol blocks input")
	other = fresh.duplicate()
	other["instance_id"] = ""
	check(not Surface.status_error(other, 100.0).is_empty(), "Missing instance blocks input")
	other = fresh.duplicate()
	other["connected"] = false
	other["error"] = "Window closed"
	check(Surface.status_error(other, 100.0) == "Window closed", "Connection reason is honest")
	check(Surface.ray_to_uv(Transform3D.IDENTITY, Vector3(0, 0, 1), Vector3.FORWARD).is_equal_approx(Vector2(0.5, 0.5)), "Ray center maps to desktop center")
	check(Surface.ray_to_uv(Transform3D.IDENTITY, Vector3(0.81, 0, 1), Vector3.FORWARD) == Surface.MISS, "Outside desktop ray misses")
	check(Surface.ray_to_uv(Transform3D.IDENTITY, Vector3(0, 0, -1), Vector3.BACK) == Surface.MISS, "Desktop back face cannot click")
	check(Surface.preview_to_pixel(Vector2(500, 500), Vector2(1000, 1000), Vector2i(1280, 800)) == Vector2(640, 400), "Preview maps center with letterboxing")
	check(Surface.preview_to_pixel(Vector2(500, 100), Vector2(1000, 1000), Vector2i(1280, 800)) == Surface.MISS, "Preview letterbox cannot click app")
	check(Surface.preview_to_pixel(Vector2(1000, 812.5), Vector2(1000, 1000), Vector2i(1280, 800)) == Vector2(1279, 799), "Inclusive preview edge clamps to final pixel")
	var key := InputEventKey.new()
	key.keycode = KEY_ENTER
	check(Surface.event_keysym(key) == "Return", "Enter maps to X Return")
	key.keycode = KEY_BACKSPACE
	check(Surface.event_keysym(key) == "BackSpace", "Backspace maps to X BackSpace")
	key.keycode = KEY_CTRL
	check(Surface.event_keysym(key) == "Control_L", "Control maps to an X modifier")
	key.keycode = KEY_A
	check(Surface.event_keysym(key) == "a", "Letter uses base lowercase keysym")

	var panel := InputProbe.new()
	root.add_child(panel)
	panel._built = true
	panel._opened = true
	panel.connected = true
	panel.show()
	var origin := Vector3(0, 0, 1)
	panel.point(origin, Vector3.FORWARD, true)
	check(panel.buttons().is_empty(), "Opening trigger cannot click desktop")
	panel.point(origin, Vector3.FORWARD, false)
	panel.point(origin, Vector3.FORWARD, true)
	panel.point(origin, Vector3.FORWARD, true)
	panel.point(origin, Vector3.FORWARD, false)
	var clicks := panel.buttons()
	check(clicks.size() == 2, "A held pinch queues one down and one release")
	if clicks.size() == 2:
		check(clicks[0]["pressed"] and not clicks[1]["pressed"], "Pointer button order is correct")
		check(clicks[0]["x"] == 640 and clicks[0]["y"] == 400, "Pointer input is in desktop pixels")
	panel.commands.clear()
	panel.point(origin, Vector3.FORWARD, true)
	panel.point(origin, Vector3.ZERO, true)
	panel.point(origin, Vector3.FORWARD, true)
	clicks = panel.buttons()
	check(clicks.size() == 1 and clicks[0]["pressed"] and panel.cancels() == 1, "Tracking loss cancels in the gutter and held reentry cannot click")
	panel.point(origin, Vector3.FORWARD, false)
	panel.commands.clear()
	panel.point(Vector3(3, 0, 1), Vector3.FORWARD, true)
	panel.point(origin, Vector3.FORWARD, true)
	check(panel.buttons().is_empty(), "Press starting outside never activates on entry")
	panel.point(origin, Vector3.FORWARD, false)
	panel.point(origin, Vector3.FORWARD, true)
	panel.commands.clear()
	check(panel.begin_move(Transform3D.IDENTITY), "Grip can start a separate shell move")
	clicks = panel.buttons()
	check(clicks.is_empty() and panel.cancels() == 1, "Grabbing shell cancels app click without activating it")
	panel.update_move(Transform3D(Basis.IDENTITY, Vector3(0.5, 0.2, -0.3)))
	check(panel.global_position.is_equal_approx(Vector3(0.5, 0.2, -0.3)), "Grip movement preserves initial offset")
	panel.end_move()
	panel.set_panel_scale(100.0)
	check(is_equal_approx(panel.get_panel_scale(), Surface.MAX_SCALE), "Panel enlargement is bounded")
	panel.scale_panel(0.001)
	check(is_equal_approx(panel.get_panel_scale(), Surface.MIN_SCALE), "Panel reduction is bounded")
	check(panel.frame_size == Vector2i(1280, 800), "Spatial resize does not resize the desktop session")
	key.pressed = true
	panel.key_event(key)
	panel.commands.clear()
	panel.close_panel()
	check(not panel.is_open(), "Close hides spatial surface")
	check(panel.commands.any(func(command: Dictionary) -> bool: return command.get("type") == "key" and not command.get("pressed", true)), "Close releases held keyboard keys")
	panel.free()

	var head := Camera3D.new()
	root.add_child(head)
	head.position = Vector3(0, 1.65, 2)
	var built := Surface.new()
	root.add_child(built)
	built.setup("", head)
	built.open_panel()
	check(built.is_open(), "Complete surface opens")
	check(is_equal_approx(built.global_position.distance_to(head.global_position), Surface.PANEL_DISTANCE), "Surface opens at comfortable distance")
	var preview := built.create_preview()
	root.add_child(preview)
	check(preview.stretch_mode == TextureRect.STRETCH_KEEP_ASPECT_CENTERED, "Desktop preview retains frame aspect")
	built.set_keyboard_visible(true)
	check(built._keyboard.visible and built._shell_viewport.size.y == 360, "Spatial keyboard exposes actual text/key controls")
	built._set_shift(true)
	check(built._letter_buttons[0].text == "!", "Shift provides punctuation")
	# Exercise actual atomic frame loading and the file command envelope in a
	# unique test-owned directory, without connecting to any running desktop.
	var ipc := ProjectSettings.globalize_path("user://desktop-surface-test-%d-%d" % [OS.get_process_id(), Time.get_ticks_usec()])
	check(DirAccess.make_dir_recursive_absolute(ipc.path_join("commands")) == OK, "Private test IPC directory can be created")
	var frame := Image.create(8, 4, false, Image.FORMAT_RGBA8)
	frame.fill(Color("e4bd75"))
	check(frame.save_png(ipc.path_join("frame.png")) == OK, "Fixture frame is written")
	var fixture := fresh.duplicate()
	fixture["width"] = 8
	fixture["height"] = 4
	fixture["updated_at_unix"] = Time.get_unix_time_from_system()
	var status_file := FileAccess.open(ipc.path_join("status.json"), FileAccess.WRITE)
	if status_file != null:
		status_file.store_string(JSON.stringify(fixture))
		status_file.close()
	else:
		check(false, "Fixture status is writable")
	built._ipc = ipc
	built.poll_frame()
	check(built.connected and built.texture != null and built.frame_size == Vector2i(8, 4), "Real frame load establishes the current instance")
	var command_id := built.send_command("text", {"text": "Explicit test text"})
	check(not command_id.is_empty(), "Current instance queues an explicit command")
	if not command_id.is_empty():
		var command_path := ipc.path_join("commands").path_join(command_id + ".json")
		var envelope: Variant = JSON.parse_string(FileAccess.get_file_as_string(command_path))
		check(envelope is Dictionary and envelope.get("instance_id") == "native-test" and envelope.get("protocol_version") == 1 and envelope.get("text") == "Explicit test text", "Atomic command preserves protocol, instance and exact content")
		check(not FileAccess.file_exists(command_path.trim_suffix(".json") + ".tmp"), "Completed queue write leaves no temporary command")
		DirAccess.remove_absolute(command_path)
	built.close_panel()
	preview.hide()
	check(not built.frame_demand(), "Hidden closed panel has no continuing frame demand")
	built.set_mirror_enabled(true)
	check(built.frame_demand() and not built.is_open(), "Passive mirror requests pixels without opening input surface")
	fixture["frame_id"] = 2
	status_file = FileAccess.open(ipc.path_join("status.json"), FileAccess.WRITE)
	status_file.store_string(JSON.stringify(fixture))
	status_file.close()
	built.poll_frame()
	check(built._last_frame_id == 2 and built.connected, "Closed mirror advances to current frame")
	built.set_mirror_enabled(false)
	fixture["frame_id"] = 3
	status_file = FileAccess.open(ipc.path_join("status.json"), FileAccess.WRITE)
	status_file.store_string(JSON.stringify(fixture))
	status_file.close()
	built.poll_frame()
	check(built._last_frame_id == 2 and not built.frame_demand(), "Disabling mirror avoids unnecessary image decoding")
	built.set_mirror_enabled(true)
	fixture["instance_id"] = "replacement-instance"
	status_file = FileAccess.open(ipc.path_join("status.json"), FileAccess.WRITE)
	status_file.store_string(JSON.stringify(fixture))
	status_file.close()
	built.poll_frame()
	check(built._frame_instance == "replacement-instance" and built.connected and not built.is_open(), "Mirror reconnects to new capture instance without opening panel")
	built.status["updated_at_unix"] = Time.get_unix_time_from_system() - 10.0
	check(built.send_command("text", {"text": "Do not queue"}).is_empty(), "Last-moment stale guard prevents queued input")
	built.close_panel()
	for filename: String in ["frame.png", "status.json"]:
		DirAccess.remove_absolute(ipc.path_join(filename))
	DirAccess.remove_absolute(ipc.path_join("commands"))
	DirAccess.remove_absolute(ipc)
	preview.free()
	built.free()
	head.free()
	print("HERMES_DESKTOP_SURFACE_TESTS " + JSON.stringify({"passed": failures.is_empty(), "failures": failures}))
	quit(0 if failures.is_empty() else 1)
