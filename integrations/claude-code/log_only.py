#!/usr/bin/env python3
"""Observability-only Claude Code hook: log every event, touch nothing.

Wire this script to *every* hook event (see settings.logging.example.json) to
capture a complete, time-ordered trace of what Claude Code emits — independent
of, and alongside, the device hook (hook.py). It exists to compare the ordering
of terminal events against what the buddy actually did, e.g. when chasing the
missing-prompt-beep race.

Contract, mirroring hook.py:
  * stdlib only — never imports buddy_bridge/pyserial, so it can NEVER open the
    serial port or reset the device. It only ever appends a line to a file.
  * Writes to $BUDDY_LOG (the same file hook.py logs to) so the two streams
    interleave into a single timeline. If $BUDDY_LOG is unset it's a no-op.
  * Never raises into the session: every path exits 0, output only to the log.
  * Dumps the FULL raw payload (truncated for sanity) rather than a hand-picked
    field list, so an event that carries more than the docs claim — or an event
    we didn't know about — is still captured verbatim.

There is no wildcard event name in settings.json, so "log all events" means
this one script enrolled under each event name. Events Claude Code adds in
future won't be captured until added there — but whatever names ARE registered
are logged in full, including their complete payload.

Noise control: high-frequency events (e.g. MessageDisplay, which can fire many
times per response) can bury the events you care about. Set BUDDY_LOG_EXCLUDE to
a comma-separated list of event names to drop them, e.g.:

    export BUDDY_LOG_EXCLUDE=MessageDisplay,FileChanged
"""

import json
import os
import sys
import time

# Keep each log line bounded; tool_input for a big Write/Edit can be huge and
# we don't want to swamp the trace. The salient ordering info is small.
_RAW_MAX = 600


def _excluded():
    raw = os.environ.get("BUDDY_LOG_EXCLUDE", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def main():
    path = os.environ.get("BUDDY_LOG")
    if not path:
        return  # logging off by default — same contract as hook.py

    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass

    data = {}
    parsed_ok = False
    try:
        if raw.strip():
            data = json.loads(raw)
            parsed_ok = True
    except Exception:
        data = {}  # malformed: fall back to the raw text below, never drop it

    event = data.get("hook_event_name") or "?"
    if event.lower() in _excluded():
        return

    # A couple of fields pulled to the front for quick scanning; the full raw
    # payload follows so nothing is lost (matcher type, message, ids, etc.).
    bits = []
    for k in ("tool_name", "message", "notification_type", "source", "matcher"):
        v = data.get(k)
        if v:
            bits.append("%s=%s" % (k, str(v)[:40]))
    summary = " ".join(bits)

    # Re-serialize when we parsed cleanly; otherwise keep the original bytes so
    # malformed/unexpected payloads are preserved rather than silently dropped.
    compact = raw.strip()
    if parsed_ok:
        try:
            compact = json.dumps(data, separators=(",", ":"))
        except Exception:
            compact = raw.strip()
    if len(compact) > _RAW_MAX:
        compact = compact[:_RAW_MAX] + "…"

    try:
        now = time.time()
        ts = time.strftime("%H:%M:%S", time.localtime(now)) + (".%03d" % (int(now * 1000) % 1000))
        detail = (summary + " | " if summary else "") + "raw=" + compact
        line = "%s pid=%-7d %-18s %s\n" % (ts, os.getpid(), "EVT:" + event, detail)
        with open(path, "a") as f:
            f.write(line)
    except Exception:
        pass  # never surface an error into the session


if __name__ == "__main__":
    main()
