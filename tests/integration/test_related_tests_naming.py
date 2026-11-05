from __future__ import annotations

from pathlib import Path

from repograph.config import load_settings
from repograph.impact import analyze_impact
from repograph.indexer import index_repository
from repograph.store import Store


def _impact(repo: Path, **kwargs) -> dict:
    with Store(load_settings(repo)) as store:
        return analyze_impact(store, repo, **kwargs)


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def test_generic_index_stem_only_matches_its_own_directory(repo: Path):
    _write(repo, {
        "web/src/a/index.ts": "export const a = 1;\n",
        "web/src/a/index.test.ts": 'import { a } from "./index";\n',
        "web/src/b/index.ts": "export const b = 1;\n",
        "web/src/b/index.test.ts": 'import { b } from "./index";\n',
        "web/tests/index.test.ts": "export const t = 1;\n",
    })
    index_repository(repo)

    result = _impact(repo, paths=["web/src/a/index.ts"], include_tests=True)

    tests = {t["path"]: t for t in result["related_tests"]}
    assert "web/src/a/index.test.ts" in tests
    assert "web/src/b/index.test.ts" not in tests
    assert "web/tests/index.test.ts" not in tests


def test_generic_stem_matches_a_test_in_a_parent_directory(repo: Path):
    _write(repo, {
        "web/src/a/index.ts": "export const a = 1;\n",
        "web/src/index.test.ts": "export const t = 1;\n",
    })
    index_repository(repo)

    result = _impact(repo, paths=["web/src/a/index.ts"], include_tests=True)

    assert "web/src/index.test.ts" in {t["path"] for t in result["related_tests"]}


def test_distinctive_stem_still_matches_across_trees(repo: Path):
    _write(repo, {
        "src/shop/services/billing.py": "def charge() -> None:\n    pass\n",
        "tests/test_billing.py": "def test_charge() -> None:\n    pass\n",
    })
    index_repository(repo)

    result = _impact(repo, paths=["src/shop/services/billing.py"], include_tests=True)

    assert "tests/test_billing.py" in {t["path"] for t in result["related_tests"]}


def test_name_matching_does_not_rescan_every_dependent_for_every_test(
        indexed: Path, monkeypatch):
    """Guards the O(tests x dependents) blow-up found on fastapi (12x impact)."""
    import repograph.impact as impact

    with Store(load_settings(indexed)) as store:
        core = store.conn.execute(
            """INSERT INTO files(path,lang,sha256,size,mtime,indexed_at)
               VALUES(?,?,?,?,?,?)""",
            ("core.py", "python", "0" * 64, 10, 1.0, "2026-01-01T00:00:00+00:00"),
        ).lastrowid
        for i in range(200):
            dep = store.conn.execute(
                """INSERT INTO files(path,lang,sha256,size,mtime,indexed_at)
                   VALUES(?,?,?,?,?,?)""",
                (f"dep_{i}.py", "python", "0" * 64, 10, 1.0,
                 "2026-01-01T00:00:00+00:00"),
            ).lastrowid
            store.conn.execute(
                """INSERT INTO imports(file_id,raw,module,line,target_file_id,
                                       confidence,method,kind,names,note)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (dep, "import core", "core", 1, core, "confirmed",
                 "python-absolute-import", "internal", "[]", ""),
            )
        for i in range(40):
            store.conn.execute(
                """INSERT INTO files(path,lang,sha256,size,mtime,indexed_at,is_test)
                   VALUES(?,?,?,?,?,?,?)""",
                (f"tests/test_dep_{i}.py", "python", "0" * 64, 10, 1.0,
                 "2026-01-01T00:00:00+00:00", 1),
            )
        store.conn.commit()

    calls = 0
    real_stem = impact._stem

    def counting_stem(path: str) -> str:
        nonlocal calls
        calls += 1
        return real_stem(path)

    monkeypatch.setattr(impact, "_stem", counting_stem)
    with Store(load_settings(indexed)) as store:
        result = analyze_impact(store, indexed, paths=["core.py"], include_tests=True)

    assert all(t["confidence"] == "inferred" for t in result["related_tests"])
    assert len(result["related_tests"]) == 40
    # 40 tests x 200 dependents would be 16k+ calls; grouping by stem keeps it
    # linear, well under the number of files involved.
    assert calls < 2000, calls
