from __future__ import annotations

from pathlib import Path

from repograph.config import load_settings
from repograph.impact import analyze_impact
from repograph.store import Store

INDEXED_AT = "2026-01-01T00:00:00+00:00"


def _file(store: Store, path: str) -> int:
    return store.conn.execute(
        """INSERT INTO files(path,lang,sha256,size,mtime,indexed_at)
           VALUES(?,?,?,?,?,?)""",
        (path, "python", "0" * 64, 10, 1.0, INDEXED_AT),
    ).lastrowid


def _symbol(store: Store, file_id: int, name: str, line: int) -> int:
    return store.conn.execute(
        """INSERT INTO symbols(file_id,name,qualified_name,kind,start_line,end_line,
                               start_col,end_col,tags,is_exported)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (file_id, name, name, "class", line, line + 4, 0, 0, "", 1),
    ).lastrowid


def test_symbol_analysis_targets_only_that_symbol_and_its_references(indexed: Path):
    with Store(load_settings(indexed)) as store:
        models = _file(store, "src/models.py")
        _symbol(store, models, "LedgerEntry", 1)
        _symbol(store, models, "Billing", 10)
        use = _file(store, "src/use.py")
        store.conn.execute(
            """INSERT INTO refs(file_id,name,line,col,kind,confidence,method,
                                target_file_id,target_name)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (use, "Billing", 3, 4, "call", "confirmed", "python-ast",
             models, "Billing"),
        )
        store.conn.commit()

        result = analyze_impact(store, indexed, symbol="LedgerEntry")

    assert result["target"]["symbols_total"] == 1
    assert [s["name"] for s in result["target"]["symbols"]] == ["LedgerEntry"]
    # A reference to a different symbol in the same file is not evidence
    # about this change.
    assert result["direct_dependents"] == []
