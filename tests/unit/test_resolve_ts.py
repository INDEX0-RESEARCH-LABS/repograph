from __future__ import annotations

import json
from pathlib import Path

from repograph.extract import extract
from repograph.resolve import Resolver


def _make(tmp_path: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _resolver(tmp_path: Path, paths: list[str]) -> Resolver:
    return Resolver(tmp_path, [(p, "typescript") for p in paths])


def test_baseurl_resolves_bare_specifier_without_paths(tmp_path: Path):
    _make(tmp_path, {
        "tsconfig.json": json.dumps({"compilerOptions": {"baseUrl": "src"}}),
        "src/utils/helper.ts": "export const x = 1;\n",
        "src/use.ts": 'import { x } from "utils/helper";\n',
    })
    r = _resolver(tmp_path, ["src/utils/helper.ts", "src/use.ts"])
    imp = extract("src/use.ts", "typescript", b'import { x } from "utils/helper";\n').imports
    got = r.resolve("src/use.ts", imp)
    assert (got[0].target, got[0].method, got[0].confidence, got[0].kind) == (
        "src/utils/helper.ts", "tsconfig-baseurl", "inferred", "internal")


def test_paths_alias_wins_over_baseurl(tmp_path: Path):
    _make(tmp_path, {
        "tsconfig.json": json.dumps({"compilerOptions": {
            "baseUrl": "src", "paths": {"utils/*": ["mapped/*"]}}}),
        "src/utils/helper.ts": "export const x = 1;\n",
        "src/mapped/helper.ts": "export const y = 2;\n",
        "src/use.ts": 'import { y } from "utils/helper";\n',
    })
    r = _resolver(tmp_path, ["src/utils/helper.ts", "src/mapped/helper.ts", "src/use.ts"])
    imp = extract("src/use.ts", "typescript", b'import { y } from "utils/helper";\n').imports
    got = r.resolve("src/use.ts", imp)
    assert got[0].target == "src/mapped/helper.ts"
    assert got[0].method == "tsconfig-path-alias"
