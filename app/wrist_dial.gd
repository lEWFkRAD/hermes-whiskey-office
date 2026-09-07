extends RefCounted
## Pure wrist-menu state: no nodes, input injection, permissions, or UI actions.
## Configure exactly eight unique nonempty string IDs with set_slots(ids).
## update accepts {valid, menu_pose, pinching, wrist_basis: Basis, cancel?: bool}.
## Hold the two-finger menu pose with an open pinch for 0.35 seconds to open.
## XRHandTracker uses Godot humanoid axes: +Y toward fingertips, -Y toward
## forearm, and +Z out through the palm. Freeze the initial -Y roll axis and
## project the +Z palm normal about it. Positive roll follows a right-handed
## rotation about this forearmward axis.
## Thus positive dial angles advance clockwise when looking along that axis.
## Convention: Godot4.7.2 openxr_hand_tracking_extension.cpp:230-246 converts
## OpenXR joint axes to these humanoid axes before filling XRHandTracker.
## GAIN 2.5 makes +/-72 physical degrees cover all eight 45-degree sectors.
## roll_degrees is continuous physical roll; dialangle_degrees wraps to [0,360).
## Pinch freezes selection; hold 0.18 seconds, then release to activate and close.
## Tracking loss, invalid geometry, cancel, or timeout close without activation.
## After closing, a new valid open-finger sample is required before invocation.
## Frame deltas are capped at 0.1s so a stalled frame cannot complete a hold.
## cancel() closes immediately and reports just_closed on the next update only.
## open_at(basis) explicitly opens a submenu/controller menu with a new neutral
## baseline. Its held pinch is ignored until open fingers have been observed.

const SLOT_COUNT := 8
const INVOKE_SECONDS := 0.35
const PINCH_SECONDS := 0.18
const POSE_DROP_SECONDS := 1.5
const TIMEOUT_SECONDS := 12.0
const ROLL_GAIN := 2.5
const SECTOR_DEGREES := 45.0
const HYSTERESIS_DEGREES := 7.0
const MAX_DELTA := 0.1

var _slots: Array[String] = []
var _open := false
var _ready := false
var _was_pinching := false
var _invoke_elapsed := 0.0
var _age := 0.0
var _pose_drop_elapsed := 0.0
var _pinch_elapsed := 0.0
var _pinch_active := false
var _selected_index := -1
var _latched_index := -1
var _forward := Vector3.DOWN
var _neutral_normal := Vector3.BACK
var _previous_raw_roll := 0.0
var _roll := 0.0
var _pending_closed := false
var _stick_selection := false
var _stick_roll_origin := 0.0

func set_slots(ids: Array) -> bool:
	cancel()
	_slots.clear()
	if ids.size() != SLOT_COUNT:
		return false
	var next: Array[String] = []
	for value: Variant in ids:
		if typeof(value) != TYPE_STRING and typeof(value) != TYPE_STRING_NAME:
			return false
		var id := str(value)
		if id.is_empty() or id.length() > 80 or id in next:
			return false
		next.append(id)
	_slots = next
	return true

func cancel() -> void:
	_pending_closed = _pending_closed or _open
	_close()

func is_open() -> bool:
	return _open

func open_at(basis: Basis) -> Dictionary:
	var was_open := _open or _pending_closed
	_close()
	_pending_closed = false
	if _slots.size() != SLOT_COUNT or not _basis_valid(basis):
		return _result(false, was_open)
	_begin(basis.orthonormalized())
	_ready = false
	_was_pinching = true
	return _result(true, false)

func _begin(basis: Basis) -> void:
	_open = true
	_invoke_elapsed = 0.0
	_selected_index = 0
	_forward = -basis.y
	_neutral_normal = basis.z
	_previous_raw_roll = 0.0
	_roll = 0.0
	_age = 0.0
	_pose_drop_elapsed = 0.0

func _close() -> void:
	_stick_selection = false
	_open = false
	_ready = false
	_was_pinching = false
	_invoke_elapsed = 0.0
	_age = 0.0
	_pose_drop_elapsed = 0.0
	_pinch_elapsed = 0.0
	_pinch_active = false
	_selected_index = -1
	_latched_index = -1
	_previous_raw_roll = 0.0
	_roll = 0.0

func _result(just_opened: bool, just_closed: bool, activated_id: String = "") -> Dictionary:
	var progress := 0.0
	if _open and _pinch_active:
		progress = clampf(_pinch_elapsed / PINCH_SECONDS, 0.0, 1.0)
	elif not _open:
		progress = clampf(_invoke_elapsed / INVOKE_SECONDS, 0.0, 1.0)
	return {
		"open": _open,
		"selected_index": _selected_index,
		"selected_id": _slots[_selected_index] if _selected_index >= 0 else "",
		"just_opened": just_opened,
		"just_closed": just_closed,
		"activated_id": activated_id,
		"progress": progress,
		"roll_degrees": _roll,
		"dialangle_degrees": float(_selected_index) * 45.0 if _stick_selection else fposmod(_roll * ROLL_GAIN, 360.0),
	}

func _basis_valid(value: Variant) -> bool:
	if typeof(value) != TYPE_BASIS:
		return false
	var basis: Basis = value
	var determinant := basis.determinant()
	return basis.x.is_finite() and basis.y.is_finite() and basis.z.is_finite() and is_finite(determinant) and determinant > 0.000001

func _update_roll(basis: Basis) -> bool:
	var normal := basis.z - _forward * basis.z.dot(_forward)
	if not normal.is_finite() or normal.length_squared() < 0.000001:
		return false
	normal = normal.normalized()
	var raw := rad_to_deg(atan2(_forward.dot(_neutral_normal.cross(normal)), _neutral_normal.dot(normal)))
	_roll += wrapf(raw - _previous_raw_roll, -180.0, 180.0)
	_previous_raw_roll = raw
	return true

func _update_selection() -> void:
	var angle := _roll * ROLL_GAIN
	var distance := wrapf(angle - float(_selected_index) * SECTOR_DEGREES, -180.0, 180.0)
	if absf(distance) > SECTOR_DEGREES * 0.5 + HYSTERESIS_DEGREES:
		_selected_index = int(floor((fposmod(angle, 360.0) + SECTOR_DEGREES * 0.5) / SECTOR_DEGREES)) % SLOT_COUNT

func update(sample: Dictionary, delta: float) -> Dictionary:
	var just_closed := _pending_closed
	_pending_closed = false
	if sample.get("cancel", false) == true:
		just_closed = just_closed or _open
		_close()
		return _result(false, just_closed)
	var valid: bool = typeof(sample.get("valid")) == TYPE_BOOL and sample.get("valid") == true
	valid = valid and typeof(sample.get("menu_pose")) == TYPE_BOOL and typeof(sample.get("pinching")) == TYPE_BOOL
	valid = valid and _basis_valid(sample.get("wrist_basis")) and is_finite(delta) and delta >= 0.0
	if not valid or _slots.size() != SLOT_COUNT:
		just_closed = just_closed or _open
		_close()
		return _result(false, just_closed)
	var dt := minf(delta, MAX_DELTA)
	var pinching: bool = sample["pinching"]
	var menu_pose: bool = sample["menu_pose"]
	var basis: Basis = sample["wrist_basis"].orthonormalized()
	if not _open:
		if not pinching:
			_ready = true
		if _ready and menu_pose and not pinching:
			_invoke_elapsed += dt
		else:
			_invoke_elapsed = 0.0
		_was_pinching = pinching
		if _invoke_elapsed + 0.000001 < INVOKE_SECONDS:
			return _result(false, just_closed)
		_begin(basis)
		return _result(true, just_closed)

	_age += dt
	if _age + 0.000001 >= TIMEOUT_SECONDS or not _update_roll(basis):
		_close()
		return _result(false, true)
	if menu_pose or pinching:
		_pose_drop_elapsed = 0.0
	else:
		_pose_drop_elapsed += dt
	if _pose_drop_elapsed + 0.000001 >= POSE_DROP_SECONDS:
		_close()
		return _result(false, true)

	# Selection is latched from the last open-finger frame. Neither pinch-start
	# jitter nor subsequent wrist movement can redirect an in-progress choice.
	if pinching:
		if not _was_pinching and _ready:
			_pinch_active = true
			_latched_index = _selected_index
			_pinch_elapsed = 0.0
		if _pinch_active:
			_pinch_elapsed += dt
	elif _pinch_active:
		var activate := _pinch_elapsed + 0.000001 >= PINCH_SECONDS
		var id := _slots[_latched_index] if activate else ""
		_pinch_active = false
		_pinch_elapsed = 0.0
		_latched_index = -1
		_ready = true
		_was_pinching = false
		if activate:
			_close()
			return _result(false, true, id)
	else:
		_ready = true
		var axis: Variant = sample.get("selection_axis", Vector2.ZERO)
		if axis is Vector2 and axis.is_finite() and axis.length() > 0.55:
			var angle := rad_to_deg(atan2(axis.x, axis.y))
			var distance := wrapf(angle - float(_selected_index) * 45.0, -180.0, 180.0)
			if absf(distance) > 22.5 + HYSTERESIS_DEGREES:
				_selected_index = posmod(int(round(angle / 45.0)), SLOT_COUNT)
			_stick_selection = true
			_stick_roll_origin = _roll
		elif _stick_selection and absf(_roll - _stick_roll_origin) > 8.0:
			_stick_selection = false
		if not _stick_selection: _update_selection()
	_was_pinching = pinching
	return _result(false, just_closed)
