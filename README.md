<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/hero-dark.svg">
    <img src="https://raw.githubusercontent.com/INDEX0-RESEARCH-LABS/repograph/main/docs/assets/hero.svg" alt="RepoGraph — local code graph and change impact analysis for AI coding agents" width="620">
  </picture>
</h1>

<p align="center">
  <a href="https://github.com/INDEX0-RESEARCH-LABS/repograph/actions/workflows/ci.yml"><img src="https://github.com/INDEX0-RESEARCH-LABS/repograph/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB" alt="Python 3.10+"></a>
  <a href="https://github.com/INDEX0-RESEARCH-LABS/repograph/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0"></a>
  <a href="https://github.com/INDEX0-RESEARCH-LABS/repograph/blob/main/STATUS.md"><img src="https://img.shields.io/badge/status-alpha-orange" alt="alpha"></a>
</p>

<p align="center">
  <b>See what a code change touches — before you ship it.</b><br>
  Local. No account, no API key, no code execution.
</p>

**RepoGraph is a local code graph and change impact analysis tool for AI coding agents.** It reads your repository, records what imports what, and answers one question:

> **"If I change this file, what else might break?"**

You get the files, tests and routes that depend on it. Every item carries its evidence (file and line) and a confidence label. It also tells you what it **could not see**.

```bash
repograph index .
repograph impact src/payments/refund.py
```

Real output from the test fixture, with the route and documentation-mention lines removed for length:

```
changed files (1): src/shop/services/subscription.py
changed symbols: 1
  function  cancel  src/shop/services/subscription.py:6

direct dependents (4):
  [confirmed] src/shop/__init__.py  (imports-changed-file at line 1)
  [confirmed] src/shop/api/routes.py  (imports-changed-file at line 3)
  [confirmed] src/shop/services/billing.py  (imports-changed-file at line 1)
  [confirmed] tests/test_subscription.py  (imports-changed-file at line 1)
transitive dependents: 1
  [confirmed] depth 2 src/shop/app.py

related tests (1):
  [inferred] tests/test_subscription.py  (test-imports-changed-file, test-name-matches-changed-file, test-name-matches-dependent)

blind spots:
  - repo-dynamic-imports (2): Dynamic imports exist in the repository; their runtime targets may include the changed files.
  - repo-parse-errors (1): Files with parse errors contribute no symbols or edges anywhere in the index.

note: absence of static evidence is not evidence of safety.
```

Python, TypeScript, JavaScript, JSX and TSX. Static analysis only. **Alpha.**

## Install

Python 3.10 or newer. Nothing else — no database server, no Docker, no cloud.

One line (installs [uv](https://docs.astral.sh/uv/) if needed, then `repograph`):

```bash
curl -fsSL https://raw.githubusercontent.com/INDEX0-RESEARCH-LABS/repograph/main/install.sh | sh
```

Then:

```bash
repograph index .
repograph impact src/payments/refund.py
```

Other options: `pipx install repograph-codeintel`, `pip install repograph-codeintel`, or `uvx --from repograph-codeintel repograph index .` (no install at all). Linux is tested in CI; macOS and Windows should work but are untested.

## Use

Run this inside **your** project:

```bash
repograph init .              # create .repograph/
repograph index .             # build the map
repograph status .            # check what was found
repograph impact src/app.py   # ask what depends on it
```

That is the loop. Re-index after you edit: `repograph index . && repograph impact --diff`.

If `repograph` is not found, activate the venv (`source .venv/bin/activate`). These commands only read files.

## Find the tests a change reaches

```bash
repograph tests --diff
```

On `pallets/click` (44 test files), changing `src/click/core.py`:

```
run these (6, 14% of 44):
  [inferred] tests/test_context.py  (test-imports-changed-file, test-name-matches-dependent)
  [inferred] tests/test_defaults.py  (test-imports-changed-file, test-name-matches-dependent)
  [inferred] tests/test_deprecations.py  (test-imports-changed-file, test-name-matches-dependent)
  [inferred] tests/test_parser.py  (test-name-matches-dependent)
  [inferred] tests/test_shell_completion.py  (test-imports-changed-file, test-name-matches-dependent)
  [inferred] tests/test_testing.py  (test-name-matches-dependent)

cannot rule out (0):

reachable but not selected (37):
  tests/conftest.py
  tests/test_abort_interrupt.py
  tests/test_arguments.py
  ...
```

`--command` prints only the pytest line, for CI. `--strict` exits `3` when a test cannot be ruled out or nothing was selected.

**Measured, and the number is bad.** On 22 one-function mutations across click, Flask and packaging, the selected set caught **41 of 180 failing test files (pooled recall 0.23, median 0.38)** while selecting a median 6.7% of test files. Adding every disclosed "reachable but not selected" file catches 179/180 — but that is 98.9% of the suite, i.e. no saving. Details: `research/TEST_SELECTION_GATE_RESULTS.md`.

So treat this command as **a disclosure aid, not a gate**: it tells you some files a change reaches, and it names the ones it cannot justify selecting. It does not know which tests exercise which behaviour, and it will omit files that fail. **Run the suite before trusting it.**

## Give it to your agent

One command registers the server **and** installs the instructions that make the agent actually use it:

```bash
repograph setup .
```

It writes a project `.mcp.json` plus a Claude Code skill (and a Cursor rule when `.cursor/` exists), shows the diff first, and backs up any file it changes. Add `--client codex` to register it in `~/.codex/config.toml`, or `--client opencode` to register it in `opencode.json` and write the instructions into `AGENTS.md`; `--dry-run` writes nothing.

Restart your agent, then ask:

> What breaks if I change the refund calculation?

Without the instructions an agent tends to keep grepping — a measured failure mode, not a guess. The skill tells it when the graph is the cheaper answer, in what order to call the tools, and to read `blind_spots` before acting.

<details>
<summary><b>Manual MCP config</b></summary>

```bash
repograph serve --root /path/to/your/project
```

```json
{
  "mcpServers": {
    "repograph": {
      "command": "repograph",
      "args": ["serve", "--root", "/absolute/path/to/your/project"]
    }
  }
}
```

Claude Code and Cursor accept this JSON shape. Use an absolute `--root` and put `repograph` on the client's `PATH`.

</details>

| Tool | What it returns |
| --- | --- |
| `analyze_change_impact` | Dependents, tests, routes, models and blind spots. |
| `find_related_tests` | Candidate tests. Heuristic — always run the suite. |
| `find_references` | Definition and resolved reference sites. |
| `get_dependency_graph` | What a file imports and what imports it. |
| `search_symbols` | Names with file and line. |
| `get_architecture_summary` | Languages, layers, hubs, entry points, routes, models. |

> **Security:** `serve --http` has **no authentication** and binds to `127.0.0.1` by default. Do not expose it to an untrusted network.

## What the labels mean

| Label | Plain meaning |
| --- | --- |
| `confirmed` | The code says it directly: a real import, or a call in the same file. |
| `inferred` | Worked out from project setup: a TypeScript alias or workspace package. |
| `heuristic` | A guess from patterns: route decorators, model base classes, test names. |
| `unresolved` | Seen in the code, but the target could not be found. Kept and reported. |

## How accurate is it?

Measured in October 2026 with a pre-registered protocol and two independent AI labelers, on three repositories never used to build the tool.

| Repository | Correct links (precision) | Links found (recall) |
| --- | ---: | ---: |
| [httpx](https://github.com/encode/httpx) (Python) | 100% (30/30) | 100% (30/30) |
| [zustand](https://github.com/pmndrs/zustand) (TypeScript) | 96.7% (58/60) | 100% (58/58) |
| [mocha](https://github.com/mochajs/mocha) (JavaScript) | 100% (30/30) | 78.9% (30/38) |
| **Overall** | **98.3%** (118/120) | **93.7%** (118/126) |

- 95% intervals: precision 94.1%–99.5%, recall 88.0%–96.8%.
- Both mistakes were one bug (a config alias leaking into example apps). Fixed and rechecked; the measured figure stays 118/120.
- All eight missed links were JSON files in mocha, which is why mocha's recall is shown on its own.
- Recall is an estimate, not a census. JSON/config imports, some Node aliases and non-code assets (`.css`, images, `.vue`) are not mapped.

Method, raw samples and threats to validity: [research/EDGE_ACCURACY_RESULTS.md](research/EDGE_ACCURACY_RESULTS.md).

## How fast is it?

One Linux machine, one run per project (Python 3.14.8, October 2026). Index step only.

| Repository | Files | Symbols | First index | Update (no changes) | Impact query |
| --- | ---: | ---: | ---: | ---: | ---: |
| [express](https://github.com/expressjs/express) | 142 | 63 | 0.28 s | 0.08 s | 2.1 ms |
| [click](https://github.com/pallets/click) | 91 | 2,077 | 0.57 s | 0.06 s | 18.4 ms |
| [vue-core](https://github.com/vuejs/core) | 528 | 2,273 | 1.79 s | 0.24 s | 22.4 ms |
| [fastapi](https://github.com/fastapi/fastapi) | 1,223 | 7,125 | 5.26 s | 1.10 s | 82.1 ms |

Express is a known weak spot: its CommonJS export style yields few symbols from many files. The report says so instead of hiding it.

## What it cannot do

- **No execution.** Reflection, computed imports and runtime wiring are invisible.
- **Two language families.** Python and JavaScript/TypeScript. Others are ignored.
- **No type checking or data flow.** It follows imports and names, not values.
- **Tests are heuristic.** A measured run on Flask found **24% of failing test files** (60% counting indirect dependents). Run the suite.
- **Routes and models are partial.** Common frameworks only.
- **An empty result is not proof.** It says "no dependents found", not "safe".

It is not a compiler, a type checker, a semantic search engine, or a replacement for tests.

<details>
<summary><b>All commands</b></summary>

| Command | What it does |
| --- | --- |
| `repograph init [path]` | Create `.repograph/` with a config file. |
| `repograph index [path]` | Build or update the map. `--force`, `--reset`, `--json`. |
| `repograph status [path]` | Counts, parse errors, whether an update is needed. |
| `repograph search <text>` | Find symbols and source text. `--kind`, `--limit`. |
| `repograph refs <name>` | Definition and the places that use it. |
| `repograph graph [path]` | Imports in, out or both. `--depth 1-5`, `--format dot`, `--cycles`. |
| `repograph arch` | Languages, layers, hubs, entry points, routes, models. |
| `repograph impact <paths>` | Dependents, tests, routes, blind spots. `--symbol`, `--diff`, `--depth`, `--tests/--no-tests`. |
| `repograph tests [paths]` | Test files a change reaches, files that cannot be ruled out, and reachable files not selected (heuristic; measured recall 0.23). `--diff`, `--base`, `--strict`, `--command`. |
| `repograph setup [path]` | Register the MCP server and install agent instructions. `--client`, `--yes`, `--dry-run`, `--no-skill`. |
| `repograph serve` | MCP server. `--http`, `--host`, `--port`. |

Every read command accepts `--json`.

</details>

<details>
<summary><b>Common problems</b></summary>

| Problem | Fix |
| --- | --- |
| `impact --diff` finds nothing | The edit is not indexed. Run `repograph index .` first. |
| Fewer symbols than expected | The code may use a pattern the parser does not cover. Check `status` and `arch` for parse errors. |
| A dependency is missing | It may be dynamic, unresolved, or in another language. Check the blind spots block. |
| MCP client cannot connect | Use an absolute `--root`, and put `repograph` on the client's `PATH`. |
| Agent never calls the tools | Re-run `repograph setup .`, restart the agent, and confirm the skill landed in `.claude/skills/repograph/SKILL.md`. |

</details>

## Project

- [STATUS.md](STATUS.md) — what is tested, measured and still missing.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — modules, schema, algorithms.
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md) — analysis gaps and security model.
- [research/](research/) — accuracy protocols, raw results, decision log.
- [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md)

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

75 tests, 69% direct coverage, CI on Python 3.10, 3.12 and 3.13. The CLI and MCP server are tested through subprocesses, so coverage does not attribute those runs to their modules.

Apache-2.0. See [LICENSE](LICENSE).
