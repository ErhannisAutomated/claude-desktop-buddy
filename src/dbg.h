#pragma once
#include <Arduino.h>

// Device-side debug acks for the missing-prompt-beep investigation.
//
// OFF unless the firmware is built with -DBUDDY_DEBUG_ACK (see the
// wt32-sc01-plus-debug env in platformio.ini). When on, the device emits one
// JSON line out USB Serial at the two points that matter:
//   * every snapshot it actually parses and applies  ({"ack":"state",...})
//   * a line it received but could NOT parse          ({"ack":"parse",...})
//   * every prompt chirp it actually fires            ({"ack":"beep",...})
//
// Read alongside the host bridge's log, this separates the three failure modes
// for a notification that didn't sound: host never sent (no permission.show in
// the host log), device dropped the line (no "state" ack), or device applied it
// but didn't chirp (a "state" ack with the prompt set, but no matching "beep").
//
// Serial only — the investigation is over USB, and keeping it off the BLE path
// avoids touching that code. Compiles to nothing in normal builds.
#ifdef BUDDY_DEBUG_ACK
  #define DBG_ACK(...) do { Serial.printf(__VA_ARGS__); } while (0)
#else
  #define DBG_ACK(...) do { (void)0; } while (0)
#endif
