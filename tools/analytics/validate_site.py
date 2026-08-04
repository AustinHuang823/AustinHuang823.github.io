#!/usr/bin/env python3
"""Fail-closed structural and copy checks for the analytics site change."""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "index.html"
NOT_FOUND = ROOT / "404.html"


class StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hero_ids = 0
        self.details = 0
        self.project_ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id") == "hero":
            self.hero_ids += 1
        if tag == "details":
            self.details += 1
            if values.get("data-pid"):
                self.project_ids.append(values["data-pid"] or "")


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    index = INDEX.read_text(encoding="utf-8")
    not_found = NOT_FOUND.read_text(encoding="utf-8")
    parser = StructureParser()
    parser.feed(index)
    failures: list[str] = []

    require(parser.hero_ids == 1, f"expected exactly one id=hero; found {parser.hero_ids}", failures)
    require(parser.details == 11, f"expected 11 expandable project rows; found {parser.details}", failures)
    require(len(parser.project_ids) == parser.details, "every details row must have data-pid", failures)
    require(len(set(parser.project_ids)) == len(parser.project_ids), "data-pid values must be unique", failures)
    require("b.dataset.key = key;" in index, "project filter buttons must expose stable dataset.key", failures)
    require("document.addEventListener('play'" in index and "}, true);" in index, "video analytics must bind to captured play events", failures)
    require("arm/write" not in index, "branch-only arm/write analytics must not be present", failures)
    code_pattern = re.compile(r"var CODE = '([a-z0-9-]*)';")
    index_codes = code_pattern.findall(index)
    not_found_codes = code_pattern.findall(not_found)
    require(len(index_codes) == 1, "index analytics must define exactly one CODE", failures)
    require(len(not_found_codes) == 1, "404 analytics must define exactly one CODE", failures)
    if len(index_codes) == 1 and len(not_found_codes) == 1:
        require(index_codes[0] == not_found_codes[0], "index and 404 analytics CODE values must match", failures)
        require(index_codes[0] == "austinhuang823", "production analytics CODE must be austinhuang823", failures)
    require("section/" in index and "session/engaged/" in index, "section and whole-page event families must be present", failures)
    for threshold in ("[3000,'3s']", "[10000,'10s']", "[30000,'30s']", "[60000,'60s']", "[120000,'120s']"):
        require(threshold in index, f"missing tracker threshold {threshold}", failures)
    require("while (state.next < thresholds.length" in index, "multi-threshold crossing loop is missing", failures)
    disclosure = "This site uses privacy-friendly, cookie-free analytics to understand aggregate engagement and improve the portfolio."
    require(index.count(disclosure) == 1, "footer analytics disclosure must appear exactly once", failures)
    require("navigator.globalPrivacyControl" in index and "navigator.globalPrivacyControl" in not_found, "GPC gate missing", failures)
    require("doNotTrack" in index and "doNotTrack" in not_found, "DNT gate missing", failures)

    retired_patterns = {
        "As seen on TV": r"As seen on TV",
        "nationally televised": r"nationally televised",
        "hyphenated Fortune 500": r"Fortune-500",
        "coupled CAM outcome": r"class-activation mapping[^.;]{0,100}reaching 95",
        "retired focusing metric": r"70%[^.]{0,100}focusing|focusing[^.]{0,100}70%",
        "unsupported 99% application metric": r"99(?:\.0)?%[^.]{0,120}(?:target|application)",
    }
    for label, pattern in retired_patterns.items():
        require(not re.search(pattern, index, flags=re.IGNORECASE), f"retired copy resurfaced: {label}", failures)

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(f"PASS: hero=1, details={parser.details}, unique data-pid={len(parser.project_ids)}, retired-copy gates clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
