extends SceneTree
const Feedback = preload("res://xr_feedback.gd")
const Commands = preload("res://office_scene_commands.gd")
const Dial = preload("res://wrist_dial.gd")
var checks := 0
var failures: Array[String] = []

class Office:
	extends Node
	var hologram
	var fabricator

func check(value: bool, message: String) -> void:
	checks += 1
	if not value: failures.append(message)

func _initialize() -> void:
	call_deferred("run_checks")

func run_checks() -> void:
	var feedback := Feedback.new()
	root.add_child(feedback)
	feedback.setup()
	feedback.tracked_body(1, {}, true, Transform3D(Basis.IDENTITY, Vector3(1, 2, 3)))
	check(feedback.bodies[1].visible and feedback.bodies[1].global_position == Vector3(1, 2, 3), "Controller appears at its actual grip pose")
	feedback.tracked_body(1, {"valid": true, "bones": [[Vector3.ZERO, Vector3.UP]]}, true, Transform3D.IDENTITY)
	check(not feedback.bodies[1].visible and feedback.bones[1].multimesh.visible_instance_count == 1, "Tracked hand replaces controller representation")
	feedback.tracked_body(1, {}, false, Transform3D.IDENTITY)
	check(not feedback.bodies[1].visible and feedback.bones[1].multimesh.visible_instance_count == 0, "Lost tracking removes stale hand and controller")
	feedback.aim(true, Vector3.ZERO, Vector3.FORWARD, 1.7, "Document", false, false)
	check(feedback.dot.visible and feedback.dot.global_position.is_equal_approx(Vector3(0, 0, -1.7)), "Aim reticle terminates at selected input hit distance")
	feedback.aim(true, Vector3.ZERO, Vector3.FORWARD, 1.7, "Document", true, false)
	check(feedback.beam.material_override.albedo_color == Color("ffd18a"), "Press or grip has distinct feedback")
	feedback.aim(true, Vector3.ZERO, Vector3.FORWARD, 1.7, "Document", false, true)
	check(not feedback.beam.visible and not feedback.caption.visible, "Menu ownership suppresses misleading desktop ray")
	feedback.aim(false, Vector3.ZERO, Vector3.FORWARD, INF, "", false, false)
	check(not feedback.dot.visible, "Tracking loss hides reticle")
	feedback.free()
	for count: int in [2, 3, 5, 6, 8]:
		var dial := Dial.new()
		var ids: Array = []
		for i in count: ids.append("action_" + str(i))
		check(dial.set_slots(ids), "Purposeful menu count accepted: " + str(count))
		dial.open_at(Basis.IDENTITY)
		for i in count:
			var angle := i * TAU / count
			var state := dial.update({"valid": true, "menu_pose": true, "pinching": false, "wrist_basis": Basis.IDENTITY, "selection_axis": Vector2(sin(angle), cos(angle))}, 0.02)
			check(state.selected_id == ids[i], "Thumbstick and visible sector agree: %s/%s" % [count, i])
	var office := Office.new()
	root.add_child(office)
	var camera := Camera3D.new()
	office.add_child(camera)
	office.hologram = load("res://office_hologram.gd").new()
	office.add_child(office.hologram)
	office.hologram.setup(camera, func(_path: String): return null, false)
	office.fabricator = load("res://office_fabricator.gd").new()
	office.add_child(office.fabricator)
	office.fabricator.setup(office.hologram, camera, false)
	var commands := Commands.new()
	office.add_child(commands)
	commands.setup(office, "", "test-instance")
	var request := {"schema": 1, "instance": "test-instance", "id": "ab".repeat(16), "expires_at": 110.0, "action": "primitive", "shape": "sphere", "radius": 0.09, "color": "ff2a2a", "label": "Red ball"}
	check(Commands.validate(request, "another", 100.0) != "", "Stale instance rejected")
	check(Commands.validate(request, "test-instance", 111.0) != "", "Expired action rejected")
	var bad := request.duplicate()
	bad.radius = NAN
	check(Commands.validate(bad, "test-instance", 100.0) != "", "Nonfinite geometry rejected")
	bad = request.duplicate()
	bad.shape = "script"
	check(Commands.validate(bad, "test-instance", 100.0) != "", "No arbitrary scene-code action")
	var result := commands.execute(request, 100.0)
	check(result.status == "done" and is_instance_valid(office.hologram.projection), "Receipt requires actual model in live scene")
	var ball: Node3D = office.hologram.projection
	check(is_equal_approx(ball.get_child(0).mesh.radius, 0.09) and ball.get_child(0).scale == Vector3.ONE, "Requested ball dimensions preserved")
	check(commands.execute(request, 100.0) == result and office.hologram.projection == ball, "Replayed ID never creates a second object")
	bad = request.duplicate()
	bad.id = "cd".repeat(16)
	check(commands.execute(bad, 100.0).status == "error", "Occupied podium is not replaced implicitly")
	var pose := Transform3D(Basis.IDENTITY, ball.global_position + Vector3(0, 0, 1))
	check(office.fabricator.begin_grab(pose, Vector3.FORWARD), "Created ball participates in actual targeted pickup")
	check(office.fabricator.held == ball and office.hologram.projection == null, "Pickup transfers the actual live ball")
	office.fabricator.end_grab()
	office.fabricator.return_held()
	check(is_instance_valid(office.hologram.projection) and office.hologram.projection.has_meta("scene_primitive") and office.fabricator.objects.is_empty(), "Return object also works for the procedural ball")
	check(office.fabricator.next_output(), "Ready objects recognizes the ball without a generation job")
	office.free()
	print("HERMES_LIVE_FEEDBACK_TESTS " + JSON.stringify({"checks": checks, "failures": failures}))
	quit(0 if failures.is_empty() else 1)
