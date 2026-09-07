#!/usr/bin/env python3
"""Foreground Hermes ACP adapter; Python standard library only.

The UI writes atomic commands/*.json envelopes with protocol_version=1,
instance_id, unique id, method and params. This process atomically publishes
status.json every 0.5 seconds. IPC is private local application data, not a
network listener. Never put credentials in commands or the status document.

ACP uses NDJSON over one owned child process. Only exact protocol 1 is accepted.
History notifications during session/load are replay, not new conversation.
ACP sessions are Hermes' ACP conversations, not a view of all gateway sessions.
The cache is display-only until an explicit session.select loads it. No send is
ever retried automatically, including after process death or connection.refresh.
Permission requests require an exact offered option chosen by the user.
The UI owns the bridge lifetime and should send shutdown when closing.

Optional HERMES_OFFICE_VOICE_COMMAND is a JSON argv for a speech-only helper.
Its check action never records. voice.record is the only recording trigger;
its transcript goes to the selected ACP session and only that successful turn
is spoken. The helper runs in an owned process group; no voice turns are retried.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

IPC_VERSION = 1
ACP_VERSION = 1
MAX_LINE = 2 * 1024 * 1024
MAX_COMMAND = 128 * 1024
MAX_SEND = 32 * 1024
MAX_TEXT = 128 * 1024
MAX_MESSAGES = 200
MAX_SESSIONS = 1000
MAX_IMAGE = 4 * 1024 * 1024
SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def valid_id(value) -> bool:
    return isinstance(value, str) and SAFE_ID.fullmatch(value) is not None


def clean_text(value, limit=MAX_TEXT) -> str:
    return value[:limit] if isinstance(value, str) else ""


def exact_int(value, expected) -> bool:
    return type(value) is int and value == expected


class OfficeBridge:
    def __init__(self, ipc_dir, workspace, data_dir, command, *, probe=False, voice_command=None):
        self.ipc_dir = Path(ipc_dir) if ipc_dir else None
        self.workspace = Path(workspace)
        self.data_dir = Path(data_dir)
        self.command = command
        self.probe = probe
        self.instance_id = uuid.uuid4().hex
        self.child = None
        self.events = queue.Queue(maxsize=256)
        self.generation = 0
        self.pending = {}
        self.counter = 0
        self.seen_ids = set()
        self.seen_files = set()
        self.transcripts = {}
        self.loaded_session = None
        self.replay_session = None
        self.replay_messages = []
        self.replay_tools = []
        self.assistant_open = False
        self.permission_requests = {}
        self.stop_requested = False
        self.started_at = time.monotonic()
        self.last_publish = 0.0
        self.list_cursor_seen = set()
        self.uncertain_turn = False
        self.voice_child = None
        self.voice_events = queue.Queue(maxsize=64)
        self.voice_generation = 0
        self.voice_context = None
        self.voice_retired = []
        self.voice_check_started = False
        self.voice_available = False
        self.voice_turn = None
        self.voice_command = None
        voice_problem = "Voice helper is not configured."
        try:
            supplied = voice_command if voice_command is not None else os.environ.get("HERMES_OFFICE_VOICE_COMMAND", "")
            parsed = json.loads(supplied) if isinstance(supplied, str) and supplied else supplied
            if parsed:
                if not isinstance(parsed, list) or not all(isinstance(a, str) and a and "\x00" not in a for a in parsed):
                    raise ValueError()
                if not (shutil.which(parsed[0]) or Path(parsed[0]).is_file()):
                    raise ValueError()
                self.voice_command = list(parsed)
                voice_problem = "Checking microphone and speech dependencies."
        except (ValueError, OSError):
            voice_problem = "Configured voice helper is unavailable or invalid."
        self.state = {
            "protocol_version": IPC_VERSION, "instance_id": self.instance_id,
            "heartbeat": time.time(), "connection": self.connection("starting"),
            "sessions": [], "selected_session": "", "messages": [],
            "tasks": {}, "busy": False, "permissions": [], "tools": [],
            "error": "", "last_command": {"id": "", "status": "", "error": ""},
            "voice_status": "unavailable", "voice_message": voice_problem,
        }
        if not probe:
            self.ipc_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            (self.ipc_dir / "commands").mkdir(exist_ok=True, mode=0o700)
            (self.ipc_dir / "captures").mkdir(exist_ok=True, mode=0o700)
            self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.workspace.mkdir(parents=True, exist_ok=True)
            self.load_cache()

    @staticmethod
    def connection(status, reason="", *, version="", protocol=None, chat=False, sessions=False, images=False):
        labels = {"starting": "Connecting to Hermes", "ready": "Hermes connected",
                  "offline": "Hermes offline", "incompatible": "Hermes version unsupported"}
        return {"status": status, "label": labels[status], "reason": reason,
                "capabilities": {"chat": chat, "sessions": sessions, "voice": False, "cancel": chat, "images": images},
                "hermes_version": version, "protocol_version": protocol}

    def load_cache(self):
        path = self.data_dir / "conversations.json"
        try:
            if path.stat().st_size > 32 * 1024 * 1024:
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("protocol_version") != IPC_VERSION:
                return
            sessions = data.get("sessions", [])
            if isinstance(sessions, list):
                for row in sessions[:MAX_SESSIONS]:
                    if isinstance(row, dict) and valid_id(row.get("id")):
                        self.remember_session(row["id"], clean_text(row.get("title"), 160), row.get("cwd"))
            records = data.get("transcripts", {})
            if isinstance(records, dict):
                for sid, messages in records.items():
                    if valid_id(sid) and isinstance(messages, list):
                        self.transcripts[sid] = [
                            {"role": m["role"], "content": clean_text(m.get("content"))}
                            for m in messages[-MAX_MESSAGES:]
                            if isinstance(m, dict) and m.get("role") in ("user", "assistant", "system")
                            and isinstance(m.get("content"), str)]
            selected = data.get("selected_session")
            if valid_id(selected) and any(s["id"] == selected for s in self.state["sessions"]):
                self.state["selected_session"] = selected
                self.state["messages"] = list(self.transcripts.get(selected, []))
            if data.get("uncertain_turn"):
                self.uncertain_turn = True
                self.state["error"] = "The previous turn may be incomplete. Select its conversation to reconnect; it will not be sent again."
        except (OSError, ValueError, TypeError):
            self.state["error"] = "Saved conversations could not be read. The original cache has not been changed."

    def persist(self):
        if self.probe:
            return
        sid = self.state["selected_session"]
        if sid and self.replay_session is None:
            self.transcripts[sid] = list(self.state["messages"])
        payload = {"protocol_version": IPC_VERSION, "sessions": self.state["sessions"],
                   "selected_session": sid, "transcripts": self.transcripts,
                   "uncertain_turn": self.uncertain_turn}
        try:
            atomic_json(self.data_dir / "conversations.json", payload)
        except OSError:
            self.state["error"] = "Conversation cache could not be saved. Keep this window open until the turn ends."

    def publish(self, force=False):
        if self.probe or (not force and time.monotonic() - self.last_publish < 0.5):
            return
        self.state["heartbeat"] = time.time()
        atomic_json(self.ipc_dir / "status.json", self.state)
        self.last_publish = time.monotonic()

    def start_child(self):
        if not self.probe and not self.voice_check_started:
            self.voice_check_started = True
            if self.voice_command:
                self.start_voice("check")
        self.generation += 1
        generation = self.generation
        self.pending.clear()
        self.permission_requests.clear()
        self.state["permissions"] = []
        self.loaded_session = None
        self.state["connection"] = self.connection("starting")
        self.started_at = time.monotonic()
        env = os.environ.copy()
        if self.probe:
            env["HERMES_ACP_SKIP_CONFIGURED_MCP"] = "1"
        try:
            self.child = subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(self.workspace) if self.workspace.is_dir() else None, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, ValueError):
            self.offline("Could not start the configured Hermes ACP command.")
            return
        child = self.child

        def read_stdout():
            try:
                while True:
                    line = child.stdout.readline(MAX_LINE + 1)
                    if not line:
                        self.events.put((generation, "eof", None))
                        return
                    if len(line) > MAX_LINE:
                        self.events.put((generation, "invalid", None))
                        return
                    if line.strip():
                        try:
                            message = json.loads(line.decode("utf-8"))
                            if not isinstance(message, dict):
                                raise ValueError("Not an object")
                        except (UnicodeError, ValueError):
                            self.events.put((generation, "invalid", None))
                            return
                        self.events.put((generation, "message", message))
            except OSError:
                self.events.put((generation, "eof", None))

        def drain_stderr():
            # Diagnostic streams may contain credentials or user text. Drain but never publish.
            try:
                while child.stderr.read(4096):
                    pass
            except OSError:
                pass

        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=drain_stderr, daemon=True).start()
        self.request("initialize", {"protocolVersion": ACP_VERSION,
                     "clientInfo": {"name": "hermes-whiskey-office", "version": "1"},
                     "clientCapabilities": {}}, "initialize")

    def write(self, payload):
        try:
            if not self.child or self.child.poll() is not None:
                raise BrokenPipeError()
            self.child.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            self.child.stdin.flush()
            return True
        except (OSError, ValueError):
            self.offline("Hermes disconnected. No message will be retried automatically.")
            return False

    def request(self, method, params, kind, command_id=""):
        self.counter += 1
        rid = "office-" + str(self.counter)
        self.pending[rid] = {"kind": kind, "command_id": command_id, "sent_at": time.monotonic()}
        self.write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return rid

    def notify(self, method, params):
        return self.write({"jsonrpc": "2.0", "method": method, "params": params})

    def stop_child(self):
        child, self.child = self.child, None
        if child:
            try:
                child.stdin.close()
            except (OSError, ValueError):
                pass
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)
            for handle in (child.stdout, child.stderr):
                try:
                    handle.close()
                except (OSError, ValueError):
                    pass

    def offline(self, reason, incompatible=False):
        if self.voice_context and self.voice_context["action"] != "check":
            self.stop_voice()
            self.state.update(voice_status="error", voice_message="Voice stopped because Hermes disconnected.")
        elif self.voice_turn:
            self.state.update(voice_status="error", voice_message="The Hermes voice turn disconnected. Its text is preserved.")
        self.voice_turn = None
        prompt = next((p for p in self.pending.values() if p["kind"] == "prompt"), None)
        if prompt:
            self.uncertain_turn = True
            self.ack(prompt["command_id"], "uncertain", "Hermes disconnected during the turn. The partial transcript is preserved; the message was not retried.")
        self.state["busy"] = False
        self.state["connection"] = self.connection("incompatible" if incompatible else "offline", reason)
        self.state["error"] = reason
        self.loaded_session = None
        self.replay_session = None
        self.pending.clear()
        self.permission_requests.clear()
        self.state["permissions"] = []
        for tool in self.state["tools"]:
            if tool["status"] in ("pending", "in_progress"):
                tool["status"] = "uncertain"
        self.persist()

    def ack(self, command_id, status, error=""):
        if command_id:
            self.state["last_command"] = {"id": command_id, "status": status, "error": error}
        if error:
            self.state["error"] = error

    def remember_session(self, sid, title="", cwd=None):
        for row in self.state["sessions"]:
            if row["id"] == sid:
                if title:
                    row["title"] = title[:160]
                if isinstance(cwd, str) and cwd:
                    row["cwd"] = cwd[:4096]
                return
        if len(self.state["sessions"]) < MAX_SESSIONS:
            self.state["sessions"].append({"id": sid, "title": title[:160] or "New conversation",
                                           "cwd": clean_text(cwd, 4096) or str(self.workspace)})

    def handle_message(self, message):
        if message.get("jsonrpc") != "2.0":
            self.offline("Hermes sent an invalid protocol message.")
            return
        if "method" in message:
            if "id" in message:
                self.reverse_request(message)
            elif message.get("method") == "session/update":
                self.session_update(message.get("params"))
            return
        rid = message.get("id")
        if not isinstance(rid, str):
            return
        pending = self.pending.pop(rid, None)
        if pending is None:
            return
        kind, cid = pending["kind"], pending["command_id"]
        if "error" in message or not isinstance(message.get("result"), dict):
            if kind == "initialize":
                self.offline("Hermes did not accept the ACP handshake.", incompatible=True)
            else:
                self.state["busy"] = False
                self.replay_session = None
                self.ack(cid, "failed", "Hermes rejected the request. Nothing was retried.")
                if kind == "prompt" and self.voice_turn:
                    self.voice_turn = None
                    self.state.update(voice_status="error", voice_message="Hermes rejected the voice turn. It was not retried.")
                self.persist()
            return
        result = message["result"]
        if kind == "initialize":
            protocol = result.get("protocolVersion")
            caps = result.get("agentCapabilities")
            if not exact_int(protocol, ACP_VERSION) or not isinstance(caps, dict):
                self.offline("This office requires Hermes ACP protocol 1 and a capability handshake.", incompatible=True)
                return
            sessions = caps.get("sessionCapabilities", {})
            has_sessions = caps.get("loadSession") is True and isinstance(sessions, dict) and isinstance(sessions.get("list"), dict)
            info = result.get("agentInfo", {})
            version = clean_text(info.get("version"), 80) if isinstance(info, dict) else ""
            prompt_caps = caps.get("promptCapabilities", {})
            images = isinstance(prompt_caps, dict) and prompt_caps.get("image") is True
            self.state["connection"] = self.connection("ready", version=version, protocol=protocol, chat=True, sessions=has_sessions, images=images)
            self.state["connection"]["capabilities"]["voice"] = self.voice_available
            if not self.uncertain_turn:
                self.state["error"] = ""
            if not self.probe and has_sessions:
                self.list_cursor_seen.clear()
                self.request("session/list", {}, "list")
            self.ack(cid, "completed")
        elif kind == "list":
            rows = result.get("sessions", [])
            if isinstance(rows, list):
                for row in rows[:MAX_SESSIONS]:
                    if isinstance(row, dict) and valid_id(row.get("sessionId")):
                        self.remember_session(row["sessionId"], clean_text(row.get("title"), 160), row.get("cwd"))
            cursor = result.get("nextCursor")
            if valid_id(cursor) and cursor not in self.list_cursor_seen and len(self.list_cursor_seen) < 20:
                self.list_cursor_seen.add(cursor)
                self.request("session/list", {"cursor": cursor}, "list")
            self.persist()
        elif kind == "new":
            sid = result.get("sessionId")
            if not valid_id(sid):
                self.state["busy"] = False
                self.ack(cid, "failed", "Hermes returned an invalid conversation identifier.")
                return
            self.remember_session(sid)
            self.state.update(selected_session=sid, messages=[], tools=[], busy=False, error="")
            self.loaded_session = sid
            self.uncertain_turn = False
            self.ack(cid, "completed")
            self.persist()
        elif kind == "load":
            sid = self.replay_session
            self.state.update(selected_session=sid, messages=self.replay_messages[-MAX_MESSAGES:],
                              tools=self.replay_tools[-100:], busy=False, error="")
            self.loaded_session = sid
            self.uncertain_turn = False
            self.replay_session = None
            self.assistant_open = False
            self.ack(cid, "completed")
            self.persist()
        elif kind == "prompt":
            self.state["busy"] = False
            self.assistant_open = False
            self.permission_requests.clear()
            self.state["permissions"] = []
            stop = result.get("stopReason")
            self.uncertain_turn = stop not in ("cancelled", "end_turn", "max_tokens", "max_turn_requests", "refusal")
            if stop == "cancelled":
                self.ack(cid, "cancelled")
                for tool in self.state["tools"]:
                    if tool["status"] in ("pending", "in_progress"):
                        tool["status"] = "cancelled"
            elif stop in ("end_turn", "max_tokens", "max_turn_requests", "refusal"):
                self.ack(cid, "completed" if stop == "end_turn" else "stopped", "" if stop == "end_turn" else "Hermes stopped the turn: " + stop)
            else:
                self.ack(cid, "uncertain", "Hermes ended the request without a recognized turn result.")
            self.persist()
            voice_turn, self.voice_turn = self.voice_turn, None
            if voice_turn and voice_turn["command_id"] == cid:
                if stop == "end_turn" and voice_turn["reply"].strip():
                    self.state["busy"] = True
                    self.start_voice("speak", cid, text=voice_turn["reply"])
                else:
                    self.state.update(voice_status="cancelled" if stop == "cancelled" else "ready",
                                      voice_message="Voice turn stopped." if stop != "end_turn" else "No spoken reply was returned.")

    def session_update(self, params):
        if not isinstance(params, dict) or not isinstance(params.get("update"), dict):
            return
        sid, update = params.get("sessionId"), params["update"]
        replay = sid == self.replay_session and self.replay_session is not None
        if not replay and sid != self.loaded_session:
            return
        kind = update.get("sessionUpdate")
        messages = self.replay_messages if replay else self.state["messages"]
        tools = self.replay_tools if replay else self.state["tools"]
        if kind in ("agent_message_chunk", "user_message_chunk"):
            content = update.get("content", {})
            if not isinstance(content, dict) or content.get("type") != "text":
                return
            text = clean_text(content.get("text"))
            if not text:
                return
            role = "user" if kind == "user_message_chunk" else "assistant"
            if not replay and role == "assistant" and self.voice_turn:
                self.voice_turn["reply"] = (self.voice_turn["reply"] + text)[:MAX_TEXT]
            # Load replay sends each historical message as a complete chunk. Live
            # assistant deltas concatenate until a tool event or terminal response.
            if not replay and role == "assistant" and self.assistant_open and messages and messages[-1]["role"] == role:
                messages[-1]["content"] = (messages[-1]["content"] + text)[:MAX_TEXT]
            else:
                messages.append({"role": role, "content": text})
            self.assistant_open = role == "assistant" and not replay
            del messages[:-MAX_MESSAGES]
        elif kind in ("tool_call", "tool_call_update"):
            tid = update.get("toolCallId")
            if not valid_id(tid):
                return
            row = next((t for t in tools if t["id"] == tid), None)
            if row is None:
                row = {"id": tid, "title": "Tool", "status": "pending"}
                tools.append(row)
                del tools[:-100]
            if isinstance(update.get("title"), str):
                row["title"] = update["title"][:300]
            if update.get("status") in ("pending", "in_progress", "completed", "failed"):
                row["status"] = update["status"]
            self.assistant_open = False
        elif kind == "session_info_update":
            if isinstance(update.get("title"), str):
                self.remember_session(sid, update["title"])
        elif kind == "plan" and not replay:
            entries = update.get("entries")
            if isinstance(entries, list):
                self.state["tasks"] = {"entries": [
                    {"title": clean_text(e.get("content"), 500), "status": clean_text(e.get("status"), 50)}
                    for e in entries[:50] if isinstance(e, dict)]}
        # Thoughts and unknown notifications are deliberately not displayed as replies.
        if not replay:
            self.persist()

    def reverse_request(self, message):
        rid = message.get("id")
        if not (isinstance(rid, str) and len(rid) <= 128 or type(rid) is int):
            return
        method, params = message.get("method"), message.get("params")
        if method != "session/request_permission":
            self.write({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Client capability not supported"}})
            return
        def cancel():
            self.write({"jsonrpc": "2.0", "id": rid, "result": {"outcome": {"outcome": "cancelled"}}})
        if not isinstance(params, dict) or params.get("sessionId") != self.loaded_session or not self.state["busy"]:
            cancel()
            return
        options = params.get("options")
        if not isinstance(options, list) or not options or len(options) > 20:
            cancel()
            return
        cleaned = []
        for option in options:
            if not isinstance(option, dict) or not valid_id(option.get("optionId")) or any(o["id"] == option["optionId"] for o in cleaned):
                cancel()
                return
            cleaned.append({"id": option["optionId"], "label": clean_text(option.get("name"), 160) or option["optionId"]})
        key = uuid.uuid4().hex
        call = params.get("toolCall", {})
        title = clean_text(call.get("title"), 500) if isinstance(call, dict) else ""
        self.permission_requests[key] = {"rpc_id": rid, "options": cleaned}
        self.state["permissions"].append({"id": key, "title": title or "Hermes requests permission", "options": cleaned})

    def execute_command(self, envelope):
        cid = envelope.get("id", "") if isinstance(envelope, dict) else ""
        if not isinstance(envelope, dict) or not valid_id(cid):
            self.state["error"] = "Ignored a malformed office command."
            return
        if cid in self.seen_ids:
            self.ack(cid, "duplicate", "This command was already received and was not executed again.")
            return
        self.seen_ids.add(cid)
        if len(self.seen_ids) > 10000:
            self.ack(cid, "rejected", "Command limit reached. Close and reopen the office.")
            return
        if not exact_int(envelope.get("protocol_version"), IPC_VERSION) or envelope.get("instance_id") != self.instance_id:
            self.ack(cid, "rejected", "This command belongs to another office connection or protocol version.")
            return
        method, params = envelope.get("method"), envelope.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            self.ack(cid, "rejected", "Invalid command method or parameters.")
            return
        if method == "shutdown":
            self.stop_voice(force=True)
            self.stop_requested = True
            self.ack(cid, "completed")
            return
        if method == "connection.refresh":
            if self.state["busy"]:
                self.ack(cid, "rejected", "Wait for the current turn to finish before reconnecting.")
                return
            self.stop_child()
            self.start_child()
            if self.state["connection"]["status"] == "offline":
                self.ack(cid, "failed", self.state["connection"]["reason"])
                return
            self.ack(cid, "accepted")
            for value in self.pending.values():
                if value["kind"] == "initialize":
                    value["command_id"] = cid
            return
        caps = self.state["connection"]["capabilities"]
        if self.state["connection"]["status"] != "ready" or not caps["chat"]:
            self.ack(cid, "rejected", "Hermes is not connected. Reconnect before sending a command.")
            return
        if method == "permission.reply":
            key, option = params.get("id"), params.get("option_id")
            permission = self.permission_requests.get(key) if isinstance(key, str) else None
            if permission is None or not isinstance(option, str) or option not in [o["id"] for o in permission["options"]]:
                self.ack(cid, "rejected", "Choose an option offered by the pending permission request.")
                return
            if self.write({"jsonrpc": "2.0", "id": permission["rpc_id"], "result": {"outcome": {"outcome": "selected", "optionId": option}}}):
                self.permission_requests.pop(key, None)
                self.state["permissions"] = [p for p in self.state["permissions"] if p["id"] != key]
                self.ack(cid, "completed")
            return
        if method == "turn.cancel":
            if self.voice_context and self.voice_context["action"] in ("record", "speak"):
                self.stop_voice()
                self.state.update(busy=False, voice_status="cancelled", voice_message="Voice stopped.")
                self.voice_turn = None
                self.ack(cid, "cancelled")
                return
            if not self.state["busy"] or not self.loaded_session or not any(p["kind"] == "prompt" for p in self.pending.values()):
                self.ack(cid, "rejected", "There is no running turn to stop.")
                return
            if self.notify("session/cancel", {"sessionId": self.loaded_session}):
                self.voice_turn = None
                if self.state["voice_status"] == "thinking":
                    self.state.update(voice_status="cancelled", voice_message="Stopping the Hermes voice turn.")
                self.ack(cid, "accepted")
            return
        if self.state["busy"]:
            self.ack(cid, "rejected", "A Hermes request is already running. Wait or stop the turn first.")
            return
        if method == "session.new":
            self.state.update(busy=True, error="", tools=[], permissions=[])
            self.ack(cid, "accepted")
            self.request("session/new", {"cwd": str(self.workspace), "mcpServers": []}, "new", cid)
        elif method == "session.select":
            sid = params.get("id")
            row = next((r for r in self.state["sessions"] if r["id"] == sid), None) if valid_id(sid) else None
            if not caps["sessions"] or row is None:
                self.ack(cid, "rejected", "This conversation cannot be loaded by the connected Hermes version.")
                return
            self.state.update(busy=True, error="", permissions=[])
            self.replay_session, self.replay_messages, self.replay_tools = sid, [], []
            self.loaded_session = None
            self.ack(cid, "accepted")
            self.request("session/load", {"sessionId": sid, "cwd": row.get("cwd") or str(self.workspace), "mcpServers": []}, "load", cid)
        elif method == "message.send":
            self.send_message(cid, params)
        elif method == "voice.record":
            if not self.voice_available or not self.loaded_session or self.voice_child is not None:
                self.ack(cid, "rejected", "Voice is unavailable, or no conversation is selected.")
                return
            image_name = params.get("image_name")
            if "image_name" in params:
                try:
                    if not caps["images"]:
                        raise ValueError()
                    self.capture_block(image_name)
                except (OSError, ValueError):
                    self.ack(cid, "rejected", "The selected office capture cannot be shared with this voice turn.")
                    return
            self.state.update(busy=True, error="")
            self.ack(cid, "accepted")
            self.start_voice("record", cid, image_name=image_name)
        else:
            self.ack(cid, "rejected", "Unsupported office command.")

    def send_message(self, cid, params, *, voice=False):
        """Single send path for typed messages and successfully transcribed voice."""
        caps = self.state["connection"]["capabilities"]
        text = params.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_SEND or "\x00" in text:
            self.ack(cid, "rejected", "Enter a message of 1 to 32768 characters.")
            return False
        if self.state["connection"]["status"] != "ready" or not self.loaded_session or self.state["busy"]:
            self.ack(cid, "rejected", "Create or select an idle conversation before sending a message.")
            return False
        blocks = [{"type": "text", "text": text}]
        display_text = text
        if "image_name" in params:
            if not caps["images"]:
                self.ack(cid, "rejected", "The connected Hermes does not support shared images.")
                return False
            try:
                image_block = self.capture_block(params["image_name"])
            except (OSError, ValueError):
                self.ack(cid, "rejected", "Choose a PNG or JPEG capture from this office, up to 4 MB.")
                return False
            blocks.append(image_block)
            display_text += "\n[Shared view: " + params["image_name"] + "]"
        self.state.update(busy=True, error="", tools=[], permissions=[])
        self.assistant_open = False
        self.state["messages"].append({"role": "user", "content": display_text})
        del self.state["messages"][:-MAX_MESSAGES]
        row = next((r for r in self.state["sessions"] if r["id"] == self.loaded_session), None)
        if row and row["title"] == "New conversation":
            row["title"] = text.strip()[:80]
        self.ack(cid, "accepted")
        self.voice_turn = {"command_id": cid, "reply": ""} if voice else None
        if voice:
            self.state.update(voice_status="thinking", voice_message="Hermes is considering what you said.")
        # Durable uncertain marker precedes the write: a crash never replays this send.
        self.uncertain_turn = True
        self.persist()
        self.request("session/prompt", {"sessionId": self.loaded_session, "prompt": blocks}, "prompt", cid)
        return True

    def start_voice(self, action, command_id="", *, text="", image_name=None):
        if not self.voice_command or self.probe or self.voice_child is not None:
            self.state.update(busy=False, voice_status="error", voice_message="Voice helper is unavailable.")
            self.ack(command_id, "failed", self.state["voice_message"])
            return
        self.voice_generation += 1
        generation = self.voice_generation
        work_dir = self.ipc_dir / "voice"
        work_dir.mkdir(exist_ok=True, mode=0o700)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            child = subprocess.Popen(self.voice_command + ["--action", action, "--work-dir", str(work_dir)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     cwd=str(self.workspace), creationflags=flags, start_new_session=os.name != "nt")
        except (OSError, ValueError):
            self.state.update(busy=False, voice_status="error", voice_message="Could not start the configured voice helper.")
            self.ack(command_id, "failed", self.state["voice_message"])
            return
        self.voice_child = child
        self.voice_context = {"action": action, "command_id": command_id, "generation": generation,
                              "started": time.monotonic(), "transcript": None, "image_name": image_name,
                              "session_id": self.loaded_session, "failed": False, "done": False}
        self.state.update(voice_status={"check": "checking", "record": "starting", "speak": "speaking"}[action],
                          voice_message={"check": "Checking local speech dependencies.", "record": "Opening the microphone.",
                                         "speak": "Speaking Hermes' reply."}[action])

        def stdout_reader():
            try:
                while True:
                    line = child.stdout.readline(MAX_COMMAND + 1)
                    if not line:
                        break
                    if len(line) > MAX_COMMAND:
                        self.voice_events.put((generation, "invalid", None))
                        return
                    if line.strip():
                        try:
                            event = json.loads(line.decode("utf-8"))
                            if not isinstance(event, dict):
                                raise ValueError()
                        except (UnicodeError, ValueError):
                            self.voice_events.put((generation, "invalid", None))
                            return
                        self.voice_events.put((generation, "message", event))
                self.voice_events.put((generation, "exit", child.wait()))
            except (OSError, ValueError):
                self.voice_events.put((generation, "invalid", None))
            finally:
                child.stdout.close()

        def stderr_reader():
            try:
                while child.stderr.read(4096):
                    pass
            except (OSError, ValueError):
                pass
            finally:
                child.stderr.close()

        def stdin_writer():
            try:
                if action == "speak":
                    child.stdin.write(text[:MAX_TEXT].encode("utf-8"))
                    child.stdin.flush()
            except (OSError, ValueError):
                self.voice_events.put((generation, "invalid", None))
            finally:
                child.stdin.close()

        for target in (stdout_reader, stderr_reader, stdin_writer):
            threading.Thread(target=target, daemon=True).start()

    @staticmethod
    def terminate_voice_group(child, force=False):
        if child.poll() is not None:
            return
        try:
            if os.name == "nt":
                # Exact owned PID tree; no shell expansion or process-name matching.
                def reap_windows_tree():
                    try:
                        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    except (OSError, subprocess.TimeoutExpired):
                        try:
                            child.kill()
                        except OSError:
                            pass
                threading.Thread(target=reap_windows_tree, daemon=True).start()
            else:
                os.killpg(child.pid, signal.SIGKILL if force else signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                child.kill() if force else child.terminate()
            except OSError:
                pass

    def stop_voice(self, force=False):
        child, self.voice_child = self.voice_child, None
        self.voice_context = None
        self.voice_generation += 1
        if child:
            self.terminate_voice_group(child, force)
            self.voice_retired.append((child, time.monotonic()))
        if force:
            for previous, _ in self.voice_retired:
                self.terminate_voice_group(previous, True)

    def poll_voice(self):
        for child, stopped in self.voice_retired[:]:
            if child.poll() is not None:
                self.voice_retired.remove((child, stopped))
            elif time.monotonic() - stopped > 1:
                self.terminate_voice_group(child, True)
        for _ in range(64):
            try:
                generation, kind, value = self.voice_events.get_nowait()
            except queue.Empty:
                break
            context = self.voice_context
            if generation != self.voice_generation or context is None:
                continue
            action, cid = context["action"], context["command_id"]
            if kind == "message":
                event = value.get("event")
                if event == "status":
                    status = clean_text(value.get("status"), 40)
                    if status in ("checking", "loading", "ready", "recording", "listening", "transcribing", "speaking", "error", "unavailable"):
                        self.state["voice_status"] = status
                    if isinstance(value.get("message"), str):
                        self.state["voice_message"] = clean_text(value["message"], 400)
                    if status in ("error", "unavailable"):
                        context["failed"] = True
                elif event == "transcript" and action == "record":
                    transcript = value.get("text")
                    if context["transcript"] is not None or not isinstance(transcript, str) or not transcript.strip() or len(transcript) > MAX_SEND or "\x00" in transcript:
                        context["failed"] = True
                    else:
                        context["transcript"] = transcript
                elif event == "done":
                    context["done"] = True
                elif event == "error":
                    context["failed"] = True
                    self.state["voice_message"] = clean_text(value.get("message"), 400) or "Voice helper reported an error."
            elif kind == "invalid":
                self.stop_voice()
                if action != "check":
                    self.state["busy"] = False
                self.state.update(voice_status="error", voice_message="Voice helper sent invalid output; nothing was submitted.")
                self.ack(cid, "failed", self.state["voice_message"])
            elif kind == "exit":
                self.voice_child = None
                self.voice_context = None
                success = value == 0 and not context["failed"]
                if action == "check":
                    self.voice_available = success
                    self.state["connection"]["capabilities"]["voice"] = success and self.state["connection"]["status"] == "ready"
                    self.state.update(voice_status="ready" if success else "unavailable",
                                      voice_message="Microphone and speech helper are ready." if success else "Voice dependencies or the cached speech model are unavailable.")
                elif not success:
                    self.state.update(busy=False, voice_status="error")
                    self.state["voice_message"] = "Voice recording failed; nothing was submitted." if action == "record" else "Hermes replied, but speech playback failed. The text is saved."
                    self.ack(cid, "failed", self.state["voice_message"])
                elif action == "record":
                    self.state["busy"] = False
                    transcript = context["transcript"]
                    if not transcript or self.loaded_session != context["session_id"]:
                        self.state.update(voice_status="error", voice_message="No usable speech was captured; nothing was submitted.")
                        self.ack(cid, "failed", self.state["voice_message"])
                        continue
                    params = {"text": transcript}
                    if context["image_name"] is not None:
                        params["image_name"] = context["image_name"]
                    # This synchronous handoff stays within one tick; no other command
                    # can enter between releasing record-busy and claiming ACP-busy.
                    if not self.send_message(cid, params, voice=True):
                        self.state.update(voice_status="error", voice_message="Speech was captured but could not be submitted. Nothing was retried.")
                elif action == "speak":
                    self.state["busy"] = False
                    self.state.update(voice_status="ready" if context["done"] else "error",
                                      voice_message="Ready to listen." if context["done"] else "Speech helper exited without confirming playback.")
                    self.ack(cid, "completed" if context["done"] else "failed", "" if context["done"] else self.state["voice_message"])
        if self.voice_context:
            timeout = 30 if self.voice_context["action"] == "check" else 180
            if time.monotonic() - self.voice_context["started"] > timeout:
                cid = self.voice_context["command_id"]
                checking = self.voice_context["action"] == "check"
                self.stop_voice()
                if not checking:
                    self.state["busy"] = False
                self.state.update(voice_status="error", voice_message="Voice helper timed out and was stopped.")
                self.ack(cid, "failed", self.state["voice_message"])

    def capture_block(self, name):
        """Read only an explicitly named capture; never accept arbitrary IPC paths."""
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,119}\.(png|jpe?g)", name, re.IGNORECASE):
            raise ValueError("Invalid capture name")
        directory = (self.ipc_dir / "captures").resolve()
        path = self.ipc_dir / "captures" / name
        if path.is_symlink() or path.resolve().parent != directory or not path.is_file():
            raise ValueError("Capture outside directory")
        with path.open("rb") as handle:
            raw = handle.read(MAX_IMAGE + 1)
        if not raw or len(raw) > MAX_IMAGE:
            raise ValueError("Capture size invalid")
        suffix = path.suffix.lower()
        if suffix == ".png" and raw.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif suffix in (".jpg", ".jpeg") and raw.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        else:
            raise ValueError("Capture type invalid")
        return {"type": "image", "data": base64.b64encode(raw).decode("ascii"), "mimeType": mime}

    def scan_commands(self):
        for path in sorted((self.ipc_dir / "commands").glob("*.json"))[:20000]:
            if path.name in self.seen_files:
                continue
            self.seen_files.add(path.name)
            try:
                if path.is_symlink() or path.stat().st_size > MAX_COMMAND:
                    raise ValueError("Invalid command file")
                envelope = json.loads(path.read_text(encoding="utf-8"))
                self.execute_command(envelope)
            except (OSError, ValueError, TypeError):
                self.state["error"] = "Ignored an unreadable or malformed office command."
            if self.stop_requested:
                break

    def tick(self):
        self.poll_voice()
        for _ in range(128):
            try:
                generation, kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if generation != self.generation or self.state["connection"]["status"] in ("offline", "incompatible"):
                continue
            if kind == "message":
                self.handle_message(value)
            elif kind == "invalid":
                self.offline("Hermes sent malformed or oversized protocol data.")
                self.stop_child()
            else:
                self.offline("Hermes exited. The conversation is saved locally; reconnect explicitly to continue.")
        if self.state["connection"]["status"] == "starting" and time.monotonic() - self.started_at > 30:
            self.offline("Hermes did not finish connecting within 30 seconds.")
            self.stop_child()
        if not self.probe:
            self.scan_commands()
            self.publish()

    def run(self):
        self.start_child()
        self.publish(force=True)
        try:
            while not self.stop_requested:
                self.tick()
                if self.probe and self.state["connection"]["status"] != "starting":
                    break
                time.sleep(0.02)
        finally:
            self.stop_voice(force=True)
            if not self.probe:
                if self.state["busy"]:
                    self.offline("The office closed during a request. No message will be sent again automatically.")
                else:
                    self.state["connection"] = self.connection("offline", "Office bridge closed.")
                    self.persist()
                self.publish(force=True)
            self.stop_child()
        return {"protocol_version": IPC_VERSION, "connection": self.state["connection"],
                "probe_only": self.probe, "sessions_created": 0 if self.probe else None}


def absolute_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("Use an absolute path.")
    return path


def parse_args(argv=None):
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ipc-dir", type=absolute_path)
    parser.add_argument("--workspace", type=absolute_path, default=base / "workspace")
    parser.add_argument("--data-dir", type=absolute_path, default=base / ".office-data")
    parser.add_argument("--acp-command", default=os.environ.get("HERMES_OFFICE_ACP_COMMAND", '["hermes","acp"]'))
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--receipt", type=absolute_path)
    args = parser.parse_args(argv)
    if not args.probe and args.ipc_dir is None:
        parser.error("--ipc-dir is required unless --probe is used")
    try:
        command = json.loads(args.acp_command)
        if not isinstance(command, list) or not command or not all(isinstance(a, str) and a and "\x00" not in a for a in command):
            raise ValueError()
        args.acp_command = command
    except ValueError:
        parser.error("--acp-command must be a JSON array of nonempty argument strings")
    return args


def main(argv=None):
    args = parse_args(argv)
    bridge = OfficeBridge(args.ipc_dir, args.workspace, args.data_dir, args.acp_command, probe=args.probe)
    try:
        report = bridge.run()
    except KeyboardInterrupt:
        return 130
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(args.receipt, report)
    if args.probe:
        print(json.dumps(report))
        return 0 if report["connection"]["status"] == "ready" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
