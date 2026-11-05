from __future__ import annotations

import subprocess
from pathlib import Path

from repograph.config import load_settings
from repograph.impact import analyze_impact
from repograph.indexer import index_repository
from repograph.store import Store


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _init(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")


def _impact(repo: Path, **kwargs) -> dict:
    with Store(load_settings(repo)) as store:
        return analyze_impact(store, repo, **kwargs)


def test_file_edited_after_indexing_is_reported_as_stale(repo: Path):
    target = repo / "src/shop/services/audit.py"
    index_repository(repo)
    target.write_text(target.read_text() + "\n\ndef late() -> None:\n    pass\n")

    result = _impact(repo, paths=["src/shop/services/audit.py"])

    blind = {b["kind"]: b for b in result["blind_spots"]}
    assert "index-stale" in blind
    assert "src/shop/services/audit.py" in blind["index-stale"]["items"]


def test_file_created_after_indexing_is_reported_as_not_indexed(repo: Path):
    index_repository(repo)
    (repo / "src/shop/late.py").write_text("def late() -> None:\n    pass\n")

    result = _impact(repo, paths=["src/shop/late.py"])

    blind = {b["kind"]: b for b in result["blind_spots"]}
    assert "changed-files-not-indexed" in blind
    assert "src/shop/late.py" in blind["changed-files-not-indexed"]["items"]


def test_diff_auto_index_refreshes_stale_targets(repo: Path):
    target = repo / "svc.py"
    original = ("def first() -> int:\n    return 1\n" + "\n" * 30
                + "def second() -> int:\n    return 2\n")
    target.write_text(original, encoding="utf-8")
    _init(repo)
    index_repository(repo)
    # Push `second` far down and change it: with the old index the new hunk
    # lines fall outside every recorded symbol range.
    shifted = ("def first() -> int:\n    return 1\n"
               + "".join(f"# filler {i}\n" for i in range(20))
               + "\n" * 30
               + "def second() -> int:\n    return 99\n")
    target.write_text(shifted, encoding="utf-8")

    stale = _impact(repo, diff=True, auto_index=False)
    assert "second" not in {s["name"] for s in stale["target"]["symbols"]}
    assert "index-stale" in {b["kind"] for b in stale["blind_spots"]}

    fresh = _impact(repo, diff=True)
    assert "second" in {s["name"] for s in fresh["target"]["symbols"]}
    assert "index-stale" not in {b["kind"] for b in fresh["blind_spots"]}
