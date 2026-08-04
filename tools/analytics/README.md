# Private portfolio analytics

This directory contains the local reporting tool for the portfolio's privacy-gated GoatCounter events. The public site sends only bounded event names and ordinary pageview metadata. Raw exports and generated reports stay under `.analytics-private/`, which is ignored by Git.

## What you can see

The offline report includes:

- section reach;
- 3 / 10 / 30 / 60 second section-attention survival curves;
- 15 / 30 / 60 / 120 second whole-page engagement;
- scroll depth;
- resume, email, filter, video, expansion, theme, and outbound interactions;
- data-quality and interpretation warnings.

The report is a standalone HTML file with inline SVG charts. It needs no package installation, JavaScript library, CDN, server, or network connection.

## See the dashboard immediately

From the repository root:

```sh
python3 tools/analytics/generate_report.py --sample
open .analytics-private/report.html
```

Every chart is watermarked `SYNTHETIC DATA`; these values are fictional and cannot be mistaken for production analytics.

To choose another output path:

```sh
python3 tools/analytics/generate_report.py --sample --output .analytics-private/demo.html
```

## Collection status

Production collection is active with the public GoatCounter site code `austinhuang823` in both `index.html` and `404.html`.

## Activate or change collection

1. Create a GoatCounter site.
2. Copy only its public site code—the prefix from `your-code.goatcounter.com`.
3. Set the `CODE` constant in both `index.html` and `404.html`.
4. Deploy the reviewed change.
5. Confirm the homepage and custom events appear in the private GoatCounter dashboard.

An empty `CODE` is the kill switch: the site sends zero analytics requests. Never commit or paste a GoatCounter password or API token.

## Generate a real report: recommended JSON export

GoatCounter's aggregate JSON export is the privacy-preferred input. It does **not** require enabling Individual pageviews. Download the JSON export ZIP and keep it in the ignored directory:

```sh
python3 tools/analytics/generate_report.py \
  --input .analytics-private/goatcounter-export.zip \
  --output .analytics-private/report.html
open .analytics-private/report.html
```

The adapter accepts GoatCounter JSON export major version `1`, reads only `info.json`, `paths.jsonl`, and `hit_stats.jsonl`, and fails loudly on incompatible versions or malformed references.

## Optional CSV export

GoatCounter CSV contains individual hits and session hashes. Its documentation says CSV export requires **Individual pageviews**, which is disabled by default. Enable it only if you want the optional per-session threshold-order diagnostics.

```sh
python3 tools/analytics/generate_report.py \
  --input .analytics-private/goatcounter-export.csv \
  --output .analytics-private/report.html
```

The CSV adapter accepts documented export version `2`, ignores bot rows, aggregates event names, and checks that a session never has a later threshold without all earlier thresholds. Raw sessions, locations, referrers, and browser details never appear in the report.

## Event definitions

Section events:

```text
section/<section>/seen
section/<section>/3s
section/<section>/10s
section/<section>/30s
section/<section>/60s
```

Whole-page events:

```text
session/engaged/15s
session/engaged/30s
session/engaged/60s
session/engaged/120s
```

Time accumulates only while the page is visible and, for sections, while that section intersects the central viewport band. Each threshold fires immediately and at most once per tab-scoped session. If a delayed browser tick crosses multiple thresholds, every crossed threshold fires in ascending order.

The homepage pageview is also deduplicated once per tab-scoped session, which makes it the aggregate JSON report's visit denominator.

## Reading the report carefully

- Compare section threshold rates against that section's `seen`, never total site traffic.
- Treat hero separately because every visit starts there.
- Lower sections have fewer opportunities to be reached.
- Longer sections have more opportunity to accumulate visible time.
- Ad blockers make absolute counts a floor.
- A visible but idle tab can inflate long-duration buckets.
- Use approximately four weeks and at least 50 visits before drawing strong conclusions.

## Validate

```sh
python3 -m unittest discover -s tools/analytics/tests -v
node tools/analytics/tests/tracker_test.js
python3 tools/analytics/validate_site.py
python3 tools/analytics/generate_report.py --sample
```

The first real export remains an operational validation gate even though both adapters target GoatCounter's documented formats.
