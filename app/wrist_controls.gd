extends Node
## Routes deliberate wrist selections to the existing app or room controls.
signal action_requested(action_id: String)

const Dial = preload("res://wrist_dial.gd")
const Menu = preload("res://wrist_menu.gd")
const PAGES := {
	"home": [
		["page_build", "Build", "Start work\nand choose resources"],
		["voice", "Dictate", "Record a draft\nSend when ready"],
		["voice_stop", "End voice", "Stop the open conversation\nkeep working quietly"],
		["share", "Discuss view", "Attach this view\nthen send when ready"],
		["nav_approvals", "Approvals", "Review the actual\nHermes request"],
		["page_windows", "Windows", "Place your workspace"],
		["window_source_loading-bay", "File tray", "Shared files and\nworking copies"],
		["page_senses", "Senses", "Voice, context and room"]
	],
	"build": [
		["nav_new_session", "New task", "Start a Hermes session"],
		["window_source_loading-bay", "Loading Bay", "Keep files and\nworking copies"],
		["nav_skills", "Skills", "Browse Hermes skills"],
		["tui", "Terminal", "The real Hermes TUI"],
		["nav_artifacts", "Artifacts", "Files and created work"],
		["page_podium", "Podium", "Project models, files\nand live windows"],
		["page_tools", "Tools", "Plugins, MCP and\nHermes capabilities"],
		["page_home", "Back", "Main tool wheel"]
	],
	"tools": [
		["nav_tools", "Tools", "Hermes capabilities"],
		["nav_plugins", "Plugins", "Installed Hermes plugins"],
		["nav_mcp", "MCP", "Connected tools in Hermes"],
		["nav_skills", "Skills", "Browse Hermes skills"],
		["nav_approvals", "Approvals", "Review the actual request"],
		["page_room", "Room", "Move around the study"],
		["nav_artifacts", "Documents", "Open Hermes artifacts"],
		["page_build", "Back", "Build controls"]
	],
	"podium": [
		["hologram_next", "Next asset", "Project the next model"],
		["page_fabricate", "Make object", "Image → model → pick up"],
		["hologram_window", "Live window", "Project the active app\nwith its existing controls"],
		["hologram_rotate", "Rotate", "Start or stop model rotation"],
		["page_projection", "Adjust", "Size and source controls"],
		["hologram_readable", "Readable", "Toggle hologram / full color"],
		["hologram_clear", "Clear", "Return the source window\nand empty the podium"],
		["page_build", "Back", "Build controls"]
	],
	"fabricate": [
		["fabricate_image", "Next image", "Preview Loading Bay\nInbox images"],
		["fabricate_render", "Render image", "Build the previewed image\nwith Object Studio"],
		["fabricate_quality", "Quality", "Switch Fast / Detailed"],
		["fabricate_ready", "Ready objects", "Put a finished model\non the podium"],
		["fabricate_return", "Return object", "Recall the last moved\nobject to the podium"],
		["window_source_loading-bay", "Loading Bay", "Add your source images"],
		["hologram_view", "At podium", "Move to the podium"],
		["page_podium", "Back", "Podium controls"]
	],
	"projection": [
		["hologram_larger", "Larger", "Enlarge projection"],
		["hologram_smaller", "Smaller", "Reduce projection"],
		["hologram_reset", "Reset size", "Restore presentation size"],
		["hologram_view", "At podium", "Move to the podium viewpoint"],
		["hologram_source", "Work in app", "Return the original window"],
		["hologram_file", "Open file", "Desktop file picker\nin desktop mode"],
		["hologram_clear", "Clear", "Empty the podium"],
		["page_podium", "Back", "Podium controls"]
	],
	"windows": [
		["page_sources", "Open window", "Choose a machine\nor connection"],
		["window_next", "Next", "Focus the next window"],
		["window_previous", "Previous", "Focus the previous window"],
		["window_arrange", "Arrange", "Arrange open windows"],
		["window_hide", "Hide", "Hide this window\nkeep its connection"],
		["window_reopen", "Reopen", "Restore the last\nhidden window"],
		["page_windowtools", "Window tools", "Keyboard, position\nand connection"],
		["page_home", "Back", "Main tool wheel"]
	],
	"windowtools": [
		["window_recenter", "Bring here", "Bring the active window closer"],
		["window_keyboard", "Keyboard", "Type in the active window"],
		["window_larger", "Larger", "Enlarge the active window"],
		["window_smaller", "Smaller", "Shrink the active window"],
		["window_disconnect", "Disconnect", "Close this local client\nremote work is not terminated"],
		["window_hide", "Hide", "Keep the connection open"],
		["page_sources", "Open window", "Choose another connection"],
		["page_windows", "Back", "Window controls"]
	],
	"senses": [
		["share", "Share view", "Attach one office image\nwithout sending it"],
		["voice_call", "Conversation", "Continuous voice replies\nuntil End voice"],
		["hud", "HUD", "Compact shared workspace"],
		["passthrough", "Passthrough", "Show your room\nwhen supported"],
		["camera_unavailable", "Scan page", "Quest camera component\nnot installed", false],
		["voice_stop", "End voice", "End the current voice conversation"],
		["page_help", "Help", "Hand and controller tips\nReplay or turn off"],
		["page_home", "Back", "Main tool wheel"]
	],
	"help": [
		["tutorial_hands", "Hand menu", "Learn the two-finger gesture"],
		["tutorial_hand_menu", "Twist & pinch", "Choose and confirm"],
		["tutorial_hand_windows", "Windows", "Point, move and resize"],
		["tutorial_controllers", "Controllers", "Movement and button shortcuts"],
		["tutorial_voice", "Voice", "Drafts and conversations"],
		["tutorial_off", "Tips off", "Keep the room quiet"],
		["tutorial_on", "Replay tips", "Show contextual tips again"],
		["page_senses", "Back", "Senses controls"]
	],
	"room": [
		["view_desk", "Desk", "Your shared workspace"],
		["view_fire", "Fireplace", "Take a seat by the fire"],
		["view_bar", "Collection", "The whiskey cabinet"],
		["view_arrival", "Room", "Return to the entrance"],
		["recenter", "Recenter", "Bring Hermes closer"],
		["hide_panel", "Hide panel", "Keep the room clear"],
		["passthrough", "Passthrough", "Show your physical room"],
		["page_home", "Back", "Main tool wheel"]
	],
	"parts": [
		["parts_next", "Next", "Inspect next assembly"],
		["parts_previous", "Previous", "Inspect previous assembly"],
		["parts_explode", "Separate", "See individual parts"],
		["parts_assemble", "Reassemble", "Restore exact positions"],
		["desktop", "Hermes", "Return to work"],
		["parts_close", "Finish", "Return to the room"],
		["share", "Share view", "Attach a review image\nwithout sending it"],
		["page_room", "Back", "Room controls"]
	]
}

var dial = Dial.new()
var menu: Node3D
var page := "home"
var mode := ""
var _head: Node3D
var _basis := Basis.IDENTITY
var _wrist := Vector3.ZERO
var _controller_button := false
var _desktop_roll := 0.0
var _desktop_pinching := false
var _consumed_frame := false
# Captured downs keep ownership until their matching release, even when a
# selection/cancellation closes the wheel between those two events.
var _captured_keys: Dictionary = {}
var _hand_invocation_armed := true
var _sources: Array = [{"id": "hermes", "title": "Hermes", "machine": "Forge"}]
var _source_page := 0
var _overview: Array = []
var _overview_page := 0

func set_open_windows(rows: Array) -> void:
	_overview = rows.duplicate(true)
	_overview_page = 0

func set_sources(rows: Array) -> void:
	_sources = rows.duplicate(true)
	if page == "sources": _set_page("sources")

func setup(head: Node3D) -> void:
	_head = head
	menu = Menu.new()
	add_child(menu)
	menu.setup(head)
	_set_page("home")

func _set_page(next: String) -> void:
	page = next if PAGES.has(next) or next in ["sources", "overview"] else "home"
	var ids: Array = []
	var entries: Array = []
	var rows: Array = PAGES.get(page, [])
	if page in ["sources", "overview"]:
		rows = []
		var choices: Array = _sources if page == "sources" else _overview
		var offset := _source_page if page == "sources" else _overview_page
		for index in 6:
			var source_index := offset * 6 + index
			if source_index < choices.size():
				var source: Dictionary = choices[source_index]
				rows.append(["window_source_" + str(source.id), str(source.title).left(20), str(source.machine)])
			else: rows.append(["window_empty_" + str(index), "—", "No source configured", false])
		rows.append(["window_more", "More", "More windows", choices.size() > 6])
		rows.append(["page_windows", "Back", "Window controls"])
	for row in rows:
		ids.append(row[0])
		entries.append({"id": row[0], "label": row[1], "description": row[2], "enabled": row.size() < 4 or row[3]})
	dial.set_slots(ids)
	menu.set_page("Hermes" if page == "home" else page.capitalize(), entries)

func is_capturing() -> bool:
	return dial.is_open() or _consumed_frame

func cancel() -> void:
	if mode == "hand":
		_hand_invocation_armed = false
	dial.cancel()
	menu.hide()
	mode = ""
	_desktop_pinching = false
	_consumed_frame = true

func open_desktop() -> void:
	if dial.is_open():
		cancel()
		return
	mode = "desktop"
	_desktop_roll = 0.0
	_desktop_pinching = Input.is_physical_key_pressed(KEY_ENTER) or Input.is_physical_key_pressed(KEY_KP_ENTER) or Input.is_physical_key_pressed(KEY_SPACE)
	_basis = Basis.IDENTITY
	_set_page("home")
	menu.open_near(Vector3.ZERO, false)
	menu.present(dial.open_at(_basis))
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE

func input(event: InputEvent) -> bool:
	if event is InputEventKey:
		var code := int(event.physical_keycode if event.physical_keycode != 0 else event.keycode)
		# Location distinguishes left/right modifiers without including their
		# changing modifier masks. IME-only text has no matching key-up to track.
		var key_id := "%d:%d" % [code, int(event.location)]
		var captured := code != 0 and _captured_keys.has(key_id)
		if not event.pressed and captured:
			_captured_keys.erase(key_id)
		if event.physical_keycode == KEY_F9:
			if event.pressed:
				_captured_keys[key_id] = true
				if not event.echo: open_desktop()
			return true
		if not dial.is_open():
			# Consume repeats too while an owned key remains held after closing.
			return captured
		if event.pressed and code != 0:
			_captured_keys[key_id] = true
		if event.physical_keycode == KEY_ESCAPE or event.physical_keycode == KEY_F10:
			if event.pressed: cancel()
		elif mode == "desktop":
			if event.physical_keycode in [KEY_ENTER, KEY_KP_ENTER, KEY_SPACE]:
				_desktop_pinching = event.pressed
			elif event.pressed and event.physical_keycode in [KEY_LEFT, KEY_RIGHT]:
				_desktop_roll += 18.0 if event.physical_keycode == KEY_RIGHT else -18.0
		return true
	if not dial.is_open(): return false
	if event is InputEventMouseButton:
		if event.pressed and mode == "desktop":
			if event.button_index == MOUSE_BUTTON_WHEEL_UP: _desktop_roll -= 18.0
			if event.button_index == MOUSE_BUTTON_WHEEL_DOWN: _desktop_roll += 18.0
		return true
	return event is InputEventMouseMotion

func update_desktop(delta: float) -> void:
	_consumed_frame = false
	if mode != "desktop" or not dial.is_open(): return
	_basis = Basis(Vector3.DOWN, deg_to_rad(_desktop_roll))
	_handle(dial.update({"valid": true, "menu_pose": true, "pinching": _desktop_pinching, "wrist_basis": _basis}, delta))

func update_xr(hand: Dictionary, right: XRController3D, left: XRController3D, delta: float) -> bool:
	_consumed_frame = false
	var invocation := left.is_button_pressed("by_button")
	if invocation and not _controller_button:
		if dial.is_open():
			cancel()
		elif right.get_is_active():
			open_controller(right)
	_controller_button = invocation
	if dial.is_open() and right.is_button_pressed("by_button"):
		cancel()
		return true
	if mode == "desktop": return is_capturing()
	if mode == "controller":
		_basis = _controller_basis(right.global_basis)
		var sample := {"valid": right.get_is_active(), "menu_pose": true, "pinching": right.get_float("trigger") > 0.72, "wrist_basis": _basis, "selection_axis": right.get_vector2("primary")}
		_wrist = right.global_position
		return _update_sample(sample, delta)
	return _update_hand(hand, delta)

func open_controller(right: XRController3D, initial_page: String = "home") -> void:
	if not right.get_is_active(): return
	mode = "controller"
	_basis = _controller_basis(right.global_basis)
	_set_page(initial_page)
	menu.open_near(right.global_position, true)
	menu.present(dial.open_at(_basis))
	_consumed_frame = true

## Automatic hand invocation requires a tracked relaxed pose after closing.
## Tracking loss cannot stand in for relaxing. This is separate from explicit
## controller/F9 opening, and an open submenu keeps its usual fresh-pinch gate.
func _update_hand(hand: Dictionary, delta: float) -> bool:
	var sample := {"valid": false, "menu_pose": false, "pinching": false, "wrist_basis": Basis.IDENTITY}
	var origin: Variant = hand.get("wrist_origin")
	if bool(hand.get("gesture_valid", false)) and origin is Vector3 and origin.is_finite():
		_basis = hand["wrist_basis"]
		_wrist = hand["wrist_origin"]
		var pose := bool(hand.get("menu_pose", false))
		if not pose:
			_hand_invocation_armed = true
		var allowed := dial.is_open() or _hand_invocation_armed
		sample = {"valid": true, "menu_pose": pose and allowed, "pinching": bool(hand.get("pinching", false)), "wrist_basis": _basis}
		if sample["menu_pose"] and not dial.is_open():
			if mode != "hand": _set_page("home")
			mode = "hand"
	elif mode == "hand":
		# This also cancels a partially completed invocation, before it opens.
		_hand_invocation_armed = false
	return _update_sample(sample, delta)

func _update_sample(sample: Dictionary, delta: float) -> bool:
	var was_open := dial.is_open()
	var state: Dictionary = dial.update(sample, delta)
	var invoking := bool(sample["valid"]) and bool(sample["menu_pose"])
	if state["just_opened"]: menu.open_near(_wrist, true)
	_handle(state)
	if dial.is_open() and mode in ["hand", "controller"]:
		menu.follow_hand(_wrist, _basis, delta)
	_consumed_frame = _consumed_frame or was_open or state["open"] or invoking
	return _consumed_frame

static func _controller_basis(controller: Basis) -> Basis:
	# Godot's wrist longitudinal roll axis is -Y; controller aim is -Z.
	return Basis(controller.x, controller.z, -controller.y).orthonormalized()

func _handle(state: Dictionary) -> void:
	menu.present(state)
	var selected := str(state.get("activated_id", ""))
	if not selected.is_empty():
		_consumed_frame = true
		if selected == "window_more" or selected.begins_with("window_empty_"):
			if selected == "window_more":
				if page == "overview": _overview_page = (_overview_page + 1) % maxi(1, ceili(_overview.size()/6.0))
				else: _source_page = (_source_page + 1) % maxi(1, ceili(_sources.size()/6.0))
			_set_page(page)
			menu.present(dial.open_at(_basis))
		elif selected.begins_with("page_"):
			_set_page(selected.trim_prefix("page_"))
			menu.present(dial.open_at(_basis))
		elif selected != "camera_unavailable":
			if mode == "hand": _hand_invocation_armed = false
			mode = ""
			action_requested.emit(selected)
		else:
			menu.present(dial.open_at(_basis))
	elif state.get("just_closed", false):
		if mode == "hand": _hand_invocation_armed = false
		mode = ""

func preview() -> void:
	open_desktop()
	_desktop_roll = 36.0
	update_desktop(0.05)
	if OS.get_environment("HERMES_OFFICE_RING_PREVIEW") == "1":
		# Screenshot fixture only: an explicit simulated pose, never XR tracking.
		var wrist := _head.global_position - _head.global_basis.z * 0.68 - _head.global_basis.y * 0.20
		menu.open_near(wrist, true)
		menu.follow_hand(wrist, _head.global_basis * Basis(Vector3.RIGHT, 0.65), 0.016)
