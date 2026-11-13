# RepoGraph head-to-head benchmark

**Date:** 2026-11-13  
**Labeler:** single agent (benchmark author); see Threats to validity.

---

## Status

**Held-out validation: pending.**  
The numbers below come from django, esbuild, and koa — repositories used to
discover and fix resolver bugs during this session. Run3 (Precision 1.000 /
Recall 1.000) reflects fixes applied to those same repos and is a **development-set
result, not a held-out measurement**. It is reported here for transparency, not
as a headline claim. A held-out run on three fresh repositories is registered and
scripted (`scripts/run_held_out_validation.sh`) but has not yet been executed.

The **unseen-repo baseline** from before any fixes is **run1: Precision 0.999 /
Recall 0.979** on the same three repos, measured before any chained-require or
package-main fixes were applied. That is the number to quote until a held-out
round completes.

---

## Setup

### Repositories

These repos were chosen because they had never appeared in any prior RepoGraph
development or accuracy round. Flask, vite, express, httpx, zustand, and mocha
are all off-limits (used in earlier rounds).

| Repository | Commit SHA | Language |
| --- | --- | --- |
| django/django | `2c64002f0df87e66411d16dcceb1c7e5e6e22157` | Python |
| evanw/esbuild | `f6058f8364fe7ab91ca57a83e02577ed74c9cae4` | TypeScript/JavaScript |
| koajs/koa | `b7ead6f7a2bb56e2948b1c5e1cca77483e89c885` | JavaScript |

**After run1 was collected**, two resolver bugs were found by comparing against
the independent ground truth (Phase 2) and by running the hand-check (Phase 3):
1. Chained `require('path').prop` and `require('path').method()` produced no
   import edge.
2. `require('../..')` resolving to a package directory via `package.json` main
   was not handled.

Both were fixed on these same repos. Run3 measures the fixes on the **same**
repositories used to find them. It is reported for completeness; it is not an
independent evaluation.

### Tool versions

| Tool | Version | Node |
| --- | --- | --- |
| RepoGraph (run1) | working tree at `80856eb` | n/a (Python) |
| RepoGraph (run3) | working tree at `ba5fd0d` | n/a (Python) |
| code-impact-mcp (`@vk0/code-impact-mcp`) | 1.6.10 | 20.20.2 |
| trace-mcp | 3.44.0 | 22.23.5 (required ≥22) |

### File selection rule (pre-registered before any tool was run)

For each repository: sort all non-test files by inbound import count
(descending); take top 5. Sample 5 more from the remainder using
`random.seed(42)`. Record the list before querying any tool.

**Selection:**

| Repo | File | Selection | GT importers |
| --- | --- | --- | --- |
| django | django/db/\_\_init\_\_.py | top-1 (inbound=789) | 780 |
| django | django/db/models/\_\_init\_\_.py | top-2 (inbound=696) | 648 |
| django | django/core/exceptions.py | top-3 (inbound=370) | 369 |
| django | django/conf/\_\_init\_\_.py | top-4 (inbound=252) | 248 |
| django | django/utils/translation/\_\_init\_\_.py | top-5 (inbound=230) | 196 |
| django | django/conf/locale/es\_AR/\_\_init\_\_.py | random | 0 |
| django | django/contrib/sites/shortcuts.py | random | 11 |
| django | django/utils/version.py | random | 48 |
| django | django/conf/locale/ta/formats.py | random | 0 |
| django | django/template/backends/base.py | random | 4 |
| esbuild | scripts/esbuild.js | top-1 (inbound=11) | 14 |
| esbuild | compat-table/src/index.ts | top-2 (inbound=5) | 5 |
| esbuild | lib/shared/types.ts | top-3 (inbound=4) | 4 |
| esbuild | lib/npm/node-platform.ts | top-4 (inbound=3) | 3 |
| esbuild | lib/shared/common.ts | top-5 (inbound=2) | 2 |
| esbuild | lib/shared/uint8array\_json\_parser.ts | random | 1 |
| esbuild | compat-table/src/css\_table.ts | random | 1 |
| esbuild | scripts/decorator-tests.js | random | 0 |
| esbuild | require/yarnpnp/in.mjs | random | 0 |
| esbuild | lib/shared/worker.ts | random | 0 |
| koa | test-helpers/context.js | top-1 (inbound=32) | 56 |
| koa | lib/only.js | top-2 (inbound=3) | 3 |
| koa | lib/context.js | top-3 (inbound=2) | 2 |
| koa | lib/is-stream.js | top-4 (inbound=2) | 2 |
| koa | lib/search-params.js | top-5 (inbound=2) | 2 |
| koa | lib/application.js | random | 25 |
| koa | test-helpers/stream.js | random | 1 |
| koa | lib/request.js | random | 1 |
| koa | lib/response.js | random | 1 |

---

## Ground truth

**Method:** two independent passes.

**GT1** — ripgrep + manual file inspection. Each candidate import line was
read in the actual source file, not from snippets alone.

**GT2** — Python `ast` module (no regex) for Python files; regex +
`posixpath` resolver for JS/TS, independent of RepoGraph's resolver.

**Agreement rate: 2,425/2,427 = 99.9%** after adjudicating 10 disagreements.
Full adjudication log in `benchmarks/compare/ground_truth.json`.

**Corrections found during comparison:**
- 5 GT1 false positives removed: import patterns matched inside string literals
  (e.g. test scaffolding code that emits import statements as strings).
- 2 GT1 misses added: multi-line `from django.db import (..., models)` missed
  by ripgrep, confirmed by `ast`.
- 24 GT1 misses added: koa test files using `require('../..')` and `require('../')`
  resolved to `lib/application.js` via `package.json` main (GT1 grep missed
  this resolution path).

Final validated GT: **2,427 direct-importer edges** across 29 queries.

**Hand-check:** 40 edges (shuffled with seed=7) were labeled in
`benchmarks/compare/hand_check.csv`. Labels were applied by the benchmark
author (an AI agent). **These labels have not been independently verified by a
human.** The agent's labels agreed 100% with its own answer key
(`hand_check_key.csv`) — a result that proves internal consistency, not
correctness. Human spot-check of at least 15 rows is pending before this
check can be cited as independent validation. See the note at the bottom
of that file.

---

## Results

### Primary metric: direct-importer recall

**Headline number to cite (run1 — before any fixes, unseen repos):**

| Tool | Precision | Recall | FP | FN | Errors | Note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| **RepoGraph (run1)** | **0.999** | **0.979** | **0** | **51** | **0** | unseen repos, pre-fix baseline |
| code-impact-mcp | 1.000 | 0.268¹ | 0 | 90 | 15 | ¹JS/TS only; Python errors are documented behavior |
| trace-mcp (run2, fixed) | 0.992 | 0.105 | 2 | 2,171 | 0 | after proper `trace index` setup |

**Run3 — post-fix on the same repos (development set, not held out):**

| Tool | Precision | Recall | FP | FN | Note |
| --- | ---: | ---: | ---: | ---: | --- |
| RepoGraph (run3) | 1.000 | 1.000 | 0 | 0 | fixes found and applied on these same repos |

Run3 is reported for transparency. Because the bugs were found and fixed
using these repositories, run3 measures coverage of the development set,
not generalization. **Do not use run3 numbers as an accuracy claim.**

### What changed between run1 and run3

| Fix | FNs closed | Commit |
| --- | ---: | --- |
| Chained `require('path').prop` and bare `require('path').method()` | 27 | `f36a0e8` |
| `require('../..')` → `package.json` main (directory resolution) | 24 | `ba5fd0d` |
| **Total** | **51** | |

Zero new false positives introduced.

### Competitor setup notes (Phase 1 finding)

**trace-mcp run1 numbers were a setup failure.** Repos auto-registered but
"Last indexed: never" — the tool requires `trace index <dir>` before queries.
After correct indexing (run2), trace's precision improves from 0.702 → 0.992
and recall from 0.016 → 0.105. The original RESULTS.md reported the broken
numbers; they are preserved in `raw/run1/` but should not be cited.

**code-impact-mcp Python errors are documented behavior,** not
misconfiguration. Its README states Python support is limited to a
"narrower file-level path." 15 Django errors are correct responses.

### Per-repository detail (run1)

#### django (Python, 10 files)

| File | GT | repograph tp/fp | code-impact | trace-fixed |
| --- | ---: | --- | --- | --- |
| db/\_\_init\_\_.py | 780 | 780/0 | ERR | 25/0 (capped) |
| db/models/\_\_init\_\_.py | 648 | 648/0 | ERR | 25/0 (capped) |
| core/exceptions.py | 369 | 369/0 | ERR | 25/0 (capped) |
| conf/\_\_init\_\_.py | 248 | 248/0 | ERR | 25/0 (capped) |
| utils/translation/\_\_init\_\_.py | 196 | 196/0 | ERR | 25/0 (capped) |
| conf/locale/es\_AR/\_\_init\_\_.py | 0 | 0/0 | ERR | 0/0 |
| contrib/sites/shortcuts.py | 11 | 11/0 | ERR | 11/0 |
| utils/version.py | 48 | 48/0 | ERR | 24/1 |
| conf/locale/ta/formats.py | 0 | 0/0 | ERR | 0/0 |
| template/backends/base.py | 4 | 4/0 | ERR | 4/0 |

trace-mcp capped at 25 items per query (confirmed from `totalAffected` field;
not configurable in this version).

#### esbuild (TypeScript/JS, 10 files)

| File | GT | repograph | code-impact | trace-fixed |
| --- | ---: | --- | --- | --- |
| scripts/esbuild.js | 14 | 11/0 | 14/0 | 14/0 |
| compat-table/src/index.ts | 5 | 5/0 | ERR | 5/0 |
| lib/shared/types.ts | 4 | 4/0 | 4/0 | 4/0 |
| lib/npm/node-platform.ts | 3 | 3/0 | 3/0 | 3/0 |
| lib/shared/common.ts | 2 | 2/0 | 2/0 | 2/0 |
| lib/shared/uint8array\_json\_parser.ts | 1 | 1/0 | 1/0 | 1/0 |
| compat-table/src/css\_table.ts | 1 | 1/0 | ERR | 1/0 |
| scripts/decorator-tests.js | 0 | 0/0 | 0/0 | 0/0 |
| require/yarnpnp/in.mjs | 0 | 0/0 | ERR | ERR |
| lib/shared/worker.ts | 0 | 0/0 | 0/0 | 0/0 |

esbuild FN on run1: `destructuring-fuzzer.js`, `node-unref-tests.js`, `test262-async.js`
all use `require('./esbuild').installForTests()` — the chained form. Fixed in run3.

#### koa (JavaScript, 9 files)

| File | GT | repograph | code-impact | trace-fixed |
| --- | ---: | --- | --- | --- |
| test-helpers/context.js | 56 | 32/0 | ERR | 25/0 (capped) |
| lib/only.js | 3 | 3/0 | 3/0 | 3/0 |
| lib/context.js | 2 | 2/0 | 1/0 | 2/0 |
| lib/is-stream.js | 2 | 2/0 | 2/0 | 2/0 |
| lib/search-params.js | 2 | 2/0 | 1/0 | 2/0 |
| lib/application.js | 25 | 1/0 | 0/0 | 1/0 |
| test-helpers/stream.js | 1 | 1/0 | ERR | 1/0 |
| lib/request.js | 1 | 1/0 | 1/0 | 1/0 |
| lib/response.js | 1 | 1/0 | 1/0 | 1/0 |

koa FNs on run1: 24 test files using `require('../../test-helpers/context').request`
(chained form) and 24 using `require('../..')` → package main. Fixed in run3.

---

## Confidence labelling (feature comparison)

| Feature | RepoGraph | code-impact-mcp | trace-mcp |
| --- | --- | --- | --- |
| Confidence per dependent | ✓ (`confirmed`/`inferred` + method + file:line) | ✗ | ✗ |
| Blind spots reported | ✓ (named, with count and items) | ✗ | ✗ |
| "No dependents = safe" implied | ✗ (explicit caveat + `no-static-dependents` blind spot) | partial ("locally contained in graph terms") | ✗ |
| Risk score | ✗ | ✓ (0–1) | ✓ (low/medium/high) |
| Resolution evidence per edge | ✓ (method + file:line) | ✗ | partial (resolution tier) |

---

## Query time

Wall-clock subprocess time (includes process spawn). RepoGraph in-process
median: 7 ms. All tools were queried one file per process launch; a persistent
server would be faster for all three.

| Tool | Median | p90 |
| --- | --- | --- |
| repograph (subprocess) | ~100 ms | ~200 ms |
| repograph (in-process) | 7 ms | 166 ms |
| code-impact-mcp | 2,000 ms\* | 25,800 ms |
| trace-mcp | 6,200 ms | 16,100 ms |

\* code-impact includes `refresh_graph` per call (~25 s for django, ~1–2 s for
small repos). Single-query time after a warm `refresh_graph` is under 100 ms.

---

## Threats to validity

1. **Benchmark author is also the tool author.** I wrote RepoGraph and ran this
   benchmark. This is the most serious threat. No independent person has
   reviewed the methodology or spot-checked the results.

2. **Hand-check labels were applied by an AI agent (the benchmark author).**
   The 40 edges in `hand_check.csv` were labeled by the same agent that wrote
   the benchmark. The 100% agreement with the answer key proves only internal
   consistency. Human verification of at least 15 rows is needed before the
   hand-check can be cited as an independent validation.

3. **Small sample.** 29 queries × 3 tools, dominated by django (10 large-GT
   files). The recall numbers are strongly influenced by django/db/\_\_init\_\_.py
   (780 GT importers).

4. **Language scope imbalance.** 10 of 29 files are Python (which code-impact
   and trace do not support at the graph level). The aggregate recall for those
   tools reflects language scope, not algorithm quality on JS/TS.

5. **trace-mcp output cap.** `get_change_impact` returns at most 25 file names
   regardless of `max_dependents` parameter (confirmed from API response). The
   tool reports `totalAffected` correctly; only the listed names are capped.
   Recall on large-GT files is structurally limited.

6. **Ground truth completeness.** The ripgrep + ast method cannot capture all
   import forms. We discovered that chained `require('path').method()` and
   directory `require('../..')` via `package.json` main were missed during GT
   construction. These were added during Phase 2. Other exotic forms may remain.

7. **query time methodology.** One subprocess launch per query. Production use
   keeps servers warm; true per-query latency would be lower for all tools.

8. **Held-out validation is pending.** Until `benchmarks/compare/scripts/run_held_out_validation.sh`
   is run on fresh repos, run1 (0.999 / 0.979) is the best available unseen-repo
   estimate. Run3 numbers should not be cited as accuracy.

---

## Reproduce

```bash
# Pin repos at exact SHAs
git clone https://github.com/django/django.git  repos/django  && git -C repos/django  checkout 2c64002
git clone https://github.com/evanw/esbuild.git  repos/esbuild && git -C repos/esbuild checkout f6058f8
git clone https://github.com/koajs/koa.git      repos/koa     && git -C repos/koa     checkout b7ead6f

# Install tools
pip install repograph-codeintel
npm install @vk0/code-impact-mcp trace-mcp@3.44.0
# trace-mcp requires Node >=22; index each repo BEFORE querying:
trace index repos/django && trace index repos/esbuild && trace index repos/koa

# Run queries (saves to benchmarks/compare/raw/run1/)
python3 benchmarks/compare/scripts/run_all_queries.py

# Build independent GT
python3 benchmarks/compare/scripts/build_gt2.py

# Score
python3 benchmarks/compare/scripts/score.py

# Held-out round (new repos, not yet run)
bash benchmarks/compare/scripts/run_held_out_validation.sh /tmp/held_out
```

Raw outputs: `benchmarks/compare/raw/run1/` (original), `run2/` (trace fixed),
`run3/` (repograph post-fix on same repos).  
Answer key: `benchmarks/compare/hand_check_key.csv` (not to be opened until
human labels are collected independently).
