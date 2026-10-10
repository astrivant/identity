"""
Verify repository-bound authenticated encryption and strict archive extraction with synthetic inputs.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from witful.collection.archive import pack, unpack
from witful.collection.crypto import decrypt, encrypt, fingerprint
from witful.collection.models import Config
from witful.privacy.scanner import validate_envelope

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(scope="module")
def keypair() -> tuple[bytes, bytes, Config]:
    """
    Generate one ephemeral recipient for the module without invoking external services.

    Returns:
        tuple[bytes, bytes, Config]: Encrypted private PEM, public PEM, and trusted fixture configuration.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(b"fixture")
    )
    return private, public, Config("example/collection", fingerprint(public), "a" * 64)


def test_encryption_is_randomized_authenticated_and_context_bound(keypair: tuple[bytes, bytes, Config]) -> None:
    """
    Check recovery plus tamper, wrong-repository, wrong-purpose, and wrong-password rejection.

    Args:
        keypair (tuple[bytes, bytes, Config]): Ephemeral encryption fixture.

    Returns:
        None: Only the intended recipient and context recover the source bytes.
    """
    private, public, config = keypair
    message = b"private fixture, never stored in cleartext"
    sealed = encrypt(message, public, config, "sources")
    assert message not in sealed
    assert encrypt(message, public, config, "sources") != sealed
    assert decrypt(sealed, private, b"fixture", config, "sources") == message
    validate_envelope(sealed)

    for other, purpose, password in (
        (evolve(config, repository="other/collection"), "sources", b"fixture"),
        (config, "figures", b"fixture"),
        (config, "sources", b"wrong"),
    ):
        with pytest.raises(ValueError):
            decrypt(sealed, private, password, other, "sources" if purpose == "sources" else "figures")

    envelope = json.loads(sealed)
    altered = bytearray(base64.b64decode(envelope["ciphertext"]))
    altered[0] ^= 1
    envelope["ciphertext"] = base64.b64encode(altered).decode()

    with pytest.raises(InvalidTag):
        decrypt(json.dumps(envelope).encode(), private, b"fixture", config, "sources")


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "knowledge/../../escape", "auth.json", "config.toml", "knowledge/snapshots/bad.json"]
)
def test_archive_rejects_non_source_paths_before_writing(tmp_path: Path, name: str) -> None:
    """
    Reject path traversal and credentials even inside a decrypted, authenticated map.

    Args:
        tmp_path (Path): Isolated restore destination parent.
        name (str): Unsupported source path.

    Returns:
        None: Invalid payloads create no destination files or directories.
    """
    target = tmp_path / "restored"

    with pytest.raises(ValueError):
        unpack(json.dumps({name: "eA=="}).encode(), target)

    assert not target.exists()


def test_pack_omits_runtime_credentials_and_refuses_source_symlinks(tmp_path: Path) -> None:
    """
    Archive only named collection inputs and preserve new-directory restore semantics.

    Args:
        tmp_path (Path): Isolated source and restore trees.

    Returns:
        None: Credentials remain outside the archive and symlinks cannot redirect collection reads.
    """
    source = tmp_path / "source"
    source.mkdir()
    (source / "lessons.jsonl").write_text("fixture\n")
    (source / "auth.json").write_text("private credential fixture")
    (source / "config.toml").write_text("machine settings")
    data = pack(source)
    assert set(json.loads(data)) == {"lessons.jsonl"}
    output = tmp_path / "restored"
    unpack(data, output)
    assert (output / "lessons.jsonl").read_text() == "fixture\n"
    assert (output / "lessons.jsonl").stat().st_mode & 0o777 == 0o600

    with pytest.raises(ValueError):
        unpack(data, output)

    (source / "lessons.jsonl").unlink()
    (source / "lessons.jsonl").symlink_to(source / "auth.json")

    with pytest.raises(ValueError):
        pack(source)
