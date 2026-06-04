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

// Speaker (onboard I2S amplifier).
// The SC01 Plus drives a small speaker through an I2S amp on these pins. The
// M5StickC Plus original used a passive buzzer via M5.Beep.tone(); here that
// shim synthesises the same chirps as a square wave streamed over I2S. Pins
// match the WT32-SC01 Plus wiring (same ones Lumia-ESP32 uses for playback).
#define SC01_I2S_PORT      0
#define SC01_I2S_BCLK_PIN  36
#define SC01_I2S_LRCK_PIN  35
#define SC01_I2S_DOUT_PIN  37
#define SC01_I2S_SAMPLE_HZ 22050
// Square-wave amplitude (0..32767). Full scale is painfully loud/harsh through
// the fixed-gain amp, so beeps run well below it. Bump if too quiet.
#define SC01_BEEP_AMPLITUDE 16000
// DMA depth. tone() queues an entire beep at once, so this must exceed the
// longest beep the firmware plays (200ms) with margin; otherwise the tail would
// be dropped. 12 x 512 frames @ 22050Hz ~= 278ms.
#define SC01_I2S_DMA_COUNT 12
#define SC01_I2S_DMA_LEN   512
