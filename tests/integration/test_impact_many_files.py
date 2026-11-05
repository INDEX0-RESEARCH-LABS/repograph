from __future__ import annotations

from pathlib import Path

from repograph.config import load_settings
from repograph.impact import analyze_impact
from repograph.store import Store

# SQLite builds before 3.32 default to 999 bound variables per statement, and
# the repo is expected to run on stock system SQLite builds.
LIMIT = 900
INDEXED_AT = "2026-01-01T00:00:00+00:00"


class _ParamLimit:
    """Connection proxy that refuses statements with too many bound variables."""

    def __init__(self, conn, limit: int) -> None:
        self._conn = conn
        self.limit = limit

    def execute(self, sql, params=()):
        count = len(params) if not isinstance(params, dict) else len(params)
        assert count <= self.limit, (
            f"{count} bound variables in one statement (limit {self.limit})"
        )
        return self._conn.execute(sql, params)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


def _add_files(store: Store, paths: list[str]) -> dict[str, int]:
    ids: dict[str, int] = {}
    for path in paths:
        cur = store.conn.execute(
            """INSERT INTO files(path,lang,sha256,size,mtime,indexed_at)
               VALUES(?,?,?,?,?,?)""",
            (path, "python", "0" * 64, 10, 1.0, INDEXED_AT),
        )
        ids[path] = cur.lastrowid
    store.conn.commit()
    return ids


def _limit_connection(store: Store) -> _ParamLimit:
    proxy = _ParamLimit(store.conn, LIMIT)
    store.conn = proxy  # plain attribute, safe to replace
    return proxy


def test_many_changed_files_are_not_sent_in_one_statement(indexed: Path):
    targets = [f"pkg/mod_{i:04d}.py" for i in range(1000)]
    with Store(load_settings(indexed)) as store:
        _add_files(store, targets)
        _limit_connection(store)

        result = analyze_impact(store, indexed, paths=targets)

    assert result["changed_files"] == targets
    assert "error" not in result


def test_many_affected_dependents_are_not_sent_in_one_statement(indexed: Path):
    dependents = [f"pkg/dep_{i:04d}.py" for i in range(1000)]
    with Store(load_settings(indexed)) as store:
        ids = _add_files(store, ["core.py", *dependents])
        for path in dependents:
            store.conn.execute(
                """INSERT INTO imports(file_id,raw,module,line,target_file_id,
                                       confidence,method,kind,names,note)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (ids[path], "from core import x", "core", 1, ids["core.py"],
                 "confirmed", "python-absolute-import", "internal", "[]", ""),
            )
        store.conn.commit()
        _limit_connection(store)

        result = analyze_impact(store, indexed, paths=["core.py"])

    assert result["summary"]["direct_dependents"] == 1000
