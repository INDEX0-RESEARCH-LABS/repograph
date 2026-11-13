#!/usr/bin/env python3
"""Apply the pre-registered file selection rule (top-5 inbound + 5 random, seed=42)."""
import json, random, sqlite3, sys
from pathlib import Path

REPO_ROOTS = {
    "django": "/tmp/opencode/compare/repos/django",
    "esbuild": "/tmp/opencode/compare/repos/esbuild",
    "koa":    "/tmp/opencode/compare/repos/koa",
}
results = {}
for name, root in REPO_ROOTS.items():
    db = Path(root) / ".repograph/index.db"
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT f.path, COUNT(i.id) AS inbound FROM files f
        LEFT JOIN imports i ON i.target_file_id = f.id
        WHERE f.is_test = 0 GROUP BY f.id ORDER BY inbound DESC, f.path
    """).fetchall(); conn.close()
    all_non_test = [dict(r) for r in rows]
    top5 = all_non_test[:5]
    top5_paths = {r["path"] for r in top5}
    remainder = [r for r in all_non_test[5:] if r["path"] not in top5_paths]
    rng = random.Random(42)
    sample5 = rng.sample(remainder, min(5, len(remainder)))
    selected = top5 + sample5
    results[name] = {"top5": [r["path"] for r in top5], "random5": [r["path"] for r in sample5],
                     "all_selected": [r["path"] for r in selected]}
    for r in selected:
        tag = "TOP" if r["path"] in top5_paths else "RND"
        print(f"  [{tag}] {r['path']}  (inbound={r['inbound']})")
Path("selected_files.json").write_text(json.dumps(results, indent=2))
print("Saved selected_files.json")
