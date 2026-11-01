"""Incremental indexing pipeline."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .extract import extract
from .resolve import Resolver
from .scanner import read_source, scan
from .store import Store

TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e", "cypress"}
TEST_FILE_RE = (
    "test_", "_test.", ".test.", ".spec.", "conftest.py",
)

# Bumped whenever extraction changes what it produces. A mismatch re-reads the
# tree once, so an upgrade heals files that older logic recorded incorrectly
# (e.g. v2: bare "&" in JSX text was reported as a parse error).
EXTRACTOR_VERSION = "2"


def is_test_path(path: str) -> bool:
    parts = path.lower().split("/")
    base = parts[-1]
    if any(p in TEST_DIRS for p in parts[:-1]):
        return True
    return any(marker in base for marker in TEST_FILE_RE) or base.startswith("test_")


@dataclass
class IndexStats:
    files_scanned: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    parse_errors: int = 0
    duration_s: float = 0.0
    truncated: bool = False
    skipped_large: int = 0
    skipped_symlink: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    db_bytes: int = 0


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def index_repository(root: Path, *, force: bool = False, reset: bool = False,
                     settings: Settings | None = None) -> IndexStats:
    from .config import load_settings

    started = time.perf_counter()
    root = Path(root).resolve()
    settings = settings or load_settings(root)
    scan_result = scan(root, settings)
    entries = scan_result.files
    stats = IndexStats(
        files_scanned=len(entries),
        truncated=scan_result.truncated,
        skipped_large=scan_result.skipped_large,
        skipped_symlink=scan_result.skipped_symlink,
    )
    for e in entries:
        stats.languages[e.lang] = stats.languages.get(e.lang, 0) + 1

    with Store(settings) as store:
        store.init_schema(reset=reset)
        if reset:
            store.conn.execute("DELETE FROM files")
            store.conn.commit()
        store.set_meta("root", str(root))
        existing = store.existing_files()
        if existing and store.get_meta("extractor_version") != EXTRACTOR_VERSION:
            force = True
        scanned = {e.path: e for e in entries}

        for path in sorted(set(existing) - set(scanned)):
            store.delete_file(path)
            stats.deleted += 1

        pending: list[tuple] = []
        for e in entries:
            old = existing.get(e.path)
            if old and not force and old.size == e.size and old.mtime == e.mtime:
                stats.unchanged += 1
                continue
            data = read_source(root, e.path, settings)
            if data is None:
                stats.unchanged += 1
                continue
            sha = _sha(data)
            if old and old.sha256 == sha and not force:
                stats.unchanged += 1
                continue
            pending.append((e, data, sha, old))

        # Register every pending file first so import targets can be linked
        # even when target and source are indexed in the same run.
        pending_ids: dict[str, int] = {}
        for e, data, sha, old in pending:
            with store.tx():
                fid = store.upsert_file(e.path, e.lang, sha, e.size, e.mtime, None,
                                        is_test_path(e.path), _now())
                store.clear_children(fid)
            pending_ids[e.path] = fid

        resolver = Resolver(root, [(e.path, e.lang) for e in entries])

        for e, data, sha, old in pending:
            fid = pending_ids[e.path]
            result = None
            error = None
            try:
                result = extract(e.path, e.lang, data)
                error = "; ".join(result.errors) if result.errors else None
            except Exception as exc:  # keep indexing; one bad file is not fatal
                error = f"{type(exc).__name__}: {exc}"
                result = None

            with store.tx():
                store.clear_children(fid)
                if error:
                    stats.parse_errors += 1
                if result is not None:
                    for sym in result.symbols:
                        store.insert_symbol(fid, sym)
                    for route in result.routes:
                        store.insert_route(fid, route)
                    resolved = resolver.resolve(e.path, result.imports)
                    binding: dict[str, tuple[int | None, str | None, str]] = {}
                    for r in resolved:
                        target_id = store.file_id(r.target) if r.target else None
                        conf = r.confidence
                        method = r.method
                        if r.kind == "external":
                            target_id = None
                        store.insert_import(fid, r, target_id, conf, method, r.kind, r.note)
                        if target_id is None:
                            continue
                        for imported, local in r.names:
                            if not local or local == "*":
                                continue
                            target_name = None if imported in ("*", "default", "") else imported
                            binding.setdefault(local, (target_id, target_name, conf))

                    same_file = {}
                    for sym in result.symbols:
                        same_file.setdefault(sym.name, sym)
                    for ref in result.refs:
                        if ref.name in same_file:
                            confirmed = ref.kind == "call"
                            store.insert_ref(fid, ref, "confirmed" if confirmed else "inferred",
                                             "same-file-symbol" if confirmed else "same-file-name",
                                             fid, ref.name)
                        elif ref.name in binding:
                            target_id, target_name, conf = binding[ref.name]
                            store.insert_ref(fid, ref, conf, "import-binding", target_id,
                                             target_name or ref.name)
                        elif ref.receiver and ref.receiver in binding:
                            target_id, _, _ = binding[ref.receiver]
                            store.insert_ref(fid, ref, "inferred", "module-or-instance-attribute",
                                             target_id, ref.name)
                        else:
                            store.insert_ref(fid, ref, "unresolved", "unresolved-name", None, None)
                store.upsert_file(e.path, e.lang, sha, e.size, e.mtime, error,
                                  is_test_path(e.path), _now())
            if old is None:
                stats.added += 1
            else:
                stats.updated += 1

        with store.tx():
            store.set_meta("indexed_at", _now())
            store.set_meta("extractor_version", EXTRACTOR_VERSION)
        # Report the index's error count, not this run's: unchanged files keep
        # the errors they were indexed with, and "0" beside a non-zero status
        # is how users stop trusting the number.
        stats.parse_errors = int(store.conn.execute(
            "SELECT COUNT(*) FROM files WHERE parsed=0").fetchone()[0])
        store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        stats.duration_s = round(time.perf_counter() - started, 3)
        db = Path(settings.db_path)
        stats.db_bytes = sum(p.stat().st_size for p in (db, Path(str(db) + "-wal")) if p.exists())
    return stats


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
