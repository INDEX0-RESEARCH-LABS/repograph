# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project follows semantic versioning once it reaches 1.0.

### Added

- Read commands (`impact`, `search`, `refs`, `graph`, `arch`, `tests`) and MCP tools now re-index
  automatically when the index is missing or stale, so answers follow code changes without a
  manual `repograph index .`. `status` still reports staleness instead of hiding it.

- A bare `&` in JSX text (`Rated & Billed`) was reported as a parse error, though TypeScript
  and React accept it. The file is now re-parsed with a same-length substitute, so byte offsets
  and evidence stay exact. Found on a 223-file repository where it accounted for all 3 parse
  errors.
- Parse errors now name the line, `repograph status` lists the affected files, and
  `repograph index` reports the index's stored error count instead of only the errors from the
  files re-parsed in that run.
- An extractor-version marker re-reads the tree once after an upgrade, so files indexed by
  older extraction logic are corrected without `--force`.

## [0.1.2] — 2026-10-31

### Added

- `repograph setup --client opencode`: registers the MCP server in `opencode.json` using the
  argv-array shape OpenCode requires, and writes the agent instructions into `AGENTS.md` between
  markers. Measured: with the server but no instructions an OpenCode agent called the tools in
  0 of 3 runs; with instructions, 4 of 4 (`research/OPENCODE_MCP_RESULTS.md`).

### Fixed

- The MCP server no longer exits when the repository has no index. Exiting made clients report
  "connection closed", and the agent never saw the error telling it to run `repograph index`.
  Tools return that error instead.
- The agent instructions now list deleting a symbol or file as a reason to call
  `analyze_change_impact`; a deletion task measured 0 of 1 runs calling any tool before.

## [0.1.1] — 2026-10-31

Packaging fix only: the README rendered on PyPI pointed its hero image and two links at
relative paths, which do not resolve there. No code change.

## [0.1.0] — 2026-10-31

First public release (`repograph-codeintel` on PyPI).

### Added

- `repograph tests` prints `reachable but not selected`: test files that reach the change through dependent modules but are not in the selection. `select()` returns the same list as `reachable_not_selected` (`--json`).
- `benchmarks/test_selection/gate_measure.py` and `research/TEST_SELECTION_GATE_RESULTS.md`: 22 one-function mutations across click, flask and packaging scored against real pytest outcomes.
- Pre-registered edge-accuracy protocol, deterministic stratified sampler/reporter (`benchmarks/edge_accuracy.py`), independent labels and weighted precision/recall reports in `benchmarks/eval/`.
- `research/EDGE_ACCURACY_RESULTS.md`: baseline, development rounds and an unseen final test (flask, vite, svelte) with threats to validity.

### Changed

- Test selection is documented and shipped as a disclosure aid, not a gate: pooled file recall measured 0.23 (41/180) at a median 6.7% of files selected, below the pre-registered 0.80 bar. README, `STATUS.md`, `ROADMAP.md` and `docs/LIMITATIONS.md` now state the number and say to run the suite.

### Fixed

- `impact --symbol` prefers a top-level definition over a nested test-local symbol with the same name; two top-level matches stay ambiguous.
- `related_tests` lists only runnable test modules (`test_*`, `*_test.*`, `*.test.*`, `*.spec.*`, `conftest.py`), so fixture apps under `tests/` are no longer predicted as tests.
- Test files that reach a change through intermediate modules are disclosed in the `test-selection-reachability` blind spot (up to 50 paths) instead of being silently omitted or merged into the selection.
- Python bare imports of example/test applications now resolve through project roots (`pyproject.toml`, `setup.py`, `setup.cfg`, including `src` layouts) and `conftest` `syspath_prepend` directories, as `inferred`; ambiguous names stay unresolved.
- Node `#private` specifiers resolve from the nearest `package.json` `imports` map, including `*` keys and condition objects.
- Package entries that point at unbuilt `dist/…` output map back to `src/…`, so a package self-reference (for example `import "vite"` inside Vite) resolves.
- Whole-module `import type`/`export type` statements resolve the `types` condition of an `imports`/`exports` entry instead of the runtime entry (2 audited svelte `#compiler` edges). Value imports still choose the file that runs.
- Python stdlib names no longer bind to same-named repository files (`types` → `fastapi/types.py`), which produced 24 false edges.
- CommonJS `require('..')` now resolves the root `index.js` (96 Express imports).
- `.d.ts` files resolve for extensionless TypeScript imports (17 Vue misses).
- `tsconfig` glob aliases survive JSONC comment stripping (`"@vue/*"` was truncated as a comment).
- Workspace packages resolve subpaths and prefer source entries over unbuilt `dist` shims.
- ESM `./x.js` imports map to `x.ts`; `import pkg` binds `pkg/__init__.py` in `src` layouts.
- Directories named `env` are no longer excluded (`lib/env/data.js`).
- `from . import mod` no longer emits a duplicate package edge, while attribute imports keep the `__init__` edge.

#### Initial alpha (never published, 2026-10-27)

Local-only, read-only analysis.

#### Added

- Incremental SQLite index in `.repograph/index.db`, with SHA-256 checking, WAL mode and per-file transactions.
- tree-sitter extraction for Python, TypeScript, TSX, JavaScript, JSX and Prisma: symbols, imports, references, decorators, routes and model tags.
- Static import resolution for Python relative/absolute imports and `src` layouts; TypeScript `tsconfig` aliases and workspace packages; CommonJS `require`; syntactic dynamic imports.
- Four confidence classes (`confirmed`, `inferred`, `heuristic`, `unresolved`) and a separate `external` import class.
- Symbol search, source and documentation text search, definitions/references lookup.
- Dependency graph with direction and depth, cycle detection via Kosaraju, architecture summary with layers, hubs, entry points, routes and models.
- Change-impact analysis from paths, a symbol, or the git worktree diff: direct and transitive dependents, related tests, affected routes, related models, documentation mentions, confidence counts and explicit blind spots.
- Typer CLI: `init`, `index`, `status`, `search`, `impact`, `graph`, `refs`, `arch`, `serve`, `version`.
- MCP stdio and streamable-HTTP server with six read-only tools: `search_symbols`, `find_references`, `get_dependency_graph`, `analyze_change_impact`, `find_related_tests`, `get_architecture_summary`.
- Security controls: no code execution, symlink policy, fixed default exclusions, secret-shaped filename exclusions, size/file limits, path containment, bound SQL parameters.
- Tests covering extraction, resolution, scanning, incremental indexing, impact, CLI subprocess behavior, MCP stdio behavior and non-execution.
- Reproducible benchmark script and measured results for express, click, requests, vue-core and fastapi.

#### Known limitations

- Static analysis only; dynamic targets, reflection, runtime DI and external consumers are not modeled.
- Only Python and TypeScript/JavaScript have first-class support. Express-style CommonJS exports are weakly extracted.
- Test selection and route/model detection are heuristic.
- Diff analysis reads symbols from the index; re-index before analyzing fresh edits.
- No schema migration; a mismatch requires re-indexing.

[0.1.0]: https://github.com/INDEX0-RESEARCH-LABS/repograph/releases/tag/v0.1.0
