"""Static import resolution for Python, TypeScript and JavaScript.

Resolution is file-level and evidence-producing: each result records how the
target was found and how certain we are. Dynamic imports, reflection and
runtime wiring are *not* resolved; they are surfaced as blind spots instead.
"""

from __future__ import annotations

import json
import posixpath
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .extract import Import


def _ts_scope_patterns(data: dict, base_dir: str) -> list[str] | None:
    """`include`/`files` of a tsconfig, as repo-relative glob patterns.

    ``None`` means the config declares no scope, so TypeScript's default
    (everything under the config directory) applies. An explicitly empty
    ``files`` / ``include`` list means the config covers nothing.
    """
    key = "include" if "include" in data else "files" if "files" in data else None
    if key is None:
        return None
    value = data.get(key)
    raw = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [posixpath.normpath(posixpath.join(base_dir, str(v)))
            for v in raw if isinstance(v, str)]


def _read_tsconfig(path: Path) -> dict | None:
    try:
        data = json.loads(_strip_json_comments(path.read_text(encoding="utf-8", errors="replace")))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _overlay(base: dict, over: dict) -> dict:
    for key in ("baseurl_dir", "paths_dir", "paths", "scope"):
        if over.get(key) is not None:
            base[key] = over[key]
    return base


def _merge_tsconfig(root: Path, path: Path, seen: frozenset[Path]) -> dict | None:
    """Effective config after following relative `extends` chains.

    Parent options are the base; later array entries override earlier ones,
    and the child overrides all parents. `baseUrl` keeps the directory of the
    config that declared it, and includes/files become repo-relative so a
    parent's scope still matches the tree when inherited. Cycles and
    node_modules targets are skipped.
    """
    resolved = path.resolve()
    if resolved in seen:
        return None
    data = _read_tsconfig(resolved)
    if data is None:
        return None
    try:
        dir_rel = resolved.parent.relative_to(root).as_posix()
    except ValueError:
        return None
    if dir_rel == ".":
        dir_rel = ""

    merged: dict = {"baseurl_dir": None, "paths_dir": None, "paths": None, "scope": None}
    extends = data.get("extends")
    parents = [extends] if isinstance(extends, str) else extends if isinstance(extends, list) else []
    for ext in parents:
        if not isinstance(ext, str) or not ext.startswith("."):
            continue  # package specifier: node_modules, not project source
        base = resolved.parent / ext
        candidates = [base.with_name(base.name + ".json"), base] if base.suffix != ".json" else [base]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                candidate.resolve().relative_to(root)
            except ValueError:
                break
            if "node_modules" in candidate.parts:
                break
            parent = _merge_tsconfig(root, candidate, seen | {resolved})
            if parent is not None:
                merged = _overlay(merged, parent)
            break

    opts = data.get("compilerOptions", {})
    own: dict = {"baseurl_dir": None, "paths_dir": None, "paths": None, "scope": None}
    if isinstance(opts, dict):
        if "baseUrl" in opts:
            own["baseurl_dir"] = posixpath.normpath(posixpath.join(dir_rel, str(opts["baseUrl"])))
        paths = opts.get("paths")
        if isinstance(paths, dict):
            entries = []
            for pattern, targets in paths.items():
                if isinstance(targets, list):
                    entries.append((pattern, [str(t) for t in targets]))
            own["paths"] = entries
            own["paths_dir"] = dir_rel
    own["scope"] = _ts_scope_patterns(data, dir_rel)
    return _overlay(merged, own)



def _glob_match(pattern: str, path: str) -> bool:
    """Match a tsconfig include pattern against a repo-relative path."""
    pat = pattern[2:] if pattern.startswith("./") else pattern
    out: list[str] = []
    i = 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    rx = "".join(out)
    # A bare directory (`src`) covers everything below it.
    return re.fullmatch(rx, path) is not None or re.fullmatch(rx + "/.*", path) is not None


@dataclass
class ResolvedImport:
    raw: str
    module: str
    line: int
    target: str | None  # repo-relative path of resolved file
    confidence: str  # confirmed | inferred | unresolved
    method: str
    kind: str = "internal"  # internal | external | unresolved
    names: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""


PY_EXT = ".py"
TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
PY_STDLIB = set(sys.stdlib_module_names) | {"__future__"}
PY_PROJECT_MANIFESTS = ("pyproject.toml", "setup.py", "setup.cfg")
# Directories walked for project manifests and package.json files. Depth is a
# deliberate bound: deeper fixture packages tend to be named after real
# dependencies, and registering those globally would hijack real imports.
MANIFEST_MAX_DEPTH = 3
PACKAGE_MAX_DEPTH = 4
WALK_SKIP = ("node_modules", ".git", ".venv", "venv", "dist", "build",
             "coverage", "__pycache__", ".tox", ".mypy_cache")


def _strip_json_comments(text: str) -> str:
    """Remove // and /* */ comments without touching string contents.

    A regex over the raw text corrupts glob patterns: ``"@vue/*"`` contains
    ``/*`` and was truncated up to the ``*/`` inside ``./packages/*/src``,
    silently discarding tsconfig path aliases.
    """
    out: list[str] = []
    i, n = 0, len(text)
    in_string = escaped = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        out.append(ch)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


class Resolver:
    def __init__(self, root: Path, files: list[tuple[str, str]]) -> None:
        self.root = root
        self.files = {rel for rel, _ in files}
        self.lang = dict(files)
        self.py_modules: dict[str, str | None] = {}
        # Names reachable only via a project root or a conftest sys.path
        # mutation. They are runtime configuration, so they stay `inferred`.
        self.py_alt_modules: dict[str, tuple[str | None, str, str]] = {}
        self.ts_configs: list[dict] = []
        self.packages: dict[str, str] = {}
        self.package_dirs: dict[str, str] = {}
        self.package_imports: dict[str, dict] = {}
        # Every directory holding a package.json. Used to tell a package's own
        # self-reference from a nested app importing the same name from the
        # registry (measured zustand defect: examples pin `zustand ^5`).
        self.pkg_dirs: set[str] = set()
        # Package dirs that declare workspaces. Bare-name resolution may only
        # cross package boundaries inside one of these.
        self.workspace_roots: set[str] = set()
        self._dirs = {str(PurePosixPath(p).parent) for p in self.files}
        self._build_python_modules()
        self._build_python_roots()
        self._build_ts_configs()
        self._build_packages()

    # -- index construction -------------------------------------------------

    def _build_python_modules(self) -> None:
        for rel, lang in self.lang.items():
            if lang != "python":
                continue
            parts = rel.split("/")
            stem = parts[-1].rsplit(".", 1)[0]
            for alias in self._python_aliases(parts, stem):
                self.py_modules[alias] = None if alias in self.py_modules else rel
            if stem == "__init__":
                pkg = ".".join(parts[:-1])
                if pkg:
                    self.py_modules.setdefault(pkg, rel)
                # `import pkg` must bind the package, not `pkg.__init__`.
                if parts[0] in ("src", "lib", "python") and len(parts) > 2:
                    self.py_modules.setdefault(".".join(parts[1:-1]), rel)

    @staticmethod
    def _python_aliases(parts: list[str], stem: str) -> list[str]:
        aliases = []
        # Module name relative to the repository root.
        rel_mod = ".".join(parts[:-1] + [stem])
        aliases.append(rel_mod)
        # Module name relative to an `src`/`lib`/`python` source root.
        if parts and parts[0] in ("src", "lib", "python") and len(parts) > 1:
            aliases.append(".".join(parts[1:-1] + [stem]))
        # Module name relative to the top-most regular package.
        dirs = parts[:-1]
        start = None
        for i in range(len(dirs), 0, -1):
            if (Path(*dirs[:i]) / "__init__.py").is_file():
                start = i - 1
                break
        if start is not None:
            aliases.append(".".join(parts[start:-1] + [stem]))
        return list(dict.fromkeys(aliases))

    def _build_python_roots(self) -> None:
        """Register names that are importable only through a sys.path root.

        Two measured, evidence-bearing cases in Flask: example projects import
        their own top-level package (``flaskr``), and a conftest fixture calls
        ``syspath_prepend(tests/test_apps)``. Neither is importable from the
        repository root, so the root-relative alias map cannot see them.
        Names are registered only when unambiguous across the whole repo.
        """
        import os

        roots: list[tuple[str, str, str]] = []

        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in WALK_SKIP]
            rel_dir = Path(dirpath).relative_to(self.root).as_posix()
            depth = 0 if rel_dir == "." else rel_dir.count("/") + 1
            if depth >= MANIFEST_MAX_DEPTH:
                dirnames[:] = []
            if not any(m in filenames for m in PY_PROJECT_MANIFESTS):
                continue
            base = "" if rel_dir == "." else rel_dir
            src = posixpath.join(base, "src") if base else "src"
            if any(p.startswith(src + "/") and p.endswith(PY_EXT) for p in self.files):
                roots.append((src, "python-project-root",
                              f"src layout of the Python project at {base or '.'}"))
            else:
                roots.append((base or ".", "python-project-root",
                              f"Python project root {base or '.'}"))

        for rel, lang in self.lang.items():
            if lang != "python" or rel.rsplit("/", 1)[-1] != "conftest.py":
                continue
            try:
                text = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if "syspath_prepend(" not in line and "sys.path.insert(" not in line:
                    continue
                for name in re.findall(r'"([^"\n]+)"|\'([^\'\n]+)\'', line):
                    literal = name[0] or name[1]
                    cand = posixpath.normpath(posixpath.join(posixpath.dirname(rel), literal))
                    if cand.startswith("../") or not any(
                            p.startswith(cand + "/") for p in self.files):
                        continue
                    roots.append((cand, "python-syspath-root",
                                  f"conftest {rel} prepends {cand} to sys.path"))

        for root, method, note in dict.fromkeys(roots):
            prefix = "" if root == "." else root + "/"
            for rel, lang in self.lang.items():
                if lang != "python" or (prefix and not rel.startswith(prefix)):
                    continue
                parts = (rel[len(prefix):] if prefix else rel).split("/")
                stem = parts[-1][:-len(PY_EXT)]
                dotted = ".".join(parts[:-1] if stem == "__init__" else parts[:-1] + [stem])
                if not dotted:
                    continue
                if dotted in self.py_modules:
                    continue  # a root-relative alias already resolves this name
                current = self.py_alt_modules.get(dotted)
                if current is None:
                    self.py_alt_modules[dotted] = (rel, method, note)
                elif current[0] != rel:
                    self.py_alt_modules[dotted] = (
                        None, "ambiguous-python-root",
                        "the same import name is defined by more than one sys.path root",
                    )

    def _build_ts_configs(self) -> None:
        import os

        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in
                           ("node_modules", ".git", ".venv", "dist", "build", "coverage")]
            rel_dir = Path(dirpath).relative_to(self.root).as_posix()
            depth = 0 if rel_dir == "." else rel_dir.count("/") + 1
            if depth > 3:
                dirnames[:] = []
                continue
            if "tsconfig.json" not in filenames:
                continue
            cfg = Path(dirpath, "tsconfig.json")
            merged = _merge_tsconfig(self.root, cfg, frozenset())
            if merged is None:
                continue
            self.ts_configs.append({
                "dir": "" if rel_dir == "." else rel_dir,
                "baseurl_dir": merged["baseurl_dir"],
                "paths_dir": merged["paths_dir"],
                "paths": merged["paths"] or [],
                "scope": merged["scope"],
            })
        # Most specific config (deepest directory) wins.
        self.ts_configs.sort(key=lambda c: len(c["dir"]), reverse=True)

    @staticmethod
    def _ts_covers(cfg: dict, rel: str) -> bool:
        """Whether a tsconfig's `include`/`files` covers this file.

        No declared scope means the project's default include (everything
        under the config directory). An explicit empty list covers nothing.
        """
        scope = cfg.get("scope")
        if scope is None:
            return True
        return any(_glob_match(pattern, rel) for pattern in scope)

    def _nearest_pkg_dir(self, rel: str) -> str:
        d = posixpath.dirname(rel)
        while True:
            if d in self.pkg_dirs:
                return d
            if not d:
                return ""
            d = posixpath.dirname(d)

    def _package_visible_from(self, rel: str, name: str) -> bool:
        """Can `rel` see this package's source as `name`?

        True for a package importing itself, and across package boundaries only
        when the repository declares workspaces (npm/yarn `workspaces` or a
        pnpm workspace file). Nested demo apps that list the registry package in
        their own `dependencies` are otherwise a separate install.
        """
        target = self.package_dirs.get(name)
        if target is None:
            return False
        importer = self._nearest_pkg_dir(rel)
        if importer == target:
            return True
        for root in self.workspace_roots:
            if root == "" or importer == root or importer.startswith(root + "/"):
                return True
        return False

    @staticmethod
    def _condition_target(value, prefer_types: bool = False) -> str | None:
        """First usable target in an exports/imports condition object.

        ``types`` is tried last for value imports: for change impact we want
        the file that runs. Whole-module ``import type`` resolves the ``types``
        condition instead, which the audit showed is a different file.
        """
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            order = (("types", "source", "import", "module", "default", "require")
                     if prefer_types else
                     ("source", "import", "module", "default", "require", "types"))
            for key in order:
                if key in value:
                    found = Resolver._condition_target(value[key], prefer_types)
                    if found:
                        return found
            for item in value.values():
                found = Resolver._condition_target(item, prefer_types)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = Resolver._condition_target(item, prefer_types)
                if found:
                    return found
        return None

    def _entry_source_candidates(self, base: str, entry: str) -> list[str]:
        """Concrete files an entry field may denote, preferring source.

        Published entries point at build output (``dist/node/index.js``) that
        is absent from a source checkout; the file developers change is
        ``src/node/index.ts``. Generalising this also makes a package
        self-reference (``import "vite"`` inside Vite) resolvable.
        """
        cand = posixpath.normpath(posixpath.join(base, entry))
        cands = [cand]
        rel = posixpath.relpath(cand, base or ".")
        if rel.startswith("dist/"):
            stem = rel[len("dist/"):].rsplit(".", 1)[0]
            for ext in TS_EXTS:
                cands.append(posixpath.normpath(
                    posixpath.join(base, "src", stem + ext)))
        return cands

    def _build_packages(self) -> None:
        import os

        # pnpm declares workspaces in pnpm-workspace.yaml, but the file also
        # exists for settings only (zustand). Without a `packages:` key there
        # are no workspace members, so nested apps stay separate installs.
        for name in ("pnpm-workspace.yaml", "pnpm-workspace.yml"):
            ws = self.root / name
            if ws.is_file():
                try:
                    text = ws.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if re.search(r"^\s*packages\s*:", text, re.MULTILINE):
                    self.workspace_roots.add("")
                break

        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in WALK_SKIP]
            rel_dir = Path(dirpath).relative_to(self.root).as_posix()
            depth = 0 if rel_dir == "." else rel_dir.count("/") + 1
            if depth >= PACKAGE_MAX_DEPTH:
                dirnames[:] = []
            if "package.json" not in filenames:
                continue
            pkg_json = Path(dirpath, "package.json")
            rel = pkg_json.relative_to(self.root).as_posix()
            try:
                data = json.loads(_strip_json_comments(pkg_json.read_text(encoding="utf-8", errors="replace")))
            except (OSError, ValueError):
                continue
            base = posixpath.dirname(rel)
            self.pkg_dirs.add(base)
            if data.get("workspaces"):
                self.workspace_roots.add(base)
            imports = data.get("imports")
            if isinstance(imports, dict) and imports:
                self.package_imports[base] = imports
            name = data.get("name")
            if not isinstance(name, str) or not name:
                continue
            self.package_dirs[name] = base
            exports = data.get("exports")
            if isinstance(exports, str):
                main_export = exports
            elif isinstance(exports, dict):
                main_export = self._condition_target(exports.get("."))
            else:
                main_export = None
            entries = [data.get("source"), data.get("module"), data.get("main"),
                       main_export, "src/index.ts", "src/index.tsx", "src/index.js",
                       "index.ts", "index.js"]
            resolved = None
            for entry in entries:
                if not isinstance(entry, str) or not entry:
                    continue
                hit = next((c for c in self._entry_source_candidates(base, entry)
                            if c in self.files), None)
                if hit:
                    resolved = hit
                    break
            # If the published entry is build output, prefer the conventional
            # source entry over a stale top-level shim.
            published = f"{data.get('module') or ''} {data.get('main') or ''} {main_export or ''}"
            if resolved and "dist/" in published:
                for entry in ("src/index.ts", "src/index.tsx", "src/index.js"):
                    cand = posixpath.normpath(posixpath.join(base, entry))
                    if cand in self.files:
                        resolved = cand
                        break
            if resolved:
                self.packages[name] = resolved

    # -- Python -------------------------------------------------------------

    def _py_lookup(self, dotted: str) -> tuple[str | None, str, str, str]:
        # Only exact module paths. A suffix match such as ``types`` ->
        # ``fastapi.types`` is not how Python absolute imports bind, and it
        # produced false edges to same-named repository files (stdlib
        # collisions). Source-root aliases are already registered exactly.
        target = self.py_modules.get(dotted)
        if target:
            return target, "confirmed", "python-absolute-import", ""
        alt = self.py_alt_modules.get(dotted)
        if alt is None:
            return None, "unresolved", "python-absolute-import", ""
        target, method, note = alt
        if target is None:
            return None, "unresolved", method, note
        return target, "inferred", method, note

    def _package_of(self, rel: str) -> list[str]:
        parts = rel.split("/")[:-1]
        return parts

    def _resolve_python(self, rel: str, imp: Import) -> list[ResolvedImport]:
        out: list[ResolvedImport] = []
        method = "python-relative-import" if imp.level else "python-absolute-import"

        def file_for_parts(parts: list[str]) -> str | None:
            base = "/".join(parts)
            if not base:
                return None
            for cand in (base + ".py", base + "/__init__.py", base + ".pyi"):
                if cand in self.files:
                    return cand
            return None

        if imp.level:
            pkg = self._package_of(rel)
            drop = imp.level - 1
            if drop > len(pkg):
                return [ResolvedImport(imp.raw, imp.module, imp.line, None, "unresolved",
                                       method, "unresolved", imp.names,
                                       "relative import escapes the repository")]
            base_parts = (pkg[:-drop] if drop else pkg) + (imp.module.split(".") if imp.module else [])
            base_target = file_for_parts(base_parts)
            base_conf = "confirmed"
            base_note = ""
        else:
            base_parts = imp.module.split(".") if imp.module else []
            base = ".".join(base_parts)
            top = base_parts[0] if base_parts else ""
            # An absolute import of a stdlib name is external unless this
            # repository defines that exact top-level module (shadowing).
            if top in PY_STDLIB and top not in self.py_modules:
                return [ResolvedImport(imp.raw, imp.module, imp.line, None, "external",
                                       method, "external", imp.names,
                                       "standard library (absolute import)")]
            base_target, base_conf, lookup_method, base_note = (
                self._py_lookup(base) if base else (None, "unresolved", method, ""))
            method = lookup_method

        # `from pkg import submodule` where `submodule` is a module file.
        name_edges: list[ResolvedImport] = []
        resolved_names: set[str] = set()
        for imported, local in imp.names:
            if imported in ("*", ""):
                continue
            if imp.level:
                target = file_for_parts(base_parts + imported.split("."))
                conf, sub_method, note = "confirmed", method, ""
            else:
                dotted = ".".join([*base_parts, imported])
                target, conf, sub_method, note = self._py_lookup(dotted)
            if target:
                resolved_names.add(imported)
                if target != base_target:
                    name_edges.append(ResolvedImport(
                        imp.raw, f"{imp.module}.{imported}", imp.line, target,
                        conf, sub_method, "internal", [(imported, local)], note))

        # Emit the package `__init__` edge only when the import names the
        # package itself, or when a name is a package attribute rather than a
        # submodule (`from . import VERSION`). Otherwise `from . import mod`
        # produced a duplicate edge that labeling scored as a wrong target.
        meaningful = [n for n, _ in imp.names if n not in ("*", "")]
        if base_target and (imp.module or not meaningful
                            or any(n not in resolved_names for n in meaningful)):
            out.append(ResolvedImport(imp.raw, imp.module, imp.line, base_target, base_conf,
                                      method, "internal", imp.names, base_note))
        out.extend(name_edges)

        if out:
            return out
        top = base_parts[0] if base_parts else ""
        if not imp.level and (top in PY_STDLIB or top and not self._looks_internal(top)):
            return [ResolvedImport(imp.raw, imp.module, imp.line, None, "external", method,
                                   "external", imp.names, "third-party or standard library")]
        if not imp.level and top:
            return [ResolvedImport(imp.raw, imp.module, imp.line, None, "unresolved", method,
                                   "unresolved", imp.names,
                                   base_note or "top-level name matches repository content but module was not resolved")]
        return [ResolvedImport(imp.raw, imp.module, imp.line, None, "unresolved", method,
                               "unresolved", imp.names)]

    def _looks_internal(self, top: str) -> bool:
        if top in self._dirs or f"{top}.py" in self.files:
            return True
        return any(top in p.split("/") for p in self.files)

    # -- TypeScript / JavaScript -------------------------------------------

    def _ts_candidates(self, base: str) -> list[str]:
        base = posixpath.normpath(base)
        if base.startswith("../") or base == "..":
            return []
        cands = [base] if base in self.files else []
        if not cands:
            for ext in (*TS_EXTS, ".d.ts"):
                if base + ext in self.files:
                    cands.append(base + ext)
                    break
            if not cands:
                for ext in (*TS_EXTS, ".d.ts"):
                    idx = posixpath.normpath(posixpath.join(base, "index" + ext))
                    if idx in self.files:
                        cands.append(idx)
                        break
            if not cands and base.endswith((".js", ".jsx", ".mjs", ".cjs")):
                # ESM style: `./x.js` refers to `./x.ts` in TypeScript source.
                stem = base.rsplit(".", 1)[0]
                for ext in (".ts", ".tsx", ".mts", ".cts", ".d.ts"):
                    if stem + ext in self.files:
                        cands.append(stem + ext)
                        break
        return cands

    def _resolve_package_import(self, rel: str, spec: str, imp: Import) -> list[ResolvedImport]:
        """Resolve a Node ``#private`` specifier from the nearest ``imports`` map.

        ``imports`` maps are package-local and use mandatory ``#`` prefixes;
        they are ordinary static configuration, but the mapping lives in JSON
        outside the module, so the edge is reported as ``inferred``.
        """
        dirs = sorted(self.package_dirs.values(), key=len, reverse=True)
        pkg_dir = next((d for d in dirs if d == "" or rel.startswith(d + "/")), None)
        mapping = self.package_imports.get(pkg_dir) if pkg_dir is not None else None
        type_only = bool(re.match(r"\s*(?:import|export)\s+type\b", imp.raw))
        target = None
        if mapping:
            if spec in mapping:
                target = self._condition_target(mapping[spec], type_only)
            else:
                for key, value in mapping.items():
                    if key.count("*") != 1:
                        continue
                    prefix, suffix = key.split("*", 1)
                    if spec.startswith(prefix) and (not suffix or spec.endswith(suffix)):
                        middle = spec[len(prefix): len(spec) - len(suffix) if suffix else None]
                        declared = self._condition_target(value, type_only)
                        if declared:
                            target = declared.replace("*", middle)
                            break
        if target:
            base = posixpath.normpath(posixpath.join(pkg_dir or ".", target))
            found = self._ts_candidates(base)
            if found:
                return [ResolvedImport(
                    imp.raw, spec, imp.line, found[0], "inferred", "package-imports-map",
                    "internal", imp.names,
                    f"resolved by the imports map of {pkg_dir or '.'}/package.json")]
        return [ResolvedImport(
            imp.raw, spec, imp.line, None, "unresolved", "package-imports-map",
            "unresolved", imp.names,
            "private # import is not declared by the nearest package.json imports map")]

    def _resolve_ts(self, rel: str, imp: Import) -> list[ResolvedImport]:
        spec = imp.module
        method = "typescript-relative-import"
        targets: list[str] = []

        if spec.startswith(".") or spec.startswith("/"):
            base = posixpath.join(posixpath.dirname(rel), spec) if spec.startswith(".") else spec.lstrip("/")
            targets = self._ts_candidates(base)
            if not targets:
                return [ResolvedImport(imp.raw, spec, imp.line, None, "unresolved",
                                       "typescript-relative-import", "unresolved", imp.names,
                                       "relative path not found (generated, missing, or out of index)")]
        else:
            if spec.startswith("#"):
                return self._resolve_package_import(rel, spec, imp)
            cfg = next(
                (c for c in self.ts_configs
                 if (c["dir"] == "" or rel == c["dir"] or rel.startswith(c["dir"] + "/"))
                 and self._ts_covers(c, rel)),
                {"dir": "", "baseurl_dir": None, "paths_dir": "", "paths": [], "scope": None},
            )
            # path targets resolve against baseUrl when set, otherwise against
            # the config directory that declared them.
            baseurl_dir = cfg.get("baseurl_dir") or cfg.get("paths_dir") or cfg["dir"]
            for pattern, subs in cfg["paths"]:
                if "*" in pattern:
                    prefix, suffix = pattern.split("*", 1)
                    if spec.startswith(prefix) and spec.endswith(suffix):
                        middle = spec[len(prefix): len(spec) - len(suffix) if suffix else None]
                        for sub in subs:
                            cand = sub.replace("*", middle)
                            base = posixpath.normpath(posixpath.join(baseurl_dir, cand))
                            found = self._ts_candidates(base)
                            if found:
                                targets = found
                                method = "tsconfig-path-alias"
                                break
                elif spec == pattern:
                    for sub in subs:
                        base = posixpath.normpath(posixpath.join(baseurl_dir, sub))
                        found = self._ts_candidates(base)
                        if found:
                            targets = found
                            method = "tsconfig-path-alias"
                            break
                if targets:
                    break
            if not targets:
                # baseUrl makes bare specifiers relative to a source directory,
                # after `paths` has had its chance. It is JSON configuration,
                # so the edge stays inferred.
                if cfg.get("baseurl_dir") is not None:
                    found = self._ts_candidates(
                        posixpath.normpath(posixpath.join(baseurl_dir, spec)))
                    if found:
                        targets = found
                        method = "tsconfig-baseurl"
            if not targets:
                if spec.startswith("@"):
                    parts = spec.split("/")
                    pkg_name = "/".join(parts[:2])
                    subpath = "/".join(parts[2:])
                else:
                    parts = spec.split("/")
                    pkg_name = parts[0]
                    subpath = "/".join(parts[1:])
                pkg_dir = self.package_dirs.get(pkg_name)
                visible = pkg_dir is not None and self._package_visible_from(rel, pkg_name)
                if visible and subpath:
                    for probe in (posixpath.join(pkg_dir, subpath),
                                  posixpath.join(pkg_dir, "src", subpath)):
                        found = self._ts_candidates(posixpath.normpath(probe))
                        if found:
                            targets = found
                            method = "workspace-package"
                            break
                elif visible and self.packages.get(pkg_name):
                    targets = [self.packages[pkg_name]]
                    method = "workspace-package"
                elif pkg_dir is not None:
                    # A nested app that pins the registry package, in a repo
                    # without workspace linking. Not an edge into this source.
                    return [ResolvedImport(imp.raw, spec, imp.line, None, "external",
                                           "bare-specifier", "external", imp.names,
                                           f"package {pkg_name!r} is not visible from "
                                           f"{self._nearest_pkg_dir(rel) or '.'}")]
            if not targets:
                return [ResolvedImport(imp.raw, spec, imp.line, None, "external",
                                       "bare-specifier", "external", imp.names,
                                       "third-party package or Node builtin")]

        conf = "confirmed" if method == "typescript-relative-import" else "inferred"
        return [ResolvedImport(imp.raw, spec, imp.line, targets[0], conf, method,
                               "internal", imp.names)]

    # -- public -------------------------------------------------------------

    def resolve(self, rel: str, imports: list[Import]) -> list[ResolvedImport]:
        lang = self.lang.get(rel, "")
        out: list[ResolvedImport] = []
        for imp in imports:
            if imp.kind == "dynamic":
                if not imp.module:
                    out.append(ResolvedImport(imp.raw, "", imp.line, None, "unresolved",
                                              "dynamic-import", "dynamic", imp.names,
                                              "dynamic import target is not a string literal"))
                    continue
                if lang == "python":
                    sub = self._resolve_python(rel, imp)
                elif lang in ("typescript", "tsx", "javascript", "jsx"):
                    sub = self._resolve_ts(rel, imp)
                else:
                    sub = []
                for r in sub:
                    r.kind = "dynamic"
                    r.method = "dynamic-import"
                    r.note = "dynamic import; target may change at runtime"
                    r.confidence = "inferred" if r.target else "unresolved"
                out.extend(sub)
                continue
            if lang == "python":
                out.extend(self._resolve_python(rel, imp))
            elif lang in ("typescript", "tsx", "javascript", "jsx"):
                out.extend(self._resolve_ts(rel, imp))
        # Deduplicate by (target, line, module); keep the strongest confidence.
        rank = {"confirmed": 0, "inferred": 1, "external": 2, "unresolved": 3}
        best: dict[tuple, ResolvedImport] = {}
        for r in out:
            key = (r.target, r.line, r.module)
            if key not in best or rank[r.confidence] < rank[best[key].confidence]:
                best[key] = r
        return list(best.values())
