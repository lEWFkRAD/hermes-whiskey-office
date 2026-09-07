extends Node
## Hand pointer and optional wrist-menu pose data. No UI actions are triggered.
## Unknown/controller-inferred sources deliberately remain unavailable.

const TRACKER_PATH := &"/user/hand_tracker/right"
var tracker_path: StringName = TRACKER_PATH
const PINCH_CLOSE_METERS := 0.025
const PINCH_OPEN_METERS := 0.045
const POSITION_FLAGS := XRHandTracker.HAND_JOINT_FLAG_POSITION_VALID | XRHandTracker.HAND_JOINT_FLAG_POSITION_TRACKED
const ORIENTATION_FLAGS := XRHandTracker.HAND_JOINT_FLAG_ORIENTATION_VALID | XRHandTracker.HAND_JOINT_FLAG_ORIENTATION_TRACKED
const FINGER_JOINTS := [
	[XRHandTracker.HAND_JOINT_INDEX_FINGER_PHALANX_PROXIMAL, XRHandTracker.HAND_JOINT_INDEX_FINGER_PHALANX_INTERMEDIATE, XRHandTracker.HAND_JOINT_INDEX_FINGER_PHALANX_DISTAL, XRHandTracker.HAND_JOINT_INDEX_FINGER_TIP],
	[XRHandTracker.HAND_JOINT_MIDDLE_FINGER_PHALANX_PROXIMAL, XRHandTracker.HAND_JOINT_MIDDLE_FINGER_PHALANX_INTERMEDIATE, XRHandTracker.HAND_JOINT_MIDDLE_FINGER_PHALANX_DISTAL, XRHandTracker.HAND_JOINT_MIDDLE_FINGER_TIP],
	[XRHandTracker.HAND_JOINT_RING_FINGER_PHALANX_PROXIMAL, XRHandTracker.HAND_JOINT_RING_FINGER_PHALANX_INTERMEDIATE, XRHandTracker.HAND_JOINT_RING_FINGER_PHALANX_DISTAL, XRHandTracker.HAND_JOINT_RING_FINGER_TIP],
	[XRHandTracker.HAND_JOINT_PINKY_FINGER_PHALANX_PROXIMAL, XRHandTracker.HAND_JOINT_PINKY_FINGER_PHALANX_INTERMEDIATE, XRHandTracker.HAND_JOINT_PINKY_FINGER_PHALANX_DISTAL, XRHandTracker.HAND_JOINT_PINKY_FINGER_TIP],
]
# Physical validity bounds apply before world scaling. Shape thresholds use
# ratios/angles to accommodate different hand sizes, with a deliberate gap
# between straight and curled classifications. Caller owns invocation dwell.
const MIN_FINGER_SEGMENT_METERS := 0.003
const MAX_FINGER_SEGMENT_METERS := 0.09
const STRAIGHT_EXTENSION_RATIO := 0.90
const STRAIGHT_BEND_COSINE := 0.75 # Each joint bends less than about 41 degrees.
const STRAIGHT_OUTWARD_COSINE := 0.45 # Finger extends away from the wrist.
const CURLED_EXTENSION_RATIO := 0.72
const CURLED_END_COSINE := 0.35 # First/last segments differ by over 69 degrees.
var _pinching := false

func sample(xr_origin: Node3D) -> Dictionary:
	if not is_instance_valid(xr_origin) or not xr_origin.is_inside_tree():
		return _invalid()
	var tracker := XRServer.get_tracker(tracker_path) as XRHandTracker
	return sample_tracker(tracker, xr_origin.global_transform, XRServer.get_reference_frame(), XRServer.world_scale)

## Kept separate for deterministic tests without registering a fake XR device.
## Joint positions are tracking-space meters; thresholds stay physical even when
## world scale changes. World conversion follows XRPose.get_adjusted_transform.
func sample_tracker(tracker: XRHandTracker, origin_transform: Transform3D, reference_frame: Transform3D = Transform3D.IDENTITY, world_scale: float = 1.0) -> Dictionary:
	if tracker == null or not tracker.has_tracking_data:
		return _invalid()
	if tracker.hand_tracking_source != XRHandTracker.HAND_TRACKING_SOURCE_UNOBSTRUCTED:
		return _invalid()
	if not is_finite(world_scale) or world_scale <= 0.0:
		return _invalid()
	var wrist_joint := XRHandTracker.HAND_JOINT_WRIST
	var index_tip_joint := XRHandTracker.HAND_JOINT_INDEX_FINGER_TIP
	var thumb_tip_joint := XRHandTracker.HAND_JOINT_THUMB_TIP
	var aim_joint := XRHandTracker.HAND_JOINT_INDEX_FINGER_PHALANX_PROXIMAL
	if not _position_tracked(tracker, aim_joint):
		aim_joint = XRHandTracker.HAND_JOINT_INDEX_FINGER_METACARPAL
	for joint in [wrist_joint, aim_joint, index_tip_joint, thumb_tip_joint]:
		if not _position_tracked(tracker, joint):
			return _invalid()
	var wrist := tracker.get_hand_joint_transform(wrist_joint).origin
	var knuckle := tracker.get_hand_joint_transform(aim_joint).origin
	var index_tip := tracker.get_hand_joint_transform(index_tip_joint).origin
	var thumb_tip := tracker.get_hand_joint_transform(thumb_tip_joint).origin
	if not wrist.is_finite() or not knuckle.is_finite() or not index_tip.is_finite() or not thumb_tip.is_finite():
		return _invalid()
	var along_hand := knuckle - wrist
	if along_hand.length_squared() < 0.000001:
		return _invalid()
	var tracking_to_world := origin_transform * reference_frame
	var ray_origin := tracking_to_world * (knuckle * world_scale)
	var ray_direction := tracking_to_world.basis * along_hand
	if not ray_origin.is_finite() or not ray_direction.is_finite() or ray_direction.length_squared() < 0.000001:
		return _invalid()
	var separation := index_tip.distance_to(thumb_tip)
	if _pinching:
		if separation >= PINCH_OPEN_METERS:
			_pinching = false
	elif separation <= PINCH_CLOSE_METERS:
		_pinching = true
	var result := {"valid": true, "origin": ray_origin, "direction": ray_direction.normalized(), "pinching": _pinching}
	result.merge(_gesture_sample(tracker, tracking_to_world, world_scale))
	return result

func _gesture_sample(tracker: XRHandTracker, tracking_to_world: Transform3D, world_scale: float) -> Dictionary:
	var unavailable := _invalid_gesture()
	var wrist_joint := XRHandTracker.HAND_JOINT_WRIST
	if (tracker.get_hand_joint_flags(wrist_joint) & ORIENTATION_FLAGS) != ORIENTATION_FLAGS:
		return unavailable
	var wrist := tracker.get_hand_joint_transform(wrist_joint)
	if not wrist.is_finite() or not _rotation_basis_valid(wrist.basis) or not tracking_to_world.is_finite():
		return unavailable
	var world_basis := tracking_to_world.basis * wrist.basis
	var world_determinant := world_basis.determinant()
	if not world_basis.is_finite() or not is_finite(world_determinant) or world_determinant <= 0.000001:
		return unavailable
	var wrist_origin := tracking_to_world * (wrist.origin * world_scale)
	if not wrist_origin.is_finite():
		return unavailable
	var fingers: Array[Dictionary] = []
	for joints: Array in FINGER_JOINTS:
		var shape := _finger_shape(tracker, joints, wrist.origin)
		if not bool(shape["valid"]):
			return unavailable
		fingers.append(shape)
	world_basis = world_basis.orthonormalized()
	# Godot converts OpenXR hand joints to its Humanoid skeleton convention:
	# local -Z points out the BACK of the hand, so +Z is the palm-facing normal.
	# Preserve that convention for either hand; don't use raw OpenXR -Y here.
	return {
		"gesture_valid": true,
		"menu_pose": bool(fingers[0]["straight"]) and bool(fingers[1]["straight"]) and bool(fingers[2]["curled"]) and bool(fingers[3]["curled"]),
		"wrist_origin": wrist_origin,
		"wrist_basis": world_basis,
		"palm_normal": world_basis.z,
	}

func _rotation_basis_valid(basis: Basis) -> bool:
	# Joint orientation should be a rotation, not an arbitrary scaled/sheared
	# matrix. Allow small numerical error before producing a unit world basis.
	if not basis.is_finite() or absf(basis.determinant() - 1.0) > 0.05:
		return false
	for axis: Vector3 in [basis.x, basis.y, basis.z]:
		if absf(axis.length_squared() - 1.0) > 0.05:
			return false
	return absf(basis.x.dot(basis.y)) <= 0.05 and absf(basis.x.dot(basis.z)) <= 0.05 and absf(basis.y.dot(basis.z)) <= 0.05

func _finger_shape(tracker: XRHandTracker, joints: Array, wrist: Vector3) -> Dictionary:
	var unavailable := {"valid": false, "straight": false, "curled": false}
	var positions: Array[Vector3] = []
	for joint: int in joints:
		if not _position_tracked(tracker, joint):
			return unavailable
		var position := tracker.get_hand_joint_transform(joint).origin
		if not position.is_finite():
			return unavailable
		positions.append(position)
	var directions: Array[Vector3] = []
	var chain_length := 0.0
	for index: int in range(3):
		var segment := positions[index + 1] - positions[index]
		var length := segment.length()
		if not is_finite(length) or length < MIN_FINGER_SEGMENT_METERS or length > MAX_FINGER_SEGMENT_METERS:
			return unavailable
		chain_length += length
		directions.append(segment / length)
	var chord := positions[3] - positions[0]
	var outward := positions[0] - wrist
	if outward.length_squared() < 0.000001:
		return unavailable
	var ratio := chord.length() / chain_length
	var straight := ratio >= STRAIGHT_EXTENSION_RATIO and directions[0].dot(directions[1]) >= STRAIGHT_BEND_COSINE and directions[1].dot(directions[2]) >= STRAIGHT_BEND_COSINE and chord.normalized().dot(outward.normalized()) >= STRAIGHT_OUTWARD_COSINE
	var curled := ratio <= CURLED_EXTENSION_RATIO and directions[0].dot(directions[2]) <= CURLED_END_COSINE
	return {"valid": true, "straight": straight, "curled": curled}

func _invalid_gesture() -> Dictionary:
	return {"gesture_valid": false, "menu_pose": false, "wrist_origin": Vector3.ZERO, "wrist_basis": Basis.IDENTITY, "palm_normal": Vector3.ZERO}

func _position_tracked(tracker: XRHandTracker, joint: int) -> bool:
	return (tracker.get_hand_joint_flags(joint) & POSITION_FLAGS) == POSITION_FLAGS

func _invalid() -> Dictionary:
	_pinching = false
	var result := {"valid": false, "origin": Vector3.ZERO, "direction": Vector3.ZERO, "pinching": false}
	result.merge(_invalid_gesture())
	return result
