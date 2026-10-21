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
  let detailView = null;
  const fresh = (row) => row.observed && Date.now() / 1000 - Number(row.rx || 0) < 15;
  function roomReading(kind, tel) {
    const number = (key) => typeof tel[key] === "number" && Number.isFinite(tel[key]) ? tel[key] : null;
    const power = tel.power === true || tel.power === "on" ? "on"
      : tel.power === false || tel.power === "off" ? "off" : tel.power === "fault" ? "fault" : "unknown";
    let value = "—", meta = "No state reported", percent = null, zone = "ok";
    if (kind === "ac" || kind === "thermostat") {
      const temp = number("temp_c"), setpoint = number("setpoint");
      value = temp === null ? "—" : `${temp.toFixed(1)}°`;
      meta = `set ${setpoint ?? "—"}° · ${power}`;
      percent = temp === null ? null : (temp - 18) / 18 * 100;
      zone = temp > 30 || power === "fault" ? "hot" : temp > 26 ? "warm" : "ok";
    } else if (kind === "camera") {
      value = tel.recording === true ? "Recording" : tel.recording === false ? "Paused" : "—";
      meta = tel.recording === true ? "recording on" : tel.recording === false ? "recording off" : "No recording state";
      percent = typeof tel.recording === "boolean" ? (tel.recording ? 100 : 0) : null;
      zone = tel.recording === false ? "warm" : "ok";
    } else if (kind === "door") {
      value = tel.forced_open === true ? "Forced open" : tel.lock === true ? "Locked" : tel.lock === false ? "Unlocked" : "—";
      meta = `lock ${tel.lock === true ? "on" : tel.lock === false ? "off" : "unknown"} · forced ${tel.forced_open === true ? "yes" : tel.forced_open === false ? "no" : "unknown"}`;
      percent = typeof tel.lock === "boolean" ? (tel.lock ? 100 : 0) : null;
      zone = tel.forced_open === true ? "hot" : tel.lock === false ? "warm" : "ok";
    } else if (kind === "plug") {
      const watts = number("power_w");
      value = watts === null ? "—" : `${Math.round(watts)} W`;
      meta = `power ${power}`;
      percent = power === "on" ? 100 : power === "off" ? 0 : null;
      zone = watts > 1500 ? "hot" : "ok";
    } else if (kind === "light" || kind === "fan") {
      const key = kind === "light" ? "brightness" : "speed", amount = number(key);
      value = amount === null ? "—" : `${Math.round(amount)}%`;
      meta = `${key} · power ${power}`;
      percent = amount;
    } else if (kind === "sensor") {
      value = tel.smoke === true && tel.leak === true ? "Smoke + leak" : tel.smoke === true ? "Smoke"
        : tel.leak === true ? "Leak" : tel.smoke === false && tel.leak === false ? "Clear" : "—";
      meta = `smoke ${tel.smoke === true ? "yes" : tel.smoke === false ? "no" : "unknown"} · leak ${tel.leak === true ? "yes" : tel.leak === false ? "no" : "unknown"}`;
      zone = tel.smoke === true || tel.leak === true ? "hot" : "ok";
      percent = value === "—" ? null : 100;
    }
    return { value, meta, zone, percent: percent === null ? null : Math.max(0, Math.min(100, percent)) };
  }
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
    if (!row) {
      if (detailView?.key !== "empty" || detailView.box !== box) {
        box.replaceChildren(make("p", "device-hint", "Select an external device to inspect its readings and reported identity."));
        detailView = { box, key: "empty" };
      }
      return;
    }
    const group = list.filter((r) => r.kind === row.kind);
    const key = JSON.stringify([row.kind, group.map((r) => r.device)]);
    if (detailView?.key !== key || detailView.box !== box) {
      box.replaceChildren();
      const heading = make("h3"), evidence = make("p", "device-evidence");
      const badges = make("div", "device-badges"), link = make("span", "badge"), wifi = make("span", "badge");
      badges.append(link, wifi);
      const facts = make("dl", "device-facts"), values = [];
      for (const label of ["Device ID", "Kind", "IP reported", "Firmware", "Adapter"]) {
        const value = make("dd"); values.push(value); facts.append(make("dt", "", label), value);
      }
      box.append(heading, evidence, badges, facts);
      const view = { box, key, heading, evidence, link, wifi, values, cards: new Map(), active: null, optionsKey: "" };
      if (group.length > 1) {
        const acView = row.kind === "ac", subs = make("div", "device-subs room-grid" + (acView ? " ac-rooms" : ""));
        subs.append(make("h4", "", `${KIND_NAME[row.kind] || row.kind} · ${group.length} devices`));
        view.summary = make("p", "sub-detail", "Hover or focus a device for its detailed summary.");
        for (const member of group) {
          const button = make("button", "device-sub device-room" + (acView ? " ac-room" : ""));
          button.type = "button"; button.dataset.device = member.device;
          const name = make("span", "device-room-name" + (acView ? " ac-room-name" : ""));
          const value = make("span", "device-room-value" + (acView ? " ac-room-temp" : ""));
          const bar = make("span", "device-bar" + (acView ? " ac-bar" : ""));
          bar.setAttribute("aria-hidden", "true");
          const fill = make("span"), meta = make("span", "device-room-meta" + (acView ? " ac-room-meta" : ""));
          bar.append(fill); button.append(name, value, bar, meta);
          const show = () => { view.active = member.device; view.summary.textContent = button.title; };
          button.addEventListener("mouseenter", show); button.addEventListener("focus", show);
          button.addEventListener("click", () => { selected = member.device; render(); window.ReWatchTopology?.select?.(member.device); });
          view.cards.set(member.device, { button, name, value, fill, meta, acView });
          subs.append(button);
        }
        subs.append(view.summary); box.append(subs);
      }
      view.options = make("div"); box.append(view.options);
      detailView = view;
    }
    const view = detailView;
    const tel = state.telemetry[row.device] || {};
    const observed = ["temp_c", "setpoint", "power", "power_w", "recording", "lock", "brightness", "speed", "smoke", "leak"]
      .filter((key) => tel[key] != null).map((key) => key + "=" + String(tel[key])).join(" · ");
    view.heading.textContent = row.room || row.device;
    view.evidence.textContent = "Observed: " + (observed || "no state reported");
    view.link.textContent = fresh(row) ? "link · recent telemetry" : "link · not recently observed";
    view.wifi.textContent = state.verify[row.device]?.ok === true ? "wifi · matched" : state.verify[row.device]?.ok === false ? "wifi · mismatch" : "wifi · not verified";
    [row.device, row.kind, row.ip, row.firmware + " (unattested)", row.adapter]
      .forEach((value, index) => { view.values[index].textContent = value ?? ""; });
    for (const member of group) {
      const card = view.cards.get(member.device); if (!card) continue;
      const reading = roomReading(member.kind, state.telemetry[member.device] || {});
      card.button.className = "device-sub device-room" + (card.acView ? " ac-room" : "") + (member.device === selected ? " on" : "");
      card.button.setAttribute("aria-pressed", String(member.device === selected));
      card.button.title = [member.device, "ip " + member.ip, "firmware " + member.firmware + " (unattested)",
        reading.value + " · " + reading.meta,
        "wifi " + (state.verify[member.device]?.ok === true ? "matched" : state.verify[member.device]?.ok === false ? "mismatch" : "not verified"),
        fresh(member) ? "link · recent" : "link · stale"].join(" · ");
      card.name.textContent = member.room || member.device; card.value.textContent = reading.value;
      card.meta.textContent = reading.meta;
      card.fill.className = `device-bar-fill ${reading.zone}` + (card.acView ? " ac-bar-fill" : "");
      card.fill.style.width = (reading.percent ?? 0).toFixed(1) + "%";
      if (view.active === member.device) view.summary.textContent = card.button.title;
    }
    const optionsKey = JSON.stringify([row.device, row.actions, fresh(row), state.conn, group.map((r) => [r.device, r.room, r.actions])]);
    if (view.optionsKey !== optionsKey) {
      view.optionsKey = optionsKey; view.options.replaceChildren(controlOptions(row, list));
    }
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
    const others = (list || []).filter((r) => r.kind === row.kind && r.device !== row.device);
    if (others.length) {
      wrap.append(make("h4", "", "Other locations · " + (KIND_NAME[row.kind] || row.kind)));
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
      const element = make("option", "", (KIND_NAME[option.kind] || option.kind) + " · "
        + (option.room || option.device) + (option.actions?.length ? "" : " · observe-only"));
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
