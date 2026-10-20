/* Shared six-panel view. Telemetry is evidence, never control authorization. */
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
  const KIND_NAME = { ac: "AC", thermostat: "Thermostat", camera: "IP camera", door: "Door",
    plug: "Plug", light: "Light", fan: "Fan", sensor: "Sensor", generic: "Device" };
  /* AC/thermostat first: the four room controllers lead the external list. */
  const kindOrder = { ac: 0, thermostat: 1, camera: 2, door: 3, plug: 4, light: 5, fan: 6, sensor: 7, generic: 8 };
  const actionHelp = {
    setpoint: "Setpoint 16–30 °C", brightness: "Brightness 0–100 %", speed: "Speed 0–100 %",
    power: "Power on / off", recording: "Recording on / off", lock: "Lock only — unlock is never sent",
  };
  let state = { telemetry: {}, devices: {}, nodes: {} }, inventory = [], selected = null;
  let started = false, controlsKey = "", loading = false;
  const fresh = (row) => row.observed && Date.now() / 1000 - Number(row.rx || 0) < 15;
  function rows() {
    const merged = new Map(inventory.map((row) => [row.device, row]));
    for (const [id, tel] of Object.entries(state.telemetry)) {
      const policy = merged.get(id) || { device: id, actions: [], adapter: "observe-only" };
      merged.set(id, { ...policy, room: tel.room || policy.room || id, kind: policy.kind || tel.kind || "generic",
        ip: tel.ip || "unknown", firmware: tel.firmware || "unknown", rx: tel.rx, observed: true });
    }
    // Enrollment is not proof of discovery in the recording simulation.
    return [...merged.values()].filter((row) => !state.simulation || Object.hasOwn(state.telemetry, row.device))
      .sort((a, b) => (kindOrder[a.kind] ?? 8) - (kindOrder[b.kind] ?? 8)
        || String(a.room).localeCompare(String(b.room)) || a.device.localeCompare(b.device));
  }
  function showPanel(name) {
    const picker = $("#panel-select");
    if (picker && picker.value !== name) picker.value = name;
    for (const panel of document.querySelectorAll("main.grid > .panel")) {
      panel.classList.toggle("mobile-active", panel.dataset.panel === name);
    }
  }
  async function refresh() {
    if (loading) return;
    loading = true;
    try {
      const response = await fetch("/api/devices", { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error("Device policy unavailable");
      const body = await response.json(); inventory = body.devices || [];
      $("#device-status").textContent = body.simulation ? "SIMULATION · controls affect this laptop only" : "MQTT bridge · requested ≠ confirmed";
    } catch {
      inventory = []; // fail closed, including already selected controls
      $("#device-status").textContent = "Policy unavailable — controls disabled";
    } finally { loading = false; render(); }
  }
  function render() {
    const list = rows();
    if (!list.some((r) => r.device === selected)) selected = list[0]?.device || null;
    const row = list.find((r) => r.device === selected);
    renderDetail(row, list); renderControls(row, list);
  }
  function renderDetail(row, list) {
    const box = $("#device-detail"); if (!box) return;
    box.replaceChildren();
    if (!row) { box.append(make("p", "device-hint", "Select an external device to inspect its readings and reported identity.")); return; }
    const tel = state.telemetry[row.device] || {};
    const observed = ["temp_c", "setpoint", "power", "power_w", "recording", "lock", "brightness", "speed", "smoke", "leak"]
      .filter((key) => tel[key] != null).map((key) => key + "=" + String(tel[key])).join(" · ");
    box.append(make("h3", "", row.room || row.device), make("p", "device-evidence", "Observed: " + (observed || "no state reported")));
    const badges = make("div", "device-badges");
    badges.append(make("span", "badge", fresh(row) ? "link · recent telemetry" : "link · not recently observed"),
      make("span", "badge", state.verify[row.device]?.ok === true ? "wifi · matched" : state.verify[row.device]?.ok === false ? "wifi · mismatch" : "wifi · not verified"));
    box.append(badges);
    const facts = make("dl", "device-facts");
    for (const [label, value] of [["Device ID", row.device], ["Kind", row.kind],
      ["IP reported", row.ip], ["Firmware", row.firmware + " (unattested)"], ["Adapter", row.adapter]]) {
      facts.append(make("dt", "", label), make("dd", "", value));
    }
    box.append(facts);
    /* Kind group: AC shows Room 1–4 with readings, hover gives the full summary. */
    const group = (list || []).filter((r) => r.kind === row.kind);
    if (group.length > 1) {
      const subs = make("div", "device-subs");
      subs.append(make("h4", "", `${KIND_NAME[row.kind] || row.kind} · ${group.length} devices`));
      const detail = make("p", "sub-detail", "Hover a device for its detailed summary.");
      for (const member of group) {
        const tel = state.telemetry[member.device] || {};
        const compact = ["temp_c", "setpoint", "power", "recording", "lock", "brightness", "speed", "power_w", "smoke", "leak"]
          .filter((key) => tel[key] != null).map((key) => `${key}=${tel[key]}`).join(" · ");
        const button = make("button", "device-sub" + (member.device === row.device ? " on" : ""),
          `${member.room || member.device} · ${compact || "no state"}`);
        button.type = "button"; button.dataset.device = member.device;
        button.title = [member.device, "ip " + member.ip, "firmware " + member.firmware + " (unattested)",
          "wifi " + (state.verify[member.device]?.ok === true ? "matched" : state.verify[member.device]?.ok === false ? "mismatch" : "not verified"),
          fresh(member) ? "link · recent" : "link · stale"].join(" · ");
        const show = () => { detail.textContent = button.title; };
        button.addEventListener("mouseenter", show);
        button.addEventListener("focus", show);
        button.addEventListener("click", () => { selected = member.device; render(); window.ReWatchTopology?.select?.(member.device); });
        subs.append(button);
      }
      subs.append(detail);
      box.append(subs);
    }
    box.append(controlOptions(row, list));
  }
  /* The details panel is the entry point for acting on any external IoT device. */
  function controlOptions(row, list) {
    const wrap = make("div", "control-options");
    wrap.append(make("h4", "", "Control options"));
    const actions = row.actions || [];
    if (!actions.length) {
      wrap.append(make("p", "device-hint", "Observe-only — no enrolled control capability for this device."));
    } else {
      for (const action of actions) {
        const line = make("div", "option-row");
        const text = make("div", "option-text");
        text.append(make("strong", "", action), make("small", "", actionHelp[action] || "policy-approved action"));
        const button = make("button", "btn", "Control");
        button.type = "button"; button.dataset.action = action; button.dataset.device = row.device;
        button.disabled = !fresh(row) || state.conn !== "live";
        button.addEventListener("click", () => {
          selected = row.device; render();
          showPanel("details");
          const form = document.querySelector('#device-controls .device-control[data-action="' + action + '"]');
          if (form) { form.querySelector("input,select")?.focus(); form.scrollIntoView({ block: "nearest" }); }
        });
        line.append(text, button); wrap.append(line);
      }
    }
    const others = (list || []).filter((r) => r.device !== row.device);
    if (others.length) {
      wrap.append(make("h4", "", "Other external IoT devices"));
      const chips = make("div", "device-chips");
      for (const other of others) {
        const chip = make("button", "chip", (other.room || other.device));
        chip.type = "button"; chip.dataset.device = other.device;
        chip.title = other.device + " · " + other.kind + (other.actions?.length ? " · controllable" : " · observe-only");
        chip.addEventListener("click", () => { selected = other.device; render(); });
        chips.append(chip);
      }
      wrap.append(chips);
    }
    return wrap;
  }
  function renderControls(row, list) {
    const box = $("#device-controls"); if (!box) return;
    const key = JSON.stringify(row ? [row.device, row.actions, fresh(row), state.conn,
      (list || []).map((r) => [r.device, r.room, r.kind])] : null);
    if (controlsKey === key && box.children.length) return;
    controlsKey = key; box.replaceChildren();
    if (!row) { box.append(make("p", "device-hint", "Select an external device to see its permitted controls.")); return; }
    box.append(make("h3", "", "Target · " + (row.room || row.device)));
    const picker = make("label", "control-target");
    picker.append(make("span", "", "Device"));
    const select = make("select"); select.id = "control-target";
    select.setAttribute("aria-label", "Device to control");
    for (const option of list || []) {
      const element = make("option", "", (option.room || option.device) + (option.actions?.length ? "" : " · observe-only"));
      element.value = option.device; select.append(element);
    }
    select.value = row.device;
    select.addEventListener("change", (event) => { selected = event.target.value; render(); });
    picker.append(select); box.append(picker);
    const actions = make("div", "device-actions");
    for (const action of row.actions || []) {
      const form = make("form", "device-control"); form.dataset.action = action;
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
          const option = make("option", "", action === "lock" ? "Lock only" : value ? "On" : "Off"); option.value = String(value); input.append(option);
        }
      }
      input.setAttribute("aria-label", action + " value"); label.append(input);
      const button = make("button", "btn", "Request " + action); button.type = "submit";
      input.disabled = button.disabled = !fresh(row) || state.conn !== "live";
      form.append(label, button); actions.append(form);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const confirmed = action !== "lock" || window.confirm("Request door locking? Confirm people can still exit safely. Unlocking is not supported.");
        if (!confirmed) return;
        const value = input.type === "number" ? Number(input.value) : input.value === "true";
        button.disabled = true; const status = $("#command-status");
        try {
          const response = await fetch("/api/control", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device: row.device, action, value, confirmed }) });
          if (response.status !== 202) throw new Error("Command rejected");
          const body = await response.json();
          status.textContent = (body.simulation ? "SIMULATED · " : "") + "Requested; verify observed state.";
        } catch { status.textContent = "Failed — no action confirmed. Check connection / policy."; }
        finally { button.disabled = !fresh(row) || state.conn !== "live"; }
      });
    }
    if (!row.actions?.length) actions.append(make("p", "device-hint", "Observe-only · no enrolled control capability."));
    const status = make("p", "device-hint", "Requested ≠ confirmed. Read observed state in details.");
    status.id = "command-status"; status.setAttribute("role", "status"); box.append(actions, status);
  }
  $("#panel-select")?.addEventListener("change", (event) => showPanel(event.target.value));
  document.querySelector('[data-panel="risk"]')?.classList.add("mobile-active");
  window.ReWatchDevices = { update(next) {
    state = next;
    if (!started) { started = true; refresh(); setInterval(refresh, 5000); }
    render();
  },
    /* Shared with the IoT-connections diagram (section 04). */
    list() { return rows(); },
    select(device) { selected = device; render(); window.ReWatchTopology?.select?.(device); },
  };
})();
