/*
 * Dependency-free DOM/clock harness for the actual rendered V10 JavaScript.
 * Run: node tests/renderer_expiry.cjs
 * The standalone command uses Python's standard library to render a fixture.
 * The Python unittest suite supplies the same fixture through --stdin.
 * This verifies behavior, not browser layout or screenshot appearance.
 */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const vm = require('node:vm');

let input;
if (process.argv.includes('--stdin')) {
  input = JSON.parse(fs.readFileSync(0, 'utf8'));
} else {
  const python = process.env.PYTHON || 'python3';
  const fixture = spawnSync(python, [path.join(__dirname, 'test_renderer.py'), '--emit-fixture'], {
    cwd: path.dirname(__dirname), encoding: 'utf8', timeout: 30000,
  });
  if (fixture.error) throw fixture.error;
  assert.equal(fixture.status, 0, fixture.stdout + fixture.stderr);
  input = JSON.parse(fixture.stdout);
}

assert.equal(typeof input.script, 'string');
assert.equal(typeof input.state, 'string');
const baseState = JSON.parse(input.state);
const START = '2026-10-12T03:00:00Z';
let checks = 0;

function createHarness(changes = {}, start = START) {
  let now = Date.parse(start);
  let reloads = 0;
  const state = {...baseState, ...changes};
  const listeners = new Map();
  const intervals = [];
  const elements = {};
  for (const id of ['report-state', 'freshness-message', 'source-age', 'research-validity', 'freshness-banner', 'reload-page']) {
    elements[id] = {
      textContent: '', dataset: {},
      addEventListener(event, callback) { listeners.set(`${id}:${event}`, callback); },
    };
  }
  elements['report-state'].textContent = JSON.stringify(state);
  // Even a restored or mistakenly populated formal element must be scrubbed.
  const formal = [{hidden: false, textContent: '49'}, {hidden: false, textContent: '7'}];
  class MockDate extends Date { static now() { return now; } }
  const document = {
    hidden: false,
    getElementById(id) { assert.ok(elements[id], `Unexpected element ${id}`); return elements[id]; },
    querySelectorAll(selector) { assert.equal(selector, '[data-formal-selection]'); return formal; },
    addEventListener(event, callback) { listeners.set(`document:${event}`, callback); },
  };
  const window = {
    location: {reload() { reloads += 1; }},
    setInterval(callback, milliseconds) { intervals.push({callback, milliseconds}); },
    addEventListener(event, callback) { listeners.set(`window:${event}`, callback); },
  };
  // No network API exists in this VM: accidental fetch/XHR work fails the test.
  vm.runInNewContext(input.script, {document, window, Date: MockDate, JSON, Number, Math}, {
    timeout: 2000, filename: 'rendered-v10-report.js',
  });
  return {
    document, elements, formal, intervals,
    state() { return elements['freshness-banner'].dataset.state; },
    message() { return elements['freshness-message'].textContent; },
    setTime(value) { now = Date.parse(value); },
    fire(key) { assert.ok(listeners.has(key), `Missing event ${key}`); listeners.get(key)(); },
    reloads() { return reloads; },
    tick() { intervals.forEach(item => item.callback()); },
  };
}

function assertFormalBlank(harness) {
  for (const element of harness.formal) {
    assert.equal(element.hidden, true);
    assert.equal(element.textContent, '');
  }
}

function test(name, callback) {
  callback();
  checks += 1;
  console.log(`PASS ${name}`);
}

test('fresh_verified remains an explicitly static snapshot', () => {
  const h = createHarness();
  assert.equal(h.state(), 'snapshot-within-24h');
  assert.match(h.message(), /不是持續更新的即時資料/);
  assert.match(h.elements['source-age'].textContent, /1 小時 0 分鐘/);
  assertFormalBlank(h);
});

test('snapshot is never promoted to fresh_verified', () => {
  const h = createHarness({sourceStatus: 'snapshot'});
  assert.equal(h.state(), 'snapshot');
  assert.match(h.message(), /未核實此刻的官方最新資料/);
  assert.match(h.elements['research-validity'].textContent, /不得當作當前有效選號/);
  assertFormalBlank(h);
});

test('unknown and expired source statuses fail closed', () => {
  const unknown = createHarness({sourceStatus: 'unknown'});
  assert.equal(unknown.state(), 'unverified');
  assert.match(unknown.message(), /來源狀態未通過/);
  const expired = createHarness({sourceStatus: 'expired'});
  assert.equal(expired.state(), 'stale');
  assert.match(expired.message(), /已標示為過期/);
  assertFormalBlank(unknown);
  assertFormalBlank(expired);
});

test('source age expires at the exact 24-hour boundary', () => {
  const h = createHarness({targetDate: '2026-10-15'}, '2026-10-13T01:59:59Z');
  assert.equal(h.state(), 'snapshot-within-24h');
  assert.equal(h.intervals.length, 1);
  assert.equal(h.intervals[0].milliseconds, 30000);
  h.setTime('2026-10-13T02:00:00Z');
  h.tick();
  assert.equal(h.state(), 'stale');
  assert.match(h.message(), /已達 24 小時時效上限/);
  assertFormalBlank(h);
});

test('Hong Kong target day starts at 16:00 UTC the preceding day', () => {
  const h = createHarness({}, '2026-10-12T15:59:59Z');
  assert.equal(h.state(), 'snapshot-within-24h');
  h.setTime('2026-10-12T16:00:00Z');
  h.fire('window:pageshow');
  assert.equal(h.state(), 'target-cutoff');
  assert.match(h.message(), /香港日期已進入或超過目標開獎日/);
  assertFormalBlank(h);
});

test('past target days remain expired even with a recent receipt', () => {
  const h = createHarness({targetDate: '2026-10-11'});
  assert.equal(h.state(), 'target-cutoff');
  assertFormalBlank(h);
});

test('invalid or missing source timestamps fail closed', () => {
  for (const value of [null, '', 'bad', '2026-10-12', '2026-02-30T02:00:00Z',
                       '2026-10-12T24:00:00Z', '2026-10-12T02:60:00Z',
                       '2026-10-12T02:00:61Z', '2026-10-12T04:00:00Z']) {
    const h = createHarness({retrievedAt: value});
    assert.equal(h.state(), 'stale', String(value));
    assertFormalBlank(h);
  }
});

test('invalid generation time and clock rollback fail closed', () => {
  for (const generatedAt of [null, 'bad', '2026-10-13T03:00:00Z']) {
    const h = createHarness({generatedAt});
    assert.equal(h.state(), 'stale');
    assertFormalBlank(h);
  }
  const h = createHarness({}, '2026-10-12T02:59:59Z');
  assert.equal(h.state(), 'stale');
  assertFormalBlank(h);
});

test('unknown or malformed target dates are never inferred', () => {
  for (const targetDate of [null, '', '2026-02-30', '2026-10-3', 'bad']) {
    const h = createHarness({targetDate});
    assert.match(h.message(), /目標日期尚未可靠核實/);
    assert.match(h.elements['research-validity'].textContent, /不得當作當前有效選號/);
    assertFormalBlank(h);
  }
});

test('tab visibility recomputes expiry on return', () => {
  const h = createHarness({targetDate: '2026-10-15'});
  h.document.hidden = true;
  h.setTime('2026-10-13T02:00:00Z');
  h.fire('document:visibilitychange');
  assert.equal(h.state(), 'snapshot-within-24h');
  h.document.hidden = false;
  h.fire('document:visibilitychange');
  assert.equal(h.state(), 'stale');
  assertFormalBlank(h);
});

test('page restoration clears any injected formal selection', () => {
  const h = createHarness();
  h.formal[0].textContent = '49';
  h.formal[0].hidden = false;
  h.fire('window:pageshow');
  assertFormalBlank(h);
});

test('repeat refresh clicks only reload the current page', () => {
  const h = createHarness();
  h.fire('reload-page:click');
  h.fire('reload-page:click');
  assert.equal(h.reloads(), 2);
  assert.doesNotMatch(input.script, /\bfetch\s*\(|XMLHttpRequest|serviceWorker/);
  assertFormalBlank(h);
});

console.log(`All renderer DOM checks passed (${checks} cases).`);
