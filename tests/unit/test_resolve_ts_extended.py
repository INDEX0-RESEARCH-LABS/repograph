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


def _resolve(tmp_path: Path, importer: str, spec: str) -> list:
    files = [p.relative_to(tmp_path).as_posix()
             for p in tmp_path.rglob("*") if p.is_file()
             and p.suffix in (".ts", ".tsx", ".js", ".jsx")]
    r = Resolver(tmp_path, [(p, "typescript") for p in files])
    imp = extract(importer, "typescript", f'import x from "{spec}";\n'.encode()).imports
    return r.resolve(importer, imp)


def test_extends_inherits_baseurl_and_paths(tmp_path: Path):
    _make(tmp_path, {
        "configs/tsconfig.base.json": json.dumps({"compilerOptions": {
            "baseUrl": "../src", "paths": {"@/*": ["*"]}}}),
        "tsconfig.json": json.dumps({"extends": "./configs/tsconfig.base.json"}),
        "src/utils/helper.ts": "export const x = 1;\n",
        "src/use.ts": "",
    })
    got = _resolve(tmp_path, "src/use.ts", "@/utils/helper")
    assert got[0].target == "src/utils/helper.ts"
    assert got[0].method == "tsconfig-path-alias"


def test_child_overrides_parent_paths(tmp_path: Path):
    _make(tmp_path, {
        "tsconfig.base.json": json.dumps({"compilerOptions": {
            "baseUrl": ".", "paths": {"@/*": ["old/*"]}}}),
        "tsconfig.json": json.dumps({
            "extends": "./tsconfig.base.json",
            "compilerOptions": {"paths": {"@/*": ["new/*"]}}}),
        "old/x.ts": "export const old = 1;\n",
        "new/x.ts": "export const new = 1;\n",
        "use.ts": "",
    })
    got = _resolve(tmp_path, "use.ts", "@/x")
    assert got[0].target == "new/x.ts"


def test_extends_array_later_entries_win(tmp_path: Path):
    _make(tmp_path, {
        "base/a.json": json.dumps({"compilerOptions": {
            "baseUrl": "..", "paths": {"@/*": ["a/*"]}}}),
        "base/b.json": json.dumps({"compilerOptions": {
            "baseUrl": "..", "paths": {"@/*": ["b/*"]}}}),
        "tsconfig.json": json.dumps({"extends": ["./base/a.json", "./base/b.json"]}),
        "a/x.ts": "export const a = 1;\n",
        "b/x.ts": "export const b = 1;\n",
        "use.ts": "",
    })
    got = _resolve(tmp_path, "use.ts", "@/x")
    assert got[0].target == "b/x.ts"


def test_extend_cycle_does_not_recurse_forever(tmp_path: Path):
    _make(tmp_path, {
        "a.json": json.dumps({"extends": "./b.json",
                              "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}),
        "b.json": json.dumps({"extends": "./a.json"}),
        "tsconfig.json": json.dumps({"extends": "./a.json"}),
        "src/x.ts": "export const x = 1;\n",
        "use.ts": "",
    })
    got = _resolve(tmp_path, "use.ts", "@/x")
    assert got[0].target == "src/x.ts"


def test_extends_into_node_modules_is_not_followed(tmp_path: Path):
    _make(tmp_path, {
        "node_modules/pkg/tsconfig.json": json.dumps({"compilerOptions": {
            "baseUrl": ".", "paths": {"@lib/*": ["src/*"]}}}),
        "node_modules/pkg/src/x.ts": "export const x = 1;\n",
        "tsconfig.json": json.dumps({"extends": "./node_modules/pkg/tsconfig.json"}),
        "use.ts": "",
    })
    got = _resolve(tmp_path, "use.ts", "@lib/x")
    assert got[0].kind != "internal"
