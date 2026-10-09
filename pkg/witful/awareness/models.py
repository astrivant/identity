"""
Define the versioned figure bundle and opt-in GitHub publication configuration.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen

FIGURES = {
    "knowledge-usage": ("knowledge", "Recorded skill use"),
    "knowledge-map": ("knowledge", "How my skills connect"),
    "decision-influences": ("life", "What informs my decisions"),
    "knowledge-hierarchy": ("knowledge", "Knowledge hierarchy"),
    "toolbox-use": ("repertoire", "Recorded tool use"),
    "problem-repertoire": ("repertoire", "Problem repertoire"),
    "checkpoint-transitions": ("checkpoints", "Project transitions"),
    "checkpoint-comparisons": ("checkpoints", "Project comparisons"),
}
BRANCH = "witful-awareness"
BUNDLE_PATH = "awareness.json"
EVENT = "witful-awareness"
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024


@frozen
class PushConfig:
    """
    Select a destination and exactly which derived images may be published.

    Attributes:
        repository (str): Existing GitHub owner/repository receiving data and dispatch.
        figures (tuple[str, ...]): Explicit figure IDs in publication order; empty disables publication.
    """

    repository: str
    figures: tuple[str, ...] = ()


@frozen
class Figure:
    """
    Carry one fixed PNG and its integrity digest, with no executable content.

    Attributes:
        id (str): Stable catalog key.
        group (str): Knowledge, life, repertoire, or checkpoints category.
        title (str): Public caption, separate from labels already visible in the image.
        sha256 (str): Hexadecimal SHA-256 of decoded PNG bytes.
        png (str): Strict base64-encoded PNG.
    """

    id: str
    group: str
    title: str
    sha256: str
    png: str


@frozen
class Bundle:
    """
    Export only selected figures, without source paths, account identity, or journal records.

    Attributes:
        figures (tuple[Figure, ...]): Ordered, unique publication figures.
        version (Literal[1]): Supported wire schema version.
    """

    figures: tuple[Figure, ...]
    version: Literal[1] = 1
