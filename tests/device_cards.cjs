/* Exercise the real shared renderer with a minimal DOM; no browser dependency. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.className = '';
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this.events = {};
    this.text = '';
    this.classList = {
      add: (...names) => { this.className += ' ' + names.join(' '); },
      contains: (name) => this.className.split(/\s+/).includes(name),
    };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this.text = ''; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((node) => node.textContent).join(' '); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, callback) { this.events[name] = callback; }
}
const all = (node, cls) => [
  ...(node.classList.contains(cls) ? [node] : []),
  ...node.children.flatMap((child) => all(child, cls)),
];
async function main() {
const detail = new Element('aside'), controls = new Element('aside'), status = new Element('p');
const descendants = (node) => [node, ...node.children.flatMap(descendants)];
const actions = { ac: ['setpoint'], camera: ['recording'], door: ['lock'], plug: ['power'],
  light: ['power', 'brightness'], fan: ['power', 'speed'], sensor: [] };
const requests = [];
let confirmLock = true;
const context = {
  document: {
    createElement: (tag) => new Element(tag),
    querySelector: (selector) => selector === '#device-detail' ? detail
      : selector === '#device-controls' ? controls : selector === '#device-status' ? status
        : descendants(controls).find((node) => '#' + node.id === selector) || null,
    querySelectorAll: () => [],
  },
  window: { confirm: () => confirmLock }, Date, setInterval: () => {},
  fetch: async (url, options) => {
    if (url === '/api/devices') return { ok: true, json: async () => ({ simulation: true,
      devices: Object.entries(telemetry).map(([device, tel]) => ({ device, kind: tel.kind,
        room: tel.room, actions: actions[tel.kind], adapter: 'simulation' })) }) };
    assert.equal(url, '/api/control');
    assert.equal(options.method, 'POST');
    requests.push(JSON.parse(options.body));
    return { status: 202, json: async () => ({ simulation: true }) };
  },
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pi4-core/web/assets/devices.js'), 'utf8'), context);
const readings = {
  ac: { temp_c: 22.3, setpoint: 20, power: 'on' },
  camera: { recording: true }, door: { lock: true, forced_open: false },
  plug: { power: true, power_w: 120 }, light: { power: true, brightness: 70 },
  fan: { power: true, speed: 40 }, sensor: { smoke: false, leak: false },
};
const telemetry = {};
for (const [kind, values] of Object.entries(readings)) {
  for (let i = 1; i <= 4; i++) telemetry[`${kind}-${i}`] = {
    ...values, kind, room: `Location ${i}`, rx: Date.now() / 1000,
    ip: `192.0.2.${i}`, firmware: 'demo-1.0',
  };
}
context.window.ReWatchDevices.update({ telemetry, verify: {}, simulation: true, conn: 'live' });
await new Promise(setImmediate); // Let the real async policy refresh finish.
assert.match(status.textContent, /SIMULATION/);
const picker = context.document.querySelector('#control-target');
assert.equal(picker.children.length, 28);
assert.equal(new Set(picker.children.map((option) => option.textContent)).size, 28);
assert.equal(new Set(picker.children.map((option) => option.value)).size, 28);
const expected = { ac: '22.3°', camera: 'Recording', door: 'Locked', plug: '120 W', light: '70%', fan: '40%', sensor: 'Clear' };
for (const [kind, value] of Object.entries(expected)) {
  context.window.ReWatchDevices.select(`${kind}-1`);
  const cards = all(detail, 'device-room');
  assert.equal(cards.length, 4, `${kind} must render four location cards`);
  assert.equal(all(detail, 'device-room-value')[0].textContent, value, `${kind} reading`);
  assert.equal(all(detail, 'device-room-name')[0].textContent, 'Location 1');
  assert.equal(cards[0].attributes['aria-pressed'], 'true');
  assert.equal(cards[1].attributes['aria-pressed'], 'false');
  cards[1].events.focus();
  assert.match(all(detail, 'sub-detail')[0].textContent, new RegExp(`${kind}-2.*unattested`));
  const summary = all(detail, 'sub-detail')[0];
  const original = cards[1];
  telemetry[`${kind}-2`] = { ...telemetry[`${kind}-2`], ...readings[kind], rx: Date.now() / 1000 };
  if (kind === 'ac') telemetry['ac-2'].temp_c = 23.4;
  for (let update = 0; update < 60; update++) {
    context.window.ReWatchDevices.update({ telemetry, verify: {}, simulation: true, conn: 'live' });
  }
  assert.equal(all(detail, 'device-room')[1], original, `${kind} update must retain the click/focus target`);
  assert.equal(all(detail, 'sub-detail')[0], summary, 'summary must survive telemetry updates');
  assert.equal(summary.textContent, original.title, 'active summary must refresh in place');
  if (kind === 'ac') assert.equal(all(original, 'device-room-value')[0].textContent, '23.4°');
  cards[1].events.click();
  assert.equal(all(detail, 'device-room').find((card) => card.attributes['aria-pressed'] === 'true').dataset.device, `${kind}-2`);
}
// Missing telemetry is unknown, not a fabricated healthy measurement.
telemetry['plug-1'] = { ...telemetry['plug-1'], power_w: undefined };
telemetry['sensor-1'] = { ...telemetry['sensor-1'], smoke: undefined, leak: undefined };
for (const kind of ['plug', 'sensor']) {
  context.window.ReWatchDevices.select(`${kind}-1`);
  assert.equal(all(detail, 'device-room-value')[0].textContent, '—');
}
telemetry['sensor-1'].smoke = false;
context.window.ReWatchDevices.select('sensor-1');
assert.equal(all(detail, 'device-room-value')[0].textContent, '—');
assert.equal(all(detail, 'device-bar-fill')[0].style.width, '0.0%');
telemetry['door-1'].forced_open = true;
context.window.ReWatchDevices.select('door-1');
assert.equal(all(detail, 'device-room-value')[0].textContent, 'Forced open');
telemetry['sensor-1'].smoke = true;
context.window.ReWatchDevices.select('sensor-1');
assert.equal(all(detail, 'device-room-value')[0].textContent, 'Smoke');
// External location strings must remain text, never interpolated markup.
telemetry['sensor-1'].room = '<img src=x onerror=alert(1)>';
context.window.ReWatchDevices.select('sensor-1');
assert.equal(all(detail, 'device-room-name')[0].textContent, '<img src=x onerror=alert(1)>');
const before = JSON.stringify(telemetry);
for (const [kind, permitted] of Object.entries(actions)) {
  for (let i = 1; i <= 4; i++) {
    const device = `${kind}-${i}`;
    context.document.querySelector('#control-target').events.change({ target: { value: device } });
    assert.equal(context.document.querySelector('#control-target').value, device);
    const forms = all(controls, 'device-control');
    assert.deepEqual(forms.map((form) => form.dataset.action), permitted);
    for (const form of forms) {
      const action = form.dataset.action;
      const input = form.children[0].children[0];
      assert.equal(input.disabled, false);
      if (action === 'lock') {
        assert.deepEqual(input.children.map((option) => option.value), ['true']);
        confirmLock = false;
        const count = requests.length;
        await form.events.submit({ preventDefault() {} });
        assert.equal(requests.length, count, 'cancelled lock must not send a command');
        confirmLock = true;
      }
      input.value = input.type === 'number' ? (action === 'setpoint' ? '23' : '55')
        : action === 'lock' ? 'true' : 'false';
      await form.events.submit({ preventDefault() {} });
      assert.deepEqual(requests.at(-1), { device, action, confirmed: true,
        value: input.type === 'number' ? Number(input.value) : input.value === 'true' });
      assert.match(context.document.querySelector('#command-status').textContent, /Requested; verify observed state/);
    }
    if (kind === 'sensor') assert.match(controls.textContent, /Observe-only/);
  }
}
assert.equal(JSON.stringify(telemetry), before, 'requested commands must not fabricate observed state');
context.window.ReWatchDevices.select('plug-1');
context.window.ReWatchDevices.update({ telemetry, verify: {}, simulation: true, conn: 'offline' });
assert.equal(all(controls, 'device-control')[0].children[0].children[0].disabled, true);
console.log('PASS: seven kinds, four cards each, readings, selection, summaries, unknown states, 28 control targets, lock confirmation, observe-only sensors');
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
