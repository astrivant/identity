"""
Expose a read-only PII gate for source checks, pre-commit, and CI.
"""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING

from attrs import asdict

from witful.commands.privacy import configure
from witful.privacy.scanner import scan_report

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """
    Report only finding locations and detector IDs, keeping sensitive matches out of logs.

    Args:
        argv (Sequence[str] | None): Explicit arguments or the current process arguments.

    Returns:
        int: Zero without detections, one for findings, two for errors or required but incomplete coverage.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    configure(parser)
    return execute(parser.parse_args(argv), parser)


def execute(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Execute an already parsed domain command.

    Args:
        args (argparse.Namespace): Validated arguments from the shared hierarchy or standalone parser.
        parser (argparse.ArgumentParser): Owning parser for consistent error reporting.

    Returns:
        int: Selected operation status.
    """

    try:
        terms = tuple(line.strip() for line in args.terms_file.read_text().splitlines() if line.strip()) if args.terms_file else ()
        report = scan_report(args.repo, staged=args.staged, paths=args.paths, terms=terms)
    except (OSError, UnicodeError, ValueError):
        parser.exit(2, "PII scan incomplete: check repository access, paths, and the private terms file.\n")

    for finding in report.findings:
        print(json.dumps(asdict(finding), separators=(",", ":")))

    for status, gaps in (("skipped", report.skipped), ("error", report.errors)):
        for gap in gaps:
            print(json.dumps({"status": status, **asdict(gap)}, separators=(",", ":")))

    print(
        json.dumps(
            {
                "findings": len(report.findings),
                "skipped": len(report.skipped),
                "errors": len(report.errors),
                "complete": report.complete,
            },
            separators=(",", ":"),
        )
    )
    # Inspection errors take precedence; unsupported content is fatal only under explicit strict coverage.
    if report.errors or (args.require_complete and not report.complete):
        return 2
    return int(bool(report.findings))
