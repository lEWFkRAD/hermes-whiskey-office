extends Node
## The renderer speaks only our own versioned file contract, never ACP internals.
signal state_changed(state: Dictionary)
const PROTOCOL_VERSION := 1
const MAX_STATUS_BYTES := 8 * 1024 * 1024
var ipc_dir := ""
var state: Dictionary = {}
var timer := 0.0
var serial := 0
var last_payload := ""
var draft := ""

func _ready() -> void:
	ipc_dir = OS.get_environment("HERMES_OFFICE_BRIDGE_DIR")
	refresh()

func disconnected(reason: String, status := "offline") -> Dictionary:
	var result := state.duplicate(true)
	result["connection"] = {"status": status, "label": "Hermes connection unavailable", "reason": reason, "capabilities": {"chat": false, "sessions": false, "voice": false, "cancel": false}}
	result["busy"] = false
	return result

func decode_snapshot(payload: String, now: float) -> Dictionary:
	var parser := JSON.new()
	if parser.parse(payload) != OK or not parser.data is Dictionary:
		return disconnected("The integration returned an unreadable status. Your draft is safe.", "incompatible")
	var value: Dictionary = parser.data
	if typeof(value.get("protocol_version")) not in [TYPE_INT, TYPE_FLOAT] or float(value.get("protocol_version", -1)) != PROTOCOL_VERSION:
		return disconnected("This office and its integration use different protocol versions. Run the compatibility check.", "incompatible")
	if not value.get("connection") is Dictionary or not value.get("instance_id") is String:
		return disconnected("The integration status has an unsupported shape.", "incompatible")
	var heartbeat: Variant = value.get("heartbeat")
	if typeof(heartbeat) not in [TYPE_INT, TYPE_FLOAT] or now - float(heartbeat) > 8.0 or float(heartbeat) > now + 30.0:
		return disconnected("The integration stopped responding. An in-flight message will not be sent again automatically.")
	for key in ["sessions", "messages", "permissions", "tools"]:
		if value.has(key) and not value[key] is Array:
			return disconnected("The integration returned unsupported " + key + " data.", "incompatible")
	return value

func refresh() -> void:
	if ipc_dir.is_empty():
		state = disconnected("Open the office with its launcher to connect Hermes.")
		state_changed.emit(state)
		return
	var path := ipc_dir.path_join("status.json")
	if not FileAccess.file_exists(path):
		state = disconnected("Starting the Hermes integration…", "starting")
		state_changed.emit(state)
		return
	var file := FileAccess.open(path, FileAccess.READ)
	if not file or file.get_length() > MAX_STATUS_BYTES:
		state = disconnected("The integration status could not be read.")
		state_changed.emit(state)
		return
	var payload := file.get_as_text()
	state = decode_snapshot(payload, Time.get_unix_time_from_system())
	state_changed.emit(state)

func send_command(method: String, params: Dictionary = {}) -> String:
	var connection: Dictionary = state.get("connection", {})
	if ipc_dir.is_empty() or str(state.get("instance_id", "")).is_empty():
		return ""
	if method not in ["connection.refresh", "shutdown"] and connection.get("status", "offline") != "ready":
		return ""
	serial += 1
	var id := "%s-%s-%s" % [OS.get_process_id(), Time.get_ticks_usec(), serial]
	var envelope := {"protocol_version": PROTOCOL_VERSION, "instance_id": state["instance_id"], "id": id, "method": method, "params": params}
	var commands := ipc_dir.path_join("commands")
	if not DirAccess.dir_exists_absolute(commands):
		return ""
	var target := commands.path_join(id + ".json")
	var temporary := target + ".tmp"
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if not file:
		return ""
	file.store_string(JSON.stringify(envelope))
	file.close()
	if DirAccess.rename_absolute(temporary, target) != OK:
		return ""
	return id

func _process(delta: float) -> void:
	timer += delta
	if timer >= 0.5:
		timer = 0.0
		refresh()
