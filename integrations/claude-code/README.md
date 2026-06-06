# Claude Code → desktop buddy (USB serial)

Drive the buddy device from **Claude Code** (the CLI), not just the desktop app.

The firmware already speaks its JSON wire protocol over USB serial as well as
BLE, so no firmware change is needed — this is a set of Claude Code **hooks**
that translate the session lifecycle into device messages over the USB cable.

The headline feature: when Claude Code needs permission for a tool call, the
prompt appears **on the device** and you approve/deny with the A/B touch
buttons. If the device is asleep or unplugged, Claude falls back to the normal
terminal prompt — so the hooks are safe to leave on.

## What maps to what

| Claude Code event | Device effect |
|---|---|
| `PermissionRequest` | approve/deny prompt on the device (blocks for A/B, with fallback) |
| `UserPromptSubmit` | busy / "thinking" |
| `PreToolUse` | transcript ticker entry |
| `Notification` (idle) | attention / "waiting" |
| `Stop` | "completed" → plays the fanfare |
| `SessionStart` | wake + clock sync (+ owner name) |
| `SessionEnd` | sleep |

## Prerequisites (read this first)

On the WT32-SC01 Plus the USB-C port is the ESP32-S3's **native USB** (it shows
up as `/dev/ttyACM*`, "USB JTAG/serial debug unit"). Two things must be true or
the bridge silently does nothing:

1. **Firmware built with `ARDUINO_USB_CDC_ON_BOOT=1`.** Without it the firmware's
   `Serial` stays on UART0 (GPIO43/44), which is *not* the USB cable, so nothing
   gets through. This repo's `platformio.ini` now sets the flag — reflash after
   pulling: `pio run -t upload`.

2. **Permission to open the port.** `/dev/ttyACM0` is `root:dialout`. Add
   yourself to the group (once), then log out and back in:

   ```bash
   sudo usermod -aG dialout $USER
   ```

When something isn't working, run the **probe** — it reports exactly what's
wrong (no pyserial, no port, permission denied, or firmware not on USB):

```bash
python3 buddy_bridge.py
```

## Setup

1. **Install pyserial** (the only dependency):

   ```bash
   pip install pyserial
   ```

2. **Plug the device in over USB** and find its port:

   ```bash
   python3 -m serial.tools.list_ports -v
   ```

   The bridge autodetects common USB-UART chips (CP210x/CH340/FTDI/ESP32-S3).
   If autodetect picks the wrong port, set `BUDDY_PORT`:

   ```bash
   export BUDDY_PORT=/dev/ttyUSB0      # or /dev/cu.usbserial-XXXX on macOS
   ```

3. **Wire up the hooks.** Copy the blocks from `settings.example.json` into your
   Claude Code settings — `~/.claude/settings.json` for every project, or a
   project's `.claude/settings.json` — and replace `ABSOLUTE_PATH` with the path
   to this repo. All events point at the same `hook.py`.

4. **(Optional) personalise:**

   ```bash
   export BUDDY_OWNER="Ada"             # device greets you by name
   export BUDDY_DECISION_TIMEOUT=30     # seconds to wait for an A/B press
   ```

## Debug logging

Set `BUDDY_LOG` to a file path and every hook invocation appends a timestamped,
pid-tagged line recording which event fired and what it sent to the device:

```bash
export BUDDY_LOG=/tmp/buddy-hooks.log
tail -f /tmp/buddy-hooks.log
```

Because each hook is a separate process, the pids and millisecond timestamps
make it possible to see the *ordering* of concurrent hooks — useful for chasing
cases where one hook's snapshot appears to overwrite another's. Unset the
variable to turn it off (the default).

### Trace *every* event (`log_only.py`)

To see the full picture — every event Claude Code emits, in order, regardless of
whether `hook.py` acts on it — enable the observability-only logger. It writes to
the **same** `$BUDDY_LOG` file, so terminal events and device actions interleave
into one timeline.

`log_only.py` is stdlib-only and never opens the serial port (it can't touch or
reset the device); it only ever appends a line. To enable it, merge
`settings.logging.example.json` into your settings *alongside* the normal
`settings.example.json` (replace `ABSOLUTE_PATH`, set `$BUDDY_LOG`). It registers
the logger under all ~29 documented hook events and dumps each event's full raw
payload, so an event that carries more fields than documented — or one we forgot
about — is still captured verbatim.

A few events are chatty (e.g. `MessageDisplay` can fire many times per response).
Mute them without losing the rest:

```bash
export BUDDY_LOG_EXCLUDE=MessageDisplay,FileChanged
```

In the merged log, lines from the logger are tagged `EVT:<EventName>` (the raw
terminal event), while `hook.py`'s own lines use lowercase verbs (`hook`,
`send`, `permission.show`, `permission.result`) — so you can tell at a glance
what the terminal emitted versus what the device was told to do.

### Device-side acks (what the device actually received and did)

The logs above prove what the *host sent*. They can't tell whether the device
received a line, parsed it, or chose to chirp — so a missing notification could
be a dropped serial line *or* the firmware not beeping, and you can't tell which.
Debug firmware closes that gap.

Build and flash the **debug** firmware env, which echoes a JSON ack out USB
serial at the points that matter (off in normal builds; see `src/dbg.h`):

```bash
pio run -e wt32-sc01-plus-debug -t upload
```

It emits:

| Ack | When | Means |
|---|---|---|
| `{"ack":"state",...}` | every snapshot it parses & applies | the device **received** it (includes the resulting `prompt` id and counts) |
| `{"ack":"parse","ok":false}` | a line it couldn't parse | the line arrived **garbled/partial** and was dropped |
| `{"ack":"beep","kind":"prompt",...}` | the prompt chirp fires | the device actually **beeped** |

Then tell the host to listen for them after each send:

```bash
export BUDDY_ACK_READ=1      # 0.3s listen window; or a number of seconds
```

These land in `$BUDDY_LOG` tagged `dev`, interleaved with the `send`/`EVT:`
lines. Reading a missing-beep incident top to bottom now separates the three
failure modes: no `permission.show` (host never sent) → a `send` with no `dev
state` ack (device dropped it) → a `dev state` ack with the prompt set but no
`dev beep` (device got it but didn't chirp). `BUDDY_ACK_READ` is off by default
and a no-op against normal firmware, so leave it unset outside an investigation.

## Try it

With the device plugged in, run `claude` and ask it to do something that needs
permission (e.g. *"run `ls` with Bash"*). The approval prompt should show on the
device; tap **A** to approve or **B** to deny. Finish a response and you should
hear the completion fanfare.

Smoke-test the bridge without Claude Code:

```bash
echo '{"hook_event_name":"Stop"}' | python3 hook.py        # should fanfare
echo '{"hook_event_name":"SessionStart","source":"startup"}' | python3 hook.py
```

## How it works / limitations

This is the **stateless MVP**: each hook invocation opens the serial port, sends
one line (and for permissions, waits for the reply), then closes it. The port is
opened with DTR/RTS held low so the ESP32 isn't reset on every hook, and a file
lock (`$XDG_RUNTIME_DIR/claude-buddy.lock`) serialises concurrent hooks.

Consequences worth knowing:

- **Single-session-ish.** The session counters (`total`/`running`/`waiting`) are
  per-event approximations, not aggregated across multiple concurrent Claude
  sessions. Two sessions sharing one device will fight over the display.
- **USB only.** No BLE here; the device must be on the cable. (BLE-direct would
  need a persistent central — a good fit for the daemon upgrade.)
- **Nothing here can break your session.** Every failure path exits 0 with no
  decision, so Claude Code behaves as if the hooks weren't installed.

If you want robust multi-session support, a wireless link, or live token/stats,
the next step is a small background **daemon** that owns the connection and
aggregates state, with these hooks becoming thin clients.
