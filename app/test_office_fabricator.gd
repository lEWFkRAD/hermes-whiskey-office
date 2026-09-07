extends SceneTree
const Fabricator = preload("res://office_fabricator.gd")
const Podium = preload("res://office_hologram.gd")
var failures: Array[String] = []
var checks := 0
func check(value: bool, message: String) -> void:
	checks += 1
	if not value: failures.append(message)
func _initialize() -> void: run.call_deferred()
func run() -> void:
	var camera := Camera3D.new()
	root.add_child(camera)
	var podium := Podium.new()
	root.add_child(podium)
	podium.setup(camera, func(_path: String) -> Node3D: return null, false)
	var maker := Fabricator.new()
	root.add_child(maker)
	maker.setup(podium, camera, false)
	var mesh := MeshInstance3D.new()
	mesh.mesh = BoxMesh.new()
	var material := StandardMaterial3D.new()
	material.albedo_color = Color.RED
	mesh.material_override = material
	check(podium.present_model(mesh, "Finished fixture"), "Completed geometry projects")
	podium.projection.set_meta("fabricated_id", "a".repeat(32))
	var item: Node3D = podium.projection
	var pose := Transform3D(Basis.IDENTITY, item.global_position + Vector3(0, 0, 2))
	var initial := item.global_transform
	check(maker.grab_input(pose, Vector3.FORWARD, true), "Tracked grip ray grabs the finished model")
	check(maker.held == item and not is_instance_valid(podium.projection), "Pickup detaches only the projection")
	check(mesh.material_override == material, "Pickup restores original full-color materials")
	check(item.global_transform.is_equal_approx(initial), "Pickup does not jump")
	pose.origin += Vector3(0.3, 0.4, 0)
	maker.grab_input(pose, Vector3.FORWARD, true)
	check(item.global_position.is_equal_approx(initial.origin + Vector3(0.3, 0.4, 0)), "Held object follows hand movement")
	pose.basis = Basis(Vector3.UP, 0.4)
	maker.grab_input(pose, Vector3.FORWARD, true)
	check(item.global_basis.is_equal_approx(pose.basis), "Held object follows wrist rotation")
	var placed := item.global_transform
	check(maker.grab_input(pose, Vector3.FORWARD, false), "Release is consumed")
	check(not maker.held and item.global_transform.is_equal_approx(placed), "Release leaves object placed")
	check(maker.placements.has("a".repeat(32)), "Placement is recorded")
	check(Fabricator.decode_transform(Fabricator.encode_transform(placed)).is_equal_approx(placed), "Position and rotation survive JSON representation")
	pose = Transform3D(Basis.IDENTITY, item.global_position + Vector3(0, 0, 2))
	maker.grab_input(pose, Vector3.FORWARD, true)
	check(maker.held == item, "Placed object can be picked up again")
	maker.grab_input(pose, Vector3.FORWARD, true, false)
	check(not maker.held, "Tracking loss releases safely")
	check(not maker.grab_input(pose, Vector3.FORWARD, true), "Tracking return does not regrab without release")
	maker.grab_input(pose, Vector3.FORWARD, false)
	check(maker.grab_input(pose, Vector3.FORWARD, true), "Fresh grip after tracking return works")
	maker.end_grab()
	maker.ray_limit = 0.1
	check(maker.pick(pose.origin, Vector3.FORWARD) == null, "A nearer window blocks selecting objects behind it")
	maker.ray_limit = 4.0
	camera.position = item.global_position + Vector3(0, 0, 2)
	camera.look_at(item.global_position)
	var click := InputEventMouseButton.new()
	click.button_index = MOUSE_BUTTON_LEFT
	click.pressed = true
	click.position = camera.unproject_position(item.global_position)
	check(maker.mouse_input(click, camera), "Desktop pointer grabs generated object")
	var move := InputEventMouseMotion.new()
	move.position = click.position + Vector2(30, 0)
	check(maker.mouse_input(move, camera), "Desktop drag owns motion while held")
	click.pressed = false
	click.position = move.position
	check(maker.mouse_input(click, camera) and not maker.held, "Desktop release places object")
	check(not maker.render_image(), "Model preview cannot be submitted as an image")
	var normal := MeshInstance3D.new()
	normal.mesh = BoxMesh.new()
	podium.present_model(normal, "Ordinary catalog model")
	check(podium.take_model() == null, "Existing catalog model is not treated as a generated output")
	check(not maker.valid_output({"id": "a".repeat(32), "phase": "ready", "path": "/tmp/other.glb"}), "Output must belong to the saved job and match its hash")
	print("HERMES_FABRICATOR_TESTS ", JSON.stringify({"checks": checks, "failures": failures}))
	maker.free()
	podium.free()
	camera.free()
	quit(0 if failures.is_empty() else 1)
