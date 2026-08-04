#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..', '..', '..');
const index = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const marker = index.indexOf('// Attention analytics');
const end = index.indexOf('</script>', marker);
assert(marker >= 0 && end > marker, 'analytics block not found in index.html');
const analyticsSource = index.slice(marker, end);

function makeHarness({dnt = '0', withSink = true} = {}) {
  let now = 0;
  let timerId = 0;
  const timers = new Map();
  const events = [];
  const listeners = new Map();
  const globalListeners = new Map();
  const observers = [];
  const storage = new Map();
  const elements = Object.fromEntries(
    ['hero', 'experience', 'projects', 'skills', 'about', 'contact'].map(id => [id, {id}]),
  );

  class FakeIntersectionObserver {
    constructor(callback, options) {
      this.callback = callback;
      this.options = options;
      this.observed = [];
      observers.push(this);
    }
    observe(element) { this.observed.push(element); }
    unobserve(element) { this.observed = this.observed.filter(item => item !== element); }
  }

  const document = {
    hidden: false,
    title: 'Test portfolio',
    referrer: '',
    documentElement: {scrollHeight: 4000, dataset: {}},
    getElementById(id) { return elements[id] || null; },
    addEventListener(type, callback) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(callback);
    },
  };

  const context = {
    console,
    URL,
    Date,
    Math,
    Object,
    Array,
    encodeURIComponent,
    document,
    navigator: {doNotTrack: dnt, globalPrivacyControl: false, webdriver: false},
    location: {hostname: 'localhost', host: 'localhost', href: 'http://localhost/', protocol: 'http:'},
    sessionStorage: {
      getItem(key) { return storage.has(key) ? storage.get(key) : null; },
      setItem(key, value) { storage.set(key, value); },
    },
    performance: {now: () => now},
    IntersectionObserver: FakeIntersectionObserver,
    innerWidth: 1440,
    innerHeight: 900,
    scrollY: 0,
    devicePixelRatio: 2,
    Image: class {},
    requestAnimationFrame(callback) { callback(now); },
    addEventListener(type, callback) {
      if (!globalListeners.has(type)) globalListeners.set(type, []);
      globalListeners.get(type).push(callback);
    },
    removeEventListener() {},
    setTimeout(callback, delay) {
      const id = ++timerId;
      timers.set(id, {callback, due: now + Number(delay)});
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
  };
  context.window = context;
  context.doNotTrack = dnt;
  if (withSink) context.__attentionAnalyticsTest = {sink: event => events.push(event)};

  function advance(milliseconds) {
    now += milliseconds;
    let ran = true;
    while (ran) {
      ran = false;
      const due = [...timers.entries()].filter(([, timer]) => timer.due <= now).sort((a, b) => a[1].due - b[1].due);
      for (const [id, timer] of due) {
        if (!timers.has(id)) continue;
        timers.delete(id);
        timer.callback();
        ran = true;
      }
    }
  }

  function dispatchDocument(type, event = {}) {
    for (const callback of listeners.get(type) || []) callback(event);
  }

  vm.runInNewContext(analyticsSource, context, {filename: 'attention-analytics.js'});
  return {advance, context, document, elements, events, observers, dispatchDocument};
}

{
  const harness = makeHarness();
  assert.equal(harness.observers.length, 1, 'one section observer should be created');
  assert.deepEqual(harness.events.map(event => event.path), ['/']);

  const observer = harness.observers[0];
  observer.callback([{target: harness.elements.projects, isIntersecting: true}]);
  harness.advance(35000); // Simulate one heavily delayed browser tick.
  const projectEvents = harness.events.map(event => event.path).filter(name => name.startsWith('section/projects/'));
  assert.deepEqual(projectEvents, [
    'section/projects/seen',
    'section/projects/3s',
    'section/projects/10s',
    'section/projects/30s',
  ], 'one delayed tick must emit every crossed threshold in order');

  harness.advance(30000);
  assert.equal(harness.events.filter(event => event.path === 'section/projects/60s').length, 1);
  assert.equal(harness.events.filter(event => event.path === 'session/engaged/60s').length, 1);

  harness.document.hidden = true;
  harness.dispatchDocument('visibilitychange');
  harness.advance(120000);
  assert.equal(harness.events.filter(event => event.path === 'session/engaged/120s').length, 0, 'hidden time must not count');
  harness.document.hidden = false;
  harness.dispatchDocument('visibilitychange');
  harness.advance(60000);
  assert.equal(harness.events.filter(event => event.path === 'session/engaged/120s').length, 1);

  observer.callback([{target: harness.elements.projects, isIntersecting: false}]);
  observer.callback([{target: harness.elements.projects, isIntersecting: true}]);
  harness.advance(70000);
  for (const name of ['seen', '3s', '10s', '30s', '60s']) {
    assert.equal(harness.events.filter(event => event.path === `section/projects/${name}`).length, 1, `${name} must be deduplicated`);
  }
}

{
  const dnt = makeHarness({dnt: '1'});
  assert.equal(dnt.events.length, 0, 'DNT must suppress all analytics');
  assert.equal(dnt.observers.length, 0, 'DNT must stop analytics before observers are created');
}

{
  const dormant = makeHarness({withSink: false});
  assert.equal(dormant.observers.length, 0, 'blank CODE must be a complete no-op');
}

console.log('PASS: tracker thresholds, janked multi-crossing, visibility pause, dedupe, DNT, and kill switch');
