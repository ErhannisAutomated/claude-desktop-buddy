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
