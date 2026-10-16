"""
Use the authenticated operator CLI for vault provisioning, with credential traffic confined to captured pipes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import TYPE_CHECKING

from attrs import frozen

from witful.exceptions import SetupError

if TYPE_CHECKING:
    from pathlib import Path


def mapping(value: object) -> dict[str, object]:
    """
    Decode a provider object without propagating its values in validation errors.

    Args:
        value (object): Decoded provider response.

    Returns:
        dict[str, object]: String-keyed response.

    Raises:
        SetupError: The response is not an object.
    """
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise SetupError("Unexpected 1Password response; values withheld.")
    return {key: item for key, item in value.items()}


def text(value: object) -> str:
    """
    Require a nonempty provider string without coercing malformed values.

    Args:
        value (object): Provider field.

    Returns:
        str: Nonempty value; callers own its secrecy.

    Raises:
        SetupError: The field is absent or malformed.
    """
    if not isinstance(value, str) or not value:
        raise SetupError("Missing or invalid 1Password field; values withheld.")
    return value


def identifier(value: object) -> str:
    """
    Accept only stable 1Password identifiers in persisted references.

    Args:
        value (object): Candidate vault or item identifier.

    Returns:
        str: Stable identifier safe to embed in an op reference.

    Raises:
        SetupError: The identifier has an unexpected format.
    """
    result = text(value)
    if re.fullmatch(r"[a-zA-Z0-9]{26}", result) is None:
        raise SetupError("Unexpected 1Password identifier; values withheld.")
    return result


def fields(item: dict[str, object]) -> dict[str, str]:
    """
    Extract unambiguous item fields while retaining secrets only in caller-owned memory.

    Args:
        item (dict[str, object]): Captured item response.

    Returns:
        dict[str, str]: Field IDs mapped to their string values.

    Raises:
        SetupError: Field structure or IDs are ambiguous.
    """
    raw = item.get("fields")
    if not isinstance(raw, list):
        raise SetupError("Missing 1Password item fields.")
    result: dict[str, str] = {}
    for entry in raw:
        field = mapping(entry)
        name = text(field.get("id"))
        if name in result:
            raise SetupError("Duplicate 1Password item fields require review.")
        value = field.get("value", "")
        if not isinstance(value, str):
            raise SetupError("Invalid 1Password item field; values withheld.")
        result[name] = value
    return result


@frozen
class OnePassword:
    """
    Bind setup to one explicit operator account and installed executable.

    Attributes:
        account (str): Operator-selected 1Password account, never inferred from repository content.
        executable (str): Resolved installed op binary.
    """

    account: str
    executable: str

    @classmethod
    def installed(cls, account: str) -> OnePassword:
        """
        Locate the operator's CLI without installing software or initiating login.

        Args:
            account (str): Explicit account selector.

        Returns:
            OnePassword: CLI bound to this account.

        Raises:
            SetupError: Account selection or the CLI is missing.
        """
        binary = shutil.which("op")
        if not account or not binary:
            raise SetupError("Install 1Password CLI and select --account; authenticate with op signin or the desktop app.")
        return cls(account, binary)

    def run(self, arguments: list[str], payload: str | None = None) -> str:
        """
        Capture a single operator command without logging its arguments, input or response.

        Args:
            arguments (list[str]): Non-secret command arguments.
            payload (str | None): Secret-bearing JSON sent through stdin only.

        Returns:
            str: Captured output; never forwarded automatically.

        Raises:
            SetupError: The command fails; raw diagnostics are withheld.
        """
        # Desktop authentication can wait for the operator. Cancellation remains available; no arbitrary login deadline applies.
        environment = dict(os.environ)
        environment.pop("OP_SERVICE_ACCOUNT_TOKEN", None)
        environment.pop("OP_CONNECT_TOKEN", None)
        environment.pop("OP_CONNECT_HOST", None)
        environment["OP_DEBUG"] = "false"
        try:
            result = subprocess.run(
                [self.executable, "--account", self.account, *arguments],
                input=payload,
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
        except OSError:
            raise SetupError("Cannot run 1Password CLI; check installation and desktop authentication.") from None
        if result.returncode:
            raise SetupError("1Password operation failed; check account access and authentication. Provider output withheld.")
        return result.stdout.strip()

    def objects(self, arguments: list[str]) -> list[dict[str, object]]:
        """
        Read a collection of vault or item metadata.

        Args:
            arguments (list[str]): Read-only list command.

        Returns:
            list[dict[str, object]]: Provider objects without automatic display.

        Raises:
            SetupError: The response is not a JSON array of objects.
        """
        try:
            value: object = json.loads(self.run([*arguments, "--format=json"]))
        except json.JSONDecodeError:
            raise SetupError("Malformed 1Password response; values withheld.") from None
        if not isinstance(value, list):
            raise SetupError("Unexpected 1Password list response.")
        return [mapping(entry) for entry in value]

    def response(self, arguments: list[str], payload: str | None = None) -> dict[str, object]:
        """
        Decode one provider response without reflecting malformed credential content.

        Args:
            arguments (list[str]): Operator command with non-secret arguments.
            payload (str | None): Optional item JSON delivered through stdin.

        Returns:
            dict[str, object]: Captured provider object.

        Raises:
            SetupError: JSON is malformed.
        """
        try:
            value: object = json.loads(self.run([*arguments, "--format=json"], payload))
        except json.JSONDecodeError:
            raise SetupError("Malformed 1Password response; values withheld.") from None
        return mapping(value)

    def vault(self, selector: str, provision: bool) -> str:
        """
        Reuse an unambiguous vault or explicitly provision the requested dedicated name.

        Args:
            selector (str): Vault name or stable ID, not a secret.
            provision (bool): Whether this setup invocation may create missing resources.

        Returns:
            str: Stable vault ID.

        Raises:
            SetupError: Selection is ambiguous or creation is disabled.
        """
        candidates = [entry for entry in self.objects(["vault", "list"]) if selector in (entry.get("id"), entry.get("name"))]
        if len(candidates) > 1:
            raise SetupError("Multiple vaults match; select an explicit vault ID.")
        if not candidates:
            if not provision:
                raise SetupError("Vault is missing and provisioning is disabled.")
            # Do not alter account-level sharing or existing vault permissions as a side effect of adoption.
            candidates = [self.response(["vault", "create", selector, "--description", "Dedicated Witful development key custody"])]
        return identifier(candidates[0].get("id"))

    def find(self, vault: str, title: str) -> dict[str, object] | None:
        """
        Reconcile existing items before any creation, refusing ambiguous duplicates.

        Args:
            vault (str): Stable selected vault ID.
            title (str): Fixed purpose label.

        Returns:
            dict[str, object] | None: Existing full item, or no matching item.

        Raises:
            SetupError: More than one item matches the purpose.
        """
        matches = [entry for entry in self.objects(["item", "list", "--vault", vault]) if entry.get("title") == title]
        if len(matches) > 1:
            raise SetupError("Duplicate custody items require operator review; nothing was overwritten.")
        if not matches:
            return None
        return self.response(["item", "get", identifier(matches[0].get("id")), "--vault", vault])

    def create(self, vault: str, title: str, values: dict[str, str]) -> dict[str, object]:
        """
        Store one new credential without writing secret templates to disk or argv.

        Args:
            vault (str): Stable selected vault ID.
            title (str): Fixed purpose label.
            values (dict[str, str]): Named fields; credential is concealed in the vault.

        Returns:
            dict[str, object]: Captured created item.
        """
        payload = {
            "title": title,
            "category": "API_CREDENTIAL",
            "fields": [
                {"id": key, "label": key, "type": "CONCEALED" if key == "credential" else "STRING", "value": value}
                for key, value in values.items()
            ],
        }
        return self.response(["item", "create", "-", "--vault", vault], json.dumps(payload))

    def existing(self, reference: str, vault: str) -> tuple[dict[str, object], str]:
        """
        Resolve a caller-supplied stable field reference within the selected custody vault.

        Args:
            reference (str): op://VAULT_ID/ITEM_ID/FIELD reference, not a secret value.
            vault (str): Explicit custody vault ID.

        Returns:
            tuple[dict[str, object], str]: Existing item and selected credential field.

        Raises:
            SetupError: Reference is malformed, crosses vault scope or names no field.
        """
        parts = reference.removeprefix("op://").split("/")
        if not reference.startswith("op://") or len(parts) != 3 or parts[0] != vault:
            raise SetupError("Use an op://VAULT_ID/ITEM_ID/FIELD reference in the selected vault.")
        item = self.response(["item", "get", identifier(parts[1]), "--vault", vault])
        if not parts[2] or parts[2] not in fields(item):
            raise SetupError("The selected credential field does not exist.")
        return item, parts[2]

    def token(self, vault: str, pending: Path, provision: bool, reference: str | None) -> str:
        """
        Reuse or create a read-only expiring service account, fencing uncertain one-time token delivery.

        Args:
            vault (str): Only vault granted to a newly created service account.
            pending (Path): Private marker retained across uncertain account creation.
            provision (bool): Whether a missing account may be provisioned.
            reference (str | None): Existing caller-selected service-account field.

        Returns:
            str: Stable reference to the token, never its value.

        Raises:
            SetupError: Reconciliation is required, provisioning is disabled, or a token is missing.
        """
        title = "Witful CodeGraph broker service account"
        item = None
        field = "credential"
        if reference is not None:
            item, field = self.existing(reference, vault)
        else:
            item = self.find(vault, title)
        if item is None:
            if pending.exists():
                raise SetupError(
                    "Service-account creation is unsettled. Recover its token or revoke the orphan in 1Password before retrying."
                )
            if not provision:
                raise SetupError("Service-account token is missing and provisioning is disabled.")
            # Persist intent before a non-idempotent call. A crash must never silently create another untracked credential.
            descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as marker:
                marker.write("Reconcile Witful CodeGraph service-account creation in the selected vault before removing this marker.\n")
                marker.flush()
                os.fsync(marker.fileno())
            token = self.run(
                [
                    "service-account",
                    "create",
                    "witful-codegraph-development",
                    "--vault",
                    vault + ":read_items",
                    "--expires-in",
                    "30d",
                    "--raw",
                ]
            )
            if not token:
                raise SetupError("1Password returned no token; reconcile the pending service account before retrying.")
            item = self.create(vault, title, {"credential": token})
        text(fields(item).get(field))
        pending.unlink(missing_ok=True)
        return f"op://{vault}/{identifier(item.get('id'))}/{field}"
