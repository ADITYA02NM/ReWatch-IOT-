/* Reproduce streaming update bursts without a server or browser dependency. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = (name) => fs.readFileSync(path.join(__dirname, '../pi4-core/web/assets', name), 'utf8');

function liveBurst() {
  const frames = [], sockets = [], rendered = [];
  const connection = { lastElementChild: {} };
  class Socket {
    constructor() { sockets.push(this); this.readyState = 1; }
    send() {}
  }
  const context = {
    window: { addEventListener() {}, ReWatchDevices: { update: (state) => rendered.push({ ...state.telemetry }) } },
    document: { querySelector: (s) => s === '#conn' ? connection : null,
      documentElement: { setAttribute() {} } },
    location: { protocol: 'http:', host: 'localhost' }, WebSocket: Socket, Date,
    setInterval() {}, setTimeout() {}, requestAnimationFrame: (callback) => frames.push(callback),
  };
  vm.runInNewContext(source('live.js'), context);
  context.window.ReWatch.start();
  const message = (body) => sockets[0].onmessage({ data: JSON.stringify(body) });
  const paint = () => { const pending = frames.splice(0); pending.forEach((callback) => callback()); };
  message({ t: 'hello', telemetry: {} }); paint();
  rendered.length = 0;
  for (let i = 0; i < 60; i++) message({ t: 'bus', topic: `rewatch/iot/device-${i}/telemetry`, d: { power: true } });
  assert.equal(rendered.length, 0, 'streaming messages must not synchronously redraw every section');
  paint();
  assert.equal(rendered.length, 1, 'one burst must produce one dashboard render per frame');
  assert.equal(Object.keys(rendered[0]).length, 60, 'batched rendering must retain all latest telemetry');
}

class Node {
  constructor(kind) {
    this.dataset = { kind }; this.attributes = {}; this.events = {}; this.textContent = '';
    this.classList = { toggle() {} };
    this.labels = [new Node.Leaf(), new Node.Leaf()];
    this.title = new Node.Leaf(); this.label = new Node.Leaf();
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(key, callback) { this.events[key] = callback; }
  querySelector(s) { return s === 'title' ? this.title : s === '.im-label' ? this.label : null; }
  querySelectorAll(s) { return s === '.im-ip' ? this.labels : []; }
}
Node.Leaf = class { constructor() { this.textContent = ''; } setAttribute() {} };
function stableKinds() {
  let builds = 0, nodes = [], links = [], selected;
  const host = {
    set innerHTML(value) {
      builds++;
      nodes = [...value.matchAll(/data-kind="([^"]+)"/g)].map((match) => new Node(match[1]));
      links = nodes.map(() => new Node.Leaf());
    },
    querySelectorAll(s) { return s === '.im-kind' ? nodes : s === '.im-link' ? links : []; },
  };
  const state = { telemetry: { 'ac-1': { kind: 'ac', room: 'Room 1', rx: Date.now() / 1000 },
    'camera-1': { kind: 'camera', room: 'Reception', rx: Date.now() / 1000 } }, events: [] };
  const context = { window: { ReWatchDevices: { select: (id) => { selected = id; } } },
    document: { querySelector: (s) => s === '#iotmap' ? host : null }, Date };
  vm.runInNewContext(source('topology.js'), context);
  const topology = context.window.ReWatchTopology;
  topology.update(state);
  const original = nodes[1];
  for (let i = 0; i < 60; i++) {
    state.telemetry['camera-1'].room = `Reception ${i}`;
    topology.update(state);
  }
  assert.equal(builds, 1, 'unchanged kinds must not rebuild the SVG during pointer interactions');
  assert.equal(nodes[1], original, 'kind buttons must retain DOM identity');
  assert.match(original.title.textContent, /Reception 59/, 'retained nodes must show current metadata');
  original.events.click();
  assert.equal(selected, 'camera-1', 'kind selection must remain immediate');
  assert.equal(builds, 1, 'selection must not replace the clicked kind node');
  state.telemetry['door-1'] = { kind: 'door', room: 'Entrance' };
  topology.update(state);
  assert.equal(nodes.length, 3, 'new kinds must still become available');
}
if (process.argv[2] === 'topology') stableKinds(); else liveBurst();
console.log('PASS: dashboard burst batching / stable section targets');
