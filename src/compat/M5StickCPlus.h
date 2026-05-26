#pragma once
// M5StickC Plus to WT32-SC01 Plus compatibility shim.
// This file is named M5StickCPlus.h on purpose: with `-I src/compat` on the
// include path (and the real m5stack/M5StickCPlus library removed from
// lib_deps), every `#include <M5StickCPlus.h>` in the firmware resolves HERE
// instead. That lets the entire app build unchanged against the SC01 Plus.
//
// I replaced:
//   * M5.Lcd becomes a real TFT_eSPI instance configured for an ST7796. using 8-bit parallel
//   * TFT_eSprite is straight from TFT_eSPI (it's an unchanged drawing API)
//   * M5.BtnA/.BtnB becomes a set of virtual buttons driven by on-screen touch zones
//   * M5.Axp becomes backlight brightness controls and a faked battery
//   * M5.Imu becomes a consistent flat/no-motion reporting stub, as the SC01 Plus has no IMU
//   * M5.Beep does nothing
//   * M5.Rtc uses software RTC set by the desktop's time-sync message

#include <Arduino.h>
#include <TFT_eSPI.h>
#include <FS.h>
#include <LittleFS.h>
using fs::File; // real M5 header used this
#include "sc01_config.h"

// Color names the firmware uses
#ifndef GREEN
#define GREEN 0x07E0
#endif
#ifndef RED
#define RED 0xF800
#endif

// RTC structs in same field names/order the firmware initialises
struct RTC_TimeTypeDef { uint8_t Hours, Minutes, Seconds; };
struct RTC_DateTypeDef { uint8_t WeekDay, Month, Date; uint16_t Year; };

// Virtual button: state is pushed in each M5.update() from touch zones
class ShimButton {
public:
  void set(bool nowDown) {
    _wasPressed  = nowDown && !_down;
    _wasReleased = !nowDown && _down;
    if (_wasPressed) _pressStart = millis();
    _down = nowDown;
  }
  bool isPressed() const { return _down; }
  bool wasPressed() const { return _wasPressed; }
  bool wasReleased() const { return _wasReleased; }
  bool pressedFor(uint32_t ms) const {
    return _down && (millis() - _pressStart) >= ms;
  }
private:
  bool _down = false, _wasPressed = false, _wasReleased = false;
  uint32_t _pressStart = 0;
};

// Power/brightness
class ShimAxp {
public:
  void ScreenBreath(uint8_t pct); // Backlight PWM
  void SetLDO2(bool on); // screen on/off (restore vs. 0)
  void PowerOff(); // backlight off, wait for tap, restart
  // Faked power telemetry: this board is USB powered with no fuel gauge.
  float GetBatVoltage() { return 4.15f }
  float GetBatCurrent() { return 0.0f; }
  float GetVBusVoltage() { return 5.0f; }
  int GetTempInAXP192() { return 25; }
  uint8_t GetBtnPress() { return 0; } // no hardware power button
private:
  uint8_t _lastPct = 80;
};

// always report sitting still
class ShimImu {
public:
  void Init() {}
  void getAccelData(float* ax, float* ay, float* az) { *ax = 0; *ay = 0; *az = 1.0f; }
};

// No buzzer
class ShimBeep {
public:
  void begin() {}
  void update() {}
  void tone(uint16_t /*freq*/, uint16_t /*durMs*/) {}
};

// Software RTC taken from by {"time":[epoch,tz]} from the desktop
class ShimRtc {
public:
  void SetTime(RTC_TimeTypeDef* t);
  void SetDate(RTC_DateTypeDef* d);
  void GetTime(RTC_TimeTypeDef* t);
  void GetDate(RTC_DateTypeDef* d);
private:
  void recompute();
  RTC_TimeTypeDef _t{};
  RTC_DateTypeDef _d{};
  time_t _baseEpoch = 0; 
  uint32_t _baseMs = 0;
  bool _haveTime = false, _haveDate = false;
};

// Faked M5
class M5Shim {
public:
  TFT_eSPI Lcd; 
  ShimButton BtnA;
  ShimButton BtnB;
  ShimAxp Axp;
  ShimImu Imu;
  ShimBeep Beep;
  ShimRtc Rtc;

  void begin();
  void update();
};

extern M5Shim M5;

// Helpers

// Push the 135x240 buddy sprite scaled up into the top of the SC01 screen
void m5PushBuddy(TFT_eSprite& spr);

// Draw the two on-screen A/B touch targets in the bottom bar
void m5DrawSoftButtons();

// True while a finger is anywhere on the panel
bool m5TouchAnyDown();

// Force the soft-button bar to repaint next frame (after a full-screen clear)
void m5SoftButtonsInvalidate();
