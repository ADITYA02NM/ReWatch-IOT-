#!/usr/bin/env python3
"""ReWatch(Iot) Herald — Raspberry Pi 3 on switch port 4 + TP-Link TL-WN722N.

Herald is the messenger. It listens for incidents and e-mails the owner over
SMTP, sending *out of the TL-WN722N Wi-Fi interface* (source-bound to its
address), so an alert still leaves the house if the wired uplink is the thing
under attack.

Mails it sends
  RED     "Your ReWatch(Iot) system is RED" + 2-minute warning + Acknowledge link
  ACKED   confirmation that somebody took ownership
  PURPLE  "no response — ReWatch(Iot) acted automatically: <what it did>"
  RESOLVED back to normal
  TEST    on rewatch/mail/test (dashboard "Send test e-mail" button)

Every attempt is reported on rewatch/mail/<incident> so the dashboard shows
"e-mail delivered 21:43:07" or the SMTP error.
"""

from __future__ import annotations

import html
import queue
import signal
import smtplib
import ssl
import sys
import threading
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import rewatch as rw  # noqa: E402
from summary import ReportWindow  # noqa: E402

LOG = rw.setup_logging("rewatch.herald")

BAND_HEX = {"RED": "#e5322d", "PURPLE": "#9b3df0", "GREEN": "#1f9d55", "YELLOW": "#d9a400",
            "BLUE": "#2f6fe0"}


def _fmt(ts: float | None) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts or time.time()))


def compose(kind: str, d: dict, dash: str) -> tuple[str, str, str]:
    """(subject, text, html) for one message kind."""
    title = d.get("title") or "Critical threat"
    inc = d.get("id") or d.get("incident") or ""
    link = f"{dash.rstrip('/')}/?incident={inc}" if inc else dash
    seconds = max(1, round(float(d.get("ack_timeout", 120))))
    duration = (f"{seconds // 60} minute{'s' if seconds != 60 else ''}"
                if seconds % 60 == 0 else f"{seconds} second{'s' if seconds != 1 else ''}")
    if kind == "alert":
        band = "RED"
        subject = f"[ReWatch(Iot)] RED — {title}"
        lines = [
            "Your ReWatch(Iot) system is RED.",
            "",
            f"What happened : {title}",
            f"When         : {_fmt(d.get('ts'))}",
            f"Risk score   : {d.get('score', '?')}/100",
            "",
            f"If you don't do anything in {duration}, ReWatch(Iot) will "
            f"automatically take action: {d.get('planned_action') or 'escalate'}.",
            "",
            "Or go back to your system dashboard and click Acknowledge:",
            link,
        ]
    elif kind == "acked":
        band = "RED"
        subject = f"[ReWatch(Iot)] Acknowledged — {title}"
        lines = [f"Incident {inc} was acknowledged by {d.get('acked_by') or 'the operator'} "
                 f"at {_fmt(d.get('acked_ts'))}.", "", "The automatic response is cancelled.",
                 "Dashboard: " + link]
    elif kind == "auto":
        band = "PURPLE"
        action = (d.get("action") or {}).get("summary", "automated response")
        subject = "[ReWatch(Iot)] PURPLE — no response, automatic action taken"
        lines = ["Nobody acknowledged the alert in time, so it was treated as unauthorised.",
                 "", f"Incident     : {title}", f"Action taken : {action}",
                 f"At           : {_fmt((d.get('action') or {}).get('ts'))}", "",
                 "Dashboard: " + link]
    elif kind == "resolved":
        band = "GREEN"
        subject = f"[ReWatch(Iot)] Resolved — {title}"
        lines = [f"Incident {inc} is resolved. Everything is back to normal.", "",
                 "The last 5 hours: " + dash.rstrip("/") + "/reports.html"]
    elif kind == "summary":
        band = d.get("band", "BLUE")
        subject = f"[ReWatch(Iot)] 5-minute system summary — {band}"
        lines = ["System summary for the preceding five-minute window.",
                 f"Window       : {_fmt(d.get('from'))} – {_fmt(d.get('to'))}",
                 f"State fresh  : {d.get('state_received', False)}",
                 f"Risk         : {band} / {d.get('score', '?')} (peak {d.get('peak', '?')})",
                 f"Devices seen : {d.get('devices', 0)}",
                 f"Nodes seen   : {d.get('nodes_seen', 0)}",
                 f"Offline/stale: {', '.join(d.get('offline') or []) or 'none reported'}",
                 f"Detections   : {d.get('detections', 0)}",
                 f"Responses attempted: {d.get('responses', 0)}",
                 f"Incident     : {d.get('incident', 'none')}", "",
                 "These are observed/reported counts, not proof of complete network coverage.",
                 "The last 5 hours: " + dash.rstrip("/") + "/reports.html"]
        if d.get("simulation"):
            lines.insert(0, "SIMULATION — not physical network evidence.")
    else:
        band = "GREEN"
        subject = "[ReWatch(Iot)] Test e-mail"
        lines = ["This is a test from ReWatch(Iot) Herald.",
                 f"Sent at {_fmt(None)} via {d.get('via', 'SMTP')}.", "", "Dashboard: " + dash]

    text = "\n".join(lines) + "\n\n— ReWatch(Iot)\n"
    colour = BAND_HEX.get(band, "#333")
    body_html = "<br>".join(html.escape(x) if not x.startswith("http")
                            else f'<a href="{html.escape(x)}">{html.escape(x)}</a>' for x in lines)
    button = (f'<p><a href="{html.escape(link)}" style="display:inline-block;padding:12px 22px;'
              f'background:{colour};color:#fff;text-decoration:none;font-weight:700;'
              f'border-radius:6px">Open dashboard &amp; Acknowledge</a></p>'
              if kind == "alert" else "")
    page = (f'<div style="font-family:Segoe UI,Arial,sans-serif;max-width:560px">'
            f'<div style="border-left:6px solid {colour};padding:4px 16px">'
            f'<h2 style="margin:6px 0;color:{colour}">ReWatch(Iot) · {band}</h2>'
            f'<p style="font-size:15px;line-height:1.5">{body_html}</p>{button}</div>'
            f'<p style="color:#888;font-size:12px">ReWatch(Iot) · sent by Herald</p></div>')
    return subject, text, page


class Herald:
    def __init__(self) -> None:
        rw.load_env()
        self.host = rw.env("SMTP_HOST", "smtp.gmail.com")
        self.port = rw.env_int("SMTP_PORT", 587)
        self.user = rw.env("SMTP_USER")
        self.password = rw.env("SMTP_PASS")
        self.sender = rw.env("SMTP_FROM", self.user)
        self.to = [x.strip() for x in rw.env("ALERT_TO", "").split(",") if x.strip()]
        self.iface = rw.env("SMTP_IFACE", "wlan1")
        self.dash = rw.env("DASHBOARD_URL", "https://rewatch.local")
        self.q: queue.Queue = queue.Queue()
        self.summary = ReportWindow()
        self.sent: set[tuple[str, str]] = set()
        self.last = {"ok": None, "ts": None, "error": ""}
        self.bus = rw.Bus("herald", subscriptions=[rw.topic("alert", "+"),
                                                   rw.topic("incident", "+"),
                                                   rw.topic("mail", "test"), rw.topic("threat", "state"),
                                                   rw.topic("health", "+"), rw.topic("detect", "#"),
                                                   rw.topic("action", "+")],
                          on_message=self.on_msg, heartbeat_info=self.hb)

    def hb(self) -> dict:
        return {"role": "smtp alerts", "iface": self.iface, "iface_ip": rw.iface_ip(self.iface),
                "smtp": f"{self.host}:{self.port}", "configured": bool(self.user and self.password and self.to),
                "last_ok": self.last["ok"], "last_ts": self.last["ts"],
                "last_error": self.last["error"][:120]}

    def on_msg(self, t: str, d) -> None:
        if not isinstance(d, dict):
            return
        self.summary.observe(t, d, rw.now())
        if t == rw.topic("mail", "test"):
            self.q.put(("test", {**d, "id": "test", "via": self.iface}))
        elif t.startswith(rw.topic("alert")):
            self.q.put(("alert", d))
        elif t.startswith(rw.topic("incident")):
            st = d.get("state")
            if st in ("acked", "auto", "resolved"):
                self.q.put((st, d))

    def send(self, kind: str, d: dict) -> None:
        inc = d.get("id", "")
        key = (inc, kind)
        if kind != "test" and key in self.sent:
            return
        subject, text, page = compose(kind, d, self.dash)
        result = {"id": inc, "kind": kind, "subject": subject, "to": self.to, "ts": rw.now(),
                  "via": self.iface}
        if not (self.user and self.password and self.to):
            result.update(ok=False, error="SMTP not configured (SMTP_USER / SMTP_PASS / ALERT_TO)")
            LOG.error(result["error"])
        else:
            msg = EmailMessage()
            msg["Subject"], msg["From"], msg["To"] = subject, self.sender, ", ".join(self.to)
            msg["Date"], msg["Message-ID"] = formatdate(localtime=True), make_msgid("rewatch")
            if kind == "alert":
                msg["X-Priority"] = "1"
            msg.set_content(text)
            msg.add_alternative(page, subtype="html")
            src = rw.iface_ip(self.iface)
            try:
                ctx = ssl.create_default_context()
                addr = (src, 0) if src else None
                if self.port == 465:
                    s = smtplib.SMTP_SSL(self.host, self.port, timeout=20, context=ctx,
                                         source_address=addr)
                else:
                    s = smtplib.SMTP(self.host, self.port, timeout=20, source_address=addr)
                    s.starttls(context=ctx)
                with s:
                    s.login(self.user, self.password)
                    refused = s.send_message(msg)
                result.update(ok=not bool(refused), src_ip=src)
                if refused:
                    result["error"] = "SMTP rejected one or more recipients"
                LOG.info("mail '%s' -> %s (via %s)", subject, self.to, src or "default route")
            except (OSError, smtplib.SMTPException) as e:
                error = ("SMTP authentication rejected; check the new app password"
                         if isinstance(e, smtplib.SMTPAuthenticationError)
                         else f"SMTP transport failed ({type(e).__name__}); check host, port and connectivity")
                result.update(ok=False, error=error)
                LOG.error("%s", error)
        if result["ok"] and kind != "test":
            self.sent.add(key)
            if len(self.sent) > 4096:
                self.sent = {key}
        self.last = {"ok": result["ok"], "ts": result["ts"], "error": result.get("error", "")}
        # Results must never match the mail/test request subscription.
        self.bus.publish(rw.topic("mail", "result", inc or "test"), result)

    def run(self) -> None:
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())

        def worker():
            while True:
                kind, d = self.q.get()
                for attempt in range(3):
                    try:
                        self.send(kind, d)
                        break
                    except Exception:  # noqa: BLE001
                        LOG.exception("send crashed (attempt %d)", attempt + 1)
                        time.sleep(3)

        threading.Thread(target=worker, daemon=True).start()
        LOG.info("herald up — %s:%s via %s -> %s", self.host, self.port, self.iface, self.to)
        while not stop.wait(1):
            report = self.summary.poll(rw.now())
            if report:
                self.q.put(("summary", report))
        self.bus.stop()


if __name__ == "__main__":
    Herald().run()
