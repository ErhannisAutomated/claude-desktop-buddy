#!/usr/bin/env python3
"""Single Claude Code hook entry point for the claude-desktop-buddy device.

Wire this one script to several hook events in settings.json; it dispatches on
`hook_event_name` from the stdin payload. It maps Claude Code's lifecycle onto
the device's JSON wire protocol (see ../../REFERENCE.md):

  PermissionRequest -> show an approve/deny prompt on the device and block for
                       the A/B button; return the decision to Claude Code. If
                       the device is absent or the user doesn't answer in time,
                       emit nothing so Claude falls back to the terminal prompt.
  UserPromptSubmit  -> "busy" (a session is running)
  PreToolUse        -> transcript ticker entry
  Notification      -> idle/attention
  Stop              -> "completed" (plays the device fanfare)
  SessionStart      -> wake + time sync (+ owner name if known)
  SessionEnd        -> "sleep"

Hard rule: never break the user's session. Any failure -> exit 0 with no
decision output, so Claude Code proceeds exactly as if the hook weren't there.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buddy_bridge as bb

# Seconds to wait for a button press before falling back to the terminal.
# Keep this below the hook's `timeout` in settings.json.
DECISION_TIMEOUT_S = float(os.environ.get("BUDDY_DECISION_TIMEOUT", "30"))


def _emit(obj):
    """Print a hook JSON result on stdout (the only thing Claude Code reads)."""
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def _send_snapshot(extra):
    """Open the port, push one heartbeat snapshot, close. Best effort."""
    with bb.portlock():
        ser = bb.open_port()
        if ser is None:
            bb.log("send", "NO DEVICE " + json.dumps(extra))
            return
        try:
            bb.send(ser, extra)  # logs the wire line itself (tag "send")
            bb.read_acks(ser, bb.ack_read_window())  # debug firmware only; no-op otherwise
        finally:
            ser.close()


def handle_permission_request(data):
    tool = data.get("tool_name", "tool")
    hint = bb.hint_for(tool, data.get("tool_input"))
    req_id = "cc_%d_%d" % (os.getpid(), int(time.time() * 1000) % 100000)

    with bb.portlock():
        ser = bb.open_port()
        if ser is None:
            bb.log("permission", "NO DEVICE tool=%s" % tool)
            return  # no device -> terminal handles it (emit nothing)
        try:
            bb.send(ser, {
                "total": 1, "running": 1, "waiting": 1,
                "msg": ("approve: " + tool)[:23],
                "prompt": {"id": req_id, "tool": tool[:20], "hint": hint[:44]},
            })
            bb.log("permission.show", "id=%s tool=%s" % (req_id, tool))
            decision = bb.await_decision(ser, req_id, DECISION_TIMEOUT_S)
            bb.log("permission.result", "id=%s -> %s" % (req_id, decision))
            # Clear the prompt either way so the device leaves the alert state.
            bb.send(ser, {"total": 1, "running": 1, "waiting": 0,
                          "msg": "working"})
            bb.read_acks(ser, bb.ack_read_window())  # capture the clear's ack too
        finally:
            ser.close()

    if decision == "once":
        _emit({"hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"}}})
    elif decision == "deny":
        _emit({"hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny"}}})
    # decision is None (timeout / device asleep): emit nothing -> Claude Code
    # shows its normal terminal prompt.


def handle_session_start(data):
    owner = os.environ.get("BUDDY_OWNER")
    with bb.portlock():
        ser = bb.open_port()
        if ser is None:
            return
        try:
            bb.send(ser, bb.time_sync_obj())
            if owner:
                bb.send(ser, {"cmd": "owner", "name": owner})
            bb.send(ser, {"total": 1, "running": 0, "waiting": 0, "msg": "ready"})
        finally:
            ser.close()


def handle_user_prompt_submit(data):
    _send_snapshot({"total": 1, "running": 1, "waiting": 0, "msg": "thinking"})


def handle_pre_tool_use(data):
    tool = data.get("tool_name", "tool")
    hint = bb.hint_for(tool, data.get("tool_input"))
    stamp = time.strftime("%H:%M")
    entry = ("%s %s" % (stamp, hint))[:90]
    _send_snapshot({"total": 1, "running": 1, "waiting": 0,
                    "msg": ("run: " + tool)[:23], "entries": [entry]})


def handle_notification(data):
    # permission_prompt is handled by PermissionRequest; here we cover the
    # "Claude is waiting on you" idle case as an attention nudge.
    _send_snapshot({"total": 1, "running": 0, "waiting": 1, "msg": "waiting"})


def handle_stop(data):
    _send_snapshot({"total": 1, "running": 0, "waiting": 0,
                    "completed": True, "msg": "done"})


def handle_session_end(data):
    _send_snapshot({"total": 0, "running": 0, "waiting": 0, "msg": "bye"})


_HANDLERS = {
    "PermissionRequest": handle_permission_request,
    "SessionStart": handle_session_start,
    "UserPromptSubmit": handle_user_prompt_submit,
    "PreToolUse": handle_pre_tool_use,
    "Notification": handle_notification,
    "Stop": handle_stop,
    "SessionEnd": handle_session_end,
}


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return  # malformed input: do nothing, exit 0
    event = data.get("hook_event_name")
    bb.log("hook", "%s tool=%s" % (event, data.get("tool_name", "")))
    handler = _HANDLERS.get(event)
    if handler is None:
        return
    try:
        handler(data)
    except Exception:
        # Last-ditch guard: never surface an error into the session.
        return


if __name__ == "__main__":
    main()
