// Fills the media placeholders in src/site/*.html from media.json and the .media manifest.
//
//   <x-media id="vrpelvisim/or" sizes="…" alt="…"></x-media>   a responsive <img>, or a <video> for "kind": "video"
//                                                             (optional: alt, aria-label, position, loading, class)
//   <x-credit id="vrpelvisim/or"></x-credit>                  the item's credit line (as="div" for a block)
//   <!--if-media a b-->…<!--else-->…<!--end-->                 the first part only if every listed item may be
//                                                             shown; otherwise the else part (which may be empty).
//                                                             Blocks can't be nested.
//
// Anything not cleared for publication must sit inside an if-media block that lists it, so a
// --drop-blocked build can swap in the stand-in instead of leaving a hole. Review builds keep both
// parts of each block so the Review panel can preview the public page.
import { isCleared, creditLine } from './rights.mjs';

export const esc = (s) =>
  String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

const ENTITIES = { amp: '&', quot: '"', apos: "'", lt: '<', gt: '>', '#39': "'" };
const decode = (s) => s.replace(/&(amp|quot|apos|lt|gt|#39);/g, (_, e) => ENTITIES[e]);
/** Attributes of a placeholder tag, with single or double quotes, entity-decoded (they are re-escaped on output). */
const attrs = (text) => Object.fromEntries([...text.matchAll(/([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g)].map((m) => [m[1], decode(m[2] ?? m[3])]));

const IF_MEDIA = /<!--if-media ([^>]+?)-->([\s\S]*?)(?:<!--else-->([\s\S]*?))?<!--end-->/g;
const X_MEDIA = /<x-media\b([^>]*?)\s*(?:\/>|>\s*<\/x-media>)/g;
const X_CREDIT = /<x-credit\b([^>]*?)\s*(?:\/>|>\s*<\/x-credit>)/g;
const LEFTOVER = /<x-media\b|<x-credit\b|<\/x-media>|<\/x-credit>|<!--if-media|<!--else-->|<!--end-->/;
export const ID_PATTERN = /^[a-z0-9][a-z0-9_-]*(\/[a-z0-9][a-z0-9_-]*)*$/;

/** Every media id a template refers to, for validation. */
export function referencedIds(template) {
  const ids = new Set();
  for (const m of template.matchAll(IF_MEDIA)) m[1].trim().split(/\s+/).forEach((id) => ids.add(id));
  for (const re of [X_MEDIA, X_CREDIT]) for (const m of template.matchAll(re)) ids.add(attrs(m[1]).id);
  return ids;
}

/**
 * ctx: { media, manifest, review, dropBlocked, used: Set, gated: Set, dropped: Set, warn(msg) }
 *   used    items whose files the page needs (rendered <img>/<video>)
 *   gated   every item the page shows or guards a block with; all must be cleared for a public build
 * In a public build without dropBlocked every item is rendered and the caller refuses uncleared ones.
 */
export function renderPage(template, ctx) {
  const shown = (id) => ctx.review || !ctx.dropBlocked || isCleared(ctx.media[id]);
  let out = template.replace(IF_MEDIA, (_, idsText, yes, no = '') => {
    if (/<!--if-media/.test(yes) || /<!--if-media/.test(no)) throw new Error(`if-media blocks can't be nested (in the block for "${idsText.trim()}")`);
    const ids = idsText.trim().split(/\s+/);
    for (const id of ids) if (!ctx.media[id]) throw new Error(`unknown media id "${id}" in an if-media block`);
    if (ctx.review) {
      ids.forEach((id) => ctx.gated.add(id));
      const key = esc(ids.join(' '));
      const guard = (part) => part.replace(/<x-(media|credit)\b/g, `<x-$1 data-guard="${key}"`);
      return `<div class="rv-slot" data-rv="${key}">${guard(yes)}</div>` + (no.trim() ? `<div class="rv-alt" data-rv="${key}" hidden>${no}</div>` : '');
    }
    if (ids.every(shown)) {
      ids.forEach((id) => ctx.gated.add(id)); // whatever the first part shows, its ids are what was checked
      return yes;
    }
    for (const id of ids) if (!shown(id)) ctx.dropped.add(id);
    return no;
  });
  out = out.replace(X_MEDIA, (_, a) => media(attrs(a), ctx, shown));
  out = out.replace(X_CREDIT, (_, a) => credit(attrs(a), ctx, shown));
  const left = out.match(LEFTOVER);
  if (left) {
    const at = out.indexOf(left[0]);
    throw new Error(`a media placeholder was not understood: …${out.slice(Math.max(0, at - 40), at + 80).replace(/\s+/g, ' ')}…`);
  }
  return out;
}

/** An uncleared item outside a guarding block can't be swapped for a stand-in. */
function checkGuard(a, item, ctx, kind) {
  if (isCleared(item)) return;
  const guarded = (a['data-guard'] ?? '').split(' ').includes(a.id);
  const msg = `${a.id} is not cleared for publication and its <x-${kind}> is not inside an if-media block that lists it`;
  if (!ctx.review && ctx.dropBlocked) throw new Error(`${msg}; wrap it so --drop-blocked can show a stand-in`);
  if (ctx.review && !guarded) ctx.warn(`  ! ${msg}`);
}

function media(a, ctx, shown) {
  const item = ctx.media[a.id];
  if (!item) throw new Error(`unknown media id "${a.id}" in a template`);
  checkGuard(a, item, ctx, 'media');
  if (!shown(a.id)) {
    ctx.dropped.add(a.id);
    return '';
  }
  ctx.used.add(a.id);
  ctx.gated.add(a.id);
  const m = ctx.manifest[a.id];
  const mark = ctx.review ? ` data-mid="${esc(a.id)}"` : '';
  if (!m) {
    ctx.warn(`  ! ${a.id} is not generated yet (run: npm run media)`);
    return `<span class="media-missing"${mark}>${esc(a.id)}: run npm run media</span>`;
  }
  // Relative URLs, like main's assets/ paths, so the page also works from a sub-path.
  if (item.kind === 'video') {
    if (!m.video) throw new Error(`${a.id} is a video in media.json but was generated as an image; run: npm run media`);
    const poster = m.files.find((f) => f.w >= 800) ?? m.files.at(-1);
    const label = esc(a['aria-label'] ?? item.alt);
    // Same attributes as the hand-written videos on main: the page script removes controls and adds its own toggle.
    return (
      `<div class="vid"><video controls muted loop playsinline preload="none" poster="media/${esc(poster.src)}" ` +
      `src="media/${esc(m.video.src)}" width="${m.w}" height="${m.h}" aria-label="${label}"${mark}></video></div>`
    );
  }
  const files = m.files;
  const src = files.find((f) => f.w >= 1200) ?? files.at(-1);
  const srcset = files.map((f) => `media/${esc(f.src)} ${f.w}w`).join(', ');
  const pos = a.position ?? item.position;
  return (
    `<img src="media/${esc(src.src)}" srcset="${srcset}" sizes="${esc(a.sizes ?? '100vw')}" width="${m.w}" height="${m.h}" ` +
    `alt="${esc(a.alt ?? item.alt)}" loading="${esc(a.loading ?? 'lazy')}" decoding="async"` +
    (pos ? ` style="object-position:${esc(pos)}"` : '') +
    (a.class ? ` class="${esc(a.class)}"` : '') +
    `${mark}>`
  );
}

function credit(a, ctx, shown) {
  const item = ctx.media[a.id];
  if (!item) throw new Error(`unknown media id "${a.id}" in an x-credit`);
  checkGuard(a, item, ctx, 'credit');
  if (!shown(a.id)) return '';
  ctx.gated.add(a.id);
  const tag = a.as === 'div' ? 'div' : 'span';
  const mark = ctx.review ? ` data-credit="${esc(a.id)}"` : '';
  return `<${tag} class="credit${a.class ? ` ${esc(a.class)}` : ''}"${mark}>${esc(creditLine(item))}</${tag}>`;
}
