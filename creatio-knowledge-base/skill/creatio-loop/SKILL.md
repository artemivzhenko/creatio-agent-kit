---
name: creatio-loop
description: The contract of the Creatio author/dev/tester loop - a task folder whose files are the protocol (task.md, questions.md, plan.md, schemas.json, report-N.md, success-report.md, failed.md), project.json with the environment and the package, the schema lock between tasks, the evidence rules and the proof tiers (unit, integration, probe, backend, process, ui). Read it with creatio-author or creatio-tester; use for "task folder", "report round", "acceptance criteria", "project.json", "schemas.json".
version: 3
---

# The author / dev / tester loop: the contract

One task, one human, three roles: the **author** analyses the task, asks the questions, writes the plan with its
acceptance criteria and judges what comes back; the **dev** builds the package artifacts the plan names; the
**tester** proves them. The dev and the tester never share a chat and communicate only through files in the task
folder. The author runs them as its subagents (since 2026-11-24: one session, the author spawns the dev and the
tester in turn and reads their reports) - or, when the human prefers three sessions, the human carries the task
between them. With subagents the MCP server runs with its `all` profile and the role split is the brief; with three
sessions the dev's starts with `CREATIO_KB_ROLE=dev` (the build tools) and the tester's with
`CREATIO_KB_ROLE=tester`. This file is the contract every role reads first; [creatio-author](../creatio-author/SKILL.md),
[creatio-dev](../creatio-dev/SKILL.md) and [creatio-tester](../creatio-tester/SKILL.md) say what each role does with it.

## Never

- The author never edits `task.md`, `questions.md` after the human answered, or any report; the dev never edits
  `plan.md` or the acceptance criteria - a plan change is the author's.
- The tester never changes package files, `plan.md` or the acceptance criteria. It reports.
- Nobody commits, branches or pushes to git: the human does.
- Nobody runs a destructive command on the environment (drop, delete of system data, restore,
  reinstall) or connects to an environment that is not the one in `project.json`.
- While `failed.md` exists in the task folder, the tester does not test that task.
- A `fail` without evidence is not a result. A free-text report is not a report.

## project.json

One file per project, outside git (it holds the password), path given to the author by the human and to the
dev and the tester by the author's brief. Template: [templates/project.example.json](templates/project.example.json). It names the
environment (clio name, url, login, password, platform version - clio's `describe-environment` prints it - whether it may be broken), the
package (name, schema prefix, workspace path, dependencies), the paths (the task folders, this
knowledge base, the test framework, the unit-test project), the read-only workspaces and the
project's own rules; since v2.1 also `package.consumers` (packages pushed and compiled with this
one, the test package among them), `environment.customLayer` (the customisation package, `Custom`
by default), `tests.runner` (the process or service that runs in-Creatio tests and its category
parameter), `sandbox` (the objects and record ids a case may write to) and `environment.kind` (`dev` on a site an
agent may change behind the business logic: `fire_timer` and the framework's `# dev-only` cases refuse without it). Credentials live here
only; the test framework's own config is produced from it by `project.py sync`. Every agent reads it before touching anything; values from it are never
copied into a repository file.

## The task folder

`<paths.tasks>/<NNN>-<slug>/`. Files are written in the language of `task.md`.

| File | Written by | When | Meaning |
|---|---|---|---|
| `task.md` | human | start | the business task, free form, numbered by the folder |
| `questions.md` | author, then human | before the plan | the author's questions, the human's answers under each; `No questions.` when none |
| `plan.md` | author | after the answers | how it will be built, the artifacts with how each is built (a kit tool, or `by hand` with the reason), the acceptance criteria table, the preconditions with the command that checks each |
| `schemas.json` | author | with the plan, kept current | `schemas`: every schema the task creates or changes - the lock other tasks check; `affects`: their dependents from `impact` |
| `evidence/` | tester | each run | command output behind every `fail` row |
| `report-1.md` … `report-3.md` | tester | a run with at least one `fail` or `blocked` | one row per criterion |
| `success-report.md` | tester | a run where every criterion passes | the task is done |
| `failed.md` | tester | the 4th failing run | where the result still diverges from the criteria; the human removes it |
| `retrospective.md` | the dev or the tester, when the author or the human asks | during or after the work | what went well and badly, the tools that misbehaved, what was done by hand, the scripts written, the tools missed, the Creatio platform facts learned - with evidence, platform not project, no real names; the prompt is [templates/retrospective.md](templates/retrospective.md) |

Templates for every file: [templates/](templates/).

## Lifecycle

1. The human writes `task.md`.
2. The author reads `project.json`, `task.md`, the knowledge base; writes `questions.md`; stops and says so in
   chat. The human answers in the same file (or in chat; the author copies them under the questions). An unattended
   run answers them as assumptions, marked so.
3. The author runs the layers probe for every schema the task replaces (a `Custom` layer goes into the questions),
   writes `plan.md` with its preconditions, the artifacts table and the acceptance criteria, and `schemas.json`,
   checks the lock (below). No approval step: the plan is built as written.
4. The author spawns the dev with the task folder. The dev runs the preconditions, builds, pushes, probes, runs its
   unit tests and reports. The author reviews the report against the plan, the push log and `verify_pushed`; a gap
   goes back to the same dev with the exact rows.
5. The author spawns the tester. The tester reads `task.md`, `questions.md`, `plan.md`, `schemas.json` and the
   previous reports; runs the preconditions first (a failed one is `blocked` before any criterion); writes and runs
   the tests of every criterion; writes `success-report.md` or the next `report-N.md`. Three reports and still red:
   `failed.md`.
6. The author reads the report: the `fail` rows with evidence go to the dev (back to 4); a row that reveals what the
   plan did not think of is the author's plan change or the human's question; `blocked` is the human's decision.
7. `success-report.md` closes the task; the author has the retrospective written and reports the outcome and its
   cost to the human. `failed.md` parks the task until the human deletes it (with the old reports, if a fresh count
   is wanted).

## Preconditions, answers, sub-criteria

A precondition is a fact the plan relies on, written as the command that checks it (`describe.py
layers UsrOrderPage -e dev` -> no `Custom` layer; `push.py ... --dry-run` -> no drift; the test
package installed). The dev runs them before building, the tester as its first step. The
human's answers are a file, not a chat: given in chat, the author copies them under the question
in `questions.md` before the plan. A criterion the tester can only half prove is split by the
author into `AC-05a`, `AC-05b` when asked; the tester proposes the split in the report and never
applies it.

## The schema lock

A task is **active** while its folder has no `success-report.md`. The lock is per schema; a push
is per package - `push.py` stops when the package holds uncommitted files of another active task. Before creating or changing
a schema, the author reads `schemas.json` of every other active folder under `paths.tasks`; a
schema listed there belongs to that task - the author stops and asks the human instead of
touching it. `schemas.json` is updated the moment the scope grows. Its `affects` lists the
dependents of those schemas (`describe.py impact <workspace> <Schema>... --tasks <paths.tasks>
--current <folder> --md` prints both the `## Impact` table of `plan.md` and the `affects:` line):
a schema another active task *changes* while this task *affects* it, or the reverse, is a
conflict the command reports with exit 1 - the author stops and asks the human; `affects` alone
is a heads-up, not a lock.

## Acceptance criteria

`plan.md` carries them as a table: `AC-nn`, the action, the expected result, the tier. The
tester picks the tool; the tier says what kind of proof is enough.

| Tier | Proves | Typical tool |
|---|---|---|
| unit | a class in `Files/cs` behaves, with no environment | `dotnet test tests/<Pkg>/` (get_recipe `clio-tests-and-devops`, "Unit tests without an instance") |
| integration | a test that runs inside Creatio, where the project keeps a test base (`BaseTest`, a category, a runner process or service named in `project.json` `tests.runner`) | `unit.py run -e <env> --category <Cat>` (tools/env), evidence from its JSON |
| probe | the artifact landed on the environment as written | `objects.py probe`, `rules.py probe`, `sqlscripts.py probe`, `proc.py probe` |
| backend | listeners, triggers, defaults - the effect of a CRUD operation | a backend case of the test framework: `insert` / `update` / `delete` over OData, `check-record`, `check-count` |
| process | a process started with parameters returns the expected results and records | a process case: `start`, `check-result`, `check-record` |
| ui | the page behaves as a user sees it | `.act` cases: validate, then a live run |

## Evidence

A `pass` row cites the command and its decisive line. A `fail` or `blocked` row cites a file in
`evidence/` with the full output (`evidence/AC-03-report-2.txt`). `blocked` means the criterion
cannot be tested or contradicts `task.md`; it is the human's decision, the tester states why.
Results vocabulary, nothing else: `pass` | `fail` | `blocked` | `not tested`.

## Two write paths

The kit is files-first: a schema is a package file, pushed by `push_package`, verified by `verify_pushed`. clio's MCP
server (registered by `agent_setup.py`) is DB-first: `create-entity-schema`, `sync-schemas`, `create-page` write to the
site. In a loop task clio writes to the site only data, rights, system settings and pages validated by `validate-page`;
a schema clio wrote on the site comes back through `export-schema` or `pkg-to-file-system` before the push, or
`plan.md` declares the task DB-first and the push is not used. The two must not meet in one task without that line.

## Retrospective

When the author or the human asks (usually after `success-report.md`, sometimes mid-task), the dev or the tester writes `retrospective.md` from the
prompt in [templates/retrospective.md](templates/retrospective.md): ten sections, the platform facts with how each was
seen and on which version, nothing that identifies the project. It is the one file the human hands to other teams;
the kit's maintainers turn its facts into the platform facts register and its "by hand" and "missed tools" sections
into tools.
