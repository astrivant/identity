"""
Append reviewed choices with immutable snapshots and explicit causal revisions.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING

from attrs import evolve
from matplotlib import ft2font, get_data_path

from witful.files import replace_file
from witful.knowledge.contracts import as_data, structure
from witful.knowledge.models import Application, Catalog
from witful.life.contracts import canonical, content_id, snapshot_identity, validate_archive
from witful.life.models import Archive, Event, Snapshot

if TYPE_CHECKING:
    from witful.life.models import Decision

__all__ = ["capture_snapshot", "read_archive", "record_decision", "renderer_fingerprint"]


def renderer_fingerprint(root: Path) -> tuple[str, ...]:
    """
    Identify rendering code, dependency lock, interpreter, and graphics environment.

    Args:
        root (Path): Checkout providing the pinned Poetry lock.

    Returns:
        tuple[str, ...]: Stable sorted fingerprint entries; differences require explicit replay acknowledgement.
    """
    package = Path(__file__).parents[1]
    names = ["files.py", "lessons.py"]
    names.extend(str(path.relative_to(package)) for path in (package / "knowledge").glob("*.py"))
    names.extend(str(path.relative_to(package)) for path in (package / "life").glob("*.py"))
    digest = hashlib.sha256()

    for name in sorted(names):
        digest.update(canonical([name, (package / name).read_text()]))

    # Packaged typography and palette are replay inputs too, including helper-only changes.
    for resource in sorted((package / "life/resources").glob("*")):
        digest.update(resource.name.encode())
        digest.update(resource.read_bytes())

    entries = [
        "code=" + digest.hexdigest(),
        "lock=" + (hashlib.sha256((root / "poetry.lock").read_bytes()).hexdigest() if (root / "poetry.lock").exists() else "absent"),
        "python=" + sys.version.split()[0],
        "platform=" + platform.system() + "/" + platform.machine(),
        "freetype=" + ft2font.__freetype_version__,
        "font=" + hashlib.sha256((Path(get_data_path()) / "fonts/ttf/DejaVuSans.ttf").read_bytes()).hexdigest(),
    ]
    entries.extend(f"{name}={version(name)}" for name in ("matplotlib", "networkx", "numpy", "pillow", "attrs", "cattrs"))
    return tuple(sorted(entries))


def capture_snapshot(root: Path, revision: str | None = None) -> Snapshot:
    """
    Freeze validated plot sources before a decision is appended.

    Args:
        root (Path): Existing identity source checkout.
        revision (str | None): Existing Git revision to import, or current working-tree inputs.

    Returns:
        Snapshot: Content-addressed snapshot, independent of future edits to source files.
    """
    resolved = "working-tree"

    def git_output(*arguments: str) -> str:
        """
        Read a known source path or resolve a commit without executing shell expressions.

        Args:
            *arguments (str): Fixed Git operation and separately passed arguments.

        Returns:
            str: Captured source text; operational failures become concise input errors.
        """
        try:
            result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True, timeout=15, check=False)
        except subprocess.TimeoutExpired:
            raise ValueError("Timed out reading the historical source revision") from None

        if result.returncode:
            raise ValueError("Historical source revision or required knowledge file is unavailable")

        return result.stdout

    if revision is not None:
        resolved = git_output("rev-parse", "--verify", "--end-of-options", revision + "^{commit}").strip()

    def source(name: str) -> str:
        """
        Select the same source revision for all files in the frozen input set.

        Args:
            name (str): Package-owned relative source path.

        Returns:
            str: Current file contents or exact file contents from the selected Git tree.
        """
        return (root / name).read_text() if revision is None else git_output("show", f"{resolved}:{name}")

    applications = tuple(structure(json.loads(line), Application) for line in source("knowledge/applications.jsonl").splitlines())
    snapshot = Snapshot(
        "",
        source("lessons.jsonl"),
        structure(json.loads(source("knowledge/catalog.json")), Catalog),
        applications,
        renderer_fingerprint(root),
        resolved,
    )
    snapshot = evolve(snapshot, id=content_id(snapshot))
    snapshot_identity(snapshot)
    return snapshot


def read_archive(root: Path) -> Archive:
    """
    Load only snapshots referenced by the reviewed decision journal.

    Args:
        root (Path): Checkout owning knowledge/life.jsonl and knowledge/snapshots/.

    Returns:
        Archive: Fully validated history; a checkout without a journal has an empty history.
    """
    path = root / "knowledge/life.jsonl"
    events = tuple(structure(json.loads(line), Event) for line in path.read_text().splitlines()) if path.exists() else ()
    snapshots: list[Snapshot] = []

    for identifier in sorted({event.snapshot_id for event in events}):
        # Validate the digest before using it as a filename supplied by an imported audit record.
        if len(identifier) != 64 or any(character not in "0123456789abcdef" for character in identifier):
            raise ValueError("Invalid snapshot identifier")

        snapshot = structure(json.loads((root / "knowledge/snapshots" / f"{identifier}.json").read_text()), Snapshot)

        if snapshot.id != identifier:
            raise ValueError("Snapshot filename does not match its contents")

        snapshots.append(snapshot)

    archive = Archive(events, tuple(snapshots))
    validate_archive(archive)
    return archive


def record_decision(root: Path, decision: Decision, *, source_revision: str | None = None) -> Event:
    """
    Append one decision under an exclusive lock, writing its snapshot before publishing its event.

    Args:
        root (Path): Existing source checkout; no project or repository is created.
        decision (Decision): Complete reviewed choice, including an explicit supersedes ID for revisions.
        source_revision (str | None): Git revision providing historical inputs for a retrospective record.

    Returns:
        Event: Existing matching head for a repeated request, or the newly appended observation.

    Raises:
        ValueError: A choice, snapshot, or revision is invalid; the journal stays unchanged.
    """
    path = root / "knowledge/life.jsonl"

    with (root / ".life.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        original = path.read_bytes() if path.exists() else None
        archive = read_archive(root)
        head = next((item for item in reversed(archive.events) if item.decision.key == decision.key), None)

        # Retrying the same reviewed request must not manufacture another historical observation.
        if head and head.decision == decision:
            return head

        snapshot = capture_snapshot(root, source_revision)
        event = Event("", archive.events[-1].id if archive.events else None, datetime.now(UTC).isoformat(), snapshot.id, decision)
        event = evolve(event, id=content_id(event))
        snapshots = {item.id: item for item in (*archive.snapshots, snapshot)}
        validate_archive(Archive((*archive.events, event), tuple(snapshots[key] for key in sorted(snapshots))))
        target = root / "knowledge/snapshots" / f"{snapshot.id}.json"
        content = canonical(as_data(snapshot)) + b"\n"

        if target.exists() and target.read_bytes() != content:
            raise ValueError("Existing snapshot cannot be overwritten")

        replace_file(target, content, expected=content if target.exists() else None)
        separator = b"\n" if original and not original.endswith(b"\n") else b""
        replace_file(path, (original or b"") + separator + canonical(as_data(event)) + b"\n", expected=original)
        return event
