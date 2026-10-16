"""
Preserve exact original Git objects and declared repository metadata inside individually encrypted native archive records.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from attrs import evolve, field, frozen

from witful.collection.protection import require_protected
from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.context import identifier
from witful.native.git import git
from witful.native.models import Pointer, parse
from witful.native.wire import binary

if TYPE_CHECKING:
    from witful.native.authority import Access
    from witful.native.models import Receipt
    from witful.native.service import Service
    from witful.native.storage import Object
    from witful.native.views import View

__all__ = ["Repository", "capture", "restore"]

GIT_BYTES = 9
GIT_ARCHIVE = 10
CHUNK_BYTES = 1024 * 1024


@frozen
class Payload:
    """
    Bind bounded encrypted chunks to exact reconstructed source bytes.

    Attributes:
        size (int): Complete original byte length.
        digest (str): SHA-256 of original bytes, retained only inside the encrypted inventory.
        chunks (tuple[Pointer, ...]): Ordered independently authenticated byte chunks.
    """

    size: int
    digest: str
    chunks: tuple[Pointer, ...]


@frozen
class GitObject:
    """
    Retain the original Git identity rather than substituting a native logical revision.

    Attributes:
        oid (str): Original Git object ID under the declared algorithm.
        data (Payload): Exact canonical type/length header, NUL separator and content, including original signatures.
    """

    oid: str
    data: Payload


@frozen
class GitFile:
    """
    Inventory original repository metadata and non-Git assets separately from canonical Git objects.

    Attributes:
        path (str): Relative original path inside the explicitly selected Git directory.
        mode (int): Original permission bits, recorded without granting those permissions on restore.
        data (Payload): Exact bytes, including config, hooks, available LFS files and approved ancillary records.
    """

    path: str
    mode: int
    data: Payload


@frozen
class Repository:
    """
    State exactly what an original-Git preservation profile retains and omits.

    Attributes:
        algorithm (Literal["sha1", "sha256"]): Git's declared object identity algorithm, independent of envelope authentication.
        objects (tuple[GitObject, ...]): Canonical original objects with verified OIDs.
        files (tuple[GitFile, ...]): Original repository-directory metadata, excluding reconstructed object storage.
        unreachable (bool): Whether all locally available unreachable objects are expressly retained.
        reflogs (bool): Whether locally available reflog files are expressly retained.
        exclusions (tuple[str, ...]): Explicit scope limits; absent provider-hidden/pruned data is never claimed retained.
        recorded (int): Actual capture time, not an invented historical author timestamp.
        version (Literal[1]): Closed inventory schema version.
    """

    algorithm: Literal["sha1", "sha256"]
    objects: tuple[GitObject, ...]
    files: tuple[GitFile, ...]
    unreachable: bool
    reflogs: bool
    exclusions: tuple[str, ...]
    recorded: int
    version: Literal[1] = 1


@frozen
class Source:
    """
    Hold bounded source observations only inside protected process memory.

    Attributes:
        algorithm (Literal["sha1", "sha256"]): Observed Git hash format.
        objects (tuple[tuple[str, bytes], ...]): Exact selected original canonical objects.
        files (tuple[tuple[str, int, bytes], ...]): Exact selected metadata bytes and modes.
        all_objects (tuple[str, ...]): Full available object inventory for change detection.
    """

    algorithm: Literal["sha1", "sha256"]
    objects: tuple[tuple[str, bytes], ...] = field(repr=False)
    files: tuple[tuple[str, int, bytes], ...] = field(repr=False)
    all_objects: tuple[str, ...]


def plumbing(directory: Path, arguments: tuple[str, ...], limit: int, data: bytes | None = None) -> bytes:
    """
    Read local original Git data without lazy fetching, replacement refs, hooks or caller-selected shell commands.

    Args:
        directory (Path): Explicit existing Git directory.
        arguments (tuple[str, ...]): Package-owned Git plumbing.
        limit (int): Bounded input/output size.
        data (bytes | None): Exact stdin for object restoration.

    Returns:
        bytes: Local plumbing output with fixed redacted errors.
    """
    return git(
        directory,
        ("--git-dir=.", "--no-replace-objects", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *arguments),
        data=data,
        limit=limit,
        environment={"GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
    )


def canonical(data: bytes, algorithm: str) -> str:
    """
    Validate canonical Git framing and recompute its original OID without treating SHA-1 as the encryption authenticator.

    Args:
        data (bytes): Exact type/length header, NUL and payload.
        algorithm (str): Declared Git object identity format.

    Returns:
        str: Verified-format Git object ID.
    """
    header, separator, payload = data.partition(b"\0")
    kind, space, size = header.partition(b" ")
    if algorithm not in {"sha1", "sha256"} or not separator or space != b" " or kind not in {b"blob", b"tree", b"commit", b"tag"}:
        raise NativeError("invalid")
    if size != str(len(payload)).encode("ascii"):
        raise NativeError("invalid")
    return hashlib.new(algorithm, data, usedforsecurity=False).hexdigest()


def read_file(directory: Path, name: str, maximum: int) -> tuple[int, bytes]:
    """
    Read an inventory path through no-follow directory descriptors without blocking on special files.

    Args:
        directory (Path): Explicit protected repository root.
        name (str): Relative path discovered by inventory.
        maximum (int): Remaining byte budget.

    Returns:
        tuple[int, bytes]: Observed original permission bits and bounded regular-file bytes.
    """
    parts = Path(name).parts
    if not parts or Path(name).is_absolute() or any(part in {".", ".."} for part in parts):
        raise NativeError("invalid")
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(file_descriptor, "rb") as source:
            observed = os.fstat(source.fileno())
            if not stat.S_ISREG(observed.st_mode):
                raise NativeError("unsupported")
            return observed.st_mode & 0o777, source.read(maximum + 1)
    finally:
        os.close(descriptor)


def files(directory: Path, reflogs: bool, maximum: int, count: int) -> tuple[tuple[str, int, bytes], ...]:
    """
    Inventory one explicit local Git directory without following symlinks or silently importing external storage.

    Args:
        directory (Path): Protected original Git directory.
        reflogs (bool): Whether the caller explicitly retains reflogs.
        maximum (int): Remaining metadata byte budget.
        count (int): Maximum metadata files.

    Returns:
        tuple[tuple[str, int, bytes], ...]: Sorted exact relative paths, original permissions and file bytes.
    """
    result: list[tuple[str, int, bytes]] = []
    used = 0
    for parent, folders, names in os.walk(directory, followlinks=False):
        root = Path(parent)
        # Alternate object databases and linked worktrees require a separately inventoried source, not following an external path.
        for name in (*folders, *names):
            path = root / name
            if path.is_symlink():
                raise NativeError("unsupported")
        if root == directory:
            folders[:] = [name for name in folders if name != "objects" and (reflogs or name != "logs")]
        for name in sorted(names):
            path = root / name
            relative = path.relative_to(directory).as_posix()
            if name.endswith(".lock") or relative in {"commondir", "gitdir", "shallow", "info/grafts"}:
                raise NativeError("unsupported")
            mode, payload = read_file(directory, relative, maximum - used)
            used += len(payload)
            if used > maximum or len(result) >= count:
                raise NativeError("incomplete")
            result.append((relative, mode, payload))
    return tuple(sorted(result))


def observe(directory: Path, unreachable: bool, reflogs: bool, maximum: int, count: int) -> Source:
    """
    Verify connectivity and record canonical object bytes plus explicit available ancillary state.

    Args:
        directory (Path): Protected original Git directory, not a whole arbitrary filesystem tree.
        unreachable (bool): Explicit retention of locally available unreachable objects.
        reflogs (bool): Explicit retention of locally available reflogs; requires unreachable retention.
        maximum (int): Aggregate source byte budget.
        count (int): Maximum object or metadata-file count.

    Returns:
        Source: Verified bounded observation; concurrent changes are checked again before native publication.
    """
    if directory.is_symlink():
        raise NativeError("unsupported")
    if reflogs and not unreachable:
        raise NativeError("invalid")
    if not (directory / "HEAD").is_file() or not (directory / "objects").is_dir():
        raise NativeError("invalid")
    if (directory / "objects/info/alternates").exists() or tuple((directory / "objects/pack").glob("*.promisor")):
        raise NativeError("unsupported")
    # Reject external filesystem links before any Git plumbing could resolve them.
    for parent, folders, names in os.walk(directory, followlinks=False):
        if any((Path(parent) / name).is_symlink() for name in (*folders, *names)):
            raise NativeError("unsupported")
    plumbing(directory, ("fsck", "--full", "--no-reflogs"), maximum)
    declared = plumbing(directory, ("rev-parse", "--show-object-format"), 128).strip()
    algorithm: Literal["sha1", "sha256"]
    if declared == b"sha1":
        algorithm = "sha1"
    elif declared == b"sha256":
        algorithm = "sha256"
    else:
        raise NativeError("unsupported")
    raw = plumbing(directory, ("cat-file", "--batch-all-objects", "--batch"), maximum)
    selected = set(plumbing(directory, ("rev-list", "--objects", "--all", "--no-object-names"), maximum).splitlines())
    objects: list[tuple[str, bytes]] = []
    available: list[str] = []
    offset = 0
    total = 0
    while offset < len(raw):
        end = raw.find(b"\n", offset)
        if end < 0:
            raise NativeError("invalid")
        fields = raw[offset:end].split(b" ")
        if len(fields) != 3:
            raise NativeError("invalid")
        oid, kind, length = fields
        try:
            size = int(length)
            object_id = oid.decode("ascii")
        except (ValueError, UnicodeError):
            raise NativeError("invalid") from None
        if size < 0 or size > maximum or raw[end + size + 1 : end + size + 2] != b"\n":
            raise NativeError("invalid")
        content = kind + b" " + length + b"\0" + raw[end + 1 : end + size + 1]
        if canonical(content, algorithm) != object_id or len(available) >= count:
            raise NativeError("invalid")
        available.append(object_id)
        if unreachable or oid in selected:
            objects.append((object_id, content))
            total += len(content)
        offset = end + size + 2
    if total > maximum or not selected <= {value.encode("ascii") for value in available}:
        raise NativeError("incomplete")
    metadata = files(directory, reflogs, maximum - total, count)
    return Source(algorithm, tuple(sorted(objects)), metadata, tuple(sorted(available)))


def capture(service: Service, access: Access, operation: str, directory: Path, unreachable: bool, reflogs: bool) -> Receipt:
    """
    Retain an explicitly selected protected original repository without replacing its historical commits or native journal authority.

    Args:
        service (Service): Authenticated native destination.
        access (Access): Current whole-identity write and import grant.
        operation (str): Stable import operation UUID.
        directory (Path): Explicit protected Git metadata directory; working-tree files and external stores are outside this scope.
        unreachable (bool): Explicitly retain all locally available unreachable objects.
        reflogs (bool): Explicitly retain locally available reflogs.

    Returns:
        Receipt: Durable encrypted inventory and original objects; no source file is removed or remote effect performed.
    """
    identifier(operation)
    require_protected(directory)
    started = service.monotonic()
    service.protection()
    admitted = service.authority.check(access, "import", "*", int(service.clock()))
    registration, frontier = service.snapshot(access, "write", "*")
    if admitted != registration:
        raise NativeError("conflict")
    try:
        source = observe(directory, unreachable, reflogs, service.budget.bytes, service.budget.revisions)
        request = hashlib.sha256(
            codec.encode(
                [
                    "witful-original-git-v1",
                    source.algorithm,
                    unreachable,
                    reflogs,
                    [[oid, hashlib.sha256(data).hexdigest()] for oid, data in source.objects],
                    [[name, mode, hashlib.sha256(data).hexdigest()] for name, mode, data in source.files],
                ],
                codec.Limits(bytes=service.budget.bytes),
            )
        ).hexdigest()
        prior = service.previous(access, operation, request)
        if prior is not None:
            service.release(access, "import", "*", registration, started)
            return prior
        sealed_objects: list[Object] = []

        def retain(data: bytes) -> Payload:
            """
            Encrypt bounded chunks before adding exact original bytes to native persistence.

            Args:
                data (bytes): Protected original canonical object or ancillary file.

            Returns:
                Payload: Authenticated reconstruction inventory with no plaintext on the data backend.
            """
            pointers: list[Pointer] = []
            for offset in range(0, len(data), CHUNK_BYTES):
                if service.monotonic() - started > service.budget.seconds:
                    raise NativeError("incomplete")
                pointer, sealed = service.seal(access, str(uuid4()), GIT_BYTES, data[offset : offset + CHUNK_BYTES])
                pointers.append(pointer)
                sealed_objects.append(sealed)
            return Payload(len(data), hashlib.sha256(data).hexdigest(), tuple(pointers))

        repository = Repository(
            source.algorithm,
            tuple(GitObject(oid, retain(data)) for oid, data in source.objects),
            tuple(GitFile(name, mode, retain(data)) for name, mode, data in source.files),
            unreachable,
            reflogs,
            (
                "working-tree files",
                "provider-hidden or previously pruned objects",
                "external submodule/LFS stores",
                "original loose-object compression and pack layout",
            ),
            int(service.clock()),
        )
        pointer, sealed = service.seal(access, str(uuid4()), GIT_ARCHIVE, as_data(repository))
        sealed_objects.append(sealed)
        if observe(directory, unreachable, reflogs, service.budget.bytes, service.budget.revisions) != source:
            raise NativeError("conflict")
        service.release(access, "import", "*", registration, started)
        return service.commit(
            access,
            operation,
            request,
            registration,
            evolve(frontier, archives=(*frontier.archives, pointer)),
            tuple(sealed_objects),
            started,
            permission="import",
        )
    except OSError:
        raise NativeError("unavailable") from None


def materialize(service: Service, access: Access, payload: Payload) -> bytes:
    """
    Reconstruct authenticated original bytes with explicit aggregate bounds.

    Args:
        service (Service): Current trusted key and persistence boundaries.
        access (Access): Admitted whole-identity export grant.
        payload (Payload): Authenticated inventory item.

    Returns:
        bytes: Complete verified original representation.
    """
    return materialize_view(service.view(access), payload)


def materialize_view(view: View, payload: Payload) -> bytes:
    """
    Reconstruct original chunks through the same bounded reader online or from an offline signed export.

    Args:
        view (View): Explicit authenticated ciphertext reader.
        payload (Payload): Original byte length, digest and ordered chunk pointers.

    Returns:
        bytes: Exact verified original bytes.
    """
    if payload.size < 0 or payload.size > view.budget.bytes or len(payload.chunks) > view.budget.revisions:
        raise NativeError("incomplete")
    data = bytearray()
    for pointer in payload.chunks:
        if pointer.kind != GIT_BYTES:
            raise NativeError("invalid")
        data.extend(binary(view.open(pointer)))
        if len(data) > payload.size:
            raise NativeError("invalid")
    result = bytes(data)
    if len(result) != payload.size or hashlib.sha256(result).hexdigest() != payload.digest:
        raise NativeError("invalid")
    return result


def validate(
    service: Service, access: Access, repository: Repository
) -> tuple[tuple[tuple[str, bytes], ...], tuple[tuple[str, int, bytes], ...]]:
    """
    Verify every retained chunk and original OID without requiring or writing a plaintext filesystem copy.

    Args:
        service (Service): Trusted current key and storage boundaries, including an independent recovery reader.
        access (Access): Already admitted export or recovery scope.
        repository (Repository): Authenticated original-Git inventory.

    Returns:
        tuple[tuple[tuple[str, bytes], ...], tuple[tuple[str, int, bytes], ...]]: Exact object and metadata bytes within aggregate limits.
    """
    return validate_view(service.view(access), repository)


def validate_view(view: View, repository: Repository) -> tuple[tuple[tuple[str, bytes], ...], tuple[tuple[str, int, bytes], ...]]:
    """
    Verify original objects and metadata using a reader with no implicit live authorization or filesystem effects.

    Args:
        view (View): Online admitted reader or independently verified offline disclosure reader.
        repository (Repository): Authenticated original-Git inventory.

    Returns:
        tuple[tuple[tuple[str, bytes], ...], tuple[tuple[str, int, bytes], ...]]: Exact reconstructed objects and metadata.
    """
    if len(repository.objects) > view.budget.revisions or len(repository.files) > view.budget.revisions:
        raise NativeError("incomplete")
    if any(item.data.size < 0 for item in repository.objects) or any(item.data.size < 0 for item in repository.files):
        raise NativeError("invalid")
    if sum(item.data.size for item in repository.objects) + sum(item.data.size for item in repository.files) > view.budget.bytes:
        raise NativeError("incomplete")
    objects = tuple((item.oid, materialize_view(view, item.data)) for item in repository.objects)
    metadata = tuple((item.path, item.mode, materialize_view(view, item.data)) for item in repository.files)
    if sum(len(data) for _, data in objects) + sum(len(data) for _, _, data in metadata) > view.budget.bytes:
        raise NativeError("incomplete")
    for name, mode, _ in metadata:
        path = Path(name)
        if (
            path.is_absolute()
            or path.as_posix() != name
            or not path.parts
            or path.parts[0] == "objects"
            or any(part in {"", ".", ".."} for part in path.parts)
            or not 0 <= mode <= 0o777
        ):
            raise NativeError("invalid")
    if len({oid for oid, _ in objects}) != len(objects) or len({name for name, _, _ in metadata}) != len(metadata):
        raise NativeError("invalid")
    for oid, data in objects:
        if canonical(data, repository.algorithm) != oid:
            raise NativeError("invalid")
    return objects, metadata


def restore(service: Service, access: Access, record: str, target: Path) -> Repository:
    """
    Restore exact objects and recorded metadata into a new protected inert repository without executing its original configuration or hooks.

    Args:
        service (Service): Current authenticated native service.
        access (Access): Whole-identity export admission.
        record (str): Exact original-Git archive UUID from the current encrypted frontier.
        target (Path): Absent destination under verified protected working storage.

    Returns:
        Repository: Verified inventory; review original config/hooks and external-worktree paths before activating the restored repository.
    """
    require_protected(target.parent)
    started = service.monotonic()
    registration, frontier = service.snapshot(access, "export", "*")
    pointer = next((item for item in frontier.archives if item.record == identifier(record) and item.kind == GIT_ARCHIVE), None)
    if pointer is None:
        raise NativeError("denied")
    repository = parse(service.open(access, pointer), Repository)
    objects, metadata = validate(service, access, repository)
    created = False
    try:
        target.mkdir(mode=0o700)
        created = True
        git(target, ("init", "--bare", "--template=", f"--object-format={repository.algorithm}", "."))
        for oid, data in objects:
            if canonical(data, repository.algorithm) != oid:
                raise NativeError("invalid")
            header, content = data.split(b"\0", 1)
            kind = header.split(b" ", 1)[0].decode("ascii")
            actual = plumbing(target, ("hash-object", "-w", "-t", kind, "--stdin"), service.budget.bytes, content).strip()
            if actual != oid.encode("ascii"):
                raise NativeError("invalid")
        # Ref/HEAD bytes can be checked with fresh safe configuration before restoring any executable or original config.
        deferred: list[tuple[str, int, bytes]] = []
        for name, mode, data in metadata:
            if name == "HEAD" or name == "packed-refs" or name.startswith("refs/"):
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                path.write_bytes(data)
                path.chmod(0o600)
            else:
                deferred.append((name, mode, data))
        plumbing(target, ("fsck", "--full", "--no-reflogs"), service.budget.bytes)
        for name, mode, data in deferred:
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(data)
            path.chmod(0o600 | (mode & 0o100))
        for name, _, data in metadata:
            if (target / name).read_bytes() != data:
                raise NativeError("incomplete")
        # Flush restored metadata and directory entries, not only Git's object files, before reporting a completed restore.
        for parent, _, names in os.walk(target, topdown=False):
            for name in names:
                with (Path(parent) / name).open("rb") as stream:
                    os.fsync(stream.fileno())
            descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        service.release(access, "export", "*", registration, started)
        return repository
    except (OSError, NativeError):
        if created:
            shutil.rmtree(target)
        raise NativeError("incomplete") from None
