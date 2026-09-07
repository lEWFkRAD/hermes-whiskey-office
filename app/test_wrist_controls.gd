extends SceneTree
## Real controls/dial and main input routing, with no viewport UI, assets, XR
## devices, filesystem IPC or app actions. Run with --headless --xr-mode off.
const Controls = preload("res://wrist_controls.gd")
var failures: Array[String] = []
var checks := 0

class FakeMenu:
	extends Node3D
	var page_title := ""
	var entries: Array = []
	var state: Dictionary = {}
	var openings := 0
	var follow_count := 0
	var last_wrist := Vector3.ZERO
	func follow_hand(wrist: Vector3, _basis: Basis, _delta: float) -> void:
		follow_count += 1
		last_wrist = wrist
	func set_page(title: String, values: Array) -> void:
		page_title = title
		entries = values.duplicate(true)
	func open_near(_wrist: Vector3, _tracked_hand: bool) -> void:
		openings += 1
		show()
	func present(value: Dictionary) -> void:
		state = value.duplicate(true)
		visible = bool(state.get("open", false))

class FakeDesktop:
	extends Node
	var keys: Array[InputEventKey] = []
	var commands: Array[Dictionary] = []
	var releases := 0
	var opened := true
	func is_open() -> bool:
		return opened
	func open_panel() -> void:
		opened = true
	func close_panel() -> void:
		opened = false
	func release_input() -> void:
		releases += 1
	func key_event(event: InputEventKey) -> bool:
		keys.append(event.duplicate() as InputEventKey)
		return true
	func send_command(kind: String, params: Dictionary) -> String:
		commands.append({"type": kind, "params": params.duplicate(true)})
		return "fake-explicit-command"

class MainHarness:
	extends "res://main.gd"
	# Keep actual _input and handle_wrist_action. Suppress the app's startup and
	# rendering loop so these routing tests never load assets or read live state.
	func _ready() -> void:
		pass
	func _process(_delta: float) -> void:
		pass

func check(value: bool, message: String) -> void:
	checks += 1
	if not value:
		failures.append(message)

func key(code: int, pressed: bool, echo := false) -> InputEventKey:
	var event := InputEventKey.new()
	event.physical_keycode = code
	event.keycode = code
	event.pressed = pressed
	event.echo = echo
	return event

func fresh():
	var controls = Controls.new()
	root.add_child(controls)
	# Inject the menu dependency instead of calling setup(), which constructs
	# the actual SubViewport. All controls and dial behavior stays production.
	controls.menu = FakeMenu.new()
	controls.add_child(controls.menu)
	controls._set_page("home")
	return controls

func advance(controls, duration: float) -> void:
	var remaining := duration
	while remaining > 0.000001:
		var delta := minf(remaining, 0.05)
		controls.update_desktop(delta)
		remaining -= delta

func open_page(controls, page: String) -> void:
	controls.open_desktop()
	if page != "home":
		controls._set_page(page)
		controls.menu.present(controls.dial.open_at(controls._basis))
	advance(controls, 0.01) # Observe open fingers before the next pinch.

func browse(controls, index: int) -> void:
	for step: int in range(index):
		check(controls.input(key(KEY_RIGHT, true)), "Right browse press is captured")
		check(controls.input(key(KEY_RIGHT, false)), "Right browse release is captured")
		advance(controls, 0.01)
	check(int(controls.menu.state.get("selected_index", -1)) == index, "Desktop browse reaches requested sector " + str(index))

func qualified_press(controls) -> void:
	check(controls.input(key(KEY_ENTER, true)), "Enter begins a captured menu pinch")
	advance(controls, 0.20)

func release_selection(controls) -> void:
	check(controls.input(key(KEY_ENTER, false)), "Enter release stays captured by menu")
	advance(controls, 0.01)

func hand_sample(degrees := 0.0, pose := true, pinching := false, valid := true) -> Dictionary:
	return {"gesture_valid": valid, "menu_pose": pose, "pinching": pinching,
		"wrist_basis": Basis(Vector3.DOWN, deg_to_rad(degrees)), "wrist_origin": Vector3(0, 1.1, -0.5)}

func advance_hand(controls, sample: Dictionary, duration: float) -> void:
	var remaining := duration
	while remaining > 0.000001:
		var delta := minf(remaining, 0.05)
		# The real XR entry point resets this at the start of each frame. Drive
		# its hand helper directly so no controller/device stub is necessary.
		controls._consumed_frame = false
		controls._update_hand(sample, delta)
		remaining -= delta

func _initialize() -> void:
	call_deferred("run_checks")

func run_checks() -> void:
	for page_name: String in Controls.PAGES:
		var rows: Array = Controls.PAGES[page_name]
		check(rows.size() == 8, "Page has exactly eight choices: " + page_name)
		var seen: Dictionary = {}
		for row: Array in rows:
			var id := str(row[0])
			check(not id.is_empty() and not seen.has(id), "Page IDs are nonempty and unique: " + page_name + "/" + id)
			seen[id] = true
			check(id not in ["approve", "reject", "allow", "deny", "permission_allow", "permission_deny"] and not id.ends_with("_approve") and not id.ends_with("_reject"), "Menu IDs never directly resolve approval: " + id)
		for index: int in range(rows.size()):
			var controls = fresh()
			var actions: Array[String] = []
			controls.action_requested.connect(func(id: String) -> void: actions.append(id))
			open_page(controls, page_name)
			browse(controls, index)
			var id := str(rows[index][0])
			qualified_press(controls)
			check(actions.is_empty(), "A held selection never emits early: " + id)
			release_selection(controls)
			if id.begins_with("page_"):
				check(actions.is_empty() and controls.page == id.trim_prefix("page_") and controls.dial.is_open(), "Page selection changes the open menu without app action: " + id)
			elif id == "camera_unavailable":
				check(actions.is_empty() and controls.dial.is_open() and controls.page == "senses", "Unavailable camera cannot emit an action")
				check(not bool(controls.menu.entries[index].get("enabled", true)), "Camera remains visibly disabled")
			else:
				check(actions == [id] and not controls.dial.is_open(), "Qualified release emits exactly the advertised route: " + id)
			advance(controls, 0.02)
			check(actions.size() <= 1, "Released selection does not repeat: " + id)
			controls.free()

	var controls = fresh()
	var actions: Array[String] = []
	controls.action_requested.connect(func(id: String) -> void: actions.append(id))
	open_page(controls, "home")
	qualified_press(controls)
	release_selection(controls)
	check(controls.page == "build" and actions.is_empty(), "Home Build opens its submenu")
	# A second press before the submenu sees open fingers is not a fresh pinch.
	controls.input(key(KEY_ENTER, true))
	advance(controls, 0.25)
	release_selection(controls)
	check(actions.is_empty() and controls.dial.is_open(), "Submenu ignores a pinch carried through its opening")
	qualified_press(controls)
	release_selection(controls)
	check(actions == ["nav_new_session"], "Fresh pinch after submenu release activates its own first slot")
	controls.free()

	controls = fresh()
	actions = []
	controls.action_requested.connect(func(id: String) -> void: actions.append(id))
	open_page(controls, "home")
	browse(controls, 1)
	controls.input(key(KEY_ENTER, true))
	advance(controls, 0.10)
	release_selection(controls)
	check(actions.is_empty() and controls.dial.is_open(), "Short desktop Enter tap does not select")
	qualified_press(controls)
	controls.input(key(KEY_RIGHT, true))
	advance(controls, 0.05)
	controls.input(key(KEY_RIGHT, false))
	check(actions.is_empty(), "Arrow movement during a qualified hold does not activate")
	release_selection(controls)
	check(actions == ["voice"], "Enter release activates Talk latched before held movement")
	controls.free()

	# Exercise the actual main._input ordering, not a copied routing algorithm.
	var main := MainHarness.new()
	root.add_child(main)
	var desktop := FakeDesktop.new()
	main.add_child(desktop)
	main.desktop_surface = desktop
	for cancel_key: int in [KEY_ESCAPE, KEY_F10]:
		controls = fresh()
		main.wrist_controls = controls
		var cancelled_actions: Array[String] = []
		controls.action_requested.connect(func(id: String) -> void: cancelled_actions.append(id))
		open_page(controls, "home")
		desktop.keys.clear()
		main._input(key(KEY_ENTER, true))
		advance(controls, 0.20)
		main._input(key(cancel_key, true))
		main._input(key(cancel_key, false))
		main._input(key(KEY_ENTER, false))
		advance(controls, 0.05)
		check(not controls.dial.is_open() and cancelled_actions.is_empty(), "Escape/F10 cancels qualified selection without action: " + str(cancel_key))
		check(desktop.keys.is_empty(), "Cancelled menu consumes cancel and held-key releases without forwarding Hermes keys: " + str(cancel_key))
		check(desktop.opened, "Cancelling radial menu leaves existing Hermes desktop open")
		controls.free()
	main.wrist_controls = null
	desktop.commands.clear()
	main.handle_wrist_action("nav_approvals")
	check(desktop.commands.size() == 1 and desktop.commands[0] == {"type": "navigate_hermes", "params": {"destination": "approvals"}}, "Approvals route opens actual Hermes review UI without approving/rejecting")
	main.free()

	controls = fresh()
	var hand_actions: Array[String] = []
	controls.action_requested.connect(func(id: String) -> void: hand_actions.append(id))
	advance_hand(controls, hand_sample(0, true, false, false), 0.2)
	advance_hand(controls, hand_sample(), 0.35)
	check(controls.dial.is_open() and controls.mode == "hand", "Initial hand invocation needs no earlier relaxed pose")
	advance_hand(controls, hand_sample(18), 0.01)
	advance_hand(controls, hand_sample(18, true, true), 0.20)
	advance_hand(controls, hand_sample(18), 0.01)
	check(hand_actions == ["voice"] and not controls.dial.is_open(), "Hand selection emits Talk once and closes")
	advance_hand(controls, hand_sample(18), 0.80)
	check(not controls.dial.is_open() and hand_actions == ["voice"], "Persistent invocation pose cannot reopen after hand action")
	advance_hand(controls, hand_sample(18, true, false, false), 0.20)
	advance_hand(controls, hand_sample(18), 0.60)
	check(not controls.dial.is_open(), "Tracking disappearance cannot count as relaxing after an action")
	advance_hand(controls, hand_sample(18, false), 0.05)
	advance_hand(controls, hand_sample(18), 0.30)
	check(not controls.dial.is_open(), "Rearmed hand still requires a complete new invocation dwell")
	advance_hand(controls, hand_sample(18), 0.05)
	check(controls.dial.is_open(), "Tracked relaxed pose rearms a subsequent deliberate invocation")
	controls.cancel()
	advance_hand(controls, hand_sample(18), 0.80)
	check(not controls.dial.is_open(), "Persistent hand pose cannot reopen after cancellation")
	# Explicit F9 opening does not depend on the hand's automatic rearm latch.
	check(controls.input(key(KEY_F9, true)), "F9 down is consumed while automatic hand invocation is disarmed")
	check(controls.input(key(KEY_F9, false)) and controls.dial.is_open() and controls.mode == "desktop", "F9 can explicitly open despite a persistent hand pose")
	check(controls.input(key(KEY_F9, true)), "F9 cancellation down is consumed")
	check(controls.input(key(KEY_F9, true, true)) and not controls.dial.is_open(), "Held F9 repeat cannot reopen a cancelled menu")
	check(controls.input(key(KEY_F9, false)), "F9 release remains consumed after cancellation")
	controls.free()

	controls = fresh()
	advance_hand(controls, hand_sample(), 0.35)
	advance_hand(controls, hand_sample(0, true, false, false), 0.05)
	check(not controls.dial.is_open(), "Tracking loss cancels an open hand menu")
	advance_hand(controls, hand_sample(), 0.80)
	check(not controls.dial.is_open(), "Tracking regain with unchanged menu pose does not reopen")
	advance_hand(controls, hand_sample(0, false), 0.05)
	advance_hand(controls, hand_sample(), 0.35)
	check(controls.dial.is_open(), "Relaxing after tracking-loss cancellation restores invocation")
	controls.free()

	controls = fresh()
	advance_hand(controls, hand_sample(), 0.20)
	advance_hand(controls, hand_sample(0, true, false, false), 0.05)
	advance_hand(controls, hand_sample(), 0.80)
	check(not controls.dial.is_open(), "Tracking loss during an incomplete invocation also requires relaxing")
	advance_hand(controls, hand_sample(0, false), 0.05)
	advance_hand(controls, hand_sample(), 0.35)
	check(controls.dial.is_open(), "Interrupted invocation can restart after a tracked relaxed pose")
	controls.free()

	controls = fresh()
	var submenu_actions: Array[String] = []
	controls.action_requested.connect(func(id: String) -> void: submenu_actions.append(id))
	advance_hand(controls, hand_sample(), 0.35)
	advance_hand(controls, hand_sample(0, true, true), 0.20)
	advance_hand(controls, hand_sample(), 0.01)
	check(controls.page == "build" and controls.dial.is_open() and submenu_actions.is_empty(), "Hand page transition stays open without relaxing invocation pose")
	advance_hand(controls, hand_sample(0, true, true), 0.25)
	advance_hand(controls, hand_sample(), 0.01)
	check(controls.dial.is_open() and submenu_actions.is_empty(), "Hand submenu still ignores carried pinch until release")
	advance_hand(controls, hand_sample(0, true, true), 0.20)
	advance_hand(controls, hand_sample(), 0.01)
	check(submenu_actions == ["nav_new_session"] and not controls.dial.is_open(), "Hand submenu accepts a fresh pinch without forcing another invocation")
	controls.free()

	# Controller conversion is checked by user-visible dial behavior. A twist
	controls = fresh()
	advance_hand(controls, hand_sample(), 0.35)
	var followed_before: int = controls.menu.follow_count
	var moved_hand := hand_sample()
	moved_hand.wrist_origin = Vector3(0.2, 1.4, -0.6)
	advance_hand(controls, moved_hand, 0.02)
	check(controls.menu.follow_count > followed_before and controls.menu.last_wrist == moved_hand.wrist_origin, "Open hand controls forward every new wrist position")
	moved_hand.wrist_origin = Vector3(NAN, 1.4, -0.6)
	advance_hand(controls, moved_hand, 0.02)
	check(not controls.dial.is_open() and not controls.menu.visible, "Invalid wrist position cancels selection and hides rings")
	controls.free()

	# Controller conversion is checked by user-visible dial behavior. A twist
	# around aim advances one sector; rotating about its palm/up axis does not.
	var controller := Basis.from_euler(Vector3(0.35, -0.6, 0.2))
	var neutral: Basis = Controls._controller_basis(controller)
	check(neutral.is_finite() and is_equal_approx(neutral.determinant(), 1.0), "Controller conversion yields a valid rotation")
	var dial = Controls.Dial.new()
	var ids: Array = []
	for row: Array in Controls.PAGES["home"]:
		ids.append(row[0])
	dial.set_slots(ids)
	dial.open_at(neutral)
	dial.update({"valid": true, "menu_pose": true, "pinching": false, "wrist_basis": neutral}, 0.01)
	var twisted := Basis(-controller.z.normalized(), deg_to_rad(18.0)) * controller
	var state: Dictionary = dial.update({"valid": true, "menu_pose": true, "pinching": false, "wrist_basis": Controls._controller_basis(twisted)}, 0.01)
	check(state.selected_index == 1 and is_equal_approx(float(state.roll_degrees), 18.0), "Controller aim-axis twist advances the same positive dial detent")
	dial.open_at(neutral)
	dial.update({"valid": true, "menu_pose": true, "pinching": false, "wrist_basis": neutral}, 0.01)
	var palm_spin := Basis(controller.y.normalized(), deg_to_rad(30.0)) * controller
	state = dial.update({"valid": true, "menu_pose": true, "pinching": false, "wrist_basis": Controls._controller_basis(palm_spin)}, 0.01)
	check(state.selected_index == 0 and is_zero_approx(float(state.roll_degrees)), "Controller palm-axis rotation is not interpreted as wrist roll")
	print("HERMES_WRIST_CONTROLS_TESTS " + JSON.stringify({"passed": failures.is_empty(), "checks": checks, "failures": failures}))
	quit(0 if failures.is_empty() else 1)
