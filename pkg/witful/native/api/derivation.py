"""
Expose reviewed fork/split through configured destination aliases and the consolidated native application.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from flask import Blueprint, Response

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec, domains
from witful.native.api.requests import decode
from witful.native.authority import Access
from witful.native.derivation import Child, derive
from witful.native.reconciliation import Selection
from witful.native.storage import Scope
from witful.native.wire import mapping, sequence, text

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.native.config import DerivationTarget
    from witful.native.service import Service


def routes(
    service: Service,
    authenticate: Callable[[], str],
    destinations: tuple[Service, ...],
    aliases: tuple[DerivationTarget, ...],
) -> Blueprint:
    """
    Accept explicit review documents while keeping backend, scope and grant provisioning outside client requests.

    Args:
        service (Service): Current authenticated parent runtime.
        authenticate (Callable[[], str]): Actual verified TLS peer boundary.
        destinations (tuple[Service, ...]): Operator-selected existing storage/custody adapters.
        aliases (tuple[DerivationTarget, ...]): Reviewed recipient scope and independent grant bindings.

    Returns:
        Blueprint: Fork/split endpoint with no implicit authority creation or arbitrary remote target.
    """
    blueprint = Blueprint("native_derivation", __name__)
    backends = {target.authority.backend: target for target in (service, *destinations)}
    configured = {target.name: target for target in aliases}

    @blueprint.post("/v1/derive")
    def adopt() -> Response:
        """
        Publish reviewed selections only after source and every configured recipient independently authorize the same actor.

        Returns:
            Response: Parent receipt after atomic publication of all verified output frontiers.
        """
        access, arguments = decode(service, authenticate)
        args = mapping(arguments, {"operation", "expected", "mode", "reason", "children"})
        children: list[Child] = []
        for item in sequence(args["children"]):
            value = mapping(item, {"destination", "ref", "selections"})
            target = configured.get(text(value["destination"]))
            if target is None or target.backend not in backends:
                raise NativeError("denied")
            selections: list[Selection] = []
            for item in sequence(value["selections"]):
                selection = mapping(item, {"sources", "entry"})
                selections.append(
                    Selection(tuple(text(source) for source in sequence(selection["sources"])), domains.decode(selection["entry"]))
                )
            target_access = Access(
                Scope(target.tenant, target.identity),
                access.subject,
                target.grant,
                target.task,
                target.epoch,
                target.policy,
            )
            children.append(Child(backends[target.backend], target_access, text(value["ref"]), tuple(selections)))
        mode = text(args["mode"])
        if mode not in {"fork", "split"} or not children or (mode == "fork") != (len(children) == 1):
            raise NativeError("invalid")
        receipt = derive(service, access, text(args["operation"]), text(args["expected"]), tuple(children), text(args["reason"]))
        return Response(codec.encode(as_data(receipt)), status=HTTPStatus.OK, mimetype="application/cbor")

    return blueprint
