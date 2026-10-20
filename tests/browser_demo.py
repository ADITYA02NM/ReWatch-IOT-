"""Standalone, hardware-free browser integration test.

Run from any directory with the project's Playwright-enabled interpreter:
    .venv/bin/python tests/browser_demo.py

Starts only its own loopback demo subprocess; auth/evidence databases and server
logs are temporary. Never loads demo/.env or connects to an MQTT bridge.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path("/tmp/opencode")


@contextmanager
def isolated_demo():
    """Own a short-lived real aiohttp server, including cleanup on failure."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rewatch-browser-", dir=ARTIFACTS) as tmp:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        # Even an unusual OS ephemeral-port configuration must not select 8080.
        assert port != 8080, "Refusing to use existing demo port"
        env = os.environ.copy()
        env.update(DEMO_SEND_MAIL="0", DEMO_PASSKEY_PREVIEW="0",
                   DEMO_AUTO_SPIKE="0", DEMO_ACK_TIMEOUT_S="20")
        command = (
            "from pathlib import Path; import sys; from aiohttp import web; "
            "from demo.demo_server import create_app; "
            "port=int(sys.argv[1]); "
            "app=create_app(port=port,code='browser-test',auth_path=Path(sys.argv[2])); "
            "web.run_app(app,host='127.0.0.1',port=port,print=None)"
        )
        with (Path(tmp) / "server.log").open("w+") as log:
            process = subprocess.Popen(
                [sys.executable, "-c", command, str(port), str(Path(tmp) / "auth.db")],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            base = f"http://127.0.0.1:{port}"
            try:
                deadline = time.monotonic() + 15
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Isolated server exited before readiness")
                    try:
                        with urllib.request.urlopen(base + "/healthz", timeout=0.5) as response:
                            health = json.load(response)
                        assert health["simulation"] is True
                        assert health["mqtt"] is False
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Isolated server readiness timed out") from None
                        time.sleep(0.05)
                yield base
            except BaseException:
                log.flush()
                log.seek(0)
                print("\nIsolated server log:\n" + log.read(), file=sys.stderr)
                raise
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


class Dashboard:
    """Small page object: use accessible controls and stable IDs from the UI."""

    def __init__(self, page, base):
        self.page = page
        self.base = base

    def state(self):
        response = self.page.request.get(self.base + "/api/state")
        assert response.status == 200
        return response.json()

    def report(self):
        response = self.page.request.get(self.base + "/api/report?hours=5")
        assert response.status == 200
        return response.json()

    def wait_state(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while True:
            state = self.state()
            if predicate(state):
                return state
            if time.monotonic() >= deadline:
                raise AssertionError("Timed out awaiting demo state: " + repr(state))
            # API condition polling, not an arbitrary browser animation delay.
            time.sleep(0.1)

    def login(self):
        self.page.goto(self.base)
        self.page.get_by_role("button", name="Use access code", exact=True).click()
        self.page.get_by_role("textbox", name="Access code", exact=True).fill("browser-test")
        self.page.get_by_role("button", name="Enter", exact=True).click()
        expect(self.page.locator("#app")).to_be_visible()
        expect(self.page.locator("#conn")).to_have_text("LIVE")

    def click(self, selector):
        self.page.locator(selector).click()


def check(name):
    print("PASS " + name, flush=True)


def main():
    errors = []
    failures = []
    started = time.monotonic()
    with isolated_demo() as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1050})

            def observe(page):
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: errors.append(message.text)
                        if message.type == "error" else None)

            context.on("page", observe)
            page = context.new_page()
            page.set_default_timeout(10000)
            dashboard = Dashboard(page, base)
            options = context.request.get(base + "/api/demo-options").json()
            assert options["passkey_preview"] is False
            dashboard.login()
            assert dashboard.state()["simulation"] is True
            check("access-code login; passkey preview disabled")

            # Poll a real observable condition; no clock patches/test endpoints.
            # While the shared timeline is below 20s, neither API nor UI may
            # reveal devices. The real half-second simulation tick follows 20s.
            early_discovery = False

            def discovered(state):
                nonlocal early_discovery
                count = page.locator(".device-tile").count()
                if state["demo_elapsed"] < 20:
                    early_discovery |= bool(count or state["telemetry"])
                    return False
                return count == 10 and len(state["telemetry"]) == 10

            dashboard.wait_state(discovered, timeout=27)
            expect(page.locator(".device-tile")).to_have_count(10)
            if early_discovery:
                failures.append("Device tiles appeared before 20-second discovery")
                print("FAIL " + failures[-1], flush=True)
            else:
                check("no devices before 20 seconds")
            check("ten devices discovered at 20 seconds")

            dashboard.click('[data-device="lobby-plug"]')
            detail = page.get_by_role("complementary", name="Selected device")
            expect(detail.get_by_role("heading", name="Lobby plug")).to_be_visible()
            detail.get_by_label("power value", exact=True).select_option("false")
            with page.expect_response(lambda response: response.url == base + "/api/control") as request:
                detail.get_by_role("button", name="Request power", exact=True).click()
            assert request.value.status == 202
            assert request.value.json()["simulation"] is True
            expect(detail.locator(".device-evidence")).to_contain_text("power=false")
            assert dashboard.state()["telemetry"]["lobby-plug"]["power"] is False
            check("selected plug details visible; power Off requested and observed")

            # A spike makes temperature continuity distinguishable from a reset.
            dashboard.click("#c-spike")
            dashboard.wait_state(lambda s: s["telemetry"]["room1-ac"]["temp_c"] > 23)
            before = dashboard.state()
            page.reload()
            expect(page.locator("#conn")).to_have_text("LIVE")
            expect(page.locator(".device-tile")).to_have_count(10)
            after = dashboard.state()
            assert after["demo_elapsed"] >= before["demo_elapsed"]
            assert set(after["telemetry"]) == set(before["telemetry"])
            assert after["telemetry"]["room1-ac"]["temp_c"] > 23
            assert after["telemetry"]["lobby-plug"]["power"] is False
            assert after["history"][0][0] == before["history"][0][0]
            check("refresh preserves rooms, elevated temperature, controls, run timeline")

            dashboard.click("#c-mail")
            expect(page.locator("#feed")).to_contain_text("delivery disabled")
            dashboard.wait_state(lambda s: any(
                e["kind"] == "mail" and "Test message" in e["title"]
                and "delivery disabled" in e["title"] for e in s["events"]))
            state = dashboard.state()
            assert state["mail_status"] == "Preview only — delivery disabled"
            assert state["nodes"]["herald"]["last_ok"] is not True
            assert not any("E-mail sent" in e["title"] for e in state["events"])
            check("test e-mail is preview-only, never reported sent")

            dashboard.click("#c-blackhat")
            expect(page.locator("#c-blackhat")).to_have_attribute("aria-pressed", "true")
            assert dashboard.state()["briefing"] is True
            dashboard.click("#c-blackhat")
            expect(page.locator("#c-blackhat")).to_have_attribute("aria-pressed", "false")
            assert dashboard.state()["briefing"] is False
            dashboard.click("#c-firmware")
            expect(page.locator("#feed")).to_contain_text("firmware", ignore_case=True)
            check("Black Hat feed toggles; firmware demo produces event")

            # ACK within the real 20-second deadline, then a fresh no-ACK run.
            expect(page.locator("#ack")).to_be_enabled(timeout=25000)
            incident = dashboard.state()["state"]["incident"]
            assert incident["state"] == "open" and incident["remaining"] > 0
            dashboard.click("#ack")
            dashboard.wait_state(lambda s: (s["state"].get("incident") or {}).get("state") == "acked")
            acked_id = incident["id"]
            check("RED incident acknowledged before deadline")

            saved = dashboard.report()
            saved_ids = {event["id"] for event in saved["events"]}
            dashboard.click("#c-replay")
            dashboard.wait_state(lambda s: s["demo_elapsed"] < 5 and not s["telemetry"])
            assert saved_ids <= {event["id"] for event in dashboard.report()["events"]}
            dashboard.click("#c-spike")
            expect(page.locator("#ack")).to_be_enabled(timeout=25000)
            new_incident = dashboard.state()["state"]["incident"]
            assert new_incident["id"] != acked_id
            assert 0 < new_incident["remaining"] <= 20
            dashboard.wait_state(lambda s:
                s["state"]["band"] == "PURPLE"
                and s["state"]["incident"]["state"] == "auto"
                and s["telemetry"]["room1-ac"]["setpoint"] == 20
                and s["telemetry"]["room1-ac"]["power"] == "on"
                and any(e["kind"] == "command" and e.get("device") == "room1-ac"
                        and "20" in e["title"] for e in s["events"]), timeout=24)
            expect(page.locator("#bandword")).to_have_text("PURPLE")
            auto = dashboard.state()
            assert auto["telemetry"]["room1-ac"]["power"] == "on"
            assert auto["server_ts"] >= new_incident["deadline"]
            check("no ACK triggers PURPLE at deadline and simulated AC reset to 20")

            page.screenshot(path=str(ARTIFACTS / "rewatch-desktop.png"), full_page=True)
            page.get_by_role("link", name="Reports · 5h", exact=True).click()
            expect(page.locator("#h1")).to_contain_text("last 5 hours")
            expect(page.locator("#rows")).to_contain_text("delivery disabled")
            expect(page.locator("#incidents")).to_contain_text("acked")
            expect(page.locator("#incidents")).to_contain_text("auto")
            report = dashboard.report()
            assert report["simulation"] is True and report["hours"] == 5
            assert saved_ids <= {event["id"] for event in report["events"]}
            check("Reports · 5h displays persisted evidence after Replay")

            for path in ("/manual.html", "/debug.html"):
                response = page.goto(base + path)
                assert response.status == 200
                expect(page.locator("body")).to_be_visible()
            check("manual/debug return 200 and render without page errors")

            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(base)
            expect(page.locator("#conn")).to_have_text("LIVE")
            expect(page.locator(".device-tile")).to_have_count(10)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), \
                "Mobile dashboard has horizontal overflow"
            for name in ("Reports · 5h", "Manual", "Debug"):
                link = page.get_by_role("link", name=name, exact=True)
                expect(link).to_be_visible()
                box = link.bounding_box()
                assert box and box["x"] >= 0 and box["x"] + box["width"] <= 391
                link.click(trial=True)
            page.screenshot(path=str(ARTIFACTS / "rewatch-mobile.png"), full_page=True)
            assert not errors, "Browser JavaScript/console errors: " + repr(errors)
            check("390px mobile: no horizontal overflow; navigation accessible; no JS errors")
            context.close()
        finally:
            browser.close()
    assert not failures, "; ".join(failures)
    print(f"PASS browser integration ({time.monotonic() - started:.1f}s); own server stopped")


if __name__ == "__main__":
    main()
