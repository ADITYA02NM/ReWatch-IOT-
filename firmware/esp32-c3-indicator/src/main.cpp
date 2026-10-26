// ReWatch(Iot) — ESP32-C3 indicator.
//
// The visible state of the appliance. The Pi 4 writes newline-delimited JSON
// down USB (~10 Hz); this board renders the score, the band, the fleet, a
// countdown and an ECG trace. It scores nothing itself. If the link goes quiet
// the panel shows a sleeping face and the pixel turns blue — a stale GREEN is
// worse than an honest blank.
//
// Frame (one JSON object per line):
//   {"score":72,"band":"RED","open":1,"cd":94,"msg":"Room 1 AC 35 C","nodes":"1110"}
//   band GREEN|BLUE|YELLOW|RED|PURPLE   cd seconds left (-1 = none)
//   nodes = core,sentinel,herald,rig  (1 = reporting)
//
// Bands carry colour AND motion:
//   GREEN  steady green      normal, being watched
//   BLUE   slow blue throb    a node is offline / no link
//   YELLOW 2 Hz yellow        scan or drift
//   RED    4 Hz red blink     critical
//   PURPLE 1 Hz purple        unacknowledged -> automated response

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_NeoPixel.h>
#include <ArduinoJson.h>
#include <ctype.h>
#include <math.h>
#include "config.h"

#if defined(REWATCH_HAS_WIFI)
#include <WiFi.h>
#include <PubSubClient.h>
#endif

namespace {

Adafruit_SSD1306 oled(OLED_W, OLED_H, &Wire, -1);
Adafruit_NeoPixel pixel(LED_COUNT, PIN_LED_DATA, NEO_GRB + NEO_KHZ800);
bool strip_ok = false;
bool oled_ok = false;

enum class Band : uint8_t { Green, Blue, Yellow, Red, Purple, Unknown };
enum class LedMode : uint8_t { Offline, Normal, Detect, Alert, Action };

struct Reading {
  int score = 0;
  Band band = Band::Unknown;
  int open = 0;
  int cd = -1;
  char msg[48] = "";
  char nodes[6] = "0000";
  bool have_data = false;
  uint32_t last_rx = 0;
};
Reading g;
String line;
// Python json.dumps escapes up to 40 Unicode characters as \uXXXX pairs.
constexpr size_t MAX_FRAME = 640;
bool dropping_line = false;
constexpr size_t MSG_COLS = OLED_W / 6;

// ── colour rails (full saturation, never dimmed) ────────────────────────────
constexpr uint32_t pack(uint8_t r, uint8_t gr, uint8_t b) {
  return (uint32_t(r) << 16) | (uint32_t(gr) << 8) | b;
}
constexpr uint32_t RGB_GREEN  = pack(0x00, 0xff, 0x00);
constexpr uint32_t RGB_YELLOW = pack(0xff, 0xcc, 0x00);
constexpr uint32_t RGB_RED    = pack(0xff, 0x00, 0x00);
constexpr uint32_t RGB_PURPLE = pack(0xb0, 0x00, 0xff);
constexpr uint32_t RGB_BLUE   = pack(0x00, 0x40, 0xff);

Band parse_band(const char *raw) {
  if (!raw) return Band::Unknown;
  char b[12]; size_t n = 0;
  while (raw[n] && n < sizeof(b) - 1) { b[n] = toupper((unsigned char)raw[n]); n++; }
  while (n && (b[n - 1] == ' ' || b[n - 1] == '\t')) n--;
  b[n] = '\0';
  if (!strcmp(b, "GREEN")) return Band::Green;
  if (!strcmp(b, "BLUE")) return Band::Blue;
  if (!strcmp(b, "YELLOW")) return Band::Yellow;
  if (!strcmp(b, "RED")) return Band::Red;
  if (!strcmp(b, "PURPLE")) return Band::Purple;
  return Band::Unknown;
}

bool link_lost() {
  if (!g.have_data) return true;
  return (millis() - g.last_rx) > LINK_TIMEOUT_MS;
}

// ── ECG trace: the band is the heartbeat rate ───────────────────────────────
int trace_pitch(Band b) {
  switch (b) {
    case Band::Yellow: return 128;  // one beat per screen
    case Band::Red:    return 64;   // two
    case Band::Purple: return 32;   // four
    default:           return 0;    // green/blue/unknown: flat
  }
}
struct Knot { float t; int8_t a; };
const Knot ECG[] = {{0,0},{.08f,0},{.13f,3},{.18f,0},{.22f,-2},{.25f,13},
                    {.28f,-4},{.32f,0},{.40f,0},{.47f,5},{.56f,0},{1,0}};
int ecg_defl(int p, int pitch) {
  float t = float(p) / float(pitch);
  for (size_t i = 1; i < sizeof(ECG) / sizeof(ECG[0]); i++) {
    if (t <= ECG[i].t) {
      float span = ECG[i].t - ECG[i - 1].t;
      float u = span > 0 ? (t - ECG[i - 1].t) / span : 0;
      float v = ECG[i - 1].a * (1 - u) + ECG[i].a * u;
      return int(v < 0 ? v - .5f : v + .5f);
    }
  }
  return 0;
}

// ── parse incoming frames ───────────────────────────────────────────────────
void apply_frame(const String &raw) {
  JsonDocument doc;
  if (deserializeJson(doc, raw)) return;
  // Only complete readings can renew the watchdog; {} must not keep GREEN alive.
  if (!doc["score"].is<int>() || !doc["band"].is<const char *>()) return;
  int score = doc["score"].as<int>();
  if (score < 0 || score > 100) return;
  g.score = score;
  g.band = parse_band(doc["band"].as<const char *>());
  g.open = doc["open"] | 0;
  g.cd = doc["cd"] | -1;
  const char *m = doc["msg"].as<const char *>();
  strncpy(g.msg, m ? m : "", sizeof(g.msg) - 1); g.msg[sizeof(g.msg) - 1] = '\0';
  const char *nd = doc["nodes"].as<const char *>();
  strcpy(g.nodes, "0000");
  if (nd && strlen(nd) == 4) {
    for (size_t i = 0; i < 4; i++) g.nodes[i] = nd[i] == '1' ? '1' : '0';
  }
  g.have_data = true;
  g.last_rx = millis();
}

// The server also publishes the richer threat/state; map it onto a frame.
void apply_state(const String &raw) {
  JsonDocument doc;
  if (deserializeJson(doc, raw)) return;
  if (!doc["score"].is<float>() || !doc["band"].is<const char *>()) return;
  float score = doc["score"].as<float>();
  if (!isfinite(score) || score < 0 || score > 100) return;
  g.score = int(roundf(score));
  g.band = parse_band(doc["band"].as<const char *>());
  strcpy(g.nodes, "0000");  // threat/state carries no fleet heartbeat bits
  JsonVariant inc = doc["incident"];
  g.open = (!inc.isNull() && strcmp(inc["state"] | "", "open") == 0) ? 1 : 0;
  g.cd = g.open ? int(inc["remaining"] | -1) : -1;
  const char *r = doc["reason"].as<const char *>();
  strncpy(g.msg, r ? r : "", sizeof(g.msg) - 1); g.msg[sizeof(g.msg) - 1] = '\0';
  g.have_data = true; g.last_rx = millis();
}

// ── pixel ───────────────────────────────────────────────────────────────────
LedMode mode_for(bool lost, Band b) {
  if (lost || b == Band::Blue) return LedMode::Offline;
  switch (b) {
    case Band::Green:  return LedMode::Normal;
    case Band::Yellow: return LedMode::Detect;
    case Band::Red:    return LedMode::Alert;
    case Band::Purple: return LedMode::Action;
    default:           return LedMode::Offline;
  }
}
uint16_t mode_period(LedMode m) {
  switch (m) {
    case LedMode::Normal: return 0;     // steady
    case LedMode::Detect: return 500;   // 2 Hz
    case LedMode::Alert:  return 250;   // 4 Hz
    case LedMode::Action: return 1000;  // 1 Hz
    default:              return 2000;  // 0.5 Hz blue
  }
}
uint32_t mode_colour(LedMode m) {
  switch (m) {
    case LedMode::Normal: return RGB_GREEN;
    case LedMode::Detect: return RGB_YELLOW;
    case LedMode::Alert:  return RGB_RED;
    case LedMode::Action: return RGB_PURPLE;
    default:              return RGB_BLUE;
  }
}
LedMode led_mode = LedMode::Offline;
void led_loop() {
  led_mode = mode_for(link_lost(), g.band);
  if (!strip_ok) return;
  uint16_t period = mode_period(led_mode);
  bool lit = period == 0 || ((millis() / (period / 2)) & 1);
  uint32_t want = lit ? mode_colour(led_mode) : 0u;
  static uint32_t shown = 0xFFFFFFFF;
  if (want == shown) return;
  shown = want;
  for (uint16_t i = 0; i < LED_COUNT; i++) pixel.setPixelColor(i, want);
  pixel.show();
}

// ── boot animation (Wall-E eyes, carried over from ULTRON) ──────────────────
void draw_eye(int cx, int cy, int r, float open) {
  if (open <= .03f) { oled.drawLine(cx - r, cy, cx + r, cy, SSD1306_WHITE); return; }
  oled.fillCircle(cx, cy, r, SSD1306_WHITE);
  if (open < .97f) {
    int half = int(r * open);
    oled.fillRect(cx - r - 2, cy - r - 2, 2 * r + 4, r - half + 2, SSD1306_BLACK);
    oled.fillRect(cx - r - 2, cy + half, 2 * r + 4, r - half + 2, SSD1306_BLACK);
  }
}
float smooth(float p) { return p * p * (3 - 2 * p); }
void draw_eyes(float turn, float open) {
  int cy = 30, R = 15, a = 40, b = 88, sh = int(turn * 10), ti = int(turn * 4);
  draw_eye(a + sh, cy + ti, R, open);
  draw_eye(b + sh, cy - ti, R, open);
}
void draw_happy(int cx, int cy, int r) {
  for (int x = -r; x <= r; x++) {
    int y = int(sqrtf(float(r * r - x * x)) * .55f);
    oled.writePixel(cx + x, cy - y - 3, SSD1306_WHITE);
    oled.writePixel(cx + x, cy - y - 2, SSD1306_WHITE);
  }
}
void draw_smile(int cx, int cy, int half, int depth) {
  for (int x = -half; x <= half; x++) {
    float u = float(x) / half; int y = int(depth * (1 - u * u));
    oled.writePixel(cx + x, cy + y, SSD1306_WHITE);
    oled.writePixel(cx + x, cy + y + 1, SSD1306_WHITE);
  }
}
void boot_animation() {
  const uint32_t OPN = 700, L = 850, Rr = 950, C = 400, BL = 180, SM = 1800;
  const uint32_t TOT = OPN + L + Rr + C + BL + SM;
  int cy = 30, R = 15, a = 40, b = 88;
  uint32_t t0 = millis();
  while (millis() - t0 < TOT) {
    uint32_t e = millis() - t0, look = OPN + L + Rr + C, blink = look + BL;
    oled.clearDisplay(); oled.setTextColor(SSD1306_WHITE); oled.setTextSize(1);
    oled.setCursor(40, 2); oled.print(F("ReWatch(Iot)"));
    if (e < OPN) draw_eyes(0, float(e) / OPN * (float(e) / OPN));
    else if (e < OPN + L) draw_eyes(-smooth(float(e - OPN) / L), 1);
    else if (e < OPN + L + Rr) draw_eyes(-1 + 2 * smooth(float(e - OPN - L) / Rr), 1);
    else if (e < look) draw_eyes(1 - smooth(float(e - OPN - L - Rr) / C), 1);
    else if (e < blink) draw_eyes(0, fabsf(cosf(float(e - look) / BL * PI)));
    else {
      int bob = int(sinf(float(millis() % 1400) / 1400 * 2 * PI) * 1.5f);
      draw_happy(a, cy + bob, R); draw_happy(b, cy + bob, R);
      draw_smile(OLED_W / 2, 46 + bob, 26, 8);
    }
    oled.display(); led_loop(); delay(15);
  }
}

// ── the readout ─────────────────────────────────────────────────────────────
void draw_lid(int cx, int cy, int r) {
  for (int x = -r; x <= r; x++) {
    int y = int(sqrtf(float(r * r - x * x)) * .6f);
    oled.writePixel(cx + x, cy - y, SSD1306_WHITE);
    oled.writePixel(cx + x, cy - y + 1, SSD1306_WHITE);
  }
}
void draw_lost() {
  oled.setTextColor(SSD1306_WHITE); oled.setTextSize(1);
  oled.setCursor(40, 2); oled.print(F("ReWatch(Iot)"));
  draw_lid(40, 36, 15); draw_lid(88, 36, 15);
  oled.setCursor(108, 14); oled.print(F("z")); oled.setCursor(118, 8); oled.print(F("z"));
  const char *cap = g.have_data ? "link lost - asleep" : "waiting for data";
  oled.setCursor((OLED_W - int(strlen(cap)) * 6) / 2, 54); oled.print(cap);
}
const char *const SHORT[4] = {"P4", "3A", "3B", "RG"};
void draw_nodes(int16_t y0) {
  oled.setTextSize(1);
  for (int i = 0; i < 4; i++) {
    int16_t x = (i % 2) * 24, y = y0 + (i / 2) * 15;
    bool up = g.nodes[i] == '1';
    if (up) { oled.fillRect(x, y, 22, 13, SSD1306_WHITE); oled.setTextColor(SSD1306_BLACK); }
    else { oled.drawRect(x, y, 22, 13, SSD1306_WHITE); oled.setTextColor(SSD1306_WHITE); }
    oled.setCursor(x + 4, y + 3); oled.print(SHORT[i]); oled.setTextColor(SSD1306_WHITE);
  }
}
const char *status_word() {
  switch (led_mode) {
    case LedMode::Alert:  return "ALERT";
    case LedMode::Detect: return "DETECT";
    case LedMode::Action: return "LOCKDOWN";
    case LedMode::Normal: return "NORMAL";
    default:              return g.band == Band::Blue ? "OFFLINE" : "LINK";
  }
}
void draw_trace(int16_t y0, int16_t h) {
  int16_t base = y0 + h - 5;
  oled.drawFastHLine(0, base, OLED_W, SSD1306_WHITE);
  int pitch = trace_pitch(g.band);
  if (!pitch) return;
  int scroll = (millis() / 60) % pitch;
  int prev = ecg_defl((scroll + pitch - 1) % pitch, pitch);
  for (int x = 0; x < OLED_W; x++) {
    int d = ecg_defl((x + scroll) % pitch, pitch);
    int from = base - prev, to = base - d, lo = min(from, to), hi = max(from, to);
    for (int y = lo; y <= hi; y++) oled.drawPixel(x, y, SSD1306_WHITE);
    prev = d;
  }
}
void draw() {
  if (!oled_ok) return;  // begin() may fail before a framebuffer is allocated
  oled.clearDisplay(); oled.setTextColor(SSD1306_WHITE);
  if (link_lost()) { draw_lost(); oled.display(); return; }
  oled.setTextSize(1); oled.setCursor(0, 0); oled.print(F("ReWatch(Iot)"));
  if (g.cd >= 0) { char cd[8]; snprintf(cd, sizeof(cd), "%3ds", g.cd); oled.setCursor(98, 0); oled.print(cd); }
  oled.drawLine(0, 10, OLED_W - 1, 10, SSD1306_WHITE);
  draw_nodes(12);
  char sb[8]; snprintf(sb, sizeof(sb), "%3d", g.score);
  oled.setTextSize(3); oled.setCursor(OLED_W - 3 * 18 - 2, 12); oled.print(sb);
  oled.setTextSize(1); oled.setCursor(OLED_W - 3 * 18 - 2, 37); oled.print(status_word());
  draw_trace(45, 19);
  oled.display();
}
void screen_sig(char *out, size_t n) {
  if (!g.have_data) snprintf(out, n, "NODATA");
  else if (link_lost()) snprintf(out, n, "LOST|%lu", (unsigned long)((millis() - g.last_rx) / 1000));
  else snprintf(out, n, "OK|%d|%d|%d|%s|%s|%lu", g.score, int(g.band), g.cd, g.nodes, g.msg,
                (unsigned long)((millis() / 60) % 128));
}

bool oled_begin() {
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setClock(400000); delay(20);
  uint8_t addr = 0;
  for (uint8_t a = OLED_ADDR; a <= OLED_ADDR + 1; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) { addr = a; break; }
  }
  if (!addr) for (uint8_t a = 0x08; a < 0x78; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) { addr = a; break; }
  }
  if (!addr) { Serial.println("[oled] not found"); return false; }
  return oled.begin(SSD1306_SWITCHCAPVCC, addr);
}

#if defined(REWATCH_HAS_WIFI)
WiFiClient net; PubSubClient mqtt(net);
uint32_t next_wifi = 0, next_mqtt = 0;
void on_mqtt(char *topic, byte *payload, unsigned int len) {
  if (len >= MAX_FRAME) return;
  char buf[MAX_FRAME]; memcpy(buf, payload, len); buf[len] = '\0';
  String body(buf);
  if (!strcmp(topic, TOPIC_FRAME)) apply_frame(body);
  else if (!strcmp(topic, TOPIC_STATE)) apply_state(body);
}
void net_loop(uint32_t now) {
  if (WiFi.status() != WL_CONNECTED) {
    if (int32_t(now - next_wifi) < 0) return;
    next_wifi = now + 10000; WiFi.begin(REWATCH_WIFI_SSID, REWATCH_WIFI_PASS); return;
  }
  if (!mqtt.connected()) {
    if (int32_t(now - next_mqtt) < 0) return;
    next_mqtt = now + 5000;
    String id = "rewatch-c3-" + String((uint32_t)ESP.getEfuseMac(), HEX);
    if (!mqtt.connect(id.c_str())) return;
    mqtt.subscribe(TOPIC_FRAME); mqtt.subscribe(TOPIC_STATE);
  }
  mqtt.loop();
}
#else
void net_loop(uint32_t) {}
#endif

}  // namespace

void setup() {
  Serial.begin(SERIAL_BAUD); Serial.setTimeout(50);
  pixel.begin(); pixel.setBrightness(LED_BRIGHT); pixel.clear(); pixel.show(); strip_ok = true;
  oled_ok = oled_begin();
  if (oled_ok) { oled.setTextWrap(false); boot_animation(); }
  line.reserve(MAX_FRAME);
#if defined(REWATCH_HAS_WIFI)
  WiFi.mode(WIFI_STA); WiFi.setSleep(false);
  mqtt.setServer(REWATCH_MQTT_HOST, REWATCH_MQTT_PORT);
  mqtt.setCallback(on_mqtt); mqtt.setBufferSize(512);
#endif
}

void loop() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (!dropping_line && line.length()) apply_frame(line);
      line = ""; dropping_line = false; continue;
    }
    if (dropping_line) continue;
    if (line.length() >= MAX_FRAME) { line = ""; dropping_line = true; continue; }
    line += c;
  }
  net_loop(millis());
  led_loop();
  static uint32_t next_draw = 0;
  if (int32_t(millis() - next_draw) < 0) return;
  next_draw = millis() + REDRAW_MS;
  static char shown[128] = "";
  char sig[128]; screen_sig(sig, sizeof(sig));
  if (strcmp(sig, shown)) { strncpy(shown, sig, sizeof(shown) - 1); draw(); }
}
