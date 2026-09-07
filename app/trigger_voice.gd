extends RefCounted
## Routes a fresh right-trigger squeeze to native dictation or existing selection.
## This is an activation shortcut, not a microphone owner or a Send command.
const PRESS := 0.72
const RELEASE := 0.35
var owner := ""
var down := false
var blocked_until_release := true

func update(value: float, tracked: bool, ui_target: bool, menu_open: bool, grabbing: bool, cancel: bool) -> Dictionary:
	var consumed := owner == "voice"
	if not tracked or cancel or not is_finite(value):
		owner = ""
		down = false
		blocked_until_release = true
		return {"start": false, "consumed": consumed}
	var pressed := value > RELEASE if down else value >= PRESS
	var start := false
	if not pressed:
		blocked_until_release = false
		owner = ""
	elif not down and not blocked_until_release and owner.is_empty():
		owner = "ui" if ui_target or menu_open or grabbing else "voice"
		start = owner == "voice"
	consumed = consumed or owner == "voice"
	down = pressed
	return {"start": start, "consumed": consumed}
