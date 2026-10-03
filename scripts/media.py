#!/usr/bin/env python3
"""
Make web-sized images and videos for the site from the portfolio-sources folder (the "thumbnail script").

    npm run media                                   # build what is missing or changed
    npm run media -- --force                        # rebuild everything
    npm run media -- --only vrpelvisim/ clash-bots/ # ids or id prefixes

Reads  src/content/media.json        what to make, from which source file, with rights and credits
       <sources>/ALL_SOURCES.csv     the materials catalogue (rights are cross-checked against it)
       src/site/icon.svg             the site icon (rendered to the favicon and home-screen PNGs)
Writes .media/<id>-<width>.webp, .media/<id>.mp4 + <id>-poster-<width>.webp for videos,
       .media/site/ (social card, icons) and .media/manifest.json (all gitignored, never committed)

Sources are only read, never changed. The default sources folder is
~/Documents/Myfile/Portfolio and Media/portfolio-sources; set PORTFOLIO_SOURCES=/path/to/folder
to use another one.

A media.json source can be:
  {"file": "clash-bots/own_build-01.jpg"}                       an image file
  {"file": "...", "crop": [x0, y0, x1, y1]}                      a pixel crop of it
  {"pdf": "_originals/own_poster.pdf", "page": 1,
   "clip": [x0, y0, x1, y1], "scale": 2.5}                       part of a PDF page (clip in PDF points;
                                                                 "scale" for raster regions, otherwise
                                                                 vector regions render 3200 px wide)
  {"video": "vrpelvisim/own_vrdemo1.mp4", "t": 12.5}             one frame of a video (needs ffmpeg)

An entry with "kind": "video" becomes a muted, looping web video (H.264 MP4, no audio) plus a poster:
  {"video": "hololens-fov/own_demo.mp4", "start": 28, "end": 57}  a clip of a video, in seconds
  {"file": "ur5-manipulation/gh_demo.gif"}                       an animated GIF
  optional on the entry: "max_width" (default 1280), "crf" (default 26; higher = smaller file) and
  "name" (the clip's file name, e.g. "perception_demo": the page's analytics name videos by file name)

media.json "_og": {"media": "<id>", "focus": [x, y]} names the image cropped into the 1200x630 social
card; focus is the point to keep, 0-1 from the top left.

Needs Pillow and PyMuPDF (both already installed on Austin's Mac via Anaconda); ffmpeg for video.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageCms, ImageOps

try:
    import fitz  # PyMuPDF
except ImportError:  # only needed for "pdf" sources and the icon
    fitz = None

SITE = Path(__file__).resolve().parent.parent
REGISTRY = SITE / "src" / "content" / "media.json"
ICON = SITE / "src" / "site" / "icon.svg"
OUT = SITE / ".media"
MANIFEST = OUT / "manifest.json"
DEFAULT_SOURCES = Path.home() / "Documents" / "Myfile" / "Portfolio and Media" / "portfolio-sources"

WIDTHS = [480, 800, 1200, 1600, 2400, 3200]
POSTER_WIDTHS = [480, 800, 1280]
MAX_LONG_EDGE = 3200          # vector PDF regions are rendered so their long edge is this
VIDEO_MAX_WIDTH = 1280
OG_SIZE = (1200, 630)
QUALITY = {"figure": 90, "screen": 88, "photo": 82, "frame": 84, "render": 84, "portrait": 84, "video": 84}
PIPELINE_VERSION = 3          # bump to force a rebuild after changing this script
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*(/[a-z0-9][a-z0-9_-]*)*$")
RIGHTS_ALIASES = {"自己的": "own", "公開可用": "public", "需要授權": "needs-permission", "機密不能用": "confidential"}


def find_sources():
    env = os.environ.get("PORTFOLIO_SOURCES")
    path = Path(env).expanduser() if env else DEFAULT_SOURCES
    if not path.is_dir():
        sys.exit(
            f"Could not find the portfolio-sources folder at {path}.\n"
            "Set PORTFOLIO_SOURCES=/path/to/portfolio-sources and run again."
        )
    return path


def load_catalogue(sources):
    """ALL_SOURCES.csv rows keyed by 'project/file', for the rights cross-check."""
    path = sources / "ALL_SOURCES.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    for r in rows:
        r["rights"] = RIGHTS_ALIASES.get(r.get("rights", ""), r.get("rights", "").lower())
    return {f"{r['project']}/{r['file']}": r for r in rows if r.get("file")}


def source_path(item, sources):
    src = item["source"]
    return sources / (src.get("file") or src.get("video") or src.get("pdf") or "")


def fingerprint(path):
    """Size and modification time of a source file; build.mjs compares this before publishing."""
    try:
        st = path.stat()
        return [st.st_size, int(st.st_mtime)]
    except OSError:
        return None


def spec_hash(item, sources):
    """Changes when the entry, the script version or the source file itself (size, mtime) changes."""
    blob = json.dumps(
        {
            "source": item["source"],
            "kind": item.get("kind"),
            "quality": item.get("quality"),
            "video": [item.get("max_width"), item.get("crf"), item.get("name")],
            "v": PIPELINE_VERSION,
            "file": fingerprint(source_path(item, sources)),
        },
        sort_keys=True,
    )
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


_pdf_cache = {}


def load_pdf(path):
    if fitz is None:
        sys.exit("PyMuPDF (fitz) is needed for images rendered from a PDF.")
    if path not in _pdf_cache:
        _pdf_cache[path] = fitz.open(path)
    return _pdf_cache[path]


SRGB = ImageCms.createProfile("sRGB")


def to_srgb(im, icc):
    """Convert to sRGB using the embedded ICC profile (Adobe RGB, Display P3, CMYK…), so colours
    don't shift when the web copy is saved without a profile."""
    if not icc:
        return im.convert("RGB")
    try:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if im.mode == "RGB" and "srgb" in ImageCms.getProfileDescription(src).lower():
            return im
        return ImageCms.profileToProfile(im, src, SRGB, outputMode="RGB")
    except Exception:
        return im.convert("RGB")


def flatten(im):
    """sRGB on white, whatever the source mode (CMYK, palette, alpha) or colour profile, with EXIF rotation applied."""
    icc = im.info.get("icc_profile")
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return to_srgb(bg, icc)
    if im.mode not in ("RGB", "CMYK"):
        im = im.convert("RGB")
    return to_srgb(im, icc)


def ffmpeg_bin(name="ffmpeg"):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} is needed for video sources")
    return path


def video_frame(path, t):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "frame.png"
        subprocess.run(
            [ffmpeg_bin(), "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", str(out)],
            check=True,
        )
        with Image.open(out) as im:
            im.load()
            return im.convert("RGB")


def open_source(item, sources):
    src = item["source"]
    if "file" in src:
        path = sources / src["file"]
        with Image.open(path) as im:
            im.load()
            im = flatten(im)
    elif "video" in src:
        path = sources / src["video"]
        im = video_frame(path, src.get("t", src.get("start", 0)))
    elif "pdf" in src:
        path = sources / src["pdf"]
        doc = load_pdf(path)
        page = doc[src.get("page", 1) - 1]
        clip = fitz.Rect(*src["clip"]) if "clip" in src else page.rect
        zoom = float(src["scale"]) if "scale" in src else src.get("long", MAX_LONG_EDGE) / max(clip.width, clip.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    else:
        raise ValueError("source needs 'file', 'video' or 'pdf'")
    if "crop" in src:
        im = im.crop(tuple(src["crop"]))
    return im, path


def quality_class(item, w, h):
    if item.get("quality"):           # set by hand when pixel size is misleading (e.g. an upscaled file)
        return item["quality"]
    if item.get("kind") == "video":   # videos sit in small slots (300-520 px wide on the page)
        return "high" if w >= 900 else "medium" if w >= 600 else "low"
    edge = max(w, h)
    inset = item.get("kind") in ("figure", "screen")   # shown inside the column, never full-bleed
    if edge >= (1600 if inset else 2400):
        return "high"
    if edge >= (1000 if inset else 1600):
        return "medium"
    return "low"


def average_color(im):
    r, g, b = im.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    return f"#{r:02x}{g:02x}{b:02x}"


def write_webps(im, stem, widths, q):
    """Save im at each width (never upscaled) as <stem>-<width>.webp; returns the file list."""
    w, h = im.size
    files = []
    for tw in sorted({x for x in widths if x < w} | {min(w, widths[-1])}):
        th = round(h * tw / w)
        out = OUT / f"{stem}-{tw}.webp"
        out.parent.mkdir(parents=True, exist_ok=True)
        frame = im if tw == w else im.resize((tw, th), Image.Resampling.LANCZOS)
        tmp = out.with_name(out.name + ".tmp")
        frame.save(tmp, "WEBP", quality=q, method=4)
        os.replace(tmp, out)  # the preview never serves a half-written file
        files.append({"w": tw, "h": th, "src": f"{stem}-{tw}.webp"})
    return files


def build_image(item, sources):
    im, path = open_source(item, sources)
    w, h = im.size
    return {
        "w": w,
        "h": h,
        "color": average_color(im),
        "quality": quality_class(item, w, h),
        "files": write_webps(im, item["id"], WIDTHS, QUALITY.get(item.get("kind", "photo"), 82)),
        "hash": spec_hash(item, sources),
        "source": str(path.relative_to(sources)),
        "spec": item["source"],  # the build checks this against media.json before publishing
        "fingerprint": fingerprint(path),
    }


def probe(path):
    out = subprocess.run(
        [ffmpeg_bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    s = data["streams"][0]
    return s["width"], s["height"], round(float(data["format"]["duration"]), 2)


def build_video(item, sources):
    """A muted, looping H.264 clip (web-safe yuv420p, faststart) and a poster from its first frame."""
    src = item["source"]
    path = sources / (src.get("video") or src.get("file"))
    max_w = int(item.get("max_width", VIDEO_MAX_WIDTH))
    rel = f"{item['id'].rsplit('/', 1)[0]}/{item['name']}.mp4" if item.get("name") and "/" in item["id"] else f"{item.get('name') or item['id']}.mp4"
    out = OUT / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".tmp.mp4")
    cmd = [ffmpeg_bin(), "-v", "error", "-y"]
    if "start" in src:
        cmd += ["-ss", str(src["start"])]
    cmd += ["-i", str(path)]
    if "end" in src:
        cmd += ["-t", str(src["end"] - src.get("start", 0))]
    cmd += [
        "-an",  # the site's videos are always muted, so never ship an audio track
        "-vf", f"scale='trunc(min({max_w},iw)/2)*2':-2:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "slow", "-crf", str(item.get("crf", 26)),
        "-profile:v", "high", "-movflags", "+faststart", str(tmp),
    ]
    subprocess.run(cmd, check=True)
    os.replace(tmp, out)
    w, h, duration = probe(out)
    poster = video_frame(out, 0)
    return {
        "w": w,
        "h": h,
        "color": average_color(poster),
        "quality": quality_class(item, w, h),
        "files": write_webps(poster, f"{item['id']}-poster", POSTER_WIDTHS, QUALITY["video"]),
        "video": {"src": rel, "bytes": out.stat().st_size, "duration": duration},
        "hash": spec_hash(item, sources),
        "source": str(path.relative_to(sources)),
        "spec": item["source"],
        "fingerprint": fingerprint(path),
    }


def build_item(item, sources):
    return build_video(item, sources) if item.get("kind") == "video" else build_image(item, sources)


def cover_crop(im, size, focus):
    """Crop im to the aspect of size around focus (0-1 fractions), then resize to size."""
    tw, th = size
    w, h = im.size
    scale = max(tw / w, th / h)
    cw, ch = round(tw / scale), round(th / scale)
    fx, fy = focus
    x0 = min(max(0, round(fx * w - cw / 2)), w - cw)
    y0 = min(max(0, round(fy * h - ch / 2)), h - ch)
    return im.crop((x0, y0, x0 + cw, y0 + ch)).resize(size, Image.Resampling.LANCZOS)


def build_site(registry, sources, manifest, force):
    """The social card (from a registered image) and the icons (from src/site/icon.svg)."""
    site = manifest.get("_site", {})
    og = registry.get("_og")
    if og:
        item = dict(registry[og["media"]], id=og["media"])
        h = hashlib.sha1(json.dumps([og, spec_hash(item, sources)], sort_keys=True).encode()).hexdigest()[:12]
        target = OUT / "site" / "og-card.jpg"
        if force or site.get("og", {}).get("hash") != h or not target.exists():
            im, _ = open_source(item, sources)
            target.parent.mkdir(parents=True, exist_ok=True)
            card = cover_crop(im, OG_SIZE, og.get("focus", [0.5, 0.5]))
            tmp = target.with_name(target.name + ".tmp")
            card.save(tmp, "JPEG", quality=86, optimize=True, progressive=True)
            os.replace(tmp, target)
            print(f"  {'site/og-card':<44} {OG_SIZE[0]}x{OG_SIZE[1]}  from {og['media']}")
        site["og"] = {"src": "site/og-card.jpg", "media": og["media"], "spec": item["source"], "hash": h,
                      "fingerprint": fingerprint(source_path(item, sources))}
    else:  # no _og: never leave an old card behind for the build to pick up
        site.pop("og", None)
        (OUT / "site" / "og-card.jpg").unlink(missing_ok=True)
    if ICON.exists():
        svg = ICON.read_bytes()
        h = hashlib.sha1(svg + str(PIPELINE_VERSION).encode()).hexdigest()[:12]
        names = {"favicon-96.png": 96, "apple-touch-icon.png": 180, "favicon.ico": 32}
        if force or site.get("icons", {}).get("hash") != h or not all((OUT / "site" / n).exists() for n in names):
            if fitz is None:
                sys.exit("PyMuPDF (fitz) is needed to render src/site/icon.svg.")
            page = fitz.open(stream=svg, filetype="svg")[0]

            def render(size):
                z = size / page.rect.width
                pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=True)
                return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)

            (OUT / "site").mkdir(parents=True, exist_ok=True)
            render(96).save(OUT / "site" / "favicon-96.png")
            render(180).save(OUT / "site" / "apple-touch-icon.png")
            render(64).save(OUT / "site" / "favicon.ico", sizes=[(16, 16), (32, 32)])
            print(f"  {'site/icons':<44} favicon.ico, favicon-96.png, apple-touch-icon.png")
        site["icons"] = {"files": [f"site/{n}" for n in names], "hash": h, "svg": hashlib.sha1(svg).hexdigest()}
    return site


def cross_check(items, catalogue):
    """Compare media.json rights with the catalogue. Confidential material is never processed."""
    stop, warn = [], []
    names = {}
    for item in items:
        if not ID_PATTERN.match(item["id"]):
            stop.append(f"{item['id']}: ids are lowercase words joined by '/', '-' or '_' (they become file names)")
        if item.get("kind") == "video" and item.get("name"):
            clip = f"{item['id'].rsplit('/', 1)[0]}/{item['name']}"
            if clip in names:
                stop.append(f"{item['id']}: clip name {item['name']} is also used by {names[clip]}")
            names[clip] = item["id"]
        key = item["source"].get("file") or item["source"].get("video") or item["source"].get("pdf")
        row = catalogue.get(key)
        if not row:
            warn.append(f"{item['id']}: {key} is not in ALL_SOURCES.csv (run: npm run sources)")
            continue
        if row["rights"] == "confidential":
            stop.append(f"{item['id']}: {key} is marked confidential in ALL_SOURCES.csv")
        elif row["rights"] != item.get("rights"):
            warn.append(f"{item['id']}: rights {item.get('rights')} in media.json but {row['rights']} in ALL_SOURCES.csv")
    return stop, warn


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--force", action="store_true", help="rebuild everything")
    ap.add_argument("--only", nargs="*", default=[], help="ids or id prefixes to build")
    args = ap.parse_args()

    sources = find_sources()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    items = [dict(v, id=k) for k, v in registry.items() if not k.startswith("_")]
    stop, warn = cross_check(items, load_catalogue(sources))
    for w in warn:
        print(f"  ! {w}", file=sys.stderr)
    if stop:
        sys.exit("Refusing to continue:\n" + "\n".join(f"  ✗ {s}" for s in stop))

    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    OUT.mkdir(exist_ok=True)
    done = skipped = failed = 0
    t0 = time.time()
    for item in items:
        if args.only and not any(item["id"].startswith(p) for p in args.only):
            continue
        prev = manifest.get(item["id"])
        outputs = []
        if prev:
            outputs = [f["src"] for f in prev["files"]] + ([prev["video"]["src"]] if "video" in prev else [])
        fresh = prev and prev.get("hash") == spec_hash(item, sources) and prev.get("fingerprint") == fingerprint(source_path(item, sources))
        if not args.force and fresh and all((OUT / f).exists() for f in outputs):
            skipped += 1
            continue
        try:
            manifest[item["id"]] = build_item(item, sources)
            m = manifest[item["id"]]
            extra = f"  {m['video']['duration']}s, {m['video']['bytes'] // 1024} KB" if "video" in m else ""
            print(f"  {item['id']:<44} {m['w']}x{m['h']}  {m['quality']}{extra}")
            done += 1
        except Exception as e:  # keep going; report at the end
            print(f"! {item['id']}: {e}", file=sys.stderr)
            failed += 1
    try:
        manifest["_site"] = build_site(registry, sources, manifest, args.force)
    except Exception as e:
        print(f"! site images: {e}", file=sys.stderr)
        failed += 1

    # drop entries whose id no longer exists in the registry, and files nothing points to
    manifest = {k: v for k, v in manifest.items() if k in registry or k == "_site"}
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    tmp.replace(MANIFEST)
    for path in [*OUT.rglob("*.tmp"), *OUT.rglob("*.tmp.mp4")]:
        path.unlink(missing_ok=True)  # left by an interrupted save
    keep = {f["src"] for k, m in manifest.items() if k != "_site" for f in m["files"]}
    keep |= {m["video"]["src"] for k, m in manifest.items() if k != "_site" and "video" in m}
    for path in [*OUT.rglob("*.webp"), *OUT.rglob("*.mp4")]:
        if str(path.relative_to(OUT)) not in keep:
            path.unlink()
    print(f"media: {done} built, {skipped} unchanged, {failed} failed in {time.time() - t0:.1f}s")
    print(f"       sources: {sources}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
