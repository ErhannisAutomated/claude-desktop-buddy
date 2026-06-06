#!/usr/bin/env python3
"""Collapse a $BUDDY_LOG trace into per-prompt timelines and flag suspects.

Reads the merged log written by hook.py / log_only.py / the device acks (see
README "Debug logging") and reconstructs, for each on-device permission prompt:
  * when it was shown (permission.show) and resolved (permission.result)
  * the host-side lock delay (gap from the hook firing to the port write)
  * any CLOBBER: a prompt-less snapshot sent by another hook while this prompt
    was still up — the device clears its dialog on any snapshot without a
    "prompt" key, so an interleaved "waiting"/"thinking"/etc. wipes it
  * if debug-firmware "dev" acks are present: whether the device acked receipt
    (state), failed to parse (parse), and actually chirped (beep)

Usage:  python3 triage.py [logfile]        (default: $BUDDY_LOG)
        python3 triage.py --timeline [log] (also dump the full merged timeline)

Read-only; never touches the device.
"""

import json
import os
import re
import sys

# Snapshot msgs that carry no "prompt" key and therefore CLEAR the device
# dialog. (Informational — detection is by the actual absence of "prompt".)
_NOPROMPT_HINT = ("thinking", "waiting", "working", "done", "bye", "ready")


def _parse_ts(s):
    # "HH:MM:SS.mmm" -> milliseconds since midnight (for diffs only)
    m = re.match(r"(\d\d):(\d\d):(\d\d)\.(\d+)", s)
    if not m:
        return None
    h, mi, se, ms = (int(x) for x in m.groups())
    return ((h * 60 + mi) * 60 + se) * 1000 + ms


def _load(path):
    rows = []
    with open(path) as f:
        for ln in f:
            ln = ln.rstrip("\n")
            m = re.match(r"(\S+)\s+pid=(\d+)\s+(\S+)\s*(.*)", ln)
            if not m:
                continue
            ts, pid, event, detail = m.group(1), int(m.group(2)), m.group(3), m.group(4)
            rows.append({"ts": ts, "ms": _parse_ts(ts), "pid": pid,
                         "event": event, "detail": detail, "raw": ln})
    return rows


def _send_json(detail):
    """The JSON object a `send` line carries (or None)."""
    try:
        return json.loads(detail)
    except Exception:
        return None


def _dev_json(detail):
    try:
        obj = json.loads(detail)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def main():
    args = [a for a in sys.argv[1:]]
    show_timeline = "--timeline" in args
    args = [a for a in args if a != "--timeline"]
    path = args[0] if args else os.environ.get("BUDDY_LOG")
    if not path:
        print("no logfile: pass a path or set $BUDDY_LOG", file=sys.stderr)
        return 2
    if not os.path.exists(path):
        print("no such file: %s" % path, file=sys.stderr)
        return 2

    rows = _load(path)
    has_dev = any(r["event"] == "dev" for r in rows)

    # First send/permission.show per pid, to measure lock/port delay against the
    # pid's `hook` line.
    hook_at = {}        # pid -> ms of its "hook" dispatch line
    first_io_at = {}    # pid -> ms of its first send/permission.show
    for r in rows:
        if r["event"] == "hook" and r["pid"] not in hook_at:
            hook_at[r["pid"]] = r["ms"]
        if r["event"] in ("send", "permission.show") and r["pid"] not in first_io_at:
            first_io_at[r["pid"]] = r["ms"]

    # Walk the timeline tracking the set of prompts currently "up" on the device.
    incidents = {}      # prompt_id -> record
    active = {}         # prompt_id -> incident (currently shown, unresolved)

    for r in rows:
        ev, detail, pid, ms, ts = r["event"], r["detail"], r["pid"], r["ms"], r["ts"]

        if ev == "permission.show":
            m = re.search(r"id=(\S+)", detail)
            pid_id = m.group(1) if m else "?"
            inc = {"id": pid_id, "pid": pid, "shown_ts": ts, "shown_ms": ms,
                   "result": None, "result_ts": None, "clobbers": [],
                   "dev_state": False, "dev_beep": False, "cleared_by_dev": False}
            delay = None
            if pid in hook_at and ms is not None:
                delay = ms - hook_at[pid]
            inc["lock_delay_ms"] = delay
            incidents[pid_id] = inc
            active[pid_id] = inc

        elif ev == "permission.result":
            m = re.search(r"id=(\S+)\s*->\s*(\S+)", detail)
            if m:
                pid_id, decision = m.group(1), m.group(2)
                inc = incidents.get(pid_id)
                if inc:
                    inc["result"] = decision
                    inc["result_ts"] = ts
                active.pop(pid_id, None)

        elif ev == "send":
            obj = _send_json(detail)
            has_prompt = bool(obj and "prompt" in obj)
            if not has_prompt and active:
                # A prompt-less snapshot from any pid clears the device dialog
                # for whatever prompt(s) are currently up — unless it's the
                # owning pid's own post-result clear (already resolved/removed).
                for inc in list(active.values()):
                    if pid != inc["pid"]:
                        msg = (obj or {}).get("msg", "?")
                        inc["clobbers"].append({"ts": ts, "pid": pid, "msg": msg})

        elif ev == "dev":
            obj = _dev_json(detail)
            if not obj:
                continue
            kind = obj.get("ack")
            if kind == "beep" and obj.get("prompt") in incidents:
                incidents[obj["prompt"]]["dev_beep"] = True
            elif kind == "state":
                pr = obj.get("prompt") or ""
                if pr and pr in incidents:
                    incidents[pr]["dev_state"] = True
                elif pr == "":
                    for inc in active.values():
                        inc["cleared_by_dev"] = True

    # ---- report ---------------------------------------------------------
    print("log: %s   (%d lines)" % (path, len(rows)))
    print("device acks present: %s" % ("yes" if has_dev
          else "NO  (debug firmware not flashed — receive/beep layer blank)"))
    print()

    order = sorted(incidents.values(), key=lambda i: i["shown_ms"] or 0)
    print("PROMPTS SHOWN ON DEVICE: %d" % len(order))
    suspects = []
    for inc in order:
        flags = []
        if inc["clobbers"]:
            flags.append("CLOBBERED x%d" % len(inc["clobbers"]))
        if inc["lock_delay_ms"] and inc["lock_delay_ms"] >= 1000:
            flags.append("lock-delay %.1fs" % (inc["lock_delay_ms"] / 1000.0))
        if has_dev and not inc["dev_state"]:
            flags.append("NO-RECEIVE")
        if has_dev and inc["dev_state"] and not inc["dev_beep"]:
            flags.append("RECEIVED-NO-BEEP")
        if inc["cleared_by_dev"]:
            flags.append("device-cleared")
        tag = ("  <<< " + ", ".join(flags)) if flags else ""
        if flags:
            suspects.append(inc)
        print("  %s  id=%-16s pid=%-6d result=%-5s%s"
              % (inc["shown_ts"], inc["id"], inc["pid"],
                 inc["result"] or "—", tag))

    if suspects:
        print("\nSUSPECT DETAIL")
        for inc in suspects:
            print("  id=%s (shown %s, result=%s)"
                  % (inc["id"], inc["shown_ts"], inc["result"] or "—"))
            if inc["lock_delay_ms"] is not None:
                print("    lock/port delay: %d ms" % inc["lock_delay_ms"])
            for c in inc["clobbers"]:
                print("    CLOBBER  %s  pid=%-6d  prompt-less snapshot msg=%r"
                      % (c["ts"], c["pid"], c["msg"]))

    if show_timeline:
        print("\nMERGED TIMELINE")
        for r in rows:
            d = r["detail"]
            if len(d) > 100:
                d = d[:100] + "…"
            print("  %s pid=%-6d %-20s %s" % (r["ts"], r["pid"], r["event"], d))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
