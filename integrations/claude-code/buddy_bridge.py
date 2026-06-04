"""Talk to a claude-desktop-buddy device over USB serial.

The firmware speaks the same newline-delimited JSON over USB serial that it
speaks over BLE (see REFERENCE.md): the host writes heartbeat snapshots, and
the device echoes permission decisions back out the same port. This module is
the thin client the Claude Code hooks use to do that.

Design notes for the stateless hook model:
  * Each hook invocation opens the port, does its thing, and closes it. A file
    lock serialises concurrent hooks so their writes don't interleave.
  * On the ESP32-S3's native USB-Serial/JTAG, a DTR/RTS transition IS the
    reset signal (it's how esptool reboots into the bootloader). pyserial's
    Serial.open() drives those lines, AND any tcsetattr() makes the cdc_acm
    driver toggle DTR -- either reboots the device on every hook. So we do raw
    file-descriptor I/O with no termios changes, exactly like `echo > port`,
    which never touches the modem lines. pyserial is still used (when present)
    only for port autodetection, never for the actual I/O.
  * Nothing here may raise into Claude Code. Callers treat a missing/!asleep
    device as "no decision" and let the terminal handle it. open_port() returns
    None rather than throwing when there's no device.
"""

import glob
import json
import os
import select
import sys
import time

try:
    import termios  # POSIX raw-fd serial config (Linux/macOS)
except Exception:  # pragma: no cover - non-POSIX
    termios = None

try:
    import serial  # pyserial — used only for port autodetection
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


class _RawPort:
    """Minimal serial wrapper over a raw fd (write/flush/read/close).

    Deliberately bypasses pyserial so opening never touches DTR/RTS, which on
    the USB-Serial/JTAG would reset the chip. Mirrors the pyserial method names
    the rest of this module already uses.
    """

    def __init__(self, fd):
        self.fd = fd

    def write(self, data):
        total = 0
        while total < len(data):
            try:
                n = os.write(self.fd, data[total:])
            except BlockingIOError:
                n = 0
            except OSError:
                break
            total += n
        return total

    def flush(self):
        try:
            termios.tcdrain(self.fd)
        except Exception:
            pass

    def read(self, n):
        r, _, _ = select.select([self.fd], [], [], 0.2)  # short poll
        if not r:
            return b""
        try:
            return os.read(self.fd, n)
        except (BlockingIOError, OSError):
            return b""

    def close(self):
        try:
            os.close(self.fd)
        except Exception:
            pass


def open_port(port=None):
    """Open the device without resetting it. Returns a _RawPort or None.

    Crucially we do NOT call tcsetattr(): changing termios makes the cdc_acm
    driver toggle DTR, which on the USB-Serial/JTAG reboots the chip. The
    default line settings are fine for raw byte I/O over USB CDC (baud/parity
    are meaningless there). This mirrors `echo > /dev/ttyACM0`, which doesn't
    reset. O_NONBLOCK keeps open() from blocking on carrier-detect.
    """
    port = port or find_port()
    if not port:
        return None
    try:
        fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    except Exception:
        return None
    return _RawPort(fd)


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


# --- diagnostics ------------------------------------------------------------

def probe():
    """Print why the bridge can or can't reach the device. Run directly:

        python3 buddy_bridge.py

    The hooks deliberately fail silently so they never disrupt a session, which
    makes "nothing happened" hard to debug. This surfaces the real reason.
    """
    import errno

    print("pyserial:", "ok" if serial is not None else "MISSING (pip install pyserial)")
    if serial is None:
        return 1

    env = os.environ.get("BUDDY_PORT")
    print("BUDDY_PORT:", env or "(unset, autodetecting)")
    if list_ports is not None:
        ports = list(list_ports.comports())
        print("ports seen:", len(ports))
        for p in ports:
            print("  %s  VID:PID=%04X:%04X  %s"
                  % (p.device, p.vid or 0, p.pid or 0, p.description))

    port = find_port()
    print("chosen port:", port or "NONE FOUND")
    if not port:
        print("=> No device port. Plug in over USB, or set BUDDY_PORT.")
        return 1

    # Permission check before opening.
    try:
        st = os.stat(port)
        print("perms: %s  (you are uid=%d, groups=%s)"
              % (oct(st.st_mode & 0o777), os.getuid(), os.getgroups()))
    except Exception as e:
        print("stat failed:", e)

    # Raw open (same path the hooks use) so the probe doesn't reset the chip.
    try:
        fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    except OSError as e:
        msg = str(e)
        if e.errno == errno.EACCES:
            msg += "  => permission denied; add yourself to the 'dialout' group: " \
                   "sudo usermod -aG dialout $USER  (then log out/in)"
        print("open FAILED:", msg)
        return 1
    ser = _RawPort(fd)
    print("opened:", port)

    # Ask the firmware for a status ack — proves bidirectional USB serial.
    send(ser, {"cmd": "status"})
    print("sent {\"cmd\":\"status\"}; listening 3s for any JSON reply...")
    import time as _t
    deadline = _t.monotonic() + 3.0
    buf = b""
    got = False
    while _t.monotonic() < deadline:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line:
                    got = True
                    print("  <-", line.decode("utf-8", "replace")[:120])
    ser.close()
    if not got:
        print("=> Port opened but the device sent nothing. Most likely the "
              "firmware's Serial isn't on USB: rebuild/flash with "
              "ARDUINO_USB_CDC_ON_BOOT=1 (see platformio.ini).")
        return 1
    print("=> Bridge looks healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(probe())
