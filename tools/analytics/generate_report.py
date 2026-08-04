#!/usr/bin/env python3
"""Generate a private, offline portfolio-attention report.

The preferred real-data input is GoatCounter's aggregate JSON export ZIP.
CSV v2 is also supported when Individual pageviews has been enabled.
Only aggregate event counts are rendered; session IDs and locations never are.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SECTIONS = ("hero", "experience", "projects", "skills", "about", "contact")
SECTION_BUCKETS = ("3s", "10s", "30s", "60s")
SESSION_BUCKETS = ("15s", "30s", "60s", "120s")
SCROLL_BUCKETS = ("25", "50", "75", "100")
COLORS = ("#3ee6c4", "#f5c542", "#74a7ff", "#d88cff", "#ff8f70", "#94a5ba")


class InputError(ValueError):
    """Raised when an analytics export cannot be trusted."""


@dataclass
class Dataset:
    counts: Counter[str] = field(default_factory=Counter)
    page_counts: Counter[str] = field(default_factory=Counter)
    sessions: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    dates: list[datetime] = field(default_factory=list)
    source_type: str = ""
    source_name: str = ""
    sample: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def pageviews(self) -> int:
        return sum(self.page_counts.values())

    @property
    def visit_denominator(self) -> int:
        if self.sessions:
            return len(self.sessions)
        return self.page_counts.get("/", 0)

    @property
    def date_range(self) -> str:
        if not self.dates:
            return "Synthetic demonstration period" if self.sample else "Not available in source"
        start, end = min(self.dates), max(self.dates)
        return f"{start.date().isoformat()} to {end.date().isoformat()}"


def parse_date(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def truthy(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def load_sample(path: Path) -> Dataset:
    data = Dataset(source_type="synthetic aggregate fixture", source_name=path.name, sample=True)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["Path", "Count", "Event"]:
            raise InputError("Synthetic fixture must use Path,Count,Event columns")
        for row in reader:
            path_name = (row.get("Path") or "").strip()
            try:
                count = int(row.get("Count") or "")
            except ValueError as exc:
                raise InputError(f"Invalid synthetic count for {path_name!r}") from exc
            if count < 0:
                raise InputError(f"Negative synthetic count for {path_name!r}")
            if truthy(row.get("Event", "")):
                data.counts[path_name] += count
            else:
                data.page_counts[path_name] += count
    return data


def normalize_csv_header(raw_header: list[str]) -> tuple[str, list[str], bool]:
    if not raw_header:
        raise InputError("CSV export is empty")
    header = [field.lstrip("\ufeff") for field in raw_header]
    first = header[0]
    attached = re.fullmatch(r"(\d+)Path", first)
    if attached:
        version = attached.group(1)
        header[0] = "Path"
        return version, header, False
    if first.isdigit() and len(header) > 1 and header[1] == "Path":
        return first, header[1:], True
    raise InputError("Unrecognized GoatCounter CSV header; expected a version-prefixed Path field")


def load_goatcounter_csv(path: Path) -> Dataset:
    data = Dataset(source_type="GoatCounter CSV v2", source_name=path.name)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = csv.reader(handle)
        try:
            raw_header = next(rows)
        except StopIteration as exc:
            raise InputError("CSV export is empty") from exc
        version, header, separate_version_column = normalize_csv_header(raw_header)
        if version != "2":
            raise InputError(f"Unsupported GoatCounter CSV export version {version}; expected 2")
        required = {"Path", "Event", "Session", "Bot", "Date"}
        if not required.issubset(header):
            missing = ", ".join(sorted(required - set(header)))
            raise InputError(f"GoatCounter CSV is missing required columns: {missing}")
        for line_number, raw_row in enumerate(rows, start=2):
            if not raw_row or not any(raw_row):
                continue
            if separate_version_column and len(raw_row) == len(header) + 1:
                raw_row = raw_row[1:]
            if len(raw_row) != len(header):
                raise InputError(f"CSV row {line_number} has {len(raw_row)} fields; expected {len(header)}")
            row = dict(zip(header, raw_row))
            bot = (row.get("Bot") or "").strip()
            if bot not in {"", "0"}:
                continue
            path_name = (row.get("Path") or "").strip()
            if not path_name:
                continue
            session = (row.get("Session") or "").strip()
            if session:
                data.sessions[session].add(path_name)
            if truthy(row.get("Event", "")):
                data.counts[path_name] += 1
            else:
                data.page_counts[path_name] += 1
            parsed = parse_date(row.get("Date", ""))
            if parsed:
                data.dates.append(parsed)
    data.warnings.extend(session_consistency_warnings(data.sessions))
    return data


def json_lines(raw: bytes, name: str) -> Iterable[dict]:
    for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InputError(f"Invalid JSON in {name} line {line_number}") from exc
        if not isinstance(value, dict):
            raise InputError(f"Expected objects in {name} line {line_number}")
        yield value


def load_goatcounter_json_zip(path: Path) -> Dataset:
    data = Dataset(source_type="GoatCounter aggregate JSON export", source_name=path.name)
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise InputError("JSON export must be the ZIP downloaded from GoatCounter") from exc
    with archive:
        names = set(archive.namelist())
        required = {"info.json", "paths.jsonl", "hit_stats.jsonl"}
        if not required.issubset(names):
            missing = ", ".join(sorted(required - names))
            raise InputError(f"GoatCounter JSON export is missing: {missing}")
        try:
            info = json.loads(archive.read("info.json"))
        except (json.JSONDecodeError, KeyError) as exc:
            raise InputError("Invalid info.json in GoatCounter export") from exc
        version = str(info.get("export_version", ""))
        if version.split(".", 1)[0] != "1":
            raise InputError(f"Unsupported GoatCounter JSON export version {version!r}; expected major version 1")
        paths: dict[int, tuple[str, bool]] = {}
        for item in json_lines(archive.read("paths.jsonl"), "paths.jsonl"):
            try:
                paths[int(item["id"])] = (str(item["path"]), bool(item.get("event", False)))
            except (KeyError, TypeError, ValueError) as exc:
                raise InputError("Invalid entry in paths.jsonl") from exc
        for item in json_lines(archive.read("hit_stats.jsonl"), "hit_stats.jsonl"):
            try:
                path_id, count = int(item["path_id"]), int(item["count"])
            except (KeyError, TypeError, ValueError) as exc:
                raise InputError("Invalid entry in hit_stats.jsonl") from exc
            if count < 0:
                raise InputError("Negative count in hit_stats.jsonl")
            if path_id not in paths:
                raise InputError(f"hit_stats.jsonl references unknown path_id {path_id}")
            path_name, is_event = paths[path_id]
            if is_event:
                data.counts[path_name] += count
            else:
                data.page_counts[path_name] += count
            parsed = parse_date(str(item.get("hour", "")))
            if parsed:
                data.dates.append(parsed)
    return data


def load_real(path: Path) -> Dataset:
    if not path.exists():
        raise InputError(f"Input does not exist: {path}")
    if path.suffix.lower() == ".csv":
        return load_goatcounter_csv(path)
    if path.suffix.lower() == ".zip":
        return load_goatcounter_json_zip(path)
    raise InputError("Unsupported input. Use GoatCounter's aggregate JSON ZIP or individual-pageviews CSV export.")


def session_consistency_warnings(sessions: dict[str, set[str]]) -> list[str]:
    warnings: list[str] = []
    violations = 0
    for events in sessions.values():
        for section in SECTIONS:
            ordered = [f"section/{section}/seen"] + [f"section/{section}/{bucket}" for bucket in SECTION_BUCKETS]
            for index, event in enumerate(ordered[1:], start=1):
                if event in events and not set(ordered[:index]).issubset(events):
                    violations += 1
                    break
        ordered_session = [f"session/engaged/{bucket}" for bucket in SESSION_BUCKETS]
        for index, event in enumerate(ordered_session[1:], start=1):
            if event in events and not set(ordered_session[:index]).issubset(events):
                violations += 1
                break
    if violations:
        warnings.append(f"Per-session threshold-order violations detected: {violations}. Inspect tracker or export completeness.")
    return warnings


def data_quality_warnings(data: Dataset) -> list[str]:
    warnings = list(data.warnings)
    for section in SECTIONS:
        seen = data.counts[f"section/{section}/seen"]
        if data.visit_denominator and seen > data.visit_denominator:
            warnings.append(
                f"{section}: seen ({seen}) exceeds the visit denominator ({data.visit_denominator})."
            )
        previous = seen
        for bucket in SECTION_BUCKETS:
            value = data.counts[f"section/{section}/{bucket}"]
            if value > seen:
                warnings.append(f"{section}: {bucket} count ({value}) exceeds seen ({seen}).")
            if value > previous:
                warnings.append(f"{section}: {bucket} count ({value}) exceeds the preceding threshold ({previous}).")
            previous = value
    previous = data.visit_denominator
    for bucket in SESSION_BUCKETS:
        value = data.counts[f"session/engaged/{bucket}"]
        if previous and value > previous:
            warnings.append(f"Session {bucket} count ({value}) exceeds the preceding threshold or denominator ({previous}).")
        previous = value
    if data.visit_denominator < 50 and not data.sample:
        warnings.append("Preliminary sample: fewer than 50 homepage visits/sessions are available.")
    if data.dates and (max(data.dates) - min(data.dates)).days < 27 and not data.sample:
        warnings.append("Preliminary collection window: less than approximately four weeks of data.")
    return warnings


def pct(numerator: int, denominator: int) -> float:
    return 0.0 if denominator <= 0 else numerator * 100.0 / denominator


def fmt_pct(value: float) -> str:
    return f"{value:.1f}%"


def svg_horizontal_bars(rows: list[tuple[str, int]], color: str = "#3ee6c4") -> str:
    width, left, right, row_height = 760, 160, 70, 38
    height = 36 + len(rows) * row_height
    maximum = max((value for _, value in rows), default=1) or 1
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img">']
    for index, (label, value) in enumerate(rows):
        y = 24 + index * row_height
        bar_width = (width - left - right) * value / maximum
        parts.append(f'<text x="0" y="{y + 14}" class="axis-label">{html.escape(label)}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{width-left-right}" height="18" rx="5" class="track"/>')
        parts.append(f'<rect x="{left}" y="{y}" width="{bar_width:.1f}" height="18" rx="5" fill="{color}"/>')
        parts.append(f'<text x="{width-right+10}" y="{y + 14}" class="value-label">{value}</text>')
    parts.append("</svg>")
    return "".join(parts)


def svg_retention(data: Dataset, sections: Iterable[str]) -> str:
    section_list = list(sections)
    width, height = 780, 360
    left, top, plot_w, plot_h = 64, 28, 570, 260
    x_positions = [left + i * plot_w / (len(SECTION_BUCKETS) - 1) for i in range(len(SECTION_BUCKETS))]
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img">']
    for percent in (0, 25, 50, 75, 100):
        y = top + plot_h - plot_h * percent / 100
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+plot_w}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end" class="axis-label">{percent}%</text>')
    for index, bucket in enumerate(SECTION_BUCKETS):
        parts.append(f'<text x="{x_positions[index]:.1f}" y="{top+plot_h+26}" text-anchor="middle" class="axis-label">{bucket}</text>')
    for index, section in enumerate(section_list):
        seen = data.counts[f"section/{section}/seen"]
        values = [pct(data.counts[f"section/{section}/{bucket}"], seen) for bucket in SECTION_BUCKETS]
        points = [(x_positions[i], top + plot_h - plot_h * min(100, values[i]) / 100) for i in range(len(values))]
        color = COLORS[index % len(COLORS)]
        parts.append('<polyline points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in points) + f'" fill="none" stroke="{color}" stroke-width="3"/>')
        for (x, y), value in zip(points, values):
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"><title>{html.escape(section)}: {value:.1f}%</title></circle>')
        legend_y = 32 + index * 26
        parts.append(f'<circle cx="{left+plot_w+38}" cy="{legend_y}" r="5" fill="{color}"/>')
        parts.append(f'<text x="{left+plot_w+50}" y="{legend_y+4}" class="axis-label">{html.escape(section)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def retention_table(data: Dataset, sections: Iterable[str]) -> str:
    headers = "".join(f"<th>{bucket}</th>" for bucket in SECTION_BUCKETS)
    rows = []
    for section in sections:
        seen = data.counts[f"section/{section}/seen"]
        cells = []
        for bucket in SECTION_BUCKETS:
            count = data.counts[f"section/{section}/{bucket}"]
            cells.append(f"<td>{count} / {seen} <small>({fmt_pct(pct(count, seen))})</small></td>")
        rows.append(f"<tr><th>{html.escape(section)}</th>{''.join(cells)}</tr>")
    return f"<table><thead><tr><th>Section</th>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def chart(title: str, subtitle: str, visual: str, sample: bool) -> str:
    watermark = '<span class="watermark">SYNTHETIC DATA</span>' if sample else ""
    return f'<section class="chart"><h2>{html.escape(title)}</h2><p>{html.escape(subtitle)}</p>{watermark}{visual}</section>'


def render_report(data: Dataset) -> str:
    warnings = data_quality_warnings(data)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    reach_rows = [(section, data.counts[f"section/{section}/seen"]) for section in SECTIONS]
    non_hero = [section for section in SECTIONS if section != "hero"]
    session_rows = [(bucket, data.counts[f"session/engaged/{bucket}"]) for bucket in SESSION_BUCKETS]
    scroll_rows = [(bucket + "%", data.counts[f"scroll/{bucket}"]) for bucket in SCROLL_BUCKETS]
    interaction_prefixes = ("click/", "filter/", "video/", "outbound/", "expand/", "theme/")
    interaction_rows = sorted((name, count) for name, count in data.counts.items() if name.startswith(interaction_prefixes))
    warning_html = "".join(f"<li>{html.escape(item)}</li>" for item in warnings) or "<li>No structural data-quality violations detected.</li>"
    interaction_html = "".join(f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>" for name, count in interaction_rows) or '<tr><td colspan="2">No interaction events in this input.</td></tr>'
    denominator_label = "unique CSV sessions" if data.sessions else "homepage pageviews (aggregate approximation)"

    main_retention = svg_retention(data, non_hero)
    hero_retention = svg_retention(data, ("hero",))
    whole_page_detail = "".join(
        f"<tr><th>{bucket}</th><td>{value}</td><td>{fmt_pct(pct(value, data.visit_denominator))}</td></tr>"
        for bucket, value in session_rows
    )
    sample_class = "sample" if data.sample else "real"
    sample_banner = (
        '<div class="banner sample-banner"><strong>SYNTHETIC DEMONSTRATION</strong> — these values are fictional and are not visitor analytics.</div>'
        if data.sample else
        '<div class="banner real-banner"><strong>REAL EXPORT</strong> — aggregate results generated locally from the selected GoatCounter export.</div>'
    )
    cards = "".join([
        f'<div class="metric"><span>{data.pageviews}</span><small>Total pageviews in input</small></div>',
        f'<div class="metric"><span>{data.visit_denominator}</span><small>{html.escape(denominator_label)}</small></div>',
        f'<div class="metric"><span>{sum(data.counts.values())}</span><small>Tracked custom events</small></div>',
    ])

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Portfolio attention report</title>
<style>
:root{{--bg:#0a0e14;--card:#111926;--border:#243247;--text:#e9eff6;--muted:#94a5ba;--accent:#3ee6c4;--gold:#f5c542}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,sans-serif}}
main{{max-width:1120px;margin:auto;padding:38px 24px 70px}} h1{{font-size:34px;margin:0 0 6px}} h2{{font-size:21px;margin:0 0 4px}}
p{{color:var(--muted)}} .banner{{padding:14px 16px;border-radius:10px;margin:22px 0;border:1px solid var(--border)}}
.sample-banner{{background:#392f0b;color:#ffe99a;border-color:#75621d}} .real-banner{{background:#08382f;color:#a7ffeb;border-color:#1a7b68}}
.meta{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:20px 0}} .meta div,.metric{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:15px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:18px 0 28px}} .metric span{{display:block;font-size:28px;font-weight:700;color:var(--accent)}} .metric small{{color:var(--muted)}}
.chart{{position:relative;overflow:hidden;background:var(--card);border:1px solid var(--border);border-radius:14px;padding:22px;margin:18px 0}} .chart>p{{margin:0 0 16px}}
.watermark{{position:absolute;right:12px;top:50%;transform:rotate(-18deg);font-size:42px;font-weight:800;color:rgba(245,197,66,.13);pointer-events:none;z-index:3}}
svg{{width:100%;height:auto;display:block}} .track{{fill:#1b2738}} .grid{{stroke:#26364c;stroke-width:1}} .axis-label{{fill:#94a5ba;font-size:12px}} .value-label{{fill:#e9eff6;font-size:13px;font-weight:700}}
table{{width:100%;border-collapse:collapse;margin-top:14px}} th,td{{padding:10px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}} th{{color:#cbd7e5}} td{{color:var(--muted)}} small{{color:#71849b}}
.notes{{background:#0e1621;border-left:4px solid var(--gold);padding:18px 22px;margin-top:28px}} .notes li{{margin:8px 0;color:var(--muted)}} code{{color:#9debdc}}
@media(max-width:700px){{main{{padding:24px 14px}} h1{{font-size:28px}} .chart{{padding:16px;overflow-x:auto}} .chart svg{{min-width:660px}} table{{font-size:12px}} .watermark{{font-size:28px}}}}
@media print{{body{{background:#fff;color:#111}} .chart,.meta div,.metric{{background:#fff;border-color:#bbb}} p,td,.notes li{{color:#444}}}}
</style></head>
<body class="{sample_class}"><main>
<header><h1>Portfolio attention report</h1><p>Section reach, accumulated visible attention, visit depth, and meaningful interactions.</p></header>
{sample_banner}
<div class="meta"><div><strong>Source</strong><br>{html.escape(data.source_type)}</div><div><strong>Input</strong><br>{html.escape(data.source_name)}</div><div><strong>Period</strong><br>{html.escape(data.date_range)}</div><div><strong>Generated</strong><br>{generated}</div></div>
<div class="metrics">{cards}</div>
{chart('Section reach', 'How many visits reached each central viewport band. Page order affects lower sections.', svg_horizontal_bars(reach_rows), data.sample)}
{chart('Section attention survival', 'Percent of each section’s seen count that crossed 3, 10, 30, and 60 accumulated visible seconds. Hero is excluded here.', main_retention + retention_table(data, non_hero), data.sample)}
{chart('Hero attention', 'Reported separately because every visit lands here and orientation time inflates its dwell.', hero_retention + retention_table(data, ('hero',)), data.sample)}
{chart('Whole-page engagement', f'Active-visible visit thresholds; rates use {denominator_label}.', svg_horizontal_bars(session_rows, '#f5c542') + f'<table><thead><tr><th>Threshold</th><th>Count</th><th>Rate</th></tr></thead><tbody>{whole_page_detail}</tbody></table>', data.sample)}
{chart('Scroll-depth funnel', 'How far visits progressed down the portfolio page.', svg_horizontal_bars(scroll_rows, '#74a7ff'), data.sample)}
{chart('Meaningful interactions', 'Deduplicated per tab-scoped session by the public tracker.', f'<table><thead><tr><th>Event</th><th>Count</th></tr></thead><tbody>{interaction_html}</tbody></table>', data.sample)}
<section class="notes"><h2>Data quality and interpretation</h2><ul>{warning_html}</ul>
<p>These metrics indicate attention patterns, not recruiter intent or content quality. Longer sections have more opportunity to accumulate time; lower sections receive fewer visitors; ad blockers make absolute counts a floor; an idle visible tab can inflate long buckets; very short mobile sections may under-accumulate in the central band. A tab-scoped session can restart after reload when browser storage is unavailable, and adjacent sections may briefly overlap the observation band.</p>
<p>The report contains aggregate counts only. Raw session hashes, locations, referrers, user-agent information, and credentials are never rendered.</p></section>
</main></body></html>"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sample", action="store_true", help="Render the clearly watermarked synthetic fixture")
    mode.add_argument("--input", type=Path, help="GoatCounter aggregate JSON ZIP or individual-pageviews CSV")
    parser.add_argument("--output", type=Path, default=Path(".analytics-private/report.html"), help="Private report output path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.sample:
            data = load_sample(Path(__file__).with_name("sample_events.csv"))
        else:
            data = load_real(args.input)
        report = render_report(data)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    except (InputError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {args.output} ({'synthetic' if data.sample else 'real export'} mode)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
