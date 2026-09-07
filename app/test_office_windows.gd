extends SceneTree
const Manager = preload("res://office_windows.gd")
var failures: Array = []
var checks := 0

class FakeSurface:
	extends Node3D
	signal panel_closed
	var opened := true
	var _has_placement := true
	var distance := INF
	var releases := 0
	var points: Array = []
	var moving := false
	func set_spatial_visible(_v: bool) -> void: pass
	func is_open() -> bool: return opened
	func end_move() -> void: moving = false
	func begin_move(_pose: Transform3D) -> bool:
		moving = true
		return true
	func release_input() -> void: releases += 1
	func set_window_active(value: bool) -> void:
		if not value: release_input()
	func open_panel(_recenter := true) -> void:
		opened = true
		show()
	func close_panel() -> void:
		opened = false
		hide()
		release_input()
		panel_closed.emit()
	func ray_distance(_o: Vector3, _d: Vector3) -> float: return distance if opened else INF
	func point(_o: Vector3, d: Vector3, pressed: bool) -> void: points.append([d, pressed])
	func set_panel_scale(value: float) -> void: scale = Vector3.ONE*value
	func get_panel_scale() -> float: return scale.x
	func move_panel(value: Transform3D) -> void:
		global_transform = Transform3D(value.basis.orthonormalized().scaled(scale), value.origin)

func check(value: bool, message: String) -> void:
	checks += 1
	if not value: failures.append(message)

func _initialize() -> void: run.call_deferred()

func run() -> void:
	var manager = Manager.new()
	root.add_child(manager)
	var head := Node3D.new()
	root.add_child(head)
	var first := FakeSurface.new()
	var second := FakeSurface.new()
	root.add_child(first)
	root.add_child(second)
	manager.setup(first, head, true)
	manager.sources.remote = {"id": "remote", "title": "Remote", "machine": "Other"}
	manager.register("remote", second)
	first.distance = 2.0
	second.distance = 1.0
	manager.point(Vector3.ZERO, Vector3.FORWARD, false)
	first.distance = INF
	second.distance = INF
	var focus_before: String = manager.active_id
	check(not manager.begin_targeted_move(Vector3.ZERO, Vector3.FORWARD, Transform3D.IDENTITY), "Empty-space grip cannot grab active window")
	check(manager.active_id == focus_before and not first.moving and not second.moving, "Miss preserves focus and transforms")
	first.distance = 2.0
	second.distance = 1.0
	check(manager.begin_targeted_move(Vector3.ZERO, Vector3.FORWARD, Transform3D.IDENTITY) and second.moving and not first.moving, "Grip targets nearest hit instead of prior active window")
	manager.release_all()
	check(not second.moving, "Tracking loss or menu ownership releases targeted grab")
	manager.point(Vector3.ZERO, Vector3.FORWARD, false)
	manager.point(Vector3.ZERO, Vector3.FORWARD, true)
	check(manager.active_id == "remote", "nearest window owns new click")
	check(first.releases >= 1, "old machine releases keys on focus switch")
	check(second.points[-1][1], "selected machine receives press")
	first.distance = 0.5
	manager.point(Vector3.ZERO, Vector3.FORWARD, true)
	check(manager.active_id == "remote", "held click cannot cross machines")
	check(not first.points[-1][1], "other machine never received held press")
	manager.point(Vector3.ZERO, Vector3.FORWARD, false)
	check(not second.points[-1][1], "release reaches original machine")
	manager.point(Vector3.ZERO, Vector3.FORWARD, true)
	check(manager.active_id == "hermes", "fresh press may change machine")
	manager.release_all()
	manager.point(Vector3.ZERO, Vector3.FORWARD, true)
	check(manager._capture_id.is_empty(), "tracking loss requires release before rearming")
	manager.point(Vector3.ZERO, Vector3.FORWARD, false)
	second.position = Vector3(3, 2, 1)
	manager.close_window("remote")
	check(first.is_open() and not second.is_open(), "close is isolated")
	check(manager.reopen(), "hidden window reopens")
	check(second.position == Vector3(3, 2, 1), "reopen preserves placement")
	manager.arrange()
	check(first.position.distance_to(second.position) > 0.8, "arrange separates surfaces")
	manager.hide_for_capture()
	check(not first.visible and not second.visible, "office share hides every machine")
	manager.restore_after_capture()
	check(first.visible and second.visible and manager.active_id == "remote", "capture restores surfaces and focus")
	manager.disconnect_window("remote")
	check(not manager.surfaces.has("remote") and manager.surfaces.has("hermes"), "disconnect frees only selected slot")
	var native := Window.new()
	manager.add_child(native)
	manager.native_windows.hermes = native
	native.hide()
	first.set_meta("podium_projected", true)
	manager._menu_hidden = ["hermes"]
	manager.menu_open = func() -> bool: return false
	manager._process(0.01)
	check(not native.visible, "Closing hand wheel cannot reopen flat preview over hologram")
	manager.open_window("hermes")
	check(not native.visible, "Reopening projected source keeps its holographic placement")
	first.set_meta("podium_projected", false)
	manager.open_window("hermes")
	check(native.visible, "Normal window display returns after projection")
	manager._layout_path = OS.get_cache_dir().path_join("hermes-window-layout-test-%d.json" % Time.get_ticks_usec())
	manager._instance = "test-owner"
	first.position = Vector3(1.4, 1.7, -2.1)
	first.set_panel_scale(0.8)
	manager.save_layout()
	check(FileAccess.file_exists(manager._layout_path), "Workspace layout persists independently of application memory")
	first.close_panel()
	first._has_placement = false
	first.position = Vector3.ZERO
	manager.load_layout()
	manager.restore_windows()
	check(first.is_open() and first.position.is_equal_approx(Vector3(1.4, 1.7, -2.1)) and is_equal_approx(first.scale.x, 0.8), "Restart recovery restores open state, position and scale")
	manager._restore_open_ids = ["unconfigured-machine"]
	manager.restore_windows()
	check(not manager.surfaces.has("unconfigured-machine"), "Recovery cannot launch an unconfigured machine")
	DirAccess.remove_absolute(manager._layout_path)
	manager._layout_path = ""
	print("HERMES_OFFICE_WINDOWS_TESTS " + JSON.stringify({"checks":checks,"failures":failures}))
	quit(0 if failures.is_empty() else 1)
