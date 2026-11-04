"""Command line interface."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .config import INDEX_DIR, load_settings, init_project
from .impact import analyze_impact
from .indexer import ensure_index, index_repository
from .query import (
    architecture_summary,
    dependency_graph,
    find_cycles,
    find_references,
    quick_status,
    search as search_repo,
)
from .store import Store

app = typer.Typer(
    name="repograph",
    help="Evidence-backed codebase intelligence for AI coding agents.",
    no_args_is_help=True,
    add_completion=False,
)


def _root(path: Optional[Path]) -> Path:
    return (path or Path.cwd()).expanduser().resolve()


def _open_store(root: Path) -> tuple[Store, object]:
    settings = load_settings(root)
    if not settings.db_path.exists():
        typer.echo(f"no index found at {settings.db_path}", err=True)
        typer.echo("run: repograph index .", err=True)
        raise typer.Exit(1)
    store = Store(settings)
    store.init_schema()
    return store, settings


def _emit(data: dict | list, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False))


@app.command()
def init(path: Optional[Path] = typer.Argument(None, help="Repository root (default: cwd).")) -> None:
    """Create the local .repograph directory and default configuration."""
    root = _root(path)
    settings = init_project(root)
    typer.echo(f"initialized {settings.state_dir}")
    typer.echo(f"next: repograph index {root}")


@app.command()
def index(
    path: Optional[Path] = typer.Argument(None, help="Repository root (default: cwd)."),
    force: bool = typer.Option(False, "--force", help="Reparse every file."),
    reset: bool = typer.Option(False, "--reset", help="Drop the existing index first."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Discover, parse and index a repository (incremental)."""
    root = _root(path)
    if not root.is_dir():
        typer.echo(f"not a directory: {root}", err=True)
        raise typer.Exit(1)
    settings = init_project(root)
    stats = index_repository(root, force=force, reset=reset, settings=settings)
    data = {
        "root": str(root),
        "files_scanned": stats.files_scanned,
        "added": stats.added,
        "updated": stats.updated,
        "unchanged": stats.unchanged,
        "deleted": stats.deleted,
        "parse_errors": stats.parse_errors,
        "duration_s": stats.duration_s,
        "db_bytes": stats.db_bytes,
        "languages": stats.languages,
        "truncated": stats.truncated,
        "skipped_large": stats.skipped_large,
        "skipped_symlink": stats.skipped_symlink,
    }
    if as_json:
        _emit(data, True)
        return
    typer.echo(f"indexed {stats.files_scanned} files in {stats.duration_s:.2f}s "
               f"({stats.added} added, {stats.updated} updated, {stats.deleted} deleted, "
               f"{stats.parse_errors} parse errors)")
    typer.echo(f"database: {settings.db_path} ({stats.db_bytes / 1024:.0f} KiB)")
    if stats.truncated:
        typer.echo("warning: file limit reached; increase max_files in .repograph/config.json", err=True)


@app.command()
def status(
    path: Optional[Path] = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show index statistics and whether a re-index is needed."""
    root = _root(path)
    store, settings = _open_store(root)
    with store:
        data = quick_status(store, settings)
    if as_json:
        _emit(data, True)
        return
    typer.echo(f"root:      {data.get('root')}")
    typer.echo(f"indexed:   {data.get('indexed_at')}")
    typer.echo(f"files:     {data['files']}  symbols: {data['symbols']}  "
               f"internal edges: {data['internal_imports']}")
    typer.echo(f"tests:     {data['tests']}  parse errors: {data['parse_errors']}")
    for item in data.get("parse_error_files") or []:
        typer.echo(f"           {item['path']}: {item['parse_error']}")
    typer.echo(f"languages: {', '.join(f'{k}={v}' for k, v in data['languages'].items()) or '-'}")
    typer.echo(f"database:  {data['db_bytes'] / 1024:.0f} KiB")
    stale = data["stale"]
    state = "stale" if data["needs_reindex"] else "up to date"
    typer.echo(f"worktree:  {state} (+{stale['added']} ~{stale['changed']} -{stale['deleted']})")


@app.command()
def search(
    query: str = typer.Argument(..., help="Symbol or text to search for."),
    path: Optional[Path] = typer.Option(None, "--root", help="Repository root."),
    kind: Optional[str] = typer.Option(None, "--kind", help="Filter symbols by kind."),
    limit: int = typer.Option(20, "--limit", min=1, max=200),
    related: bool = typer.Option(False, "--related", help="Include directly related files."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Search indexed symbols and source text."""
    root = _root(path)
    if ensure_index(root):
        typer.echo("index was stale; re-indexed.", err=True)
    store, _ = _open_store(root)
    with store:
        if kind:
            from .query import search_symbols

            data = {"query": query, "symbols": search_symbols(store, query, kind=kind, limit=limit)}
        else:
            data = search_repo(store, root, query, limit=limit, related=related)
    if as_json:
        _emit(data, True)
        return
    typer.echo(f"symbols ({len(data['symbols'])}):")
    for s in data["symbols"]:
        typer.echo(f"  {s['kind']:<9} {s['qualified_name']}  {s['path']}:{s['lines'][0]}")
    text = data.get("text", [])
    typer.echo(f"text matches ({len(text)}):")
    for t in text:
        typer.echo(f"  [{t.get('kind', 'source')}] {t['path']}:{t['line']}: {t['text']}")
    for r in data.get("related_files", []):
        typer.echo(f"  related [{r['relation']}] {r['path']} -> {r['target']}")



@app.command()
def impact(
    paths: Optional[list[str]] = typer.Argument(None, help="Changed files (repo-relative)."),
    path: Optional[Path] = typer.Option(None, "--root", help="Repository root."),
    symbol: Optional[str] = typer.Option(None, "--symbol", help="Analyze a symbol instead of files."),
    diff: bool = typer.Option(False, "--diff", help="Use the current git worktree diff."),
    depth: int = typer.Option(2, "--depth", min=1, max=5),
    tests: bool = typer.Option(True, "--tests/--no-tests"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Estimate what a change can affect, with evidence and confidence."""
    root = _root(path)
    if ensure_index(root):
        typer.echo("index was stale; re-indexed.", err=True)
    store, _ = _open_store(root)
    with store:
        data = analyze_impact(store, root, paths=list(paths or []), symbol=symbol,
                              diff=diff, depth=depth, include_tests=tests)
    if as_json:
        _emit(data, True)
        if "error" in data:
            raise typer.Exit(2)
        return
    if "error" in data:
        typer.echo(f"error: {data['error']}", err=True)
        for c in data.get("candidates", []):
            typer.echo(f"  candidate: {c['qualified_name']} ({c['path']}:{c['kind']})", err=True)
        raise typer.Exit(2)
    target = data["target"]
    typer.echo(f"changed files ({len(data['changed_files'])}): {', '.join(data['changed_files']) or '-'}")
    typer.echo(f"changed symbols: {data['summary']['changed_symbols']}")
    for s in target["symbols"][:10]:
        typer.echo(f"  {s['kind']:<9} {s['qualified_name']}  {s['path']}:{s['lines'][0]}")
    typer.echo(f"\ndirect dependents ({len(data['direct_dependents'])}):")
    for d in data["direct_dependents"][:20]:
        reason = d["reasons"][0]
        typer.echo(f"  [{d['confidence']}] {d['path']}  ({reason['relation']} at line {reason.get('line')})")
    typer.echo(f"transitive dependents: {len(data['transitive_dependents'])}")
    for t in data["transitive_dependents"][:10]:
        typer.echo(f"  [{t['confidence']}] depth {t['depth']} {t['path']}")
    typer.echo(f"\nrelated tests ({len(data['related_tests'])}):")
    for t in data["related_tests"][:15]:
        rules = ", ".join(r["rule"] for r in t["rules"])
        typer.echo(f"  [{t['confidence']}] {t['path']}  ({rules})")
    if data["affected_routes"]:
        typer.echo("\naffected routes:")
        for r in data["affected_routes"][:15]:
            typer.echo(f"  {r['method']} {r['path']}  {r['file']}:{r['line']}")
    if data["related_models"]:
        typer.echo("\nrelated models:")
        for m in data["related_models"][:15]:
            typer.echo(f"  {m['qualified_name']}  {m['path']}:{m['line']}")
    if data["architecture"]["documentation_mentions"]:
        typer.echo("\ndocumentation mentions:")
        for d in data["architecture"]["documentation_mentions"][:5]:
            typer.echo(f"  {d['path']}:{d['line']}")
    typer.echo("\nblind spots:")
    for b in data["blind_spots"]:
        typer.echo(f"  - {b['kind']} ({b['count']}): {b['message']}")
    typer.echo("\nnote: absence of static evidence is not evidence of safety.")


@app.command()
def tests(
    paths: Optional[list[str]] = typer.Argument(None, help="Changed files (repo-relative)."),
    path: Optional[Path] = typer.Option(None, "--root", help="Repository root."),
    diff: bool = typer.Option(False, "--diff", help="Use the git diff instead of paths."),
    base: str = typer.Option("HEAD", "--base", help="Git ref to diff against."),
    strict: bool = typer.Option(
        False, "--strict", help="Exit 3 when a test cannot be ruled out or none was selected."
    ),
    command_only: bool = typer.Option(
        False, "--command", help="Print only the pytest command to run."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Test files a change reaches, and the ones that cannot be ruled out (heuristic)."""
    from .test_gate import select

    if not paths and not diff:
        typer.echo("error: provide paths or --diff", err=True)
        raise typer.Exit(2)
    root = _root(path)
    if ensure_index(root):
        typer.echo("index was stale; re-indexed.", err=True)
    store, _ = _open_store(root)
    with store:
        data = select(store, root, paths=list(paths or []), diff=diff, base=base, strict=strict)

    if "error" in data:
        typer.echo(f"error: {data['error']}", err=True)
        raise typer.Exit(2)
    if as_json:
        _emit(data, True)
        raise typer.Exit(data["exit_code"])
    if command_only:
        typer.echo(data["command"])
        raise typer.Exit(data["exit_code"])

    sel = data["selection"]
    typer.echo(f"changed files ({len(data['changed_files'])}):")
    for p in data["changed_files"][:20]:
        typer.echo(f"  {p}")
    for p in data["unindexed_changed_files"]:
        typer.echo(f"  {p}  (not in the index: run `repograph index .`)")

    fraction = f"{sel['fraction']:.0%} of {sel['total_tests']}" if sel["fraction"] is not None else "no tests"
    typer.echo(f"\nrun these ({sel['run']}, {fraction}):")
    for t in data["run"]:
        typer.echo(f"  [{t['confidence']}] {t['path']}  ({', '.join(t['rules'])})")
    if not data["run"]:
        typer.echo("  - nothing: no test reaches this change. That is not evidence of safety.")

    typer.echo(f"\ncannot rule out ({sel['undetermined']}):")
    for u in data["undetermined"][:20]:
        typer.echo(f"  {u['path']}  ({u['reason']})")
    if data["reachable_not_selected"]:
        typer.echo(f"\nreachable but not selected ({len(data['reachable_not_selected'])}):")
        for p in data["reachable_not_selected"][:20]:
            typer.echo(f"  {p}")
    for c in data["caveats"]:
        typer.echo(f"  note: {c}")

    typer.echo(f"\nnext: {data['command']}")
    raise typer.Exit(data["exit_code"])


@app.command()
def graph(
    target: Optional[str] = typer.Argument(None, help="Focus file (default: whole repo)."),
    path: Optional[Path] = typer.Option(None, "--root"),
    direction: str = typer.Option("both", "--direction", help="in, out, or both."),
    depth: int = typer.Option(2, "--depth", min=1, max=5),
    fmt: str = typer.Option("json", "--format", help="json or dot."),
    cycles: bool = typer.Option(False, "--cycles", help="Report dependency cycles."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect the file dependency graph or its cycles."""
    root = _root(path)
    if ensure_index(root):
        typer.echo("index was stale; re-indexed.", err=True)
    store, _ = _open_store(root)
    with store:
        if cycles:
            data = {"cycles": find_cycles(store)}
        else:
            data = dependency_graph(store, path=target, direction=direction, depth=depth)
    if as_json or (fmt == "json" and not typer.get_text_stream("stdout").isatty()):
        _emit(data, True)
        return
    if "cycles" in data:
        if not data["cycles"]:
            typer.echo("no dependency cycles found")
        for i, cyc in enumerate(data["cycles"], 1):
            typer.echo(f"cycle {i}: {' -> '.join(cyc)}")
        return
    if fmt == "dot" and not as_json:
        typer.echo("digraph repograph {")
        typer.echo('  rankdir="LR";')
        for n in data["nodes"]:
            typer.echo(f'  "{n}";')
        for e in data["edges"]:
            typer.echo(f'  "{e["from"]}" -> "{e["to"]}" [label="L{e["line"]}"];')
        typer.echo("}")
        return
    _emit(data, True)


@app.command()
def refs(
    name: str = typer.Argument(..., help="Symbol name or qualified name."),
    path: Optional[Path] = typer.Option(None, "--root"),
    limit: int = typer.Option(100, "--limit", min=1, max=500),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Find definitions and resolved references for a symbol."""
    root = _root(path)
    if ensure_index(root):
        typer.echo("index was stale; re-indexed.", err=True)
    store, _ = _open_store(root)
    with store:
        data = find_references(store, name, limit=limit)
    if as_json:
        _emit(data, True)
        return
    for d in data["definitions"]:
        typer.echo(f"def  {d['kind']:<9} {d['qualified_name']}  {d['path']}:{d['lines'][0]}")
    for r in data["references"]:
        typer.echo(f"ref  [{r['confidence']}] {r['path']}:{r['line']} -> {r['target']}")
    if not data["definitions"]:
        typer.echo("symbol not found in index", err=True)


@app.command()
def arch(
    path: Optional[Path] = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Summarize repository architecture from the index."""
    root = _root(path)
    if ensure_index(root):
        typer.echo("index was stale; re-indexed.", err=True)
    store, _ = _open_store(root)
    with store:
        data = architecture_summary(store, root)
    if as_json:
        _emit(data, True)
        return
    typer.echo(f"files: {data['files']}  symbols: {data['symbols']}  internal edges: {data['internal_edges']}")
    typer.echo(f"unresolved imports: {data['unresolved_imports']}  dynamic imports: {data['dynamic_imports']}"
               "  (a resolved-edge count is not a census)")
    typer.echo(f"parse errors: {len(data['parse_errors'])}")
    typer.echo("languages: " + ", ".join(f"{k}={v}" for k, v in data["languages"].items()))
    typer.echo("layers:    " + ", ".join(f"{k}={v}" for k, v in data["layers"].items()))
    typer.echo("top directories:")
    for name, d in list(data["top_directories"].items())[:10]:
        typer.echo(f"  {name:<20} files={d['files']:<5} in={d['inbound']:<5} out={d['outbound']}")
    typer.echo("dependency hubs:")
    for hub in data["dependency_hubs"][:5]:
        typer.echo(f"  in={hub['inbound']:<4} {hub['path']}")
    typer.echo(f"entry points: {', '.join(data['entry_points'][:8]) or '-'}")
    typer.echo(f"routes: {len(data['http_routes'])}  models: {len(data['database_models'])}")


@app.command()
def setup(
    path: Optional[Path] = typer.Argument(None, help="Repository root (default: cwd)."),
    client: Optional[list[str]] = typer.Option(
        None, "--client", "-c", help="claude, cursor, codex, opencode. Repeatable. Default: detected."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply without asking."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes and write nothing."),
    no_skill: bool = typer.Option(
        False, "--no-skill", help="Register the server but skip agent instructions."
    ),
) -> None:
    """Register the MCP server with your agent and install its usage instructions."""
    from pathlib import Path as _Path

    from .agent_setup import apply, detect_clients, plan

    root = _root(path)
    clients = client or detect_clients(root, _Path.home())
    try:
        changes = plan(root, clients, include_skill=not no_skill)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"clients: {', '.join(clients)}")
    if "codex" not in clients and (_Path.home() / ".codex").is_dir():
        typer.echo("note: Codex detected; add --client codex to register it in ~/.codex/config.toml")
    for change in changes:
        typer.echo(f"  {change.kind:<9} {change.path}  ({change.note})")

    pending = [c for c in changes if c.kind != "unchanged"]
    if not pending:
        typer.echo("already configured; nothing to write.")
    else:
        for change in pending:
            typer.echo("")
            typer.echo(change.diff().rstrip("\n"))

    if dry_run:
        typer.echo("\ndry run: nothing written.")
        raise typer.Exit(0)

    if pending:
        if not yes:
            typer.confirm("Apply these changes?", abort=True)
        try:
            written = apply(changes)
        except (OSError, ValueError) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from exc
        typer.echo("")
        for item in written:
            typer.echo(f"wrote {item}")

    settings = load_settings(root)
    if not settings.db_path.exists():
        typer.echo(f"\nnext: repograph index {root}")
    typer.echo("next: restart your agent, then ask \"what breaks if I change <symbol>?\"")




@app.command()
def watch(
    path: Optional[Path] = typer.Option(None, "--root", help="Repository root."),
    interval: float = typer.Option(2.0, "--interval", help="Poll interval in seconds."),
    daemon: bool = typer.Option(False, "--daemon", help="Run in background."),
    stop: bool = typer.Option(False, "--stop", help="Stop a running background watcher."),
) -> None:
    """Watch for file changes and re-index automatically (polling, no native deps)."""
    root = _root(path)
    settings = load_settings(root)
    pid_file = settings.state_dir / "watch.pid"
    log_file = settings.state_dir / "watch.log"

    if stop:
        if not pid_file.exists():
            typer.echo("no watcher running")
            raise typer.Exit(0)
        pid = int(pid_file.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            typer.echo(f"stopped watcher (pid {pid})")
        except ProcessLookupError:
            typer.echo(f"watcher already dead (pid {pid})")
        pid_file.unlink(missing_ok=True)
        raise typer.Exit(0)

    if daemon:
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            try:
                os.kill(pid, 0)
                typer.echo(f"watcher already running (pid {pid})")
                raise typer.Exit(0)
            except ProcessLookupError:
                pid_file.unlink(missing_ok=True)
        child = os.fork()
        if child > 0:
            pid_file.write_text(str(child))
            typer.echo(f"watcher started (pid {child}), logging to {log_file}")
            typer.echo(f"stop with: repograph watch --stop --root {root}")
            raise typer.Exit(0)
        os.setsid()
        sys.stdin.close()
        _log = open(log_file, "a")
        sys.stdout = _log
        sys.stderr = _log
        _watch_loop(root, interval)
        raise typer.Exit(0)

    typer.echo(f"watching {root} (poll every {interval}s, Ctrl+C to stop)")
    try:
        _watch_loop(root, interval)
    except KeyboardInterrupt:
        typer.echo("\nstopped")


def _watch_loop(root: Path, interval: float) -> None:
    settings = load_settings(root)
    if not settings.db_path.exists():
        print("no index; running initial index...", flush=True)
        index_repository(root, settings=settings)

    while True:
        time.sleep(interval)
        with Store(settings) as store:
            store.init_schema()
            data = quick_status(store, settings)
        if data.get("needs_reindex"):
            added = data["stale"]["added"]
            changed = data["stale"]["changed"]
            deleted = data["stale"]["deleted"]
            print(f"[{datetime.now().strftime('%H:%M:%S')}] stale (+{added} ~{changed} -{deleted}); re-indexing...", flush=True)
            stats = index_repository(root, settings=settings)
            print(f"  indexed {stats.files_scanned} files, {stats.parse_errors} parse errors", flush=True)



@app.command()
def serve(
    path: Optional[Path] = typer.Option(None, "--root", help="Repository root to expose."),
    http: bool = typer.Option(False, "--http", help="Use Streamable HTTP instead of stdio."),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
) -> None:
    """Run the MCP server (stdio by default)."""
    from .mcp_server import build_server

    root = _root(path)
    settings = load_settings(root)
    if not settings.db_path.exists():
        typer.echo(
            f"warning: no index at {settings.db_path}; tools return that error until "
            f"`repograph index {root}` runs",
            err=True,
        )
    server = build_server(root)
    if http:
        server.settings.host = host
        server.settings.port = port
        if host not in ("127.0.0.1", "localhost", "::1"):
            typer.echo("warning: the MCP server has no authentication; do not expose it to untrusted networks",
                       err=True)
        typer.echo(f"MCP streamable-http on http://{host}:{port}/mcp", err=True)
        server.run("streamable-http")
    else:
        server.run("stdio")


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
