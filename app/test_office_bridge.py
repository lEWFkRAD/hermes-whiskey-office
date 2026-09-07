"""Offline subprocess contract tests. No Hermes, models, microphones, or network."""
import json
import base64
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from office_bridge import OfficeBridge, atomic_json, parse_args

APP = Path(__file__).resolve().parent

FAKE_VOICE = r'''
import argparse, json, sys, time
p=argparse.ArgumentParser()
p.add_argument('--action', required=True)
p.add_argument('--work-dir', required=True)
p.add_argument('--log', required=True)
p.add_argument('--scenario', default='normal')
a=p.parse_args()
def emit(**row):
    print(json.dumps(row), flush=True)
with open(a.log, 'a', encoding='utf-8') as f:
    f.write(json.dumps({'action':a.action,'argv':sys.argv})+'\n')
if a.action=='check':
    emit(event='status',status='ready' if a.scenario!='no-model' else 'unavailable',message='Fixture dependency check')
    sys.exit(3 if a.scenario=='no-model' else 0)
if a.action=='record':
    emit(event='status',status='listening',message='Fixture recording')
    if a.scenario=='hold':
        time.sleep(30)
    elif a.scenario=='bad-json':
        print('broken output',flush=True)
        time.sleep(30)
    elif a.scenario=='record-fail':
        emit(event='transcript',text='Must not submit failed capture')
        sys.exit(4)
    else:
        emit(event='status',status='transcribing',message='Fixture transcription')
        emit(event='transcript',text='What is in my office?')
elif a.action=='speak':
    text=sys.stdin.read()
    with open(a.log, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'spoken':text})+'\n')
    if a.scenario=='speak-fail':
        sys.exit(5)
    emit(event='done')
'''


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix=".bridge-test-", dir=APP)).resolve()
        self.bridges = []
        self.seq = 0

    def tearDown(self):
        for bridge in self.bridges:
            bridge.stop_voice(force=True)
            bridge.stop_child()
            for child, _ in bridge.voice_retired:
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)
        if self.root.parent != APP:
            raise AssertionError("Temporary test path left the app workspace")
        shutil.rmtree(self.root)

    def make(self, scenario="normal", probe=False, data_dir=None, voice_scenario=None):
        index = len(self.bridges)
        log = self.root / ("child-" + str(index) + ".jsonl")
        command = [sys.executable, "-u", str(APP / "fake_acp.py"), "--scenario", scenario, "--log", str(log)]
        voice_command = None
        voice_log = self.root / ("voice-" + str(index) + ".jsonl")
        if voice_scenario:
            helper = self.root / "fake_voice.py"
            helper.write_text(FAKE_VOICE, encoding="utf-8")
            voice_command = [sys.executable, "-u", str(helper), "--log", str(voice_log), "--scenario", voice_scenario]
        bridge = OfficeBridge(self.root / ("ipc-" + str(index)), self.root / "workspace",
                              data_dir or self.root / ("data-" + str(index)), command, probe=probe, voice_command=voice_command)
        bridge.test_log = log
        bridge.test_voice_log = voice_log
        self.bridges.append(bridge)
        bridge.start_child()
        self.wait(bridge, lambda: bridge.state["connection"]["status"] != "starting")
        return bridge

    def wait(self, bridge, condition, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            bridge.tick()
            if condition():
                return
            time.sleep(0.01)
        self.fail("Timed out: " + json.dumps(bridge.state))

    def command(self, bridge, method, params=None, cid=None, instance=None):
        self.seq += 1
        cid = cid or "command-" + str(self.seq)
        envelope = {"protocol_version": 1, "instance_id": instance or bridge.instance_id,
                    "id": cid, "method": method, "params": params or {}}
        bridge.execute_command(envelope)
        return cid

    def new(self, bridge):
        self.command(bridge, "session.new")
        self.wait(bridge, lambda: bridge.loaded_session == "new-session" and not bridge.state["busy"])

    def sent(self, bridge, method):
        if not bridge.test_log.exists():
            return []
        return [row for line in bridge.test_log.read_text(encoding="utf-8").splitlines()
                if (row := json.loads(line)).get("method") == method]

    def test_handshake_and_probe_never_create_or_prompt(self):
        bridge = self.make(probe=True)
        self.assertEqual(bridge.state["connection"]["protocol_version"], 1)
        self.assertTrue(bridge.state["connection"]["capabilities"]["chat"])
        self.assertFalse(bridge.state["connection"]["capabilities"]["voice"])
        self.assertEqual(len(self.sent(bridge, "initialize")), 1)
        self.assertFalse(self.sent(bridge, "session/list"))
        self.assertFalse(self.sent(bridge, "session/new"))
        self.assertFalse(self.sent(bridge, "session/prompt"))
        self.assertNotIn("secret-do-not-publish", json.dumps(bridge.state))

    def test_protocol_two_incompatible(self):
        bridge = self.make("protocol2")
        self.assertEqual(bridge.state["connection"]["status"], "incompatible")
        self.command(bridge, "session.new")
        self.assertEqual(bridge.state["last_command"]["status"], "rejected")
        self.assertFalse(self.sent(bridge, "session/new"))

    def test_missing_optional_caps_preserves_core_chat_only(self):
        bridge = self.make("missing-caps")
        self.assertTrue(bridge.state["connection"]["capabilities"]["chat"])
        self.assertFalse(bridge.state["connection"]["capabilities"]["sessions"])
        self.command(bridge, "session.select", {"id": "saved-session"})
        self.assertEqual(bridge.state["last_command"]["status"], "rejected")
        self.new(bridge)

    def test_malformed_json_fails_closed(self):
        bridge = self.make("malformed")
        self.assertEqual(bridge.state["connection"]["status"], "offline")
        self.assertFalse(bridge.state["connection"]["capabilities"]["chat"])

    def test_load_replays_before_response_and_live_chunks_merge(self):
        bridge = self.make()
        self.wait(bridge, lambda: bool(bridge.state["sessions"]))
        self.command(bridge, "session.select", {"id": "saved-session"})
        self.wait(bridge, lambda: bridge.loaded_session == "saved-session" and not bridge.state["busy"])
        self.assertEqual(bridge.state["messages"], [{"role": "user", "content": "Earlier question"},
                                                    {"role": "assistant", "content": "Earlier answer"}])
        self.assertEqual(bridge.state["tools"][0]["status"], "completed")
        self.command(bridge, "message.send", {"text": "Continue"})
        self.wait(bridge, lambda: not bridge.state["busy"])
        self.assertEqual(bridge.state["selected_session"], "saved-session")
        self.assertEqual(bridge.state["messages"][-1], {"role": "assistant", "content": "Hello office"})
        self.assertEqual(len(bridge.state["messages"]), 4)
        self.assertEqual(bridge.state["tools"][0]["title"], "Read workspace")
        self.assertNotIn("Not a reply", json.dumps(bridge.state))

    def test_duplicate_and_stale_commands_never_replay_send(self):
        bridge = self.make()
        self.new(bridge)
        self.command(bridge, "message.send", {"text": "One send"}, cid="send-once")
        self.wait(bridge, lambda: not bridge.state["busy"])
        self.command(bridge, "message.send", {"text": "One send"}, cid="send-once")
        self.assertEqual(bridge.state["last_command"]["status"], "duplicate")
        self.command(bridge, "message.send", {"text": "Stale"}, instance="old-instance")
        self.assertEqual(bridge.state["last_command"]["status"], "rejected")
        self.assertEqual(len(self.sent(bridge, "session/prompt")), 1)

    def test_crash_midturn_keeps_partial_uncertain_and_restart_does_not_send(self):
        bridge = self.make("crash")
        self.new(bridge)
        self.command(bridge, "message.send", {"text": "Do work"}, cid="crash-send")
        self.wait(bridge, lambda: bridge.state["connection"]["status"] == "offline")
        self.assertEqual(bridge.state["last_command"]["status"], "uncertain")
        self.assertEqual(bridge.state["messages"][-1]["content"], "Partial answer")
        self.assertFalse(bridge.state["busy"])
        self.command(bridge, "message.send", {"text": "Try again"})
        self.assertEqual(bridge.state["last_command"]["status"], "rejected")
        other = self.make(data_dir=bridge.data_dir)
        self.assertEqual(other.state["messages"][-1]["content"], "Partial answer")
        self.assertIsNone(other.loaded_session)
        self.assertFalse(self.sent(other, "session/prompt"))
        self.command(other, "message.send", {"text": "Cannot send cached-only"})
        self.assertEqual(other.state["last_command"]["status"], "rejected")

    def test_permission_requires_offered_option_and_never_auto_approves(self):
        bridge = self.make("permission")
        self.new(bridge)
        self.command(bridge, "message.send", {"text": "Permission test"})
        self.wait(bridge, lambda: bool(bridge.state["permissions"]))
        permission = bridge.state["permissions"][0]
        self.assertEqual(permission["title"], "Write a test file")
        self.command(bridge, "permission.reply", {"id": permission["id"], "option_id": "allow_always"})
        self.assertEqual(bridge.state["last_command"]["status"], "rejected")
        self.assertEqual(len(bridge.state["permissions"]), 1)
        self.assertTrue(bridge.state["busy"])
        self.command(bridge, "permission.reply", {"id": permission["id"], "option_id": "deny"})
        self.wait(bridge, lambda: not bridge.state["busy"])
        self.assertEqual(bridge.state["messages"][-1]["content"], "Permission choice: deny")
        self.assertFalse(bridge.state["permissions"])

    def test_cancellation_waits_for_terminal_and_busy_rejects_double_send(self):
        bridge = self.make("cancel")
        self.new(bridge)
        self.command(bridge, "message.send", {"text": "Long work"}, cid="long-turn")
        self.wait(bridge, lambda: bool(self.sent(bridge, "session/prompt")))
        self.command(bridge, "message.send", {"text": "Second work"})
        self.assertEqual(bridge.state["last_command"]["status"], "rejected")
        self.command(bridge, "connection.refresh")
        self.assertEqual(bridge.state["last_command"]["status"], "rejected")
        self.command(bridge, "turn.cancel")
        self.assertTrue(bridge.state["busy"])
        self.wait(bridge, lambda: not bridge.state["busy"])
        self.assertEqual(bridge.state["last_command"], {"id": "long-turn", "status": "cancelled", "error": ""})
        self.assertEqual(len(self.sent(bridge, "session/prompt")), 1)
        self.assertEqual(len(self.sent(bridge, "session/cancel")), 1)

    def test_atomic_ipc_status_and_malformed_command_types(self):
        bridge = self.make()
        envelope = {"protocol_version": 1, "instance_id": bridge.instance_id, "id": "file-command",
                    "method": "session.new", "params": {}}
        atomic_json(bridge.ipc_dir / "commands" / "001.json", envelope)
        self.wait(bridge, lambda: bridge.loaded_session == "new-session")
        bridge.publish(force=True)
        status = json.loads((bridge.ipc_dir / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["instance_id"], bridge.instance_id)
        self.assertLess(abs(time.time() - status["heartbeat"]), 2)
        for index, invalid in enumerate(([1], "bad", None, 3, True)):
            bridge.execute_command({"protocol_version": 1, "instance_id": bridge.instance_id,
                                    "id": "invalid-" + str(index), "method": "message.send", "params": invalid})
            self.assertEqual(bridge.state["last_command"]["status"], "rejected")
        bridge.execute_command({"protocol_version": True, "instance_id": bridge.instance_id,
                                "id": "bad-version", "method": "session.new", "params": {}})
        self.assertEqual(bridge.state["last_command"]["status"], "rejected")
        self.assertEqual(len(self.sent(bridge, "session/new")), 1)

    def test_unsupported_reverse_rpc_has_error_not_permission(self):
        bridge = self.make()
        bridge.reverse_request({"jsonrpc": "2.0", "id": "unknown-rpc", "method": "fs/read_text_file", "params": {}})
        self.wait(bridge, lambda: '"unknown-rpc"' in bridge.test_log.read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in bridge.test_log.read_text(encoding="utf-8").splitlines()]
        response = next(r for r in rows if r.get("id") == "unknown-rpc")
        self.assertEqual(response["error"]["code"], -32601)
        self.assertFalse(bridge.state["permissions"])

    def test_probe_cli_receipt_is_initialize_only(self):
        receipt = self.root / "receipt.json"
        log = self.root / "probe-log.jsonl"
        argv = [sys.executable, str(APP / "office_bridge.py"), "--probe", "--receipt", str(receipt),
                "--acp-command", json.dumps([sys.executable, "-u", str(APP / "fake_acp.py"), "--log", str(log)])]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["probe_only"])
        self.assertEqual(report["sessions_created"], 0)
        self.assertEqual(json.loads(receipt.read_text()), report)
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([row["method"] for row in rows], ["initialize"])

    def test_explicit_capture_is_attached_only_to_this_turn_and_not_cached(self):
        bridge = self.make()
        self.new(bridge)
        raw = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
        (bridge.ipc_dir / "captures" / "headset.png").write_bytes(raw)
        self.assertTrue(bridge.state["connection"]["capabilities"]["images"])
        self.command(bridge, "message.send", {"text": "Look at my view", "image_name": "headset.png"})
        self.wait(bridge, lambda: not bridge.state["busy"])
        prompt = self.sent(bridge, "session/prompt")[0]["params"]["prompt"]
        self.assertEqual(prompt[1], {"type": "image", "mimeType": "image/png", "data": base64.b64encode(raw).decode("ascii")})
        self.assertIn("[Shared view: headset.png]", bridge.state["messages"][0]["content"])
        self.assertNotIn(prompt[1]["data"], json.dumps(bridge.state))
        self.assertNotIn(prompt[1]["data"], (bridge.data_dir / "conversations.json").read_text())
        self.command(bridge, "message.send", {"text": "Next turn"})
        self.wait(bridge, lambda: not bridge.state["busy"])
        self.assertEqual(len(self.sent(bridge, "session/prompt")[1]["params"]["prompt"]), 1)

    def test_capture_paths_types_size_and_missing_capability_fail_closed(self):
        bridge = self.make()
        self.new(bridge)
        (self.root / "outside.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (bridge.ipc_dir / "captures" / "bad.png").write_bytes(b"not an image")
        (bridge.ipc_dir / "captures" / "huge.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * (4 * 1024 * 1024))
        for name in ("../outside.png", str(self.root / "outside.png"), "bad.png", "huge.png", "missing.jpg", False):
            self.command(bridge, "message.send", {"text": "View", "image_name": name})
            self.assertEqual(bridge.state["last_command"]["status"], "rejected")
            self.assertFalse(bridge.state["busy"])
        bridge.state["connection"]["capabilities"]["images"] = False
        self.command(bridge, "message.send", {"text": "View", "image_name": "headset.png"})
        self.assertEqual(bridge.state["last_command"]["status"], "rejected")
        self.assertFalse(self.sent(bridge, "session/prompt"))

    def voice_rows(self, bridge):
        return [json.loads(line) for line in bridge.test_voice_log.read_text(encoding="utf-8").splitlines()] if bridge.test_voice_log.exists() else []

    def voice_ready(self, bridge):
        self.wait(bridge, lambda: bridge.voice_context is None)
        self.assertTrue(bridge.state["connection"]["capabilities"]["voice"])

    def test_voice_check_never_records_and_missing_cache_disables_voice(self):
        bridge = self.make(voice_scenario="normal")
        self.voice_ready(bridge)
        self.assertEqual([r["action"] for r in self.voice_rows(bridge)], ["check"])
        other = self.make(voice_scenario="no-model")
        self.wait(other, lambda: other.voice_context is None)
        self.assertFalse(other.state["connection"]["capabilities"]["voice"])
        self.new(other)
        self.command(other, "voice.record")
        self.assertEqual(other.state["last_command"]["status"], "rejected")
        self.assertEqual([r["action"] for r in self.voice_rows(other)], ["check"])

    def test_voice_uses_selected_session_image_and_speaks_only_its_reply(self):
        bridge = self.make(voice_scenario="normal")
        self.voice_ready(bridge)
        self.new(bridge)
        (bridge.ipc_dir / "captures" / "view.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        self.command(bridge, "voice.record", {"image_name": "view.png"}, cid="voice-turn")
        self.wait(bridge, lambda: any("spoken" in r for r in self.voice_rows(bridge)) and not bridge.state["busy"])
        sent = self.sent(bridge, "session/prompt")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["params"]["sessionId"], "new-session")
        self.assertEqual(sent[0]["params"]["prompt"][0]["text"], "What is in my office?")
        self.assertEqual(sent[0]["params"]["prompt"][1]["type"], "image")
        self.assertEqual([r["spoken"] for r in self.voice_rows(bridge) if "spoken" in r], ["Hello office"])
        self.assertEqual(bridge.state["last_command"], {"id": "voice-turn", "status": "completed", "error": ""})
        self.assertEqual(bridge.state["voice_status"], "ready")
        self.command(bridge, "message.send", {"text": "Typed followup"})
        self.wait(bridge, lambda: not bridge.state["busy"])
        self.assertEqual(len([r for r in self.voice_rows(bridge) if r.get("action") == "speak"]), 1)
        self.assertEqual(len(self.sent(bridge, "session/prompt")[1]["params"]["prompt"]), 1)

    def test_voice_record_cancel_kills_only_owned_helper_and_never_sends(self):
        bridge = self.make(voice_scenario="hold")
        self.voice_ready(bridge)
        self.new(bridge)
        self.command(bridge, "voice.record")
        self.wait(bridge, lambda: bridge.state["voice_status"] == "listening")
        child = bridge.voice_child
        self.command(bridge, "voice.record")
        self.assertEqual(bridge.state["last_command"]["status"], "rejected")
        self.command(bridge, "message.send", {"text": "Competing turn"})
        self.assertEqual(bridge.state["last_command"]["status"], "rejected")
        self.command(bridge, "turn.cancel")
        self.wait(bridge, lambda: child.poll() is not None)
        self.assertFalse(bridge.state["busy"])
        self.assertEqual(bridge.state["voice_status"], "cancelled")
        self.assertFalse(self.sent(bridge, "session/prompt"))
        self.assertIsNone(bridge.child.poll())

    def test_failed_record_does_not_submit_and_failed_speak_preserves_text(self):
        bridge = self.make(voice_scenario="record-fail")
        self.voice_ready(bridge)
        self.new(bridge)
        self.command(bridge, "voice.record")
        self.wait(bridge, lambda: not bridge.state["busy"])
        self.assertEqual(bridge.state["voice_status"], "error")
        self.assertFalse(self.sent(bridge, "session/prompt"))
        other = self.make(voice_scenario="speak-fail")
        self.voice_ready(other)
        self.new(other)
        self.command(other, "voice.record")
        self.wait(other, lambda: not other.state["busy"])
        self.assertEqual(other.state["voice_status"], "error")
        self.assertEqual(other.state["messages"][-1]["content"], "Hello office")
        self.assertIn("text is saved", other.state["voice_message"])

    def test_voice_malformed_output_and_probe_cannot_record(self):
        bridge = self.make(voice_scenario="bad-json")
        self.voice_ready(bridge)
        self.new(bridge)
        self.command(bridge, "voice.record")
        self.wait(bridge, lambda: not bridge.state["busy"])
        self.assertEqual(bridge.state["voice_status"], "error")
        self.assertFalse(self.sent(bridge, "session/prompt"))
        probe = self.make(probe=True, voice_scenario="normal")
        self.assertFalse(self.voice_rows(probe))
        self.assertFalse(probe.state["connection"]["capabilities"]["voice"])


if __name__ == "__main__":
    unittest.main()
