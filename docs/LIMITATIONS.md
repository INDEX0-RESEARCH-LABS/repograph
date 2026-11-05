# Limitations and threat model

RepoGraph reports what static parsing can establish. It does not prove safety.

## Analysis limits

| Area | What is missed | Reported as |
| --- | --- | --- |
| Dynamic imports | Computed module paths, runtime loaders, plugin systems | `dynamic` import or `unresolved` |
| Reflection | `getattr`, string-based registries, decorators that construct behavior | Usually absent; not detectable in general |
| Dependency injection | Container wiring, runtime binding | Unresolved reference or no edge |
| Generated code | Files outside the index, code generated at build time | Missing from graph |
| External consumers | Packages, services or scripts outside this repository | Not modeled |
| Types and data flow | Whether a changed signature is actually compatible | Not modeled |
| Re-exports | Some chain re-exports can stop at the re-exporting file | `inferred`/`unresolved` |
| Framework routing | Only recognized decorator/call patterns | `heuristic` route or absent |
| Tests | Tests selected by imports/naming, not execution traces | `inferred` or absent |
| Test name matching | A generic stem (`index`, `main`, ...) only matches inside its own directory subtree; a distinctive stem still matches across trees, so unrelated same-named modules can be paired | `inferred` test list |
| Test selection | Measured **23% pooled file recall** (41/180 failing files) at a median 6.7% of files selected; 99.4% only if every disclosed reachable file is also run (98.9% of the suite) | `inferred` list, incomplete; `reachable but not selected` list printed |
| Parsing | Syntax errors, unsupported language features, huge files | `parse_errors` blind spot |
| Large change sets | Output lists are capped (symbols/transitive 200, tests 50, routes/models 100); the true totals and `output-truncated` blind spot are reported, but the detail is not | totals and `truncated` flags |

### Known language gaps

- **Python**: decorators that return replacements, metaclasses, `__getattr__`, module-level `__all__` indirection and namespace packages can defeat static binding.
- **TypeScript/JavaScript**: `export *` chains, path aliases not declared in `tsconfig`, bundler-only aliases, decorator metadata, nested `package.json` `exports` conditions and CommonJS function-expression exports are weak spots. The Express benchmark shows the last one directly: 142 files yielded only 63 symbols.
- **No other languages**: Go, Rust, Java, C/C++, Ruby, PHP and others are not parsed. Their files are ignored, so the graph can be very incomplete in polyglot repositories.

### Measured accuracy caveats

- The current unseen test (round 5: httpx, zustand, mocha) measured 98.3% precision (118/120 resolved edges; Wilson 94.1%–99.5%) and 93.7% estimated recall (118/126; Wilson 88.0%–96.8%). Round 4 (flask, vite, svelte) measured 100% precision and 94.3% recall on the earlier build.
- Two zustand edges are false internals: a root `tsconfig` alias is applied to example apps that pin the registry package. Fixed after reporting: aliases now follow the config's `include`, cross-package bare names need a workspace declaration, and the within-sample recheck leaves every previously correct sampled edge unchanged.
- Known recall gaps: JSON/config imports (all 8 round-5 misses), bundler-virtual specifiers and fixture packages nested below the package-discovery depth bound. Python bare imports from test/example roots and Node `#imports` maps were measured defects and are now resolved as `inferred` (see `research/EDGE_ACCURACY_RESULTS.md`, "Post-fix recheck"). Conditional `exports` targets beyond the package entry are still only approximated by path probing.
- Non-code assets (CSS, images, JSON), `.vue` SFCs and bundler-virtual specifiers (`?raw`, `?worker`, `?url`) are outside the code graph. They are reported unresolved, not silently dropped.
- Labelers were AI agents, not humans. Two independent labelers agreed on 94.09% of the round-5 sample and 91.5% of the round-4 sample; disagreements were adjudicated against the source.
- Three test repositories per round are not a random sample of all code. Do not extrapolate to polyglot or generated-code-heavy repositories.

### Benchmark caveats

- Numbers in the README come from one Linux x86_64 machine, Python 3.14.8, one run per repository. They are not a promise of performance on other hardware or repositories.
- `impact` timing uses the highest-inbound file at depth 2. Other queries and repositories vary.
- Star counts and competitor descriptions in `research/` are timestamped GitHub REST snapshots. They are not quality claims.
- The 2026-11-05 re-check (same five repositories, previous release vs current code, identical file sets) changed no internal edge counts. It moved 4 vue-core and 5 fastapi dynamic import rows to `external`, and upgraded 2 click edges from `python-project-root` (inferred) to `python-absolute-import` (confirmed). Absolute counts differ from the October table because upstream repositories moved; only the within-run deltas are comparable. Edge accuracy was not re-scored: the existing labels belong to other samples.

## Security model

### Assets

- Source code and repository metadata.
- Local credentials that may exist alongside the repository.
- The user's workstation and agent session.

### Trust boundaries

1. **Repository content is untrusted.** Source files, comments, README text, route strings and symbol names may contain hostile content. They are data, never instructions.
2. **The local MCP client is trusted** to the extent it can read the index and call read-only tools.
3. **The network is not used** by indexing, querying or the default server.

### Controls

- Indexing reads bytes and parses with tree-sitter. It never imports, evaluates or executes repository code. A regression test writes a file that would create a marker if executed and asserts the marker does not appear.
- Symlinked files are skipped by default. If `follow_symlinks` is enabled, resolved targets must remain inside the repository.
- Default exclusions cannot be removed by project config. User excludes are appended.
- Secret-shaped files (`.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `id_rsa`, `id_ed25519`, `.npmrc`, `.pypirc`) are never indexed or searched.
- File size, total file count and parse scope are bounded. One parse failure does not abort the index.
- SQL uses bound parameters. Only generated placeholder lists are interpolated.
- User-supplied impact paths are resolved and must stay within the repository; escapes return an error.
- The MCP server is read-only. It has no auth; HTTP mode is localhost by default and warns on non-loopback binds.
- Index files are local and gitignored by convention (`.repograph/`).

### Non-goals

- RepoGraph is not a sandbox for malicious repositories beyond the parsing boundary. It does not defend the host against a compromised Python/tree-sitter installation.
- It does not scan for secrets inside otherwise eligible source files. Exclusion is filename-based.
- It does not redact secrets from indexed source text. Do not index repositories whose source contains credentials.
- It does not authenticate MCP clients. Treat HTTP mode as a local-only developer tool.

## Reporting

See [SECURITY.md](../SECURITY.md). Do not include real secrets in a report.
