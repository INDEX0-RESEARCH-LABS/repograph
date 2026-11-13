#!/usr/bin/env python3
"""Parse all raw tool outputs and score against ground truth.

Outputs:
  /tmp/opencode/compare/scores.json  — per-query per-tool scores
  /tmp/opencode/compare/edge_samples.json — 100-edge manual label set
"""
import json
from pathlib import Path

RAW = Path("/home/darion-dev/repograph/benchmarks/compare/raw")
GT = json.loads(Path("/tmp/opencode/compare/ground_truth.json").read_text())

SELECTED = {
    "django": [
        "django/db/__init__.py", "django/db/models/__init__.py",
        "django/core/exceptions.py", "django/conf/__init__.py",
        "django/utils/translation/__init__.py",
        "django/conf/locale/es_AR/__init__.py",
        "django/contrib/sites/shortcuts.py", "django/utils/version.py",
        "django/conf/locale/ta/formats.py", "django/template/backends/base.py",
    ],
    "esbuild": [
        "scripts/esbuild.js", "compat-table/src/index.ts",
        "lib/shared/types.ts", "lib/npm/node-platform.ts",
        "lib/shared/common.ts", "lib/shared/uint8array_json_parser.ts",
        "compat-table/src/css_table.ts", "scripts/decorator-tests.js",
        "require/yarnpnp/in.mjs", "lib/shared/worker.ts",
    ],
    "koa": [
        "test-helpers/context.js", "lib/only.js", "lib/context.js",
        "lib/is-stream.js", "lib/search-params.js", "lib/application.js",
        "test-helpers/stream.js", "lib/request.js", "lib/response.js",
    ],
}

# Build safe-name → (repo, file) lookup
safe_to_path = {}
for repo, files in SELECTED.items():
    for f in files:
        safe = f.replace("/", "__")
        safe_to_path[f"{repo}__{safe}"] = (repo, f)


# ── Parsers ───────────────────────────────────────────────────────────────────

def parse_repograph(data):
    if "error" in data and "direct_dependents" not in data:
        return None, data["error"]
    return [d["path"] for d in data.get("direct_dependents", [])], None


def parse_code_impact(data):
    if "error" in data and "get_dependencies" not in data:
        return None, data["error"]
    try:
        txt = data["get_dependencies"]["result"]["content"][0]["text"]
        parsed = json.loads(txt)
        if "error" in parsed:
            return None, f"tool: {parsed['error']}"
        return parsed.get("importedBy", []), None
    except Exception as e:
        return None, str(e)


def parse_trace(data):
    if "error" in data and "get_change_impact" not in data:
        return None, data["error"]
    try:
        txt = data["get_change_impact"]["result"]["content"][0]["text"]
        parsed = json.loads(txt)
        if "error" in parsed:
            return None, f"tool: {parsed['error']}"
        return [d["path"] for d in parsed.get("dependents", [])], None
    except Exception as e:
        return None, str(e)


PARSERS = {
    "repograph": parse_repograph,
    "code_impact": parse_code_impact,
    "trace": parse_trace,
}

# ── Load and parse ─────────────────────────────────────────────────────────────

tool_outputs = {}  # (repo, file, tool) → (deps_or_None, err_or_None)
query_times = {}

for jf in sorted(RAW.glob("*.json")):
    stem = jf.stem
    for tool in ("repograph", "code_impact", "trace"):
        if stem.endswith(f"__{tool}"):
            prefix = stem[: -len(f"__{tool}")]
            if prefix not in safe_to_path:
                continue
            repo, rel = safe_to_path[prefix]
            data = json.loads(jf.read_text())
            deps, err = PARSERS[tool](data)
            tool_outputs[(repo, rel, tool)] = (deps, err)
            # query time
            qt = data.get("_query_time_ms", 0)
            if isinstance(data.get("_meta"), dict):
                qt = data["_meta"].get("wall_s", 0) * 1000
            query_times[(repo, rel, tool)] = qt
            break

# ── Score ──────────────────────────────────────────────────────────────────────

TOOLS = ["repograph", "code_impact", "trace"]
scores = {}
edge_samples = []

for repo, files in SELECTED.items():
    for rel_file in files:
        key = f"{repo}::{rel_file}"
        gt_data = GT.get(repo, {}).get(rel_file, {})
        gt_all = {g.lstrip("./") for g in gt_data.get("verified_importers", [])}

        scores[key] = {}
        for tool in TOOLS:
            deps, err = tool_outputs.get((repo, rel_file, tool), (None, "not found"))
            qt = query_times.get((repo, rel_file, tool), 0)

            if deps is None:
                scores[key][tool] = {
                    "gt_total": len(gt_all), "reported": 0, "tp": 0, "fp": 0, "fn": len(gt_all),
                    "precision": None, "recall": None, "error": err, "query_ms": qt,
                }
                continue

            reported = {r.lstrip("./") for r in deps}

            # For code_impact: its graph is JS/TS only → scope GT to JS/TS too
            if tool == "code_impact":
                gt_scope = {f for f in gt_all if f.endswith((".js", ".ts", ".tsx", ".mjs", ".cjs"))}
            else:
                gt_scope = gt_all

            tp = len(reported & gt_scope)
            fp = len(reported - gt_all)   # FP against full GT
            fn = len(gt_scope - reported)
            prec = tp / (tp + fp) if (tp + fp) > 0 else None
            rec = tp / len(gt_scope) if gt_scope else None

            scores[key][tool] = {
                "gt_in_scope": len(gt_scope), "gt_total": len(gt_all),
                "reported": len(reported), "tp": tp, "fp": fp, "fn": fn,
                "precision": round(prec, 3) if prec is not None else None,
                "recall": round(rec, 3) if rec is not None else None,
                "error": err, "query_ms": round(qt, 1),
            }

            # Collect edge samples for manual review (capped at ~100 total)
            for dep in list(reported)[:4]:
                in_gt = dep in gt_all
                edge_samples.append({
                    "repo": repo, "target": rel_file, "dependent": dep,
                    "tool": tool, "in_gt": in_gt,
                })

Path("/tmp/opencode/compare/scores.json").write_text(json.dumps(scores, indent=2))
Path("/tmp/opencode/compare/edge_samples.json").write_text(json.dumps(edge_samples, indent=2))

# ── Summary tables ─────────────────────────────────────────────────────────────

print(f"\n{'Tool':<15} {'TP':>6} {'FP':>6} {'FN':>6} {'Precision':>10} {'Recall':>8} {'Errors':>7}")
print("─" * 65)
for tool in TOOLS:
    ttp = tfp = tfn = tgt = nerr = 0
    tms = []
    for key, td in scores.items():
        s = td.get(tool, {})
        ttp += s.get("tp", 0)
        tfp += s.get("fp", 0)
        tfn += s.get("fn", 0)
        tgt += s.get("gt_in_scope", s.get("gt_total", 0))
        if s.get("error") and s.get("reported", 0) == 0:
            nerr += 1
        tms.append(s.get("query_ms", 0))
    p = ttp / (ttp + tfp) if (ttp + tfp) > 0 else 0
    r = ttp / (ttp + tfn) if (ttp + tfn) > 0 else 0
    import statistics
    med = statistics.median(tms)
    print(f"{tool:<15} {ttp:>6} {tfp:>6} {tfn:>6} {p:>10.3f} {r:>8.3f} {nerr:>7}  (median query {med:.0f}ms)")

print(f"\nEdge samples collected: {len(edge_samples)}")
print(f"Distinct in-GT: {sum(1 for e in edge_samples if e['in_gt'])}")
print(f"Distinct not-in-GT (FP): {sum(1 for e in edge_samples if not e['in_gt'])}")
