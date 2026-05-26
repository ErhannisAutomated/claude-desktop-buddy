// M5StickC Plus to WT32-SC01 Plus shim

#include <M5StickCPlus.h> // resolves to ../compat/M5StickCPlus.h (shim)
#include <Wire.h>
#include <time.h>

M5Shim M5;


static bool g_touchDown = false;
static uint16_t g_tx = 0, g_ty = 0;
static bool g_barDirty = true;

static bool readTouch(uint16_t& x, uint16_t& y) {
  Wire.beginTransmission(SC01_TOUCH_ADDR);
  Wire.write(0x02);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(SC01_TOUCH_ADDR, 5) != 5) return false;
  uint8_t n = Wire.read() & 0x0F;
  uint8_t xh = Wire.read();
  uint8_t xl = Wire.read();
  uint8_t yh = Wire.read();
  uint8_t yl = Wire.read();
  if (n == 0) return false;
  uint16_t rx = ((xh & 0x0F) << 8) | xl;
  uint16_t ry = ((yh & 0x0F) << 8) | yl;

#if SC01_TOUCH_SWAP_XY
  { uint16_t t = rx; rx = ry; ry = t; }
#endif
#if SC01_TOUCH_INVERT_X
  rx = (SC01_TFT_W - 1) - rx;
#endif
#if SC01_TOUCH_INVERT_Y
  ry = (SC01_TFT_H - 1) - ry;
#endif
  x = rx; y = ry;
#if SC01_TOUCH_DEBUG
  Serial.printf("touch raw n=%u x=%u y=%u\n", n, x, y);
#endif
  return true;
}

// M5 fake lifecycle
void M5Shim::begin() {
  // Force the backlight FIRST
  pinMode(SC01_BL_PIN, OUTPUT);
  digitalWrite(SC01_BL_PIN, HIGH);

  Lcd.init();
  Lcd.setRotation(0);
  Lcd.invertDisplay(SC01_INVERT_DISPLAY);

#if SC01_BOOT_SELFTEST
  Serial.println("[sc01] display self-test: R/G/B");
  Lcd.fillScreen(TFT_RED); delay(500);
  Lcd.fillScreen(TFT_GREEN); delay(500);
  Lcd.fillScreen(TFT_BLUE); delay(500);
#endif

  Lcd.fillScreen(TFT_BLACK);
  Axp.ScreenBreath(80); // brightness in PWM path
  Wire.begin(SC01_TOUCH_SDA, SC01_TOUCH_SCL);
  Wire.setClock(400000);
}

void M5Shim::update() {
  g_touchDown = readTouch(g_tx, g_ty);

  bool aDown = false, bDown = false;
  if (g_touchDown && g_ty >= SC01_BAR_Y) {
    if (g_tx < SC01_TFT_W / 2) aDown = true;
    else bDown = true;
  }
  BtnA.set(aDown);
  BtnB.set(bDown);
}

bool m5TouchAnyDown() { return g_touchDown; }


void m5SoftButtonsInvalidate() { g_barDirty = true; }

// Backlight
void ShimAxp::ScreenBreath(uint8_t pct) {
  if (pct > 100) pct = 100;
  _lastPct = pct;
  analogWrite(SC01_BL_PIN, (int)((uint32_t)pct * SC01_BL_FULL / 100));
}
void ShimAxp::SetLDO2(bool on) {
  analogWrite(SC01_BL_PIN, on ? (int)((uint32_t)_lastPct * SC01_BL_FULL / 100) : 0);
}
void ShimAxp::PowerOff() {
  analogWrite(SC01_BL_PIN, 0);
  // No PMIC to cut power; idle dark until a tap, then reboot.
  uint16_t x, y;
  while (!readTouch(x, y)) delay(50);
  ESP.restart();
}

// Software RTC
static int64_t daysFromCivil(int y, unsigned m, unsigned d) {
  y -= m <= 2;
  int era = (y >= 0 ? y : y - 399) / 400;
  unsigned yoe = (unsigned)(y - era * 400);
  unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return (int64_t)era * 146097 + (int)doe - 719468;
}

void ShimRtc::recompute() {
  if (!(_haveTime && _haveDate)) return;
  // The bridge already applied the tz offset, so treat the components as UTC
  int64_t days = daysFromCivil(_d.Year, _d.Month, _d.Date);
  _baseEpoch = (time_t)(days * 86400 + _t.Hours * 3600 + _t.Minutes * 60 + _t.Seconds);
  _baseMs = millis();
}
void ShimRtc::SetTime(RTC_TimeTypeDef* t) { _t = *t; _haveTime = true; recompute(); }
void ShimRtc::SetDate(RTC_DateTypeDef* d) { _d = *d; _haveDate = true; recompute(); }

void ShimRtc::GetTime(RTC_TimeTypeDef* t) {
  if (!_baseEpoch) { *t = _t; return; }
  time_t now = _baseEpoch + (millis() - _baseMs) / 1000;
  struct tm lt; gmtime_r(&now, &lt);
  t->Hours = lt.tm_hour; t->Minutes = lt.tm_min; t->Seconds = lt.tm_sec;
}
void ShimRtc::GetDate(RTC_DateTypeDef* d) {
  if (!_baseEpoch) { *d = _d; return; }
  time_t now = _baseEpoch + (millis() - _baseMs) / 1000;
  struct tm lt; gmtime_r(&now, &lt);
  d->WeekDay = lt.tm_wday; d->Month = lt.tm_mon + 1;
  d->Date = lt.tm_mday; d->Year = lt.tm_year + 1900;
}

// On-screen rendering helpers
void m5PushBuddy(TFT_eSprite& spr) {
  // This TFT_eSPI build has no scaled sprite push, so do a nearest-neighbour upscale of the 135x240 sprite framebuffer into PSRAM buffer
  const int sw = spr.width(), sh = spr.height();
  const int ow = (int)(sw * SC01_SPR_ZOOM_X + 0.5f);
  const int oh = (int)(sh * SC01_SPR_ZOOM_Y + 0.5f);

  static uint16_t* buf = nullptr;
  static int cap = 0;
  if (!buf || cap < ow * oh) {
    if (buf) free(buf);
    cap = ow * oh;
    buf = (uint16_t*)ps_malloc(cap * sizeof(uint16_t));     // PSRAM first
    if (!buf) buf = (uint16_t*)malloc(cap * sizeof(uint16_t));
  }
  uint16_t* src = (uint16_t*)spr.getPointer();
  if (!buf || !src) { spr.pushSprite(0, 0); return; }

  for (int oy = 0; oy < oh; oy++) {
    int sy = (int)(oy / SC01_SPR_ZOOM_Y); if (sy >= sh) sy = sh - 1;
    const uint16_t* srow = src + sy * sw;
    uint16_t* drow = buf + oy * ow;

    for (int ox = 0; ox < ow; ox++) {
      int sx = (int)(ox / SC01_SPR_ZOOM_X); if (sx >= sw) sx = sw - 1;
      drow[ox] = srow[sx];
    }
  }

  const int x = SC01_SPR_CX - ow / 2;
  const int y = SC01_SPR_CY - oh / 2;
  bool prevSwap = M5.Lcd.getSwapBytes();
  M5.Lcd.setSwapBytes(true);
  M5.Lcd.pushImage(x, y, ow, oh, buf);
  M5.Lcd.setSwapBytes(prevSwap);
}

void m5DrawSoftButtons() {
  TFT_eSPI& g = M5.Lcd;
  const int y = SC01_BAR_Y;
  const int h = SC01_BAR_H - 2;
  const int wL = SC01_TFT_W / 2;
  bool aHot = M5.BtnA.isPressed();
  bool bHot = M5.BtnB.isPressed();

  static bool lastA = false, lastB = false;
  if (!g_barDirty && aHot == lastA && bHot == lastB) return;
  g_barDirty = false;
  lastA = aHot;
  lastB = bHot;

  g.drawFastHLine(0, y - 1, SC01_TFT_W, TFT_DARKGREY);


  // Approve
  g.fillRect(0, y, wL - 1, h, aHot ? GREEN : TFT_BLACK);
  g.drawRect(0, y, wL - 1, h, GREEN);

  // Dcecline
  g.fillRect(wL + 1, y, SC01_TFT_W - wL - 1, h, bHot ? RED : TFT_BLACK);
  g.drawRect(wL + 1, y, SC01_TFT_W - wL - 1, h, RED);

  g.setTextDatum(MC_DATUM);
  g.setTextSize(3);
  g.setTextColor(aHot ? TFT_BLACK : GREEN, aHot ? GREEN : TFT_BLACK);
  g.drawString("A", wL / 2, y + h / 2);
  g.setTextColor(bHot ? TFT_BLACK : RED, bHot ? RED : TFT_BLACK);
  g.drawString("B", wL + (SC01_TFT_W - wL) / 2, y + h / 2);
  g.setTextDatum(TL_DATUM);
  g.setTextSize(1);
}
