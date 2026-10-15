"""
Verify recipient-only exports offline using independent sender pins and protected local recipient custody.
"""

from __future__ import annotations

import base64
import json
import sys
import time
from typing import TYPE_CHECKING, Literal

from attrs import frozen
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from witful.collection.exports import read_file
from witful.collection.protection import require_protected
from witful.exceptions import NativeError, StorageProtectionError
from witful.knowledge.contracts import as_data
from witful.native import codec, domains
from witful.native.cli import write
from witful.native.config import Trust  # noqa: TC001 - cattrs/schema resolve this nested model at runtime.
from witful.native.context import Context
from witful.native.envelope import EnvelopeService, Signer
from witful.native.kinds import FRONTIER
from witful.native.models import Frontier, Pointer, parse
from witful.native.service import Budget
from witful.native.sharing import Disclosure, PrivateRecipient, open_disclosure
from witful.native.values import pack
from witful.native.wire import binary, mapping

if TYPE_CHECKING:
    import argparse


@frozen
class Expectation:
    """
    Bind an offline review to externally selected provenance rather than trusting metadata carried by the export.

    Attributes:
        context (Context): Expected immutable tenant, identity and export UUID with sharing kind 11.
        generation (int): Expected exported frontier generation, obtained independently to detect rollback.
        root (str | None): Expected frontier UUID, or None for a deliberately empty identity.
        digest (str): Expected ciphertext frontier SHA-256 in hexadecimal, empty for an empty identity.
        wrapping (str): Recipient generation UUID, separately selected from the private key.
        signing (str): Expected outer sender signing generation.
        signers (tuple[Trust, ...]): Independently pinned outer and retained historical sender public keys.
        budget (Budget): Explicit complete-history verification and output limits.
        envelope (codec.Limits): Explicit bounded binary decoding limits.
        version (Literal[1]): Closed verification contract version.
    """

    context: Context
    generation: int
    root: str | None
    digest: str
    wrapping: str
    signing: str
    signers: tuple[Trust, ...]
    budget: Budget = Budget()
    envelope: codec.Limits = codec.DEFAULT_LIMITS
    version: Literal[1] = 1


def report(disclosure: Disclosure) -> object:
    """
    Render each current revision once while retaining the complete original history in the encrypted package.

    Args:
        disclosure (Disclosure): Fully verified recipient-owned read-only archive.

    Returns:
        object: JSON current refs, revisions, base64 original source bytes and archival manifest pointers.
    """
    head = disclosure.archive.head
    view = disclosure.view
    frontier = Frontier() if head.root is None else parse(view.open(Pointer(head.root, head.root, FRONTIER, head.digest.hex())), Frontier)
    revisions: list[object] = []
    started, size = view.monotonic(), 0
    for pointer in frontier.revisions:
        revision = view.revision(frontier, pointer.record)
        entry = domains.decode(view.open(revision.payload))
        original = binary(view.open(revision.source)) if revision.source is not None else None
        value = {
            "revision": as_data(revision),
            "entry": {"domain": entry.domain, "value": entry.value},
            "source_base64": base64.b64encode(original).decode() if original is not None else None,
        }
        size += len(codec.encode(pack(value), view.keys.limits))
        if size > view.budget.bytes or view.monotonic() - started > view.budget.seconds:
            raise NativeError("incomplete")
        revisions.append(value)
    return {
        "version": 1,
        "scope": as_data(disclosure.archive.scope),
        "recorded": disclosure.recorded,
        "head": {"generation": head.generation, "root": head.root, "digest": head.digest.hex()},
        "frontier": as_data(frontier),
        "revisions": revisions,
    }


def execute(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Load only recipient-local custody, verify expected history and write a new protected output without contacting the source.

    Args:
        args (argparse.Namespace): Parsed explicit file paths; no secret values arrive through argv.
        parser (argparse.ArgumentParser): Owning leaf parser, retained for the common command-handler contract.

    Returns:
        int: Zero only after complete verification and protected output publication; failures expose no key or plaintext detail.
    """
    try:
        require_protected(args.output.parent)
        if args.output.exists():
            raise NativeError("conflict")
        expected = parse(json.loads(read_file(args.trust, private=True)), Expectation)
        if not expected.signers or len({signer.generation for signer in expected.signers}) != len(expected.signers):
            raise NativeError("invalid")
        # A password is mandatory: an unencrypted PEM is not an accepted recipient custody profile.
        private = serialization.load_pem_private_key(
            read_file(args.private_key, private=True), password=read_file(args.password_file, private=True)
        )
        if not isinstance(private, rsa.RSAPrivateKey):
            raise NativeError("invalid")
        keys = EnvelopeService(
            PrivateRecipient(expected.wrapping, private),
            expected.wrapping,
            expected.signing,
            {signer.generation: Signer(base64.b64decode(signer.public, validate=True), signer.fingerprint) for signer in expected.signers},
            expected.envelope,
        )
        with args.input.open("rb") as source:
            raw = source.read(expected.budget.bytes + 1)
        if len(raw) > expected.budget.bytes:
            raise NativeError("incomplete")
        package = mapping(codec.decode(raw, expected.envelope), {"context", "sealed"})
        if parse(package["context"], Context) != expected.context:
            raise NativeError("denied")
        sealed = binary(package["sealed"])
        header = keys.verify(expected.context, sealed)
        if header["w"] != expected.wrapping or header["s"] != expected.signing:
            raise NativeError("denied")
        disclosure = open_disclosure(expected.context, sealed, keys, expected.budget, time.monotonic)
        head = disclosure.archive.head
        if (head.generation, head.root, head.digest.hex()) != (expected.generation, expected.root, expected.digest):
            raise NativeError("conflict")
        write(args.output, report(disclosure))
        print("Recipient export verified; reviewed data written to protected output")
        return 0
    except NativeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm, StorageProtectionError):
        print("Recipient verification unavailable", file=sys.stderr)
        return 1
