extends SceneTree
## Headless deterministic hand geometry and pointer-keyboard draft contracts.
const HandPointer = preload("res://hand_pointer.gd")
const Workbench = preload("res://workbench.gd")
var failures: Array[String] = []

func check(value: bool, message: String) -> void:
	if not value:
		failures.append(message)

func joint(tracker: XRHandTracker, id: int, position: Vector3) -> void:
	tracker.set_hand_joint_transform(id, Transform3D(Basis.IDENTITY, position))
	tracker.set_hand_joint_flags(id, HandPointer.POSITION_FLAGS)

func gap(tracker: XRHandTracker, distance: float) -> void:
	var tip := tracker.get_hand_joint_transform(XRHandTracker.HAND_JOINT_INDEX_FINGER_TIP).origin
	joint(tracker, XRHandTracker.HAND_JOINT_THUMB_TIP, tip + Vector3(distance, 0, 0))

func finger(tracker: XRHandTracker, index: int, straight: bool) -> void:
	var bases := [Vector3(-0.025, 1, -0.07), Vector3(0, 1, -0.075), Vector3(0.022, 1, -0.07), Vector3(0.041, 1, -0.061)]
	var base: Vector3 = bases[index]
	var offsets := [Vector3.ZERO, Vector3(0, 0, -0.035), Vector3(0, 0, -0.060), Vector3(0, 0, -0.080)] if straight else [Vector3.ZERO, Vector3(0, -0.026, -0.015), Vector3(0, -0.044, 0.004), Vector3(0, -0.035, 0.027)]
	var joints: Array = HandPointer.FINGER_JOINTS[index]
	for segment: int in range(4):
		joint(tracker, joints[segment], base + offsets[segment])

func menu_tracker() -> XRHandTracker:
	var tracker := XRHandTracker.new()
	tracker.has_tracking_data = true
	tracker.hand_tracking_source = XRHandTracker.HAND_TRACKING_SOURCE_UNOBSTRUCTED
	tracker.set_hand_joint_transform(XRHandTracker.HAND_JOINT_WRIST, Transform3D(Basis(Vector3.RIGHT, -PI / 2.0), Vector3(0, 1, 0)))
	tracker.set_hand_joint_flags(XRHandTracker.HAND_JOINT_WRIST, HandPointer.POSITION_FLAGS | HandPointer.ORIENTATION_FLAGS)
	for index: int in range(4):
		finger(tracker, index, index < 2)
	gap(tracker, 0.08)
	return tracker

func run_gesture_checks(pointer) -> void:
	var tracker := menu_tracker()
	var result: Dictionary = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.valid and result.gesture_valid and result.menu_pose, "Two straight fingers with ring/pinky curled form menu pose")
	check(result.wrist_origin.is_equal_approx(Vector3(0, 1, 0)) and result.palm_normal.is_equal_approx(Vector3.UP), "Godot wrist positive Z gives palm-facing world normal")
	gap(tracker, 0.02)
	result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.menu_pose and result.pinching, "Menu finger classification imposes no thumb posture")
	gap(tracker, 0.08)
	check(pointer.sample_tracker(tracker, Transform3D.IDENTITY).menu_pose, "Moving thumb away preserves menu pose")
	for shape: Array in [[true, true, true, true], [false, false, false, false], [true, false, false, false], [true, true, true, false], [true, true, false, true]]:
		for index: int in range(4):
			finger(tracker, index, shape[index])
		gap(tracker, 0.08)
		result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
		check(result.valid and result.gesture_valid and not result.menu_pose, "Open/fist/single-finger/extra-extended poses do not invoke menu: " + str(shape))
	tracker = menu_tracker()
	var extra_joint := XRHandTracker.HAND_JOINT_MIDDLE_FINGER_PHALANX_DISTAL
	tracker.set_hand_joint_flags(extra_joint, 0)
	result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.valid and not result.gesture_valid and not result.menu_pose, "Missing extra joint does not interrupt pointer")
	check(result.wrist_origin == Vector3.ZERO and result.wrist_basis == Basis.IDENTITY and result.palm_normal == Vector3.ZERO, "Unavailable gesture fields have finite safe defaults")
	tracker.set_hand_joint_flags(extra_joint, XRHandTracker.HAND_JOINT_FLAG_POSITION_VALID)
	result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.valid and not result.gesture_valid, "Valid but untracked gesture joint is rejected independently")
	tracker = menu_tracker()
	tracker.set_hand_joint_flags(XRHandTracker.HAND_JOINT_WRIST, HandPointer.POSITION_FLAGS | XRHandTracker.HAND_JOINT_FLAG_ORIENTATION_VALID)
	result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.valid and not result.gesture_valid, "Gesture requires tracked wrist orientation but pointer does not")
	tracker = menu_tracker()
	joint(tracker, extra_joint, Vector3(NAN, 1, -0.1))
	result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.valid and not result.gesture_valid and not result.menu_pose, "Nonfinite extra finger position disables only gesture")
	tracker = menu_tracker()
	var wrist := tracker.get_hand_joint_transform(XRHandTracker.HAND_JOINT_WRIST)
	wrist.basis.x = Vector3(NAN, 0, 0)
	tracker.set_hand_joint_transform(XRHandTracker.HAND_JOINT_WRIST, wrist)
	result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.valid and not result.gesture_valid, "Malformed wrist orientation leaves position-based pointer working")
	tracker = menu_tracker()
	wrist = tracker.get_hand_joint_transform(XRHandTracker.HAND_JOINT_WRIST)
	wrist.basis = Basis(Vector3.ZERO, Vector3.ZERO, Vector3.ZERO)
	tracker.set_hand_joint_transform(XRHandTracker.HAND_JOINT_WRIST, wrist)
	result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.valid and not result.gesture_valid, "Degenerate wrist orientation is rejected")
	tracker = menu_tracker()
	wrist = tracker.get_hand_joint_transform(XRHandTracker.HAND_JOINT_WRIST)
	wrist.basis = wrist.basis.scaled(Vector3(2, 1, 1))
	tracker.set_hand_joint_transform(XRHandTracker.HAND_JOINT_WRIST, wrist)
	result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.valid and not result.gesture_valid, "Scaled wrist orientation is malformed gesture evidence")
	tracker = menu_tracker()
	joint(tracker, XRHandTracker.HAND_JOINT_RING_FINGER_PHALANX_INTERMEDIATE, tracker.get_hand_joint_transform(XRHandTracker.HAND_JOINT_RING_FINGER_PHALANX_PROXIMAL).origin)
	result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.valid and not result.gesture_valid, "Zero-length finger segment is invalid gesture evidence")
	tracker = menu_tracker()
	joint(tracker, XRHandTracker.HAND_JOINT_RING_FINGER_TIP, Vector3(1, 1, 1))
	result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.valid and not result.gesture_valid, "Implausible physical finger segment cannot invoke menu")
	tracker = menu_tracker()
	var moved := Transform3D(Basis(Vector3.UP, 0.6), Vector3(3, 0, 2))
	var reference := Transform3D(Basis(Vector3.FORWARD, 0.25), Vector3(-1, 0.5, 0))
	var expected_basis := (moved.basis * reference.basis * tracker.get_hand_joint_transform(XRHandTracker.HAND_JOINT_WRIST).basis).orthonormalized()
	result = pointer.sample_tracker(tracker, moved, reference, 2.5)
	check(result.gesture_valid and result.menu_pose, "World transform and scale do not alter physical gesture classification")
	check(result.wrist_origin.is_equal_approx(moved * reference * Vector3(0, 2.5, 0)), "Wrist origin applies scale, reference and origin exactly once")
	check(result.wrist_basis.is_equal_approx(expected_basis) and result.palm_normal.is_equal_approx(expected_basis.z), "Wrist basis and palm normal apply reference and origin rotations in order")
	check(is_equal_approx(result.palm_normal.length(), 1.0), "Palm normal stays unit length under world scale")
	for world_scale: float in [0.1, 10.0]:
		result = pointer.sample_tracker(tracker, Transform3D.IDENTITY, Transform3D.IDENTITY, world_scale)
		check(result.gesture_valid and result.menu_pose, "Gesture thresholds stay in tracking meters at scale " + str(world_scale))

func press_character(workbench, lower: String) -> void:
	for button in workbench._keyboard_keys:
		if str(button.get_meta("lower", "")) == lower:
			button.pressed.emit()
			return
	check(false, "Keyboard contains " + lower)

func _initialize() -> void:
	call_deferred("run_checks")

func run_checks() -> void:
	var pointer := HandPointer.new()
	var tracker := XRHandTracker.new()
	tracker.has_tracking_data = true
	tracker.hand_tracking_source = XRHandTracker.HAND_TRACKING_SOURCE_UNOBSTRUCTED
	joint(tracker, XRHandTracker.HAND_JOINT_WRIST, Vector3(0, 1, 0))
	joint(tracker, XRHandTracker.HAND_JOINT_INDEX_FINGER_PHALANX_PROXIMAL, Vector3(0, 1, -0.08))
	joint(tracker, XRHandTracker.HAND_JOINT_INDEX_FINGER_METACARPAL, Vector3(0, 1, -0.04))
	joint(tracker, XRHandTracker.HAND_JOINT_INDEX_FINGER_TIP, Vector3(0.02, 1, -0.16))
	gap(tracker, 0.05)
	var result: Dictionary = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.valid and not result.pinching, "Tracked unobstructed open hand is valid")
	check(not result.gesture_valid and not result.menu_pose, "Minimal pointer tracking does not claim full finger gesture data")
	check(result.origin.is_equal_approx(Vector3(0, 1, -0.08)) and result.direction.is_equal_approx(Vector3.FORWARD), "Ray starts at index knuckle and follows wrist-to-knuckle direction")
	gap(tracker, 0.024)
	check(pointer.sample_tracker(tracker, Transform3D.IDENTITY).pinching, "Pinch closes below 2.5cm")
	gap(tracker, 0.035)
	check(pointer.sample_tracker(tracker, Transform3D.IDENTITY).pinching, "Pinch holds through hysteresis band")
	gap(tracker, 0.046)
	check(not pointer.sample_tracker(tracker, Transform3D.IDENTITY).pinching, "Pinch releases above 4.5cm")
	gap(tracker, 0.035)
	check(not pointer.sample_tracker(tracker, Transform3D.IDENTITY).pinching, "Open hand stays open through hysteresis band")
	gap(tracker, 0.024)
	pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	tracker.has_tracking_data = false
	result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(not result.valid and not result.pinching and result.origin == Vector3.ZERO and result.direction == Vector3.ZERO, "Tracking loss clears pinch and returns zero ray")
	check(not result.gesture_valid and not result.menu_pose and result.palm_normal == Vector3.ZERO, "Tracking loss also clears gesture evidence")
	tracker.has_tracking_data = true
	gap(tracker, 0.035)
	check(not pointer.sample_tracker(tracker, Transform3D.IDENTITY).pinching, "Tracking regain does not inherit previous pinch")
	tracker.hand_tracking_source = XRHandTracker.HAND_TRACKING_SOURCE_UNKNOWN
	check(not pointer.sample_tracker(tracker, Transform3D.IDENTITY).valid, "Unknown source is rejected")
	tracker.hand_tracking_source = XRHandTracker.HAND_TRACKING_SOURCE_CONTROLLER
	check(not pointer.sample_tracker(tracker, Transform3D.IDENTITY).valid, "Controller-inferred joints are rejected")
	tracker.hand_tracking_source = XRHandTracker.HAND_TRACKING_SOURCE_UNOBSTRUCTED
	tracker.set_hand_joint_flags(XRHandTracker.HAND_JOINT_THUMB_TIP, XRHandTracker.HAND_JOINT_FLAG_POSITION_VALID)
	check(not pointer.sample_tracker(tracker, Transform3D.IDENTITY).valid, "Valid-but-untracked joint is rejected")
	gap(tracker, 0.024)
	tracker.set_hand_joint_flags(XRHandTracker.HAND_JOINT_INDEX_FINGER_PHALANX_PROXIMAL, 0)
	result = pointer.sample_tracker(tracker, Transform3D.IDENTITY)
	check(result.valid and result.origin.is_equal_approx(Vector3(0, 1, -0.04)), "Tracked metacarpal provides knuckle fallback")
	tracker.set_hand_joint_flags(XRHandTracker.HAND_JOINT_INDEX_FINGER_METACARPAL, 0)
	check(not pointer.sample_tracker(tracker, Transform3D.IDENTITY).valid, "No tracked aim joint invalidates pointer")
	joint(tracker, XRHandTracker.HAND_JOINT_INDEX_FINGER_PHALANX_PROXIMAL, Vector3(0, 1, 0))
	check(not pointer.sample_tracker(tracker, Transform3D.IDENTITY).valid, "Degenerate wrist-to-knuckle vector is rejected")
	joint(tracker, XRHandTracker.HAND_JOINT_INDEX_FINGER_PHALANX_PROXIMAL, Vector3(0, 1, -0.08))
	var moved := Transform3D(Basis(Vector3.UP, 0.6), Vector3(3, 0, 2))
	var reference := Transform3D(Basis(Vector3.UP, -0.2), Vector3(-1, 0, 0))
	result = pointer.sample_tracker(tracker, moved, reference, 2.0)
	check(result.valid and result.pinching, "Pinch thresholds remain physical under world scale")
	check(result.origin.is_equal_approx(moved * reference * Vector3(0, 2, -0.16)), "Ray origin applies world scale, reference frame, and XR origin once")
	check(result.direction.is_equal_approx((moved.basis * reference.basis * Vector3.FORWARD).normalized()), "Direction follows origin and reference rotation")
	joint(tracker, XRHandTracker.HAND_JOINT_THUMB_TIP, Vector3(NAN, 1, 0))
	check(not pointer.sample_tracker(tracker, Transform3D.IDENTITY).valid, "Non-finite tracking is rejected")
	check(not pointer.sample(null).valid, "Missing XR origin safely returns unavailable")
	run_gesture_checks(pointer)
	pointer.free()

	var workbench := Workbench.new()
	root.add_child(workbench)
	var state := {"connection": {"status": "ready", "capabilities": {"chat": true, "sessions": false}}, "selected_session": "test", "pending_message": "", "busy": false, "controls_summary": "A opens the panel.", "senses_summary": "Physical camera access is unavailable."}
	workbench.update_state(state)
	var submitted: Array[String] = []
	workbench.message_submitted.connect(func(value: String) -> void: submitted.append(value))
	press_character(workbench, "h")
	press_character(workbench, "i")
	workbench._keyboard_shift.button_pressed = true
	press_character(workbench, "1")
	check(workbench.draft_text() == "hi!", "QWERTY and shifted punctuation edit the existing draft")
	workbench.backspace_text()
	workbench.insert_text(" there\nx")
	check(workbench.draft_text() == "hi there\nx", "Backspace, space, and newline preserve the draft")
	check(workbench._keyboard_preview.text == workbench.draft_text(), "Keyboard preview shows the actual draft")
	check(submitted.is_empty(), "Keyboard typing never auto-sends")
	state.busy = true
	workbench.update_state(state)
	workbench.insert_text("blocked")
	check(workbench.draft_text() == "hi there\nx" and workbench._keyboard_send.disabled, "Busy state disables keyboard editing and sending")
	state.busy = false
	workbench.update_state(state)
	workbench._keyboard_send.pressed.emit()
	check(submitted.size() == 1 and submitted[0] == "hi there\nx", "Explicit keyboard Send emits the current draft once")
	check(workbench.draft_text() == "hi there\nx", "Send preserves draft until acknowledgement")
	workbench.acknowledge_message(false)
	check(workbench.draft_text() == "hi there\nx", "Rejected command preserves keyboard draft")
	workbench._keyboard_send.pressed.emit()
	workbench.acknowledge_message(true)
	check(workbench.draft_text().is_empty(), "Accepted command clears only its sent draft")
	check(workbench._connection_details.text.contains("A opens the panel.") and workbench._connection_details.text.contains("Physical camera access is unavailable."), "Connection displays supplied Quest controls and senses")
	var new_sessions: Array[bool] = []
	workbench.new_session_requested.connect(func() -> void: new_sessions.append(true))
	workbench._new_session_button.pressed.emit()
	check(new_sessions.size() == 1, "Session creation is allowed with chat even when session listing is unavailable")
	workbench.free()
	print("HERMES_HAND_POINTER_TESTS " + JSON.stringify({"passed": failures.is_empty(), "failures": failures}))
	quit(0 if failures.is_empty() else 1)
