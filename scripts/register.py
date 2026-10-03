#!/usr/bin/env python3
"""
Register catalogued images in src/content/media.json, and keep their rights and credits in step with
ALL_SOURCES.csv.

    npm run register -- add vrpelvisim/own_or-frame-01.jpg --id vrpelvisim/or --kind frame \\
        --alt "Virtual operating room with a C-arm and two X-ray panels"
    npm run register -- sync          # copy rights/owner/contact/credit/licence/URL from the CSV
    npm run register -- sync --check  # only show what would change

`add` fills rights, holder, contact, credit, licence, sourceUrl and caption from the file's row in
ALL_SOURCES.csv; you supply the id, the kind and the alt text (and optionally --caption, --position).
Afterwards media.json owns the display strings (credit, holder, contact, licence label, caption): edit
them there. `sync` copies only `rights` from the catalogue and reports source-URL differences without
changing them. Permission records are written by hand in media.json when Austin says a holder agreed,
with the file they cover (see README); the public build also re-checks every image against the catalogue.

Confidential rows are refused. The default sources folder is
~/Documents/Myfile/Portfolio and Media/portfolio-sources (override with PORTFOLIO_SOURCES).
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
REGISTRY = SITE / "src" / "content" / "media.json"
DEFAULT_SOURCES = Path.home() / "Documents" / "Myfile" / "Portfolio and Media" / "portfolio-sources"
KINDS = ["photo", "frame", "screen", "figure", "render", "portrait", "video"]
SYNCED = ["rights"]                     # the status field copied by `sync`; display strings stay as edited in media.json
COMPARED = ["sourceUrl"]                 # reported by `sync` when it differs, never overwritten


def sources_dir():
    env = os.environ.get("PORTFOLIO_SOURCES")
    return Path(env).expanduser() if env else DEFAULT_SOURCES


def catalogue():
    path = sources_dir() / "ALL_SOURCES.csv"
    if not path.exists():
        sys.exit(f"No catalogue at {path}. Run: npm run sources")
    with path.open(newline="", encoding="utf-8") as f:
        return {f"{r['project']}/{r['file']}": r for r in csv.DictReader(f) if r.get("file")}


def short_license(text):
    """The catalogue's licence note, cut down to the label printed under public images."""
    t = text.strip()
    low = t.lower()
    if low.startswith("public domain"):
        return "Public domain"
    m = re.search(r"CC[ -]BY(?:-[A-Z]{2})*(?: \d\.\d)?|CC0(?: 1\.0)?", t)
    if m:
        return m.group(0).replace("CC-BY", "CC BY")
    return re.split(r"[.;(]", t)[0].strip()


def short_holder(text):
    """Who must say yes, as a short name (the catalogue keeps the long version)."""
    t = re.split(r";|\(|, (?:wholly|which|the) ", text.strip())[0].strip()
    return t[:80]


def fields_from_row(row):
    rights = row["rights"].strip()
    out = {
        "rights": rights,
        "credit": row["credit"].strip(),
        "sourceUrl": (row.get("page_url") or row.get("source_url") or "").strip(),
        "holder": short_holder(row["owner"]),
        "contact": row["permission_contact"].strip() if rights == "needs-permission" else "",
        "license": short_license(row["license"]) if rights == "public" else "",
    }
    if not out["sourceUrl"].startswith("http"):
        out["sourceUrl"] = ""
    return out


def load_registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def save_registry(reg):
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def add(args):
    rows = catalogue()
    row = rows.get(args.file)
    if not row:
        sys.exit(f"{args.file} is not in ALL_SOURCES.csv (run: npm run sources, then fill in its row)")
    if row["rights"] == "confidential":
        sys.exit(f"{args.file} is marked confidential: it must never be registered")
    if row["rights"] not in ("own", "public", "needs-permission"):
        sys.exit(f"{args.file}: set its rights in ALL_SOURCES.csv first (own | public | needs-permission)")
    reg = load_registry()
    if args.id in reg and not args.force:
        sys.exit(f"{args.id} already exists (use --force to replace it)")
    entry = {"project": row["project"], "source": {"file": args.file}, "kind": args.kind}
    entry.update(fields_from_row(row))
    entry["caption"] = args.caption if args.caption is not None else row["caption"].strip()
    entry["alt"] = args.alt
    if args.position:
        entry["position"] = args.position
    if args.force and args.id in reg and "permission" in reg[args.id]:
        # a permission covers one file: keep it only if the source is unchanged
        if reg[args.id]["permission"].get("source") == args.file:
            entry["permission"] = reg[args.id]["permission"]
        else:
            print(f"  ! {args.id}: the old permission covered another file and was dropped; ask the holder again")
    entry = {k: v for k, v in entry.items() if v != ""}
    reg[args.id] = entry
    save_registry(reg)
    print(f"registered {args.id} ← {args.file} ({entry['rights']})")


def sync(args):
    rows = catalogue()
    reg = load_registry()
    changes = 0
    for mid, entry in reg.items():
        if mid.startswith("_"):
            continue
        key = entry.get("source", {}).get("file")
        row = rows.get(key)
        if not row:
            if key:
                print(f"  ! {mid}: {key} not in ALL_SOURCES.csv")
            continue
        if row["rights"] == "confidential":
            print(f"  ✗ {mid}: {key} is now marked confidential: remove it from media.json and from every page")
            continue
        fresh = fields_from_row(row)
        for field in SYNCED:
            new = fresh.get(field, "")
            old = entry.get(field, "")
            if new != old and (new or field == "contact"):
                print(f"  {mid}.{field}: {old!r} → {new!r}")
                changes += 1
                if not args.check:
                    if new:
                        entry[field] = new
                    else:
                        entry.pop(field, None)
        for field in COMPARED:
            if fresh.get(field) and fresh[field] != entry.get(field):
                print(f"  · {mid}.{field} differs from the catalogue (kept): {entry.get(field)!r} vs {fresh[field]!r}")
    if changes and not args.check:
        save_registry(reg)
    print(f"{changes} change(s){' (not written: --check)' if args.check and changes else ''}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="register one catalogued file")
    a.add_argument("file", help="<project>/<file> as in ALL_SOURCES.csv")
    a.add_argument("--id", required=True, help="media id, e.g. vrpelvisim/or")
    a.add_argument("--kind", required=True, choices=KINDS)
    a.add_argument("--alt", required=True, help="alt text: what the image shows, for screen readers")
    a.add_argument("--caption", help="caption (default: the catalogue caption)")
    a.add_argument("--position", help="CSS object-position for crops, e.g. '50%% 40%%'")
    a.add_argument("--force", action="store_true", help="replace an existing id (keeps its permission record only if the file is the same)")
    s = sub.add_parser("sync", help="refresh rights and credits from ALL_SOURCES.csv")
    s.add_argument("--check", action="store_true")
    args = ap.parse_args()
    add(args) if args.cmd == "add" else sync(args)


if __name__ == "__main__":
    main()
