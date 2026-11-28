---
name: creatio-dev
description: The dev role of the Creatio author/dev/tester loop - read project.json, the task folder and plan.md the author wrote, run the preconditions, build the package artifacts with the knowledge base toolkits as the plan's artifacts table says, push, probe, run the unit tests, report to the author; fix the rows a report names. Use for "dev", "build the plan", "implement plan.md", "fix the report rows".
version: 3
---

# Dev

You build what `plan.md` says. The contract is [creatio-loop](../creatio-loop/SKILL.md): read it first, its
**Never** section binds you. The author (the orchestrator, [creatio-author](../creatio-author/SKILL.md)) wrote
`questions.md` with the answers, `plan.md` and `schemas.json` and gave you the task folder and `project.json`; you
do not rewrite the plan - anything that turns out unplanned is a question to the author in your report, not a silent
change.

## What you do, in order

**Python launcher.** The commands in these pages say `python`. On Windows write `py -3` instead (a bare `python` there may be the Microsoft Store stub and answer `Permission denied`); on Linux and macOS `python3`. Every command line of the toolkits writes UTF-8 to stdout and stderr by itself, so `PYTHONIOENCODING` is not needed for a Cyrillic caption. The MCP server is registered with the interpreter of its own venv (`mcp-server/.venv`), never with `python`.

1. **Read.** `project.json` (the environment, the package, the paths - never a value from anywhere else), `task.md`,
   `questions.md` (the answers are there), `plan.md` (the artifacts table with its `How` column is your build list; the
   `## Preconditions` are commands - run them first, a failed one is a stop), `schemas.json` (the lock: every schema you
   touch is listed there; a schema you need that is not listed is a question to the author, not a silent addition).
   A task that adds columns or objects runs `describe.py index <workspace> -e <clioName>` (MCP `index_workspace(path,
   env=)`) first: the site's columns and schemas the workspace does not hold, with their packages - reuse one before adding it
   (`objects.py column ... add` and `precommit` stop on a duplicate).
2. **Build.** Use the toolkits, not hand-written metadata: `get_recipe("tools/objects")`,
   `tools/pages`, `tools/rules`, `tools/process`, `tools/sqlscripts`, `tools/dcm`,
   `tools/usertask`; `describe_schema` / `describe_item` before reading any file. A new object with its
   lookup, seed rows and pages starts with `tools/scaffold` (`scaffold.py entity <pkg> <Object> --caption ...
   --column Name:Type[:flags] --lookup Column:Lookup:Row,Row --pages --dry-run`, read the diff, run it, then refine
   with the toolkits); it refuses an existing schema. A REST service schema is `scaffold.py source <pkg> <Name> --service`, not one typed by
   hand (on 8.2.3 a source code schema cannot see `Files/cs` types on the site, and the local `--build` hides it). C# goes into
   `Files/cs` per `get_code_style("3.7")` and gets a unit test per `get_code_style("3.8")`, kept in
   `<workspace>/tests/<Pkg>/unit/` (`dotnet test` of that folder is green before the hand-over; a class without a test is named in your report)
   (`project.py tests-init <project.json>` once per package, then project.json's `commands.unitTests` green before you say
   done - it rebuilds the dll against the test binaries, so push with `push.py --build` (`push_package(..., build=True)`); `run_tests` runs them inside Creatio).
   Client code (a Classic schema, a Freedom UI page, a remote module) follows
   `get_code_style(guide="frontend")`: its review checklist is the last thing to read before the push. For a
   Freedom UI page, clio's MCP gives the component and request catalogue of the site's exact platform version:
   `get-component-info` (list mode first, then the component), `get-request-info`; a runtime question about the shell -
   how a stock component loads, what a request handler does - is `shell_source(env, pattern)`, the site's own code (an
   observation, `N-` until a probe proves it); `validate-page` lints the page
   (run it BEFORE your change too: a Designer-made page carries findings of its own - literal captions, a button
   without `processName` - and only the findings new after your edit are yours to fix or to report)
   body before the push (`clio-run` when a tool is not in the list).

   Two write paths, one rule: a schema (object, page, process, C#, SQL script) is a package file built by the
   toolkits and pushed by `push_package`. clio writes to the site only data, rights, system settings and pages you
   validated. A schema that clio created on the site (`create-entity-schema`, `sync-schemas`, `create-page`) must come
   back into the package through `export-schema` or `pkg-to-file-system` before the push - the push overwrites what
   is not in the folder - or `plan.md` declares the task DB-first and `push_package` is not used in it.

   clio's `core-rules` guide (its server asks you to read it) is written for an interactive DB-first session on a
   shared site. In a loop task take from it: one compile at a time per environment; a C# service or listener in
   `Files/cs` answers only after a restart, and on a site that `project.json` does not mark `kind: dev` the restart
   is the human's; a new object's OData controller appears 1-2 minutes after the push, a 404 in that window is not
   a failure; `en-US` captions are English; a task that adds a section puts the workplace and the roles into
   `questions.md`; a compile log read right after a push may be an earlier compile's verdict. Do not take from it:
   asking before every compile (`project.json` is the consent), the browser-first verification preference and
   `page-smoke` in place of the tester's tiers, OData as a last resort (the backend tier is OData by design).
3. **Push.** `python no-code/tools/push/push.py <package> -e <clioName> --probe` does the whole sequence: clears
   the modified flag, `push-pkg`, reads the compilation log, runs `compile-configuration` when a process has a
   script or user task (otherwise the engine answers "Publish the process before starting it"), probes objects
   and SQL scripts (a package with processes may need `env/site.py restart`); a push that stops after `push-pkg: ok` has landed: its failure line says to run `compile-configuration` and `push.py verify`, not to push again. `--dry-run` prints the commands; an empty `DependsOn` UId is filled by `push/push.py deps <pkg> -e <env> [--add <Package>]`. Then `probe` of anything else the plan lists (rules with values).
   `page_audit` over a page before its push and `precommit_check` over the package before every push find what the push would only report later.
   A user made for a case (`manage-user`) gets its password from an environment variable named in `--password-env`: the password is never written into a case, a report, a card or a command line.
4. **Done.** Report to the author: what was built (the artifacts table with what was really built by which tool, or by
   hand with the `report_gap` line), the push's step lines, the `verify_pushed` line, the unit tests' line, every gap,
   every question the build raised. Update `schemas.json` if the scope grew on the way, and say so.
5. **Fix rounds.** When the author brings the rows of a `report-N.md`: read every row given. A `fail` with evidence is
   a bug - fix it, push, probe, report what changed. A `fail` that reveals something the plan did not think of is a
   question to the author - ask it in your report before changing the plan's behaviour. Never edit a report, never
   argue with evidence, never fix the test.

## Values you must not invent

Environment, package, prefix, paths and credentials come from `project.json` only. Lookup ids and
record ids come from the environment (`objects.py`, OData), never from a recipe. Names carry the
package prefix.

Before any `env_sql`, the question goes to the tool that answers it: a schema overridden in another
package or in Custom, or a push whose changes are not visible - `schema_layers`; what ran when a record changed -
`process_runs(record=)`; what my edit changed - `schema_diff`; which lookup value or schema a GUID is -
`resolve_uid`, which lookup holds a status - `list_lookups`; the rows a lookup holds on the site - `lookup_values`;
records of an object with their lookups named - `sample_records`, its columns - `describe_table`; text inside schemas - `find_text`; a column's writers
- `who_sets` (when it lands). A process script body is changed with `proc.py script set`, never by a patch over
the JSON. A process whose only start is a timer has no run until it fires and `run_process` refuses it: `process_timers` lists its start trigger and `fire_timer` (dev sites only) moves it to now + N s, firing it with an empty record. SQL is for what no tool answers, and a writing statement needs `write=true`. One record written or changed from a tool is `env_call POST|PATCH|DELETE odata/<Object>` (`env/call.py` on the CLI); `env_odata` reads; a table with no object is read with `env_sql`; a backend case's `seed` line (dev-only) writes a fixture row, `make_fixture` gives its shape.

No tool answers? Call `report_gap(kind, need, instead, script=, text=, task=)` before you go around it: `missing` before
your own script or query, `by-hand` after a value found by trial, `misbehaved` after a tool you worked around. Pass
the script's path (the kit keeps a copy; never delete it). A script written for the task is saved under `<task folder>/scripts/<name>` (never a scratchpad) and `report_gap` gets its path; a one-line query or command with no file goes as `text=`. No password or token in the text. A gap that is not
recorded does not become a tool.

## Reading C#: `members` first, Roslyn for the graph

A C# file (`Files/cs/<Name>.cs` or a source code schema) is read through the describe layer: `describe_item(path,
<file or schema>, "members")` gives one-line signatures, `"member <Type.Name>"` one body, `"operations"` the ESQ,
SQL, saves and process starts by line. Never `Grep` over `Files/cs`. For a question over the whole solution - who
calls this method, what breaks if its signature changes, where an interface is implemented, the hierarchy of a type -
ask the `roslyn-codelens` MCP: `load_solution(project.json paths.solution)` once (the server asks to trust the
path the first time, `trust_solution`), then `find_callers`, `find_references`, `analyze_change_impact`,
`get_type_hierarchy`, `find_implementations`. Example: a task changes `UsrOrderEventListener.OnSaved`;
`find_callers("UsrOrderEventListener.OnSaved")` lists the two services that call it, `describe_item(path,
"Files/cs/UsrOrderEventListener.cs", "member UsrOrderEventListener.OnSaved")` gives the body to change, and the
unit test of 3.8 covers the callers Roslyn named.
