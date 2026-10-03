#!/usr/bin/env node
// Static build with no dependencies beyond Node itself. The page is the live site's single-page design
// (src/site/index.html); this fills in its images and videos from the materials pipeline.
//
//   node build.mjs                          review build into dist/ (Review panel, noindex)
//   node build.mjs --public                 what a visitor would get, in dist-public/: no review tools, media
//                                           copied in. It STOPS if the page uses an image or video that is
//                                           not cleared, not generated from its current source file, or not
//                                           cleared in the ALL_SOURCES.csv catalogue.
//   node build.mjs --public --drop-blocked  the same, but uses each uncleared item's stand-in (or nothing)
//   node build.mjs --out <dir>              build somewhere else (a new or empty folder, or an earlier build)
//
// Images are not built here: run `npm run media` first (see README). A failed public build never
// leaves a folder behind: the output is written to <out>-partial and only renamed into place at the end.
import { readFileSync, writeFileSync, mkdirSync, rmSync, cpSync, existsSync, readdirSync, statSync, renameSync, realpathSync } from 'node:fs';
import { join, dirname, resolve, relative, isAbsolute, sep, basename } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isDeepStrictEqual } from 'node:util';
import { createHash } from 'node:crypto';

const ROOT = dirname(fileURLToPath(import.meta.url));
const SITE_URL = 'https://austinhuang823.github.io/';
const PAGES = ['index.html', '404.html']; // templates in src/site/, written to the same names
const STAMP = '.portfolio-build'; // marks folders this script created, so it only ever clears its own output
// Generated site files (from npm run media) and where the page expects them: the same URLs as on main.
const SITE_FILES = {
  'site/og-card.jpg': 'assets/img/og-card.jpg',
  'site/favicon-96.png': 'assets/img/favicon-96.png',
  'site/apple-touch-icon.png': 'assets/img/apple-touch-icon.png',
  'site/favicon.ico': 'favicon.ico',
};
const read = (p) => JSON.parse(readFileSync(join(ROOT, p), 'utf8'));
const sha1 = (buf) => createHash('sha1').update(buf).digest('hex');

async function modules() {
  // Fresh import each time so the dev server picks up edits to the render code.
  const stamp = `?t=${Date.now()}`;
  const rights = await import(pathToFileURL(join(ROOT, 'src/site/rights.mjs')).href + stamp);
  const render = await import(pathToFileURL(join(ROOT, 'src/site/render.mjs')).href + stamp);
  return { ...rights, ...render };
}

function sourcesDir() {
  return process.env.PORTFOLIO_SOURCES
    ? resolve(process.env.PORTFOLIO_SOURCES.replace(/^~/, homedir()))
    : join(homedir(), 'Documents', 'Myfile', 'Portfolio and Media', 'portfolio-sources');
}

function loadContent() {
  const media = read('src/content/media.json');
  const manifest = existsSync(join(ROOT, '.media/manifest.json')) ? read('.media/manifest.json') : {};
  const templates = Object.fromEntries(PAGES.map((p) => [p, readFileSync(join(ROOT, 'src/site', p), 'utf8')]));
  return { media, manifest, templates };
}

/** Catch the mistakes that would otherwise show up as a blank image, a dead link or a missing credit. */
function validate({ media, templates }, { RIGHTS, sourceKey, referencedIds, ID_PATTERN }) {
  const problems = [];
  const warnings = [];
  for (const [id, item] of Object.entries(media)) {
    if (id.startsWith('_')) continue;
    const where = `media ${id}`;
    if (!ID_PATTERN.test(id)) problems.push(`${where}: ids are lowercase words joined by "/", "-" or "_" (they become file names and URLs)`);
    if (!RIGHTS.includes(item.rights)) problems.push(`${where}: rights must be one of ${RIGHTS.join(', ')}`);
    if (item.rights === 'confidential') problems.push(`${where}: confidential material must never be registered; remove it`);
    if (!sourceKey(item)) problems.push(`${where}: source needs "file", "video" or "pdf"`);
    if (!item.alt) problems.push(`${where}: missing alt text`);
    if (!item.credit) problems.push(`${where}: missing credit line`);
    if (item.rights === 'public' && !item.license) problems.push(`${where}: public images need the licence (e.g. "CC BY 4.0")`);
    if (item.rights === 'needs-permission' && !item.holder) problems.push(`${where}: needs-permission images must name the holder`);
    if (item.rights === 'needs-permission' && !item.contact) warnings.push(`${where}: no contact recorded for ${[].concat(item.holder).join(', ')}`);
    if (item.name && !/^[a-z0-9][a-z0-9_-]*$/.test(item.name)) problems.push(`${where}: "name" must be a plain file name without extension`);
    const perm = item.permission;
    if (perm) {
      if (!['granted', 'requested', 'refused'].includes(perm.status)) problems.push(`${where}: permission.status must be granted, requested or refused`);
      if (perm.status === 'granted' && (!perm.date || !perm.source)) {
        problems.push(`${where}: a granted permission needs "date" and "source" (the file it covers: ${sourceKey(item)})`);
      } else if (perm.status === 'granted' && perm.source !== sourceKey(item)) {
        warnings.push(`${where}: permission was granted for ${perm.source}, but the image now comes from ${sourceKey(item)}; it is not cleared until the holder OKs the new file`);
      }
    }
  }
  const og = media._og;
  if (og && !media[og.media]) problems.push(`media.json _og: unknown media id "${og.media}"`);
  else if (og && media[og.media].kind === 'video') problems.push('media.json _og: the social card must come from an image entry, not a video');
  for (const [page, text] of Object.entries(templates)) {
    for (const id of referencedIds(text)) if (!media[id]) problems.push(`src/site/${page}: unknown media id "${id}"`);
  }
  return { problems, warnings };
}

/* ---------- public-build gates ---------- */

/** Minimal quote-aware CSV reader (RFC 4180), enough for ALL_SOURCES.csv. */
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  text = text.replace(/^﻿/, '');
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') {
      row.push(field);
      field = '';
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else field += c;
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  const [head, ...body] = rows.filter((r) => r.some((v) => v !== ''));
  return body.map((r) => Object.fromEntries(head.map((h, i) => [h.trim(), (r[i] ?? '').trim()])));
}

const RIGHTS_ALIASES = { 自己的: 'own', 公開可用: 'public', 需要授權: 'needs-permission', 機密不能用: 'confidential' };

/** The materials catalogue is the last word on rights: fail closed if it can't be read, and require agreement. */
function catalogueProblems(media, ids, { sourceKey }) {
  const csvPath = join(sourcesDir(), 'ALL_SOURCES.csv');
  if (!existsSync(csvPath)) return [`cannot read the catalogue at ${csvPath} (set PORTFOLIO_SOURCES)`];
  const rows = new Map(parseCsv(readFileSync(csvPath, 'utf8')).map((r) => [`${r.project}/${r.file}`, r]));
  const problems = [];
  for (const id of ids) {
    const item = media[id];
    const key = sourceKey(item);
    const row = rows.get(key);
    const rights = RIGHTS_ALIASES[row?.rights] ?? row?.rights?.toLowerCase();
    if (!row) problems.push(`${id}: ${key} has no row in ALL_SOURCES.csv`);
    else if (rights === 'confidential') problems.push(`${id}: ${key} is marked confidential in ALL_SOURCES.csv`);
    // own and public print different credits (a licence for public), so they must match exactly too
    else if (rights !== item.rights) problems.push(`${id}: media.json says ${item.rights}, but ALL_SOURCES.csv says ${row.rights || '(empty)'}`);
  }
  return problems;
}

/** The size and modification time of a source file, as media.py records them. */
function fingerprint(key) {
  try {
    const st = statSync(join(sourcesDir(), key));
    return [st.size, Math.floor(st.mtimeMs / 1000)];
  } catch {
    return null;
  }
}

/** Web copies must have been generated from the source media.json names now, and from that file as it is now. */
function staleMedia({ media, manifest }, ids, { sourceKey }) {
  return ids.filter((id) => {
    const m = manifest[id];
    const item = media[id];
    if (!m) return true;
    if (item.kind === 'video' && !m.video) return true;
    if (!isDeepStrictEqual(m.spec, item.source)) return true;
    return !m.fingerprint || !isDeepStrictEqual(m.fingerprint, fingerprint(sourceKey(item)));
  });
}

/** The social card and icons: generated from the current _og image and the current icon.svg. */
function staleSite({ media, manifest }, { sourceKey }) {
  const site = manifest._site ?? {};
  const og = media._og;
  const stale = [];
  if (!og) stale.push('media.json has no "_og" entry, but the page links the social card (assets/img/og-card.jpg)');
  else if (
    !site.og ||
    site.og.media !== og.media ||
    !isDeepStrictEqual(site.og.spec, media[og.media].source) ||
    !isDeepStrictEqual(site.og.fingerprint, fingerprint(sourceKey(media[og.media])))
  ) {
    stale.push(`the social card (from ${og.media})`);
  }
  const svg = join(ROOT, 'src/site/icon.svg');
  if (!site.icons || !existsSync(svg) || site.icons.svg !== sha1(readFileSync(svg))) stale.push('the site icons (from src/site/icon.svg)');
  for (const from of Object.keys(SITE_FILES)) if (!existsSync(join(ROOT, '.media', from))) stale.push(`${from} is missing`);
  return stale;
}

/* ---------- output folder safety ---------- */

/** Resolve --out and refuse anything that isn't clearly a build folder. */
function safeOut(outArg, pub) {
  const out = resolve(ROOT, outArg ?? (pub ? 'dist-public' : 'dist'));
  const rel = relative(ROOT, out);
  const inRepo = !rel.startsWith('..') && !isAbsolute(rel);
  if (out === ROOT || !relative(out, ROOT).startsWith('..')) throw new Error(`--out ${out} would contain the repo; refusing`);
  if (inRepo && !/^dist[\w-]*$/.test(rel.split(sep)[0])) {
    throw new Error(`--out inside the repo must be dist/, dist-public/ or another dist-* folder (got ${rel})`);
  }
  // dist-public is what gets deployed: never put a review build (contacts, review tools) there.
  if (!pub && /^dist-public/.test(basename(out))) throw new Error(`a review build can't go into ${basename(out)}; use dist/ (or add --public)`);
  if (existsSync(out)) {
    if (!statSync(out).isDirectory()) throw new Error(`--out ${out} is a file`);
    const known = inRepo && ['dist', 'dist-public'].includes(rel); // folders made before the stamp existed
    if (readdirSync(out).length && !existsSync(join(out, STAMP)) && !known) {
      throw new Error(`--out ${out} already has files this script did not create; use a new or empty folder`);
    }
  }
  return out;
}

/* ---------- review build extras ---------- */

function reviewData(content, ids, mod) {
  const items = {};
  for (const id of ids) {
    const item = content.media[id];
    const m = content.manifest[id];
    const status = mod.rightsStatus(item, m?.quality);
    items[id] = {
      kind: item.kind ?? 'photo',
      cleared: mod.isCleared(item),
      level: status.level,
      label: status.label,
      short: status.short,
      credit: mod.creditLine(item),
      holder: mod.holderText(item),
      contact: item.rights === 'needs-permission' ? item.contact ?? '' : '',
      source: mod.sourceKey(item),
      size: m ? `${m.w}×${m.h}` : 'not generated',
      quality: m?.quality ?? '',
    };
  }
  // </script> can't appear inside the JSON, so a credit can never break out of the data block.
  return JSON.stringify({ items }).replace(/</g, '\\u003c');
}

function injectReview(htmlText, data, assets) {
  // Replacer functions: a "$" in a credit must never be read as a replacement pattern.
  return htmlText
    .replace('</head>', () => `<meta name="robots" content="noindex">\n<link rel="stylesheet" href="${assets['review.css']}">\n</head>`)
    .replace('</body>', () => `<script type="application/json" id="review-data">${data}</script>\n<script src="${assets['review.js']}" defer></script>\n</body>`);
}

const localDate = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/* ---------- build ---------- */

export async function build({ review = true, out = join(ROOT, 'dist'), copyMedia = !review, quiet = false, dropBlocked = false } = {}) {
  const t0 = Date.now();
  const partial = `${out}-partial`;
  try {
    return await buildInto({ review, out, partial, copyMedia, quiet, dropBlocked, t0 });
  } catch (e) {
    rmSync(partial, { recursive: true, force: true });
    // A public build that didn't finish must not leave an older one behind to be deployed by mistake.
    if (!review && existsSync(out)) rmSync(out, { recursive: true, force: true });
    throw e;
  }
}

async function buildInto({ review, out, partial, copyMedia, quiet, dropBlocked, t0 }) {
  const mod = await modules();
  const content = loadContent();
  const { problems, warnings: checks } = validate(content, mod);
  if (problems.length) {
    console.error(problems.map((p) => `  ✗ ${p}`).join('\n'));
    throw new Error(`${problems.length} content problem(s), see above`);
  }
  if (!quiet) for (const w of checks) console.warn(`  ! ${w}`);

  const warnings = new Set();
  const used = new Set();
  const gated = new Set();
  const dropped = new Set();
  const ctx = { media: content.media, manifest: content.manifest, review, dropBlocked: !review && dropBlocked, used, gated, dropped, warn: (m) => warnings.add(m) };
  const pages = Object.entries(content.templates).map(([name, text]) => [name, mod.renderPage(text, ctx)]);
  const og = content.media._og;
  if (og) gated.add(og.media); // the social card is cut from this image, so it must be cleared too

  if (!review && dropBlocked && dropped.size && !quiet) {
    console.warn(`  ! --drop-blocked: left out ${dropped.size} item(s) that are not cleared yet (stand-ins used where the page has one):`);
    for (const id of [...dropped].sort()) console.warn(`      ${id}`);
  }

  // The public build is the only thing that may ever be deployed, so it refuses any item that is
  // not cleared (own work, an open licence, or permission granted for this exact file), any item
  // whose web copies were made from a different or since-changed source, and anything the catalogue
  // disagrees with.
  if (!review) {
    const ids = [...gated];
    const stop = (title, lines, hint) => {
      throw new Error(`Public build stopped: ${title}\n${lines.map((l) => `  ✗ ${l}`).join('\n')}\n${hint}`);
    };
    const blocked = ids.filter((id) => !mod.isCleared(content.media[id]));
    if (blocked.length) {
      const cardBlocked = og && blocked.includes(og.media) && !used.has(og.media);
      stop(
        `${blocked.length} item(s) are not cleared for publication.`,
        blocked.map((id) => {
          const m = content.media[id];
          const role = og && id === og.media ? ' [the social card is cut from it]' : '';
          return `${id}${role}  (${m.rights}; ask: ${mod.holderText(m)}${m.contact ? ` — ${m.contact}` : ''})`;
        }),
        cardBlocked
          ? 'Point media.json "_og" at a cleared image (the social card has no stand-in), then npm run media.'
          : 'Record permission in src/content/media.json (permission.status "granted", with date and source), take the item\n' +
              'off the page, or build with each uncleared item swapped for its stand-in: npm run build:public -- --drop-blocked',
      );
    }
    const stale = [...staleMedia(content, ids, mod), ...staleSite(content, mod)];
    if (stale.length) stop(`${stale.length} generated file(s) are missing or older than their source.`, stale, 'Run: npm run media');
    const cat = catalogueProblems(content.media, ids, mod);
    if (cat.length) stop('the catalogue disagrees.', cat, 'Fix the row in ALL_SOURCES.csv or the entry in media.json, then build again.');
  }

  rmSync(partial, { recursive: true, force: true });
  mkdirSync(partial, { recursive: true });
  writeFileSync(join(partial, STAMP), `Built by build.mjs (${review ? 'review build: never deploy' : 'public build'}); safe to delete and rebuild.\n`);
  cpSync(join(ROOT, 'public'), partial, { recursive: true });

  // Site icons and the social card live at fixed URLs. The card is copied only if it was cut from the
  // image _og names now; a public build has already refused to go on without them.
  const site = content.manifest._site ?? {};
  for (const [from, to] of Object.entries(SITE_FILES)) {
    const src = join(ROOT, '.media', from);
    const ogMismatch = from === 'site/og-card.jpg' && (!og || site.og?.media !== og.media);
    if (!existsSync(src) || ogMismatch) {
      warnings.add(`  ! ${from} is missing or out of date (run: npm run media)`);
      continue;
    }
    mkdirSync(dirname(join(partial, to)), { recursive: true });
    cpSync(src, join(partial, to));
  }
  if (copyMedia) {
    for (const id of used) {
      const m = content.manifest[id];
      for (const f of [...(m?.files ?? []).map((x) => x.src), ...(m?.video ? [m.video.src] : [])]) {
        mkdirSync(dirname(join(partial, 'media', f)), { recursive: true });
        cpSync(join(ROOT, '.media', f), join(partial, 'media', f));
      }
    }
  }

  const assets = {};
  if (review) {
    mkdirSync(join(partial, 'assets'), { recursive: true });
    for (const name of ['review.js', 'review.css']) {
      const buf = readFileSync(join(ROOT, 'src/review', name));
      writeFileSync(join(partial, 'assets', name), buf);
      assets[name] = `/assets/${name}?v=${sha1(buf).slice(0, 8)}`;
    }
  }
  const data = review ? reviewData(content, [...gated], mod) : '';
  for (const [name, text] of pages) {
    writeFileSync(join(partial, name), review && name === 'index.html' ? injectReview(text, data, assets) : text);
  }
  writeFileSync(
    join(partial, 'sitemap.xml'),
    `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n  <url>\n    <loc>${SITE_URL}</loc>\n    <lastmod>${localDate()}</lastmod>\n  </url>\n</urlset>\n`,
  );
  writeFileSync(
    join(partial, 'robots.txt'),
    review ? 'User-agent: *\nDisallow: /\n' : `User-agent: *\nAllow: /\n\nSitemap: ${SITE_URL}sitemap.xml\n`,
  );

  // Swap the finished build into place.
  rmSync(out, { recursive: true, force: true });
  renameSync(partial, out);
  if (warnings.size) console.warn([...warnings].join('\n'));
  if (!quiet) {
    console.log(`built ${pages.length} pages with ${used.size} images/videos in ${Date.now() - t0} ms → ${out}${review ? ' (review build)' : ' (public build)'}`);
  }
  return { pages: pages.length, used: [...used], dropped: [...dropped] };
}

const isMain = (() => {
  try {
    return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(process.argv[1]);
  } catch {
    return false;
  }
})();

if (isMain) {
  const args = process.argv.slice(2);
  const pub = args.includes('--public');
  const outArg = args.includes('--out') ? args[args.indexOf('--out') + 1] : undefined;
  try {
    // Public builds go to their own folder so they never clobber the running preview.
    const out = safeOut(outArg, pub);
    await build({ review: !pub, out, copyMedia: pub || args.includes('--copy-media'), dropBlocked: args.includes('--drop-blocked') });
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
}
