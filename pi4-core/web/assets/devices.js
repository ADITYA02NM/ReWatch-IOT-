/* Shared production/demo device view. Policy comes from the server, not telemetry. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const make = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = String(text);
    return node;
  };
  const icons = { ac: "❄", thermostat: "◉", camera: "◈", door: "▥", plug: "ϟ", light: "☀", fan: "✣", sensor: "◇", generic: "□" };
  let state = { telemetry: {}, devices: {}, nodes: {} }, inventory = [], selected = null;
  let started = false, mapKey = "", detailKey = "", loading = false;
  const fresh = (row) => row.observed && Date.now() / 1000 - Number(row.rx || 0) < 15;
  function rows() {
    const merged = new Map(inventory.map((row) => [row.device, row]));
    for (const [id, tel] of Object.entries(state.telemetry)) {
      const policy = merged.get(id) || { device: id, actions: [], adapter: "observe-only" };
      merged.set(id, { ...policy, room: tel.room || policy.room || id,
        kind: policy.kind || tel.kind || "generic", ip: tel.ip || "unknown",
        firmware: tel.firmware || "unknown", rx: tel.rx, observed: true });
    }
    // Demo enrollment is preconfigured; it is not discovery evidence. Also
    // discard cached inventory immediately after Replay clears telemetry.
    return [...merged.values()]
      .filter((row) => !state.simulation || Object.hasOwn(state.telemetry, row.device))
      .sort((a, b) => a.device.localeCompare(b.device));
  }
  async function refresh() {
    if (loading) return;
    loading = true;
    try {
      const response = await fetch("/api/devices", { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error("Device policy unavailable");
      const body = await response.json();
      inventory = body.devices || [];
      $("#device-status").textContent = body.simulation
        ? "SIMULATION · controls affect this laptop only"
        : "MQTT bridge controls · requested ≠ confirmed";
      render();
    } catch {
      inventory = []; // fail closed: never retain stale authorization in the UI
      $("#device-status").textContent = "Device policy unavailable — controls disabled";
      render();
    } finally { loading = false; }
  }
  function render() {
    const root = $("#inventory-map"); if (!root) return;
    const list = rows();
    const key = JSON.stringify([selected, list.map((r) => [r.device, r.kind, r.room, fresh(r), state.devices[r.device]?.level]),
      Object.entries(state.nodes).map(([id, n]) => [id, n.online, Date.now() / 1000 - Number(n.rx || 0) < 20])]);
    if (key !== mapKey) {
      mapKey = key;
      const focused = document.activeElement?.dataset?.device;
      root.replaceChildren();
      const infra = make("div", "topology-infra");
      for (const [id, name] of [["sentinel", "Sentinel · observe"], ["core", "Core · decide"], ["herald", "Herald · notify"]]) {
        const n = state.nodes[id], up = n?.online && Date.now() / 1000 - Number(n.rx || 0) < 20;
        const card = make("div", "topology-role" + (up ? " online" : ""));
        card.append(make("span", "role-dot"), make("span", "", name)); infra.append(card);
      }
      root.append(infra, make("div", "bus-line", state.simulation ? "SIMULATED MESSAGE BUS" : "LOGICAL MQTT BUS"));
      const grid = make("div", "device-grid");
      for (const row of list) {
        const level = fresh(row) ? (state.devices[row.device]?.level || "ok") : "offline";
        const button = make("button", "device-tile " + level);
        button.type = "button"; button.dataset.device = row.device;
        button.setAttribute("aria-pressed", String(selected === row.device));
        button.append(make("span", "device-icon", icons[row.kind] || icons.generic),
          make("strong", "", row.room || row.device), make("small", "", row.kind + " · " + level));
        button.addEventListener("click", () => { selected = row.device; render(); });
        grid.append(button);
      }
      if (!list.length) grid.append(make("p", "empty", "Waiting for observed or enrolled devices…"));
      root.append(grid);
      if (focused) [...grid.children].find((node) => node.dataset.device === focused)?.focus();
      $("#topo-sub").textContent = list.length + " devices · logical, not a physical port map";
    }
    const row = list.find((r) => r.device === selected);
    renderDetail(row);
  }
  function renderDetail(row) {
    const box = $("#device-detail"); if (!box) return;
    const key = JSON.stringify(row ? [row.device, row.actions, fresh(row), state.conn] : null);
    if (detailKey !== key || !box.children.length) {
      detailKey = key; box.replaceChildren();
      if (!row) { box.append(make("p", "device-hint", "Select a device to inspect its evidence and permitted actions.")); return; }
      box.append(make("h3", "", row.room || row.device), make("p", "device-evidence"));
      const actions = make("div", "device-actions");
      for (const action of row.actions || []) {
        const form = make("form", "device-control");
        const label = make("label", "", action);
        let input;
        if (["setpoint", "brightness", "speed"].includes(action)) {
          input = make("input"); input.type = "number";
          input.min = action === "setpoint" ? "16" : "0"; input.max = action === "setpoint" ? "30" : "100";
          input.value = state.telemetry[row.device]?.[action] ?? (action === "setpoint" ? 20 : 50);
          input.step = action === "setpoint" ? "0.5" : "1"; input.required = true;
        } else {
          input = make("select");
          for (const value of (action === "lock" ? [true] : [true, false])) {
            const option = make("option", "", action === "lock" ? "Lock only" : value ? "On" : "Off");
            option.value = String(value); input.append(option);
          }
        }
        input.setAttribute("aria-label", action + " value"); label.append(input);
        const button = make("button", "btn", "Request " + action); button.type = "submit";
        const disabled = !fresh(row) || state.conn !== "live";
        input.disabled = disabled; button.disabled = disabled;
        form.append(label, button); actions.append(form);
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          const confirmed = action !== "lock" || window.confirm("Request door locking? Confirm people can still exit safely. Unlocking is not supported.");
          if (!confirmed) return;
          const value = input.type === "number" ? Number(input.value) : input.value === "true";
          button.disabled = true;
          const status = $("#command-status");
          try {
            const response = await fetch("/api/control", { method: "POST", credentials: "same-origin",
              headers: { "Content-Type": "application/json" }, body: JSON.stringify({ device: row.device, action, value, confirmed }) });
            if (response.status !== 202) throw new Error("Command rejected or transport unavailable");
            const body = await response.json();
            status.textContent = (body.simulation ? "SIMULATED · " : "") + "Command requested. Check observed state; acceptance is not confirmation.";
          } catch { status.textContent = "Command failed. Nothing confirmed; check connection and permissions."; }
          finally { button.disabled = !fresh(row) || state.conn !== "live"; }
        });
      }
      if (!row.actions?.length) actions.append(make("p", "device-hint", "Observe-only · no enrolled control capability."));
      box.append(actions);
      const status = make("p", "device-hint"); status.id = "command-status"; status.setAttribute("role", "status"); box.append(status);
    }
    const evidence = box.querySelector(".device-evidence");
    if (row && evidence) {
      const tel = state.telemetry[row.device] || {};
      const observed = ["setpoint", "power", "recording", "lock", "brightness", "speed", "smoke", "leak"]
        .filter((key) => tel[key] != null).map((key) => key + "=" + String(tel[key])).join(" · ");
      evidence.textContent = row.device + " · " + row.adapter + " · " + (fresh(row) ? "recent telemetry" : "not recently observed")
        + "\nIP (reported): " + row.ip + " · firmware (unattested): " + row.firmware + "\nObserved: " + (observed || "no state reported");
    }
  }
  window.ReWatchDevices = {
    update(next) {
      state = next;
      if (!started) { started = true; refresh(); setInterval(refresh, 5000); }
      render();
    },
  };
})();
