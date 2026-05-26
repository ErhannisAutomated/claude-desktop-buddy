// TFT_eSPI user setup for the WT32-SC01 Plus

#pragma once
#define USER_SETUP_LOADED 1

#define ST7796_DRIVER
#define TFT_PARALLEL_8_BIT

#define TFT_WIDTH 320
#define TFT_HEIGHT 480

// Control lines
#define TFT_CS -1
#define TFT_DC 0
#define TFT_RST 4
#define TFT_WR 47
#define TFT_RD 48

#define TFT_D0 9
#define TFT_D1 46
#define TFT_D2 3
#define TFT_D3 8
#define TFT_D4 18
#define TFT_D5 17
#define TFT_D6 16
#define TFT_D7 15

// backlight (GPIO45) is intentionally not defined here, as the M5 shim controls it via analogWrite() 
#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
#define SMOOTH_FONT
