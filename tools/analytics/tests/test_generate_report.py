from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))

import generate_report as report  # noqa: E402


CSV_FIELDS = [
    "2Path", "Title", "Event", "User-Agent", "Browser", "System", "Session",
    "Bot", "Referrer", "Referrer scheme", "Screen size", "Location", "FirstVisit", "Date",
]


def csv_row(path: str, event: bool, session: str = "session-secret", location: str = "US-MA") -> list[str]:
    return [
        path, "", "true" if event else "false", "", "Chrome 1", "macOS", session,
        "0", "", "o", "1440,900,2", location, "true", "2026-08-04T12:00:00Z",
    ]


class ReportTests(unittest.TestCase):
    def test_sample_report_is_watermarked_and_complete(self) -> None:
        data = report.load_sample(TOOL_DIR / "sample_events.csv")
        rendered = report.render_report(data)
        self.assertTrue(data.sample)
        self.assertEqual(data.counts["section/projects/30s"], 30)
        self.assertIn("SYNTHETIC DEMONSTRATION", rendered)
        self.assertGreaterEqual(rendered.count("SYNTHETIC DATA"), 6)
        self.assertIn("Section attention survival", rendered)
        self.assertIn("Meaningful interactions", rendered)

    def test_csv_v2_parses_and_never_renders_raw_private_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(CSV_FIELDS)
                writer.writerow(csv_row("/", False))
                writer.writerow(csv_row("section/projects/seen", True))
                writer.writerow(csv_row("section/projects/3s", True))
                writer.writerow(csv_row("section/projects/10s", True))
            data = report.load_goatcounter_csv(path)
            rendered = report.render_report(data)
        self.assertEqual(data.source_type, "GoatCounter CSV v2")
        self.assertEqual(data.counts["section/projects/10s"], 1)
        self.assertNotIn("session-secret", rendered)
        self.assertNotIn("US-MA", rendered)

    def test_csv_session_order_violation_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(CSV_FIELDS)
                writer.writerow(csv_row("section/projects/seen", True))
                writer.writerow(csv_row("section/projects/30s", True))
            data = report.load_goatcounter_csv(path)
        self.assertTrue(any("threshold-order violations" in warning for warning in data.warnings))

    def test_csv_rejects_unknown_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.csv"
            fields = CSV_FIELDS.copy()
            fields[0] = "3Path"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(fields)
                writer.writerow(csv_row("/", False))
            with self.assertRaises(report.InputError):
                report.load_goatcounter_csv(path)

    def test_json_zip_aggregates_paths_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("info.json", json.dumps({"export_version": "1.0"}))
                archive.writestr(
                    "paths.jsonl",
                    "\n".join([
                        json.dumps({"id": 1, "path": "/", "title": "Home"}),
                        json.dumps({"id": 2, "path": "section/projects/seen", "event": True, "title": ""}),
                        json.dumps({"id": 3, "path": "section/projects/3s", "event": True, "title": ""}),
                    ]),
                )
                archive.writestr(
                    "hit_stats.jsonl",
                    "\n".join([
                        json.dumps({"hour": "2026-08-04T10:00:00Z", "path_id": 1, "ref_id": 1, "count": 8}),
                        json.dumps({"hour": "2026-08-04T10:00:00Z", "path_id": 2, "ref_id": 1, "count": 6}),
                        json.dumps({"hour": "2026-08-04T10:00:00Z", "path_id": 3, "ref_id": 1, "count": 4}),
                        json.dumps({"hour": "2026-08-04T11:00:00Z", "path_id": 3, "ref_id": 2, "count": 2}),
                    ]),
                )
            data = report.load_goatcounter_json_zip(path)
        self.assertEqual(data.page_counts["/"], 8)
        self.assertEqual(data.counts["section/projects/seen"], 6)
        self.assertEqual(data.counts["section/projects/3s"], 6)
        self.assertEqual(data.source_type, "GoatCounter aggregate JSON export")

    def test_json_zip_rejects_incompatible_major_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("info.json", json.dumps({"export_version": "2.0"}))
                archive.writestr("paths.jsonl", "")
                archive.writestr("hit_stats.jsonl", "")
            with self.assertRaises(report.InputError):
                report.load_goatcounter_json_zip(path)

    def test_impossible_aggregate_sequence_is_flagged(self) -> None:
        data = report.Dataset(source_type="test", source_name="test")
        data.page_counts["/"] = 10
        data.counts["section/skills/seen"] = 4
        data.counts["section/skills/3s"] = 5
        warnings = report.data_quality_warnings(data)
        self.assertTrue(any("exceeds seen" in warning for warning in warnings))

    def test_section_seen_exceeding_visit_denominator_is_flagged(self) -> None:
        data = report.Dataset(source_type="test", source_name="test")
        data.page_counts["/"] = 10
        data.counts["section/projects/seen"] = 11
        warnings = report.data_quality_warnings(data)
        self.assertTrue(any("seen (11) exceeds the visit denominator (10)" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
