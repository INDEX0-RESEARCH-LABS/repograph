#!/usr/bin/env python3
"""Independent ground truth via Python ast module + regex JS parser.

This deliberately avoids RepoGraph's resolver entirely:
- Python: use ast.parse() to walk ImportFrom/Import nodes, then resolve
  the dotted name to a file path using only stdlib logic.
- JS/TS: regex over import/require statements, then path.resolve() logic.

Outputs: gt2.json  — same shape as ground_truth.json
"""
import ast
import json
import os
import re
from pathlib import Path

REPOS = {
    "django": Path("/tmp/opencode/compare/repos/django"),
    "esbuild": Path("/tmp/opencode/compare/repos/esbuild"),
    "koa":    Path("/tmp/opencode/compare/repos/koa"),
}

SELECTED = {
    "django": [
        "django/db/__init__.py", "django/db/models/__init__.py",
        "django/core/exceptions.py", "django/conf/__init__.py",
        "django/utils/translation/__init__.py",
        "django/conf/locale/es_AR/__init__.py",
        "django/contrib/sites/shortcuts.py", "django/utils/version.py",
        "django/conf/locale/ta/formats.py", "django/template/backends/base.py",
    ],
    "esbuild": [
        "scripts/esbuild.js", "compat-table/src/index.ts",
        "lib/shared/types.ts", "lib/npm/node-platform.ts",
        "lib/shared/common.ts", "lib/shared/uint8array_json_parser.ts",
        "compat-table/src/css_table.ts", "scripts/decorator-tests.js",
        "require/yarnpnp/in.mjs", "lib/shared/worker.ts",
    ],
    "koa": [
        "test-helpers/context.js", "lib/only.js", "lib/context.js",
        "lib/is-stream.js", "lib/search-params.js", "lib/application.js",
        "test-helpers/stream.js", "lib/request.js", "lib/response.js",
    ],
}

# ── Python ground truth via ast ────────────────────────────────────────────

def all_py_files(root: Path):
    for p in root.rglob("*.py"):
        if ".repograph" not in str(p):
            yield p.relative_to(root).as_posix()

def dotted_to_candidates(root: Path, dotted: str, is_init: bool) -> list[str]:
    """All file paths that the dotted name could refer to."""
    if is_init:
        mod = dotted  # e.g. "django.db"
    else:
        mod = dotted  # e.g. "django.db.models"
    parts = mod.split(".")
    candidates = []
    # As a module file: parts → path
    as_file = "/".join(parts) + ".py"
    candidates.append(as_file)
    # As a package __init__
    as_pkg = "/".join(parts) + "/__init__.py"
    candidates.append(as_pkg)
    return candidates

def py_imports_of(root: Path, src_rel: str) -> list[str]:
    """All module dotted names imported by src_rel (Python), via ast."""
    try:
        src = (root / src_rel).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=src_rel)
    except SyntaxError:
        return []
    imports = []
    pkg_parts = src_rel.replace(".py","").split("/")
    is_init = pkg_parts[-1] == "__init__"
    pkg = pkg_parts[:-1]  # package path list

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(("abs", alias.name, None))
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            mod = node.module or ""
            if level == 0:
                imports.append(("abs", mod, [a.name for a in node.names]))
            else:
                # Relative: resolve against package
                drop = level - 1
                base = pkg[:len(pkg)-drop] if drop else pkg
                full = ".".join(base + ([mod] if mod else []))
                imports.append(("abs", full, [a.name for a in node.names]))
    return imports

def resolve_py(root: Path, dotted: str, names: list | None, all_py: set) -> list[str]:
    """Resolve a Python module name to file path(s)."""
    parts = dotted.split(".")
    results = []
    # Try as direct file
    for cands in [
        "/".join(parts) + ".py",
        "/".join(parts) + "/__init__.py",
    ]:
        if cands in all_py:
            results.append(cands)
    # Also try each name as a submodule
    if names:
        for name in names:
            for cands in [
                "/".join(parts + [name]) + ".py",
                "/".join(parts + [name]) + "/__init__.py",
            ]:
                if cands in all_py and cands not in results:
                    results.append(cands)
    return results

def build_py_gt(root: Path, target_rel: str, all_py: set) -> list[str]:
    """Find all Python files that import target_rel."""
    # Determine dotted name of the target
    tgt_parts = target_rel.replace(".py","").split("/")
    is_init = tgt_parts[-1] == "__init__"
    if is_init:
        tgt_dotted = ".".join(tgt_parts[:-1])  # django.db
    else:
        tgt_dotted = ".".join(tgt_parts)  # django.utils.version

    importers = []
    for src in all_py:
        if src == target_rel:
            continue
        try:
            imps = py_imports_of(root, src)
        except Exception:
            continue
        for kind, mod, names in imps:
            resolved = resolve_py(root, mod, names, all_py)
            if target_rel in resolved:
                importers.append(src)
                break
    return sorted(importers)

# ── JS/TS ground truth via regex ───────────────────────────────────────────

TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

def all_js_files(root: Path):
    for ext in TS_EXTS:
        for p in root.rglob(f"*{ext}"):
            if ".repograph" not in str(p) and "node_modules" not in str(p):
                yield p.relative_to(root).as_posix()

# Match: require('...'), import '...', from '...', import('...')
_JS_IMPORT_RE = re.compile(
    r"""(?:require|import|from)\s*\(?\s*['"]([^'"]+)['"]\)?""",
    re.MULTILINE
)

def js_imports_of(root: Path, src_rel: str) -> list[str]:
    """Extract all import specifiers from a JS/TS file."""
    try:
        content = (root / src_rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [m.group(1) for m in _JS_IMPORT_RE.finditer(content)]

def resolve_js_spec(root: Path, src_rel: str, spec: str, all_js: set, pkg_main: dict) -> list[str]:
    """Resolve a JS import specifier to repo-relative file path(s)."""
    if not spec.startswith("."):
        # Bare specifier: check package.json main
        for pkg_dir, main in pkg_main.items():
            # spec == package name (e.g. 'koa')
            if spec == pkg_dir.split("/")[-1] or spec == "..":
                pass  # handled below via relative
        return []  # external or unresolvable bare spec

    src_dir = "/".join(src_rel.split("/")[:-1])
    import posixpath
    base = posixpath.normpath(posixpath.join(src_dir, spec))

    # Try direct
    if base in all_js:
        return [base]
    # With extensions
    for ext in TS_EXTS:
        cand = base + ext
        if cand in all_js:
            return [cand]
    # As index
    for ext in TS_EXTS:
        cand = base + "/index" + ext
        if cand in all_js:
            return [cand]
    return []

def _load_pkg_mains(root: Path) -> dict:
    """Map package_dir → resolved main file for packages in this repo."""
    result = {}
    for pjson in root.rglob("package.json"):
        if "node_modules" in str(pjson) or ".repograph" in str(pjson):
            continue
        try:
            d = json.loads(pjson.read_text(encoding="utf-8", errors="replace"))
            main = d.get("main")
            if main:
                pkg_dir = pjson.parent.relative_to(root).as_posix()
                result[pkg_dir] = main
        except Exception:
            pass
    return result

def _resolve_relative_up(root: Path, src_rel: str, spec: str, all_js: set) -> list[str]:
    """Handle '../..' style specs by resolving via package.json main."""
    import posixpath
    src_dir = "/".join(src_rel.split("/")[:-1])
    target_dir = posixpath.normpath(posixpath.join(src_dir, spec))
    # Check for package.json in that dir
    pjson = root / target_dir / "package.json"
    if pjson.exists():
        try:
            d = json.loads(pjson.read_text())
            main = d.get("main")
            if main:
                cand = posixpath.normpath(posixpath.join(target_dir, main))
                if cand in all_js:
                    return [cand]
                for ext in TS_EXTS:
                    c = cand + ext
                    if c in all_js:
                        return [c]
        except Exception:
            pass
    # Try as index
    for ext in TS_EXTS:
        cand = posixpath.normpath(posixpath.join(target_dir, "index" + ext))
        if cand in all_js:
            return [cand]
    return []

def build_js_gt(root: Path, target_rel: str, all_js: set) -> list[str]:
    """Find all JS/TS files that import target_rel."""
    target_stem = Path(target_rel).stem
    target_no_ext = re.sub(r'\.[^.]+$', '', target_rel)

    importers = []
    for src in all_js:
        if src == target_rel:
            continue
        specs = js_imports_of(root, src)
        matched = False
        for spec in specs:
            if not spec.startswith("."):
                continue  # skip bare specifiers in this method

            # Try normal resolution
            resolved = resolve_js_spec(root, src, spec, all_js, {})
            if target_rel in resolved:
                matched = True
                break

            # Try '../..' style (package.json main)
            if spec in ("..", "../..", "../../.."):
                resolved2 = _resolve_relative_up(root, src, spec, all_js)
                if target_rel in resolved2:
                    matched = True
                    break
        if matched:
            importers.append(src)
    return sorted(importers)

# ── Main ───────────────────────────────────────────────────────────────────

def main():
    gt2 = {}
    for repo, targets in SELECTED.items():
        root = REPOS[repo]
        gt2[repo] = {}

        if repo == "django":
            print(f"\nBuilding Python GT for {repo} (ast)...")
            all_py = set(all_py_files(root))
            print(f"  {len(all_py)} .py files")
            for target in targets:
                importers = build_py_gt(root, target, all_py)
                gt2[repo][target] = importers
                print(f"  {target}: {len(importers)} importers")
        else:
            print(f"\nBuilding JS/TS GT for {repo} (regex+path)...")
            all_js = set(all_js_files(root))
            print(f"  {len(all_js)} JS/TS files")
            for target in targets:
                importers = build_js_gt(root, target, all_js)
                gt2[repo][target] = importers
                print(f"  {target}: {len(importers)} importers")

    out = Path("/home/darion-dev/repograph/benchmarks/compare/gt2.json")
    out.write_text(json.dumps(gt2, indent=2))
    print(f"\nSaved: {out}")
    total = sum(len(v) for r in gt2.values() for v in r.values())
    print(f"Total GT2 edges: {total}")

if __name__ == "__main__":
    main()
