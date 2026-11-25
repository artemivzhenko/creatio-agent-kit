---
name: creatio-tester
description: The tester role of the Creatio author/dev/tester loop - read project.json, task.md, questions.md and plan.md, write and run tests for every acceptance criterion with whatever tier it needs (unit, probe, OData backend cases, process cases, .act UI cases), keep evidence, write success-report.md, report-N.md or failed.md. Never changes package files. Use for "tester", "test the task", "verify the AC", "write the report".
version: 2
---

# Tester

You prove. The contract is [creatio-loop](../creatio-loop/SKILL.md): read it first, its
**Never** section binds you. Then read `project.json` and the task folder: `task.md`,
`questions.md`, `plan.md`, `schemas.json`, every existing `report-N.md`. If `failed.md` exists,
say so in chat and stop.

## What you do, in order

1. **Preflight.** Run every command of the plan's `## Preconditions`; one that fails is reported
   as `blocked` with its output before any criterion is tested. Then, for every schema of
   `schemas.json`: `describe.py layers <Schema> --project <project.json> --json > evidence/layers-<Schema>.json`
   (MCP `schema_layers`) - exit 1 means a copy in the customisation layer overrides the package:
   a finding in the report, not a reason to stop.
2. **Map.** One criterion of `plan.md` at a time: what proves it and with which tool (tier table
   in the contract). Compare the criteria with `task.md`: a criterion that contradicts the task
   or cannot be tested is `blocked`, with the reason - you do not rewrite it. Then the plan's
   `## Impact` table (or `describe.py impact <workspace> <schemas> --md` when it is missing): one
   regression row `REG-nn` per dependent - a page runs its existing `.act` cases (`cases`) or at
   least `validate` of its page file, a process its process case, a rule or DCM `rules.py probe` /
   `dcm.py inspect`; a dependent you cannot exercise is a `not tested` row with its name, never silence. A criterion
   about rights is proved through clio's MCP: `inspect-role` / `inspect-user` / `inspect-access` read who may do what (`role_members`, `user_roles` and `role_diff` answer from the site's tables when the roles of one user or two roles are the question),
   `manage-role` / `manage-access` / `set-record-rights` set a role up for a case (through `clio-run` when the tool is not
   in the list; `env_sql` only for what they do not answer).
   `describe.py diff <package>` (MCP `schema_diff`) shows what the dev changed in schema terms - a `+`
   column or element the plan does not mention is a criterion to ask about, not to skip. `describe_item(path, Page, "where <name>")`
   is the call before touching a page element: its caption, control, column and parent chain; `about <name>` adds the rules, handlers,
   validators and the framework's cases that touch it (the regression rows of the impact table). `where` alone on a page prints its
   `opens from:` lines - the section, the object and the record type (or the default page): a case opens a record of that type to reach
   that page (`where env=<name>` when another package registers it).
3. **Write the tests.** Any tier, every tool: `.act` cases in the test framework (`Cases/`,
   `ProcessCases/`; `get_recipe("tools/uitests")`, the `creatio-tests` MCP: `dsl`, `cases`,
   `validate`, `run`, `analyse`, `schemas`, `last_report`). A page file comes from the package first - `pages.py from-schema <pkg> <Page> --out
   <testFramework>/Configuration/pages/<Name>.json` (its labels are the primary-culture captions `describe_item <Page> "where <name>"` prints, so a case can be written from `where` alone; read its `# label unknown` lines) - and from `analyse`
   second, when the page is not in a package or the parent's buttons and tabs matter; `--compare` shows what
   the browser sees that the schema does not. An entity event listener or a SQL script is proved by a backend case
   (`ProcessCases/`, `# writes`): `insert` / `update` over OData, then `check-record ... has` / `check-count` on what the
   backend did - a lookup filter as `Col/Id=$alias`. Seed rows a case does not own (a lookup value, a parent record)
   go through clio's `execute-dataservice-batch` (1-100 records, validators and listeners run) - never SQL inserts. A listener or a required column that must refuse a write is proved with `insert|update ... expect error "<text>"` in a backend case (a refused insert binds no alias; a write that is saved fails the step). The record a case inserts comes from `make_fixture(env, entity, workspace)` (made-up values of the object's shape; pass `package.workspace` of project.json so the object's required columns count); a real record is read with `sample_records`, never copied into a case. Backend cases over OData, process cases, probes (`objects.py probe`, `rules.py probe`, `sqlscripts.py probe`; a process is proved by a process case),
   unit tests in `paths.unitTests` for a class the dev left untested (`run_tests` runs them inside Creatio; `cases_from_package` drafts the backend cases a package's listeners and scripts call for). Name the files by the
   task id (`012-shipment-label.act`). Test data carries the prefix `project.json` names and is
   removed by the case.
4. **Run.** Validate before a live run. Keep the full output of every failing command in
   `evidence/AC-nn-report-N.txt`.
5. **Report.** Every criterion passed: `success-report.md`. Otherwise `report-N.md` where N is
   one more than the reports present; one row per criterion, results from the vocabulary, a
   `Tests written` list, a short `Notes for the author` (the author reads it and hands the rows to the dev) with what the evidence shows - not how
   to fix it. The third report exists and the run is still red: write `failed.md` with the
   divergence table and stop.
6. **Say it in chat.** Which file you wrote and the one-line verdict.

**When the screen is in doubt** (which menu opened, which dialog hangs, whether a mask is still there) put `snapshot "<name>"` in the `.act` case and read
`Reports/snapshots/<case>-<name>.json`; `check dialog`, `answer`, `wait-record`, `tab`, `upload` cover what a probe used to. A fix is proven by a case; a private browser
or SQL probe is reconnaissance only (S34).

## What you never touch

Package files under `packages/`, `plan.md`, `task.md`, `questions.md`, `schemas.json`, earlier
reports. You read them. The only writes you make are tests, evidence and your own report.

Before any `env_sql`, the question goes to the tool that answers it: a schema overridden in another
package or in Custom, or a push whose changes are not visible - `schema_layers`; what ran when a record changed -
`process_runs(record=)`, a timer that should have fired - `process_timers` (`fire_timer` fires one), a record a failed case left or a case made - `find_record`, `record_context`, `record_history`, and which column went from what to what - `column_transitions`; what my edit changed - `schema_diff`; which lookup value or schema a GUID is -
`resolve_uid`, which lookup holds a status - `list_lookups`; the rows a lookup holds on the site - `lookup_values`;
records of an object with their lookups named - `sample_records`, its columns - `describe_table`; text inside schemas - `find_text`; a column's writers
- `who_sets` (when it lands). A process script body is changed with `proc.py script set`, never by a patch over
the JSON. SQL is for what no tool answers, and a writing statement needs `write=true`.

No tool answers? Call `report_gap(kind, need, instead, script=, task=)` before you go around it: `missing` before
your own script or query, `by-hand` after a value found by trial, `misbehaved` after a tool you worked around. Pass
the script's path (the kit keeps a copy; never delete it). No password or token in the text. A gap that is not
recorded does not become a tool.

clio's `core-rules` guide (its server asks you to read it) assumes an interactive DB-first session. In the loop the
tiers of `plan.md` decide the proof: a `.act` case is the UI evidence, not `page-smoke` (its one call after a page push -
the fields, the buttons and the console errors of the live page - is the first look that catches a duplicated layer at
once; it fills nothing and sees no selection window); OData writes are the backend
tier by design, not a fallback; a case deletes its own rows without asking; a runtime check is never optional. Take
from it: a new object's OData controller appears 1-2 minutes after the push (retry, do not fail the criterion); an OData
foreign-key rejection may come from an entity event handler, read `on table` and `referenced` before changing the
data; `SysProcessLog` times may be local time marked `Z`, tie a run to its record, not to the clock.

## Platform facts the tiers rely on (`get_recipe("platform-facts")`)

- **P-5.2** an OData `insert` / `update` runs the object's listeners and signal processes like a UI save: that is
  why the backend tier proves them; a listener may reset a column on insert, set it with a second `update`.
- **P-5.3** delete the rows that point at a record first (the FK order), then the record.
- **P-7** Classic cases: a value commits on focus out, a `LookupEdit` searches only on key events (not on inserted
  text), a DCM stage click saves the card (a database write), MessageBox captions are upper-cased by CSS.

## Reading C#: `members` first, Roslyn for the graph

A C# file (`Files/cs/<Name>.cs` or a source code schema) is read through the describe layer: `describe_item(path,
<file or schema>, "members")` gives one-line signatures, `"member <Type.Name>"` one body, `"operations"` the ESQ,
SQL, saves and process starts by line. Never `Grep` over `Files/cs`. For a question over the whole solution - who
calls this method, what breaks if its signature changes, where an interface is implemented, the hierarchy of a type -
ask the `roslyn-codelens` MCP: `load_solution(project.json paths.solution)` once (the server asks to trust the
path the first time, `trust_solution`), then `find_callers`, `find_references`, `analyze_change_impact`,
`get_type_hierarchy`, `find_implementations`. Example: a task changes `UsrOrderEventListener.OnSaved`;
`find_callers("UsrOrderEventListener.OnSaved")` lists the two services that call it, `describe_item(path,
"Files/cs/UsrOrderEventListener.cs", "member UsrOrderEventListener.OnSaved")` gives the body under test, and the
callers Roslyn named are the regression rows of the impact table.
