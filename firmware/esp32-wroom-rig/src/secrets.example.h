// Copy to secrets.h before building the room rig.
#pragma once
#define REWATCH_WIFI_SSID "wifi name"
#define REWATCH_WIFI_PASS "wifi pass"
#define REWATCH_MQTT_HOST "192.168.100.1"   // Pi 4 core
#define REWATCH_MQTT_PORT 1883
// Optional broker auth (leave empty for an open LAN broker):
#define REWATCH_MQTT_USER ""
#define REWATCH_MQTT_PASS ""
