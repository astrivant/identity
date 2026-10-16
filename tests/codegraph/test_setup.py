"""
Exercise operator custody setup against synthetic CLI responses and real cryptographic key validation.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from witful.cli import build_parser
from witful.codegraph.setup import cli, custody
from witful.codegraph.setup.onepassword import OnePassword, fields, mapping, text
from witful.exceptions import SetupError

if TYPE_CHECKING:
    from pathlib import Path

VAULT = "v" * 26
TOKEN = "synthetic-token-never-log"


class Provider:
    """
    Model CLI operations with retained remote items and independently observable mutation attempts.
    """

    def __init__(self) -> None:
        """
        Start with an empty synthetic account and no private filesystem state.
        """
        self.items: list[dict[str, object]] = []
        self.vaults: list[dict[str, object]] = []
        self.calls: list[list[str]] = []
        self.fail_token_save = False
        self.accounts = 0

    def run(self, arguments: list[str], payload: str | None = None) -> str:
        """
        Execute the minimal provider contract without any real account or network access.

        Args:
            arguments (list[str]): Captured non-secret arguments.
            payload (str | None): Optional secret JSON payload.

        Returns:
            str: Synthetic provider response.

        Raises:
            SetupError: The injected token-storage failure occurs.
        """
        self.calls.append(arguments)
        assert all(TOKEN not in entry for entry in arguments)
        if arguments[:2] == ["vault", "list"]:
            return json.dumps(self.vaults)
        if arguments[:2] == ["vault", "create"]:
            entry: dict[str, object] = {"id": VAULT, "name": arguments[2]}
            self.vaults.append(entry)
            return json.dumps(entry)
        if arguments[:2] == ["item", "list"]:
            return json.dumps(self.items)
        if arguments[:2] == ["item", "get"]:
            return json.dumps(next(item for item in self.items if item["id"] == arguments[2]))
        if arguments[:2] == ["item", "create"]:
            assert payload is not None
            item: dict[str, object] = json.loads(payload)
            if self.fail_token_save and TOKEN in payload:
                raise SetupError("Injected save failure")
            item["id"] = str(len(self.items) + 1).zfill(26)
            self.items.append(item)
            return json.dumps(item)
        assert arguments[:2] == ["service-account", "create"]
        assert arguments[arguments.index("--vault") + 1] == VAULT + ":read_items"
        assert arguments[arguments.index("--expires-in") + 1] == "30d"
        self.accounts += 1
        return TOKEN


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> Provider:
    """
    Inject synthetic CLI traffic while preserving the actual provisioning and validation logic.

    Args:
        monkeypatch (pytest.MonkeyPatch): Scoped method replacement.

    Returns:
        Provider: In-memory remote state and call observations.
    """
    result = Provider()

    def run(self: OnePassword, arguments: list[str], payload: str | None = None) -> str:
        """
        Forward one operator call to the synthetic account.

        Args:
            self (OnePassword): Selected account wrapper.
            arguments (list[str]): Non-secret command arguments.
            payload (str | None): Private JSON input.

        Returns:
            str: Synthetic response.
        """
        assert self.account == "fixture"
        return result.run(arguments, payload)

    monkeypatch.setattr(OnePassword, "run", run)
    original = rsa.generate_private_key

    def generate(public_exponent: int, key_size: int) -> rsa.RSAPrivateKey:
        """
        Assert the production size choice while using a faster valid key in repeated synthetic tests.

        Args:
            public_exponent (int): Requested public exponent.
            key_size (int): Requested production wrapping size.

        Returns:
            rsa.RSAPrivateKey: Real broker-compatible test key.
        """
        assert key_size == 8192
        return original(public_exponent=public_exponent, key_size=3072)

    monkeypatch.setattr(rsa, "generate_private_key", generate)
    return result


def test_setup_reuses_keys_and_never_saves_secrets(provider: Provider, tmp_path: Path) -> None:
    """
    Verify first setup, read-only retry, least-privilege account scope and non-secret local receipts.

    Args:
        provider (Provider): Synthetic account.
        tmp_path (Path): Private setup directory.

    Returns:
        None: Retried provisioning performs no additional mutations or key rotation.
    """
    client = OnePassword("fixture", "op")
    result = custody.provision(client, tmp_path, "fixture vault", True)
    initial = len(provider.calls)
    assert custody.provision(client, tmp_path, VAULT, False) == result
    assert provider.accounts == 1
    assert not any("create" in call for call in provider.calls[initial:])
    for path in tmp_path.iterdir():
        assert path.stat().st_mode & 0o077 == 0
        saved = path.read_text()
        assert TOKEN not in saved
        for item in provider.items:
            assert fields(item)["credential"] not in saved
    assert result["vault"] == VAULT


def test_uncertain_token_save_blocks_duplicate_accounts(provider: Provider, tmp_path: Path) -> None:
    """
    Preserve a recovery marker when a one-time token cannot be durably stored remotely.

    Args:
        provider (Provider): Synthetic account with injected item-save failure.
        tmp_path (Path): Private durable receipt directory.

    Returns:
        None: A retry fails before another service account can be created.
    """
    provider.fail_token_save = True
    client = OnePassword("fixture", "op")
    with pytest.raises(SetupError, match="Injected"):
        custody.provision(client, tmp_path, "fixture vault", True)
    assert (tmp_path / "service-account.pending").stat().st_mode & 0o077 == 0
    provider.fail_token_save = False
    with pytest.raises(SetupError, match="unsettled"):
        custody.provision(client, tmp_path, VAULT, True)
    assert provider.accounts == 1


def test_changed_remote_key_requires_rotation_review(provider: Provider, tmp_path: Path) -> None:
    """
    Reject a changed public pin even when the remote generation field was left unchanged.

    Args:
        provider (Provider): Synthetic account with existing custody.
        tmp_path (Path): Original setup receipt directory.

    Returns:
        None: Trusted metadata is preserved and no account mutation occurs.
    """
    client = OnePassword("fixture", "op")
    custody.provision(client, tmp_path, "fixture vault", True)
    key = ed25519.Ed25519PrivateKey.generate()
    payload = base64.b64encode(
        key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    ).decode()
    provider.items[1]["fields"] = [
        {"id": "credential", "value": payload},
        {"id": "generation", "value": fields(provider.items[1])["generation"]},
        {"id": "kind", "value": "signing"},
    ]
    with pytest.raises(SetupError, match="bindings changed"):
        custody.provision(client, tmp_path, VAULT, True)
    assert provider.accounts == 1


def test_explicit_references_and_disabled_provisioning(provider: Provider, tmp_path: Path) -> None:
    """
    Resolve supplied key locations without creating missing vaults or widening their scope.

    Args:
        provider (Provider): Synthetic account.
        tmp_path (Path): Setup directory.

    Returns:
        None: Missing references and cross-vault selection fail closed.
    """
    client = OnePassword("fixture", "op")
    with pytest.raises(SetupError, match="provisioning is disabled"):
        custody.provision(client, tmp_path, "missing", False)
    assert not provider.items and not provider.accounts
    result = custody.provision(client, tmp_path, "fixture vault", True)
    keys = mapping(result["keys"])
    wrapping = text(mapping(keys["wrapping"])["reference"])
    signing = text(mapping(keys["signing"])["reference"])
    assert custody.provision(client, tmp_path, VAULT, False, wrapping, signing, text(result["service_account_reference"])) == result
    with pytest.raises(SetupError, match="selected vault"):
        client.existing(wrapping.replace(VAULT, "x" * 26), VAULT)
    provider.items.append(dict(provider.items[0]))
    with pytest.raises(SetupError, match="Duplicate custody"):
        client.find(VAULT, "Witful CodeGraph wrapping")


def test_invalid_key_and_reference_never_echo_secret() -> None:
    """
    Reject malformed private material through a fixed diagnostic.

    Returns:
        None: The invalid credential does not appear in the exception.
    """
    item: dict[str, object] = {
        "id": "i" * 26,
        "fields": [
            {"id": "credential", "value": TOKEN},
            {"id": "kind", "value": "wrapping"},
            {"id": "generation", "value": str(uuid4())},
        ],
    }
    with pytest.raises(SetupError) as caught:
        custody.inspect(item, VAULT, "wrapping")
    assert TOKEN not in str(caught.value)


def test_cli_capture_withholds_provider_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify real subprocess construction sends credentials only through stdin and suppresses failure payloads.

    Args:
        monkeypatch (pytest.MonkeyPatch): Scoped process and environment substitution.

    Returns:
        None: Provider failures reveal neither captured streams nor token environment overrides.
    """
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", TOKEN)

    def run(
        arguments: list[str], *, input: str | None, text: bool, capture_output: bool, check: bool, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        """
        Inspect the actual process boundary and return a secret-bearing failure.

        Args:
            arguments (list[str]): Executable and non-secret argv.
            input (str | None): Pipe payload.
            text (bool): Text-mode capture selection.
            capture_output (bool): Whether stdout and stderr are captured.
            check (bool): Whether subprocess may create an exception with raw output.
            env (dict[str, str]): Child environment.

        Returns:
            subprocess.CompletedProcess[str]: Deliberate failure containing a synthetic secret.
        """
        assert TOKEN not in str(arguments) and input == TOKEN
        assert text and capture_output and not check
        assert "OP_SERVICE_ACCOUNT_TOKEN" not in env and env["OP_DEBUG"] == "false"
        return subprocess.CompletedProcess(arguments, 1, TOKEN, TOKEN)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SetupError) as caught:
        OnePassword("fixture", "/installed/op").run(["item", "create", "-"], TOKEN)
    assert TOKEN not in str(caught.value)


def test_setup_parser_defaults_and_private_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Preserve optional default-on provisioning and reject setup writes inside a repository.

    Args:
        monkeypatch (pytest.MonkeyPatch): Synthetic protected-volume verifier.
        tmp_path (Path): Disposable filesystem fixture.

    Returns:
        None: Parser choices remain inert and storage boundaries are checked before provisioning.
    """
    parser = build_parser()
    arguments = ["codegraph", "setup", "--account", "fixture", "--directory", str(tmp_path)]
    assert parser.parse_args(arguments).provision is True
    assert parser.parse_args([*arguments, "--no-provision"]).provision is False
    monkeypatch.setattr(cli, "require_protected", lambda path: None)
    private = tmp_path / "private"
    assert cli.prepare(private) == private
    assert private.stat().st_mode & 0o077 == 0
    subprocess.run(["git", "init", "--quiet", str(private)], check=True)
    with pytest.raises(SetupError, match="outside Git"):
        cli.prepare(private / "nested")
    link = tmp_path / "alias"
    link.symlink_to(private)
    with pytest.raises(SetupError, match="symlink"):
        cli.prepare(link)
    os.chmod(tmp_path, 0o755)
    with pytest.raises(SetupError, match="0700"):
        cli.prepare(tmp_path)
