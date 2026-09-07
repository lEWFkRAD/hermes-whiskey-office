extends SceneTree
const Podium = preload("res://office_hologram.gd")
var failures: Array[String] = []
var checks := 0

class SurfaceHarness:
	extends "res://desktop_surface.gd"
	var commands: Array[Dictionary] = []
	func _process(_delta: float) -> void: pass
	func _emit_command(value: Dictionary) -> bool:
		commands.append(value)
		return true

func check(value: bool, label: String) -> void:
	checks += 1
	if not value: failures.append(label)

func model(path: String) -> Node3D:
	var packed := load(path) as PackedScene
	return packed.instantiate() as Node3D if packed else null

func _initialize() -> void: run.call_deferred()

func run() -> void:
	var head := Camera3D.new()
	root.add_child(head)
	head.position = Vector3(1.85, 1.85, 0.7)
	head.look_at(Podium.CENTER + Vector3(0, 1.2, 0))
	var podium := Podium.new()
	root.add_child(podium)
	podium.setup(head, model, false)
	check(podium.choices.size() >= 20, "Original and decorative libraries are available")
	var object := MeshInstance3D.new()
	object.mesh = BoxMesh.new()
	object.mesh.size = Vector3(4, 2, 3)
	var original := StandardMaterial3D.new()
	original.albedo_color = Color.RED
	object.material_override = original
	check(podium.present_model(object, "Fixture table"), "Arbitrary mesh can be projected")
	check(object.material_override == podium._object_material, "Runtime hologram material applied")
	check(original.albedo_color == Color.RED, "Source material resource remains untouched")
	var bounds: AABB = Podium.model_bounds(podium.projection)
	check(bounds.size.x <= 1.051 and bounds.size.y <= 0.951 and bounds.size.z <= 1.051, "Large model fits podium")
	podium.set_readable(true)
	check(object.material_override == original, "Readable mode restores original material")
	podium.set_readable(false)
	var before: Node3D = podium.projection
	check(not podium.open_index(-1) and podium.projection == before, "Invalid selection preserves presentation")
	var empty := Node3D.new()
	check(not podium.present_model(empty, "Empty") and podium.projection == before, "Empty geometry preserves presentation")
	podium.resize(100)
	check(is_equal_approx(podium.size_factor, 1.7), "Projection enlargement bounded")
	podium.resize(0.0001)
	check(is_equal_approx(podium.size_factor, 0.55), "Projection reduction bounded")
	for identifier in ["desk", "keyboard", "window-palm", "shared-work-island", "turntable-reference"]:
		var found := false
		for i in podium.choices.size():
			if str(podium.choices[i].id) == identifier:
				found = true
				check(podium.open_index(i), identifier + " projects from actual library")
				break
		check(found, identifier + " catalogued")
	var surface := SurfaceHarness.new()
	root.add_child(surface)
	surface.setup("", head)
	surface.open_panel()
	surface.set_spatial_visible(false)
	surface.set_panel_scale(1.2)
	var rest := surface.global_transform
	var material := surface._panel.material_override
	var image := Image.create(8, 8, false, Image.FORMAT_RGBA8)
	image.fill(Color.WHITE)
	surface.texture = ImageTexture.create_from_image(image)
	surface.connected = true
	check(podium.project_window(surface), "Existing live window can be mounted")
	check(surface.is_open() and surface.get_spatial_visible(), "Mounted window retains its logical open state")
	check(surface._panel.material_override == podium._screen_material, "Mounted window uses live shader")
	podium.refresh_window()
	check(podium._screen_material.get_shader_parameter("live_texture") == surface.texture, "Same changing texture resource supplies projection")
	var origin := surface.global_position + surface.global_basis.z * 2
	var direction := -surface.global_basis.z
	surface.point(origin, direction, false)
	surface.point(origin, direction, true)
	surface.point(origin, direction, false)
	check(surface.commands.any(func(c: Dictionary) -> bool: return c.get("type") == "pointer_button" and c.get("pressed") == true), "Projected window forwards deliberate pointer press")
	surface.point(origin, direction, true)
	surface.point(origin, Vector3.ZERO, true)
	check(surface.commands.any(func(c: Dictionary) -> bool: return c.get("type") == "pointer_cancel"), "Tracking loss cancels projected pointer")
	podium.clear()
	check(surface.global_transform.is_equal_approx(rest), "Clear restores exact window placement")
	check(is_equal_approx(surface.get_panel_scale(), 1.2) and not surface.get_spatial_visible(), "Clear restores scale and presentation mode")
	check(surface._panel.material_override == material and surface.is_open(), "Clear restores material without disconnecting source")
	podium.project_window(surface)
	surface.close_panel()
	podium.refresh_window()
	check(podium.live_window == null and not surface.is_open(), "Closing source clears projection without reopening it")
	var path := "user://hologram-test.txt"
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_string("First artifact revision")
	file.close()
	check(podium.load_file(path), "Text artifact projects")
	check(podium._document != null and podium._flat_texture != null, "Text uses a real rendered document texture")
	file = FileAccess.open(path, FileAccess.WRITE)
	file.store_string("Second artifact revision")
	file.close()
	podium._process(1.1)
	var texts := podium._document.find_children("*", "Label", true, false)
	check(texts.size() == 1 and texts[0].text.contains("Second artifact revision"), "Changed file refreshes its live rendition")
	DirAccess.remove_absolute(path)
	podium._process(1.1)
	check(podium._document != null, "Missing source keeps last preview")
	podium.clear()
	check(not podium._rings.visible and podium.projection == null, "Empty podium has no glowing projection")
	podium.queue_free()
	surface.queue_free()
	head.queue_free()
	await process_frame
	print("HERMES_HOLOGRAM_TESTS ", JSON.stringify({"checks": checks, "passed": failures.is_empty(), "failures": failures}))
	quit(0 if failures.is_empty() else 1)
