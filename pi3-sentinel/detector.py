#!/usr/bin/env python3
"""ReWatch Sentinel — Raspberry Pi 3 on switch port 2 (detection + logging).

Three jobs, one process:

1. **Network detection** (scapy, promiscuous on eth0)
   * TCP SYN / connect port scans (nmap -sS / -sT / -sV)   -> detect/portscan
   * UDP port scans (nmap -sU)                               -> detect/portscan
   * ARP host-discovery sweeps (nmap -sn on the LAN)         -> detect/arpsweep
   * ICMP ping sweeps                                        -> detect/pingsweep
   * packet floods from a single source                      -> detect/flood
   * a MAC address never seen before                         -> detect/newdevice

2. **IoT telemetry anomaly detection** (MQTT rewatch/iot/+/telemetry)
   * per-device profile (AC units: normal band, setpoint drift, rate of change)
   * publishes a *condition* on detect/anomaly/<device>: ok | warn | critical
   * a device that stops reporting                         -> detect/device-offline

3. **Evidence logging to the pen drive** (USB, mounted at /mnt/rewatch-usb)
   * every message on rewatch/# -> bus.jsonl, detections -> events.jsonl,
     one folder per day. Falls back to /var/log/rewatch if the stick is missing
     and says so in its heartbeat (the dashboard shows "USB: missing").

Nothing in here is simulated. If no packets arrive, nothing is reported.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import rewatch as rw  # noqa: E402

LOG = rw.setup_logging("rewatch.sentinel")


# ═════════════════════════════════════════════════════════════════════════════
# Network scan detection (pure logic — fed by the sniffer, unit-tested alone)
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class ScanConfig:
    window_s: float = 10.0
    tcp_ports: int = 12          # distinct (dst, port) SYNs from one source
    udp_ports: int = 15
    arp_targets: int = 12        # distinct who-has targets from one source
    icmp_targets: int = 8
    flood_pps: float = 400.0     # packets/second from one source, over 2 s
    cooldown_s: float = 30.0     # one event per source per kind per cooldown


class ScanDetector:
    """Sliding-window counters per source. Returns detection events."""

    def __init__(self, cfg: ScanConfig | None = None, ignore: set[str] | None = None) -> None:
        self.cfg = cfg or ScanConfig()
        self.ignore = ignore or set()
        self._tcp: dict[str, deque] = defaultdict(deque)   # src -> (ts, dst, port)
        self._udp: dict[str, deque] = defaultdict(deque)
        self._arp: dict[str, deque] = defaultdict(deque)   # src -> (ts, target)
        self._icmp: dict[str, deque] = defaultdict(deque)
        self._rate: dict[str, deque] = defaultdict(deque)  # src -> ts
        self._last: dict[tuple[str, str], float] = {}

    @staticmethod
    def _trim(q: deque, horizon: float) -> None:
        while q and q[0][0] < horizon:
            q.popleft()

    def _cool(self, kind: str, src: str, t: float) -> bool:
        k = (kind, src)
        if t - self._last.get(k, 0.0) < self.cfg.cooldown_s:
            return False
        self._last[k] = t
        return True

    def feed(self, proto: str, src: str, dst: str = "", port: int = 0,
             t: float | None = None) -> list[dict]:
        """proto: tcp-syn | udp | arp-req | icmp-echo | any"""
        if not src or src in self.ignore:
            return []
        t = rw.now() if t is None else t
        out: list[dict] = []
        c = self.cfg

        # flood (every packet counts)
        rq = self._rate[src]
        rq.append((t,))
        while rq and rq[0][0] < t - 2.0:
            rq.popleft()
        if len(rq) / 2.0 >= c.flood_pps and self._cool("flood", src, t):
            out.append(rw.make_event(
                "flood", "critical", f"Packet flood from {src} ({len(rq) // 2} pkt/s)",
                src=src, detail={"pps": len(rq) // 2}))

        if proto == "tcp-syn":
            q = self._tcp[src]
            q.append((t, dst, port))
            self._trim(q, t - c.window_s)
            ports = {(d, p) for _, d, p in q}
            if len(ports) >= c.tcp_ports and self._cool("tcp", src, t):
                hosts = sorted({d for d, _ in ports})
                sample = sorted({p for _, p in ports})[:12]
                out.append(rw.make_event(
                    "portscan", "high",
                    f"TCP port scan from {src} — {len(ports)} ports on {len(hosts)} host(s)",
                    src=src, target=", ".join(hosts[:4]),
                    detail={"proto": "tcp", "ports": sample, "count": len(ports),
                            "hosts": hosts[:8], "tool_hint": "nmap -sS/-sT"}))
        elif proto == "udp":
            q = self._udp[src]
            q.append((t, dst, port))
            self._trim(q, t - c.window_s)
            ports = {(d, p) for _, d, p in q}
            if len(ports) >= c.udp_ports and self._cool("udp", src, t):
                out.append(rw.make_event(
                    "portscan", "high", f"UDP port scan from {src} — {len(ports)} ports",
                    src=src, target=dst, detail={"proto": "udp", "count": len(ports),
                                                 "tool_hint": "nmap -sU"}))
        elif proto == "arp-req":
            q = self._arp[src]
            q.append((t, dst))
            self._trim(q, t - c.window_s)
            targets = {d for _, d in q}
            if len(targets) >= c.arp_targets and self._cool("arp", src, t):
                out.append(rw.make_event(
                    "arpsweep", "medium",
                    f"Host-discovery sweep from {src} — {len(targets)} addresses probed",
                    src=src, detail={"count": len(targets), "tool_hint": "nmap -sn / arp-scan"}))
        elif proto == "icmp-echo":
            q = self._icmp[src]
            q.append((t, dst))
            self._trim(q, t - c.window_s)
            targets = {d for _, d in q}
            if len(targets) >= c.icmp_targets and self._cool("icmp", src, t):
                out.append(rw.make_event(
                    "pingsweep", "medium", f"Ping sweep from {src} — {len(targets)} hosts",
                    src=src, detail={"count": len(targets)}))
        return out


class DeviceRegistry:
    """MAC addresses seen on the LAN. Learns for LEARN_S after first start,
    then anything new is an event. Persisted next to the logs."""

    def __init__(self, path: Path, learn_s: float = 300.0) -> None:
        self.path = path
        self.known: dict[str, dict] = {}
        self.learn_until = 0.0
        if path.is_file():
            try:
                blob = json.loads(path.read_text())
                self.known = blob.get("known", {})
                self.learn_until = blob.get("learn_until", 0.0)
            except (OSError, ValueError):
                pass
        if not self.known:
            self.learn_until = rw.now() + learn_s
        self._dirty = False

    def see(self, mac: str, ip: str) -> dict | None:
        mac = mac.lower()
        if mac in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"):
            return None
        t = rw.now()
        if mac in self.known:
            rec = self.known[mac]
            if rec.get("ip") != ip and ip and ip != "0.0.0.0":
                rec["ip"] = ip
                self._dirty = True
            rec["last"] = t
            return None
        self.known[mac] = {"ip": ip, "first": t, "last": t}
        self._dirty = True
        if t < self.learn_until:
            LOG.info("learned device %s %s", mac, ip)
            return None
        return rw.make_event("newdevice", "low", f"New device on the LAN — {mac} ({ip})",
                             src=ip, detail={"mac": mac, "ip": ip})

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            self.path.write_text(json.dumps({"known": self.known, "learn_until": self.learn_until}))
            self._dirty = False
        except OSError:
            pass


# ═════════════════════════════════════════════════════════════════════════════
# IoT anomaly detection (pure logic)
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class AcProfile:
    normal_min: float = 16.0
    normal_max: float = 26.0
    warn_drift: float = 4.0        # |temp - setpoint| above this -> warn
    crit_temp_hi: float = 32.0     # at or above -> critical
    crit_temp_lo: float = 10.0
    crit_drift: float = 10.0
    crit_hold_s: float = 2.0       # critical must hold this long (no single-sample spikes)
    rate_warn: float = 2.5         # deg C per second


@dataclass
class DeviceState:
    level: str = "ok"
    reason: str = ""
    last_ts: float = 0.0
    last_temp: float | None = None
    crit_since: float | None = None
    last_pub: float = 0.0
    history: deque = field(default_factory=lambda: deque(maxlen=60))
    offline: bool = False
    info: dict = field(default_factory=dict)


class AnomalyDetector:
    def __init__(self, profile: AcProfile | None = None) -> None:
        self.p = profile or AcProfile()
        self.devices: dict[str, DeviceState] = {}

    def feed(self, tel: dict, t: float | None = None) -> dict | None:
        """Returns a condition dict when the level changes (or every 5 s while
        not ok) — otherwise None."""
        dev = str(tel.get("device") or "")
        if not dev:
            return None
        try:
            temp = float(tel.get("temp_c"))
        except (TypeError, ValueError):
            return None
        sp = tel.get("setpoint")
        sp = float(sp) if isinstance(sp, (int, float)) else None
        t = rw.now() if t is None else t
        st = self.devices.setdefault(dev, DeviceState())
        first = st.last_ts == 0.0 and st.last_temp is None
        st.info = {k: tel.get(k) for k in ("room", "kind", "ip", "setpoint", "power")}
        p = self.p

        rate = 0.0
        if st.last_temp is not None and t > st.last_ts:
            rate = (temp - st.last_temp) / max(t - st.last_ts, 0.25)
        st.last_temp, st.last_ts, st.offline = temp, t, False
        st.history.append((t, temp))

        drift = abs(temp - sp) if sp is not None else 0.0
        crit = temp >= p.crit_temp_hi or temp <= p.crit_temp_lo or drift >= p.crit_drift
        if crit:
            if st.crit_since is None:
                st.crit_since = t
        else:
            st.crit_since = None

        if crit and t - st.crit_since >= p.crit_hold_s:
            level = "critical"
            reason = (f"{temp:.1f} °C — critical (setpoint {sp:.0f} °C)" if sp is not None
                      else f"{temp:.1f} °C — critical")
        elif crit or temp > p.normal_max or temp < p.normal_min or drift > p.warn_drift \
                or abs(rate) >= p.rate_warn:
            level = "warn"
            if abs(rate) >= p.rate_warn:
                reason = f"{temp:.1f} °C — changing {rate:+.1f} °C/s"
            else:
                reason = f"{temp:.1f} °C — outside normal {p.normal_min:.0f}–{p.normal_max:.0f} °C"
        else:
            level, reason = "ok", f"{temp:.1f} °C — normal"

        changed = level != st.level or first
        st.level, st.reason = level, reason
        if changed or (level != "ok" and t - st.last_pub >= 5.0):
            st.last_pub = t
            return {
                "device": dev, "level": level, "reason": reason, "temp_c": temp,
                "setpoint": sp, "rate": round(rate, 2), "room": st.info.get("room"),
                "kind": st.info.get("kind"), "active": level != "ok", "ts": t,
                "changed": changed,
            }
        return None

    def sweep_offline(self, timeout_s: float = 15.0, t: float | None = None) -> list[dict]:
        t = rw.now() if t is None else t
        out = []
        for dev, st in self.devices.items():
            if not st.offline and st.last_ts and t - st.last_ts > timeout_s:
                st.offline = True
                out.append(rw.make_event(
                    "device-offline", "low",
                    f"{st.info.get('room') or dev} stopped reporting",
                    device=dev, detail={"silent_s": round(t - st.last_ts)}))
        return out


# ═════════════════════════════════════════════════════════════════════════════
# Pen-drive logger
# ═════════════════════════════════════════════════════════════════════════════
class UsbLogger:
    def __init__(self, mount: Path, fallback: Path) -> None:
        self.mount, self.fallback = mount, fallback
        self._lock = threading.Lock()
        self.bytes = 0
        self.lines = 0

    @property
    def on_usb(self) -> bool:
        return os.path.ismount(self.mount)

    def root(self) -> Path:
        base = (self.mount / "rewatch") if self.on_usb else self.fallback
        d = base / time.strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write(self, name: str, obj: dict) -> None:
        line = json.dumps(obj, separators=(",", ":")) + "\n"
        with self._lock:
            try:
                with open(self.root() / name, "a", encoding="utf-8") as f:
                    f.write(line)
                self.bytes += len(line)
                self.lines += 1
            except OSError as e:
                LOG.warning("log write failed: %s", e)

    def free_mb(self) -> float | None:
        try:
            st = os.statvfs(self.mount if self.on_usb else self.fallback)
            return round(st.f_bavail * st.f_frsize / 1e6, 1)
        except OSError:
            return None


# ═════════════════════════════════════════════════════════════════════════════
# Wiring it together
# ═════════════════════════════════════════════════════════════════════════════
class Sentinel:
    def __init__(self) -> None:
        rw.load_env()
        self.iface = rw.env("SENTINEL_IFACE", "eth0")
        self.logger = UsbLogger(Path(rw.env("SENTINEL_USB_MOUNT", "/mnt/rewatch-usb")),
                                Path(rw.env("SENTINEL_FALLBACK_DIR", "/var/log/rewatch")))
        ignore = {ip.strip() for ip in rw.env("SENTINEL_IGNORE_IPS", "").split(",") if ip.strip()}
        self.own_ip = rw.iface_ip(self.iface) or rw.local_ip()
        ignore.add(self.own_ip)
        self.scan = ScanDetector(ScanConfig(
            tcp_ports=rw.env_int("SCAN_TCP_PORTS", 12),
            arp_targets=rw.env_int("SCAN_ARP_TARGETS", 12),
            flood_pps=rw.env_float("SCAN_FLOOD_PPS", 400.0)), ignore=ignore)
        reg_dir = Path(rw.env("SENTINEL_STATE_DIR", "/var/lib/rewatch"))
        reg_dir.mkdir(parents=True, exist_ok=True)
        self.registry = DeviceRegistry(reg_dir / "known_devices.json",
                                       rw.env_float("SENTINEL_LEARN_S", 300))
        self.anomaly = AnomalyDetector(AcProfile(
            normal_max=rw.env_float("AC_NORMAL_MAX", 26.0),
            crit_temp_hi=rw.env_float("AC_CRITICAL_C", 32.0)))
        self.pkts = 0
        self.sniffing = False
        self.detections = 0
        self.bus = rw.Bus("sentinel", subscriptions=[rw.topic("#")],
                          on_message=self.on_bus, heartbeat_info=self.hb)

    def hb(self) -> dict:
        return {
            "role": "detection + logging",
            "usb": self.logger.on_usb,
            "usb_free_mb": self.logger.free_mb(),
            "logged_lines": self.logger.lines,
            "sniffing": self.sniffing,
            "iface": self.iface,
            "pkts": self.pkts,
            "detections": self.detections,
            "devices_known": len(self.registry.known),
        }

    def emit(self, ev: dict) -> None:
        self.detections += 1
        LOG.warning("DETECT %s: %s", ev["kind"], ev["title"])
        self.bus.publish(rw.topic("detect", ev["kind"]), ev)
        # events.jsonl is written by on_bus when the message comes back

    # every message on the bus is evidence
    def on_bus(self, t: str, d) -> None:
        if not isinstance(d, dict):
            return
        rec = {"topic": t, "rx": rw.now(), "d": d}
        if t.endswith("/telemetry"):
            self.logger.write("telemetry.jsonl", rec)
            cond = self.anomaly.feed(d)
            if cond:
                if cond["changed"]:
                    LOG.info("anomaly %s -> %s (%s)", cond["device"], cond["level"], cond["reason"])
                self.bus.publish(rw.topic("detect", "anomaly", cond["device"]), cond)
            return
        if t.startswith(rw.topic("health")):
            return  # heartbeats would drown the log; state changes are in threat/state
        if t == rw.topic("threat", "state"):
            return
        name = "events.jsonl" if "/detect/" in t or "/alert/" in t or "/action/" in t \
            or "/incident/" in t else "bus.jsonl"
        self.logger.write(name, rec)

    # ── sniffer ─────────────────────────────────────────────────────────────
    def sniff(self) -> None:
        try:
            from scapy.all import ARP, ICMP, IP, TCP, UDP, Ether, sniff  # type: ignore
        except ImportError:
            LOG.error("scapy not installed — network detection disabled (pip install scapy)")
            return
        if os.geteuid() != 0:
            LOG.error("not root — cannot sniff; network detection disabled")
            return

        def handle(pkt) -> None:
            self.pkts += 1
            evs: list[dict] = []
            if pkt.haslayer(ARP):
                a = pkt[ARP]
                if a.psrc and a.psrc != "0.0.0.0":
                    nd = self.registry.see(a.hwsrc, a.psrc)
                    if nd:
                        evs.append(nd)
                if a.op == 1:
                    evs += self.scan.feed("arp-req", a.psrc, a.pdst)
            elif pkt.haslayer(IP):
                ip = pkt[IP]
                if pkt.haslayer(TCP):
                    fl = int(pkt[TCP].flags)
                    if fl & 0x02 and not fl & 0x10:  # SYN without ACK
                        evs += self.scan.feed("tcp-syn", ip.src, ip.dst, int(pkt[TCP].dport))
                    else:
                        evs += self.scan.feed("any", ip.src)
                elif pkt.haslayer(UDP):
                    dport = int(pkt[UDP].dport)
                    if dport not in (53, 67, 68, 123, 137, 138, 1900, 5353, 1883):
                        evs += self.scan.feed("udp", ip.src, ip.dst, dport)
                elif pkt.haslayer(ICMP) and int(pkt[ICMP].type) == 8:
                    evs += self.scan.feed("icmp-echo", ip.src, ip.dst)
                if pkt.haslayer(Ether) and ip.src.startswith(self.own_ip.rsplit(".", 1)[0] + "."):
                    nd = self.registry.see(pkt[Ether].src, ip.src)
                    if nd:
                        evs.append(nd)
            for ev in evs:
                self.emit(ev)

        bpf = rw.env("SENTINEL_BPF",
                     "arp or icmp or (tcp[tcpflags] & tcp-syn != 0) or (udp and not port 1883)")
        while True:
            try:
                self.sniffing = True
                LOG.info("sniffing on %s (%s)", self.iface, bpf)
                sniff(iface=self.iface, filter=bpf, prn=handle, store=False, promisc=True)
            except Exception as e:  # noqa: BLE001
                LOG.error("sniffer stopped: %s — restarting in 5 s", e)
            self.sniffing = False
            time.sleep(5)

    def housekeeping(self) -> None:
        while True:
            time.sleep(5)
            for ev in self.anomaly.sweep_offline(rw.env_float("DEVICE_OFFLINE_S", 15)):
                self.emit(ev)
            self.registry.save()

    def run(self) -> None:
        threading.Thread(target=self.sniff, name="sniff", daemon=True).start()
        threading.Thread(target=self.housekeeping, name="house", daemon=True).start()
        LOG.info("sentinel up — logging to %s", self.logger.root())
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        stop.wait()
        self.registry.save()
        self.bus.stop()


if __name__ == "__main__":
    Sentinel().run()
