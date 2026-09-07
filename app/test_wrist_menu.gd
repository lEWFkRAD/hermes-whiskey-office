extends SceneTree
## Spatial hand attachment, readable orientation and tracking-loss behavior.
const Menu = preload("res://wrist_menu.gd")
var checks := 0
var failures: Array[String] = []

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok: failures.append(label)

func _initialize() -> void:
	run.call_deferred()

func run() -> void:
	var head := Node3D.new()
	root.add_child(head)
	head.position = Vector3(0, 1.7, 0)
	var menu = Menu.new()
	root.add_child(menu)
	menu.setup(head)
	var wrist := Vector3(0.2, 1.25, -0.65)
	menu.open_near(wrist, true)
	menu.present({"open": true, "selected_index": 2, "progress": 0.0, "dialangle_degrees": 82.0})
	menu.follow_hand(wrist, Basis.IDENTITY, 0.016)
	check(menu._cuff.is_visible_in_tree(), "Valid tracked input shows wrist cuff")
	check(menu._cuff.global_position.is_equal_approx(wrist), "Cuff attaches to physical wrist without menu offset")
	var original: Vector3 = menu.global_position
	var moved := wrist + Vector3(0.12, 0.04, 0)
	menu.follow_hand(moved, Basis(Vector3.DOWN, 0.6), 0.016)
	check(menu.global_position.is_equal_approx(original), "Expanded menu stays stationary while hand moves")
	check(menu._cuff.global_position.is_equal_approx(moved), "Cuff stays on the wrist independently of stationary menu")
	check(menu._cuff.global_basis.is_equal_approx(Basis(Vector3.DOWN, 0.6)), "Cuff follows wrist rotation")
	check(menu.global_basis.is_equal_approx(head.global_basis), "Wrist roll cannot rotate readable labels")
	var still: Vector3 = menu.global_position
	menu.follow_hand(moved, Basis.IDENTITY, 0.0)
	check(menu.global_position.is_equal_approx(still), "Zero elapsed time does not move labels")
	for frame in 12: menu.follow_hand(moved, Basis.IDENTITY, 1.0/90.0)
	check(menu.global_position.is_equal_approx(original), "Menu remains anchored across headset frames")
	var jump := moved + Vector3(0.7, 0, 0)
	menu.follow_hand(jump, Basis.IDENTITY, 0.016)
	check(menu.global_position.is_equal_approx(original), "Large hand movements cannot drag expanded controls")
	menu.follow_hand(head.global_position, Basis.IDENTITY, 0.016)
	check((menu.global_position-head.global_position).dot(-head.global_basis.z) >= 0.3999, "Hand near the face keeps labels beyond minimum depth")
	head.position.z -= 0.15
	menu.follow_hand(head.global_position, Basis.IDENTITY, 0.008)
	check(menu.global_position.is_equal_approx(original), "Head movement does not drag world-anchored menu")
	menu.present({"open": true, "selected_index": 2, "progress": 0.7, "dialangle_degrees": 170.0})
	check(is_equal_approx(menu._canvas.angle, 90.0), "Pinch indicator stays on latched sector despite wrist movement")
	check(menu._cuff_material.albedo_color.r > 0.9, "Pinch changes cuff to amber")
	menu.present({"open": false})
	check(not menu._cuff.is_visible_in_tree(), "Closing hides even the world-attached cuff")
	menu.open_near(Vector3.ZERO, false)
	var desktop: Transform3D = menu.global_transform
	menu.follow_hand(jump, Basis.IDENTITY, 0.016)
	check(menu.global_transform.is_equal_approx(desktop) and not menu._cuff.visible, "Desktop fallback does not pretend a tracked wrist exists")
	menu.open_near(wrist, true)
	menu.follow_hand(Vector3(NAN, 0, 0), Basis.IDENTITY, 0.016)
	check(not menu.visible and menu.global_position.is_finite(), "Invalid tracking hides ring without poisoning transforms")
	menu.free()
	head.free()
	print("HERMES_WRIST_MENU_TESTS " + JSON.stringify({"passed": failures.is_empty(), "checks": checks, "failures": failures}))
	quit(0 if failures.is_empty() else 1)
