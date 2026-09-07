extends SceneTree
## Tests only a uniquely named user:// fixture directory, never ~/.hermes.
## Run: godot --headless --path . --script res://test_contracts.gd

var failures: Array[String] = []
var fixture_dir := ""
var office: Variant

func _initialize() -> void:
	run_checks.call_deferred()

func check(condition: bool, message: String) -> void:
	if not condition:
		failures.append(message)

func fixture(name: String, value: Variant) -> void:
	var file := FileAccess.open(fixture_dir.path_join(name), FileAccess.WRITE)
	if file == null:
		failures.append("Cannot create fixture " + name)
		return
	file.store_string(JSON.stringify(value))
	file.close()

func run_checks() -> void:
	fixture_dir = ProjectSettings.globalize_path("user://contract-test-%d" % Time.get_ticks_usec())
	if DirAccess.make_dir_recursive_absolute(fixture_dir) != OK:
		push_error("Cannot create isolated test directory.")
		quit(1)
		return
	var script := load("res://main.gd") as GDScript
	office = script.new()
	office.state_dir = fixture_dir
	office.elapsed = 50.0
	# Deliberately do not add the office to the scene tree: no assets, renderer,
	# OpenXR initialization, or services are involved in contract tests.
	office.refresh_snapshots()
	check(office.agent_title == "Hermes offline", "Missing agents must be offline")
	check(office.kanban_summary == "Task board unavailable", "Missing board must be unavailable")
	check(office.voice_title == "Voice offline", "Missing voice must be offline")
	check(not FileAccess.file_exists(office.state_path("request")), "Refresh must never request voice")
	office.request_voice_turn()
	check(not FileAccess.file_exists(office.state_path("request")), "Absent bridge must not create a request")
	fixture("quest-agents.json", [{"id": "someone-else", "status": "working", "task": "Unrelated work"}])
	office.refresh_agent_state()
	check(office.agent_title == "Hermes offline", "Other agents must not be renamed Hermes")
	fixture("quest-agents.json", [{"id": "hermes", "status": "working", "task": "Reviewing the brief"}])
	fixture("vr-kanban.json", [
		{"title": "First", "status": "todo"},
		{"name": "Second", "column": "in-progress"},
		{"task": "Third", "status": "blocked"},
		{"title": "Fourth", "status": "complete"}
	])
	fixture("vr-voice-state.json", {"status": "ready", "updated": Time.get_unix_time_from_system(), "message": "Press trigger"})
	var agents_before := FileAccess.get_file_as_string(office.state_path("agents"))
	var board_before := FileAccess.get_file_as_string(office.state_path("kanban"))
	office.refresh_snapshots()
	check(office.agent_status == "working", "Hermes status must survive reading")
	check(office.agent_task == "Reviewing the brief", "Hermes task must survive reading")
	for column in ["TODO", "RUNNING", "REVIEW", "DONE"]:
		check(office.grouped_tasks[column].size() == 1, "Task status mapping: " + column)
	check(not FileAccess.file_exists(office.state_path("request")), "Ready state must not auto-start voice")
	office.request_voice_turn()
	var request: Variant = office.read_json(office.state_path("request"))
	check(request is Dictionary and request.size() == 1 and request.has("requested"), "Request must preserve timestamp-only contract")
	check(office.voice_title == "Voice request sent", "A request must not claim listening")
	var first_request := FileAccess.get_file_as_string(office.state_path("request"))
	office.request_voice_turn()
	check(first_request == FileAccess.get_file_as_string(office.state_path("request")), "Pending request must not be sent twice")
	fixture("vr-voice-state.json", {"status": "listening", "updated": office.request_stamp + 0.1, "message": "Listening for 6 seconds"})
	office.refresh_voice_state()
	check(not office.request_pending, "Bridge timestamp must acknowledge request")
	check(office.voice_title == "Voice · listening", "Listening must come from the bridge")
	check(agents_before == FileAccess.get_file_as_string(office.state_path("agents")), "Agent state must stay unchanged")
	check(board_before == FileAccess.get_file_as_string(office.state_path("kanban")), "Kanban state must stay unchanged")
	var malformed := FileAccess.open(office.state_path("agents"), FileAccess.WRITE)
	malformed.store_string("{broken")
	malformed.close()
	office.refresh_agent_state()
	check(office.agent_title == "Hermes offline", "Malformed JSON must fail to offline")
	# Locomotion mathematics are independent of a headset or renderer.
	office.layout = {
		"walk_bounds": [-4.45, 4.45, -5.45, 5.35],
		"walk_obstacles": [[-1.65, 1.4, -3.25, -1.9]]
	}
	var wall_stop: Vector3 = office.slide_walk_position(Vector3(4.3, 1.65, 1.0), Vector3(1, 0, 0))
	check(wall_stop.x <= 4.45 and wall_stop.x >= 4.3, "Stick/desktop movement must stop at room boundary")
	var desk_stop: Vector3 = office.slide_walk_position(Vector3(0, 1.65, -1.6), Vector3(0, 0, -3))
	check(desk_stop.z >= -1.9, "A long movement step must not tunnel through the desk")
	var free_move: Vector3 = office.slide_walk_position(Vector3(2.5, 1.65, 2), Vector3(0.5, 10, -0.5))
	check(free_move.is_equal_approx(Vector3(3, 1.65, 1.5)), "Free movement must preserve horizontal displacement and head height")
	var original := Transform3D(Basis(Vector3.UP, 0.47), Vector3(2.0, 0, -1.0))
	var tracked_head := Vector3(0.63, 1.62, -0.42)
	var pivot := original * tracked_head
	var snapped: Transform3D = office.snap_turn_transform(original, pivot, deg_to_rad(30.0))
	check((snapped * tracked_head).is_equal_approx(pivot), "Snap turn must keep the off-center headset pivot fixed")
	var round_trip := original
	for step in range(12):
		round_trip = office.snap_turn_transform(round_trip, pivot, deg_to_rad(30.0))
	check(round_trip.is_equal_approx(original), "Twelve 30-degree snaps must return to original transform")
	var origin := XROrigin3D.new()
	root.add_child(origin)
	var head := XRCamera3D.new()
	origin.add_child(head)
	head.position = Vector3(2.5, 1.65, 2)
	office.xr_origin = origin
	office.xr_camera = head
	var before := head.global_position
	office.apply_xr_locomotion(Vector2.UP, Vector2.ZERO, 0.02, true)
	check(head.global_position.distance_to(before) > 0.01, "Left stick keeps moving while menu owns right-stick selection")
	var orientation: Basis = origin.basis
	office.apply_xr_locomotion(Vector2.ZERO, Vector2.RIGHT, 0.02, true)
	check(origin.basis.is_equal_approx(orientation), "Menu selection cannot snap-turn")
	office.apply_xr_locomotion(Vector2.ZERO, Vector2.RIGHT, 0.02, false)
	check(origin.basis.is_equal_approx(orientation), "Closing menu with held stick cannot cause surprise snap")
	office.apply_xr_locomotion(Vector2.ZERO, Vector2.ZERO, 0.02, false)
	office.apply_xr_locomotion(Vector2.ZERO, Vector2.RIGHT, 0.02, false)
	check(not origin.basis.is_equal_approx(orientation), "Neutral rearms normal turning")
	origin.free()
	office.free()
	for filename in ["quest-agents.json", "vr-kanban.json", "vr-voice-state.json", "vr-voice-request.json"]:
		var path := fixture_dir.path_join(filename)
		if FileAccess.file_exists(path):
			DirAccess.remove_absolute(path)
	DirAccess.remove_absolute(fixture_dir)
	print("HERMES_CONTRACT_TESTS " + JSON.stringify({"passed": failures.is_empty(), "failures": failures}))
	quit(0 if failures.is_empty() else 1)
