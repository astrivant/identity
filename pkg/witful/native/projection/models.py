"""
Define closed projection policy and encrypted outbox contracts independently of workers and transports.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from attrs import frozen

from witful.exceptions import NativeError
from witful.native.authority import Access  # noqa: TC001 - encrypted intent schemas resolve nested access at runtime.
from witful.native.context import Context, identifier  # noqa: TC001 - permit schemas resolve their expected envelope context.
from witful.native.models import Pointer  # noqa: TC001 - persisted preparation schemas resolve nested pointers at runtime.

INTENT = 14
PREPARED = 15
BUNDLE = 16
RESULT = 17
PERMIT = 18


@frozen
class Target:
    """
    Select an independently operated projection gateway and an explicitly approved initial remote frontier.

    Attributes:
        id (str): Opaque destination UUID resolving to a gateway-owned remote/ref; requests cannot choose arbitrary remotes.
        tenant (str): Exact source tenant UUID.
        identity (str): Exact source identity UUID.
        url (str): Explicit HTTPS gateway origin.
        ca (str): Independently trusted gateway CA path.
        certificate (str): Controller-to-gateway client certificate path.
        key (str): Controller transport key path, never remote publication credentials.
        grant (str): Independently provisioned gateway-call grant for this controller certificate.
        task (str): Approved gateway-call task UUID.
        initial (str | None): Independently reviewed initial remote commit OID, or explicit create-if-absent.
    """

    id: str
    tenant: str
    identity: str
    url: str
    ca: str
    certificate: str
    key: str
    grant: str
    task: str
    initial: str | None = None

    def __attrs_post_init__(self) -> None:
        """
        Reject malformed identifiers, embedded credentials and unsupported destination origins before admission.

        Returns:
            None: The target is structurally valid; current grant and gateway destination policy remain independent checks.
        """
        for value in (self.id, self.tenant, self.identity, self.grant, self.task):
            identifier(value)
        try:
            endpoint = urlsplit(self.url)
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username is not None
                or endpoint.password is not None
                or endpoint.query
                or endpoint.fragment
                or endpoint.path not in ("", "/")
                or endpoint.port == 0
                or not self.url.isascii()
                or any(ord(char) < 33 or ord(char) == 127 for char in self.url)
            ):
                raise NativeError("invalid")
        except ValueError:
            raise NativeError("invalid") from None
        if self.initial is not None and (len(self.initial) != 40 or any(char not in "0123456789abcdef" for char in self.initial)):
            raise NativeError("invalid")


@frozen
class Policy:
    """
    Configure scheduling separately from the actual remote durability requirement and refusal budgets.

    Attributes:
        mode (Literal["disabled", "manual", "interval", "batch", "required"]): Explicit delivery and completion policy.
        targets (tuple[Target, ...]): Reviewed identity-bound gateway destinations; no remote exists implicitly.
        author (str): Honest component attribution for newly generated export commits.
        email (str): Operator-reviewed exporter contact.
        interval_seconds (int): Minimum scheduled scan interval; a timer is not a durability guarantee.
        batch_size (int): Pending intent threshold for batch scheduling.
        max_entries (int): Maximum pending outbox items before refusing further affected writes.
        max_bytes (int): Maximum pending ciphertext bytes before refusing further affected writes.
        max_lag_seconds (int): Maximum age of the oldest unverified intent before refusing further affected writes.
        attempts (int): Bounded delivery attempts per explicit drain.
        retry_seconds (int): Initial interruptible retry delay.
        retry_max_seconds (int): Maximum exponential delay.
    """

    mode: Literal["disabled", "manual", "interval", "batch", "required"] = "disabled"
    targets: tuple[Target, ...] = ()
    author: str = "Witful projection service"
    email: str = "projection@example.invalid"
    interval_seconds: int = 60
    batch_size: int = 8
    max_entries: int = 64
    max_bytes: int = 64 * 1024 * 1024
    max_lag_seconds: int = 3600
    attempts: int = 5
    retry_seconds: int = 1
    retry_max_seconds: int = 60

    def __attrs_post_init__(self) -> None:
        """
        Require positive bounded configuration values and unique target identities without arbitrary operator ceilings.

        Returns:
            None: Scheduling and resource controls are coherent.
        """
        if any(
            type(value) is not int or value < 1
            for value in (
                self.interval_seconds,
                self.batch_size,
                self.max_entries,
                self.max_bytes,
                self.max_lag_seconds,
                self.attempts,
                self.retry_seconds,
                self.retry_max_seconds,
            )
        ):
            raise NativeError("invalid")
        if self.mode not in {"disabled", "manual", "interval", "batch", "required"} or self.retry_seconds > self.retry_max_seconds:
            raise NativeError("invalid")
        if len({target.id for target in self.targets}) != len(self.targets):
            raise NativeError("invalid")
        if self.mode != "disabled" and not self.targets:
            raise NativeError("invalid")

    def select(self, tenant: str, identity: str) -> tuple[Target, ...]:
        """
        Select only explicitly configured targets for this exact source scope.

        Args:
            tenant (str): Admitted opaque source tenant.
            identity (str): Admitted opaque source identity.

        Returns:
            tuple[Target, ...]: Enabled targets, empty only when disabled or this scope has no configured projection policy.
        """
        if self.mode == "disabled":
            return ()
        return tuple(target for target in self.targets if (target.tenant, target.identity) == (tenant, identity))


@frozen
class Intent:
    """
    Retain accepted projection work atomically with its source write while keeping names and authorization bindings encrypted.

    Attributes:
        operation (str): Accepted native operation UUID whose receipt selects the exact covered frontier.
        backend (str): Registered source backend at acceptance.
        access (Access): Original admitted writer scope, subject, grant, task, epoch and policy.
        target (Target): Exact reviewed destination configuration at acceptance.
        generation (int): Source commit watermark covered by this intent.
        recorded (int): Actual acceptance time in UTC epoch seconds.
        required (bool): Retained requirement for remote verification before workload completion, independent of later policy changes.
        version (Literal[1]): Closed intent schema version.
    """

    operation: str
    backend: str
    access: Access
    target: Target
    generation: int
    recorded: int
    required: bool = False
    version: Literal[1] = 1

    def __attrs_post_init__(self) -> None:
        """
        Require coherent source, target and accepted frontier bindings before admitting retained work.

        Returns:
            None: The opaque intent is structurally coherent; current permissions remain independently checked.
        """
        identifier(self.operation)
        identifier(self.backend)
        if (
            self.generation < 1
            or self.recorded < 0
            or (self.target.tenant, self.target.identity) != (self.access.scope.tenant, self.access.scope.identity)
        ):
            raise NativeError("invalid")


@frozen
class Prepared:
    """
    Bind exact immutable delivery bytes and honest Git metadata before any remote request.

    Attributes:
        intent (Intent): Original accepted work and current-permission bindings.
        bundle (Pointer): Signed encrypted exact blob/tree/commit bytes.
        permit (Pointer): Signed encrypted gateway permit containing no domain plaintext.
        expected (str | None): Exact remote parent or create-if-absent boundary.
        oid (str): Exact prepared Git commit OID.
        tree (str): Exact tree OID.
        blob (str): Exact encrypted sidecar blob OID.
        author (str): Honest configured projection author.
        email (str): Explicit projection contact.
        recorded (int): Actual export commit time, fixed for every retry.
        attempts (int): Persisted observed delivery attempts.
        next_attempt (int): Earliest allowed retry in UTC epoch seconds.
        state (Literal["projection_pending", "unknown", "blocked", "diverged"]): Independent delivery state, never local durability.
        version (Literal[1]): Closed preparation schema version.
    """

    intent: Intent
    bundle: Pointer
    permit: Pointer
    expected: str | None
    oid: str
    tree: str
    blob: str
    author: str
    email: str
    recorded: int
    attempts: int = 0
    next_attempt: int = 0
    state: Literal["projection_pending", "unknown", "blocked", "diverged"] = "projection_pending"
    version: Literal[1] = 1


@frozen
class Permit:
    """
    Bind the approved source and exact delivery bytes inside a separately decryptable, signed gateway envelope.

    Attributes:
        intent (Intent): Original accepted scope, current grant and opaque destination.
        context (Context): Independently expected encrypted archive context; the gateway only verifies its signature.
        expected (str | None): Exact remote compare-and-set boundary.
        digest (str): SHA-256 of the complete exact bundle, never a plaintext content fingerprint.
        oid (str): Exact prepared Git commit OID.
        author (str): Explicit new exporter identity.
        email (str): Explicit exporter contact.
        recorded (int): Fixed actual preparation timestamp.
        version (Literal[1]): Closed permit contract.
    """

    intent: Intent
    context: Context
    expected: str | None
    digest: str
    oid: str
    author: str
    email: str
    recorded: int
    version: Literal[1] = 1


@frozen
class Result:
    """
    Retain independent remote verification without conflating it with the original durable receipt.

    Attributes:
        prepared (Pointer): Exact authenticated candidate and original intent.
        oid (str): Independently read-back commit.
        recorded (int): Actual successful verification time.
        version (Literal[1]): Closed result contract.
    """

    prepared: Pointer
    oid: str
    recorded: int
    version: Literal[1] = 1
