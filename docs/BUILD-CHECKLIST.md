# Video submission preparation

Scope: runnable, explicitly simulated laptop demonstration now; hardware setup and
validation later. ULTRON and VoidMain are read-only references. No credentials in Git.

## Checklist

- [x] Confirm scope and GitHub destination with owner.
- [x] Inspect demo, dashboard, firmware, installer and repository configuration.
- [x] Add regression tests for replay timing, 20-second acknowledgement and SMTP results.
- [x] Fix demo: discovery at 20 s, spike at 30 s; refresh reconnects, explicit Replay resets.
- [x] Add demo-only Black Hat controls and clear simulation labels.
- [x] Fix SMTP integration without storing credentials or blocking the event loop.
- [x] Preserve manual/debug pages and align firmware with dashboard protocol.
- [x] Harden installer preview/cancellation and validate inputs.
- [x] Write README, hardware guide, SVGs, three-paragraph story and security notes.
- [x] Add trusted typed MQTT capabilities, ten-device demo and shared topology UI.
- [x] Retain report evidence across Replay/restart and generate five-minute summaries.
- [x] Run unit/integration/browser checks and review security/code.
- [x] Check ignored files, secrets, links and Git diff.
- [x] Commit and push to https://github.com/ADITYA02NM/ReWatch-IOT-.git.

## Acceptance checks

- First dashboard connection starts the shared demo; only explicit Replay resets it.
- Refresh, including Ctrl+Shift+R, and ordinary reconnect preserve the current scene.
- Ten devices are discovered at 20 s; AC scenario starts 10 s later.
- Demo RED deadline is 20 s; production default remains 120 s.
- ACK cancels automatic action; no ACK triggers PURPLE and a simulated setpoint reset.
- SMTP preview, server acceptance and failure are distinct; acceptance is not delivery.
- Demo controls are absent from production; manual/debug pages stay available.
- No hardware validation claims, fake photographs or exposed SMTP password.

## Verification record

Recorded on **21 October 2026**, Linux, Python 3.14.7. These are local results,
not a claim that GitHub-hosted CI or a complete three-Pi deployment was tested.

| Check | Command / evidence | Result |
| --- | --- | --- |
| Unit/API/regressions | `.venv/bin/python -m pytest -o addopts='' -q --disable-warnings` | `259 passed, 141 warnings, 139 subtests passed in 1.21s` |
| Python lint | `.venv/bin/ruff check . --select F` | `All checks passed!` |
| Shell syntax | `bash -n start.sh tools/node-install.sh demo/run.sh` | Exit 0 |
| JavaScript syntax | `node --check` for every production/demo asset JS file | Exit 0, 9 files |
| Chromium integration | `.venv/bin/python tests/browser_demo.py` | `PASS browser integration (52.2s); own server stopped` |
| C3 parser/framing | `python3 firmware/tests/check_indicator.py` | `C3 parser/framing regression checks passed` |
| Clean-cache parser dependency | Isolated tracked-source copy, Python 3.11.15, PlatformIO 6.1.18, empty project `.pio/libdeps` and separate empty `PLATFORMIO_CORE_DIR`; commands below | ArduinoJson 7.4.3 installed; parser passed; `platformio.ini` unchanged |
| C3 compilation | `pio run -d firmware/esp32-c3-indicator -e esp32-c3-devkitm-1 -e esp32-c3-uart` | `2 succeeded` |
| WROOM credential-free compilation | `pio run -d firmware/esp32-wroom-rig -e compile-check` | `1 succeeded` |
| Documentation | Local Markdown destinations and XML parsing | 35 links, zero missing; 10 SVGs parsed |
| Whitespace | `git diff --check` | Exit 0 |

Browser checks exercise real login, no early discovery, ten devices, plug power,
refresh continuity, preview-only mail, synthetic feed/firmware events, ACK and
no-ACK/PURPLE behavior, persisted five-hour reports, manual/debug and 390px mobile
layout/navigation with no JavaScript errors. The browser runner uses a temporary
isolated server and databases, never the user's port 8080.

The 141 pytest warnings are legacy aiohttp string application-key conventions
and test-time application mutation warnings. No type checker is configured.
WROOM's normal `esp32dev` build requires the operator's ignored `secrets.h`;
building all environments without it fails, by design. No placeholder credentials
were added to make that environment appear configured.

### Security review and SAST

Independent reviews identified and regression tests now cover: trusted-device
observation starvation, mail test/result feedback, unsafe nftables source input,
installer failure exit codes, real firewall execution from a simulated response,
and missing detection counts in demo summaries. Both last review findings were
reproduced with failing tests before correction.

Semgrep 1.181.0 ran from an isolated Python 3.11 environment because the system
MCP installation lacked `rich`. Community rules flag the conditional `ws://`
fallbacks in four production/demo live/debug scripts: these select `wss://` on
HTTPS, while localhost HTTP and the documented initial lab HTTP mode use WS.
Two NaN-injection matches are false positives on `bool(session-id and session
validation)`, not numeric input conversion. Bash arithmetic/case parsing produced
two partial-parsing warnings; `bash -n` and installer regressions passed. No rule
suppression was added, and this is **not** a clean or exhaustive security scan.
Mutable GitHub Action references were replaced by upstream-verified commit SHAs.
Final SAST output: **83 files scanned, six findings, two partial-parse warnings**.
The workflow YAML was separately parsed; read-only permissions, eight steps and
immutable Action references were checked. All 75 staged paths were inspected by
artifact/credential-pattern checks: zero forbidden artifacts or matches; locally
configured SMTP passwords, if present, were also compared without printing them.

### Evidence boundaries

- Real SMTP inbox delivery, all three Pis, radio routing/capture coverage,
  electrical safety and physical OLED/LED appearance remain unverified.
- The connected C3 UART upload succeeded earlier in this session; compilation
  and upload do not establish visible display behavior.
- Before the local demo restart, its available 17 events, 600 samples and one
  incident were saved and imported into the ignored evidence database. Evidence
  already discarded by an older in-memory run cannot be reconstructed.
- Secrets, local databases, virtual environments and firmware builds must remain
  ignored. Publication is tracked in Git history and the remote branch.

### Publication

The implementation commit `4cba845` and history-preserving merge `f688f53` were
pushed to `origin/main` without force. Remote SHA equality was verified after
that push; both previously independent root histories are retained. The local
dashboard is running at `http://localhost:8080` with its ignored recording
configuration, alongside the optional USB C3 bridge. No SMTP sends were enabled.
The dashboard-specific requirements entry now delegates to the canonical root
requirements, avoiding a stale, invalid alternate WebAuthn pin.
The initial GitHub run exposed two installer tests that assumed the agent's
pre-created `/tmp/opencode` directory. Their temporary-directory fixtures now
use the standard portable temporary location; no installer behavior was weakened.

The subsequent [CI run 39487021837](https://github.com/ADITYA02NM/ReWatch-IOT-/actions/runs/39487021837)
at `f59d16c` passed unit/API tests but failed the host firmware parser compilation:
`ArduinoJson.h` was absent on the clean runner. Local cached PlatformIO libraries
had masked the missing setup. CI now installs only the parser's library before
the unchanged lint/syntax/parser checks:

```sh
python -m pip install platformio==6.1.18
python -m platformio pkg install \
  --project-dir firmware/esp32-c3-indicator \
  --environment esp32-c3-devkitm-1 \
  --library "bblanchon/ArduinoJson@7.4.3" \
  --no-save
python firmware/tests/check_indicator.py
```

These commands were checked against current PlatformIO documentation and executed
in a new virtual environment and tracked-source copy with no existing project or
PlatformIO Core dependency cache. Before installation the same parser check
failed with the missing-header error; afterward it printed
`C3 parser/framing regression checks passed`. No full embedded toolchain download
is needed for this host check, and no firmware configuration or assertions changed.
The local checks in the table were rerun for this workflow fix; firmware builds
used existing local build caches. Hosted success must be verified for the exact
pushed commit, not inferred from these local results.

## Six-panel operator dashboard (2026-10-21)

The dashboard is now a single non-scrolling 3×2 grid at 1366×768 (also verified
at 390×844, one panel at a time through the footer switcher):

| # | Panel | What it does |
|---|---|---|
| 01 | Risk | Semi-circular speedometer on the left, big score on the right, history graph with a hover tooltip showing score, band and the alert active at that sample |
| 02 | Alerts | Incident ring with ACK countdown, per-alert **Acknowledge** (targets that alert's `incident` id), paginated feed |
| 03 | BlackBox | Schematic of the box internals — Core, Sentinel, Herald, ESP32 rig, USB-linked C3 — packet pulses on live events, lids open on detections |
| 04 | IoT connections | Radial map of enrolled/observed devices with reported IPs; selecting a node opens its details |
| 05 | Controls | Simulate (AC start/stop), Clear, Export .md, Refresh, OLED+LED preview, Mail test; demo adds Replay, Black Hat feed, Firmware drill |
| 06 | IoT details | Selected device evidence, firmware facts, capability-approved control forms |

New shared modules: `pi4-core/web/assets/risk.js` and `topology.js`. The demo
copies are generated by `tools/build_demo_web.py`, which fails if any expected
source fragment is missing, so production stays the single source of truth.

**Verification for this work**

- `.venv/bin/python tests/browser_demo.py` → `PASS browser integration (51.0s)`
  with all 13 sub-checks green, including fit-at-1366×768, 20-second discovery of
  ten devices, plug control, ACK before deadline, no-ACK → PURPLE, Replay
  evidence retention and the mobile single-panel layout.
- `.venv/bin/python -m pytest -o addopts='' -q --disable-warnings` → `259 passed,
  141 warnings, 139 subtests passed in 1.03s`; `.venv/bin/ruff check . --select F`
  → All checks passed; `node --check` clean on every generated JS file.

**Live SMTP drill (same day, user-confirmed)**

With credentials only in the ignored local `demo/.env`, five messages were
handed to Gmail and accepted by the SMTP server, and the user confirmed all
five arrived: test, RED alert, PURPLE no-response, resolved, and the 5-minute
system summary. The feed now reports "E-mail accepted by SMTP server (delivery
not confirmed) · <subject>" rather than claiming delivery.
