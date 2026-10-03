# austinhuang823.github.io: live design, new materials

Austin Huang's portfolio in the design of the live site (`main`: one page, Obsidian/Heritage
themes, the inverse-kinematics arm, project cards and expandable rows), with its images and videos
regenerated from the portfolio-sources materials folder instead of being committed to Git.
**Live at https://austinhuang823.github.io/ since 2026-10-03**, published from this repo's `main` by
`npm run deploy` (see "Publishing"). Deploy only with Austin's OK.

The copy and layout are main's. What changed is the media: higher-resolution versions of every image,
a 1080p HoloLens clip in place of the 274 px GIF, new pictures in rows that had none, a credit on every
image, and a rights gate on the public build.

No npm dependencies. Node (built-in modules only) builds the page; Python with Pillow and PyMuPDF
makes the images, and ffmpeg the videos. All of it was already on Austin's Mac
(Node 20.12, Anaconda Python 3.10, Homebrew ffmpeg).

## Run it

```bash
cd ~/Developer/AustinHuang823.github.io
npm run media    # web images and videos from portfolio-sources (first time, and after media changes)
npm run dev      # preview at http://127.0.0.1:4823, rebuilds on save
```

In the preview, the **Review** button (bottom left) lists every image and video on the page with its
rights status, credit and who to ask; it can draw the status on each image and preview what the public
build would show today.

Screenshots for people who won't run the site (uses the Chrome already on the Mac; needs `npm run dev`):

```bash
npm run shoot -- --out shots                      # full page at 1440 and 390 px
npm run shoot -- --out shots --scale 2 --open     # retina, every project row expanded
npm run shoot -- --out shots --status --preview   # rights badges / the public build's stand-ins
```

## Where things live

| What | Where | In Git? |
|---|---|---|
| This repo | `~/Developer/AustinHuang823.github.io` (`~/Documents` is iCloud-synced, so the repo is not there) | yes |
| Source material | `~/Documents/Myfile/Portfolio and Media/portfolio-sources/` (iCloud, backed up) | **never** |
| Web images and videos | `.media/` here, made by `npm run media` | no |
| Builds | `dist/` (review build), `dist-public/` (public build) | no |

Inside portfolio-sources:

```
<project-slug>/          one folder per project: own and published images and videos, plus _contact-sheet.jpg
about/                   portraits
ALL_SOURCES.csv          every file: source URL, owner or photographer, size, rights, who to ask
READINESS.md             phase-one readiness: measured sizes, placeholders, gaps
PROJECTS.md              the project list and Austin's role in each
PERMISSIONS.md           who to ask for which image, with draft emails (nothing sent)
_originals/              documents as received (résumé, posters, reports) for figure extraction
_permissions/<holder>/   file each permission email or licence here when it arrives
```

Set `PORTFOLIO_SOURCES=/path/to/portfolio-sources` if the folder ever moves.

## Layout of this repo

```
src/site/index.html      the page: main's index.html, with <x-media> placeholders where images and videos go
src/site/404.html        main's 404 page
src/site/icon.svg        the "a." icon; npm run media renders favicon.ico and the PNG icons from it
src/site/render.mjs      fills the placeholders (responsive <img>, <video>, credits, if-media blocks)
src/site/rights.mjs      what may go public, credit lines, who to ask
src/content/media.json   every image and video: source file, rights, holder, contact, credit, licence, caption, alt
src/review/              the Review panel (review builds only)
scripts/sources.py       catalogue: measure every source file, sync ALL_SOURCES.csv, draw contact sheets
scripts/register.py      add a catalogued file to media.json; sync its rights from the catalogue
scripts/media.py         portfolio-sources → .media/: sRGB WebP sizes, H.264 clips + posters, social card, icons
scripts/shoot.mjs        screenshots via local Chrome
build.mjs, serve.mjs     build and local preview
public/                  fonts (OFL), résumé and poster PDFs, copied into every build
tools/analytics/         GoatCounter reporting (unchanged from main); validate_site.py checks src/site/
```

### Placeholders in src/site/index.html

```html
<x-media id="vrpelvisim/or" sizes="(max-width: 900px) calc(100vw - 48px), 513px" alt="…"></x-media>
<x-credit id="vrpelvisim/or"></x-credit>

<!--if-media clashbots/clip-->
  …markup that uses the clip…
<!--else-->
  …what the public build shows until the clip is cleared (may be empty)…
<!--end-->
```

`<x-media>` becomes a responsive `<img>` (srcset of the generated widths, `width`/`height` for no
layout shift, lazy loading), or a `<video>` with the same attributes main used for an entry with
`"kind": "video"`. Optional attributes: `alt`, `aria-label`, `position` (object-position), `loading`,
`class`. `<x-credit>` prints the credit line (`as="div"` for a block). Edit the rest of the page
exactly as before: it is plain HTML, CSS and JavaScript.

## Adding or replacing material

Images and videos never go into Git. They stay in portfolio-sources; the repo records where each one
comes from, who owns it and how to credit it.

1. **Put the file in the project's folder** in portfolio-sources. Name it
   `<prefix><what-it-shows>-<NN>.<ext>`: `own_` for Austin's own photos, frames and figures; the
   source for everything else (`xtalpi_`, `ncats_`, `press_`, `gh_`, `tv_`, …). Get the largest
   version that exists.
2. **Catalogue it:** `npm run sources`. It measures every file, adds a row for anything new (with
   empty rights) and redraws the project's `_contact-sheet.jpg`. Fill in the row in `ALL_SOURCES.csv`:
   `rights`, `owner`, `credit`, `license`, `permission_contact`, `source_url`, `page_url`, `caption`.
3. **Register it** in `src/content/media.json`:
   ```bash
   npm run register -- add <project>/<file> --id <project>/<name> --kind photo --alt "what it shows"
   ```
   This copies rights, holder, contact, credit, licence label, source URL and caption from the
   catalogue row; `kind` is photo, frame, screen, figure, render, portrait or video. After that,
   media.json owns the display strings (shorten a credit there; card credits sit on the image). A
   source can also be a pixel `crop`, part of a PDF page, a video frame, or (for `"kind": "video"`) a
   clip with `start`/`end` seconds or an animated GIF: see the top of `scripts/media.py`. Give a clip a
   `"name"` to keep its file name stable: the page's analytics count plays by file name, so the four
   clips keep main's names (`clashbots`, `perception_demo`, `rdkdc_imagedrawing`, `segmentation`). To
   replace an image, keep the id and change its `source`.
4. **Run `npm run media`.** It only processes new or changed entries (including a source file that was
   replaced under the same name), converts colour profiles to sRGB, strips audio from clips, warns if
   media.json and ALL_SOURCES.csv disagree about rights, and refuses anything the catalogue marks
   confidential.
5. **Place it on the page** with `<x-media>` and `<x-credit>` in `src/site/index.html`. If it is not
   cleared yet, wrap it in an `if-media` block with a stand-in (or nothing) for the public build.
6. **Check it** with `npm run dev` and the Review panel.
7. **Commit the JSON and HTML** (never the image). `npm run build` refuses unknown ids, missing alt text
   or credits, public images without a licence, and anything registered as confidential.

Before publishing a video clip of real places, watch it for bystanders and readable plates: the HoloLens
clip starts at 28.5 s of the master because a passer-by crosses it earlier.

## Rights, credits and the public build

Four statuses, used the same way in ALL_SOURCES.csv and media.json:

| `rights` | 中文 | Meaning | Before it can be public |
|---|---|---|---|
| `own` | 自己的 | Austin's own work: his photos, video, figures, team course projects | nothing (team projects credit the team) |
| `public` | 公開可用 | Public domain (incl. U.S. federal works), CC0, CC BY, CC BY-SA, CC BY-NC | print the credit and licence (automatic) |
| `needs-permission` | 需要授權 | Company sites, press material, broadcast footage, course or publisher figures | the holder agrees, in writing |
| `confidential` | 機密不能用 | Internal or NDA material | never: not stored, not registered |

Every image and video shows a credit line (on the image in cards, under it elsewhere); public ones add
their licence, permitted ones add "used with permission".

When a holder agrees, file the email or licence in `portfolio-sources/_permissions/<holder>/`, then
record it on the entry in media.json, naming the exact file they agreed to:

```json
"permission": { "status": "granted", "date": "2026-11-02", "source": "clash-bots/tv_clash-bots-broadcast-clip-01.mp4", "note": "holder's written OK, filed in _permissions/iqiyi/" }
```

and note it in the file's `ALL_SOURCES.csv` row. A permission covers that file only. `status` can
also be `requested` or `refused`; only `granted` clears an image.

`npm run build:public` builds what a visitor would get into `dist-public/`. It **stops**, lists each
item with who to ask, and deletes any older `dist-public/` if the page uses (or guards a block with)
an image or video that is:

- not cleared (own, public, or permission granted for this exact file),
- not regenerated since its `source` entry or the source file itself changed (run `npm run media`), or
- registered with different rights than its ALL_SOURCES.csv row (they must match exactly; the
  catalogue must be readable, so the build fails closed without it).

The social card is cut from the image media.json `_og` names, so it obeys the same rules, and the
build refuses to go on without it or the icons. Any other failure also leaves no `dist-public/`:
builds are written to `<folder>-partial` and only moved into place when complete. A review build
can't be written into `dist-public/`.

`npm run build:public -- --drop-blocked` builds anyway: each uncleared item is replaced by its
`<!--else-->` stand-in or left out. An uncleared item outside an `if-media` block stops a
`--drop-blocked` build, because there would be nothing to show in its place. Since October 2026 the
page uses nothing that needs permission (Austin's call: the Clash Bots card shows his own build photo
instead of iQIYI's broadcast clip, and the stereotactic-navigation row has a schematic drawn for the
site instead of the course figure), so the plain `npm run build:public` goes through. Both are still
catalogued in ALL_SOURCES.csv; register them again if permission ever arrives. media.json holds only
what the page uses. `dist-public/` is the only thing that is ever deployed; it has no review code,
contacts or `data-` hooks.

## NDA

Work at XtalPi, Axle Informatics / NCATS, Dynacolor, iQIYI and the JHU–Sanaria lab may be covered by
NDAs. Only material those organisations published, or Austin's own non-confidential work, is used:
no internal screenshots, code, data, decks or photos. XtalPi's pharma partner is never named, and
there are no diagrams of XtalPi systems (the production card keeps main's gauge).

## Publishing

GitHub Pages serves the site from a GitHub Actions deployment, not from the files in `main`, so the
generated images and videos never enter Git:

```bash
npm run deploy    # strict public build → release asset site.tar.gz → .github/workflows/deploy-pages.yml
gh run watch      # follow the deploy, then check https://austinhuang823.github.io/
```

`scripts/deploy.mjs` refuses to run with uncommitted changes, builds `dist-public/` with the strict
gates, attaches it to a new release (`site-YYYY-MM-DD-HHMM`, notes name the commit it was built from)
and starts the workflow on `main`, which downloads that asset and publishes it. Only `main` may deploy
to the `github-pages` environment. To roll back, re-run the workflow with an older tag:
`gh workflow run deploy-pages.yml --ref main -f tag=site-…`.

Pushing to `main` does not change the live site; only a deploy does. Analytics: main's privacy-gated
GoatCounter script (site code `austinhuang823`) is unchanged and only runs on austinhuang823.github.io,
never in the local preview. `python3 tools/analytics/validate_site.py` and
`node tools/analytics/tests/tracker_test.cjs` check it.
