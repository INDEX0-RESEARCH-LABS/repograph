# Benchmarks

Measured, not estimated. Every number in `results/` was produced by `benchmark.py` on a real clone.

## Environment

- Date: 2026-10-27
- OS: Linux 7.2.5 (Omarchy), x86_64
- Python: 3.14.8
- Storage: local filesystem
- CPU/RAM: not recorded; results are machine-specific

## Method

For each repository:

1. Clone shallow (`--depth 1`) or use a local path.
2. Use the shallow clone, or copy a local repository into the work directory. Delete the copy's `.repograph/` to force a cold index. The source repository is never modified.
3. Time `index_repository` (cold).
4. Time an immediate second `index_repository` (incremental no-op).
5. Open the store and run:
   - 5 symbol searches for the most frequent symbol name (median);
   - 5 impact analyses on the file with the highest inbound import count, depth 2 (median);
   - one architecture summary;
   - one depth-1 dependency graph.
6. Read the database size including the WAL file.

The script does not average across runs. These are single-run numbers; a rigorous comparison should repeat runs and report ranges.

## Results

| Repository | Files | Symbols | Internal imports | Parse errors | Cold | Incremental | DB | Search (median) | Impact (median) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| express | 142 | 63 | 46 | 0 | 0.282 s | 0.082 s | 176 KiB | 0.2 ms | 2.1 ms |
| click | 91 | 2,077 | 350 | 0 | 0.573 s | 0.056 s | 960 KiB | 2.5 ms | 18.4 ms |
| requests | 37 | 807 | 130 | 0 | 0.259 s | 0.041 s | 508 KiB | 0.7 ms | 8.2 ms |
| vue-core | 528 | 2,273 | 1,875 | 2 | 1.791 s | 0.244 s | 1,496 KiB | 1.2 ms | 22.4 ms |
| fastapi | 1,223 | 7,125 | 1,939 | 0 | 5.257 s | 1.101 s | 4,048 KiB | 5.4 ms | 82.1 ms |

## What the numbers mean

- **Cold** includes scanning, parsing, resolution, reference binding and SQLite writes.
- **Incremental** is a no-op re-index: size/mtime checks, no parse. It is 4.5–6× faster than cold on these repositories.
- **Impact** is the highest-inbound file at depth 2, the worst case in the sample. Other files are faster.
- **Express** is a real quality signal: 142 JavaScript files produce only 63 symbols because CommonJS function-expression exports are poorly extracted. Fast indexing does not imply good analysis.
- **Vue core** produced 2 parse errors in this run. They are retained in the index as unparsed files and would appear in impact blind spots.

## Reproduce

```bash
.venv/bin/python benchmarks/benchmark.py \
  --clone https://github.com/fastapi/fastapi --name fastapi

.venv/bin/python benchmarks/benchmark.py \
  --repo /path/to/local/repo --name local
```

Clones land in `/tmp/opencode/repograph-bench/<name>`. Results are written to `benchmarks/results/<name>.json` and printed.

To rerun all five:

```bash
for spec in \
  "https://github.com/expressjs/express express" \
  "https://github.com/pallets/click click" \
  "https://github.com/psf/requests requests" \
  "https://github.com/vuejs/core vue-core" \
  "https://github.com/fastapi/fastapi fastapi"
do
  set -- $spec
  .venv/bin/python benchmarks/benchmark.py --clone "$1" --name "$2"
done
```

## 2026-11-05 hardening re-check

Same five repositories, re-cloned on 2026-11-05, indexed twice: once with the
previous release (0.1.3) and once with the current working tree, on identical
file sets. Absolute counts differ from the October table because the upstream
repositories moved; only the deltas below are comparable.

| Repository | Files | Internal edges (kind) | Δ | Dynamic | Δ | External | Δ | Unresolved | Δ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| express | 142 | 142 → 142 | 0 | 0 → 0 | 0 | 225 → 225 | 0 | 0 → 0 | 0 |
| click | 91 | 335 → 335 | 0 | 1 → 1 | 0 | 354 → 354 | 0 | 0 → 0 | 0 |
| requests | 37 | 120 → 120 | 0 | 2 → 2 | 0 | 193 → 193 | 0 | 1 → 1 | 0 |
| vue-core | 528 | 1,894 → 1,894 | 0 | 4 → 0 | −4 | 210 → 214 | +4 | 16 → 16 | 0 |
| fastapi | 1,223 | 1,911 → 1,911 | 0 | 174 → 169 | −5 | 2,128 → 2,133 | +5 | 158 → 158 | 0 |

What changed and why:

- **Dynamic → external (9 rows).** A dynamic `import("pkg")` / `importlib.import_module("pkg")`
  now keeps `kind=external` instead of being relabelled `dynamic`, so package
  dependencies are no longer counted as unresolved runtime targets.
- **Click confidence (2 rows).** Two example-app imports moved from
  `python-project-root` (inferred) to `python-absolute-import` (confirmed) after
  package aliases began coming from the indexed file set instead of the process
  working directory.
- **Internal edges unchanged on all five.** These repositories already resolved
  their `src`-layout Python imports and their `paths` aliases under the old
  rules, so the new `baseUrl`, `extends`, variant, and reference handling has no
  effect on them. The TypeScript config work is covered by unit tests, not by
  these corpora.

Impact timings after the re-check: express 3.1 ms, click 14.6 ms, requests 5.1 ms,
vue-core 19.9 ms, fastapi 56.8 ms (highest-inbound file, depth 2, median of 5).
An intermediate build regressed fastapi to 758 ms through quadratic test-name
matching; that was found by this re-run and fixed. Timings are single-machine and
not an accuracy claim.

## Edge accuracy

No new accuracy number was produced for this re-check. The samples behind the
rounds below predate these changes and their independent labels belong to those
samples, so re-scoring them would measure the old build. A fresh unseen-corpus
round is required before quoting accuracy for the current code.

Speed is not accuracy. The edge evaluation is separate:

- Protocol: `research/EDGE_ACCURACY_PROTOCOL.md`
- Results: `research/EDGE_ACCURACY_RESULTS.md`
- Harness: `benchmarks/edge_accuracy.py` (`sample`, `report`)
- Artifacts: `benchmarks/eval/` (samples, independent labels, weighted reports)

Round 5 (httpx, zustand, mocha — never indexed or tuned against): 118/120 sampled resolved edges correct (98.3% precision) and 93.7% estimated recall. Round 4 (flask, vite, svelte) recorded 150/150 and 94.3% on the earlier build. Development rounds and the pre-fix baseline are in the results document. The harness never labels anything; labels come from independent reviewers.

```bash
.venv/bin/python benchmarks/edge_accuracy.py sample \
  --repo fastapi=/tmp/opencode/repograph-bench/fastapi \
  --repo vue-core=/tmp/opencode/repograph-bench/vue-core \
  --repo express=/tmp/opencode/repograph-bench/express \
  --out benchmarks/eval/sample.jsonl

.venv/bin/python benchmarks/edge_accuracy.py report \
  --sample benchmarks/eval/sample.jsonl \
  --labels benchmarks/eval/labels-a.jsonl \
  --labels benchmarks/eval/labels-b.jsonl \
  --out benchmarks/eval/report.json
```

## Honest caveats

- These measure speed and index size. Accuracy is measured separately above.
- One machine, one run, no variance analysis.
- The largest repository is 1,223 files. This is not evidence of behavior at 100k files.
- Cloned repositories change over time; hashes are not pinned. Dates are in each JSON file.
- No competitor was benchmarked.
