# Outreach targets: 10 conversations, not a campaign

**Goal:** 10 cold users, measured by the bar already written down — **3 of 10 run it a second time**.
Nothing else. Stars, downloads and "looks cool" replies are not data.

**Rules**

- 1:1 messages only. No bulk mail, no list, no follow-up beyond one reminder.
- Ask for a wrong answer, not for support. "It was not useful" is a valid reply and is recorded as such.
- Never mention star counts, funding, roadmap or "launch". No urgency language.
- No telemetry is added to the tool. The measurement is the conversation.
- If they run it on a private repo and only report "works", that is a first run, not a second.

## Why these ten

Each was indexed during the benchmark work; the counts below were produced by
`repograph index` and `repograph status --json` on the repository, not estimated. All are public,
all are on a supported language, and all have tests the tool can see. They span 37 → 1,223 files so
the same question tests small and large repositories.

| # | Repository | Lang | Files | Symbols | Test files | Parse errors | Use it to ask |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `psf/requests` | Python | 37 | 807 | 15 | 0 | Smallest possible first run; "did the graph match your mental model?" |
| 2 | `pallets/click` | Python | 91 | 2,077 | 59 | 0 | `impact src/click/core.py` — 12 direct dependents, easy to check by hand |
| 3 | `pallets/flask` | Python | 83 | 1,622 | 48 | 0 | `impact src/flask/helpers.py` — 10 direct, 53 transitive |
| 4 | `encode/httpx` | Python | 60 | 1,241 | 37 | 0 | Async client internals; re-exports are the likely weak spot |
| 5 | `pypa/packaging` | Python | 74 | 2,397 | 35 | 0 | Dense pure-Python modules, no framework noise |
| 6 | `fastapi/fastapi` | Python | 1,223 | 7,125 | 667 | 0 | Scale: 5.3 s cold index on a real application codebase |
| 7 | `mochajs/mocha` | JS | 483 | 485 | 401 | 3 | Large JS suite; 3 parse errors are a real, disclosable gap |
| 8 | `vuejs/core` | TS/JS | 528 | 2,273 | 207 | 2 | TS monorepo layout; aliases and workspace resolution |
| 9 | `pmndrs/zustand` | TS/TSX | 51 | 179 | 15 | 5 | **Known weak.** 5 parse errors; ask which files it failed on |
| 10 | `expressjs/express` | JS | 142 | 63 | 92 | 0 | **Known weak.** CommonJS function-expression exports defeat symbol extraction |

Targets 9 and 10 are included because asking "why is this bad?" is more honest than only showing the
good cases, and because a maintainer who says "this is useless for CommonJS" has given a real answer.

## Who to message

Not "the maintainer" — find a person who already touched the code. Two ways, both using public data:

```bash
gh pr list -R pallets/click --state merged --limit 20 --json number,author,title,changedFiles
gh issue list -R psf/requests --state open --limit 20 --search "which tests"
```

Pick the author of a merged PR that changed a core module in the last few months. They have already
seen a real diff, so the question ("what did this change break?") is concrete for them.

## The message

Short, one ask, no pitch:

> Hi — I built a local code-graph tool (tree-sitter + SQLite, no network, no code execution). I am
> not looking for users, I am looking for wrong answers: would you run
> `curl -fsSL https://raw.githubusercontent.com/INDEX0-RESEARCH-LABS/repograph/main/install.sh | sh`
> (installs `repograph` in one line), then `repograph index .` and `repograph impact <a file you touched>`
> on one repository you know well and tell me one dependency it gets wrong? It takes about a minute.
> If it is not useful to you, saying so is also a useful reply.

If they reply "it worked", the follow-up is one sentence: *"Did you run it again after that? On what?"*
That answer, not the first run, is the metric.

## Tracking sheet

Fill this in by hand. Do not infer a "run" from a download.

| # | Repository | Person (handle) | Sent | Replied | First run | Second run | Wrong edge reported |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | psf/requests | | | | | | |
| 2 | pallets/click | | | | | | |
| 3 | pallets/flask | | | | | | |
| 4 | encode/httpx | | | | | | |
| 5 | pypa/packaging | | | | | | |
| 6 | fastapi/fastapi | | | | | | |
| 7 | mochajs/mocha | | | | | | |
| 8 | vuejs/core | | | | | | |
| 9 | pmndrs/zustand | | | | | | |
| 10 | expressjs/express | | | | | | |

## Decision rule

- **3+ second runs:** continue. The next work is precision on the reported wrong edges, not new features.
- **0–2 second runs:** stop. Write the result into `research/` and leave the project as a published
  negative result with a working tool — do not run a second round of outreach with softer wording.

Both outcomes are acceptable. Only an unmeasured outcome is not.
