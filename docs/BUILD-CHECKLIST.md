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
| Unit/API/regressions | `.venv/bin/python -m pytest -o addopts='' -q --disable-warnings` | `259 passed, 141 warnings, 139 subtests passed in 0.83s` |
| Python lint | `.venv/bin/ruff check . --select F` | `All checks passed!` |
| Shell syntax | `bash -n start.sh tools/node-install.sh demo/run.sh` | Exit 0 |
| JavaScript syntax | `node --check` for every production/demo asset JS file | Exit 0 |
| Chromium integration | `.venv/bin/python tests/browser_demo.py` | `PASS browser integration (51.6s); own server stopped` |
| C3 parser/framing | `python3 firmware/tests/check_indicator.py` | `C3 parser/framing regression checks passed` |
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
The workflow YAML was separately parsed; read-only permissions, seven steps and
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
