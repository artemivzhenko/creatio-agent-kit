---
name: creatio-author
description: The author role of the Creatio author/tester loop - read project.json and the task folder, ask the questions, write plan.md with acceptance criteria and schemas.json, check the schema lock, build the package artifacts with the knowledge base toolkits, push, probe, run the unit tests, answer the tester's reports in chat. Use for "author", "implement the task", "write the plan", "answer the report".
version: 2
---

# Author

You build. The contract is [creatio-loop](../creatio-loop/SKILL.md): read it first, its
**Never** section binds you. Then read `project.json` (the human gives its path) and the task
folder.

## What you do, in order

**Python launcher.** The commands in these pages say `python`. On Windows write `py -3` instead (a bare `python` there may be the Microsoft Store stub and answer `Permission denied`); on Linux and macOS `python3`. Every command line of the toolkits writes UTF-8 to stdout and stderr by itself, so `PYTHONIOENCODING` is not needed for a Cyrillic caption. The MCP server is registered with the interpreter of its own venv (`mcp-server/.venv`), never with `python`.

1. **Questions.** Read `task.md`, `project.json`, and the knowledge base around the task
   (`search_recipes`, `describe_package` of the package, `resolve_caption` first on a task that names things in
   business words, `find_schema` for every schema the task names, `who_sets` before changing what a column means (`who_reads_message` for a client message), `sys_setting` for a setting the task reads or sets, `find_text(kind="process")` instead of grep over `metadata.json`). Write `questions.md`: numbered, each with the assumption you would make if unanswered.
   Say in chat that the questions are ready and stop. If there are none, write `No questions.`
   and go on.
2. **Plan.** Copy answers the human gave in chat into `questions.md`. Run `describe.py layers
   <Schema> -e <clioName>` for every schema the task replaces: a copy in the customisation layer
   is a question, not a surprise. With the answers in `questions.md`, write `plan.md` (with its
   `## Preconditions` as commands - run them) (approach, artifacts table with a `How` column: the kit
   tool or toolkit command that builds each, or `by hand: <reason>` - the reason is decided here, where it
   still exists, and it becomes a `report_gap` line when the step runs; acceptance criteria table with
   tiers) and `schemas.json`. Run `describe.py impact <workspace>
   <every schema of schemas.json> --tasks <paths.tasks> --current <this folder> --md` (MCP
   `schema_impact`): paste its `## Impact` table into `plan.md` and its `affects:` names into
   `schemas.json`. Exit 1 means another active task changes a schema of this plan or one of its
   dependents - stop and ask the human. Do not wait for approval otherwise: build the plan as written.
   A task that adds columns or objects runs `describe.py index <workspace> -e <clioName>` (MCP `index_workspace(path,
   env=)`) first: the site's columns and schemas the workspace does not hold, with their packages - reuse one before adding it
   (`objects.py column ... add` and `precommit` stop on a duplicate).
3. **Build.** Use the toolkits, not hand-written metadata: `get_recipe("tools/objects")`,
   `tools/pages`, `tools/rules`, `tools/process`, `tools/sqlscripts`, `tools/dcm`,
   `tools/usertask`; `describe_schema` / `describe_item` before reading any file. A new object with its
   lookup, seed rows and pages starts with `tools/scaffold` (`scaffold.py entity <pkg> <Object> --caption ...
   --column Name:Type[:flags] --lookup Column:Lookup:Row,Row --pages --dry-run`, read the diff, run it, then refine
   with the toolkits); it refuses an existing schema. C# goes into
   `Files/cs` per `get_code_style("architecture")` 3.7 and gets a unit test per 3.8
   (`clio new-test-project` once per package, `dotnet test` green before you say done; `run_tests` runs them inside Creatio).
   Client code (a Classic schema, a Freedom UI page, a remote module) follows
   `get_code_style(guide="frontend")`: its review checklist is the last thing to read before the push. For a
   Freedom UI page, clio's MCP gives the component and request catalogue of the site's exact platform version:
   `get-component-info` (list mode first, then the component), `get-request-info`; `validate-page` lints the page
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
4. **Push.** `python no-code/tools/push/push.py <package> -e <clioName> --probe` does the whole sequence: clears
   the modified flag, `push-pkg`, reads the compilation log, runs `compile-configuration` when a process has a
   script or user task (otherwise the engine answers "Publish the process before starting it"), probes objects
   and SQL scripts. `--dry-run` prints the commands. Then `probe` of anything else the plan lists (rules with values).
   `page_audit` over a page before its push and `precommit_check` over the package before every push find what the push would only report later.
5. **Done.** Say in chat what was built, what the probes and unit tests showed, and that the
   task is ready for the tester. Update `schemas.json` if the scope grew on the way.
6. **Reports.** When the human brings a `report-N.md`: read every row. A `fail` with evidence is
   a bug - fix it, push, probe, say in chat what changed. A `fail` that reveals something the
   plan did not think of is a question - ask it in chat before changing the plan's behaviour.
   Never edit the report, never argue with evidence, never fix the test.

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
the JSON. SQL is for what no tool answers, and a writing statement needs `write=true`.

No tool answers? Call `report_gap(kind, need, instead, script=, task=)` before you go around it: `missing` before
your own script or query, `by-hand` after a value found by trial, `misbehaved` after a tool you worked around. Pass
the script's path (the kit keeps a copy; never delete it). No password or token in the text. A gap that is not
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
