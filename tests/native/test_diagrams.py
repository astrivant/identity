"""
Preserve diagram geometry and text while making numeric SVG coordinates unambiguous to the text privacy gate.
"""

from __future__ import annotations

import re

from native.diagrams import separate_coordinates
from witful.privacy.scanner import scan_text


def test_coordinate_separators_preserve_geometry_and_sensitive_text() -> None:
    """
    Keep every numeric/path token and text label, including actual detector findings outside geometry.

    Returns:
        None: Formatting is idempotent, does not redact labels and does not relax the scanner's rules.
    """
    coordinates = " ".join(("M", "359", "240.0024", "Q", "359", "154.2156", "352.8", "154.2156", "z"))
    path = f'<path d="{coordinates}"/>'
    label = "<text>" + "555" + "-010-1234</text>"
    assert scan_text(path)
    normalized = separate_coordinates(path)
    assert scan_text(normalized) == ()
    assert re.findall(r"[-+]?\d*\.?\d+|[MQz]", path) == re.findall(r"[-+]?\d*\.?\d+|[MQz]", normalized)
    assert separate_coordinates(normalized) == normalized
    assert separate_coordinates(path + label) == normalized + label
    assert any(rule == "phone" for _, rule in scan_text(separate_coordinates(path + label)))
