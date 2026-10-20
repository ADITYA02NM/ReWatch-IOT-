// ReWatch — ESP32-WROOM room rig.
//
// Four AC controllers for rooms 1-4, modelled as real devices on the IoT Wi-Fi.
// Each one:
//   * publishes rewatch/iot/<id>/telemetry at ~2 Hz  (temp_c, setpoint, power, room, ip)
//   * obeys   rewatch/iot/<id>/cmd  {"setpoint":20}  — this is how the Pi 4
//     responder forces an AC back to its baseline
//   * answers GET http://<ip>/status so the Pi 4 Wi-Fi verifier can cross-check
//     the bus reading against the device's own
//
// Scenario control on rewatch/rig/cmd:
//   {"scenario":"ac-spike","device":"room1-ac"}  drive that room toward 35 C
//   {"scenario":"reset"}                           every room back to 20 C
// The onboard BOOT button (GPIO0) toggles the Room 1 spike by hand for a demo.
//
// The temperature is a real first-order model (it eases toward its target), so
// the verifier always agrees with the bus — this rig does not lie. Switch the
// board off and the rest of the system keeps running without it.

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <WebServer.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <math.h>
#if defined(REWATCH_BUILD_CHECK)
#include "secrets.example.h"
#else
#include "secrets.h"
#endif

static const uint8_t PIN_LED = 2;      // onboard LED
static const uint8_t PIN_BTN = 0;      // BOOT button
static const float   BASELINE = 20.0f;
static const float   SPIKE = 35.0f;
static const float   EASE = 0.06f;     // per tick toward target

struct Room {
  const char *id;
  const char *name;
  float setpoint;   // what the thermostat is told to hold
  float target;     // where it is being driven (spike overrides setpoint)
  float temp;       // actual temperature
  bool spiked;
};
Room rooms[] = {
  {"room1-ac", "Room 1", BASELINE, BASELINE, 20.0f, false},
  {"room2-ac", "Room 2", BASELINE, BASELINE, 20.0f, false},
  {"room3-ac", "Room 3", BASELINE, BASELINE, 20.0f, false},
  {"room4-ac", "Room 4", BASELINE, BASELINE, 20.0f, false},
};
const size_t NROOMS = sizeof(rooms) / sizeof(rooms[0]);

WiFiClient net;
PubSubClient mqtt(net);
WebServer http(80);

Room *find_room(const char *id) {
  for (size_t i = 0; i < NROOMS; i++)
    if (!strcmp(rooms[i].id, id)) return &rooms[i];
  return nullptr;
}

void set_spike(Room *r, bool on) {
  r->spiked = on;
  r->target = on ? SPIKE : r->setpoint;
  Serial.printf("[rig] %s spike %s\n", r->id, on ? "ON" : "off");
}

// ── HTTP /status for the Wi-Fi verifier ─────────────────────────────────────
void handle_status() {
  JsonDocument doc;
  doc["node"] = "esp32-wroom-rig";
  doc["ip"] = WiFi.localIP().toString();
  doc["rssi"] = WiFi.RSSI();
  JsonArray arr = doc["devices"].to<JsonArray>();
  for (size_t i = 0; i < NROOMS; i++) {
    JsonObject o = arr.add<JsonObject>();
    o["device"] = rooms[i].id;
    o["room"] = rooms[i].name;
    o["temp_c"] = roundf(rooms[i].temp * 10) / 10.0f;
    o["setpoint"] = rooms[i].setpoint;
  }
  String out; serializeJson(doc, out);
  http.send(200, "application/json", out);
}

// ── MQTT commands ───────────────────────────────────────────────────────────
void on_mqtt(char *topic, byte *payload, unsigned int len) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, len)) return;
  String t(topic);
  if (t == "rewatch/rig/cmd") {
    const char *scen = doc["scenario"] | "";
    if (!strcmp(scen, "reset")) {
      for (size_t i = 0; i < NROOMS; i++) { rooms[i].setpoint = BASELINE; set_spike(&rooms[i], false); }
    } else if (!strcmp(scen, "ac-spike")) {
      Room *r = find_room(doc["device"] | "room1-ac");
      if (r) set_spike(r, true);
    }
    return;
  }
  // rewatch/iot/<id>/cmd  — the responder (or an operator) setting a target
  if (!t.startsWith("rewatch/iot/") || !t.endsWith("/cmd")) return;
  int s2 = t.indexOf('/', 12);
  if (s2 > 0) {
    if (t.substring(s2) != "/cmd") return;
    String id = t.substring(12, s2);
    Room *r = find_room(id.c_str());
    if (r && doc["setpoint"].is<float>()) {
      float setpoint = doc["setpoint"].as<float>();
      // Bound this demo model; malformed/nonfinite targets must not poison telemetry.
      if (!isfinite(setpoint) || setpoint < 16.0f || setpoint > 35.0f) return;
      r->setpoint = setpoint;
      set_spike(r, false);              // a command back to baseline clears the spike
      r->target = r->setpoint;
      Serial.printf("[rig] %s setpoint -> %.0f (%s)\n", r->id, r->setpoint,
                    doc["by"].as<const char *>() ? doc["by"].as<const char *>() : "?");
    }
  }
}

void mqtt_reconnect() {
  if (mqtt.connected()) return;
  static uint32_t next = 0;
  if ((int32_t)(millis() - next) < 0) return;
  next = millis() + 3000;
  String id = "rewatch-rig-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  bool ok = strlen(REWATCH_MQTT_USER)
    ? mqtt.connect(id.c_str(), REWATCH_MQTT_USER, REWATCH_MQTT_PASS,
                   "rewatch/health/rig", 0, true, "{\"node\":\"rig\",\"online\":false}")
    : mqtt.connect(id.c_str(), "rewatch/health/rig", 0, true,
                   "{\"node\":\"rig\",\"online\":false}");
  if (ok) {
    mqtt.subscribe("rewatch/rig/cmd");
    mqtt.subscribe("rewatch/iot/+/cmd");
    mqtt.publish("rewatch/health/rig", "{\"node\":\"rig\",\"online\":true}", true);
    Serial.println("[rig] mqtt up");
  }
}

void publish_all() {
  String ip = WiFi.localIP().toString();
  for (size_t i = 0; i < NROOMS; i++) {
    Room &r = rooms[i];
    JsonDocument d;
    d["device"] = r.id; d["room"] = r.name; d["kind"] = "ac";
    d["temp_c"] = roundf(r.temp * 10) / 10.0f;
    d["setpoint"] = r.setpoint;
    d["power"] = r.spiked ? "fault" : "on";
    d["ip"] = ip;
    // No wall clock is configured: the host stamps reception time instead.
    d["uptime_s"] = millis() / 1000;
    char topic[48]; snprintf(topic, sizeof(topic), "rewatch/iot/%s/telemetry", r.id);
    String out; serializeJson(d, out);
    mqtt.publish(topic, out.c_str());
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BTN, INPUT_PULLUP);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(REWATCH_WIFI_SSID, REWATCH_WIFI_PASS);
  Serial.print("[rig] wifi");
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(250); Serial.print("."); }
  Serial.printf("\n[rig] ip %s\n", WiFi.localIP().toString().c_str());
  mqtt.setServer(REWATCH_MQTT_HOST, REWATCH_MQTT_PORT);
  mqtt.setCallback(on_mqtt);
  mqtt.setBufferSize(512);
  http.on("/status", handle_status);
  http.on("/", []() { http.send(200, "text/plain", "ReWatch room rig. GET /status for JSON."); });
  http.begin();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) { WiFi.reconnect(); delay(500); return; }
  mqtt_reconnect();
  mqtt.loop();
  http.handleClient();
  static uint32_t t_health = 0;
  if (millis() - t_health >= 5000 && mqtt.connected()) {
    t_health = millis();
    mqtt.publish("rewatch/health/rig", "{\"node\":\"rig\",\"online\":true}", true);
  }

  // BOOT button toggles the Room 1 spike (debounced edge)
  static bool last = true; static uint32_t t_btn = 0;
  bool now = digitalRead(PIN_BTN);
  if (last && !now && millis() - t_btn > 300) {
    t_btn = millis();
    set_spike(&rooms[0], !rooms[0].spiked);
  }
  last = now;

  // temperature model + telemetry at ~2 Hz
  static uint32_t t_pub = 0;
  if (millis() - t_pub >= 500) {
    t_pub = millis();
    bool anyspike = false;
    for (size_t i = 0; i < NROOMS; i++) {
      Room &r = rooms[i];
      r.temp += (r.target - r.temp) * EASE + (random(-10, 11) / 100.0f);  // ease + tiny noise
      if (r.spiked) anyspike = true;
    }
    publish_all();
    // LED: steady when calm, blinking while a room is spiked
    digitalWrite(PIN_LED, anyspike ? (millis() / 200) & 1 : HIGH);
  }
}
