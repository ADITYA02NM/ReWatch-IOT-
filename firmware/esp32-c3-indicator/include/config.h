// ReWatch(Iot) — ESP32-C3 indicator configuration.
//
// A dumb display: it renders whatever the Pi 4 tells it and scores nothing of
// its own. The Pi 4 is the single source of truth; two scorers would disagree.
#pragma once
#include <Arduino.h>

// ── I2C / OLED ──────────────────────────────────────────────────────────────
// SDA 5 / SCL 6 on the ESP32-C3 SuperMini. GPIO8 is the onboard NeoPixel, so it
// is kept off the I2C bus.
constexpr uint8_t  PIN_I2C_SDA = 5;
constexpr uint8_t  PIN_I2C_SCL = 6;
constexpr uint8_t  OLED_ADDR   = 0x3C;
constexpr uint8_t  OLED_W      = 128;
constexpr uint8_t  OLED_H      = 64;

// ── NeoPixel ────────────────────────────────────────────────────────────────
constexpr uint8_t  PIN_LED_DATA = 8;
constexpr uint8_t  LED_COUNT    = 1;    // onboard pixel; raise for an external strip
constexpr uint8_t  LED_BRIGHT   = 255;  // full rail — colours are never dimmed

// ── Serial link to Pi 4 (USB) ───────────────────────────────────────────────
constexpr uint32_t SERIAL_BAUD     = 115200;
constexpr uint32_t LINK_TIMEOUT_MS = 3000;   // silence => sleeping face, blue pixel
constexpr uint32_t REDRAW_MS       = 125;    // OLED <= 8 Hz

// ── Optional wireless mirror ────────────────────────────────────────────────
// With include/secrets.h present the board ALSO subscribes to the broker, so it
// lights up on a shelf with no host attached. Without it the radio never starts.
#if defined(__has_include)
#  if __has_include("secrets.h")
#    include "secrets.h"
#    define REWATCH_HAS_WIFI 1
#  endif
#endif

constexpr char TOPIC_FRAME[]  = "rewatch/indicator/frame";
constexpr char TOPIC_STATE[]  = "rewatch/threat/state";
constexpr char TOPIC_HEALTH[] = "rewatch/health/#";
