from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repograph.impact import git_changes


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _init(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")


def test_pure_rename_is_delete_plus_add(repo: Path):
    (repo / "old_name.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _init(repo)
    _git(repo, "mv", "old_name.py", "new_name.py")

    changes = git_changes(repo)

    assert "old_name.py" in changes["deleted"]
    assert "new_name.py" in changes["paths"]
    assert changes["lines"]["new_name.py"]


def test_top_level_directory_named_a_is_not_mangled(repo: Path):
    (repo / "a").mkdir()
    (repo / "a/mod.py").write_text("x = 1\n", encoding="utf-8")
    _init(repo)
    (repo / "a/mod.py").write_text("x = 2\n", encoding="utf-8")

    changes = git_changes(repo)

    assert changes["paths"] == ["a/mod.py"]
    assert changes["lines"]["a/mod.py"] == [1]


def test_unicode_filename_is_not_quoted(repo: Path):
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src/café.py").write_text("x = 1\n", encoding="utf-8")
    _init(repo)
    (repo / "src/café.py").write_text("x = 2\n", encoding="utf-8")

    changes = git_changes(repo)

    assert changes["paths"] == ["src/café.py"]


def test_path_with_spaces_is_reported_verbatim(repo: Path):
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src/my file.py").write_text("x = 1\n", encoding="utf-8")
    _init(repo)
    (repo / "src/my file.py").write_text("x = 2\n", encoding="utf-8")

    changes = git_changes(repo)

    assert changes["paths"] == ["src/my file.py"]


def test_deleting_one_of_two_functions_is_reported(repo: Path):
    target = repo / "pair.py"
    target.write_text("def keep() -> int:\n    return 1\n\ndef gone() -> int:\n    return 2\n",
                      encoding="utf-8")
    _init(repo)
    target.write_text("def keep() -> int:\n    return 1\n", encoding="utf-8")

    changes = git_changes(repo)

    assert "pair.py" in changes["paths"]
    assert changes["lines"]["pair.py"]


def test_deleting_a_block_inside_a_function_records_adjacent_lines(repo: Path):
    target = repo / "inner.py"
    target.write_text("def body() -> int:\n    x = 1\n    y = 2\n    return x\n", encoding="utf-8")
    _init(repo)
    target.write_text("def body() -> int:\n    x = 1\n    return x\n", encoding="utf-8")

    changes = git_changes(repo)

    assert "inner.py" in changes["paths"]
    assert set(changes["lines"]["inner.py"]) & {2, 3}


def test_deleting_the_first_lines_of_a_file_records_line_one(repo: Path):
    target = repo / "head.py"
    target.write_text("#1\n#2\ndef kept() -> int:\n    return 1\n", encoding="utf-8")
    _init(repo)
    target.write_text("def kept() -> int:\n    return 1\n", encoding="utf-8")

    changes = git_changes(repo)

    assert "head.py" in changes["paths"]
    assert 1 in changes["lines"]["head.py"]


def test_git_timeout_returns_an_error_dict(repo: Path, monkeypatch: pytest.MonkeyPatch):
    (repo / "x.py").write_text("x = 1\n", encoding="utf-8")

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=60)

    monkeypatch.setattr("repograph.impact.subprocess.run", boom)
    changes = git_changes(repo)

    assert changes["available"] is False
    assert "timed out" in changes["error"]
