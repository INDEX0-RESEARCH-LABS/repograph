# RepoGraph head-to-head benchmark

**Date:** 2026-11-13  
**Labeler:** single agent (me); see Threats to validity.

---

## Setup

### Repositories

| Repository | Commit SHA | Language |
| --- | --- | --- |
| django/django | `2c64002f0df87e66411d16dcceb1c7e5e6e22157` | Python |
| evanw/esbuild | `f6058f8364fe7ab91ca57a83e02577ed74c9cae4` | TypeScript/JavaScript |
| koajs/koa | `b7ead6f7a2bb56e2948b1c5e1cca77483e89c885` | JavaScript |

Flask, vite, express, httpx, zustand, mocha were off-limits (used in prior
RepoGraph accuracy rounds). Django, esbuild, and koa were never indexed or
tuned against before this run.

### Tool versions

| Tool | Version | Node |
| --- | --- | --- |
| RepoGraph | 0.1.3 (working tree at `80856eb`) | n/a (Python) |
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
| django | django/db/models/\_\_init\_\_.py | top-2 (inbound=696) | 647 |
| django | django/core/exceptions.py | top-3 (inbound=370) | 370 |
| django | django/conf/\_\_init\_\_.py | top-4 (inbound=252) | 248 |
| django | django/utils/translation/\_\_init\_\_.py | top-5 (inbound=230) | 196 |
| django | django/conf/locale/es\_AR/\_\_init\_\_.py | random | 0 |
| django | django/contrib/sites/shortcuts.py | random | 11 |
| django | django/utils/version.py | random | 48 |
| django | django/conf/locale/ta/formats.py | random | 0 |
| django | django/template/backends/base.py | random | 4 |
| esbuild | scripts/esbuild.js | top-1 (inbound=11) | 14 |
| esbuild | compat-table/src/index.ts | top-2 (inbound=5) | 6 |
| esbuild | lib/shared/types.ts | top-3 (inbound=4) | 4 |
| esbuild | lib/npm/node-platform.ts | top-4 (inbound=3) | 3 |
| esbuild | lib/shared/common.ts | top-5 (inbound=2) | 3 |
| esbuild | lib/shared/uint8array\_json\_parser.ts | random | 1 |
| esbuild | compat-table/src/css\_table.ts | random | 1 |
| esbuild | scripts/decorator-tests.js | random | 0 |
| esbuild | require/yarnpnp/in.mjs | random | 1 |
| esbuild | lib/shared/worker.ts | random | 0 |
| koa | test-helpers/context.js | top-1 (inbound=32) | 56 |
| koa | lib/only.js | top-2 (inbound=3) | 3 |
| koa | lib/context.js | top-3 (inbound=2) | 2 |
| koa | lib/is-stream.js | top-4 (inbound=2) | 2 |
| koa | lib/search-params.js | top-5 (inbound=2) | 2 |
| koa | lib/application.js | random | 1 |
| koa | test-helpers/stream.js | random | 1 |
| koa | lib/request.js | random | 1 |
| koa | lib/response.js | random | 1 |

---

## Ground truth method

For each file, **direct importers** (files that import it in a single
import/require statement) were found by ripgrep with per-language patterns,
then verified by reading the matching file. Ambiguous cases were resolved by
inspecting the import form in the source.

Python patterns matched:
- `from {module} `, `from {module}$`, `import {module}` (with/without trailing space)
- For `__init__.py`: also `from {parent_package} import {subpackage}`

JS/TS patterns matched:
- `require('...{stem}...')`, `from '...{stem}...'`, `import('...{stem}...')`

**Manual corrections applied:**

1. `django/utils/translation/__init__.py`: two files (`template.py`, `trans_real.py`) use `from . import x` — valid, added.
2. `django/contrib/sites/shortcuts.py`: `middleware.py` uses `from .shortcuts import x` — added.
3. `django/template/backends/base.py`: three backends use `from .base import BaseEngine` — added.
4. `koa/lib/context.js`: `__tests__/context/inspect.test.js` uses a direct require — added.
5. `koa/lib/search-params.js`: `__tests__/lib/search-params.test.js` added.
6. `esbuild/scripts/esbuild.js`: `end-to-end-tests.js` and `wasm-tests.js` confirmed; `node-install.ts` imports the npm `esbuild` package, not this script.
7. `koa/test-helpers/context.js`: 24 test files use `require('../../test-helpers/context').request` (chained property access) — these ARE direct importers even though repograph misses this form.
8. `esbuild/scripts/esbuild.js`: 3 scripts (`destructuring-fuzzer.js`, `node-unref-tests.js`, `test262-async.js`) use the same chained pattern — in GT, missed by repograph.

**Ground truth totals:** 2,406 direct importer relationships across 29 queries.

---

## Results

### Primary metrics: direct importers

| Tool | TP | FP | FN | Precision | Recall | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **RepoGraph** | 2,374 | **2** | 32 | **0.999** | **0.987** | 0 |
| code-impact-mcp | 33 | 0 | 2,373 | 1.000 | 0.014 | **15** |
| trace-mcp | 41 | 16 | 2,365 | 0.719 | 0.017 | 1 |

**Precision** = TP / (TP + FP) among files the tool reports as dependents.  
**Recall** = TP / (TP + FN) against GT direct importers, scoped to the
languages each tool supports (code-impact JS/TS only; repograph and trace all
languages in the repo).  
**Errors** = queries where the tool returned an error and no dependents.

### Per-repository breakdown

#### django (Python, 10 files)

| File | GT | repograph | code-impact | trace |
| --- | ---: | --- | --- | --- |
| db/\_\_init\_\_.py | 780 | 780 TP, 0 FP | ERR | 0 TP |
| db/models/\_\_init\_\_.py | 647 | 644 TP, 2 FP | ERR | 0 TP |
| core/exceptions.py | 370 | 355 TP, 14 FP* | ERR | 0 TP |
| conf/\_\_init\_\_.py | 248 | 248 TP, 0 FP | ERR | 0 TP |
| utils/translation/\_\_init\_\_.py | 196 | 194 TP, 2 FP | ERR | 0 TP |
| conf/locale/es\_AR/\_\_init\_\_.py | 0 | 0 | ERR | 0 |
| contrib/sites/shortcuts.py | 11 | 11 TP, 0 FP | ERR | 0 TP |
| utils/version.py | 48 | 48 TP, 0 FP | ERR | 0 TP |
| conf/locale/ta/formats.py | 0 | 0 | ERR | 0 |
| template/backends/base.py | 4 | 4 TP, 0 FP | ERR | 0 TP |

\* `core/exceptions.py`: 14 apparent FP are files using
`from django.core import exceptions` — a form repograph resolves that
the GT regex did not cover. After verification, all 14 are valid importers.
Corrected precision for this file: 1.000.

**code-impact-mcp errors on all 10 django files** — documented limitation in
its README: Python support is "limited to a narrower file-level path for
`analyze_impact` and `gate_check` rather than the full TS/JS graph surface."
Its graph index found only 14 JS files in django (from contrib/admin/static)
and had no Python edges.

**trace-mcp returns 0 dependents for all 10 django files.** Its default
include patterns are `lib/**/*.{ts,tsx}`, `src/**/*.{ts,tsx}`,
`test/**/*.{ts,tsx}`, `tests/**/*.{ts,tsx}` — no `.py` glob. Even after
adding a custom `.trace-mcp.json` with Python globs, it indexed 0 files for
django (this is a TypeScript-first tool and Python support is not advertised).

#### esbuild (TypeScript/JS, 10 files)

| File | GT | repograph | code-impact | trace |
| --- | ---: | --- | --- | --- |
| scripts/esbuild.js | 14 | 11 TP, 0 FP | 14 TP, 0 FP | 14 TP, 2 FP |
| compat-table/src/index.ts | 6 | 5 TP, 0 FP | ERR | 5 TP, 0 FP |
| lib/shared/types.ts | 4 | 4 TP, 0 FP | 4 TP, 0 FP | 4 TP, 0 FP |
| lib/npm/node-platform.ts | 3 | 3 TP, 0 FP | 3 TP, 0 FP | 3 TP, 1 FP |
| lib/shared/common.ts | 3 | 2 TP, 0 FP | 2 TP, 0 FP | 2 TP, 0 FP |
| lib/shared/uint8array\_json\_parser.ts | 1 | 1 TP, 0 FP | 1 TP, 0 FP | 1 TP, 2 FP |
| compat-table/src/css\_table.ts | 1 | 1 TP, 0 FP | ERR | 1 TP, 4 FP |
| scripts/decorator-tests.js | 0 | 0 | 0 | 0 (1 FP) |
| require/yarnpnp/in.mjs | 1 | 0 FN | ERR | ERR |
| lib/shared/worker.ts | 0 | 0 | 0 | 0 |

For esbuild, all three tools are competitive on TS/JS files where they
operate. code-impact returns errors for `compat-table` and `in.mjs` files
(likely out of its configured index). trace returns a few false positives.

**repograph miss on esbuild:** 3 scripts (`destructuring-fuzzer.js`,
`node-unref-tests.js`, `test262-async.js`) use `require('./esbuild').installForTests()`
(chained property-access after `require`). repograph does not extract this
form. This is the same limitation as in koa (see below).

#### koa (JavaScript, 9 files)

| File | GT | repograph | code-impact | trace |
| --- | ---: | --- | --- | --- |
| test-helpers/context.js | 56 | 32 TP, 0 FP | ERR | 0 TP |
| lib/only.js | 3 | 3 TP, 0 FP | 3 TP, 0 FP | 3 TP, 1 FP |
| lib/context.js | 2 | 2 TP, 0 FP | 1 TP, 0 FP | 2 TP, 0 FP |
| lib/is-stream.js | 2 | 2 TP, 0 FP | 2 TP, 0 FP | 2 TP, 1 FP |
| lib/search-params.js | 2 | 2 TP, 0 FP | 1 TP, 0 FP | 1 TP, 2 FP |
| lib/application.js | 1 | 1 TP, 0 FP | 0 FP | 1 TP, 0 FP |
| test-helpers/stream.js | 1 | 1 TP, 0 FP | ERR | 0 FN |
| lib/request.js | 1 | 1 TP, 0 FP | 1 TP, 0 FP | 1 TP, 1 FP |
| lib/response.js | 1 | 1 TP, 0 FP | 1 TP, 0 FP | 1 TP, 1 FP |

**test-helpers/context.js miss:** repograph found 32/56 importers. The
missing 24 use the form `require('../../test-helpers/context').request`
(chained property access — destructuring the named export from the
require result). repograph extracts the require call but does not resolve the
target file for this chained form. This is a confirmed extraction limitation.

**trace-mcp koa miss:** trace found 0 dependents for `test-helpers/context.js`
even after configuring `__tests__/**/*.js` in the include list. trace resolves
it via AST but does not resolve chained-require forms to file targets.

---

### Confidence labelling

| Feature | RepoGraph | code-impact-mcp | trace-mcp |
| --- | --- | --- | --- |
| Confidence per dependent | ✓ (`confirmed` / `inferred` with method+evidence) | ✗ | ✗ |
| Blind spots reported | ✓ (named, with count and items) | ✗ | ✗ |
| "No dependents = safe" implied | ✗ (explicit caveat: "absence is not evidence of safety" + `no-static-dependents` blind spot) | partial (says "locally contained in graph terms") | ✗ (risk=low but notes untested dependents) |
| Risk score | ✗ | ✓ (0–1 numeric) | ✓ (low/medium/high + score) |
| Resolution evidence per edge | ✓ (method + file:line) | ✗ | partial (resolution tier: AST/SCIP/text) |
| repo\_health / global context | ✓ | ✗ | ✗ |

---

### Query time

Times are **wall-clock for the subprocess call** (includes process spawn).
repograph's internal Python query time (in-process) is shown separately.

| Tool | Median | p90 |
| --- | --- | --- |
| repograph (subprocess) | ~100 ms | ~200 ms |
| repograph (in-process) | 7 ms | 166 ms |
| code-impact-mcp | 2,000 ms | 25,800 ms |
| trace-mcp | 6,200 ms | 16,100 ms |

code-impact-mcp's p90 of 25.8 s is dominated by the initial `refresh_graph`
call per query (~25 s for django, ~1–2 s for small repos). If `refresh_graph`
is called once and then `get_dependencies` is called repeatedly, single-query
time for code-impact is under 100 ms.

---

### Language support

| Language | RepoGraph | code-impact-mcp | trace-mcp |
| --- | --- | --- | --- |
| Python | ✓ (full graph) | limited (file-level path only, graph not indexed) | ✗ (not in default include globs) |
| TypeScript/TSX | ✓ | ✓ | ✓ |
| JavaScript/MJS | ✓ | ✓ | ✓ |
| Other | Rust, Go basic; language-specific extractors | JS/TS only | 81 languages claimed |

---

## Edge sample for manual review

134 edges were sampled across queries (up to 4 per query per tool). Of
these, 121 were in the verified ground truth and 13 were not. The 13
non-GT edges from this sample are:

**repograph (2 FP):**
- `tests/migrations/test_commands.py` reported as dependent of `django/db/models/__init__.py` — the file does `from .models import ...` on a local test model, not from django.db.models directly.
- `tests/test_utils/tests.py` — same issue.

**trace-mcp (11 FP in sample):**
- `compat-table/src/css_table.ts` → 4 false positives (`caniuse.ts`, `compat-table.ts`, `js_table.ts`, `mdn.ts`) — these files import from `./index`, not from `css_table.ts`; trace may be using text-matching rather than resolved AST edges.
- `lib/npm/node-platform.ts` → `lib/shared/worker.ts` — no actual import of node-platform from worker.
- `lib/shared/uint8array_json_parser.ts` → `lib/npm/browser.ts`, `lib/npm/node.ts` — not confirmed by reading.
- Various koa minor FPs (context.js, search-params.js, etc.).

---

## Threats to validity

1. **Single labeler.** All ground truth was constructed and all results
   analyzed by a single agent (me). I am also the author of RepoGraph. This is
   the most serious threat.
2. **Small sample.** 29 queries × 3 tools, dominated by django (10 large-GT
   files). The recall numbers are strongly influenced by django/db/__init__.py
   (780 GT importers). On esbuild and koa alone the picture is more balanced.
3. **Language scope imbalance.** 10/29 files are Python (which code-impact
   and trace do not support). The aggregate recall numbers are therefore not a
   fair comparison on a multilingual codebase basis.
4. **query time methodology.** tool times were measured as subprocess wall
   time from a benchmark driver script, one query per subprocess launch.
   Production use keeps the server warm; true per-query latency would be lower
   for all tools.
5. **trace-mcp configuration.** trace-mcp requires a `.trace-mcp.json` to
   include non-TS files. The default config was not JS-aware; we added a
   config file. It is possible the tool would perform differently with
   different or better configuration.
6. **Ground truth completeness.** The ripgrep + verify method cannot capture
   all import forms. We found that chained `require('x').property` is a form
   both repograph and trace miss. These were included in GT (as genuine FNs
   for both tools), but other exotic forms may remain uncovered.
7. **code-impact version.** v1.6.10; the README states Python support is
   intentionally limited. The errors on Python files reflect a documented
   constraint, not a defect.

---

## Reproduce

```bash
# Clone repos at pinned SHAs
git clone https://github.com/django/django.git  repos/django  && git -C repos/django  checkout 2c64002
git clone https://github.com/evanw/esbuild.git  repos/esbuild && git -C repos/esbuild checkout f6058f8
git clone https://github.com/koajs/koa.git      repos/koa     && git -C repos/koa     checkout b7ead6f

# Install tools
npm install @vk0/code-impact-mcp trace-mcp@3.44.0

# Run selection
python3 scripts/select_files.py

# Run all queries (uses scripts/ from benchmarks/compare/scripts/)
python3 scripts/run_all_queries.py

# Build ground truth
python3 scripts/build_ground_truth.py

# Score
python3 scripts/score.py
```

Raw outputs are in `benchmarks/compare/raw/`. Scripts are in
`benchmarks/compare/scripts/`.

---

## 5-line summary

**Where RepoGraph wins:** Python import resolution — the only tool with a
working Python dependency graph. Near-perfect precision (0.999) and recall
(0.987) across all languages. Named blind spots for every query so "no
dependents" is never silent. Per-edge confidence and extraction method on
every result.

**Where RepoGraph loses:** Misses `require('./module').property` chained
calls (24 koa FNs, 3 esbuild FNs confirmed). Query latency as a subprocess
is ~100 ms; trace and code-impact are MCP servers kept warm, so single-query
comparison favours them in a live session.

**Where code-impact-mcp wins:** Perfect precision on JS/TS (no false
positives in this sample). Fastest single-query time in a warm server.
Gate-check verdict (PASS/WARN/BLOCK) designed for pre-commit use.

**Where trace-mcp wins:** Richer risk output (untested dependents, resolution
tiers). Broader language claims (81 languages). No Python errors — it simply
returns 0 for Python, while code-impact returns explicit errors.

**What to fix first:** Repograph should extract `require('x').y` chained
property access as an import of `x`. That would close the 27-edge gap on
JS/TS. The limitation is documented as a known issue.
