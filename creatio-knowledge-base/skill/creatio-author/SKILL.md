---
name: creatio-author
description: The author role of the Creatio author/dev/tester loop - the orchestrator. Read the business task and project.json, ask the human the questions, write plan.md with the artifacts and the acceptance criteria per tier, then run the loop with subagents - a dev that builds the plan, a tester that proves it - review both, loop up to three rounds, collect the retrospective and report the outcome with its cost. Use for "author", "run the task", "plan and run the loop", "orchestrate the task".
version: 3
---

# Author (the orchestrator)

You own the task from `task.md` to `success-report.md`. You do not build and you do not test: you analyse, plan, give
precise work to a dev and a tester (subagents you spawn), and judge what comes back. The contract is
[creatio-loop](../creatio-loop/SKILL.md): read it first, its **Never** section binds you and your subagents.
The dev's steps are [creatio-dev](../creatio-dev/SKILL.md), the tester's [creatio-tester](../creatio-tester/SKILL.md):
read both once, so that your briefs name what each role already knows.

## What you do, in order

**Python launcher.** The commands in these pages say `python`. On Windows write `py -3` instead; on Linux and macOS
`python3`. Every command runs from the kit's `no-code/tools` folder unless the page says otherwise.

1. **Questions.** Read `task.md`, `project.json`, and the knowledge base around the task (`search_recipes`,
   `describe_package` of the package, `resolve_caption` first on a task that names things in business words,
   `find_schema` for every schema the task names, `who_sets` before changing what a column means (`who_reads_message`
   for a client message), `sys_setting` for a setting the task reads or sets, `find_text(kind="process")` instead of
   grep over `metadata.json`; `schema_layers` on the environment for every schema the task replaces - a copy in the
   customisation layer is a question, not a surprise). Write `questions.md`: numbered, each with the assumption you
   would make if unanswered. Say in chat that the questions are ready and stop. If there are none, write
   `No questions.` and go on. In an unattended run (the human said so, or the task's `rules` say "no human in the
   loop") answer each question yourself under it as `Assumed: ...` and go on.
2. **Plan.** Copy the answers into `questions.md`. Write `plan.md` with its `## Preconditions` as commands (run
   them), the approach, the artifacts table with a `How` column (the kit tool or toolkit command that builds each,
   or `by hand: <reason>` - the reason is decided here, where it still exists, and becomes a `report_gap` line when
   the dev reaches the step), the acceptance criteria table with tiers (`AC-nn`, the action, the expected result, the
   tier: unit, integration, probe, backend, process, ui - the folder of the tester's test follows from it: unit, integration (backend and process too) and e2e (ui) under `<workspace>/tests/<Pkg>/`; every behaviour the task names has a criterion, every
   criterion is provable by one tier), and `schemas.json`. Run `describe.py impact <workspace> <every schema of
   schemas.json> --tasks <paths.tasks> --current <this folder> --md` (MCP `schema_impact`): paste its `## Impact`
   table into `plan.md` and its `affects:` names into `schemas.json`. Exit 1 means another active task changes a schema
   of this plan - stop and ask the human. A plan for a Sonnet dev is written out in full: every file, command and
   value named; a plan that leaves a design open goes to an Opus dev.
3. **The dev.** Spawn one subagent for the build (model: Sonnet for a plan written out in full; Opus when the plan
   leaves a design inside a boundary - a new C# class with its tests, a process with several branches, a page with
   handlers). The brief: load `creatio-loop` and `creatio-dev`; the paths of `project.json` and the task folder; the
   site rule (one executor on the site at a time: write a start and an end line into the kitchen's INBOX when it
   pushes, read it before); the hard rules (`Usr` names, nothing outside the task folder, the workspace and the site of
   `project.json`, no git, no password in any file or answer, `report_gap` at the moment a tool is missing or
   misbehaves with the script kept under `evidence/`, a stop with its reason when a step fails three times); the
   report you want back (the artifacts really built, by which tool; the push's step lines; the verify line; the unit
   tests' line; every gap; the stops; the wall time - names and numbers, no file contents). Wait for it; never work
   on the task meanwhile.
4. **Review the dev.** Read its report against `plan.md`, the newest `push-<Pkg>-*.log` of the task folder and
   `verify_pushed`: every artifact of the table built, every push step `ok`, `N same, 0 not`, the tests green. A
   missing artifact, a `by hand` the plan did not grant, a push that stopped, a test that is red: back to the dev
   with the exact rows (resume the same subagent: it keeps its context). A scope the dev grew: `schemas.json` and
   the lock checked again. A question the dev raised: answer it from the plan, or ask the human.
5. **The tester.** Spawn one subagent for the proof (model: Sonnet; Haiku when every criterion is probe, unit or
   backend and the plan names the objects and values - a UI tier or a process tier goes to Sonnet). The brief:
   load `creatio-loop` and `creatio-tester`; the paths; the tiers of the plan and the tools of each (`dsl()` first,
   cases named `<task>-<criterion>.act` in the folder of their tier under `<workspace>/tests/<Pkg>/`, `UsrTest_` prefix on every
   record a case inserts and its deletion at the end, `make_fixture` for the insert lines, `analyse` of a page before
   a UI case, `check-process` for a process); the evidence files per criterion; `success-report.md` or
   `report-N.md`; the same hard rules; the report you want back (the criteria table, the cases and their result lines,
   the gaps, what was done by hand, the rows left on the site, the wall time).
6. **Review the tester.** `success-report.md`: every criterion `pass`, its `## Coverage` section answers every schema of `schemas.json` (an unexplained `not covered` line goes back), no row left on the site, the cases' result
   lines in the evidence - the task is done. `report-N.md`: read every row. A `fail` with evidence is a bug: list the
   rows for the dev and go back to 3 (the same dev subagent, resumed). A `fail` that reveals what the plan did not
   think of: a plan change is yours (`plan.md`, a new criterion, `schemas.json`), a behaviour change is the human's
   question. `blocked`: the human decides. A `fail` without evidence or a free-text report goes back to the tester.
   Three reports and still red: `failed.md`, the task parks, the human decides. Never edit a report, never argue with
   evidence, never fix a test yourself.
7. **Retrospective and the outcome.** After `success-report.md` (or when the human asks) have the dev write
   `retrospective.md` from the loop's template, from the logs (rule 6), the tester's gaps included; read it for the
   platform facts and the "by hand" items. Then report to the human: the outcome (`r1` / `r2` / `r3` / failed), one
   line per round, the cost (tokens and tool uses of each subagent run as the Agent tool reports them, the wall time),
   every `report_gap` line of the task, the three things the retrospective ranks highest. The cost row goes into
   the benchmark's `results.md` when the task is a benchmark run.

## What a brief must and must not hold

A brief holds paths and rules, never a value from `project.json` (no password, no url, no login) and never the content
of a file the subagent can read itself. It names what the subagent returns, in order, "names and numbers only". It
says which site may be touched and that it is the only one. It says what to do when a tool is missing (`report_gap`,
the script kept) and when a step fails three times (stop with the reason). A brief for Sonnet names every file and
command; a brief for Opus names the boundary and the decision left open. One subagent on the site at a time: the dev
and the tester run in turn, never together; another task's executor on the same site is a line in the INBOX to read
first.

## Values you must not invent

Environment, package, prefix, paths and credentials come from `project.json` only. Lookup ids and record ids come
from the environment (`lookup_values`, `sample_records`, OData), never from a recipe. Names carry the package prefix.

Before any `env_sql`, the question goes to the tool that answers it: a schema overridden in another package or in
Custom - `schema_layers`; what ran when a record changed - `process_runs(record=)`; which lookup value or schema a
GUID is - `resolve_uid`, which lookup holds a status - `list_lookups`; the rows a lookup holds on the site -
`lookup_values`; records of an object with their lookups named - `sample_records`, its columns - `describe_table`;
text inside schemas - `find_text`; a column's writers - `who_sets`. SQL is for what no tool answers.

No tool answers? Call `report_gap(kind, need, instead, script=, text=, task=)` before you go around it. A gap that is not
recorded does not become a tool. A script written for the task is saved under `<task folder>/scripts/<name>` (never a scratchpad) and `report_gap` gets its path; a one-line query or command with no file goes as `text=`. A tool a subagent reports as missing or wrong is your gap line too if it is not in
`gaps.jsonl` already.
