# Roadmap

No dates. Items move when they are tested, not when they are announced.

## 0.1 — current alpha

- [x] Python, TypeScript, TSX, JavaScript and Prisma extraction via tree-sitter.
- [x] Incremental SQLite index with SHA-256 verification.
- [x] Python relative/absolute imports, `src` layouts, TypeScript aliases, workspace packages, `require` and syntactic dynamic imports.
- [x] Symbols, imports, references, routes and model tags.
- [x] Lexical symbol/source/documentation search.
- [x] File graph, cycles (Kosaraju), architecture summary.
- [x] Impact analysis with direct/transitive dependents, related tests, routes, models, confidence and blind spots.
- [x] Git worktree diff mapping.
- [x] Typer CLI and six-tool MCP server.
- [x] Unit, integration, CLI, MCP and security tests.
- [x] Reproducible benchmarks on five public repositories.
- [x] Edge-accuracy evaluation on development and unseen repositories (`research/EDGE_ACCURACY_RESULTS.md`).
- [x] Affected-tests gate measured against real pytest outcomes and **rejected**: 0.23 pooled file recall at 6.7% selected (`research/TEST_SELECTION_GATE_RESULTS.md`). The command ships as a disclosure aid that names the files it did not select.

## Not planned (measured and rejected)

- [ ] Static-graph test selection as a CI gate. Measured 0.23 pooled recall; running the disclosed reachable files instead selects 98.9% of the suite. Revisit only with an execution-trace or coverage-measured oracle, not another import-graph heuristic.

## 0.2 — precision before breadth

- [ ] Run held-out validation on three fresh repos; publish the number if it holds.
- [ ] CI/PR integration: `repograph impact --diff --fail-on-blind-spots` as a GitHub Actions step.
- [ ] Test-selection recall: investigate execution-trace or coverage-based approaches (static import graph measured at 0.23; not viable as a gate).
- [ ] Reduce unresolved imports on real repositories; publish unresolved-rate metrics per benchmark.
- [ ] Better CommonJS/ESM export handling, including `export *` chains and `package.json` `exports`.
- [ ] Improve TypeScript symbol extraction for arrow-function exports and default exports.
- [ ] Store and expose reference evidence for framework route handlers, not only the route line.
- [ ] Add changed-symbol impact when no resolved reference exists (currently a known blind spot).
- [ ] Add `--fail-on-unresolved` style CI guardrails for teams that want a strict mode.
- [ ] Add schema migration tooling instead of the current version-mismatch error.
- [x] Publish a precision/recall evaluation on a labeled set of import edges, including false positives.
- [x] Head-to-head comparison with code-impact-mcp and trace-mcp on three fresh repos (django, esbuild, koa). Pre-fix baseline: 0.999 precision / 0.979 recall. See `benchmarks/compare/RESULTS.md`.
- [ ] Close measured recall gaps: Python `tests/`/`examples/` roots, Node `#imports`, JSON/config imports, conditional `exports`.
- [ ] **Held-out validation of November 2026 fixes** (`benchmarks/compare/scripts/run_held_out_validation.sh`). Run on three repos never used in development. Required before citing post-fix numbers as accuracy.

## 0.3 — language and repository coverage

- [ ] Go extraction and module resolution.
- [ ] Rust extraction and Cargo workspace resolution.
- [ ] Java/Kotlin extraction for Spring-style routes and models.
- [ ] Nested/multi-root monorepo support with per-package configs.
- [ ] Configuration for generated directories and custom route patterns.
- [ ] Explicit cross-repository boundaries (no implicit merge).

## Later / exploratory

- [ ] LSP or long-running index server for editor integration.
- [ ] Tree-sitter query packs so language support can be extended without touching core Python.
- [ ] Call-graph depth beyond file imports, with clearly separate confidence.
- [ ] Change-impact reports as SARIF or GitHub annotations.
- [ ] Optional semantic retrieval, clearly separated from the deterministic graph.

## Explicit non-goals

- Executing or building the analyzed repository.
- Required cloud services or API keys.
- Claiming that a change is safe because the graph is empty.
- Replacing tests, type checkers or code review.
- A general-purpose RAG/vector database.

## Known gaps that block a 1.0

- No human-labeled or adjudicated accuracy set; current labels are from independent AI agents.
- Measured recall gaps remain in test/example import roots, `#imports`, config files and conditional exports.
- Dynamic and reflective code remains a blind spot by design, but its practical frequency is not measured.
- Only three first-class languages.
- No migration story for schema changes beyond `--force`.
- Single-machine SQLite only; no tested upper bound beyond the benchmark repositories.

See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) for the full list.
