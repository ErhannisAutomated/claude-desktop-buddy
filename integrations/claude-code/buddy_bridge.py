"""Talk to a claude-desktop-buddy device over USB serial.

The firmware speaks the same newline-delimited JSON over USB serial that it
speaks over BLE (see REFERENCE.md): the host writes heartbeat snapshots, and
the device echoes permission decisions back out the same port. This module is
the thin client the Claude Code hooks use to do that.

Design notes for the stateless hook model:
  * Each hook invocation opens the port, does its thing, and closes it. A file
    lock serialises concurrent hooks so their writes don't interleave.
  * Opening a USB-UART normally pulses DTR/RTS, which auto-resets the ESP32.
    We force both low before opening so the device keeps running across the
    many short-lived hook processes.
  * Nothing here may raise into Claude Code. Callers treat a missing/!asleep
    device as "no decision" and let the terminal handle it. open_port() returns
    None rather than throwing when there's no device.
"""

import glob
import json
import os
import sys
import time

try:
    import serial  # pyserial
    from serial.tools import list_ports
except Exception:  # pragma: no cover - pyserial not installed
    serial = None
    list_ports = None

BAUD = 115200

# USB-UART bridges commonly found on these boards (VID, PID).
_KNOWN_VID_PID = {
    (0x10C4, 0xEA60),  # CP210x (WT32-SC01 Plus)
    (0x1A86, 0x7523),  # CH340
    (0x1A86, 0x55D4),  # CH9102
    (0x0403, 0x6001),  # FTDI
    (0x303A, 0x1001),  # Espressif native USB CDC (ESP32-S3)
}


def find_port():
    """Best-effort autodetect, overridable with $BUDDY_PORT."""
    env = os.environ.get("BUDDY_PORT")
    if env:
        return env
    if list_ports is not None:
        for p in list_ports.comports():
            if (p.vid, p.pid) in _KNOWN_VID_PID:
                return p.device
        # Fall back to anything that smells like a USB serial adapter.
        for p in list_ports.comports():
            desc = (p.description or "").lower()
            if any(k in desc for k in ("cp210", "ch340", "ch910", "usb", "uart", "acm")):
                return p.device
    # Last resort: a raw device glob (Linux/macOS).
    for pat in ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.usbserial*", "/dev/cu.usbmodem*"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


def open_port(port=None):
    """Open the device without resetting it. Returns a Serial or None."""
    if serial is None:
        return None
    port = port or find_port()
    if not port:
        return None
    try:
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = BAUD
        ser.timeout = 0.2          # short read timeout; we poll in a loop
        ser.dtr = False            # hold reset lines low so the ESP32 keeps
        ser.rts = False            # running across repeated hook opens
        ser.open()
        return ser
    except Exception:
        return None


def send(ser, obj):
    """Write one JSON line. Swallows errors (device may have vanished)."""
    if ser is None:
        return False
    try:
        ser.write((json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8"))
        ser.flush()
        return True
    except Exception:
        return False


def await_decision(ser, req_id, timeout_s):
    """Block until the device echoes a permission decision for req_id.

    Returns "once", "deny", or None on timeout. The device prints non-JSON
    debug lines too, so we only parse lines that start with '{'.
    """
    if ser is None:
        return None
    deadline = time.monotonic() + timeout_s
    buf = b""
    while time.monotonic() < deadline:
        try:
            chunk = ser.read(256)
        except Exception:
            return None
        if chunk:
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"{"):
                    continue
                try:
                    msg = json.loads(line.decode("utf-8", "replace"))
                except Exception:
                    continue
                if msg.get("cmd") == "permission" and msg.get("id") == req_id:
                    return msg.get("decision")
    return None


# --- file lock so concurrent hooks don't garble the serial stream -----------

def _lock_path():
    base = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    return os.path.join(base, "claude-buddy.lock")


class portlock:
    """Context manager: best-effort exclusive lock. Never blocks forever."""

    def __init__(self, timeout_s=5.0):
        self.timeout_s = timeout_s
        self._fd = None

    def __enter__(self):
        try:
            import fcntl
            self._fd = open(_lock_path(), "w")
            deadline = time.monotonic() + self.timeout_s
            while True:
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        break  # give up, proceed unlocked rather than hang
                    time.sleep(0.05)
        except Exception:
            self._fd = None
        return self

    def __exit__(self, *exc):
        if self._fd is not None:
            try:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                self._fd.close()
            except Exception:
                pass
        return False


# --- snapshot helpers -------------------------------------------------------

def time_sync_obj():
    """{"time":[epoch, tz_offset_sec]} so the device clock is correct."""
    lt = time.localtime()
    off = lt.tm_gmtoff if lt.tm_gmtoff is not None else 0
    return {"time": [int(time.time()), int(off)]}


def hint_for(tool_name, tool_input):
    """A short, human-readable summary of a tool call for the device."""
    ti = tool_input or {}
    if tool_name == "Bash":
        return (ti.get("command") or "").strip()
    for k in ("file_path", "path", "url", "pattern", "command", "notebook_path"):
        if ti.get(k):
            return str(ti[k])
    return tool_name
