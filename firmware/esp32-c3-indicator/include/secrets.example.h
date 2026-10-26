// Copy to secrets.h to enable the optional wireless mirror. With this file the
// board subscribes to the broker as well as listening on USB serial. Without it
// the radio is never started (the default, cable-only build).
#pragma once
#define REWATCH_WIFI_SSID "wifi name"
#define REWATCH_WIFI_PASS "wifi pass"
#define REWATCH_MQTT_HOST "192.168.100.1"   // Pi 4 core
#define REWATCH_MQTT_PORT 1883
