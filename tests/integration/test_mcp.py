from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from repograph.indexer import index_repository

EXPECTED_TOOLS = {
    "search_symbols",
    "find_references",
    "get_dependency_graph",
    "analyze_change_impact",
    "find_related_tests",
    "get_architecture_summary",
}


def _payload(result) -> dict:
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured
    return json.loads(result.content[0].text)


async def _exercise(repo: Path) -> dict:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "repograph.mcp_server"],
        env={**os.environ, "REPOGRAPH_ROOT": str(repo)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            assert EXPECTED_TOOLS <= tools

            found = _payload(await session.call_tool("search_symbols", {"query": "cancel"}))
            assert any(s["name"] == "cancel" for s in found["symbols"])

            refs = _payload(await session.call_tool("find_references", {"name": "cancel"}))
            assert refs["definitions"]

            graph = _payload(await session.call_tool(
                "get_dependency_graph", {"path": "src/shop/services/billing.py", "direction": "both"}))
            assert graph["edges"]

            impact = _payload(await session.call_tool(
                "analyze_change_impact",
                {"paths": ["src/shop/services/subscription.py"], "depth": 2}))
            assert impact["direct_dependents"]
            assert impact["blind_spots"]

            tests = _payload(await session.call_tool(
                "find_related_tests", {"paths": ["src/shop/services/subscription.py"]}))
            assert any(t["path"] == "tests/test_subscription.py" for t in tests["tests"])

            arch = _payload(await session.call_tool("get_architecture_summary", {}))
            assert arch["files"] == 20

            bad = _payload(await session.call_tool("analyze_change_impact", {}))
            assert "error" in bad
            return {"tools": tools}


def test_mcp_stdio_server_exposes_and_answers(repo: Path):
    index_repository(repo)
    result = asyncio.run(asyncio.wait_for(_exercise(repo), timeout=90))
    assert EXPECTED_TOOLS <= result["tools"]


async def _unindexed(repo: Path) -> dict:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "repograph.mcp_server"],
        env={**os.environ, "REPOGRAPH_ROOT": str(repo)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # The connection must survive an unindexed repository: a client
            # reports a process exit as a disconnected server, and the agent
            # then has nothing to call.
            tools = {t.name for t in (await session.list_tools()).tools}
            assert EXPECTED_TOOLS <= tools
            result = _payload(await session.call_tool("search_symbols", {"query": "x"}))
            return result


def test_mcp_server_stays_connected_without_an_index(tmp_path: Path):
    result = asyncio.run(asyncio.wait_for(_unindexed(tmp_path), timeout=90))
    # The server stays connected; instead of failing, it auto-indexes the repo
    # on first use, so the tool returns a result rather than a missing-index error.
    assert "no index" not in str(result.get("error", ""))
