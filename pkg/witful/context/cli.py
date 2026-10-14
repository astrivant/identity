"""
Prepare and revalidate advisory local context receipts without installing hooks or executing knowledge.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from attrs import evolve
from jsonschema import ValidationError

from witful.collection.protection import check_collection
from witful.commands.context import configure
from witful.context.core import check, digest, resolve
from witful.context.models import Descriptor, Mapping, Receipt, Review
from witful.context.storage import capture, destination, read
from witful.files import replace_file
from witful.knowledge.contracts import as_data, schema, structure

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run explicit offline snapshot, plan, resolve, or check operations.

    Args:
        argv (Sequence[str] | None): Selected arguments or process command line.

    Returns:
        int: Zero for snapshot/schema or complete coverage, one for gaps, two for invalid inputs or unavailable state.
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
    root = args.repo.resolve()
    try:
        if args.command == "schema":
            print(
                json.dumps(
                    {"mapping": schema(Mapping), "descriptor": schema(Descriptor), "review": schema(Review), "receipt": schema(Receipt)},
                    indent=2,
                )
            )
            return 0
        started = time.monotonic()
        now = int(time.time())
        if args.command == "snapshot":
            tree, observation = capture(root, (), now, now)
            print(
                json.dumps(
                    {
                        "identity": tree.id,
                        "hierarchy_digest": digest(tree),
                        "source_revision": observation.source_revision,
                        "observed_at": now,
                        "offline": True,
                        "advisory": True,
                    },
                    indent=2,
                )
            )
            return 0
        inputs = [args.mapping, args.descriptor]
        if args.decisions:
            inputs.append(args.decisions)
        if args.command == "check":
            inputs.append(args.input)
        check_collection(root, *inputs)
        mapping, descriptor = structure(read(args.mapping), Mapping), structure(read(args.descriptor), Descriptor)
        # A denied scope never loads the journal, graph, workspace fingerprints, or a previous receipt.
        if mapping.scope != descriptor.scope:
            print(json.dumps({"state": "invalid", "blockers": ["access_unavailable"], "advisory": True}))
            return 2
        review = structure(read(args.decisions), Review) if args.decisions else Review()
        tree, observation = capture(root, tuple(args.workspace), args.observed_at, now)
        observation = evolve(
            observation,
            source_reads=observation.source_reads + 2 + int(args.decisions is not None),
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        receipt = resolve(tree, mapping, descriptor, observation, review.decisions)
        if args.command == "check":
            previous = structure(read(args.input), Receipt)
            errors = check(previous, receipt, context_present=args.context_present)
            print(json.dumps({"passed": not errors, "state": receipt.state, "errors": errors, "advisory": True}, indent=2))
            return int(bool(errors))
        output = destination(root, args.output)
        before = output.read_bytes() if output.exists() else None
        if before is not None and not args.replace:
            raise ValueError("An existing receipt needs explicit replacement")
        replace_file(output, (json.dumps(as_data(receipt), indent=2) + "\n").encode(), expected=before)
        print(json.dumps({"path": str(output), "state": receipt.state, "binding": receipt.binding, "advisory": True}, indent=2))
        return 0 if receipt.state == "complete" else 2 if receipt.state == "invalid" else 1
    except (OSError, ValueError, RuntimeError, ValidationError, subprocess.SubprocessError):
        print(
            "Context unavailable: check the authorized collection, closed input contracts and workspace. No action is authorized.",
            file=sys.stderr,
        )
        return 2
