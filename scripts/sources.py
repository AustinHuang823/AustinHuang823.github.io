#!/usr/bin/env python3
"""
Catalogue the portfolio-sources folder: measure every image, keep ALL_SOURCES.csv in step with the
files on disk, redraw each project's _contact-sheet.jpg, and print a readiness table.

    npm run sources                     # measure, sync the CSV, redraw contact sheets, print the table
    npm run sources -- --check          # report problems only; change nothing
    npm run sources -- --report out.md  # also write the readiness table as Markdown

Rows already in ALL_SOURCES.csv keep everything a person or agent wrote (rights, owner, credit,
licence, contact, URLs, caption, notes); only width, height, long_edge, tier and bytes are measured.
A file with no row gets a new row with rights "" so it shows up as uncatalogued. A row whose file is
gone is reported (and kept, so nothing is lost silently).

Default folder: ~/Documents/Myfile/Portfolio and Media/portfolio-sources (override with
PORTFOLIO_SOURCES=/path). Needs Pillow; ffprobe only if videos are present.
"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

DEFAULT_SOURCES = Path.home() / "Documents" / "Myfile" / "Portfolio and Media" / "portfolio-sources"
COLUMNS = [
    "project", "file", "rights", "owner", "credit", "license", "permission_contact",
    "source_type", "source_url", "page_url", "width", "height", "long_edge", "tier", "bytes",
    "caption", "notes", "retrieved", "checked",
]
RIGHTS = ["own", "public", "needs-permission", "confidential"]
RIGHTS_ZH = {"own": "自己的", "public": "公開可用", "needs-permission": "需要授權", "confidential": "機密不能用"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
SHEET = "_contact-sheet.jpg"

COLORS = {
    "own": (47, 125, 79),
    "public": (42, 111, 176),
    "needs-permission": (201, 138, 22),
    "confidential": (179, 38, 30),
    "": (120, 120, 120),
}


def tier(long_edge):
    """How large an image can be shown without looking soft."""
    if long_edge >= 2400:
        return "hero"         # full-bleed on large screens
    if long_edge >= 1600:
        return "wide"         # wide or pair blocks
    if long_edge >= 1000:
        return "inline"       # inset figures, cards
    return "placeholder"      # thumbnails only, or a stand-in until a better original arrives


def find_sources(arg=None):
    env = arg or os.environ.get("PORTFOLIO_SOURCES")
    path = Path(env).expanduser() if env else DEFAULT_SOURCES
    if not path.is_dir():
        sys.exit(f"No portfolio-sources folder at {path} (set PORTFOLIO_SOURCES).")
    return path


def project_dirs(root):
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))


UNSUPPORTED = {".heic", ".heif", ".avif", ".psd", ".raw", ".cr2", ".nef", ".dng"}


def media_files(folder, problems=None):
    for p in sorted(folder.iterdir()):
        if p.name == SHEET or p.name.startswith("."):
            continue
        if p.suffix.lower() in UNSUPPORTED and problems is not None:
            problems.append(f"{folder.name}/{p.name}: {p.suffix} can't be read here; convert it to JPEG or PNG (e.g. sips -s format jpeg)")
        if p.suffix.lower() in IMAGE_EXT | VIDEO_EXT and p.is_file():
            yield p


def measure(path):
    if path.suffix.lower() in VIDEO_EXT:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None, None
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(path)],
            capture_output=True, text=True,
        )
        s = (json.loads(out.stdout or "{}").get("streams") or [{}])[0]
        return s.get("width"), s.get("height")
    with Image.open(path) as im:
        w, h = im.size
        # EXIF rotation swaps the displayed width and height
        try:
            if im.getexif().get(0x0112) in (5, 6, 7, 8):
                w, h = h, w
        except Exception:
            pass
        if im.format == "JPEG":
            im.draft("RGB", (max(1, im.size[0] // 8), max(1, im.size[1] // 8)))  # decode small, but read the whole stream
        im.load()  # raises on truncated or corrupt files, so they are reported instead of graded
        return w, h


EXTRA_COLUMNS = []  # columns a person added to the CSV; kept, after the standard ones


def load_rows(csv_path):
    if not csv_path.exists():
        return []
    # utf-8-sig: a file saved from Excel or Numbers may start with a byte-order mark
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for c in reader.fieldnames or []:
            if c and c not in COLUMNS and c not in EXTRA_COLUMNS:
                EXTRA_COLUMNS.append(c)
        cols = COLUMNS + EXTRA_COLUMNS
        return [{c: (r.get(c) or "") for c in cols} for r in reader]


def write_rows(csv_path, rows):
    def key(r):
        return (r["project"], r["file"] == "", r["file"])
    tmp = csv_path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS + EXTRA_COLUMNS)
        w.writeheader()
        for r in sorted(rows, key=key):
            w.writerow({c: r.get(c, "") for c in COLUMNS + EXTRA_COLUMNS})
    tmp.replace(csv_path)


def font(size, bold=False):
    # Arial Unicode covers the Chinese rights labels; bold text (titles, filenames) is ASCII.
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def thumbnail(path, box):
    if path.suffix.lower() in VIDEO_EXT:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "frame.png"
            subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", "1", "-i", str(path), "-frames:v", "1", str(tmp)], check=False)
            if not tmp.exists():
                return None
            with Image.open(tmp) as im:
                im = im.convert("RGB")
                im.thumbnail(box, Image.Resampling.LANCZOS)
                return im
    with Image.open(path) as im:
        if im.format == "JPEG":
            im.draft("RGB", (box[0] * 2, box[1] * 2))
        im.seek(0)
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (236, 236, 236))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        im = im.convert("RGB")
        im.thumbnail(box, Image.Resampling.LANCZOS)
        return im


def contact_sheet(folder, rows_by_file, out_path):
    files = list(media_files(folder))
    if not files:
        return False
    cols = 5
    width = 2400
    pad = 24
    cell_w = (width - pad * (cols + 1)) // cols
    thumb_h = int(cell_w * 0.68)
    label_h = 92
    rows_n = (len(files) + cols - 1) // cols
    header_h = 120
    height = header_h + rows_n * (thumb_h + label_h + pad) + pad
    sheet = Image.new("RGB", (width, height), (250, 250, 248))
    d = ImageDraw.Draw(sheet)
    f_title, f_meta, f_name, f_small = font(44, True), font(22), font(19, True), font(18)
    best = 0
    counts = {}
    for p in files:
        r = rows_by_file.get(p.name, {})
        counts[r.get("rights", "")] = counts.get(r.get("rights", ""), 0) + 1
        try:
            best = max(best, int(r.get("long_edge") or 0))
        except ValueError:
            pass
    d.text((pad, 26), folder.name, fill=(20, 20, 22), font=f_title)
    summary = f"{len(files)} files · best long edge {best}px · " + " · ".join(
        f"{RIGHTS_ZH.get(k, 'uncatalogued')} {v}" if k else f"uncatalogued {v}" for k, v in sorted(counts.items())
    )
    d.text((pad, 80), summary + f" · {date.today().isoformat()}", fill=(90, 90, 96), font=f_meta)
    for i, p in enumerate(files):
        r = rows_by_file.get(p.name, {})
        cx = pad + (i % cols) * (cell_w + pad)
        cy = header_h + (i // cols) * (thumb_h + label_h + pad)
        d.rectangle([cx, cy, cx + cell_w, cy + thumb_h], fill=(226, 226, 222))
        try:
            t = thumbnail(p, (cell_w, thumb_h))
        except Exception:
            t = None
        if t is not None:
            sheet.paste(t, (cx + (cell_w - t.width) // 2, cy + (thumb_h - t.height) // 2))
        else:
            d.text((cx + 12, cy + 12), "cannot preview", fill=(120, 120, 120), font=f_small)
        rights = r.get("rights", "")
        color = COLORS.get(rights, COLORS[""])
        d.rectangle([cx, cy, cx + 8, cy + thumb_h], fill=color)
        name = p.name if len(p.name) <= 44 else p.name[:41] + "…"
        d.text((cx, cy + thumb_h + 10), name, fill=(25, 25, 28), font=f_name)
        dims = f"{r.get('width') or '?'}×{r.get('height') or '?'}  {(r.get('tier') or '').upper()}"
        d.text((cx, cy + thumb_h + 36), dims, fill=(70, 70, 76), font=f_small)
        tag = RIGHTS_ZH.get(rights, "uncatalogued") + (f"  {rights}" if rights else "")
        owner = (r.get("owner") or "")[:34]
        d.rectangle([cx, cy + thumb_h + 62, cx + 14, cy + thumb_h + 76], fill=color)
        d.text((cx + 22, cy + thumb_h + 59), f"{tag} · {owner}", fill=color, font=f_small)
    sheet.save(out_path, "JPEG", quality=86, optimize=True)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--check", action="store_true", help="report only; do not write the CSV or contact sheets")
    ap.add_argument("--no-sheets", action="store_true", help="skip redrawing contact sheets")
    ap.add_argument("--report", help="write the readiness table to this Markdown file")
    ap.add_argument("--root", help="portfolio-sources folder (default: PORTFOLIO_SOURCES or ~/Documents/...)")
    args = ap.parse_args()

    root = find_sources(args.root)
    csv_path = root / "ALL_SOURCES.csv"
    rows = load_rows(csv_path)
    index = {(r["project"], r["file"]): r for r in rows if r["file"]}
    problems = []

    for folder in project_dirs(root):
        for p in media_files(folder, problems):
            key = (folder.name, p.name)
            try:
                w, h = measure(p)
            except Exception as e:
                problems.append(f"{folder.name}/{p.name}: cannot read ({e})")
                continue
            row = index.get(key)
            if row is None:
                row = {c: "" for c in COLUMNS + EXTRA_COLUMNS}
                row.update(project=folder.name, file=p.name, source_type="", notes="not catalogued yet")
                rows.append(row)
                index[key] = row
                problems.append(f"{folder.name}/{p.name}: not in ALL_SOURCES.csv (added with empty rights)")
            if w and h:
                if row["width"] and row["height"] and (str(w), str(h)) != (row["width"], row["height"]):
                    problems.append(f"{folder.name}/{p.name}: size was recorded as {row['width']}×{row['height']}, measured {w}×{h}")
                row["width"], row["height"] = str(w), str(h)
                row["long_edge"] = str(max(w, h))
                row["tier"] = tier(max(w, h))
            row["bytes"] = str(p.stat().st_size)

    for r in rows:
        if r["rights"] and r["rights"] not in RIGHTS:
            problems.append(f"{r['project']}/{r['file']}: unknown rights '{r['rights']}' (use {', '.join(RIGHTS)})")
        if not r["rights"]:
            problems.append(f"{r['project']}/{r['file']}: rights not set")
        if r["file"] and not (root / r["project"] / r["file"]).exists():
            problems.append(f"{r['project']}/{r['file']}: listed in ALL_SOURCES.csv but the file is missing")
        if r["rights"] == "confidential" and r["file"] and (root / r["project"] / r["file"]).exists():
            problems.append(f"{r['project']}/{r['file']}: confidential material must not be stored here")
        if r["rights"] == "needs-permission" and not r["permission_contact"]:
            problems.append(f"{r['project']}/{r['file']}: needs-permission but no permission_contact")

    if not args.check:
        write_rows(csv_path, rows)
        if not args.no_sheets:
            for folder in project_dirs(root):
                by_file = {r["file"]: r for r in rows if r["project"] == folder.name}
                contact_sheet(folder, by_file, folder / SHEET)

    # readiness table
    lines = [
        "| project | files | own | public | needs permission | confidential rows | best long edge | hero ≥2400 | wide ≥1600 | inline ≥1000 | placeholder <1000 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for folder in project_dirs(root):
        rs = [r for r in rows if r["project"] == folder.name]
        files = [r for r in rs if r["file"]]
        def n(cond):
            return sum(1 for r in files if cond(r))
        best = max([int(r["long_edge"] or 0) for r in files] or [0])
        lines.append(
            f"| {folder.name} | {len(files)} | {n(lambda r: r['rights'] == 'own')} | {n(lambda r: r['rights'] == 'public')} | "
            f"{n(lambda r: r['rights'] == 'needs-permission')} | {sum(1 for r in rs if r['rights'] == 'confidential')} | {best} | "
            f"{n(lambda r: r['tier'] == 'hero')} | {n(lambda r: r['tier'] == 'wide')} | {n(lambda r: r['tier'] == 'inline')} | {n(lambda r: r['tier'] == 'placeholder')} |"
        )
    table = "\n".join(lines)
    print(table)
    if args.report:
        Path(args.report).write_text(table + "\n", encoding="utf-8")
    if problems:
        print(f"\n{len(problems)} note(s):", file=sys.stderr)
        for p in problems:
            print(f"  ! {p}", file=sys.stderr)


if __name__ == "__main__":
    main()
