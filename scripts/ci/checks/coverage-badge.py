"""
Render a stable SVG badge from the combined pytest coverage report without external services.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree

report = ElementTree.parse(".cache/coverage/coverage.xml").getroot()
covered = int(report.attrib["lines-covered"])
total = int(report.attrib["lines-valid"])

# Missing or inconsistent results must fail publication instead of presenting an invented coverage percentage.
if total <= 0 or not 0 <= covered <= total:
    raise ValueError("Coverage badge requires a nonempty report with valid covered and total line counts.")

percent = Decimal(covered * 100) / Decimal(total)
label = f"{percent:.1f}".removesuffix(".0") + "%"
color = "#4c1" if percent >= 90 else "#97ca00" if percent >= 75 else "#dfb317" if percent >= 60 else "#e05d44"

# Keep the output deterministic so unchanged percentages produce no publication commit.
badge = (Path(__file__).parent / "resources/coverage.svg").read_text(encoding="utf-8").format(label=label, color=color)
destination = Path(".cache/coverage-badge/coverage.svg")
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(badge, encoding="utf-8")
