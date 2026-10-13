"""
Adapt synchronous Codex prompt and Stop events to conversation-scoped local completion checks.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import shlex
import sys
from pathlib import Path

from attrs import frozen

from witful.completion.core import check
from witful.completion.models import Audit
from witful.completion.storage import context_workspaces, identity, runtime_directory, snapshots
from witful.files import replace_file
from witful.knowledge.contracts import as_data, structure


@frozen
class Session:
    """
    Keep explicit conversational activation and the expected turn separate from all other sessions.

    Attributes:
        active (bool): Whether this conversation currently selects the configured identity.
        task (str): Hashed session/turn binding, never raw prompt text.
        workspace (str): Explicit hook working directory.
    """

    active: bool
    task: str
    workspace: str


def _text(payload: dict[str, object], name: str) -> str:
    """
    Require a bounded nonempty hook field while ignoring unneeded prompt and transcript data.

    Args:
        payload (dict[str, object]): Parsed event fields.
        name (str): Required text field.

    Returns:
        str: Validated text value.

    Raises:
        ValueError: A required field is absent, empty, or oversized.
    """
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError("A required hook field is missing or invalid")
    return value


def configuration(root: Path, selected: str) -> dict[str, object]:
    """
    Prepare a synchronous hook definition for explicit user review and native trust.

    Args:
        root (Path): Explicit collection root.
        selected (str): Conversation identity name recognized by the adapter.

    Returns:
        dict[str, object]: User-level hooks.json content without installing or trusting it.
    """
    command = shlex.join([sys.executable, "-m", "witful.completion", "--repo", str(root.resolve()), "codex-hook", "--identity", selected])
    return {"hooks": {name: [{"hooks": [{"type": "command", "command": command, "timeout": 60}]}] for name in ("UserPromptSubmit", "Stop")}}


def handle(root: Path, selected: str, payload: dict[str, object]) -> dict[str, object]:
    """
    Bind each prompt to fresh review state and block Stop until explicit current coverage passes.

    Args:
        root (Path): Selected collection; no other identity source is read or modified.
        selected (str): Exact conversational activation name configured by the caller.
        payload (dict[str, object]): Native event; prompt text is inspected only for exact mode commands.

    Returns:
        dict[str, object]: Native JSON response; incomplete coverage uses a block decision.

    Raises:
        ValueError: An unsupported event or invalid binding was supplied.
    """
    event = _text(payload, "hook_event_name")
    if event not in {"UserPromptSubmit", "Stop"}:
        raise ValueError("Only UserPromptSubmit and synchronous Stop events are supported")
    session = _text(payload, "session_id")
    turn = _text(payload, "turn_id")
    cwd = Path(_text(payload, "cwd"))
    if not cwd.is_absolute() or not selected.strip():
        raise ValueError("The hook requires an absolute workspace and configured identity name")
    key = hashlib.sha256(session.encode()).hexdigest()
    task = hashlib.sha256(json.dumps([session, turn]).encode()).hexdigest()
    directory = runtime_directory(root) / key
    if directory.is_symlink():
        raise ValueError("Session state must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = directory / "session.json"
    audit_path = directory / f"{task}.json"
    if any(path.is_symlink() for path in (state_path, audit_path, directory / ".lock")):
        raise ValueError("Runtime state files must not be symlinks")

    # A per-session advisory lock serializes hook retries without coupling independent conversations.
    with (directory / ".lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        before = state_path.read_bytes() if state_path.exists() else None
        state = structure(json.loads(before), Session) if before is not None else Session(True, task, str(cwd))
        if event == "UserPromptSubmit":
            prompt = payload.get("prompt")
            if not isinstance(prompt, str):
                raise ValueError("UserPromptSubmit requires prompt text")
            if prompt.strip() == "identity deactivate":
                state = Session(False, task, str(cwd))
            elif prompt.strip() == f"identity activate {selected}":
                identity(root)
                state = Session(True, task, str(cwd))
            else:
                state = Session(state.active, task, str(cwd))
            replace_file(state_path, (json.dumps(as_data(state)) + "\n").encode(), expected=before)
            if not state.active:
                return {}
            workspace_args = [value for path in context_workspaces(root, cwd)[1:] for value in ("--workspace", str(path))]
            command = shlex.join(
                [
                    sys.executable,
                    "-m",
                    "witful.completion",
                    "--repo",
                    str(root),
                    "plan",
                    "--task",
                    task,
                    *workspace_args,
                    "--output",
                    str(audit_path),
                    "--replace",
                ]
            )
            context = (
                "Before final handoff, run the completion plan after source changes, review every entry, and run check with the same "
                "task/workspace/output (use --input for check). Evidence is an attestation, not automatically verified truth. "
                "Use outcome handoff and explicit blockers when work remains. Do not store prompts, transcripts, or credentials. "
                f"Plan command: {command}"
            )
            return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
        if not state.active:
            return {}
        if state.task != task or state.workspace != str(cwd):
            return {
                "decision": "block",
                "reason": "Completion audit belongs to a different turn or workspace; initialize this prompt again.",
            }
        if not audit_path.is_file():
            return {"decision": "block", "reason": f"Complete the current hierarchy review before handoff. Audit is missing: {audit_path}"}
        audit = structure(json.loads(audit_path.read_text()), Audit)
        errors = check(audit, identity(root), task, snapshots(context_workspaces(root, cwd)))
        if errors:
            return {"decision": "block", "reason": "Completion audit failed: " + "; ".join(errors[:8])}
        return {}
