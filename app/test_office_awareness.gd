extends SceneTree
const Awareness = preload("res://office_awareness.gd")
class Office:
	extends Node3D
	var xr_active := false
	var camera: Node3D
	var xr_camera: Node3D
	var office_windows = null
	var hologram = null
	var fabricator = null
	var passthrough_active := false
func _initialize() -> void: run.call_deferred()
func run() -> void:
	var office := Office.new()
	root.add_child(office)
	office.camera = Node3D.new()
	office.add_child(office.camera)
	office.camera.position = Vector3(1.234, 1.7, -2)
	var state := Awareness.new()
	office.add_child(state)
	state.office = office
	state.path = "user://awareness-acceptance.json"
	var value := state.snapshot()
	assert(value.viewer_position_m == [1.23, 1.7, -2.0])
	assert(value.windows.is_empty())
	assert(value.mode == "desktop preview")
	assert(value.physical_camera == "not connected")
	assert(not value.has("document_contents"))
	state.publish()
	assert(FileAccess.file_exists(state.path))
	var written: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(state.path))
	assert(written.instance == state.instance and written.running)
	var path: String = state.path
	state.free()
	assert(not FileAccess.file_exists(path))
	office.free()
	print("HERMES_OFFICE_AWARENESS_TESTS: 8 checks passed")
	quit()
