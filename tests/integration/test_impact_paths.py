from __future__ import annotations

from pathlib import Path

from repograph.config import load_settings
from repograph.impact import analyze_impact
from repograph.indexer import index_repository
from repograph.store import Store


def test_dotted_directory_is_not_stripped(repo: Path):
    path = repo / ".storybook" / "main.ts"
    path.parent.mkdir()
    path.write_text("export const config = {};\n", encoding="utf-8")
    index_repository(repo)

    with Store(load_settings(repo)) as store:
        result = analyze_impact(store, repo, paths=[".storybook/main.ts"])

    assert result["changed_files"] == [".storybook/main.ts"]
    assert result["target"]["missing_from_index"] == []


def test_leading_dot_slash_is_normalized(repo: Path):
    path = repo / ".storybook" / "main.ts"
    path.parent.mkdir()
    path.write_text("export const config = {};\n", encoding="utf-8")
    index_repository(repo)

    with Store(load_settings(repo)) as store:
        result = analyze_impact(store, repo, paths=["./.storybook/main.ts"])

    assert result["changed_files"] == [".storybook/main.ts"]
