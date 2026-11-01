from __future__ import annotations

import os
import time
from pathlib import Path

from repograph.config import load_settings
from repograph.indexer import index_repository
from repograph.store import Store


def _stats(repo: Path):
    return index_repository(repo)


def test_initial_index_counts_and_exclusions(repo: Path):
    stats = _stats(repo)
    assert stats.files_scanned == 20
    assert stats.parse_errors == 1
    assert stats.added == 20
    with Store(load_settings(repo)) as store:
        assert store.stats()["files"] == 20
        assert store.stats()["tests"] == 3
        paths = {r["path"] for r in store.all_files()}
    assert "ignored/generated.py" not in paths
    assert "src/shop/broken.py" in paths


def test_incremental_noop_and_metadata(indexed: Path):
    stats = index_repository(indexed)
    assert (stats.added, stats.updated, stats.deleted) == (0, 0, 0)
    assert stats.unchanged == 20
    assert stats.duration_s >= 0


def test_incremental_modify_and_delete(indexed: Path):
    target = indexed / "src/shop/services/audit.py"
    target.write_text("def record(event: str, subject: str) -> None:\n    return None\n\ndef extra() -> int:\n    return 1\n")
    stats = index_repository(indexed)
    assert stats.updated == 1
    with Store(load_settings(indexed)) as store:
        assert store.symbols_by_name("extra")[0]["path"] == "src/shop/services/audit.py"

    target.unlink()
    stats = index_repository(indexed)
    assert stats.deleted == 1
    with Store(load_settings(indexed)) as store:
        assert store.symbols_by_name("extra") == []
        assert store.file_id("src/shop/services/audit.py") is None


def test_force_and_reset(indexed: Path):
    stats = index_repository(indexed, force=True)
    assert stats.updated == 20
    stats = index_repository(indexed, reset=True)
    assert stats.added == 20


def test_extractor_version_change_reindexes_everything(indexed: Path):
    # An upgrade that changes extraction must not leave files indexed by the
    # old logic: the fixture's broken file demonstrates the stale rows.
    with Store(load_settings(indexed)) as store:
        store.set_meta("extractor_version", "1")
        store.conn.commit()
    stats = index_repository(indexed)
    assert stats.updated == 20


def test_timestamp_only_change_is_skipped(indexed: Path):
    target = indexed / "src/shop/models.py"
    os_time = time.time() + 10
    target.touch()
    os.utime(target, (os_time, os_time))
    stats = index_repository(indexed)
    assert stats.updated == 0
    # Without --force the content hash still protects against false negatives.
    target.write_text(target.read_text() + "\nclass Extra(Base):\n    pass\n")
    stats = index_repository(indexed)
    assert stats.updated == 1


def test_parsing_never_executes_repository_code(repo: Path):
    marker = repo / "EXECUTED"
    (repo / "src/shop/evil.py").write_text(
        "open(r'%s', 'w').write('pwned')\n" % marker
    )
    index_repository(repo)
    assert not marker.exists()


def test_unreadable_or_vanished_file_does_not_abort(repo: Path):
    victim = repo / "src/shop/dynamic.py"
    victim.unlink()
    index_repository(repo)
    stats = index_repository(repo)
    assert stats.parse_errors <= 1
