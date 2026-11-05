from __future__ import annotations

from pathlib import Path

from repograph.config import load_settings
from repograph.impact import analyze_impact
from repograph.indexer import index_repository
from repograph.store import Store


def _impact(repo: Path, **kwargs) -> dict:
    with Store(load_settings(repo)) as store:
        return analyze_impact(store, repo, **kwargs)


def _ts_repo(repo: Path) -> None:
    (repo / "web").mkdir(exist_ok=True)
    (repo / "web/tsconfig.json").write_text(
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}',
        encoding="utf-8",
    )
    (repo / "web/src").mkdir(exist_ok=True)
    (repo / "web/src/target.ts").write_text("export const x = 1;\n", encoding="utf-8")
    # Alias import: resolution goes through JSON config, so the edge is inferred.
    (repo / "web/src/mid.ts").write_text(
        'import { x } from "@/target";\nexport const y = x;\n', encoding="utf-8"
    )
    # Relative import: confirmed edge. Combined path must stay inferred.
    (repo / "web/src/leaf.ts").write_text(
        'import { y } from "./mid";\nexport const z = y;\n', encoding="utf-8"
    )
    index_repository(repo)


def test_transitive_confidence_is_weakest_along_the_path(repo: Path):
    _ts_repo(repo)
    result = _impact(repo, paths=["web/src/target.ts"], depth=3)
    transitive = {t["path"]: t for t in result["transitive_dependents"]}
    direct = {d["path"]: d for d in result["direct_dependents"]}
    assert direct["web/src/mid.ts"]["confidence"] == "inferred"
    # leaf -> mid is confirmed, but mid -> target is inferred.
    assert transitive["web/src/leaf.ts"]["confidence"] == "inferred"
    assert transitive["web/src/leaf.ts"]["depth"] == 2


def test_transitive_path_is_fully_confirmed_when_every_hop_is(repo: Path):
    (repo / "pkg").mkdir()
    for rel in ("pkg/a.ts", "pkg/b.ts", "pkg/c.ts", "pkg/d.ts"):
        (repo / rel).write_text("export const v = 1;\n", encoding="utf-8")
    (repo / "pkg/b.ts").write_text('import { v } from "./a";\nexport const w = v;\n')
    (repo / "pkg/c.ts").write_text('import { w } from "./b";\nexport const q = w;\n')
    (repo / "pkg/d.ts").write_text('import { q } from "./c";\nexport const r = q;\n')
    index_repository(repo)
    result = _impact(repo, paths=["pkg/a.ts"], depth=3)
    transitive = {t["path"]: t for t in result["transitive_dependents"]}
    assert transitive["pkg/c.ts"]["confidence"] == "confirmed"
    assert transitive["pkg/d.ts"]["confidence"] == "confirmed"


def test_via_records_the_full_path_back_to_the_changed_file(repo: Path):
    _ts_repo(repo)
    result = _impact(repo, paths=["web/src/target.ts"], depth=3)
    transitive = {t["path"]: t for t in result["transitive_dependents"]}
    via = transitive["web/src/leaf.ts"]["via"]
    assert [step["from"] for step in via] == ["web/src/leaf.ts", "web/src/mid.ts"]
    assert via[-1]["to"] == "web/src/target.ts"
    assert transitive["web/src/leaf.ts"]["evidence"]["location"].startswith("web/src/mid.ts:")
