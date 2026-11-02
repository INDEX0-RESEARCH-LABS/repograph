"""MCP server exposing RepoGraph's read-only intelligence tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from . import __version__
from .config import load_settings
from .impact import analyze_impact
from .query import (
    architecture_summary,
    dependency_graph,
    find_references as query_references,
    search_symbols as query_symbols,
)
from .store import Store

INSTRUCTIONS = """RepoGraph answers repository-structure questions from a local index.
Every relationship carries a source location, extraction method and confidence.
Results are partial by construction: absence of a dependency or test is not
evidence that a change is safe. Call analyze_change_impact before proposing
edits, and read the blind_spots field."""


def _store(root: Path) -> Store:
    settings = load_settings(root)
    if not settings.db_path.exists():
        # Auto-build on first use so agents never see "no index" after a change.
        from .indexer import index_repository

        index_repository(root, settings=settings)
    else:
        from .indexer import ensure_index

        ensure_index(root, settings=settings)
    store = Store(settings)
    store.init_schema()
    return store


def build_server(root: str | Path) -> MCPServer:
    root = Path(root).expanduser().resolve()
    # No fail-fast here on purpose. An MCP client reports a process exit as a
    # disconnected server, and the agent is then left with no tool to call.
    # Tools return the missing-index error instead, which is actionable.
    server = MCPServer("repograph", instructions=INSTRUCTIONS, version=__version__)

    @server.tool(description="Search indexed symbols by name or qualified name. Returns definitions with file:line evidence.")
    def search_symbols(query: str, kind: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        try:
            with _store(root) as store:
                hits = query_symbols(store, query, kind=kind, limit=limit)
            return {"query": query, "symbols": hits,
                    "note": "Matches are lexical over symbol names, not semantic embeddings."}
        except Exception as exc:  # MCP tools must return actionable errors
            return {"error": f"{type(exc).__name__}: {exc}"}

    @server.tool(description="Find definitions and statically resolved reference sites for a symbol.")
    def find_references(name: str, limit: int = 100) -> dict[str, Any]:
        limit = max(1, min(int(limit), 500))
        try:
            with _store(root) as store:
                return query_references(store, name, limit=limit)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    @server.tool(description="Get the file-level dependency graph around a path (direction: in, out, both).")
    def get_dependency_graph(path: Optional[str] = None, direction: str = "both",
                             depth: int = 1) -> dict[str, Any]:
        if direction not in ("in", "out", "both"):
            return {"error": "direction must be one of: in, out, both"}
        try:
            with _store(root) as store:
                return dependency_graph(store, path=path, direction=direction,
                                        depth=max(1, min(int(depth), 5)))
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    @server.tool(description=(
        "Analyze the impact of changed files, a symbol, or the current git diff. "
        "Returns direct and transitive dependents, related tests, routes, models, "
        "architecture notes, and explicit blind spots."
    ))
    def analyze_change_impact(paths: Optional[list[str]] = None,
                              symbol: Optional[str] = None, diff: bool = False,
                              depth: int = 2, include_tests: bool = True) -> dict[str, Any]:
        if not paths and not symbol and not diff:
            return {"error": "provide paths, symbol, or diff=true"}
        try:
            with _store(root) as store:
                return analyze_impact(store, root, paths=paths, symbol=symbol, diff=diff,
                                      depth=max(1, min(int(depth), 5)),
                                      include_tests=bool(include_tests))
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    @server.tool(description="Find tests related to changed files via import edges and naming conventions.")
    def find_related_tests(paths: list[str], depth: int = 1) -> dict[str, Any]:
        try:
            with _store(root) as store:
                result = analyze_impact(store, root, paths=paths, depth=max(1, min(int(depth), 3)))
            if "error" in result:
                return result
            return {"tests": result["related_tests"],
                    "blind_spots": [b for b in result["blind_spots"] if b["kind"] in
                                    ("parse-errors", "no-static-dependents",
                                     "test-selection-reachability")],
                    "note": ("Test selection is heuristic; the suite is the ground truth. "
                             "Test files in test-selection-reachability can also be affected.")}
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    @server.tool(description="Summarize repository architecture: languages, layers, hubs, entry points, routes, models.")
    def get_architecture_summary() -> dict[str, Any]:
        try:
            with _store(root) as store:
                return architecture_summary(store, root)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    return server


def main() -> None:
    import os

    root = os.environ.get("REPOGRAPH_ROOT", os.getcwd())
    build_server(root).run("stdio")


if __name__ == "__main__":
    main()
