#pragma once

// WT32-SC01 Plus board config, all board-specific tunables live here.

#define SC01_TFT_W 320
#define SC01_TFT_H 480

// Backlight
#define SC01_BL_PIN 45
#define SC01_BL_FULL 255

// ST7796 on the SC01 Plus needs color inversion on
// Without it, the dark UI renders with a white background
#define SC01_INVERT_DISPLAY   1

// Touch on i2c
#define SC01_TOUCH_SDA 6
#define SC01_TOUCH_SCL 5
#define SC01_TOUCH_ADDR 0x38
#define SC01_TOUCH_INT 7 
#define SC01_TOUCH_SWAP_XY 0
#define SC01_TOUCH_INVERT_X 0
#define SC01_TOUCH_INVERT_Y 0

#define SC01_TOUCH_DEBUG 0

// Screen self-test
#define SC01_BOOT_SELFTEST 1

// On-screen button bar
#define SC01_BAR_Y 426
#define SC01_BAR_H (SC01_TFT_H - SC01_BAR_Y)

#define SC01_SPR_ZOOM_X 2.00f
#define SC01_SPR_ZOOM_Y 1.75f
#define SC01_SPR_CX (SC01_TFT_W / 2)
#define SC01_SPR_CY 213

#define SC01_LONGPRESS_MS 600
