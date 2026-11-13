# Resume text block — RepoGraph

**Use this version** (honest about what is and isn't held out):

---

**RepoGraph** — local code-graph and change-impact tool for AI coding agents
(Python, open-source, Apache-2.0)

Built a static analysis tool that answers "if I change this file, what else
might break?" — indexing Python and JavaScript/TypeScript repositories into a
local SQLite graph and returning direct/transitive dependents, related tests,
and routes, each with evidence (file, line, confidence label) and explicit
blind spots.

Measurement highlights:
- **0.999 precision / 0.979 recall** (unseen-repo baseline, pre-fix) on
  2,427 ground-truth direct-importer edges across django, esbuild, and koa
  — repositories never previously used in development. Ground truth built
  by two independent methods (ripgrep + Python `ast` module), 99.9%
  agreement rate.
- **98.3% precision** (118/120, Wilson 94.1–99.5%) and **93.7% recall**
  (118/126, Wilson 88.0–96.8%) on a separate unseen corpus (httpx, zustand,
  mocha), measured with a pre-registered protocol and independent AI labelers.
- Head-to-head against code-impact-mcp v1.6.10 and trace-mcp v3.44.0 on the
  same repos: repograph showed higher recall on Python (the other tools don't
  support it at graph depth) and comparable precision on JS/TS. Full results
  and threats to validity at `benchmarks/compare/RESULTS.md`.
- Found and fixed two resolver bugs during the head-to-head (chained
  `require('x').prop` and `require('../..')` → `package.json` main). Post-fix
  numbers on the same repos are 1.000/1.000 — a development-set result, not
  a held-out claim. Held-out validation is scripted and pending.
- 40-edge hand-check labeled during the benchmark. Labels applied by an AI
  agent; pending human spot-check before citing as independent validation.

github.com/INDEX0-RESEARCH-LABS/repograph

---

**What to remove if space is tight:**
Drop the two bullet points about hand-check and held-out validation — they are
accurate but long. Keep the 0.999/0.979 line and the "(unseen-repo baseline,
pre-fix)" qualifier.

**What must NOT be changed:**
Do not upgrade "unseen-repo baseline, pre-fix" to just "baseline" — that
hides the development-set caveat. Do not write 1.000/1.000 without
"development set, not held out."
