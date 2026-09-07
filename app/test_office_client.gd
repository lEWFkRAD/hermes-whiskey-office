extends SceneTree
var failures: Array[String] = []

func check(value: bool, message: String) -> void:
	if not value: failures.append(message)

func _initialize() -> void:
	var client = load("res://office_client.gd").new()
	var valid := {"protocol_version": 1, "instance_id": "test-instance", "heartbeat": 100.0, "connection": {"status": "ready", "capabilities": {"chat": true}}, "messages": [{"role": "assistant", "content": "Saved reply"}], "sessions": [], "tools": [], "permissions": [], "future_optional_field": true}
	var parsed: Dictionary = client.decode_snapshot(JSON.stringify(valid), 101.0)
	check(parsed.connection.status == "ready", "Additive fields must stay compatible")
	client.state = parsed
	valid.protocol_version = 2
	parsed = client.decode_snapshot(JSON.stringify(valid), 101.0)
	check(parsed.connection.status == "incompatible" and not parsed.connection.capabilities.chat, "Major mismatch must disable sends")
	check(parsed.messages.size() == 1, "Mismatch must retain visible history")
	valid.protocol_version = true
	parsed = client.decode_snapshot(JSON.stringify(valid), 101.0)
	check(parsed.connection.status == "incompatible", "Boolean is not a protocol number")
	valid.protocol_version = 1
	parsed = client.decode_snapshot(JSON.stringify(valid), 120.0)
	check(parsed.connection.status == "offline", "A dead bridge must not look ready")
	valid.messages = "invalid"
	parsed = client.decode_snapshot(JSON.stringify(valid), 101.0)
	check(parsed.connection.status == "incompatible", "Malformed transcript shape must fail safely")
	parsed = client.decode_snapshot("{broken", 101.0)
	check(parsed.connection.status == "incompatible", "Malformed JSON must not crash")
	check(client.send_command("message.send", {"text": "No bridge"}).is_empty(), "Offline client must not create requests")
	client.free()
	print("HERMES_OFFICE_CLIENT_TESTS " + JSON.stringify({"passed": failures.is_empty(), "failures": failures}))
	quit(0 if failures.is_empty() else 1)
