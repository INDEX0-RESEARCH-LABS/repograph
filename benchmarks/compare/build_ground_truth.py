#!/usr/bin/env python3
"""Build verified ground truth for direct importers of each selected file.

Method: ripgrep for import/require statements, then verify each match by
reading the file. Manual corrections based on inspecting actual file content
(documented in RESULTS.md threats-to-validity section).
"""
import json
import re
import subprocess
from pathlib import Path

REPOS = {
    "django": "/tmp/opencode/compare/repos/django",
    "esbuild": "/tmp/opencode/compare/repos/esbuild",
    "koa":    "/tmp/opencode/compare/repos/koa",
}

# Selected files (matches pre-registered selection rule output)
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


def rg(patterns, root, glob="*.py"):
    found = set()
    for pat in patterns:
        r = subprocess.run(
            ["rg", "-l", f"--glob={glob}", "-e", pat, "."],
            capture_output=True, text=True, cwd=root, timeout=30,
        )
        for line in r.stdout.splitlines():
            f = line.strip().lstrip("./")
            if f and ".repograph" not in f:
                found.add(f)
    return found


def django_importers(rel_file, root):
    parts = rel_file.replace(".py", "").split("/")
    stem = parts[-1]
    is_init = stem == "__init__"
    mod = ".".join(parts[:-1] if is_init else parts)
    mod_re = re.escape(mod)
    patterns = [
        f"from {mod_re}[ \\t,]", f"from {mod_re}$",
        f"import {mod_re}[ \\t,;$]", f"import {mod_re}$",
    ]
    if is_init and len(parts) >= 2:
        parent = ".".join(parts[:-2]) if len(parts) >= 3 else ""
        subname = parts[-2]
        if parent:
            patterns += [
                f"from {re.escape(parent)} import {re.escape(subname)}",
                f"from {re.escape(parent)} import.*{re.escape(subname)}",
            ]
    return sorted(rg(patterns, root, "*.py") - {rel_file})


def js_ts_importers(rel_file, root):
    stem = Path(rel_file).stem  # context, only, etc.
    patterns = [
        f"['\"](.*/)?{re.escape(stem)}['\"]",
        f"require\\(['\"](.*/)?{re.escape(stem)}['\"]\\)",
        f"from ['\"](.*/)?{re.escape(stem)}['\"]",
    ]
    found = set()
    for pat in patterns:
        for glob in ("*.js", "*.ts", "*.tsx", "*.mjs", "*.cjs"):
            r = subprocess.run(
                ["rg", "-l", f"--glob={glob}", "-e", pat, "."],
                capture_output=True, text=True, cwd=root, timeout=30,
            )
            for line in r.stdout.splitlines():
                f = line.strip().lstrip("./")
                if f and ".repograph" not in f:
                    found.add(f)
    return sorted(found - {rel_file})


def verify_py(importer_path, target_rel, root):
    try:
        content = (Path(root) / importer_path).read_text(errors="replace")
    except OSError:
        return False
    parts = target_rel.replace(".py", "").split("/")
    stem = parts[-1]
    is_init = stem == "__init__"
    mod = ".".join(parts[:-1] if is_init else parts)
    if re.search(rf"(?:from\s+{re.escape(mod)}(?:\s|$|\.|,)|import\s+{re.escape(mod)}(?:\s|$|,))", content):
        return True
    if is_init and len(parts) >= 2:
        parent = ".".join(parts[:-2]) if len(parts) >= 3 else ""
        subname = parts[-2]
        if parent and re.search(rf"from\s+{re.escape(parent)}\s+import\b.*\b{re.escape(subname)}\b", content):
            return True
    return False


def verify_js(importer_path, target_rel, root):
    try:
        content = (Path(root) / importer_path).read_text(errors="replace")
    except OSError:
        return False
    stem = Path(target_rel).stem
    return bool(re.search(
        rf"""(?:require|from|import)\s*\(?\s*['"](?:\.\./|\./)([^'"]*/)??{re.escape(stem)}(?:\.[jt]sx?)?['"]\)?""",
        content,
    ))


def build_gt():
    gt = {}
    for repo, files in SELECTED.items():
        root = REPOS[repo]
        gt[repo] = {}
        for rel_file in files:
            if rel_file.endswith(".py"):
                candidates = django_importers(rel_file, root)
                verified = [c for c in candidates if verify_py(c, rel_file, root)]
            else:
                candidates = js_ts_importers(rel_file, root)
                verified = [c for c in candidates if verify_js(c, rel_file, root)]

            gt[repo][rel_file] = {
                "verified_importers": verified,
                "unverified_candidates": [c for c in candidates if c not in verified],
            }
            print(f"  {repo}/{rel_file}: {len(verified)} verified ({len(candidates)} candidates)")
    return gt


if __name__ == "__main__":
    print("Building ground truth...")
    gt = build_gt()

    # ── Manual corrections from pre-restart session ──────────────────────────
    # These were verified by reading actual file content; documented in RESULTS.md.

    # koa/lib/only.js: require('./only.js') confirmed in application, request, response
    gt["koa"]["lib/only.js"]["verified_importers"] = [
        "lib/application.js", "lib/request.js", "lib/response.js"]
    gt["koa"]["lib/only.js"]["unverified_candidates"] = []
    gt["koa"]["lib/only.js"]["note"] = "manual: require('./only.js') in all 3 files"

    # koa/lib/is-stream.js: confirmed in application.js and response.js
    gt["koa"]["lib/is-stream.js"]["verified_importers"] = ["lib/application.js", "lib/response.js"]
    gt["koa"]["lib/is-stream.js"]["unverified_candidates"] = []

    # koa/lib/context.js: direct importers are application.js and test-helpers/context.js
    # (test files import via test-helpers/context.js, not directly)
    gt["koa"]["lib/context.js"]["verified_importers"] = ["lib/application.js", "test-helpers/context.js"]
    gt["koa"]["lib/context.js"]["unverified_candidates"] = []
    gt["koa"]["lib/context.js"]["note"] = "57 test files import via test-helpers/context.js (transitive); direct: 2"

    # koa/lib/request.js and response.js: only application.js imports them directly
    gt["koa"]["lib/request.js"]["verified_importers"] = ["lib/application.js"]
    gt["koa"]["lib/response.js"]["verified_importers"] = ["lib/application.js"]

    # koa/test-helpers/stream.js: only body.test.js requires '../../test-helpers/stream'
    # (other test files require node's 'stream', not this fixture)
    gt["koa"]["test-helpers/stream.js"]["verified_importers"] = ["__tests__/response/body.test.js"]
    gt["koa"]["test-helpers/stream.js"]["note"] = "other test files import node:stream, not this fixture"

    # koa/lib/search-params.js: only request.js requires it
    gt["koa"]["lib/search-params.js"]["verified_importers"] = ["lib/request.js"]
    gt["koa"]["lib/search-params.js"]["unverified_candidates"] = []

    # esbuild/scripts/esbuild.js: end-to-end-tests.js and wasm-tests.js confirmed;
    # node-install.ts imports npm 'esbuild' package, not this script file
    cur = gt["esbuild"]["scripts/esbuild.js"]["verified_importers"]
    extras = ["scripts/end-to-end-tests.js", "scripts/wasm-tests.js"]
    for e in extras:
        if e not in cur: cur.append(e)
    cur = [c for c in cur if "node-install" not in c]
    gt["esbuild"]["scripts/esbuild.js"]["verified_importers"] = sorted(cur)
    gt["esbuild"]["scripts/esbuild.js"]["unverified_candidates"] = []
    gt["esbuild"]["scripts/esbuild.js"]["note"] = "node-install.ts imports npm package esbuild, not this script"

    # esbuild/lib/shared/worker.ts: 0 actual importers
    # (rg matched 'worker_threads' — node module, not this file)
    gt["esbuild"]["lib/shared/worker.ts"]["verified_importers"] = []
    gt["esbuild"]["lib/shared/worker.ts"]["unverified_candidates"] = []
    gt["esbuild"]["lib/shared/worker.ts"]["note"] = "rg false positives from worker_threads (node module)"

    # esbuild: false positives from generic stems (index, types, in, css_table)
    for f in ["compat-table/src/index.ts", "lib/shared/types.ts",
              "compat-table/src/css_table.ts", "require/yarnpnp/in.mjs"]:
        gt["esbuild"][f]["unverified_candidates"] = []

    out = Path("/tmp/opencode/compare/ground_truth.json")
    out.write_text(json.dumps(gt, indent=2))
    print(f"\nGround truth written to {out}")

    total = sum(len(d["verified_importers"]) for r in gt.values() for d in r.values())
    print(f"Total verified importers: {total}")
