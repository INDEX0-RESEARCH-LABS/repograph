from __future__ import annotations

from pathlib import Path

from repograph.config import load_settings
from repograph.impact import analyze_impact
from repograph.indexer import index_repository
from repograph.store import Store


def test_capped_lists_report_totals_and_a_blind_spot(repo: Path):
    core = repo / "core.py"
    core.write_text("".join(f"def fn_{i}() -> int:\n    return {i}\n\n" for i in range(250)),
                    encoding="utf-8")
    for i in range(51):
        (repo / "tests" / f"test_core_{i:02d}.py").write_text(
            "from core import fn_0\n\ndef test_it() -> None:\n    assert fn_0() == 0\n",
            encoding="utf-8")
    for i in range(201):
        (repo / f"dep_{i}.py").write_text("from core import fn_1\n", encoding="utf-8")
        (repo / f"leaf_{i}.py").write_text(f"from dep_{i} import fn_1\n", encoding="utf-8")
    index_repository(repo)

    with Store(load_settings(repo)) as store:
        file_id = store.file_id("core.py")
        for i in range(150):
            store.conn.execute(
                """INSERT INTO routes(file_id,method,path,handler,line,framework,confidence)
                   VALUES(?,?,?,?,?,?,?)""",
                (file_id, "GET", f"/r{i}", f"r{i}", 1, "test", "heuristic"))
            store.conn.execute(
                """INSERT INTO symbols(file_id,name,qualified_name,kind,start_line,end_line,
                                       start_col,end_col,tags,is_exported)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (file_id, f"Model{i}", f"Model{i}", "class", 1, 1, 0, 0, "db_model", 1))
        store.conn.commit()
        result = analyze_impact(store, repo, paths=["core.py"])

    assert result["target"]["symbols_total"] == 400
    assert len(result["target"]["symbols"]) == 200
    assert result["target"]["symbols_truncated"] is True

    assert result["transitive_dependents_total"] == 201
    assert len(result["transitive_dependents"]) == 200
    assert result["transitive_dependents_truncated"] is True

    assert result["related_tests_total"] == 51
    assert len(result["related_tests"]) == 50
    assert result["related_tests_truncated"] is True

    assert result["affected_routes_total"] == 150
    assert len(result["affected_routes"]) == 100
    assert result["affected_routes_truncated"] is True

    assert result["related_models_total"] == 150
    assert len(result["related_models"]) == 100
    assert result["related_models_truncated"] is True

    assert result["summary"]["transitive_dependents"] == 201
    assert result["summary"]["related_tests"] == 51
    assert result["summary"]["affected_routes"] == 150
    assert result["summary"]["related_models"] == 150

    blind = {b["kind"]: b for b in result["blind_spots"]}
    assert "output-truncated" in blind
    assert set(blind["output-truncated"]["items"]) >= {
        "transitive_dependents", "related_tests", "affected_routes",
        "related_models", "symbols",
    }
