#!/usr/bin/env node
// Full-page screenshots of the running preview, for reviewing the layout without running the site.
// Uses the Chrome already installed on the Mac over the DevTools protocol; no npm packages.
//
//   npm run dev                                   # in another terminal
//   npm run shoot -- [--out shots] [--pages /,/work/] [--widths 1440,390] [--scale 2] [--status] [--preview] [--open] [--motion]
//
// --scale 2 renders at retina density (default 1). --status draws the image-rights badges on every
// image; --preview shows what the public build would show today (each blocked image's stand-in).
// --open expands every collapsed project row. Shots use reduced motion (final numbers, a still arm,
// video posters) unless --motion is given.
// Node 20 needs --experimental-websocket (the npm script adds it).
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
};
const BASE = opt('base', 'http://127.0.0.1:4823');
const OUT = resolve(opt('out', 'shots'));
const STATUS = args.includes('--status');
const PREVIEW = args.includes('--preview');
const OPEN = args.includes('--open');
const PAGES = opt('pages', '/').split(',');
const WIDTHS = opt('widths', '1440,390').split(',').map(Number);
const SCALE = Number(opt('scale', '1')) || 1;
const CHROME = process.env.CHROME ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

if (typeof WebSocket === 'undefined') {
  console.error('Run with: node --experimental-websocket scripts/shoot.mjs (Node 20), or Node 22+.');
  process.exit(1);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const port = 9300 + Math.floor(Math.random() * 600);
const profile = mkdtempSync(join(tmpdir(), 'shoot-'));
const chrome = spawn(
  CHROME,
  ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--hide-scrollbars', '--no-first-run', 'about:blank'],
  { stdio: 'ignore' },
);

async function devtools() {
  for (let i = 0; i < 50; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' });
      if (res.ok) return (await res.json()).webSocketDebuggerUrl;
    } catch {
      /* not up yet */
    }
    await sleep(200);
  }
  throw new Error('Chrome did not start');
}

function client(url) {
  const ws = new WebSocket(url);
  let id = 0;
  const pending = new Map();
  const listeners = new Map();
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.id && pending.has(msg.id)) {
      const { ok, fail } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? fail(new Error(msg.error.message)) : ok(msg.result);
    } else if (msg.method && listeners.has(msg.method)) {
      for (const fn of listeners.get(msg.method)) fn(msg.params);
    }
  };
  const ready = new Promise((r) => (ws.onopen = r));
  return {
    ready,
    send: (method, params = {}) =>
      new Promise((ok, fail) => {
        pending.set(++id, { ok, fail });
        ws.send(JSON.stringify({ id, method, params }));
      }),
    once: (method) =>
      new Promise((r) => {
        const fns = listeners.get(method) ?? [];
        const fn = (p) => {
          listeners.set(method, (listeners.get(method) ?? []).filter((f) => f !== fn));
          r(p);
        };
        listeners.set(method, [...fns, fn]);
      }),
    close: () => ws.close(),
  };
}

// Load every lazy image, settle reveals, hide the review button, then report the page height.
const PREPARE = `(async () => {
  // Review controls: badges and the public preview are switched through the panel's own toggles.
  const [badges, preview] = document.querySelectorAll('.rv-toggles input');
  if (badges && badges.checked !== ${STATUS}) badges.click();
  if (preview && preview.checked !== ${PREVIEW}) preview.click();
  if (${OPEN}) document.querySelectorAll('details').forEach((d) => (d.open = true));
  document.querySelectorAll('img[loading="lazy"]').forEach((i) => (i.loading = 'eager'));
  for (let y = 0; y < document.body.scrollHeight; y += innerHeight / 2) { scrollTo(0, y); await new Promise((r) => setTimeout(r, 60)); }
  scrollTo(0, 0);
  document.querySelectorAll('.reveal').forEach((e) => e.classList.add('on', 'is-in'));
  const s = document.createElement('style');
  s.textContent = '.rv-button,.rv-panel{display:none!important} *{transition:none!important}';
  document.head.append(s);
  dispatchEvent(new Event('resize')); // re-place the review badges after the layout settles
  await Promise.all([...document.images].map((i) => i.complete ? 0 : new Promise((r) => { i.onload = i.onerror = r; })));
  await Promise.all([...document.images].map((i) => i.decode().catch(() => {}))); // async-decoded images can paint blank otherwise
  await document.fonts.ready;
  await new Promise((r) => setTimeout(r, 120));
  return document.documentElement.scrollHeight;
})()`;

try {
  const cdp = client(await devtools());
  await cdp.ready;
  await cdp.send('Page.enable');
  if (!args.includes('--motion')) {
    await cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  }
  mkdirSync(OUT, { recursive: true });
  for (const width of WIDTHS) {
    const mobile = width < 600;
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width,
      height: mobile ? 844 : 900,
      deviceScaleFactor: SCALE,
      mobile,
    });
    for (const path of PAGES) {
      const loaded = cdp.once('Page.loadEventFired');
      const nav = await cdp.send('Page.navigate', { url: BASE + path });
      if (nav.errorText) throw new Error(`Could not load ${BASE + path}: ${nav.errorText} (is npm run dev running?)`);
      await loaded;
      const { result } = await cdp.send('Runtime.evaluate', { expression: PREPARE, awaitPromise: true, returnByValue: true });
      await sleep(500);
      // Chrome can't capture more than 16384 device pixels in one go; taller pages wrap around.
      const height = Math.min(result.value, Math.floor(16384 / SCALE));
      const shot = await cdp.send('Page.captureScreenshot', {
        format: 'jpeg',
        quality: 84,
        captureBeyondViewport: true,
        clip: { x: 0, y: 0, width, height, scale: 1 },
      });
      const name = `${(path.replace(/^\/|\/$/g, '') || 'home').replace(/\//g, '-')}-${width}${SCALE !== 1 ? `@${SCALE}x` : ''}${STATUS ? '-status' : ''}${PREVIEW ? '-public' : ''}${OPEN ? '-open' : ''}.jpg`;
      writeFileSync(join(OUT, name), Buffer.from(shot.data, 'base64'));
      console.log(`  ${name}  ${width}×${height}${height < result.value ? `  (cut from ${result.value}px)` : ''}`);
    }
  }
  cdp.close();
} finally {
  chrome.kill();
  await sleep(300);
  rmSync(profile, { recursive: true, force: true });
}
