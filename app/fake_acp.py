#!/usr/bin/env python3
"""Deterministic offline ACP fixture for test_office_bridge.py; never runs Hermes."""
import argparse
import json
import os
import sys


def emit(value):
    print(json.dumps(value), flush=True)


def reply(rid, result):
    emit({"jsonrpc": "2.0", "id": rid, "result": result})


def update(sid, kind, **values):
    emit({"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": sid, "update": {"sessionUpdate": kind, **values}}})


def text(sid, role, value):
    if role == "assistant":
        role = "agent"
    update(sid, role + "_message_chunk", content={"type": "text", "text": value})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="normal")
    parser.add_argument("--log")
    args = parser.parse_args()
    pending = None
    print("secret-do-not-publish-test-marker", file=sys.stderr, flush=True)
    for line in sys.stdin:
        message = json.loads(line)
        if args.log:
            with open(args.log, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(message) + "\n")
        method = message.get("method")
        params = message.get("params", {})
        rid = message.get("id")
        if method == "initialize":
            if args.scenario == "malformed":
                print("this is not JSON", flush=True)
                continue
            caps = {"loadSession": True, "sessionCapabilities": {"list": {}, "future": {}},
                    "promptCapabilities": {"image": True}}
            if args.scenario == "missing-caps":
                caps = {}
            result = {"protocolVersion": 2 if args.scenario == "protocol2" else 1,
                      "agentInfo": {"name": "fake-hermes", "version": "test-1"},
                      "agentCapabilities": caps, "newOptionalField": {"ignored": True}}
            reply(rid, result)
            emit({"jsonrpc": "2.0", "method": "future/notification", "params": {"unknown": True}})
        elif method == "session/list":
            reply(rid, {"sessions": [{"sessionId": "saved-session", "title": "Saved conversation",
                                     "cwd": os.getcwd(), "extra": 7}], "nextCursor": None})
        elif method == "session/new":
            reply(rid, {"sessionId": "new-session", "modes": {"currentModeId": "default"}})
        elif method == "session/load":
            sid = params["sessionId"]
            text(sid, "user", "Earlier question")
            text(sid, "assistant", "Earlier answer")
            update(sid, "tool_call", toolCallId="old-tool", title="Read prior file", status="pending")
            update(sid, "tool_call_update", toolCallId="old-tool", status="completed")
            reply(rid, {})
        elif method == "session/prompt":
            sid = params["sessionId"]
            if args.scenario == "crash":
                text(sid, "assistant", "Partial answer")
                os._exit(17)
            elif args.scenario in ("permission", "cancel"):
                pending = (rid, sid)
                if args.scenario == "permission":
                    emit({"jsonrpc": "2.0", "id": "permission-1", "method": "session/request_permission",
                          "params": {"sessionId": sid, "toolCall": {"toolCallId": "test-tool", "title": "Write a test file"},
                                     "options": [{"optionId": "allow_once", "kind": "allow_once", "name": "Allow once"},
                                                 {"optionId": "deny", "kind": "reject_once", "name": "Deny"}]}})
            else:
                update(sid, "tool_call", toolCallId="tool-1", title="Read workspace", status="in_progress", future=1)
                update(sid, "tool_call_update", toolCallId="tool-1", status="completed")
                update(sid, "new_future_event", content={"type": "text", "text": "Not a reply"})
                text(sid, "assistant", "Hello ")
                text(sid, "assistant", "office")
                reply(rid, {"stopReason": "end_turn"})
        elif method == "session/cancel" and pending:
            reply(pending[0], {"stopReason": "cancelled"})
            pending = None
        elif rid == "permission-1" and pending:
            selected = message.get("result", {}).get("outcome", {})
            text(pending[1], "assistant", "Permission choice: " + selected.get("optionId", "cancelled"))
            reply(pending[0], {"stopReason": "end_turn"})
            pending = None
        elif method:
            emit({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Unknown method"}})


if __name__ == "__main__":
    main()
