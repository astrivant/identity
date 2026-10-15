"""
Dispatch parsed native commands and keep compatibility file I/O inside explicitly protected boundaries.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import time
from http import HTTPStatus
from http.client import HTTPConnection, HTTPException
from typing import TYPE_CHECKING

from witful.collection.protection import require_protected
from witful.exceptions import NativeError, StorageProtectionError
from witful.knowledge.contracts import schema
from witful.native import codec, domains
from witful.native.client import Client, ClientSettings
from witful.native.config import Evidence, Settings, load, require_profile
from witful.native.domains import Entry
from witful.native.wire import mapping, sequence, text

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def health(settings: Settings) -> int:
    """
    Probe this pod's loopback listener while validating the configured certificate name and a real client certificate.

    Args:
        settings (Settings): Closed server and probe TLS settings.

    Returns:
        int: Zero only when this local worker reports ready.
    """
    connection = HTTPConnection("127.0.0.1", settings.runtime.port, timeout=5)
    try:
        context = ssl.create_default_context(cafile=settings.tls.ca)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(settings.tls.client_certificate, settings.tls.client_key)
        raw = socket.create_connection(("127.0.0.1", settings.runtime.port), timeout=5)
        try:
            connection.sock = context.wrap_socket(raw, server_hostname=settings.tls.server_name)
        except (OSError, ValueError):
            raw.close()
            raise
        connection.request("GET", "/ready")
        response = connection.getresponse()
        return 0 if response.status == HTTPStatus.OK and response.read(32) == b"ready\n" else 1
    except (OSError, HTTPException, ValueError):
        return 1
    finally:
        connection.close()


def write(path: Path, value: object, encrypted: bool = False) -> None:
    """
    Create a new protected compatibility output without overwriting a user's existing file.

    Args:
        path (Path): Explicit destination on verified protected working storage.
        value (object): Authorized response.
        encrypted (bool): Whether the response is an already encrypted recovery package serialized as CBOR.

    Returns:
        None: The complete output is fsynced with private permissions.
    """
    if not encrypted:
        require_protected(path.parent)
    encoded = (
        codec.encode(value, codec.Limits(bytes=64 * 1024 * 1024))
        if encrypted
        else (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode()
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(encoded)
        output.flush()
        os.fsync(output.fileno())


def execute(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Execute one selected leaf without reparsing argv or starting unrelated domain runtimes.

    Args:
        args (argparse.Namespace): Namespace parsed by the shared recursive builder.
        parser (argparse.ArgumentParser): Owning leaf parser.

    Returns:
        int: Selected operation status, with redacted failures and no implicit network retry.
    """
    operation: str = args.native_operation
    try:
        if operation == "schema":
            from witful.native.sharing_cli import Expectation

            models = {"server": Settings, "client": ClientSettings, "evidence": Evidence, "recipient": Expectation}
            print(json.dumps(schema(models[args.kind]), indent=2))
            return 0
        if operation in {"serve", "check", "health"}:
            settings = load(args.config)
            require_profile(settings, int(time.time()))
            if operation == "check":
                print("Configuration schema and signed protection evidence verified")
                return 0
            if operation == "health":
                return health(settings)
            os.environ["WITFUL_NATIVE_CONFIG"] = str(args.config.resolve())
            os.execv(
                sys.executable,
                [sys.executable, "-m", "gunicorn", "--config", "python:witful.native.gunicorn", "witful.native.application:create_app()"],
            )
        require_protected(args.client)
        client = Client.load(args.client)
        arguments: object
        if args.output is not None:
            if operation not in {"export", "share"}:
                require_protected(args.output.parent)
            if args.output.exists():
                raise NativeError("conflict")
        if operation in {"append", "merge"}:
            require_protected(args.input)
            with args.input.open("rb") as source:
                raw = source.read(client.settings.max_bytes + 1)
            if len(raw) > client.settings.max_bytes:
                raise NativeError("incomplete")
            imported = json.loads(raw)
        if operation == "append":
            records = [mapping(value, {"domain", "value"}) for value in sequence(imported)]
            arguments = {
                "operation": args.operation,
                "ref": args.ref,
                "expected": args.expected,
                "entries": [domains.encode(Entry(text(item["domain"]), item["value"])) for item in records],
            }
        elif operation == "merge":
            review = mapping(imported, {"reason", "selections"})
            selections: list[dict[str, object]] = []
            for value in sequence(review["selections"]):
                selection = mapping(value, {"sources", "domain", "value"})
                selections.append(
                    {
                        "sources": [text(source) for source in sequence(selection["sources"])],
                        "entry": domains.encode(Entry(text(selection["domain"]), selection["value"])),
                    }
                )
            arguments = {
                "operation": args.operation,
                "target": args.target,
                "candidate": args.candidate,
                "expected": args.expected,
                "reviewed": args.reviewed,
                "selections": selections,
                "reason": text(review["reason"]),
            }
        elif operation == "migrate":
            arguments = {"operation": args.operation, "destination": args.destination}
        elif operation == "migration-abort":
            arguments = {"operation": args.operation}
        elif operation == "rotate":
            arguments = {"operation": args.operation, "mode": args.mode}
        elif operation == "share":
            arguments = {"recipient": args.recipient}
        elif operation == "restore":
            with args.input.open("rb") as source:
                raw = source.read(client.settings.max_bytes + 1)
            package = mapping(codec.decode(raw, codec.Limits(bytes=client.settings.max_bytes)), {"context", "sealed"})
            arguments = {**package, "destination": args.destination}
        elif operation == "original-capture":
            arguments = {"operation": args.operation, "path": args.path, "unreachable": args.unreachable, "reflogs": args.reflogs}
        elif operation == "original-restore":
            arguments = {"path": args.path, "record": args.record}
        elif operation == "read":
            arguments = {"record": args.record}
        elif operation == "history":
            arguments = {"ref": args.ref}
        elif operation == "search":
            arguments = {"ref": args.ref, "query": args.query}
        elif operation == "branch":
            arguments = {"operation": args.operation, "name": args.name, "record": args.record, "immutable": args.immutable}
        else:
            arguments = {}
        result = client.invoke(operation, arguments)
        if operation == "read":
            entry = domains.decode(result)
            result = {"domain": entry.domain, "value": entry.value}
        elif operation == "history":
            history: list[dict[str, object]] = []
            for item in sequence(result):
                record = mapping(item, {"revision", "entry"})
                entry = domains.decode(record["entry"])
                history.append({"revision": record["revision"], "domain": entry.domain, "value": entry.value})
            result = history
        if args.output is not None:
            write(args.output, result, encrypted=operation in {"export", "share"})
        else:
            print(json.dumps(result, ensure_ascii=True))
        return 0
    except NativeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, StorageProtectionError):
        print("Native operation unavailable", file=sys.stderr)
        return 1
