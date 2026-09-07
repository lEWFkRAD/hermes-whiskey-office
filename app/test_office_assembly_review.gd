extends SceneTree
const Review = preload("res://office_assembly_review.gd")
var checked := 0
var failures: Array[String] = []

func check(value: bool, message: String) -> void:
	checked += 1
	if not value: failures.append(message)

func model(path: String) -> Node3D:
	var resource := load(path) as PackedScene
	return resource.instantiate() as Node3D if resource else null

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	var room := model("res://assets/whiskey-room.glb")
	if not room:
		check(false, "Room imported")
		finish()
		return
	root.add_child(room)
	var review := Review.new()
	root.add_child(review)
	review.setup(room, model)
	if not review.choices.is_empty():
		var probe := model(str(review.choices[0].library_path))
		var meshes := probe.find_children("*", "MeshInstance3D", true, false)
		if not meshes.is_empty():
			var metadata: Dictionary = {}
			for key in meshes[0].get_meta_list(): metadata[str(key)] = meshes[0].get_meta(key)
			print("ASSEMBLY_IMPORT_METADATA ", JSON.stringify({"name": str(meshes[0].name), "meta": metadata}))
		probe.free()
	check(review.choices.size() >= 5, "Desk, shelves, monitor, keyboard and computer have review libraries")
	for i in review.choices.size():
		var spec: Dictionary = review.choices[i]
		var label := str(spec.id)
		check(review.open_index(i), label + " opens")
		if not review.is_open(): continue
		check(review._parts.size() == spec.get("library_parts", {}).size(), label + " all source part IDs imported")
		check(not review._hidden.is_empty(), label + " original batches hidden")
		var before: Array[Transform3D] = []
		var identities: Dictionary = {}
		for part: Node3D in review._parts:
			before.append(part.transform)
			identities[str(part.get_meta("office_part_id"))] = true
		check(identities.size() == review._parts.size(), label + " unique part identities")
		review.set_exploded(true)
		if label == "keyboard":
			var lowest_cap := INF
			var plate := -INF
			for part: Node3D in review._parts:
				var role: String = Review.identity(part, "semantic_role")
				if role == "keyboard_keycap": lowest_cap = minf(lowest_cap, part.global_position.y)
				if role == "keyboard_switch_plate": plate = part.global_position.y
			check(is_finite(lowest_cap) and is_finite(plate) and lowest_cap > plate + 0.05, "Keyboard keys stay above the switch plate in separated review")
		var moved := 0
		for j in review._parts.size():
			if review._parts[j].transform != before[j]: moved += 1
		check(moved > 0, label + " separated parts actually move")
		for cycle in 3:
			review.set_exploded(false)
			review.set_exploded(true)
		review.set_exploded(false)
		var exact := true
		for j in review._parts.size(): exact = exact and review._parts[j].transform == before[j]
		check(exact, label + " exact reassembly after repeated cycles")
		var hidden := review._hidden.duplicate()
		review.close_review()
		check(not review.is_open() and review._parts.is_empty(), label + " review unloaded")
		var restored := true
		for node: Node3D in hidden: restored = restored and node.visible
		check(restored, label + " original room restored")
	check(not review.open_index(-1) and not review.open_index(review.choices.size()), "Invalid selection rejected")
	review.queue_free()
	room.queue_free()
	await process_frame
	finish()

func finish() -> void:
	print("HERMES_OFFICE_ASSEMBLY_TESTS ", JSON.stringify({"checks": checked, "passed": failures.is_empty(), "failures": failures}))
	quit(0 if failures.is_empty() else 1)
