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
