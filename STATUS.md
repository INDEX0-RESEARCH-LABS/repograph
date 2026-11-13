# Status report

**Date:** 2026-10-31
**Version:** 0.1.2 alpha
**Repository:** `/home/darion-dev/repograph` — published source at `https://github.com/INDEX0-RESEARCH-LABS/repograph`; 0.1.0–0.1.2 published to PyPI, not announced

## Bottom line

RepoGraph is a working local tool: it indexes real Python/TypeScript/JavaScript repositories, exposes a CLI and six MCP tools, and produces evidence-backed impact reports with explicit blind spots. The engineering baseline is tested.

**Accuracy — what can be cited:**  
Round 5 (httpx, zustand, mocha — never indexed or tuned against, October 2026): **98.3% precision on 120 resolved edges** (Wilson 94.1%–99.5%) and **93.7% estimated recall** (118/126; Wilson 88.0%–96.8%).

A second measurement in November 2026 against django, esbuild, and koa — also repos never previously used — found **0.999 precision / 0.979 recall** (run1, pre-fix, 2,427 GT edges verified by two independent methods). Two resolver bugs were found during that benchmark: chained `require('x').prop` and directory `require('../..')` via `package.json` main both produced no edge. After fixing them, run3 measured 1.000/1.000 on the **same** repos used to find the bugs. That is a development-set result; it cannot be cited as accuracy. **Held-out validation of the fixes is pending** (`benchmarks/compare/scripts/run_held_out_validation.sh`).

The **product claim is still only partly validated**. There is no user study and no evidence that the tool changes agent behavior. A five-pair agent pilot compared control against a prompt offering the RepoGraph CLI: both arms were perfect on grep-solvable rename tasks, and session transcripts show no treatment run actually invoked the tool, so the pilot measured prompt wording rather than graph access. Missing edges remain the main risk, not wrong ones. Setup now ships the agent instructions alongside the server, and a follow-up measurement in OpenCode shows they can fire without a filename: with the server but no instructions, 0 of 3 runs called a tool; with instructions, 4 of 4 did on a symbol-named task, and 3 of 3 on a prompt naming only the concept (`research/OPENCODE_MCP_RESULTS.md`). That is one client, one model and one repository, so it bounds a mechanism, not a rate. The competitive field is crowded, including projects already claiming evidence/confidence and impact analysis.

The **affected-tests gate failed its own pre-registered bar**. On 22 one-function mutations in click, Flask and packaging, `repograph tests` caught 41 of 180 failing test files (pooled recall 0.23, median 0.38) while selecting a median 6.7% of files. Unioned with every file it disclosed as reachable-but-unselected, recall reaches 179/180 — at 98.9% of the suite, so there is no saving. Static import-graph test selection is not viable as a gate here; the command is documented and shipped as a disclosure aid that must be backed by a full suite run (`research/TEST_SELECTION_GATE_RESULTS.md`).

## Implemented

### Indexing

- Repository scanner with fixed default exclusions, secret-shaped filename exclusions, symlink policy, size cap and file cap.
- tree-sitter extraction for Python, TypeScript, TSX, JavaScript, JSX and Prisma.
- Symbols, imports, references, decorators, HTTP routes, model tags.
- Static import resolution:
  - Python relative/absolute imports and `src` layouts;
  - TypeScript `tsconfig`/`jsconfig` aliases and workspace `package.json` names;
  - CommonJS `require`, dynamic `import()` and syntactic `importlib` calls.
- Incremental SQLite index (size/mtime then SHA-256), WAL, per-file transactions, parse-error retention.
- External, dynamic and unresolved imports kept distinct.

### Query and analysis

- Lexical symbol search and source/documentation text search.
- Definitions and resolved references with confidence/method.
- File dependency graph (`in`/`out`/`both`, depth 1–5).
- Cycle detection via iterative Kosaraju.
- Architecture summary: languages, layers, directories, hubs, entry points, routes, models.
- Impact analysis from paths, a symbol, or git worktree diff:
  - direct dependents (imports + references);
  - transitive dependents with chains;
  - related tests (import + naming rules);
  - affected routes and models;
  - documentation mentions;
  - confidence counts and structured blind spots;
  - caveats that state absence is not safety.
- Path containment for user-supplied impact paths.

### Interfaces

- Typer CLI: `init`, `setup`, `index`, `status`, `search`, `impact`, `tests`, `graph`, `refs`, `arch`, `serve`, `version`.
- JSON output for read commands.
- MCP stdio server and optional streamable HTTP (localhost default, no auth).
- Six tools: `search_symbols`, `find_references`, `get_dependency_graph`, `analyze_change_impact`, `find_related_tests`, `get_architecture_summary`.
- `REPOGRAPH_ROOT` support for `python -m repograph.mcp_server`.
- `repograph tests --diff` reports the test files a change reaches, the tests it cannot rule
  out (unparsed file, unresolved internal import, changed `conftest.py`, changed file not indexed),
  and the test files reachable through dependent modules that it did **not** select;
  `--strict` exits 3, and `--command` emits the pytest line for CI.
  It is a disclosure aid, not a gate: `research/TEST_SELECTION_GATE_RESULTS.md` measured pooled
  file recall of 0.23 (41/180) at a median 6.7% of files selected.
- `repograph setup` registers the server with Claude Code, Cursor, Codex or OpenCode and installs the agent
  instructions that make the tool get called: diff before writing, one-time `.bak`, idempotent
  re-runs, and a launch command verified to work from an unrelated working directory.

### Safety

- Indexing never imports or executes repository code; enforced by a test that would create a marker if executed.
- Symlinks skipped by default; opt-in targets must resolve inside the root.
- Default exclusions cannot be removed by project config.
- Secret-shaped filenames excluded.
- Bound SQL parameters.
- Read-only MCP tools.

## Verification

### Tests

```
80 passed
```

Coverage (direct in-process measurement):

```
TOTAL 2540 statements, 778 missed, 69%
```

The CLI and MCP server show 0% direct coverage because they are tested through subprocesses (`python -m repograph`, stdio MCP client). Their behavior is exercised; the coverage tool does not attribute it to those modules. Core modules: `impact.py` 94%, `indexer.py` 96%, `store.py` 94%, `resolve.py` 91%, `extract.py` 89%, `agent_setup.py` 87%, `test_gate.py` 94%.

Reproduce:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m pytest --cov=repograph --cov-report=term-missing
```

### Benchmarks

**Competitor head-to-head (2026-10-31).** On the same 22 mutations and 180 known-failing test
files, Graphify 0.9.99's `affected` (file seed, their best arm) caught 158/180 with 22 failing
files undisclosed; RepoGraph's impact caught 179/180 with 1 undisclosed, at a higher context
cost (median 90% vs 74% of test files named). Bare-name seeds at matched depth were close
(0.700 vs 0.711 pooled). Protocol and limits: `research/H2H_GRAPHIFY_VS_IMPACT.md`.

Measured 2026-10-27, Linux x86_64, Python 3.14.8, one run per repository. Raw JSON in `benchmarks/results/`.

| Repo | Files | Symbols | Internal imports | Parse errors | Cold | Incremental | DB | Impact |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| express | 142 | 63 | 46 | 0 | 0.282 s | 0.082 s | 176 KiB | 2.1 ms |
| click | 91 | 2,077 | 350 | 0 | 0.573 s | 0.056 s | 960 KiB | 18.4 ms |
| requests | 37 | 807 | 130 | 0 | 0.259 s | 0.041 s | 508 KiB | 8.2 ms |
| vue-core | 528 | 2,273 | 1,875 | 2 | 1.791 s | 0.244 s | 1,496 KiB | 22.4 ms |
| fastapi | 1,223 | 7,125 | 1,939 | 0 | 5.257 s | 1.101 s | 4,048 KiB | 82.1 ms |

Impact is the highest-inbound file at depth 2. Express (63 symbols from 142 JS files) and two Vue parse errors are documented weaknesses, not hidden.

Self-index: 22 Python files, 224 symbols, 1,972 refs, 50 resolved edges (0 unresolved, 0 dynamic), 0 parse errors, 0.38 s cold (CLI, interpreter start included), 288 KiB.

### Edge accuracy

Pre-registered protocol, two independent AI labelers per round. Round 5 used repositories never indexed or tuned against (httpx, zustand, mocha), with seed `20261029` and no resolver change until the round was reported.

| Repo | Resolved sample | Precision | Recall |
| --- | ---: | ---: | ---: |
| httpx | 30 | 100% | 100% |
| zustand | 60 | 96.7% | 100% |
| mocha | 30 | 100% | 78.9% |
| **overall** | **120** | **98.3%** (118/120) | **93.7%** (118/126) |

- Wilson 95%: precision 94.1%–99.5%, recall 88.0%–96.8%. Weighted: 99.5% / 98.5%.
- Labeler agreement 94.09% (12/203 disagreements), all adjudicated: 10 asset rows `unresolved_ok`, 2 zustand example rows `not_internal`, 8 mocha JSON `require`s `internal_missed`.
- `confirmed` 90/90 correct; `inferred` 28/30.
- Precision defect (fixed, rechecked): the root `tsconfig` alias was applied to `examples/*`, which pin the registry `zustand` package. Aliases now follow the config's `include`, and cross-package bare names resolve only for a package's own files or inside a declared workspace. Re-index: 2/2 audited errors now external, 118/118 correct sampled rows unchanged, zustand internal edges 72 → 69 (the third is the same mechanism, outside the sample), httpx/mocha counts unchanged.
- zustand has 5 parse errors in core files (`src/react.ts`, `src/vanilla.ts`, `src/traditional.ts`, `src/middleware/subscribeWithSelector.ts`, `tests/ssr.test.tsx`) from advanced type syntax; those files contribute no edges. mocha's 3 are intentionally broken fixtures.
- mocha's 8 misses are all JSON `require`s; mocha recall is reported separately rather than hidden by pooling.
- Round 4 (flask, vite, svelte, measured on 2026-10-27) recorded 100% precision (150/150) and 94.3% recall, after which twelve resolver fixes were tuned on its misses. Those numbers describe that build, not the current one.
- Post-fix recheck from round 4: Python project/conftest import roots and Node `#imports`/`exports` maps corrected 25 of the 29 misses with no change to the 150 previously correct sampled edges. Not a new estimate.
- Audit of the new inferred methods (Amendment 2): 38/40 correct, 95.0% (Wilson 83.5%–98.6%). The two wrong edges were type-only `#compiler` imports; the `types` condition is now preferred for `import type`, rechecked within the sample.
- Agent behavior: five paired rename tasks, both arms perfect. Transcripts show 0 of 5 treatment runs invoked RepoGraph and both arms used grep, so the pilot tested prompt wording, not graph access. No behavioral claim. See `research/AGENT_BEHAVIOR_PILOT.md`.

### Test selection

Measured against pytest outcomes, not against the tool's own logic: 12 symbols drawn by seed from Flask at `d086db8`, one literal-constant mutation each.

- 6 mutations produced failing tests; pooled **file recall 6/25 (24%)**, median 0.57, precision 6/36.
- Counting test files reached through direct/transitive dependents raises recall to 15/25 (60%), so the misses are a test-rule limitation, not a missing graph edge.
- Two defects identified: `--symbol` cannot disambiguate a name reused by tests (3 of 12 names), and `--symbol` analyses the whole defining file.
- This fails the pre-registered test-selection bar (recall ≥ 80%). Docs now state the list is incomplete and the suite is ground truth. See `research/TEST_SELECTION_RESULTS.md`.
- Fixes (symbol tie-break, test-module filter, reachability blind spot) leave recall at 24% but raise precision to 6/14 (42.9%) and disclose 15/15 missed failing files. Within-sample recheck, not a new estimate.

Full method and threats to validity: `research/EDGE_ACCURACY_RESULTS.md`. Raw artifacts: `benchmarks/eval/`.

## Research conclusions

- The agent and MCP ecosystem is large and active.
- The generic code-graph category is saturated; several competitors claim impact analysis, change-aware tests, evidence/confidence, and "every edge explained".
- RepoGraph has **no proven differentiation yet**. The defensible hypothesis remains narrow: auditable impact with explicit uncertainty. Accuracy data now supports the "auditable" part; user value is untested.
- No competitor was installed or benchmarked. All competitor capabilities are claims from GitHub descriptions.

## Documentation and materials

- `README.md` — usage, confidence model, benchmarks, limitations.
- `docs/ARCHITECTURE.md` — modules, schema, indexing, resolution, algorithms.
- `docs/MCP.md` — tool contracts and agent policy.
- `docs/LIMITATIONS.md` — analysis gaps, benchmark caveats, threat model.
- `SECURITY.md`, `CONTRIBUTING.md`, `ROADMAP.md`, `CHANGELOG.md`, `LICENSE`.
- `research/` — evidence, competitive analysis, technical landscape, opportunity analysis, hypotheses, validation plan, decision log, edge-accuracy protocol and results, agent-behavior pilot, market red-team (`MARKET_DEBATE.md`) the 2026-10 direction review (`DIRECTION_2026-10.md`) the growth teardown of comparable repositories (`GROWTH_TEARDOWN.md`), the `morluto/rea` teardown (`REA_TEARDOWN.md`), which amends the 30-day plan: installer-with-skill before registry publish, and the 2026-10-29 multi-agent review (`BRUTAL_REVIEW.md`), which finds the PR-comment positioning indefensible and recommends the affected-tests gate as the surviving direction.
- `benchmarks/` — reproducible script, raw results, method.
- `launch/` — strategy and draft announcement (not published).
- `.github/` — CI, issue templates, PR template.

## Not done

- User interviews, agent task evaluation, willingness-to-pay evidence.
- Closing the measured recall gaps (Python test/example roots, Node `#imports`, JSON/config imports).
- Independent human labeling or adjudication of the accuracy sample.
- Go/Rust/Java/Kotlin support.
- LSP/compiler-backed resolution.
- Call graphs, data flow, type compatibility.
- Semantic search or embeddings.
- Schema migrations.
- GitHub Action/pre-commit integration.
- Watch mode, daemon, editor integration.
- Public release, package publication or announcement (source is on GitHub).
- Windows/macOS testing.

## Known issues and limitations

- Static analysis only; dynamic targets, reflection, DI and external consumers are blind spots.
- CommonJS extraction is weak (Express benchmark).
- Test selection and route/model detection are heuristic.
- Diff analysis uses symbols already in the index; re-index first.
- Measured precision is high but sampled; recall has known gaps. Do not use as a blocking CI gate; re-index and verify before relying on an empty dependent list.
- One machine, one run benchmarks; not tested beyond 1,223 files.
- Coverage report understates CLI/MCP behavior due to subprocess testing.
- `parse_errors` retry behavior: a file with unchanged content and a prior parse error is skipped until content changes or `--force` is used.
- MCP HTTP mode has no authentication.

## Launch readiness

**Ready for an experimental, feedback-seeking release if the maintainer authorizes it.** Not ready for a "complete dependency coverage" or blocking-CI claim. The affected-tests gate is explicitly not a blocking-CI product: it measured 0.23 pooled recall.

Done:

1. Edge precision/recall on labeled development and unseen test corpora.
2. Clean wheel install in a fresh virtual environment.
3. Reproducible benchmark results.
4. CI passing on Python 3.10, 3.12 and 3.13 for commit `11b7bb7`.

Still blocking a stronger launch:

1. Agent-behavior evaluation (12 pre-registered tasks, with and without MCP).
2. At least one design partner using it on a real repository.
3. Explicit authorization to publish an announcement or package.

## Reproduce the prototype

```bash
cd /home/darion-dev/repograph
.venv/bin/python -m pytest
.venv/bin/python -m repograph index .
.venv/bin/python -m repograph status .
.venv/bin/python -m repograph impact src/repograph/impact.py --root .
.venv/bin/python -m repograph serve --root .
```

## Next action

Run Phase 2 of `research/VALIDATION_PLAN.md` with tasks that are not word-search-solvable, a treatment that requires the tool's use, and transcript verification that it was used. Token and tool-call counts are recoverable from session exports. The rename-based pilot never invoked the tool and is not sufficient. Before any new accuracy claim, collect a fresh unseen corpus; the post-fix recheck was within-sample. Do not add languages until then.
