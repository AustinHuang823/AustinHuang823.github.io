#!/usr/bin/env node
// Local preview server with rebuild-on-save and live reload. No dependencies.
//
//   node serve.mjs               http://127.0.0.1:4823 (review build)
//   node serve.mjs --port 5000
//
// Pages come from dist/, images straight from .media/. Only listens on this machine.
import http from 'node:http';
import { createReadStream, existsSync, readFileSync, statSync, watch } from 'node:fs';
import { join, dirname, extname, normalize, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';

const ROOT = dirname(fileURLToPath(import.meta.url));
const DIST = join(ROOT, 'dist');
const MEDIA = join(ROOT, '.media');
const args = process.argv.slice(2);
const PORT = Number(args[args.indexOf('--port') + 1]) || 4823;

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.woff2': 'font/woff2',
  '.pdf': 'application/pdf',
  '.txt': 'text/plain; charset=utf-8',
  '.ico': 'image/x-icon',
  '.mp4': 'video/mp4',
  '.xml': 'application/xml; charset=utf-8',
};

const RELOAD_SNIPPET = '<script>new EventSource("/__reload").onmessage=()=>location.reload()</script></body>';
const clients = new Set();

let building = null;
let again = false;
function build() {
  // One build at a time; a save during a build queues exactly one more.
  if (building) {
    again = true;
    return building;
  }
  building = new Promise((resolve) => {
    // A child process, so edits to any template module are picked up.
    execFile(process.execPath, [join(ROOT, 'build.mjs')], { cwd: ROOT }, (err, stdout, stderr) => {
      process.stdout.write(stdout);
      process.stderr.write(stderr);
      if (!err) for (const res of clients) res.write('data: reload\n\n');
      resolve(!err);
    });
  }).finally(() => {
    building = null;
    if (again) {
      again = false;
      build();
    }
  });
  return building;
}

/** Map a URL path onto a file inside base, refusing anything that escapes it. */
function resolveFile(base, urlPath) {
  let decoded;
  try {
    decoded = decodeURIComponent(urlPath);
  } catch {
    return null;
  }
  const clean = normalize(decoded).replace(/^(\.\.[/\\])+/, '');
  const candidates = [clean, join(clean, 'index.html'), `${clean}.html`];
  for (const c of candidates) {
    const full = join(base, c);
    if (!full.startsWith(base + sep) && full !== base) continue;
    if (existsSync(full) && statSync(full).isFile()) return full;
  }
  return null;
}

function send(res, file, status = 200, range = null) {
  const type = TYPES[extname(file)] ?? 'application/octet-stream';
  if (type.startsWith('text/html')) {
    const body = readFileSync(file, 'utf8').replace('</body>', () => RELOAD_SNIPPET);
    res.writeHead(status, { 'content-type': type, 'cache-control': 'no-store' });
    res.end(body);
    return;
  }
  // Byte ranges: Safari won't play a video without them.
  const size = statSync(file).size;
  const headers = { 'content-type': type, 'cache-control': 'no-store', 'accept-ranges': 'bytes' };
  let opts = {};
  const m = range && /^bytes=(\d*)-(\d*)$/.exec(range);
  if (m && (m[1] || m[2])) {
    let start = m[1] ? Number(m[1]) : Math.max(0, size - Number(m[2]));
    let end = m[1] && m[2] ? Math.min(Number(m[2]), size - 1) : size - 1;
    if (start > end || start >= size) {
      res.writeHead(416, { 'content-range': `bytes */${size}` });
      res.end();
      return;
    }
    status = 206;
    headers['content-range'] = `bytes ${start}-${end}/${size}`;
    headers['content-length'] = end - start + 1;
    opts = { start, end };
  } else headers['content-length'] = size;
  const stream = createReadStream(file, opts);
  stream.on('open', () => {
    res.writeHead(status, headers);
    stream.pipe(res);
  });
  stream.on('error', () => {
    if (!res.headersSent) res.writeHead(404);
    res.end();
  });
}

const server = http.createServer((req, res) => {
  try {
    handle(req, res);
  } catch {
    // a file can vanish mid-rebuild; never let one request take the server down
    if (!res.headersSent) res.writeHead(500);
    res.end();
  }
});

function handle(req, res) {
  const url = new URL(req.url, 'http://127.0.0.1'); // never trust the Host header
  if (url.pathname === '/__reload') {
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store', connection: 'keep-alive' });
    res.write('\n');
    clients.add(res);
    req.on('close', () => clients.delete(res));
    return;
  }
  if (!url.pathname.endsWith('/') && !extname(url.pathname) && resolveFile(DIST, url.pathname + '/')) {
    res.writeHead(301, { location: url.pathname + '/' });
    res.end();
    return;
  }
  const file = url.pathname.startsWith('/media/')
    ? resolveFile(MEDIA, url.pathname.slice('/media'.length))
    : resolveFile(DIST, url.pathname);
  if (file) return send(res, file, 200, req.headers.range);
  const notFound = join(DIST, '404.html');
  if (existsSync(notFound)) return send(res, notFound, 404);
  res.writeHead(404).end('Not found');
}

let timer = null;
function schedule() {
  clearTimeout(timer);
  timer = setTimeout(build, 120);
}

await build();
for (const dir of ['src', 'public']) watch(join(ROOT, dir), { recursive: true }, schedule);
if (existsSync(MEDIA)) watch(MEDIA, (event, name) => name === 'manifest.json' && schedule());

server.listen(PORT, '127.0.0.1', () => {
  console.log(`preview: http://127.0.0.1:${PORT}  (review build, rebuilds on save)`);
});
