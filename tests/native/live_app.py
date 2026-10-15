"""
Build a synthetic native application for real Gunicorn transport tests, without claiming production storage attestation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from witful.native.api.admission import Admission
from witful.native.api.builder import Builder
from witful.native.authority import Authority
from witful.native.envelope import EnvelopeService, Signer
from witful.native.git import Git
from witful.native.postgres import Postgres
from witful.native.service import Service
from witful.native.wire import mapping, text

from tests.native.conftest import Keys

if TYPE_CHECKING:
    from flask import Flask
    from witful.native.storage import Store


def create_app() -> Flask:
    """
    Compose actual persistence and authentication boundaries with process-local synthetic custody and an explicit protection stand-in.

    Returns:
        Flask: Test-only application with no production credentials or implicit deployment registration.
    """
    settings = mapping(json.loads(Path(os.environ["WITFUL_TEST_NATIVE_FACTORY"]).read_text()), {"kind", "data", "authority", "backend"})
    store: Store
    if settings["kind"] == "git":
        store = Git(Path(text(settings["data"])), "Synthetic", "fixture@example.invalid")
    else:
        store = Postgres(text(settings["data"]))
    wrapping, signing = str(uuid4()), str(uuid4())
    keys = Keys({wrapping: rsa.generate_private_key(public_exponent=65537, key_size=3072)}, {signing: ed25519.Ed25519PrivateKey.generate()})
    public = keys.signing[signing].public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    envelope = EnvelopeService(keys, wrapping, signing, {signing: Signer(public, hashlib.sha256(public).hexdigest())})
    service = Service(store, Authority(text(settings["authority"]), text(settings["backend"])), lambda _: envelope, lambda: None)
    admission = Admission(2)
    app = Builder(service, admission, lambda: True).build()
    app.extensions["witful.runtime"] = admission
    return app
