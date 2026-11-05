from __future__ import annotations

from pathlib import Path

from repograph.config import load_settings
from repograph.impact import analyze_impact
from repograph.store import Store

INDEXED_AT = "2026-01-01T00:00:00+00:00"


def _file(store: Store, path: str) -> int:
    cur = store.conn.execute(
        """INSERT INTO files(path,lang,sha256,size,mtime,indexed_at)
           VALUES(?,?,?,?,?,?)""",
        (path, "python", "0" * 64, 10, 1.0, INDEXED_AT),
    )
    return cur.lastrowid


def _import(store: Store, file_id: int, module: str, line: int, kind: str) -> None:
    store.conn.execute(
        """INSERT INTO imports(file_id,raw,module,line,target_file_id,confidence,
                               method,kind,names,note)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (file_id, module, module, line, None, "unresolved", "python-relative-import",
         kind, "[]", "no module found"),
    )


def test_unresolved_and_dynamic_items_are_flagged_by_relevance(indexed: Path):
    with Store(load_settings(indexed)) as store:
        billing = _file(store, "src/billing.py")
        store.conn.execute(
            """INSERT INTO symbols(file_id,name,qualified_name,kind,start_line,end_line,
                                   start_col,end_col,tags,is_exported)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (billing, "Invoice", "Invoice", "class", 1, 5, 0, 0, "", 1),
        )
        _import(store, billing, "totally_unrelated", 1, "unresolved")
        _import(store, billing, "billing_impl", 2, "unresolved")
        _import(store, billing, "invoice_store", 3, "unresolved")
        _import(store, billing, "other", 4, "dynamic")
        _import(store, billing, "billing_worker", 5, "dynamic")
        store.conn.commit()
        expected = dict(store.conn.execute(
            "SELECT kind, COUNT(*) FROM imports WHERE kind IN ('unresolved','dynamic') GROUP BY kind"
        ).fetchall())

        result = analyze_impact(store, indexed, paths=["src/billing.py"])

    blind = {b["kind"]: b for b in result["blind_spots"]}
    # Repository-wide totals live in repo_health, not in this change's blind spots.
    assert "repo-unresolved-imports" not in blind
    assert "repo-dynamic-imports" not in blind
    assert result["repo_health"]["unresolved_imports"] == expected["unresolved"]
    assert result["repo_health"]["dynamic_imports"] == expected["dynamic"]
    assert result["repo_health"]["dynamic_imports"] >= 2

    unresolved = blind["unresolved-internal-imports"]["items"]
    # Related imports (stem `billing`, symbol `Invoice`) come first, and every
    # item says whether it plausibly touches the change.
    assert [(i["module"], i["related"]) for i in unresolved] == [
        ("billing_impl", True),
        ("invoice_store", True),
        ("totally_unrelated", False),
    ]
    dynamic = blind["dynamic-imports"]["items"]
    assert [(i["module"], i["related"]) for i in dynamic] == [
        ("billing_worker", True),
        ("other", False),
    ]
