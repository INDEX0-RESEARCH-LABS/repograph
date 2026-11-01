"""Read-side queries: search, dependency graph, cycles, architecture."""

from __future__ import annotations

import os
import posixpath
import re
from collections import defaultdict, deque
from pathlib import Path

from .config import Settings
from .scanner import scan
from .store import Store

MAX_DOC_BYTES = 400_000
LAYER_RULES = [
    ("tests", re.compile(r"(^|/)(tests?|__tests__|specs?|e2e)(/|$)|(^|/)(test_|conftest)|\.(test|spec)\.")),
    ("api", re.compile(r"(^|/)(api|routes?|controllers?|endpoints?|handlers?|graphql|rpc)(\.\w+)?(/|$)")),
    ("data", re.compile(r"(^|/)(models?|entities|schema|schemas|migrations?|db|database|storage|repositories)(\.\w+)?(/|$)")),
    ("ui", re.compile(r"(^|/)(ui|components?|pages?|views?|screens?|layouts?|styles?|hooks)(\.\w+)?(/|$)")),
    ("infra", re.compile(r"(^|/)(infra|deploy|docker|k8s|terraform|scripts?|ci|config|settings)(\.\w+)?(/|$)")),
    ("domain", re.compile(r"(^|/)(core|domain|services?|lib|utils?|common|shared|internal|app)(\.\w+)?(/|$)")),
]


def _dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def search_symbols(store: Store, query: str, *, kind: str | None = None,
                   limit: int = 20, path_prefix: str | None = None) -> list[dict]:
    q = query.strip()
    if not q:
        return []
    like = "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    sql = (
        "SELECT s.id,s.name,s.qualified_name,s.kind,s.start_line,s.end_line,s.tags,f.path "
        "FROM symbols s JOIN files f ON f.id=s.file_id "
        "WHERE (lower(s.name) LIKE ? ESCAPE '\\' OR lower(s.qualified_name) LIKE ? ESCAPE '\\')"
    )
    params: list[object] = [like, like]
    if kind:
        sql += " AND s.kind=?"
        params.append(kind)
    if path_prefix:
        sql += " AND f.path LIKE ?"
        params.append(path_prefix.rstrip("/") + "%")
    sql += " LIMIT 500"
    rows = _dicts(store.conn.execute(sql, params).fetchall())
    low = q.lower()

    def score(row: dict) -> tuple:
        name = row["name"].lower()
        qn = row["qualified_name"].lower()
        if name == low:
            base = 100
        elif name.startswith(low):
            base = 80
        elif low in name:
            base = 60
        elif low in qn:
            base = 40
        else:
            base = 10
        if row["kind"] in ("class", "function", "model", "interface"):
            base += 3
        return (-base, len(row["qualified_name"]), row["path"])

    rows.sort(key=score)
    out = []
    for r in rows[:limit]:
        out.append({
            "name": r["name"],
            "qualified_name": r["qualified_name"],
            "kind": r["kind"],
            "path": r["path"],
            "lines": [r["start_line"], r["end_line"]],
            "tags": [t for t in r["tags"].split(",") if t],
            "evidence": {"extractor": "tree-sitter", "location": f"{r['path']}:{r['start_line']}"},
        })
    return out


def _doc_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for name in ("README.md", "ARCHITECTURE.md", "AGENTS.md", "CONTRIBUTING.md"):
        p = root / name
        if p.is_file():
            candidates.append(p)
    for sub in ("docs", "doc", "adr", "decisions"):
        d = root / sub
        if d.is_dir():
            for dirpath, dirnames, filenames in os.walk(d):
                dirnames[:] = [x for x in dirnames if x not in (".git", "node_modules", "images", "assets")]
                for fn in filenames:
                    if fn.lower().endswith((".md", ".mdx", ".rst", ".txt")):
                        candidates.append(Path(dirpath, fn))
                if len(candidates) > 80:
                    break
    return candidates


def text_search(root: Path, store: Store, query: str, *, limit: int = 20,
                case_sensitive: bool = False) -> list[dict]:
    needle = query if case_sensitive else query.lower()
    if not needle:
        return []
    tokens = [t for t in re.split(r"[^\w-]+", needle) if t]
    hits: list[dict] = []

    def scan_file(full: Path, rel: str, kind: str) -> None:
        nonlocal hits
        try:
            if full.stat().st_size > MAX_DOC_BYTES:
                return
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        per_file = 0
        for lineno, line in enumerate(text.splitlines(), start=1):
            hay = line if case_sensitive else line.lower()
            matched = (all(tok in hay for tok in tokens) if len(tokens) > 1 else needle in hay)
            if not matched:
                continue
            hits.append({
                "path": rel,
                "line": lineno,
                "text": line.strip()[:240],
                "kind": kind,
                "evidence": {"method": "text-scan", "location": f"{rel}:{lineno}"},
            })
            per_file += 1
            if per_file >= 3 or len(hits) >= limit:
                return

    for row in store.conn.execute("SELECT path FROM files ORDER BY path").fetchall():
        scan_file(root / row["path"], row["path"], "source")
        if len(hits) >= limit:
            return hits
    for doc in _doc_files(root):
        try:
            rel = doc.relative_to(root).as_posix()
        except ValueError:
            continue
        scan_file(doc, rel, "docs")
        if len(hits) >= limit:
            break
    return hits


def search(store: Store, root: Path, query: str, *, limit: int = 20,
           related: bool = False) -> dict:
    symbols = search_symbols(store, query, limit=limit)
    text = text_search(root, store, query, limit=limit)
    result: dict = {"query": query, "symbols": symbols, "text": text}
    if related:
        paths = list(dict.fromkeys([s["path"] for s in symbols] + [t["path"] for t in text]))
        rel: list[dict] = []
        edges = store.file_edges()
        for p in paths:
            for e in edges:
                if e["dst"] == p:
                    rel.append({"path": e["src"], "relation": "imported-by", "target": p,
                                "evidence": {"line": e["line"], "method": e["method"],
                                             "confidence": e["confidence"]}})
                elif e["src"] == p:
                    rel.append({"path": e["dst"], "relation": "imports", "target": p,
                                "evidence": {"line": e["line"], "method": e["method"],
                                             "confidence": e["confidence"]}})
        seen = set()
        deduped = []
        for r in rel:
            key = (r["path"], r["relation"], r["target"])
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        result["related_files"] = deduped[:limit]
    return result


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------

def _adjacency(edges: list[dict]) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    forward: dict[str, list[dict]] = defaultdict(list)
    reverse: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        forward[e["src"]].append(e)
        reverse[e["dst"]].append(e)
    return forward, reverse


def dependency_graph(store: Store, *, path: str | None = None, direction: str = "both",
                     depth: int = 1, max_nodes: int = 2000) -> dict:
    edges = store.file_edges()
    forward, reverse = _adjacency(edges)
    if path is None:
        nodes = sorted({e["src"] for e in edges} | {e["dst"] for e in edges})
        out_edges = edges
    else:
        depth = max(1, min(depth, 10))
        seen = {path: 0}
        queue = deque([(path, 0)])
        out_edges: list[dict] = []
        edge_keys = set()
        while queue:
            cur, d = queue.popleft()
            if d >= depth:
                continue
            nexts = []
            if direction in ("in", "both"):
                nexts.extend(reverse.get(cur, []))
            if direction in ("out", "both"):
                nexts.extend(forward.get(cur, []))
            for e in nexts:
                key = (e["src"], e["dst"], e["line"])
                if key not in edge_keys:
                    edge_keys.add(key)
                    out_edges.append(e)
                other = e["src"] if e["dst"] == cur else e["dst"]
                if other not in seen:
                    seen[other] = d + 1
                    queue.append((other, d + 1))
        nodes = sorted(seen)
        if len(nodes) > max_nodes:
            nodes = nodes[:max_nodes]
            out_edges = [e for e in out_edges if e["src"] in nodes and e["dst"] in nodes]
    return {
        "nodes": nodes,
        "edges": [
            {"from": e["src"], "to": e["dst"], "confidence": e["confidence"],
             "method": e["method"], "line": e["line"],
             "evidence": {"location": f"{e['src']}:{e['line']}"}}
            for e in out_edges
        ],
        "truncated": len(out_edges) >= 5000,
        "note": "Only statically resolved imports are shown; external and dynamic imports are excluded.",
    }


def find_cycles(store: Store, limit: int = 50) -> list[list[str]]:
    """Strongly connected components with more than one file (Kosaraju)."""
    edges = store.file_edges()
    nodes = {e["src"] for e in edges} | {e["dst"] for e in edges}
    adj: dict[str, list[str]] = defaultdict(list)
    radj: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        adj[e["src"]].append(e["dst"])
        radj[e["dst"]].append(e["src"])

    visited: set[str] = set()
    order: list[str] = []
    for start in nodes:
        if start in visited:
            continue
        stack = [(start, iter(adj.get(start, [])))]
        visited.add(start)
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if nxt not in visited:
                    visited.add(nxt)
                    stack.append((nxt, iter(adj.get(nxt, []))))
                    advanced = True
                    break
            if not advanced:
                order.append(node)
                stack.pop()

    assigned: set[str] = set()
    comps: list[list[str]] = []
    for start in reversed(order):
        if start in assigned:
            continue
        comp = []
        stack = [start]
        assigned.add(start)
        while stack:
            n = stack.pop()
            comp.append(n)
            for nxt in radj.get(n, []):
                if nxt not in assigned:
                    assigned.add(nxt)
                    stack.append(nxt)
        if len(comp) > 1:
            comps.append(sorted(comp))
    comps.sort(key=lambda c: (len(c), c), reverse=True)
    return comps[:limit]


# --------------------------------------------------------------------------
# References
# --------------------------------------------------------------------------

def find_references(store: Store, query: str, *, limit: int = 100) -> dict:
    q = query.strip()
    defs = _dicts(store.conn.execute(
        """SELECT s.*, f.path FROM symbols s JOIN files f ON f.id=s.file_id
           WHERE s.qualified_name=? OR s.name=? ORDER BY s.qualified_name LIMIT 50""",
        (q, q),
    ).fetchall())
    if not defs:
        defs = _dicts(store.conn.execute(
            """SELECT s.*, f.path FROM symbols s JOIN files f ON f.id=s.file_id
               WHERE s.qualified_name LIKE ? ORDER BY length(s.qualified_name) LIMIT 50""",
            ("%" + q,),
        ).fetchall())

    definitions = [{
        "path": d["path"], "name": d["name"], "qualified_name": d["qualified_name"],
        "kind": d["kind"], "lines": [d["start_line"], d["end_line"]],
        "evidence": {"method": "symbol-definition", "location": f"{d['path']}:{d['start_line']}"},
    } for d in defs]

    refs: list[dict] = []
    if defs:
        pairs = {(d["path"], d["name"]) for d in defs}
        rows = store.conn.execute(
            """SELECT r.name,r.target_name,r.line,r.kind,r.confidence,r.method,f.path AS ref_path,
                      tf.path AS target_path
               FROM refs r JOIN files f ON f.id=r.file_id
               LEFT JOIN files tf ON tf.id=r.target_file_id
               WHERE r.target_file_id IS NOT NULL ORDER BY r.line LIMIT 5000"""
        ).fetchall()
        for r in rows:
            if (r["target_path"], r["target_name"]) in pairs:
                refs.append({
                    "path": r["ref_path"], "line": r["line"], "kind": r["kind"],
                    "confidence": r["confidence"], "method": r["method"],
                    "target": f"{r['target_path']}:{r['name']}",
                    "evidence": {"location": f"{r['ref_path']}:{r['line']}",
                                 "extractor": r["method"], "confidence": r["confidence"]},
                })
    return {
        "query": q,
        "definitions": definitions,
        "references": refs[:limit],
        "references_truncated": len(refs) > limit,
        "note": "References are statically resolved call/inheritance sites; reflective or dynamic uses are not included.",
    }


# --------------------------------------------------------------------------
# Architecture
# --------------------------------------------------------------------------

def _classify_layer(path: str) -> str:
    for name, rx in LAYER_RULES:
        if rx.search(path):
            return name
    return "other"


def _doc_mentions(root: Path, needles: set[str], limit: int = 20) -> list[dict]:
    if not needles:
        return []
    candidates = _doc_files(root)
    out: list[dict] = []
    for p in candidates[:80]:
        try:
            if p.stat().st_size > MAX_DOC_BYTES:
                continue
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = p.relative_to(root).as_posix()
        for lineno, line in enumerate(lines, start=1):
            low = line.lower()
            for needle in needles:
                if needle and needle.lower() in low:
                    out.append({"path": rel, "line": lineno, "excerpt": line.strip()[:220],
                                "matched": needle,
                                "evidence": {"method": "documentation-text-match",
                                             "location": f"{rel}:{lineno}"}})
                    break
            if len(out) >= limit:
                return out
    return out


def architecture_summary(store: Store, root: Path) -> dict:
    stats = store.stats()
    files = store.all_files()
    edges = store.file_edges()
    # The edge count is only as complete as the resolved imports. Report the
    # imports that were classified but not turned into edges, so the summary
    # does not read as a census.
    unresolved = store.conn.execute(
        "SELECT COUNT(*) FROM imports WHERE kind='unresolved'").fetchone()[0]
    dynamic = store.conn.execute(
        "SELECT COUNT(*) FROM imports WHERE kind='dynamic'").fetchone()[0]
    in_deg: dict[str, int] = defaultdict(int)
    out_deg: dict[str, int] = defaultdict(int)
    for e in edges:
        in_deg[e["dst"]] += 1
        out_deg[e["src"]] += 1

    layers: dict[str, int] = defaultdict(int)
    for f in files:
        layers[_classify_layer(f["path"])] += 1

    top_dirs: dict[str, dict] = {}
    for f in files:
        top = f["path"].split("/")[0] if "/" in f["path"] else "."
        entry = top_dirs.setdefault(top, {"files": 0, "inbound": 0, "outbound": 0})
        entry["files"] += 1
        entry["inbound"] += in_deg.get(f["path"], 0)
        entry["outbound"] += out_deg.get(f["path"], 0)

    entry_names = {"main.py", "__main__.py", "app.py", "cli.py", "server.py", "manage.py",
                   "index.ts", "main.ts", "server.ts", "index.js", "app.js", "mod.rs"}
    entries = [f["path"] for f in files if posixpath.basename(f["path"]) in entry_names]

    routes = _dicts(store.conn.execute(
        """SELECT r.method,r.path,r.handler,r.line,r.framework,r.confidence,f.path AS file
           FROM routes r JOIN files f ON f.id=r.file_id ORDER BY f.path, r.line LIMIT 300"""
    ).fetchall())
    models = _dicts(store.conn.execute(
        """SELECT s.name,s.qualified_name,s.kind,f.path,s.start_line FROM symbols s
           JOIN files f ON f.id=s.file_id WHERE s.tags LIKE '%db_model%'
           ORDER BY f.path, s.start_line LIMIT 300"""
    ).fetchall())

    hubs = sorted(
        ({"path": p, "inbound": n, "outbound": out_deg.get(p, 0)} for p, n in in_deg.items()),
        key=lambda x: (-x["inbound"], x["path"]),
    )[:10]

    return {
        "root": stats.get("root"),
        "indexed_at": stats.get("indexed_at"),
        "files": stats["files"],
        "symbols": stats["symbols"],
        "internal_edges": len(edges),
        "unresolved_imports": unresolved,
        "dynamic_imports": dynamic,
        "languages": stats["languages"],
        "symbol_kinds": stats["symbol_kinds"],
        "layers": dict(sorted(layers.items(), key=lambda kv: -kv[1])),
        "top_directories": dict(sorted(top_dirs.items(), key=lambda kv: -kv[1]["files"])),
        "dependency_hubs": hubs,
        "entry_points": entries[:50],
        "http_routes": [{
            "method": r["method"], "path": r["path"], "handler": r["handler"],
            "file": r["file"], "line": r["line"], "framework": r["framework"],
            "confidence": r["confidence"],
            "evidence": {"extractor": r["framework"], "location": f"{r['file']}:{r['line']}"},
        } for r in routes],
        "database_models": [{
            "name": m["name"], "qualified_name": m["qualified_name"], "kind": m["kind"],
            "path": m["path"], "line": m["start_line"],
            "confidence": "heuristic",
            "evidence": {"method": "base-class-name-heuristic",
                         "location": f"{m['path']}:{m['start_line']}"},
        } for m in models],
        "parse_errors": _dicts(store.conn.execute(
            "SELECT path,parse_error FROM files WHERE parsed=0 ORDER BY path LIMIT 50"
        ).fetchall()),
        "limitations": [
            "Layer names are path heuristics, not framework semantics.",
            "Routes and models are detected from decorator/base-class patterns; other frameworks are not recognized.",
            "Only statically resolvable imports are counted. Dynamic imports, reflection and runtime DI are not.",
            "`internal_edges` is a resolved-import count, not a census: unresolved and dynamic imports are reported separately and can hide real dependencies.",
        ],
    }


def quick_status(store: Store, settings: Settings) -> dict:
    stats = store.stats()
    existing = store.existing_files()
    scanned = {e.path: e for e in scan(settings.root, settings).files}
    added = len(set(scanned) - set(existing))
    deleted = len(set(existing) - set(scanned))
    changed = sum(
        1 for p, e in scanned.items()
        if p in existing and (e.size != existing[p].size or e.mtime != existing[p].mtime)
    )
    return {
        **stats,
        "parse_error_files": _dicts(store.conn.execute(
            "SELECT path, parse_error FROM files WHERE parsed=0 ORDER BY path LIMIT 50"
        ).fetchall()),
        "db_bytes": sum(p.stat().st_size for p in (settings.db_path, Path(str(settings.db_path) + "-wal")) if p.exists()),
        "stale": {"added": added, "changed": changed, "deleted": deleted},
        "needs_reindex": bool(added or deleted or changed),
    }
