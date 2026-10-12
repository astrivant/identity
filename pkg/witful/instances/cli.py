"""
Start, reconcile, correlate, inspect, and compare explicit instance observations locally.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from jsonschema import ValidationError

from witful.files import replace_file
from witful.instances.journal import check_references, instance_resource, pending_tasks, read, record, require_ready, start
from witful.instances.models import Audit, Event, Task
from witful.instances.reporting import build, comparisons, logs
from witful.knowledge.contracts import as_data, schema

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run bounded local instance operations without changing native journals or contacting an exporter.

    Args:
        argv (Sequence[str] | None): Explicit arguments or process command line.

    Returns:
        int: Zero on success; parser exit two on invalid provenance, incomplete coverage, or source corruption.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    creation = commands.add_parser("start", help="Reuse a known boundary or record a new observed instance")
    creation.add_argument("--boundary-id", required=True)
    creation.add_argument("--boundary-kind", choices=("runtime", "logical-session"), required=True)
    for name in (
        "session-id",
        "served-model",
        "model-evidence",
        "requested-model",
        "template-revision",
        "parent-instance-id",
        "predecessor-instance-id",
    ):
        creation.add_argument("--" + name)
    creation.add_argument("--coverage", choices=("incomplete", "complete"), default="incomplete")
    creation.add_argument("--coverage-source")
    for command in ("reconcile", "task", "audit", "observe", "stop"):
        operation = commands.add_parser(command)
        operation.add_argument("--instance-id", required=True)
        operation.add_argument("--operation-id", required=True)
        if command == "reconcile":
            operation.add_argument("--coverage", choices=("incomplete", "complete"), required=True)
            operation.add_argument("--coverage-source")
        if command == "task":
            operation.add_argument("--task-id", required=True)
            operation.add_argument("--status", choices=("pending", "running", "blocked", "succeeded", "failed", "cancelled"), required=True)
            operation.add_argument("--summary", required=True)
            operation.add_argument("--source", required=True)
            operation.add_argument("--previous", help="Exact preceding task event ID, required for updates")
        if command == "audit":
            operation.add_argument("--action", required=True)
            operation.add_argument("--outcome", default="unknown")
            operation.add_argument("--request-id")
            operation.add_argument("--trace-id")
            operation.add_argument("--span-id")
    for command in ("guard", "resource"):
        operation = commands.add_parser(command)
        operation.add_argument("--instance-id", required=True)
    for command in ("status", "check", "schemas", "logs"):
        commands.add_parser(command)
    render = commands.add_parser("build")
    render.add_argument("--output-dir", type=Path, default=Path("docs/assets"))
    render.add_argument("--limit", type=int, default=8)
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    try:
        result: object
        if args.command == "start":
            event = start(
                root,
                args.boundary_id,
                args.boundary_kind,
                session_id=args.session_id,
                served_model=args.served_model,
                model_evidence=args.model_evidence,
                requested_model=args.requested_model,
                template_revision=args.template_revision,
                coverage=args.coverage,
                coverage_source=args.coverage_source,
                parent_instance_id=args.parent_instance_id,
                predecessor_instance_id=args.predecessor_instance_id,
            )
            # Retain the exact startup frontier rather than silently substituting current task states on retry.
            indexed = {item.id: item for item in read(root)}
            result = {
                "instance_id": event.instance_id,
                "event": as_data(event),
                "pending_tasks": [as_data(indexed[key]) for key in event.pending],
            }
        elif args.command in {"reconcile", "task", "audit", "observe", "stop"}:
            task = Task(args.task_id, args.status, args.summary, args.source, args.previous) if args.command == "task" else None
            audit = Audit(args.action, args.outcome, args.request_id, args.trace_id, args.span_id) if args.command == "audit" else None
            event = record(
                root,
                args.instance_id,
                args.operation_id,
                args.command,
                task=task,
                audit=audit,
                coverage=args.coverage if args.command == "reconcile" else None,
                coverage_source=args.coverage_source if args.command == "reconcile" else None,
            )
            result = as_data(event)
        elif args.command == "schemas":
            path = root / "knowledge/schemas/instance-event.schema.json"
            replace_file(
                path,
                (json.dumps(schema(Event), indent=2, sort_keys=True) + "\n").encode(),
                expected=path.read_bytes() if path.exists() else None,
            )
            result = {"schema": str(path)}
        elif args.command == "resource":
            result = instance_resource(root, args.instance_id)
        elif args.command == "guard":
            require_ready(read(root), args.instance_id)
            result = {"instance_id": args.instance_id, "ready": True}
        elif args.command == "logs":
            result = logs(root)
        elif args.command == "build":
            output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
            result = {"artifacts": [str(path) for path in build(root, output, args.limit)]}
        else:
            events = read(root)
            diffs = comparisons(root, events)
            result = {
                "events": len(events),
                "instances": [as_data(item.instance) for item in events if item.instance is not None],
                "pending_tasks": [as_data(item) for item in pending_tasks(events)],
                "evidence_gaps": list(check_references(root, events)),
                "comparisons": [as_data(item) for item in diffs],
            }
        print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, ValueError, RuntimeError, ValidationError, subprocess.TimeoutExpired):
        parser.exit(
            2,
            "Instance operation failed: validate IDs, immutable retry keys, native sources, and reconciliation coverage. "
            "Original journals were preserved; no source text or credentials were logged.\n",
        )
    return 0
