extends SceneTree
## Pure radial-menu contracts; no XR device, UI, permission, or action execution.
const WristDial = preload("res://wrist_dial.gd")
const IDS: Array = ["desktop", "hud", "tui", "voice", "view", "keyboard", "settings", "close"]
var failures: Array[String] = []
var checks := 0

func check(value: bool, message: String) -> void:
	checks += 1
	if not value:
		failures.append(message)

func fresh():
	var dial := WristDial.new()
	check(dial.set_slots(IDS), "Eight unique slots are accepted")
	return dial

func sample(degrees: float = 0.0, pinch: bool = false, pose: bool = true, baseline: Basis = Basis.IDENTITY) -> Dictionary:
	return {"valid": true, "menu_pose": pose, "pinching": pinch,
		"wrist_basis": Basis(-baseline.y.normalized(), deg_to_rad(degrees)) * baseline}

func advance(dial, value: Dictionary, duration: float) -> Dictionary:
	var remaining := duration
	var state: Dictionary = {}
	while remaining > 0.000001:
		var dt := minf(remaining, 0.05)
		state = dial.update(value, dt)
		remaining -= dt
	return state

func opened(dial, baseline: Basis = Basis.IDENTITY) -> Dictionary:
	return advance(dial, sample(0, false, true, baseline), 0.35)

func _initialize() -> void:
	call_deferred("run_checks")

func run_checks() -> void:
	var dial = fresh()
	var state := advance(dial, sample(), 0.30)
	check(not state.open and is_equal_approx(state.progress, 0.30 / 0.35), "Invocation needs the full hold and reports progress")
	state = dial.update(sample(), 0.05)
	check(state.open and state.just_opened and state.selected_index == 0, "Invocation opens once at neutral slot zero")
	check(not dial.update(sample(), 0.01).just_opened, "just_opened is a single-frame event")
	state = advance(dial, sample(0, true, false), 0.10)
	check(state.open and state.activated_id.is_empty(), "Holding pinch does not activate")
	state = dial.update(sample(0, false, false), 0.01)
	check(state.open and state.activated_id.is_empty(), "Short pinch release does not activate")
	state = advance(dial, sample(0, true, false), 0.18)
	check(state.open and is_equal_approx(state.progress, 1.0), "Qualified pinch holds at full progress without dispatch")
	state = dial.update(sample(0, false, false), 0.01)
	check(not state.open and state.just_closed and state.activated_id == "desktop", "Qualified release emits chosen ID once and closes")
	check(dial.update(sample(0, false, false), 0.01).activated_id.is_empty(), "Activation never repeats on subsequent open fingers")
	check(not advance(dial, sample(0, true), 0.6).open, "Held pinch cannot reopen after activation")
	check(opened(dial).open, "Fresh open fingers and invocation can reopen")

	dial = fresh()
	check(not advance(dial, sample(0, true), 0.8).open, "Starting with pinch held cannot invoke")
	advance(dial, sample(), 0.2)
	dial.update(sample(0, false, false), 0.01)
	check(not advance(dial, sample(), 0.2).open, "Interrupted invocation must restart its hold")
	advance(dial, sample(), 0.15)
	advance(dial, sample(0, true), 0.2)
	state = dial.update({"valid": false}, 0.01)
	check(not state.open and state.just_closed and state.activated_id.is_empty(), "Tracking loss cancels a qualified held pinch without firing")
	check(not advance(dial, sample(0, true), 0.5).open, "Reacquired held pinch cannot invoke or activate")
	check(opened(dial).open, "Reacquisition requires valid open fingers and a new invocation")

	dial = fresh()
	opened(dial)
	check(dial.update(sample(11.6), 0.01).selected_index == 0, "29 dial degrees remain inside neutral hysteresis")
	check(dial.update(sample(12.0), 0.01).selected_index == 1, "30 dial degrees cross the neutral detent")
	check(dial.update(sample(7.2), 0.01).selected_index == 1, "Returning to18 dial degrees retains sector one")
	check(dial.update(sample(6.0), 0.01).selected_index == 0, "15 dial degrees cross back out of sector one")
	for physical: float in [18.0, 36.0, 54.0, 72.0, -54.0, -36.0, -18.0, 0.0]:
		state = dial.update(sample(physical), 0.01)
		var expected := int(round(fposmod(physical * 2.5, 360.0) / 45.0)) % 8
		check(state.selected_index == expected, "Natural wrist roll reaches sector" + str(expected))

	dial = fresh()
	opened(dial)
	dial.update(sample(18), 0.01)
	state = dial.update(sample(36, true, false), 0.05)
	check(state.selected_index == 1, "Pinch-start jitter cannot redirect the prior selected slot")
	state = advance(dial, sample(-54, true, false), 0.25)
	check(state.open and state.selected_index == 1, "Selection freezes while pinching even when invocation pose is lost")
	state = dial.update(sample(-54, false, false), 0.01)
	check(state.activated_id == "hud", "Release dispatches the frozen slot ID")

	dial = fresh()
	opened(dial)
	dial.update(sample(170), 0.01)
	state = dial.update(sample(179), 0.01)
	var before_roll: float = state.roll_degrees
	var before_index: int = state.selected_index
	state = dial.update(sample(-179), 0.01)
	check(is_equal_approx(state.roll_degrees - before_roll, 2.0), "+179 to-179 unwraps to a two-degree clockwise move")
	check(state.selected_index == before_index, "Angle wrap does not jump the highlighted sector")
	state = dial.update(sample(179), 0.01)
	check(is_equal_approx(state.roll_degrees, before_roll), "Reverse wrap follows the same continuous baseline")
	check(state.dialangle_degrees >= 0.0 and state.dialangle_degrees < 360.0, "Public dial angle remains within one circle")

	dial = fresh()
	var baseline := Basis.from_euler(Vector3(0.6, -0.9, 0.3))
	opened(dial, baseline)
	state = dial.update(sample(36, false, true, baseline), 0.01)
	check(is_equal_approx(state.roll_degrees, 36.0) and state.selected_index == 2, "World-oriented wrist uses its frozen humanoid-Y forearm axis")
	dial.update(sample(18, false, true, baseline), 0.01)
	state = dial.update(sample(36, false, true, baseline), 0.01)
	check(is_equal_approx(state.roll_degrees, 36.0), "Holding menu pose does not reset the opening baseline")

	dial = fresh()
	opened(dial, baseline)
	var palm_spin := sample(0, false, true, baseline)
	palm_spin.wrist_basis = Basis(baseline.z.normalized(), deg_to_rad(45.0)) * baseline
	state = dial.update(palm_spin, 0.01)
	check(is_zero_approx(state.roll_degrees) and state.selected_index == 0, "Rotation about the palm normal is not mistaken for forearm roll")

	# Match the official Godot OpenXR-to-humanoid joint rotation, not a fixture
	# whose axis convention merely repeats the dial implementation.
	dial = fresh()
	var openxr_basis := Basis.from_euler(Vector3(-0.3, 0.7, 0.2))
	var bone_adjustment := Basis(Quaternion(0.0, -sqrt(0.5), sqrt(0.5), 0.0))
	var humanoid_basis := openxr_basis * bone_adjustment
	opened(dial, humanoid_basis)
	var openxr_roll := sample(0, false, true, humanoid_basis)
	openxr_roll.wrist_basis = Basis(openxr_basis.z.normalized(), deg_to_rad(36.0)) * humanoid_basis
	state = dial.update(openxr_roll, 0.01)
	check(is_equal_approx(state.roll_degrees, 36.0) and state.selected_index == 2, "Official OpenXR bone adjustment preserves forearm twist as humanoid-Y roll")

	dial = fresh()
	opened(dial)
	check(advance(dial, sample(0, false, false), 1.45).open, "Relaxed invocation pose has a1.5s grace interval")
	state = dial.update(sample(0, false, false), 0.05)
	check(not state.open and state.just_closed and state.activated_id.is_empty(), "Relaxed pose closes without action at timeout")
	opened(dial)
	check(advance(dial, sample(0, true, false), 2.0).open, "Pinch keeps menu open beyond relaxed-pose grace")
	state = advance(dial, sample(0, true, false), 10.0)
	check(not state.open and state.activated_id.is_empty(), "Absolute12s timeout cancels even a held pinch")

	dial = fresh()
	opened(dial)
	advance(dial, sample(0, true), 0.2)
	var cancelled := sample()
	cancelled.cancel = true
	state = dial.update(cancelled, 0.01)
	check(not state.open and state.just_closed and state.activated_id.is_empty(), "Explicit sample cancellation suppresses a ready activation")
	opened(dial)
	dial.cancel()
	state = dial.update(sample(0, true), 0.01)
	check(not state.open and state.just_closed, "cancel() reports closure on the next update")
	check(not dial.update(sample(0, true), 0.01).just_closed, "cancel() closure is reported once")
	opened(dial)
	check(not dial.set_slots(["same", "same", "a", "b", "c", "d", "e", "f"]), "Duplicate slot IDs are rejected")
	check(not advance(dial, sample(), 0.5).open, "Invalid slot configuration leaves actions disabled")
	check(dial.set_slots(IDS), "Valid configuration can be restored")
	check(not dial.update(sample(), 5.0).open, "One stalled frame cannot complete invocation")
	opened(dial)
	var broken := sample()
	broken.wrist_basis = Basis(Vector3.ZERO, Vector3.ZERO, Vector3.ZERO)
	state = dial.update(broken, 0.01)
	check(not state.open and state.activated_id.is_empty(), "Degenerate wrist basis cancels safely")
	opened(dial)
	broken.wrist_basis = Basis(Vector3(NAN, 0, 0), Vector3.UP, Vector3.BACK)
	check(not dial.update(broken, 0.01).open, "Non-finite wrist basis cancels safely")
	opened(dial)
	check(not dial.update(sample(), NAN).open, "Invalid frame delta cancels safely")

	dial = fresh()
	state = dial.open_at(Basis.IDENTITY)
	check(state.open and state.just_opened and state.selected_index == 0 and dial.is_open(), "Explicit opening starts at neutral without an action")
	check(state.activated_id.is_empty(), "Explicit submenu opening never dispatches")
	advance(dial, sample(18, true, false), 0.3)
	state = dial.update(sample(18, false, false), 0.01)
	check(state.open and state.activated_id.is_empty(), "Pinch held through explicit opening cannot activate on release")
	advance(dial, sample(18, true, false), 0.18)
	state = dial.update(sample(18, false, false), 0.01)
	check(state.activated_id == "hud" and not dial.is_open(), "Fresh pinch after explicit-open release activates the selected submenu slot")
	check(dial.set_slots(["a", "b", "c", "d", "e", "f", "g", "h"]), "Submenu replaces the eight IDs")
	state = dial.open_at(baseline)
	check(state.open and state.selected_id == "a" and is_zero_approx(state.roll_degrees), "Submenu gets a new neutral basis and its own IDs")
	state = dial.open_at(Basis(Vector3.ZERO, Vector3.ZERO, Vector3.ZERO))
	check(not state.open and state.just_closed and state.activated_id.is_empty(), "Invalid explicit basis cancels without dispatch")
	dial.open_at(Basis.IDENTITY)
	var stick_sample := {"valid": true, "menu_pose": true, "pinching": false, "wrist_basis": Basis.IDENTITY, "selection_axis": Vector2.RIGHT}
	state = dial.update(stick_sample, 0.02)
	check(state.selected_index == 2, "Right thumbstick chooses right sector")
	stick_sample.selection_axis = Vector2.ZERO
	state = dial.update(stick_sample, 0.02)
	check(state.selected_index == 2, "Neutral stick preserves selected sector")
	stick_sample.pinching = true
	stick_sample.selection_axis = Vector2.LEFT
	for frame in 12: state = dial.update(stick_sample, 0.02)
	check(state.selected_index == 2 and state.activated_id.is_empty(), "Trigger hold latches selection despite stick motion")
	stick_sample.pinching = false
	state = dial.update(stick_sample, 0.02)
	check(not state.activated_id.is_empty() and not state.open, "Release activates one latched thumbstick choice")
	print("HERMES_WRIST_DIAL_TESTS " + JSON.stringify({"passed": failures.is_empty(), "checks": checks, "failures": failures}))
	quit(0 if failures.is_empty() else 1)
