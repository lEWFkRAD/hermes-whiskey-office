extends SceneTree
## Run: godot --headless --path app --script res://test_xr_workbench.gd

const XRWorkbench = preload("res://xr_workbench.gd")
var failures: Array[String] = []

class PointerProbe:
	extends "res://xr_workbench.gd"
	var events: Array[InputEvent] = []
	func _dispatch_input(event: InputEvent) -> void:
		events.append(event)
	func button_events() -> Array[InputEventMouseButton]:
		var result: Array[InputEventMouseButton] = []
		for event in events:
			if event is InputEventMouseButton:
				result.append(event)
		return result

func check(value: bool, message: String) -> void:
	if not value:
		failures.append(message)

func _initialize() -> void:
	call_deferred("run_checks")

func run_checks() -> void:
	var transform := Transform3D.IDENTITY
	check(XRWorkbench.ray_to_uv(transform, Vector3(0, 0, 1), Vector3.FORWARD).is_equal_approx(Vector2(0.5, 0.5)), "Center ray maps to UV center")
	check(XRWorkbench.ray_to_uv(transform, Vector3(-0.64, 0.4, 1), Vector3.FORWARD).is_equal_approx(Vector2.ZERO), "Top-left maps to UV zero")
	check(XRWorkbench.ray_to_uv(transform, Vector3(0.641, 0, 1), Vector3.FORWARD) == XRWorkbench.MISS, "Outside width misses")
	check(XRWorkbench.ray_to_uv(transform, Vector3(0, 0.401, 1), Vector3.FORWARD) == XRWorkbench.MISS, "Outside height misses")
	check(XRWorkbench.ray_to_uv(transform, Vector3(0, 0, -1), Vector3.BACK) == XRWorkbench.MISS, "Back-face ray cannot activate UI")
	check(XRWorkbench.ray_to_uv(transform, Vector3(0, 0, 1), Vector3.RIGHT) == XRWorkbench.MISS, "Parallel ray misses")
	check(XRWorkbench.ray_to_uv(transform, Vector3(0, 0, 1), Vector3.BACK) == XRWorkbench.MISS, "Ray pointing away misses")
	check(XRWorkbench.ray_to_uv(transform, Vector3.ZERO, Vector3.ZERO) == XRWorkbench.MISS, "Lost tracking zero direction misses")
	var moved := Transform3D(Basis(Vector3.UP, 0.7), Vector3(3, 1.4, -2))
	check(XRWorkbench.ray_to_uv(moved, moved * Vector3(0.32, 0.2, 1), moved.basis * Vector3.FORWARD).is_equal_approx(Vector2(0.75, 0.25)), "Transformed world ray retains correct UV")

	var panel := PointerProbe.new()
	root.add_child(panel)
	panel._opened = true
	panel._built = true
	panel.show()
	var origin := Vector3(0, 0, 1)
	panel.point(origin, Vector3.FORWARD, true)
	check(panel.button_events().is_empty(), "Opening with trigger held cannot click")
	panel.point(origin, Vector3.FORWARD, false)
	panel.point(origin, Vector3.FORWARD, true)
	panel.point(origin, Vector3.FORWARD, true)
	panel.point(origin, Vector3.FORWARD, false)
	var clicks := panel.button_events()
	check(clicks.size() == 2, "Held trigger emits one down and one up")
	if clicks.size() == 2:
		check(clicks[0].pressed and not clicks[1].pressed, "Click event order is down then up")
		check(clicks[0].position == Vector2(640, 400), "UV converts to viewport pixels")
		check(clicks[0].button_mask == MOUSE_BUTTON_MASK_LEFT and clicks[1].button_mask == 0, "Button masks match pressed state")
	panel.events.clear()
	panel.point(origin, Vector3.FORWARD, true)
	panel.point(origin, Vector3.ZERO, true)
	panel.point(origin, Vector3.FORWARD, true)
	clicks = panel.button_events()
	check(clicks.size() == 2, "Tracking loss releases, held reentry does not press")
	if clicks.size() == 2:
		check(not clicks[1].pressed and clicks[1].position == XRWorkbench.OUTSIDE, "Off-panel release cancels rather than clicking last hovered control")
	panel.point(origin, Vector3.FORWARD, false)
	panel.events.clear()
	panel.point(Vector3(2, 0, 1), Vector3.FORWARD, true)
	panel.point(origin, Vector3.FORWARD, true)
	check(panel.button_events().is_empty(), "Press starting outside cannot activate on entry")
	panel.point(origin, Vector3.FORWARD, false)
	panel.point(origin, Vector3.FORWARD, true)
	panel.events.clear()
	panel.close_panel()
	clicks = panel.button_events()
	check(clicks.size() == 1 and not clicks[0].pressed, "Closing cancels active pointer press")
	check(not panel.is_open(), "Closed panel stops pointer interaction")
	check(not panel.enable_passthrough(null, true), "Missing XR interface returns unavailable")
	panel.free()
	var head := Camera3D.new()
	root.add_child(head)
	head.position = Vector3(1, 1.65, 2)
	head.rotation = Vector3(0.15, 0.4, 0)
	var built := XRWorkbench.new()
	root.add_child(built)
	built.setup(head)
	check(built.viewport.size == Vector2i(1280, 800), "Real helper builds the requested viewport")
	check(is_instance_valid(built.widget), "Real helper creates the existing workbench widget")
	built.open_panel()
	check(built.is_open(), "Built panel opens")
	check(is_equal_approx(built.global_position.distance_to(head.global_position), 1.15), "Panel opens 1.15m from head")
	check(built.global_basis.z.is_equal_approx(head.global_basis.z), "Panel front faces the head without mirroring")
	built.widget.close_requested.emit()
	check(not built.is_open(), "Widget close signal closes world panel")
	built.free()
	head.free()
	print("HERMES_XR_WORKBENCH_TESTS " + JSON.stringify({"passed": failures.is_empty(), "failures": failures}))
	quit(0 if failures.is_empty() else 1)
