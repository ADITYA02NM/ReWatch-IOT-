#!/usr/bin/env python3
"""Host regression check of the actual C3 parsers/framing, not a hardware test.

Run after the C3 PlatformIO build: python3 firmware/tests/check_indicator.py
Requires g++; generated files stay in the ignored C3 .pio directory.
"""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1] / "esp32-c3-indicator"
SOURCE = (ROOT / "src/main.cpp").read_text()


def block(start: str) -> str:
    """Extract one balanced C++ block from the firmware for this narrow test."""
    begin = SOURCE.index(start)
    opening = SOURCE.index("{", begin)
    depth = 1
    end = opening + 1
    while depth:
        depth += (SOURCE[end] == "{") - (SOURCE[end] == "}")
        end += 1
    return SOURCE[begin:end]


declarations = SOURCE[SOURCE.index("enum class Band"):SOURCE.index("// ── colour rails")]
program = r'''
#include <ArduinoJson.h>
#include <string>
#include <cstring>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cassert>
#include <iostream>
using String = std::string;
using std::isfinite;
constexpr int OLED_W = 128;
constexpr uint32_t LINK_TIMEOUT_MS = 3000;
uint32_t clock_ms = 100;
uint32_t millis() { return clock_ms; }
struct {
  std::string input;
  size_t pos = 0;
  int available() { return pos < input.size(); }
  char read() { return input[pos++]; }
} Serial;
'''
program += declarations
program += block("Band parse_band(")
program += block("bool link_lost(")
program += block("void apply_frame(")
program += block("void apply_state(")
program += "void receive(const std::string &input) { Serial.input = input; Serial.pos = 0;\n"
program += block("while (Serial.available()") + "\n}\n"
program += r'''
int main() {
  assert(link_lost());
  const std::string valid = R"({"score":72,"band":"RED","open":1,"cd":94,"nodes":"1111"})";
  receive(valid + "\r\n");
  assert(g.have_data && g.score == 72 && g.band == Band::Red);
  assert(g.cd == 94 && std::string(g.nodes) == "1111");
  clock_ms = 200;
  for (const auto &bad : {"{}", "[]", "not JSON", "{\"score\":101,\"band\":\"GREEN\"}",
                         "{\"score\":1,\"band\":42}"}) {
    receive(std::string(bad) + "\n");
    assert(g.last_rx == 100 && g.score == 72);
  }
  // An oversized line's valid-looking JSON suffix must not be accepted.
  receive(std::string(MAX_FRAME + 1, 'x') + valid + "\n");
  assert(g.last_rx == 100);
  receive(valid.substr(0, 20));
  assert(g.last_rx == 100);
  receive(valid.substr(20) + "\n");
  assert(g.last_rx == 200);
  // Maximum Python-escaped message: 40 supplementary Unicode code points.
  std::string unicode;
  for (int i = 0; i < 40; i++) unicode += R"(\ud83d\ude00)";
  clock_ms = 300;
  receive("{\"score\":0,\"band\":\"BLUE\",\"msg\":\"" + unicode + "\"}\n");
  assert(g.last_rx == 300 && g.band == Band::Blue);
  assert(std::string(g.nodes) == "0000");
  receive("{\"score\":1,\"band\":\"unknown\",\"nodes\":\"1\"}\n");
  assert(g.band == Band::Unknown && std::string(g.nodes) == "0000");
  apply_state(R"({"score":72.6,"band":"PURPLE","incident":{"state":"open","remaining":0}})");
  assert(g.score == 73 && g.band == Band::Purple && g.open == 1 && g.cd == 0);
  clock_ms = 3300;
  assert(!link_lost());
  clock_ms = 3301;
  assert(link_lost());
  std::cout << "C3 parser/framing regression checks passed\n";
}
'''
build = ROOT / ".pio/protocol-check"
build.mkdir(parents=True, exist_ok=True)
cpp = build / "check.cpp"
binary = build / "check"
cpp.write_text(program)
subprocess.run([
    "g++", "-std=c++11", "-Wall", "-Wextra", "-I",
    str(ROOT / ".pio/libdeps/esp32-c3-devkitm-1/ArduinoJson/src"),
    str(cpp), "-o", str(binary),
], check=True)
subprocess.run([str(binary)], check=True)
