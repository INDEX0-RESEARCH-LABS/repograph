from __future__ import annotations

import subprocess
from pathlib import Path

from repograph.config import load_settings
from repograph.impact import analyze_impact, git_changes
from repograph.indexer import index_repository
from repograph.store import Store


def _impact(repo: Path, **kwargs) -> dict:
    with Store(load_settings(repo)) as store:
        return analyze_impact(store, repo, **kwargs)


def test_direct_and_transitive_dependents(indexed: Path):
    result = _impact(indexed, paths=["src/shop/services/subscription.py"], depth=2)
    direct = {d["path"] for d in result["direct_dependents"]}
    transitive = {t["path"] for t in result["transitive_dependents"]}
    assert "src/shop/services/billing.py" in direct
    assert "src/shop/api/routes.py" in direct
    assert "src/shop/app.py" in transitive
    assert result["summary"]["changed_files"] == 1
    assert result["caveats"]


def test_changed_file_evidence_has_locations(indexed: Path):
    result = _impact(indexed, paths=["src/shop/services/subscription.py"])
    for dep in result["direct_dependents"]:
        assert ":" in dep["evidence"]["location"]
        assert dep["confidence"] in {"confirmed", "inferred"}
        for reason in dep["reasons"]:
            assert reason["evidence"]["location"]


def test_routes_and_models_are_reported(indexed: Path):
    result = _impact(indexed, paths=["src/shop/models.py"], depth=2)
    assert any(r["path"] == "/subscriptions/{subscription_id}/cancel"
               for r in result["affected_routes"])
    names = {m["name"] for m in result["related_models"]}
    assert {"Subscription", "Customer"} <= names
    assert all(m["confidence"] == "heuristic" for m in result["related_models"])


def test_related_tests_use_import_and_naming(indexed: Path):
    result = _impact(indexed, paths=["src/shop/services/subscription.py"])
    tests = {t["path"]: t for t in result["related_tests"]}
    assert "tests/test_subscription.py" in tests
    rules = {r["rule"] for r in tests["tests/test_subscription.py"]["rules"]}
    assert "test-imports-changed-file" in rules


def test_reachable_tests_are_disclosed_not_listed(repo: Path):
    """A test that reaches the change through another module is disclosed as a blind spot.

    tests/test_deep.py imports shop.api.routes, which imports subscription.py.
    No direct import edge exists from the test file to the changed file, so it
    must not be silently omitted: it appears in test-selection-reachability.
    """
    deep = repo / "tests" / "test_deep.py"
    deep.write_text("from shop.api.routes import refund\n\n"
                    "def test_refund() -> None:\n    assert refund()\n", encoding="utf-8")
    index_repository(repo)
    result = _impact(repo, paths=["src/shop/services/subscription.py"])
    tests = {t["path"] for t in result["related_tests"]}
    assert "tests/test_deep.py" not in tests
    blind = {b["kind"]: b for b in result["blind_spots"]}
    assert "tests/test_deep.py" in blind["test-selection-reachability"]["items"]
    assert blind["test-selection-reachability"]["count"] >= 1


def test_fixture_app_under_tests_is_not_a_selected_test(repo: Path):
    """`is_test_path` marks `tests/test_apps/**`, but pytest collects none of it."""
    app = repo / "tests" / "test_apps" / "cliapp" / "app.py"
    app.parent.mkdir(parents=True)
    app.write_text("from shop.services.subscription import cancel\n", encoding="utf-8")
    index_repository(repo)
    result = _impact(repo, paths=["src/shop/services/subscription.py"])
    assert "tests/test_apps/cliapp/app.py" not in {t["path"] for t in result["related_tests"]}
    assert "tests/test_subscription.py" in {t["path"] for t in result["related_tests"]}


def test_top_level_symbol_is_not_shadowed_by_a_test_local_class(repo: Path):
    """A test-local `class Subscription` must not make `--symbol Subscription` ambiguous."""
    shadow = repo / "tests" / "test_shadow.py"
    shadow.write_text("def test_local() -> None:\n"
                      "    class Subscription:\n        pass\n"
                      "    assert Subscription\n", encoding="utf-8")
    index_repository(repo)
    result = _impact(repo, symbol="Subscription")
    assert "error" not in result, result.get("candidates")
    assert result["target"]["paths"] == ["src/shop/models.py"]


def test_unresolved_external_and_parse_error_blind_spots(indexed: Path):
    result = _impact(indexed, paths=["src/shop/api/routes.py"])
    kinds = {b["kind"] for b in result["blind_spots"]}
    assert "external-imports" in kinds
    assert "repo-parse-errors" in kinds
    assert "absence of a relationship is not evidence" in result["caveats"][0].lower()


def test_no_static_dependents_is_not_safety(indexed: Path):
    result = _impact(indexed, paths=["src/shop/services/audit.py"])
    kinds = {b["kind"] for b in result["blind_spots"]}
    # audit.py is imported by subscription.py, so this one has dependents.
    assert "repo-parse-errors" in kinds
    result = _impact(indexed, paths=["src/shop/dynamic.py"])
    kinds = {b["kind"] for b in result["blind_spots"]}
    assert "no-static-dependents" in kinds


def test_symbol_target_and_ambiguity(indexed: Path):
    unambiguous = _impact(indexed, symbol="SubscriptionService.cancel")
    assert unambiguous["target"]["paths"] == ["web/src/domain/subscription.ts"]
    # A bare name prefers the top-level definition over a nested method with the
    # same name; this is the documented tie-break.
    bare = _impact(indexed, symbol="cancel")
    assert "error" not in bare
    assert bare["target"]["paths"] == ["src/shop/services/subscription.py"]
    missing = _impact(indexed, symbol="does_not_exist")
    assert "not found" in missing["error"]


def test_two_top_level_definitions_stay_ambiguous(repo: Path):
    """The tie-break only favours top level; two top-level matches still fail closed."""
    extra = repo / "src" / "shop" / "extra.py"
    extra.write_text("class Subscription:\n    pass\n", encoding="utf-8")
    index_repository(repo)
    result = _impact(repo, symbol="Subscription")
    assert "ambiguous" in result["error"]
    assert {c["path"] for c in result["candidates"]} == {"src/shop/models.py", "src/shop/extra.py"}


def test_file_cycles_are_visible_in_graph(indexed: Path):
    result = _impact(indexed, paths=["src/shop/services/billing.py"])
    assert result["changed_files"] == ["src/shop/services/billing.py"]
    assert "src/shop/services/subscription.py" in {
        d["path"] for d in result["direct_dependents"]
    }


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_git_diff_maps_hunks_to_symbols(indexed: Path):
    _git(indexed, "init")
    _git(indexed, "config", "user.email", "test@example.com")
    _git(indexed, "config", "user.name", "Test")
    _git(indexed, "add", "-A")
    _git(indexed, "commit", "-m", "initial")

    target = indexed / "src/shop/models.py"
    target.write_text(target.read_text() + "\n\nclass Extra(Base):\n    pass\n")
    changes = git_changes(indexed)
    assert changes["available"] is True
    assert "src/shop/models.py" in changes["paths"]
    assert changes["lines"]["src/shop/models.py"]

    index_repository(indexed)  # diff analysis reads symbols from the index
    result = _impact(indexed, diff=True, depth=1)
    assert result["source"] == "git-diff"
    names = {s["name"] for s in result["target"]["symbols"]}
    assert "Extra" in names
    assert "Subscription" not in names


def test_git_diff_reports_not_a_repository(indexed: Path):
    changes = git_changes(indexed)
    assert changes["available"] is False
    assert "not a git repository" in changes["error"]


def test_path_escape_is_rejected(indexed: Path):
    result = _impact(indexed, paths=["../../etc/passwd"])
    assert "error" in result


def test_pure_deletion_file_has_importers_as_dependents(repo: Path):
    target = repo / "src/shop/pair.py"
    target.write_text("def keep() -> int:\n    return 1\n\ndef gone() -> int:\n    return 2\n",
                      encoding="utf-8")
    (repo / "src/shop/uses_pair.py").write_text(
        "from shop.pair import keep, gone\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    index_repository(repo)
    target.write_text("def keep() -> int:\n    return 1\n", encoding="utf-8")

    changes = git_changes(repo)
    assert "src/shop/pair.py" in changes["paths"]

    result = _impact(repo, diff=True)
    assert "src/shop/pair.py" in result["changed_files"]
    assert "src/shop/uses_pair.py" in {d["path"] for d in result["direct_dependents"]}


def test_deleted_function_is_reported_and_call_sites_are_marked(repo: Path):
    target = repo / "src/shop/services/audit.py"
    target.write_text(
        "def record(event: str, subject: str) -> None:\n    return None\n\n"
        "def unused() -> None:\n    return None\n",
        encoding="utf-8",
    )
    caller = repo / "src/shop/caller.py"
    caller.write_text(
        "from shop.services.audit import record\n\ndef run() -> None:\n    record('x', 'y')\n",
        encoding="utf-8",
    )
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    index_repository(repo)
    target.write_text("def unused() -> None:\n    return None\n", encoding="utf-8")

    result = _impact(repo, diff=True)
    removed = result["target"]["removed_symbols"]
    assert any(s["name"] == "record" and s["path"] == "src/shop/services/audit.py"
               for s in removed)
    blind = {b["kind"]: b for b in result["blind_spots"]}
    assert "removed-symbols" in blind
    reasons = [
        r for d in result["direct_dependents"] if d["path"] == "src/shop/caller.py"
        for r in d["reasons"]
    ]
    assert any(r["relation"] == "references-removed-symbol"
               and r["symbol"] == "record"
               and r["confidence"] == "confirmed"
               for r in reasons)
