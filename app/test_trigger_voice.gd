extends SceneTree
const Voice = preload("res://trigger_voice.gd")
class Office:
	extends "res://main.gd"
	func show_workbench(_value: bool) -> void: pass
class Desktop:
	extends RefCounted
	var commands: Array = []
	func send_command(kind: String, params: Dictionary) -> String:
		commands.append({"kind": kind, "params": params})
		return "fixture-command"
var failures: Array[String] = []
var checks := 0
func check(value: bool, message: String) -> void:
	checks += 1
	if not value: failures.append(message)
func tick(voice, pressure: float, target := false, menu := false, grip := false, valid := true, cancel := false) -> Dictionary:
	return voice.update(pressure, valid, target, menu, grip, cancel)
func _initialize() -> void:
	var voice = Voice.new()
	check(not tick(voice, 1.0).start, "Held trigger on startup never opens microphone")
	tick(voice, 0.0)
	check(tick(voice, 1.0).start, "Fresh empty-space squeeze invokes native dictation")
	check(not tick(voice, 1.0).start, "Holding cannot repeat start")
	check(not tick(voice, .5).start, "Pressure jitter cannot repeat start")
	check(tick(voice, .2, true).consumed, "Release over a window cannot click that window")
	check(not tick(voice, 0.0).consumed, "Released gesture returns ownership")
	check(not tick(voice, 1.0, true).start, "Aimed UI squeeze remains selection")
	check(not tick(voice, 1.0, false).consumed, "Dragging off a window cannot open microphone")
	tick(voice, 0.0)
	check(not tick(voice, 1.0, false, true).start, "Menu trigger stays with menu")
	tick(voice, 0.0)
	check(not tick(voice, 1.0, false, false, true).start, "Grab excludes dictation")
	tick(voice, 0.0)
	tick(voice, 1.0)
	tick(voice, 1.0, false, false, false, false)
	check(not tick(voice, 1.0).start, "Tracking return while held cannot restart dictation")
	tick(voice, 0.0)
	check(not tick(voice, 1.0, false, false, false, true, true).start, "Back suppresses simultaneous squeeze")
	check(not tick(voice, 1.0).start, "Held trigger after Back remains blocked")
	tick(voice, 0.0)
	check(not tick(voice, NAN).start and not tick(voice, 1.0).start, "Invalid tracking pressure requires a fresh release")
	tick(voice, 0.0)
	check(tick(voice, 1.0).start, "Explicit fresh squeeze rearms")
	var office := Office.new()
	var desktop := Desktop.new()
	office.desktop_surface = desktop
	office.request_voice_turn()
	check(desktop.commands == [{"kind": "navigate_hermes", "params": {"destination": "dictate"}}], "Native action starts dictation without submitting the existing draft")
	office.free()
	print("HERMES_TRIGGER_VOICE_TESTS " + JSON.stringify({"checks": checks, "failures": failures}))
	quit(0 if failures.is_empty() else 1)
