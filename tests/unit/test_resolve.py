from __future__ import annotations

import json
from pathlib import Path

from repograph.extract import extract
from repograph.resolve import Resolver


def _files(*paths: str) -> list[tuple[str, str]]:
    out = []
    for p in paths:
        lang = "python" if p.endswith(".py") else "typescript"
        out.append((p, lang))
    return out


def test_python_relative_and_src_layout_resolution(tmp_path: Path):
    files = _files("src/pkg/__init__.py", "src/pkg/a.py", "src/pkg/sub/__init__.py",
                   "src/pkg/sub/b.py", "src/pkg/models.py")
    for rel, _ in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    r = Resolver(tmp_path, files)

    imp = extract("src/pkg/a.py", "python", b"from .models import Thing\nfrom . import sub\n").imports
    got = r.resolve("src/pkg/a.py", imp)
    targets = {(x.target, x.confidence) for x in got}
    assert ("src/pkg/models.py", "confirmed") in targets
    assert ("src/pkg/sub/__init__.py", "confirmed") in targets

    imp = extract("src/pkg/sub/b.py", "python", b"from .. import models\n").imports
    got = r.resolve("src/pkg/sub/b.py", imp)
    assert any(x.target == "src/pkg/models.py" for x in got)

    imp = extract("src/pkg/a.py", "python", b"from pkg.models import Thing\n").imports
    got = r.resolve("src/pkg/a.py", imp)
    assert any(x.target == "src/pkg/models.py" and x.confidence == "confirmed" for x in got)


def test_python_external_and_unresolved(tmp_path: Path):
    files = _files("pkg/__init__.py", "pkg/a.py", "pkg/broken_ref.py")
    for rel, _ in files:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    r = Resolver(tmp_path, files)
    imp = extract("pkg/a.py", "python", b"import json\nfrom .missing import X\nfrom pkg.unknown import Y\n").imports
    got = r.resolve("pkg/a.py", imp)
    kinds = {(x.module, x.kind) for x in got}
    assert ("json", "external") in kinds
    assert any(x.kind == "unresolved" for x in got)


def test_python_stdlib_name_does_not_match_repo_file(tmp_path: Path):
    """`import types` must not bind to app/types.py (measured FastAPI defect)."""
    for rel in ("app/__init__.py", "app/main.py", "app/types.py", "app/security/http.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    files = [("app/__init__.py", "python"), ("app/main.py", "python"),
             ("app/types.py", "python"), ("app/security/http.py", "python")]
    r = Resolver(tmp_path, files)
    imp = extract("app/main.py", "python",
                  b"import types\nimport http\nfrom app.types import Thing\n").imports
    got = {(x.module, x.kind, x.target) for x in r.resolve("app/main.py", imp)}
    assert ("types", "external", None) in got
    assert ("http", "external", None) in got
    assert ("app.types", "internal", "app/types.py") in got


def test_js_relative_parent_resolves_root_index(tmp_path: Path):
    """`require('..')` from test/x.js resolves to the root index.js (measured Express defect)."""
    (tmp_path / "test").mkdir()
    (tmp_path / "index.js").write_text("")
    (tmp_path / "test/x.js").write_text("")
    r = Resolver(tmp_path, [("index.js", "javascript"), ("test/x.js", "javascript")])
    imp = extract("test/x.js", "javascript", b"const app = require('..');\n").imports
    got = {(x.module, x.target, x.confidence, x.kind) for x in r.resolve("test/x.js", imp)}
    assert ("..", "index.js", "confirmed", "internal") in got


def test_ts_dts_extensionless_import(tmp_path: Path):
    """`.d.ts` files are real resolution targets (measured Vue dts-test defect)."""
    (tmp_path / "dts-test").mkdir()
    (tmp_path / "dts-test/utils.d.ts").write_text("")
    (tmp_path / "dts-test/use.ts").write_text("")
    r = Resolver(tmp_path, [("dts-test/utils.d.ts", "typescript"),
                            ("dts-test/use.ts", "typescript")])
    imp = extract("dts-test/use.ts", "typescript", b'import { x } from "./utils";\n').imports
    got = {(x.module, x.target, x.kind) for x in r.resolve("dts-test/use.ts", imp)}
    assert ("./utils", "dts-test/utils.d.ts", "internal") in got


def test_ts_workspace_subpath_maps_into_package(tmp_path: Path):
    """`vue/server-renderer` maps under packages/vue, not to its main entry (measured Vue defect)."""
    (tmp_path / "packages/vue/server-renderer").mkdir(parents=True)
    (tmp_path / "packages/vue/package.json").write_text(
        json.dumps({"name": "vue", "main": "index.js"}))
    for rel in ("packages/vue/index.js", "packages/vue/server-renderer/index.js",
                "packages/vue/use.ts"):
        (tmp_path / rel).write_text("")
    files = [("packages/vue/index.js", "javascript"),
             ("packages/vue/server-renderer/index.js", "javascript"),
             ("packages/vue/use.ts", "typescript")]
    r = Resolver(tmp_path, files)
    imp = extract("packages/vue/use.ts", "typescript",
                  b'import { render } from "vue/server-renderer";\n').imports
    got = {(x.module, x.target, x.method) for x in r.resolve("packages/vue/use.ts", imp)}
    assert ("vue/server-renderer", "packages/vue/server-renderer/index.js",
            "workspace-package") in got


def test_ts_glob_alias_survives_comment_stripping(tmp_path: Path):
    """`@vue/*` glob must not be treated as a comment opener (measured Vue defect)."""
    (tmp_path / "tsconfig.json").write_text("""{
      // source aliases, used by the build
      "compilerOptions": { "paths": { "@app/*": ["./packages/*/src"] } }
    }
    """)
    (tmp_path / "packages/core/src").mkdir(parents=True)
    (tmp_path / "packages/core/src/index.ts").write_text("")
    (tmp_path / "packages/core/use.ts").write_text("")
    files = [("packages/core/src/index.ts", "typescript"),
             ("packages/core/use.ts", "typescript")]
    r = Resolver(tmp_path, files)
    imp = extract("packages/core/use.ts", "typescript",
                  b'import { x } from "@app/core";\n').imports
    got = {(x.module, x.target, x.method) for x in r.resolve("packages/core/use.ts", imp)}
    assert ("@app/core", "packages/core/src/index.ts", "tsconfig-path-alias") in got


def test_ts_alias_workspace_and_relative(tmp_path: Path):
    (tmp_path / "web/src/api").mkdir(parents=True)
    (tmp_path / "web/src/domain").mkdir(parents=True)
    (tmp_path / "web/tsconfig.json").write_text(json.dumps({
        "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}
    }))
    (tmp_path / "web/package.json").write_text(json.dumps({"name": "@shop/web", "module": "src/index.ts"}))
    for rel in ("web/src/api/client.ts", "web/src/domain/subscription.ts", "web/src/index.ts"):
        (tmp_path / rel).write_text("")
    files = [("web/src/api/client.ts", "typescript"), ("web/src/domain/subscription.ts", "typescript"),
             ("web/src/index.ts", "typescript")]
    r = Resolver(tmp_path, files)
    imp = extract("web/src/api/client.ts", "typescript",
                  b'import { S } from "@/domain/subscription";\nimport { x } from "@shop/web";\n'
                  b'import { y } from "./missing";\n').imports
    got = {(x.module, x.target, x.confidence, x.method) for x in r.resolve("web/src/api/client.ts", imp)}
    assert ("@/domain/subscription", "web/src/domain/subscription.ts", "inferred",
            "tsconfig-path-alias") in got
    assert ("@shop/web", "web/src/index.ts", "inferred", "workspace-package") in got
    assert any(x[0] == "./missing" for x in got)


def test_ts_extensionless_index_and_external(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/index.ts").write_text("")
    (tmp_path / "src/use.ts").write_text("")
    r = Resolver(tmp_path, [("src/index.ts", "typescript"), ("src/use.ts", "typescript")])
    imp = extract("src/use.ts", "typescript", b'import "./";\nimport "react";\n').imports
    got = {(x.module, x.target, x.kind) for x in r.resolve("src/use.ts", imp)}
    assert ("./", "src/index.ts", "internal") in got
    assert ("react", None, "external") in got


def test_ts_workspace_prefers_source_entry_over_unbuilt_dist(tmp_path: Path):
    """Published `module` in dist/ is absent in a source checkout; use src/index.ts."""
    (tmp_path / "packages/core/src").mkdir(parents=True)
    (tmp_path / "packages/core/package.json").write_text(json.dumps({
        "name": "@app/core", "main": "index.js",
        "module": "dist/core.esm.js"}))
    for rel in ("packages/core/index.js", "packages/core/src/index.ts",
                "packages/core/use.ts"):
        (tmp_path / rel).write_text("")
    files = [("packages/core/index.js", "javascript"),
             ("packages/core/src/index.ts", "typescript"),
             ("packages/core/use.ts", "typescript")]
    r = Resolver(tmp_path, files)
    imp = extract("packages/core/use.ts", "typescript",
                  b'import { x } from "@app/core";\n').imports
    got = {(x.module, x.target, x.method) for x in r.resolve("packages/core/use.ts", imp)}
    assert ("@app/core", "packages/core/src/index.ts", "workspace-package") in got


def test_python_src_layout_package_import(tmp_path: Path):
    """`import requests` binds src/requests/__init__.py, not an unresolved name."""
    for rel in ("src/requests/__init__.py", "src/requests/api.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    r = Resolver(tmp_path, [("src/requests/__init__.py", "python"),
                            ("src/requests/api.py", "python")])
    imp = extract("src/requests/api.py", "python", b"import requests\n").imports
    got = {(x.module, x.target, x.kind) for x in r.resolve("src/requests/api.py", imp)}
    assert ("requests", "src/requests/__init__.py", "internal") in got


def test_python_from_dot_import_submodule_only(tmp_path: Path):
    """`from . import mod` must not also emit a package __init__ edge."""
    for rel in ("pkg/__init__.py", "pkg/mod.py", "pkg/use.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    r = Resolver(tmp_path, [("pkg/__init__.py", "python"), ("pkg/mod.py", "python"),
                            ("pkg/use.py", "python")])
    imp = extract("pkg/use.py", "python", b"from . import mod\n").imports
    got = {(x.module, x.target) for x in r.resolve("pkg/use.py", imp)}
    assert "pkg/__init__.py" not in {t for _, t in got}
    assert (".mod", "pkg/mod.py") in got


def test_ts_esm_js_specifier_maps_to_ts_source(tmp_path: Path):
    """`./parse.js` resolves to `./parse.ts` in TypeScript ESM sources."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src/parse.ts").write_text("")
    (tmp_path / "src/use.ts").write_text("")
    r = Resolver(tmp_path, [("src/parse.ts", "typescript"), ("src/use.ts", "typescript")])
    imp = extract("src/use.ts", "typescript", b'import * as p from "./parse.js";\n').imports
    got = {(x.module, x.target, x.kind) for x in r.resolve("src/use.ts", imp)}
    assert ("./parse.js", "src/parse.ts", "internal") in got


def test_ts_workspace_subpath_falls_back_to_src(tmp_path: Path):
    """`pkg/sub` may map to `packages/pkg/src/sub/index.ts` (exports subpath)."""
    (tmp_path / "packages/pkg/src/sub").mkdir(parents=True)
    (tmp_path / "packages/pkg/package.json").write_text(
        json.dumps({"name": "pkg", "main": "index.js"}))
    for rel in ("packages/pkg/index.js", "packages/pkg/src/sub/index.ts",
                "packages/pkg/use.ts"):
        (tmp_path / rel).write_text("")
    files = [("packages/pkg/index.js", "javascript"),
             ("packages/pkg/src/sub/index.ts", "typescript"),
             ("packages/pkg/use.ts", "typescript")]
    r = Resolver(tmp_path, files)
    imp = extract("packages/pkg/use.ts", "typescript", b'import "pkg/sub";\n').imports
    got = {(x.module, x.target, x.method) for x in r.resolve("packages/pkg/use.ts", imp)}
    assert ("pkg/sub", "packages/pkg/src/sub/index.ts", "workspace-package") in got


def test_python_from_dot_import_attribute_keeps_init_edge(tmp_path: Path):
    """`from . import VERSION` binds a package attribute, so __init__ is a real edge."""
    for rel in ("pkg/__init__.py", "pkg/use.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    r = Resolver(tmp_path, [("pkg/__init__.py", "python"), ("pkg/use.py", "python")])
    imp = extract("pkg/use.py", "python", b"from . import VERSION\n").imports
    got = {(x.module, x.target) for x in r.resolve("pkg/use.py", imp)}
    assert "pkg/__init__.py" in {t for _, t in got}


def test_python_project_root_resolves_example_app(tmp_path: Path):
    """Example projects import their own top-level package (measured Flask miss)."""
    for rel in ("examples/tutorial/flaskr/__init__.py", "examples/tutorial/flaskr/db.py",
                "examples/tutorial/tests/test_db.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    (tmp_path / "examples/tutorial/pyproject.toml").write_text("[project]\nname='tutorial'\n")
    files = [("examples/tutorial/flaskr/__init__.py", "python"),
             ("examples/tutorial/flaskr/db.py", "python"),
             ("examples/tutorial/tests/test_db.py", "python")]
    r = Resolver(tmp_path, files)
    imp = extract("examples/tutorial/tests/test_db.py", "python",
                  b"from flaskr import create_app\nfrom flaskr.db import get_db\n").imports
    got = {(x.module, x.target, x.confidence, x.method) for x in r.resolve(
        "examples/tutorial/tests/test_db.py", imp)}
    # The package name itself is reachable only through the project root.
    assert any(x[0] == "flaskr" and x[1] == "examples/tutorial/flaskr/__init__.py"
               and x[2] == "inferred" and x[3] == "python-project-root" for x in got)
    # The submodule also has a package-alias route now that alias lookup is
    # independent of the process working directory.
    assert any(x[1] == "examples/tutorial/flaskr/db.py" for x in got)


def test_python_ambiguous_project_roots_stay_unresolved(tmp_path: Path):
    """Two project roots defining the same name must not guess."""
    for rel in ("a/common/__init__.py", "b/common/__init__.py", "use.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    (tmp_path / "a/pyproject.toml").write_text("")
    (tmp_path / "b/setup.py").write_text("")
    files = [("a/common/__init__.py", "python"), ("b/common/__init__.py", "python"),
             ("use.py", "python")]
    r = Resolver(tmp_path, files)
    imp = extract("use.py", "python", b"import common\n").imports
    got = r.resolve("use.py", imp)
    assert got[0].target is None and got[0].kind == "unresolved"
    assert got[0].method == "ambiguous-python-root"


def test_python_conftest_syspath_root_resolves_test_app(tmp_path: Path):
    """A conftest syspath_prepend directory is an import root (measured Flask miss)."""
    for rel in ("tests/test_apps/blueprintapp/__init__.py",
                "tests/test_apps/blueprintapp/apps/admin/__init__.py",
                "tests/test_blueprints.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    (tmp_path / "tests/conftest.py").write_text(
        "import os\n"
        "def fixture(monkeypatch):\n"
        "    monkeypatch.syspath_prepend(os.path.join(os.path.dirname(__file__), 'test_apps'))\n")
    files = [("tests/test_apps/blueprintapp/__init__.py", "python"),
             ("tests/test_apps/blueprintapp/apps/admin/__init__.py", "python"),
             ("tests/test_blueprints.py", "python"), ("tests/conftest.py", "python")]
    r = Resolver(tmp_path, files)
    imp = extract("tests/test_blueprints.py", "python",
                  b"from blueprintapp.apps.admin import admin\n").imports
    got = {(x.module, x.target, x.confidence, x.method) for x in r.resolve(
        "tests/test_blueprints.py", imp)}
    assert ("blueprintapp.apps.admin",
            "tests/test_apps/blueprintapp/apps/admin/__init__.py",
            "inferred", "python-syspath-root") in got


def test_ts_package_imports_map_resolves_private_specifiers(tmp_path: Path):
    """`#private` specifiers come from the nearest package.json imports map."""
    pkg = tmp_path / "packages/svelte"
    (pkg / "src/internal/client").mkdir(parents=True)
    (pkg / "src/compiler").mkdir(parents=True)
    (pkg / "src/wild").mkdir(parents=True)
    (pkg / "package.json").write_text(json.dumps({
        "name": "svelte",
        "imports": {
            "#client/constants": "./src/internal/client/constants.js",
            "#compiler": {"types": "./src/compiler/private.d.ts",
                          "default": "./src/compiler/index.js"},
            "#wild/*": "./src/wild/*.js",
        },
    }))
    for rel in ("packages/svelte/src/internal/client/constants.js",
                "packages/svelte/src/compiler/index.js",
                "packages/svelte/src/compiler/private.d.ts",
                "packages/svelte/src/wild/a.js",
                "packages/svelte/src/use.ts"):
        (tmp_path / rel).write_text("")
    files = [(rel, "typescript" if rel.endswith((".ts", ".d.ts")) else "javascript")
             for rel in ("packages/svelte/src/internal/client/constants.js",
                         "packages/svelte/src/compiler/index.js",
                         "packages/svelte/src/compiler/private.d.ts",
                         "packages/svelte/src/wild/a.js",
                         "packages/svelte/src/use.ts")]
    r = Resolver(tmp_path, files)
    imp = extract("packages/svelte/src/use.ts", "typescript",
                  b'import "#client/constants";\nimport "#compiler";\n'
                  b'import type { AST } from "#compiler";\n'
                  b'import "#wild/a";\nimport "#missing";\n').imports
    got = {(x.module, x.target, x.kind, x.method) for x in r.resolve(
        "packages/svelte/src/use.ts", imp)}
    assert ("#client/constants", "packages/svelte/src/internal/client/constants.js",
            "internal", "package-imports-map") in got
    assert ("#compiler", "packages/svelte/src/compiler/index.js",
            "internal", "package-imports-map") in got
    assert ("#compiler", "packages/svelte/src/compiler/private.d.ts",
            "internal", "package-imports-map") in got
    assert ("#wild/a", "packages/svelte/src/wild/a.js",
            "internal", "package-imports-map") in got
    assert ("#missing", None, "unresolved", "package-imports-map") in got


def test_ts_exports_dist_entry_maps_to_source_entry(tmp_path: Path):
    """`import "vite"` inside Vite resolves via exports dist -> src (measured miss)."""
    (tmp_path / "packages/vite/src/node").mkdir(parents=True)
    (tmp_path / "packages/vite/package.json").write_text(json.dumps({
        "name": "vite", "exports": {".": "./dist/node/index.js"}}))
    # Vite is a pnpm workspace; without a workspace declaration a playground is
    # a separate install and the bare name belongs to the registry.
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - packages/*\n")
    for rel in ("packages/vite/src/node/index.ts", "playground/config.ts"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    files = [("packages/vite/src/node/index.ts", "typescript"),
             ("playground/config.ts", "typescript")]
    r = Resolver(tmp_path, files)
    imp = extract("playground/config.ts", "typescript",
                  b'import { defineConfig } from "vite";\n').imports
    got = {(x.module, x.target, x.confidence, x.method) for x in r.resolve(
        "playground/config.ts", imp)}
    assert ("vite", "packages/vite/src/node/index.ts", "inferred",
            "workspace-package") in got


def test_ts_alias_scope_excludes_example_app(tmp_path: Path):
    """A root tsconfig's `include` bounds its aliases (measured zustand defect)."""
    (tmp_path / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {"paths": {"zustand": ["./src/index.ts"]}},
        "include": ["src/**/*", "tests/**/*"],
    }))
    (tmp_path / "package.json").write_text(json.dumps({"name": "zustand"}))
    (tmp_path / "examples/demo").mkdir(parents=True)
    (tmp_path / "examples/demo/package.json").write_text(json.dumps({
        "name": "demo", "dependencies": {"zustand": "^5.0.2"}}))
    for rel in ("src/index.ts", "src/use.ts", "examples/demo/App.jsx"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("")
    files = [("src/index.ts", "typescript"), ("src/use.ts", "tsx"),
             ("examples/demo/App.jsx", "jsx")]
    r = Resolver(tmp_path, files)

    inside = extract("src/use.ts", "typescript", b'import { x } from "zustand";\n').imports
    assert ("zustand", "src/index.ts", "tsconfig-path-alias") in {
        (x.module, x.target, x.method) for x in r.resolve("src/use.ts", inside)}

    outside = extract("examples/demo/App.jsx", "jsx", b'import { x } from "zustand";\n').imports
    assert all(x.kind != "internal" for x in r.resolve("examples/demo/App.jsx", outside))


def test_ts_package_self_reference_needs_workspaces_for_cross_package(tmp_path: Path):
    """Nested apps without workspace linking do not resolve into the root package."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "zustand"}))
    (tmp_path / "src/index.ts").parent.mkdir(parents=True)
    (tmp_path / "src/index.ts").write_text("")
    (tmp_path / "examples/starter").mkdir(parents=True)
    (tmp_path / "examples/starter/package.json").write_text(json.dumps({
        "name": "starter", "dependencies": {"zustand": "^5.0.2"}}))
    (tmp_path / "examples/starter/index.tsx").write_text("")
    files = [("src/index.ts", "typescript"), ("examples/starter/index.tsx", "tsx")]
    r = Resolver(tmp_path, files)
    imp = extract("examples/starter/index.tsx", "tsx", b'import { x } from "zustand";\n').imports
    assert all(x.kind != "internal" for x in r.resolve("examples/starter/index.tsx", imp))

    # The package's own files still resolve the name to its source.
    (tmp_path / "src/use.ts").write_text("")
    r2 = Resolver(tmp_path, [("src/index.ts", "typescript"), ("src/use.ts", "typescript")])
    imp2 = extract("src/use.ts", "typescript", b'import { x } from "zustand";\n').imports
    assert ("zustand", "src/index.ts", "workspace-package") in {
        (x.module, x.target, x.method) for x in r2.resolve("src/use.ts", imp2)}


def test_python_alias_uses_top_most_contiguous_package(tmp_path: Path, monkeypatch):
    """libs/pkg/sub/m.py is `pkg.sub.m`, not `sub.m`, regardless of cwd."""
    for rel in ("libs/pkg/__init__.py", "libs/pkg/sub/__init__.py",
                "libs/pkg/sub/m.py", "libs/pkg/sub/use.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path.parent)
    files = [(rel, "python") for rel in (
        "libs/pkg/__init__.py", "libs/pkg/sub/__init__.py",
        "libs/pkg/sub/m.py", "libs/pkg/sub/use.py")]
    r = Resolver(tmp_path, files)

    imp = extract("libs/pkg/sub/use.py", "python", b"from pkg.sub.m import f\n").imports
    got = r.resolve("libs/pkg/sub/use.py", imp)
    assert any(x.target == "libs/pkg/sub/m.py" for x in got)

    imp = extract("libs/pkg/sub/use.py", "python", b"from sub.m import f\n").imports
    got = r.resolve("libs/pkg/sub/use.py", imp)
    assert not any(x.target == "libs/pkg/sub/m.py" for x in got)
