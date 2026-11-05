"""Evidence-backed change-impact analysis.

Design rule: an empty result is reported as *absence of static evidence*, never
as safety. Every relationship carries its extractor, location and confidence.
"""

from __future__ import annotations

import json
import posixpath
import re
import subprocess
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from .config import INDEX_DIR, safe_path
from .query import _doc_mentions, _classify_layer
from .store import Store

CAVEATS = [
    "This is a static analysis of statically resolvable relationships. Absence of a relationship is not evidence that a change is safe.",
    "Dynamic imports, reflection, runtime dependency injection, generated code and external consumers are not modeled.",
    "Test selection uses import edges and naming conventions, not execution traces; it can miss tests and include irrelevant ones.",
    "Route and database-model detection use framework-specific heuristics and may produce false positives or miss frameworks.",
    "Confidence levels describe extraction certainty, not the risk of the change itself.",
]

_UNUSED = None
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(root), "-c", "core.quotepath=false", *args],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=[str(a) for a in args], returncode=124, stdout="",
            stderr="git timed out after 60 seconds",
        )


def _diff_path(raw: str) -> str | None:
    """A path from a ``---``/``+++`` line, with git's C quoting undone."""
    p = raw.rstrip("\n")
    if p.startswith('"') and p.endswith('"') and len(p) >= 2:
        # core.quotepath=false keeps unicode raw; only control characters and
        # backslashes are quoted, and those fit JSON's escape set closely enough.
        try:
            p = json.loads(p)
        except ValueError:
            p = p[1:-1]
    return None if p == "/dev/null" else p


def git_changes(root: Path, base: str = "HEAD") -> dict:
    """Changed paths plus added-line ranges from the current worktree.

    Includes staged and unstaged edits against ``base`` and untracked files.
    Deleted files are reported separately because they have no current symbols.
    """
    probe = _git(root, "rev-parse", "--is-inside-work-tree")
    if probe.returncode != 0:
        error = ("git timed out after 60 seconds" if probe.returncode == 124
                 else "not a git repository")
        return {"available": False, "error": error, "paths": [], "lines": {},
                "deleted": [], "untracked": []}
    diff = _git(root, "diff", "--unified=0", "--no-color", "--no-prefix",
                "--no-renames", base, "--")
    if diff.returncode != 0:
        return {"available": False, "error": diff.stderr.strip()[:300] or "git diff failed",
                "paths": [], "lines": {}, "deleted": [], "untracked": []}

    lines: dict[str, set[int]] = defaultdict(set)
    deleted: set[str] = set()
    current: str | None = None
    old_path: str | None = None
    for raw in diff.stdout.splitlines():
        if raw.startswith("--- "):
            old_path = _diff_path(raw[4:].split("\t", 1)[0])
        elif raw.startswith("+++ "):
            current = _diff_path(raw[4:].split("\t", 1)[0])
            if current is None and old_path:
                deleted.add(old_path)
        elif raw.startswith("@@ ") and current:
            m = _HUNK_RE.match(raw)
            if m:
                start = int(m.group(1))
                count = int(m.group(2) or 1)
                for n in range(start, start + count):
                    lines[current].add(n)

    untracked = [
        p for p in _git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0") if p
    ]
    # The index directory is our own artifact. Users who have not gitignored it
    # would otherwise see it reported as a changed file, and the SQLite WAL adds
    # a new path on every index run.
    own = (INDEX_DIR + "/", INDEX_DIR)
    untracked = [p for p in untracked if not p.startswith(own)]
    lines = {k: v for k, v in lines.items() if not k.startswith(own)}
    paths = sorted(set(lines) | set(untracked))
    return {
        "available": True,
        "paths": paths,
        "lines": {k: sorted(v) for k, v in lines.items()},
        "deleted": sorted(deleted - set(paths)),
        "untracked": untracked,
    }


def _normalize_path(root: Path, path: str) -> str:
    p = Path(path)
    if p.is_absolute():
        resolved = safe_path(root, p)
        return resolved.relative_to(root.resolve()).as_posix()
    rel = posixpath.normpath(path.replace("\\", "/"))
    if rel.startswith("../"):
        raise PermissionError(f"path escapes repository root: {path}")
    # normpath already removes a leading "./"; lstrip("./") would strip the
    # characters, turning ".storybook/main.ts" into "storybook/main.ts".
    return rel


def _stem(path: str) -> str:
    base = posixpath.basename(path)
    for ext in (".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".prisma"):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    for prefix in ("test_",):
        if base.startswith(prefix):
            base = base[len(prefix):]
    for suffix in ("_test", ".test", ".spec", "_spec", "-test"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return base


def _is_test_module(path: str) -> bool:
    """True only for a runnable test module, not every file under `tests/`.

    `is_test_path` treats fixture apps such as `tests/test_apps/cliapp/app.py`
    as tests; those are application code that pytest does not collect.
    """
    base = posixpath.basename(path)
    if base == "conftest.py":
        return True
    if base.startswith("test_") or base.endswith("_test" + posixpath.splitext(base)[1]):
        return True
    return any(f".{kind}." in base for kind in ("test", "spec"))


def _find_symbol(store: Store, name: str) -> tuple[dict | None, list[dict]]:
    rows = [dict(r) for r in store.conn.execute(
        """SELECT s.*, f.path FROM symbols s JOIN files f ON f.id=s.file_id
           WHERE s.qualified_name=? OR s.name=?""",
        (name, name),
    ).fetchall()]
    if not rows:
        return None, []
    # A bare name also matches nested symbols (a test-local `class View` has the
    # qualified name `test_x.View`). Prefer a top-level definition so a fixture or
    # test class cannot shadow the real one; several top-level matches stay
    # ambiguous.
    exact = [r for r in rows if r["qualified_name"] == name]
    if len(exact) == 1:
        return exact[0], []
    candidates = exact or rows
    if len(candidates) == 1:
        return candidates[0], []
    return None, [{"name": r["name"], "qualified_name": r["qualified_name"], "path": r["path"],
                   "kind": r["kind"]} for r in candidates][:20]


def _symbols_in_files(store: Store, paths: list[str]) -> list[dict]:
    if not paths:
        return []
    marks = ",".join("?" * len(paths))
    rows = store.conn.execute(
        f"""SELECT s.*, f.path FROM symbols s JOIN files f ON f.id=s.file_id
            WHERE f.path IN ({marks}) ORDER BY f.path, s.start_line""",
        paths,
    ).fetchall()
    return [dict(r) for r in rows]


def _importers(store: Store, path: str) -> list[dict]:
    rows = store.conn.execute(
        """SELECT s.path AS src, i.line, i.method, i.confidence, i.module, i.kind
           FROM imports i JOIN files s ON s.id=i.file_id JOIN files t ON t.id=i.target_file_id
           WHERE t.path=? AND s.path != t.path ORDER BY s.path, i.line""",
        (path,),
    ).fetchall()
    return [dict(r) for r in rows]


def _ref_sites(store: Store, path: str, symbol_names: set[str] | None) -> list[dict]:
    rows = store.conn.execute(
        """SELECT r.name, r.target_name, r.line, r.kind, r.confidence, r.method, s.path AS src
           FROM refs r JOIN files s ON s.id=r.file_id JOIN files t ON t.id=r.target_file_id
           WHERE t.path=? AND s.path != t.path ORDER BY s.path, r.line""",
        (path,),
    ).fetchall()
    out = []
    for r in rows:
        if symbol_names is not None and r["target_name"] not in symbol_names:
            continue
        out.append(dict(r))
    return out


def analyze_impact(
    store: Store,
    root: Path,
    *,
    paths: list[str] | None = None,
    symbol: str | None = None,
    diff: bool = False,
    depth: int = 2,
    include_tests: bool = True,
) -> dict:
    depth = max(1, min(int(depth), 5))
    source = "files"
    changed_lines: dict[str, list[int]] = {}
    deleted: list[str] = []
    diff_info: dict | None = None
    target_paths: list[str] = []

    if diff:
        source = "git-diff"
        diff_info = git_changes(root)
        if not diff_info["available"]:
            return {"error": diff_info["error"], "caveats": CAVEATS}
        target_paths = list(diff_info["paths"])
        changed_lines = diff_info["lines"]
        deleted = diff_info["deleted"]
    elif symbol:
        source = "symbol"
        found, candidates = _find_symbol(store, symbol)
        if not found:
            if candidates:
                return {"error": f"ambiguous symbol: {symbol}", "candidates": candidates,
                        "caveats": CAVEATS}
            return {"error": f"symbol not found in index: {symbol}", "caveats": CAVEATS}
        target_paths = [found["path"]]
    elif paths:
        try:
            target_paths = [_normalize_path(root, p) for p in paths]
        except (PermissionError, ValueError) as exc:
            return {"error": str(exc), "caveats": CAVEATS}
    else:
        return {"error": "provide paths, a symbol, or --diff", "caveats": CAVEATS}

    indexed = {r["path"] for r in store.all_files()}
    missing = [p for p in target_paths if p not in indexed]
    target_paths = [p for p in target_paths if p in indexed]

    symbols_in_targets = _symbols_in_files(store, target_paths)
    changed_symbols = symbols_in_targets
    if changed_lines:
        changed_symbols = [
            s for s in symbols_in_targets
            if any(s["start_line"] <= n <= s["end_line"] for n in changed_lines.get(s["path"], []))
        ]
    changed_symbol_names: dict[str, set[str]] = defaultdict(set)
    for s in changed_symbols:
        changed_symbol_names[s["path"]].add(s["name"])

    # Direct dependents: static importers plus resolved reference sites.
    direct: dict[str, dict] = {}
    for p in target_paths:
        for imp in _importers(store, p):
            entry = direct.setdefault(imp["src"], {"path": imp["src"], "reasons": [],
                                                   "confidences": set()})
            entry["reasons"].append({
                "relation": "imports-changed-file", "target": p,
                "line": imp["line"], "module": imp["module"],
                "method": imp["method"], "confidence": imp["confidence"],
                "evidence": {"location": f"{imp['src']}:{imp['line']}"},
            })
            entry["confidences"].add(imp["confidence"])
        names = changed_symbol_names.get(p) if changed_lines else None
        for ref in _ref_sites(store, p, names):
            entry = direct.setdefault(ref["src"], {"path": ref["src"], "reasons": [],
                                                   "confidences": set()})
            entry["reasons"].append({
                "relation": "references-changed-symbol", "target": p, "symbol": ref["target_name"],
                "line": ref["line"], "reference_kind": ref["kind"],
                "method": ref["method"], "confidence": ref["confidence"],
                "evidence": {"location": f"{ref['src']}:{ref['line']}"},
            })
            entry["confidences"].add(ref["confidence"])

    def _conf(confidences: set[str]) -> str:
        return "confirmed" if confidences and confidences <= {"confirmed"} else "inferred"

    direct_list = []
    for entry in sorted(direct.values(), key=lambda e: e["path"]):
        direct_list.append({
            "path": entry["path"],
            "confidence": _conf(entry["confidences"]),
            "reasons": entry["reasons"][:12],
            "reason_count": len(entry["reasons"]),
            "evidence": entry["reasons"][0]["evidence"],
        })

    # Transitive dependents: reverse-import BFS. A path's confidence is the
    # weakest hop on it, and `via` is the whole chain back to a changed file,
    # not just the edge that happened to discover the node.
    edges = store.file_edges()
    reverse: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        reverse[e["dst"]].append(e)
    seen_depth = {p: 0 for p in target_paths}
    transitive: dict[str, dict] = {}
    queue = deque((p, 0, [], True) for p in target_paths)
    while queue:
        cur, d, path, all_confirmed = queue.popleft()
        if d >= depth:
            continue
        for e in reverse.get(cur, []):
            src = e["src"]
            if src in target_paths:
                continue
            hop_confirmed = all_confirmed and e["confidence"] == "confirmed"
            step = {"from": src, "to": cur, "line": e["line"], "method": e["method"],
                    "confidence": e["confidence"]}
            new_path = [step, *path]
            new_depth = d + 1
            previous = seen_depth.get(src)
            if previous is not None:
                if previous < new_depth:
                    continue
                # Same depth: an equal-length path with stronger confidence
                # replaces the recorded one and propagates the improvement.
                if previous == new_depth:
                    entry = transitive.get(src)
                    if entry is None or entry["all_confirmed"] or not hop_confirmed:
                        continue
                    entry["all_confirmed"] = hop_confirmed
                    entry["chain"] = new_path
                    queue.append((src, new_depth, new_path, hop_confirmed))
                    continue
            seen_depth[src] = new_depth
            transitive[src] = {"path": src, "depth": new_depth, "chain": new_path,
                               "all_confirmed": hop_confirmed}
            queue.append((src, new_depth, new_path, hop_confirmed))

    transitive_list = [{
        "path": v["path"], "depth": v["depth"],
        "confidence": "confirmed" if v["all_confirmed"] else "inferred",
        "via": v["chain"],
        "evidence": {"location": f"{v['chain'][-1]['from']}:{v['chain'][-1]['line']}"},
    } for v in sorted(transitive.values(), key=lambda x: (x["depth"], x["path"]))]
    transitive_list = [t for t in transitive_list if t["path"] not in direct]

    related_tests: list[dict] = []
    reach: dict[str, dict] = {}
    if include_tests:
        test_rows = [dict(r) for r in store.conn.execute(
            "SELECT path FROM files WHERE is_test=1 ORDER BY path"
        ).fetchall()]
        test_rows = [r for r in test_rows if _is_test_module(r["path"])]
        changed_stems = {_stem(p) for p in target_paths if _stem(p)}
        dependent_stems = {_stem(d["path"]) for d in direct_list}
        included: dict[str, dict] = {}
        importer_map: dict[str, list[dict]] = defaultdict(list)
        for e in edges:
            importer_map[e["dst"]].append(e)
        test_paths = {row["path"] for row in test_rows}
        # A test often reaches a changed file through intermediate modules: the
        # test imports the package, the package imports the changed file. Direct
        # import rules miss that. Follow importers up to a bounded depth for test
        # files only: tests are the leaves a user runs, and --depth controls the
        # dependent listing, not test discovery.
        seen_reach = set(target_paths)
        frontier = list(target_paths)
        for hop in range(1, 6):
            next_frontier: list[str] = []
            for dst in frontier:
                for e in importer_map.get(dst, []):
                    src = e["src"]
                    if src in test_paths and src not in reach:
                        reach[src] = {"depth": hop, "line": e["line"], "via": dst}
                    if src not in seen_reach:
                        seen_reach.add(src)
                        next_frontier.append(src)
            frontier = next_frontier
            if not frontier:
                break
        for row in test_rows:
            tp = row["path"]
            entry = included.setdefault(tp, {"path": tp, "rules": [], "confidences": set()})
            for p in target_paths:
                for e in importer_map.get(p, []):
                    if e["src"] == tp:
                        entry["rules"].append({
                            "rule": "test-imports-changed-file", "target": p,
                            "line": e["line"], "method": e["method"],
                            "confidence": "confirmed",
                            "evidence": {"location": f"{tp}:{e['line']}"},
                        })
                        entry["confidences"].add("confirmed")
            if _stem(tp) in changed_stems:
                entry["rules"].append({
                    "rule": "test-name-matches-changed-file",
                    "confidence": "inferred",
                    "evidence": {"location": tp, "method": "path-name-convention"},
                })
                entry["confidences"].add("inferred")
            if _stem(tp) in dependent_stems:
                entry["rules"].append({
                    "rule": "test-name-matches-dependent",
                    "confidence": "inferred",
                    "evidence": {"location": tp, "method": "path-name-convention"},
                })
                entry["confidences"].add("inferred")
        related_tests = [{
            "path": v["path"],
            "confidence": _conf(v["confidences"]),
            "rules": v["rules"],
            "evidence": v["rules"][0]["evidence"],
        } for v in sorted(included.values(), key=lambda x: x["path"]) if v["rules"]][:50]

    affected = target_paths + [d["path"] for d in direct_list] + [t["path"] for t in transitive_list]
    marks = ",".join("?" * len(affected)) if affected else "''"
    route_rows = store.conn.execute(
        f"""SELECT r.method,r.path,r.handler,r.line,r.framework,f.path AS file
            FROM routes r JOIN files f ON f.id=r.file_id
            WHERE f.path IN ({marks}) ORDER BY f.path, r.line LIMIT 100""",
        affected,
    ).fetchall()
    affected_routes = [{
        "method": r["method"], "path": r["path"], "handler": r["handler"],
        "file": r["file"], "line": r["line"],
        "confidence": "heuristic",
        "reason": "route-defined-in-changed-or-dependent-file",
        "evidence": {"extractor": r["framework"], "location": f"{r['file']}:{r['line']}"},
    } for r in route_rows]

    model_rows = store.conn.execute(
        f"""SELECT s.name,s.qualified_name,s.kind,f.path,s.start_line
            FROM symbols s JOIN files f ON f.id=s.file_id
            WHERE s.tags LIKE '%db_model%' AND f.path IN ({marks})
            ORDER BY f.path, s.start_line LIMIT 100""",
        affected,
    ).fetchall()
    related_models = [{
        "name": m["name"], "qualified_name": m["qualified_name"], "kind": m["kind"],
        "path": m["path"], "line": m["start_line"],
        "confidence": "heuristic",
        "reason": "model-defined-in-changed-or-dependent-file",
        "evidence": {"method": "base-class-name-heuristic",
                     "location": f"{m['path']}:{m['start_line']}"},
    } for m in model_rows]

    # Explicit blind spots, not silent omissions.
    blind: list[dict] = []
    all_unresolved = store.conn.execute(
        "SELECT COUNT(*) FROM imports WHERE kind='unresolved'"
    ).fetchone()[0]
    if target_paths:
        marks_t = ",".join("?" * len(target_paths))
        unres = store.conn.execute(
            f"""SELECT f.path, i.line, i.module, i.note FROM imports i JOIN files f ON f.id=i.file_id
                WHERE f.path IN ({marks_t}) AND i.kind='unresolved' ORDER BY f.path, i.line""",
            target_paths,
        ).fetchall()
        dyn = store.conn.execute(
            f"""SELECT f.path, i.line, i.module FROM imports i JOIN files f ON f.id=i.file_id
                WHERE f.path IN ({marks_t}) AND i.kind='dynamic' ORDER BY f.path, i.line""",
            target_paths,
        ).fetchall()
        ext = store.conn.execute(
            f"""SELECT DISTINCT i.module FROM imports i JOIN files f ON f.id=i.file_id
                WHERE f.path IN ({marks_t}) AND i.kind='external' ORDER BY i.module LIMIT 30""",
            target_paths,
        ).fetchall()
        errs = store.conn.execute(
            f"SELECT path, parse_error FROM files WHERE parsed=0 AND path IN ({marks_t})",
            target_paths,
        ).fetchall()
        if unres:
            blind.append({"kind": "unresolved-internal-imports", "count": len(unres),
                          "message": "Imports that look internal but could not be resolved; dependencies through them are unknown.",
                          "items": [{"file": r["path"], "line": r["line"], "module": r["module"],
                                     "note": r["note"]} for r in unres[:20]]})
        if all_unresolved:
            blind.append({"kind": "repo-unresolved-imports", "count": all_unresolved,
                          "message": "Repository-wide unresolved imports can hide paths into the changed files."})
        if dyn:
            blind.append({"kind": "dynamic-imports", "count": len(dyn),
                          "message": "Dynamic imports were resolved syntactically but their runtime targets may differ.",
                          "items": [{"file": r["path"], "line": r["line"], "module": r["module"]}
                                    for r in dyn[:20]]})
        if ext:
            blind.append({"kind": "external-imports", "count": len(ext),
                          "message": "External packages were not analyzed; only their local import sites are known.",
                          "items": [r["module"] for r in ext]})
        if errs:
            blind.append({"kind": "parse-errors", "count": len(errs),
                          "message": "Files that failed to parse contribute no symbols or edges.",
                          "items": [{"file": r["path"], "error": r["parse_error"]} for r in errs]})
        unreached_tests = sorted(set(reach) - {t["path"] for t in related_tests})
        if unreached_tests:
            blind.append({
                "kind": "test-selection-reachability",
                "count": len(unreached_tests),
                "message": ("Test files reachable through dependent modules but not in the "
                            "selected list. The list is a selection, not the full impact; run "
                            "these or the suite before trusting it."),
                "items": unreached_tests[:50],
            })
        no_dep = [p for p in target_paths if not _importers(store, p)]
        if no_dep:
            blind.append({"kind": "no-static-dependents", "count": len(no_dep),
                          "message": "No static dependents were found. The code may still be used dynamically, as an entry point, or outside this repository.",
                          "items": no_dep})
    repo_dynamic = store.conn.execute(
        "SELECT COUNT(*) FROM imports WHERE kind='dynamic'"
    ).fetchone()[0]
    if repo_dynamic:
        blind.append({"kind": "repo-dynamic-imports", "count": repo_dynamic,
                      "message": "Dynamic imports exist in the repository; their runtime targets may include the changed files."})
    repo_parse_errors = store.conn.execute(
        "SELECT COUNT(*) FROM files WHERE parsed=0"
    ).fetchone()[0]
    if repo_parse_errors:
        blind.append({"kind": "repo-parse-errors", "count": repo_parse_errors,
                      "message": "Files with parse errors contribute no symbols or edges anywhere in the index."})
    if deleted:
        blind.append({"kind": "deleted-files", "count": len(deleted),
                      "message": "Deleted files have no current symbols; impact is based on remaining importers only.",
                      "items": deleted[:20]})

    needles = {_stem(p) for p in target_paths if _stem(p)}
    needles |= {s["name"] for s in changed_symbols[:5]}
    docs = _doc_mentions(root, needles, limit=10)

    by_layer = defaultdict(int)
    for p in target_paths:
        by_layer[_classify_layer(p)] += 1

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "target": {
            "paths": target_paths,
            "symbols": [{
                "name": s["name"], "qualified_name": s["qualified_name"], "kind": s["kind"],
                "path": s["path"], "lines": [s["start_line"], s["end_line"]],
                "changed_by_hunk": s["id"] in {x["id"] for x in changed_symbols},
                "evidence": {"location": f"{s['path']}:{s['start_line']}"},
            } for s in changed_symbols[:200]],
            "changed_lines": changed_lines,
            "deleted": deleted,
            "missing_from_index": missing,
            "diff": {k: v for k, v in (diff_info or {}).items() if k in ("untracked",)} if diff_info else None,
        },
        "changed_files": target_paths,
        "direct_dependents": direct_list,
        "transitive_dependents": transitive_list[:200],
        "related_tests": related_tests,
        "affected_routes": affected_routes,
        "related_models": related_models,
        "architecture": {
            "layers": dict(by_layer),
            "documentation_mentions": docs,
            "note": "Documentation matches are lexical and only point to where a concept is discussed.",
        },
        "blind_spots": blind,
        "caveats": CAVEATS,
        "summary": {
            "changed_files": len(target_paths),
            "changed_symbols": len(changed_symbols),
            "direct_dependents": len(direct_list),
            "transitive_dependents": len(transitive_list),
            "related_tests": len(related_tests),
            "affected_routes": len(affected_routes),
            "related_models": len(related_models),
            "completeness": "partial" if blind else "partial-static",
            "confidence_counts": {
                "confirmed": sum(1 for d in direct_list if d["confidence"] == "confirmed"),
                "inferred": sum(1 for d in direct_list if d["confidence"] == "inferred"),
            },
        },
    }
