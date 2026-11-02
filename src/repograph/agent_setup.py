"""Install RepoGraph into coding agents.

The point of this module is not to copy a config file. It is to make the agent
*know when to call the tools* — the measured failure mode is silence, not
connectivity. So setup writes two things: the MCP server registration and a
short instruction file the client loads automatically.

Everything here is a local file write: no repo code runs, every file is backed
up before the first change, and re-running is a no-op.
"""

from __future__ import annotations

import difflib
import json
import re
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

SKILL_NAME = "repograph"

SKILL_BODY = """\
# RepoGraph

A local index of this repository lives in `.repograph/`. Query it instead of
guessing which files a change reaches. It reads a SQLite index and never runs
repository code.

## When to call

Call `analyze_change_impact` before a change that crosses a file boundary:
renaming, moving or deleting a symbol or a file, changing a signature, editing a
shared module, a route handler, or a database model.

Skip it for edits fully contained in one file with no importers, for prose or
dependency bumps, and for runtime-behaviour questions — the graph is static.

## Order

1. `analyze_change_impact` with `paths`, `symbol`, or `diff: true`.
2. Read `blind_spots` before acting. An empty list is not proof of safety.
3. `find_related_tests` when only the test set is needed.
4. `find_references` before a rename; `get_dependency_graph` to walk deeper
   than depth 2; `get_architecture_summary` for orientation.

## Rules

- Cite `file:line` from the result. Do not invent edges.
- `confidence` is a ceiling: `confirmed` may justify an edit, `inferred` and
  `heuristic` require reading the file, `unresolved` means unknown.
- After edits run `repograph index .`. A stale index gives stale answers.
- On a "no index" error, run `repograph index .` and retry once. Do not fall
  back to guessing without saying so.
"""

SKILL_DESCRIPTION = (
    "Answer what a change affects from a local RepoGraph index: before editing a "
    "symbol, before a multi-file change, or when reviewing a diff. Returns "
    "dependents, related tests, routes, models, and the blind spots static "
    "analysis could not resolve."
)


@dataclass
class Change:
    path: Path
    before: str
    after: str
    note: str = ""

    @property
    def kind(self) -> str:
        if not self.before:
            return "create"
        return "unchanged" if self.before == self.after else "update"

    def diff(self) -> str:
        if self.kind == "unchanged":
            return ""
        old = self.before.splitlines(keepends=True)
        new = self.after.splitlines(keepends=True)
        label = "/dev/null" if self.kind == "create" else str(self.path)
        return "".join(
            difflib.unified_diff(old, new, fromfile=label, tofile=str(self.path))
        )


def server_entry(root: Path) -> dict[str, object]:
    """Launch command that does not depend on the client's working directory."""
    args = ["serve", "--root", str(root)]
    candidates = [
        os.path.expanduser("~/.local/share/uv/tools/repograph-codeintel/bin/repograph"),
        shutil.which("repograph"),
    ]
    for exe in candidates:
        if exe and os.path.isfile(exe) and os.access(exe, os.X_OK):
            return {"command": exe, "args": args}
    return {"command": sys.executable, "args": ["-m", "repograph", *args]}


def _merge_json(
    path: Path, keys: str | tuple[str, ...], entry: dict[str, object], note: str
) -> Change:
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    try:
        data = json.loads(before) if before.strip() else {}
    except ValueError as exc:
        raise ValueError(f"{path} is not valid JSON; fix it before running setup") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    keys = (keys,) if isinstance(keys, str) else keys
    node = data
    for key in keys:
        child = node.setdefault(key, {})
        if not isinstance(child, dict):
            raise ValueError(f"{path}: {key!r} must be an object")
        node = child
    node[SKILL_NAME] = entry
    after = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return Change(path=path, before=before, after=after, note=note)


def _codex_block(entry: dict[str, object]) -> str:
    command = json.dumps(entry["command"])
    args = ", ".join(json.dumps(a) for a in entry["args"])  # type: ignore[arg-type]
    return (
        "# >>> repograph (managed by `repograph setup`)\n"
        "[mcp_servers.repograph]\n"
        f"command = {command}\n"
        f"args = [{args}]\n"
        "# <<< repograph\n"
    )


def _codex_config(home: Path, entry: dict[str, object]) -> Change:
    path = home / ".codex" / "config.toml"
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    block = _codex_block(entry)
    pattern = re.compile(r"# >>> repograph.*?# <<< repograph\n", re.DOTALL)
    if pattern.search(before):
        after = pattern.sub(block, before, count=1)
    else:
        after = before + ("\n" if before and not before.endswith("\n") else "") + block
    return Change(path=path, before=before, after=after, note="user-level Codex config")


def _skill_file(root: Path) -> Change:
    path = root / ".claude" / "skills" / SKILL_NAME / "SKILL.md"
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    after = (
        "---\n"
        f"name: {SKILL_NAME}\n"
        f"description: {SKILL_DESCRIPTION}\n"
        "---\n\n"
        f"{SKILL_BODY}"
    )
    return Change(path=path, before=before, after=after, note="Claude Code skill")


def _cursor_rule(root: Path) -> Change:
    path = root / ".cursor" / "rules" / f"{SKILL_NAME}.mdc"
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    after = (
        "---\n"
        f"description: {SKILL_DESCRIPTION}\n"
        "alwaysApply: true\n"
        "---\n\n"
        f"{SKILL_BODY}"
    )
    return Change(path=path, before=before, after=after, note="Cursor rule")


AGENTS_START = "<!-- repograph:start (managed by `repograph setup`) -->"
AGENTS_END = "<!-- repograph:end -->"


def _opencode_entry(entry: dict[str, object]) -> dict[str, object]:
    """OpenCode takes one argv array, unlike Claude/Cursor's command+args pair.

    Emitting the other shape is silently skipped by the client, so the server
    looks configured but never starts.
    """
    return {"type": "local", "command": [entry["command"], *entry["args"]]}  # type: ignore[misc]


def _opencode_rule(root: Path) -> Change:
    """OpenCode reads project instructions from AGENTS.md, keyed by markers."""
    path = root / "AGENTS.md"
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    block = f"{AGENTS_START}\n{SKILL_BODY}{AGENTS_END}\n"
    pattern = re.compile(r"<!-- repograph:start.*?<!-- repograph:end -->\n?", re.DOTALL)
    if pattern.search(before):
        after = pattern.sub(block, before, count=1)
    else:
        after = before + ("\n" if before and not before.endswith("\n") else "") + block
    return Change(path=path, before=before, after=after, note="OpenCode instructions (AGENTS.md)")


def detect_clients(root: Path, home: Path) -> list[str]:
    """Project-scoped clients only.

    Codex is excluded on purpose: its config is user-level, so writing it is an
    explicit `--client codex` decision rather than a side effect of running
    setup in a repository.
    """
    found: list[str] = []
    if (root / ".cursor").is_dir():
        found.append("cursor")
    if (
        (root / "opencode.json").is_file()
        or (root / ".opencode").is_dir()
        or (home / ".config" / "opencode" / "opencode.json").is_file()
    ):
        found.append("opencode")
    # Claude Code is the default: it is the client that reads project `.mcp.json`
    # and the skill directory, and it is where the invocation gap was measured.
    found.append("claude")
    return found


def plan(
    root: Path,
    clients: list[str],
    include_skill: bool = True,
    home: Path | None = None,
) -> list[Change]:
    root = root.expanduser().resolve()
    home = (home or Path.home()).expanduser().resolve()
    entry = server_entry(root)
    changes: list[Change] = []
    unknown = set(clients) - {"claude", "cursor", "codex", "opencode"}
    if unknown:
        raise ValueError(f"unknown client(s): {', '.join(sorted(unknown))}")

    if "claude" in clients:
        changes.append(_merge_json(root / ".mcp.json", "mcpServers", entry, "project MCP config"))
        if include_skill:
            changes.append(_skill_file(root))
    if "opencode" in clients:
        changes.append(
            _merge_json(
                root / "opencode.json",
                ("mcp", "servers"),
                _opencode_entry(entry),
                "OpenCode MCP config",
            )
        )
        if include_skill:
            changes.append(_opencode_rule(root))
    if "cursor" in clients:
        changes.append(
            _merge_json(root / ".cursor" / "mcp.json", "mcpServers", entry, "Cursor MCP config")
        )
        if include_skill:
            changes.append(_cursor_rule(root))
    if "codex" in clients:
        changes.append(_codex_config(home, entry))
    return changes


def apply(changes: list[Change]) -> list[Path]:
    written: list[Path] = []
    for change in changes:
        if change.kind == "unchanged":
            continue
        change.path.parent.mkdir(parents=True, exist_ok=True)
        backup = change.path.with_name(change.path.name + ".bak")
        if change.kind == "update" and not backup.exists():
            backup.write_text(change.before, encoding="utf-8")
        change.path.write_text(change.after, encoding="utf-8")
        if change.path.suffix == ".json":
            json.loads(change.path.read_text(encoding="utf-8"))
        written.append(change.path)
    return written
