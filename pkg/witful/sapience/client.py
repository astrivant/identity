"""
Validate MCP responses and synchronize one explicit local Sapience server process.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters, stdio_client, types

from witful.knowledge.contracts import as_data

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from witful.sapience.models import Projection


@asynccontextmanager
async def connect(command: Sequence[str]) -> AsyncIterator[ClientSession]:
    """
    Launch the selected server, forwarding only documented provider and storage settings.

    Args:
        command (Sequence[str]): Explicit executable and arguments; never interpreted by a shell.

    Yields:
        ClientSession: Initialized MCP session, closed together with its subprocess on exit.

    Raises:
        ValueError: No executable was provided.
    """
    if not command:
        raise ValueError("Provide a Sapience server executable")

    allowed = {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "EMBEDDINGS_PROVIDER",
        "EMBEDDINGS_MODEL",
        "SAPIENCE_DATA_DIR",
        "MEMORY_DB_PATH",
        "LEDGER_DB_PATH",
        "SAPIENCE_NAMESPACE",
        "PYTHONPATH",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    parameters = StdioServerParameters(command=command[0], args=list(command[1:]), env=environment)

    async with stdio_client(parameters) as (reader, writer), ClientSession(reader, writer, read_timeout_seconds=120) as session:
        await session.initialize()
        yield session


def decode(result: types.CallToolResult, output_schema: dict[str, object]) -> dict[str, object]:
    """
    Reject error envelopes, conflicting representations, and malformed output contracts.

    Args:
        result (types.CallToolResult): Untrusted tool response.
        output_schema (dict[str, object]): Advertised success schema, additionally checked by domain callers.

    Returns:
        dict[str, object]: Validated JSON object without promoting generated content to authority.

    Raises:
        ValueError: The tool failed or its JSON representations are inconsistent.
    """
    if result.is_error:
        raise ValueError("Sapience reported a tool failure; no journal changes were made")

    texts = [item.text for item in result.content if isinstance(item, types.TextContent)]
    text_data: object = json.loads(texts[0]) if len(texts) == 1 else None
    data: object = result.structured_content if result.structured_content is not None else text_data

    if not isinstance(data, dict) or "error" in data or not all(isinstance(key, str) for key in data):
        raise ValueError("Sapience returned an invalid or failed result")

    if result.structured_content is not None and texts and (len(texts) != 1 or text_data != data):
        raise ValueError("Sapience structured and text results disagree")

    Draft202012Validator(output_schema).validate(data)
    return dict(data)


async def contracts(session: ClientSession) -> dict[str, dict[str, object]]:
    """
    Discover typed operations before performing any writes.

    Args:
        session (ClientSession): Initialized server session.

    Returns:
        dict[str, dict[str, object]]: Available structured output schemas keyed by tool name.

    Raises:
        ValueError: The server lacks the fork's projection contract.
    """
    tools = await session.list_tools()
    schemas = {tool.name: dict(tool.output_schema) for tool in tools.tools if tool.output_schema is not None}

    if not {"upsert_memory", "read_memory"} <= schemas.keys():
        raise ValueError("Sapience must provide structured upsert_memory and read_memory; install the documented fork")

    return schemas


async def synchronize(session: ClientSession, projection: Projection) -> int:
    """
    Upsert and read back every record so interrupted runs can safely resume with stable IDs.

    Args:
        session (ClientSession): Initialized, explicitly selected server session.
        projection (Projection): Validated local hierarchy projection.

    Returns:
        int: Number of records confirmed by full readback.

    Raises:
        ValueError: The server acknowledges a different ID, namespace, or provenance, or readback differs.
    """
    schemas = await contracts(session)

    for memory in projection.memories:
        payload = as_data(memory)
        written = decode(await session.call_tool("upsert_memory", payload), schemas["upsert_memory"])

        if written != {"id": memory.memory_id, "namespace": memory.namespace, "status": "upserted", "metadata": payload["metadata"]}:
            raise ValueError("Sapience write acknowledgement does not match source provenance")

        stored = decode(
            await session.call_tool("read_memory", {"memory_id": memory.memory_id, "namespace": memory.namespace}), schemas["read_memory"]
        )
        expected = {"id": payload.pop("memory_id"), **payload}

        if stored != expected:
            raise ValueError("Sapience readback differs from the projected source; retry the same projection")

    return len(projection.memories)
