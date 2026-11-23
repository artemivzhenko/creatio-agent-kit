# Creatio KB MCP server

Exposes this knowledge base to an AI assistant over MCP, so the model can look up a
recipe for a concrete task instead of loading all 177 files into context - and, through the
same server, ask the describe layer about a package, install it and query the environment.

## What it gives the model

Recipes (`kb_index.py`):

| Tool | Purpose |
| --- | --- |
| `search_recipes(query, area?, limit?)` | Ranked search by task or symptom. `area` = `ClassicUI` / `FreedomUI` / `RemoteModule` / `Mobile` / `Backend` / `SQL` / `Clio` / `Tools`. |
| `get_recipe(recipe_id, part?)` | Full text of one recipe: explanation header plus runnable code; `part=traps` only the Trap / Verified / Gap lines (ask first, before writing code of that kind), `summary` the header, `code` the code without it. For clio, a command name (`execute-sql-script`) or a block skill (`clio-sql-and-data`) resolves directly; for a toolkit, `tools/process`. |
| `find_api(symbol, limit?)` | Reverse lookup — which recipes use `crt.OpenLookupPageRequest`, `UseAdminRights`, `EntitySchemaQuery`… A bare name also matches the dotted one. |
| `list_recipes(area?, topic?)` | Browse ids and titles. |
| `kb_overview()` | Map of areas, topics and counts — the entry point when the model does not know what exists. |
| `get_code_style(section?, guide?)` | The style and architecture guides: `guide="csharp"` (default, `../CREATIO_CODE_STYLE.md`) or `guide="frontend"` (`../CREATIO_FRONTEND_CODE_STYLE.md`: Classic UI, Freedom UI, remote modules, mobile); whole or one `##` section by number or heading words (`"logging"`, `"9"`). |

The describe layer (`../no-code/tools/creatio_schemas/describe/`, its README is the contract -
every list answer has a `limit`, default 40, and a `... N more` tail; `0` means all):

| Tool | Purpose |
| --- | --- |
| `describe_package(package, kind?, limit?, offset?)` | One line per schema, SQL script and data binding, from the package index. |
| `describe_schema(package, schema, limit?, offset?)` | The summary of one schema: what the toolkit's `inspect` prints. |
| `describe_item(package, schema, query, limit?, offset?)` | One part, chosen by `"<topic> [<name>] [k=v]"`; `"topics"` lists what the schema answers. |
| `find_in_processes(path, pattern, limit?, offset?)` | Search the decoded text of every process (script lines, flow conditions, formulas, filters with lookup captions, Add/Modify values); `Package / Process / Element [type] / where: text`. Read-only. |
| `who_sets(path, target, limit?, offset?)` | Every place that writes `<Entity>.<Column> [= value]`: process steps and scripts, C#, client pages, SQL scripts. Read-only. |
| `who_reads_message(path, sender, limit?, offset?)` | Publishers and subscribers of a message sender in C# and client code. Read-only. |
| `page_audit(path, page, all?)` | What makes a Freedom page slow, one line per finding over a threshold (elements per tab, grids with no master filter, attributes through 3+ joins, comboboxes, page/object rules, columns, timers); last line `<Page>: <n> finding(s)`. Read-only. |
| `resolve_caption(path, text, kind?, culture?, limit?, offset?)` | The workspace by caption or `Usr` name: objects, pages, columns, page elements, parameters, lookup values, ranked, best match first; `culture=all` searches the other cultures. |
| `find_schema(path, schema, limit?, offset?)` | The package, the files (absolute paths), what it refers to, what refers to it. |
| `find_text(path, pattern, kind?, context?, limit?)` | A regex over every file the index knows: `<Package>/<Item> (<kind>) <line>: <text>`, `context` lines around each hit; resource XML only with `kind="resource"`. The answer to "where is this text" without a Grep over raw schema files. |
| `schema_deps(path, schema, direction?, kind?, via?, limit?, offset?)` | The typed graph: objects a page or process builds on (and through which columns); every process, rule, page, DCM, binding or listener that builds on an object. |
| `schema_impact(path, schemas, tasks?, current?, md?, limit?, kind?)` | The dependents of the schemas a task changes; with the loop's tasks folder, which other active task changes or affects them. Ends with `exit code 1` on a conflict. `md` gives the `## Impact` table for `plan.md`; `kind` keeps one kind of dependents (a lookup with a hundred). |
| `schema_diff(package, schemas?, against?)` | The working copy against git HEAD, a revision, a folder with a pulled copy, or the site (`against="env:<name>"`: the named schemas' copies pulled from the site's tables): `+` / `-` / `~` lines per item, never a JSON hunk. |
| `resolve_uid(path, text)` | What a UId names (a schema, `column X.Y`, a process element or parameter), the UId of a dotted name, or a text with every UId replaced by its name - the reverse of what the designer stores. |
| `tool_stats(days?)` | Calls, characters and the largest answers per tool over the last days, and the share of answers cut with a `... N more` tail (from `mcp-server/.stats/`). |
| `schema_layers(path_or_env, schema, rule?, workspace?)` | The SysSchema copies of a schema on an environment, applied first to last; `Custom layer present` means a copy on the site overrides what you push. |
| `schema_snapshot(schema, env?, workspace?, columns?, out?, page_file?)` | An object or a page (folded elements, handlers / methods; `page_file` adds the live page from `analyse`) as text lines: the effective columns over the workspace's layers and / or the site's table, row count, column checksums and copies; `out` writes the evidence file. |
| `merge_plan(path, schemas?, env?, limit?, offset?)` | Each schema replaced by more than one package (or the named ones): the target (the lowest package), `layer <pkg>: +n columns / elements / methods` in apply order, `siblings` when the order is guessed, `conflict` lines, `depends: <target> gains ...`; ends with the counts and `exit code 1` on a conflict. Writes nothing (safe on a client workspace). |
| `cases_from_package(package, out, env?, user?)` | The baseline cases of a package written from its schemas (an object's insert / read / update / delete, a process's start / outputs, a form page's new record) with `stop` lines for what cannot be guessed. |
| `merge_layers(path, schema, target?, env?)` | The layers of one object or page (Freedom: the diff arrays concatenated; Classic: a method in two layers folded at its callParent) as one layer of the target package, PRINTED only: the plan, `write` / `delete` per file, or `stopped: ... - nothing written`; `env` gives the site's order and the references check. `describe.py merge --apply` writes. |
| `merge_run(path, child, parent, env, evidence)` | The REHEARSAL of the package-merge procedure: plan, baseline cases of the child, every case on the site `env` (a red case stops), a snapshot of every object and page, `rehearsal: nothing written`; the evidence goes to the folder. `describe.py merge-run ... --apply` merges, pushes and pauses (exit 3) for the child's application, `--continue` compares and tests again. |
| `merge_package(path, child, parent, env?)` | One child package folded into its parent, PRINTED only: `layer` lines (merged through merge_layers), `move` lines (the UId kept), `depends` redirects, `note` and `stop` lines; `describe.py merge-package --apply` writes, and the parent is pushed first. |
| `snapshot_compare(before, after, ignore_layers?)` | Two snapshot files as `+ - ~` lines, or `same`; a difference ends with `exit code 1`. |
| `list_lookups(path, limit?, offset?)` | Every lookup object: parent chain, bindings, users. |
| `index_workspace(path, rebuild?, stats?, env?)` | Build or refresh `.creatio-index/index.sqlite` under a workspace; reports added / changed / removed; `stats` adds size, format and rows per table; `paths.platform` reads the platform captions once; `env` stores the site's columns and schemas the workspace does not hold (read-only SQL). The other tools refresh it themselves on every call. |

The environment (`creatio_schemas/environment.py` over clio; `env` is a clio environment name):

| Tool | Purpose |
| --- | --- |
| `env_sql(env, sql, limit?, out?, write?)` | Rows as JSON, one object per row; several statements answer each under `-- statement k` (or `affected: N`); a statement that is not select / with / show / explain is refused without `write=true`; `out=<file.csv>` writes every row of the last statement that returned rows (UTF-8 with BOM, `;`) and answers the count and five rows; a database error (`[ERR]`, or a SQLSTATE line such as `42703: ...` on the clio builds that exit 0) comes back as `error: ...`, never as `(no rows)`. |
| `describe_table(env, table)` | The real columns (type, length, nullable), primary key and foreign keys of a table on the site - ask it instead of guessing a column name. Read-only. |
| `env_odata(env, entity, select?, filter?, top?)` | Records over OData (`top` defaults to 20). |
| `env_call(env, method, path, body?)` | A service or OData call with login and CSRF; the fault in one line. |
| `find_record(env, id, objects?, everywhere?, time_zone?)` | Which table holds an Id, with the caption, dates and authors. |
| `record_context(env, entity, id, columns?, depth?)` | A record with its lookups named and the rows that point at it. |
| `role_members(env, role, units?)`, `user_roles(env, user)`, `role_diff(env, role, users)` | Role membership from `SysAdminUnitInRole` (nested roles included); the diff ends with `exit code 1` when a user is missing. |
| `run_process(env, process, params?, results?)` | Starts a process (`params` a JSON object), prints its result parameters and its `SysProcessLog` row; `exit code 1` unless the run completed. |
| `process_runs(env, process?, record?, since?, until?, limit?, window?, time_zone?, noise?, steps?)` | The runs of a process, or every run within `window` seconds of a change of a record (`<Entity>:<Id>`) or its details; noise processes hidden with a count. |
| `process_error(env, log_id, time_zone?)` | One run's error without stack frames, and the element it stopped on. |
| `process_timers(env, process, record?, window?, time_zone?)` | The pending timers of a process (Quartz triggers of the run's elements): fire time in UTC and `time_zone`, caption, state, run and element ids. Read-only. |
| `fire_timer(env, process, record, project, timer?, delay?, time_zone?)` | Moves one pending timer to now + `delay` s (`update qrtz_triggers`). WRITES, and is refused (`refused: <env> is not a dev environment`) unless `project` marks the environment `kind: dev`. |
| `record_history(env, record, column?, clusters?, time_zone?, limit?)` | The change log (`Sys<Entity>Log`) of a record: when, who, `was -> became` per column; `clusters` ms adds the other records the same user changed in the window. Read-only. |
| `column_transitions(env, column, from_?, to?, since?, out?, time_zone?, limit?)` | Every change of `<Entity>.<Column>` over all records from the change log; `out` writes a CSV. Read-only. |
| `run_tests(env?, project?, category?, test?, package?)` | The in-Creatio tests: failures first, `N passed, M failed`, a warning when the test dll is older than the package; `exit code` 0/1/2. |
| `review_download(package, keep?)` | A pulled package against git HEAD: line endings / BOM only, content changes, dependencies, orphan resources, untracked files; `keep` prints the restore lines. |
| `precommit_check(workspace)` | Staged files that must not be committed (size, archives, binaries, stray roots), then `exit code 1`. |
| `sys_setting(code, envs, workspace?)` | A setting's value on each environment and the data bindings of the workspace that set it. |
| `push_package(package, env, ...)` | `IsChanged` cleared, `push-pkg`, the compilation log, `compile-configuration` when needed, the probes of the changed items; `dry_run` shows the plan. |
| `verify_pushed(package, env, schemas?, bin?)` | Is the site running the pushed code: per schema `same` / `differs (metadata or body ...)` / `not on the site`, a script process `not published` / `compile error`, a client schema `not served`; read-only. |
| `ci_check(packages, package?, cyrillic?, base?)` | The package rules of the CI pipeline (`ci-cd/pipeline.py check`) on a packages folder: schema folder files, duplicate UIds, `alert(` / `debugger`, one `.sql` and one `.dll` per folder; with `base` (a git ref) a binding or SQL script changed since it without a new descriptor date; one line per problem, `exit code` 0/1. Read-only. |
| `ci_hierarchy(packages)` | The install order by levels from `descriptor.json` with the dependency report (inside, outside, used by, PROBLEMS). Read-only. |
| `ci_lint(packages, locale?, package?)` | Schemas without `resource.<locale>.xml` and process Read Data elements that read every column; two parts, each with its `exit code`. Read-only. |
| `ci_build(packages, out, package?)` | `clio compress` per package into `out`, plus `out/Pkg.zip`; writes into `out` only. |
| `ci_deploy(packages, env, package?, restart?, redis?, compile_all?, artifact?)` | The deploy stage on a site (`artifact`: a build or backup `Pkg.zip` installed in its `order.txt` order - the rollback): `IsChanged` cleared, `push-pkg` per package in dependency order, `compile-configuration`, `restart-web-app`, `clear-redis-db`, `healthcheck`. WRITES to the site. For one package with probes use `push_package`. |
| `ci_backup(packages, env, package?, out?)` | What the site runs now, pulled per package into `out/Pkg-<stamp>.zip` in the artifact shape; the rollback input of `ci_deploy`. Writes into `out` only. |
| `ci_verify(packages, env, package?)` | After a deploy: the site's schema bodies against the working copy per package (`push.py verify`), exit 1 on a difference. Read-only. |
| `ci_push_all(packages, env, package?, retry?, continue_on_error?)` | Only the push of several packages in dependency order, one at a time; the failed ones in `error-pkg.txt`, `retry` pushes that list again; a log line per step in `logs/`. WRITES to the site. |

The describe and environment tools import `../no-code/tools` at startup (standard library only);
the environment tools also need `clio` on the PATH with the environment registered. The `ci_*` tools run the
kit's `../../ci-cd/pipeline.py` and `clio-ext.py` in-process with their output captured, so the kit must be checked out
whole; the in-Creatio unit tests are `run_tests`, the UI cases the `run` tool of the creatio-tests server.

Search is lexical BM25 with a title bonus and a light stemmer (`pagination` finds
`paginate`, `files` finds `file`), built in memory at startup. No API keys, no network,
no embedding service. The words `creatio`, `freedom`, `classic`, `ui` are ignored in
queries — the UI generation is the `area` argument, not a search term. The index rebuilds automatically when a file in
the knowledge base changes, so editing a recipe takes effect on the next call.

**What the tools cost.** Every tool is registered through one wrapper (`server.py`, `_counted_tool`) that appends a line per call to
`mcp-server/.stats/<date>.jsonl` (gitignored): `{ts, tool, args, chars, ms, truncated}` - `args` is the argument names with the length of each
value, never a value; `truncated` is a `... N more` tail in the answer. `CREATIO_KB_STATS=0` turns it off, `CREATIO_KB_STATS_DIR` moves it
(the tests). The tool `tool_stats(days=1)` and `python mcp-server/tool_stats.py [days]` print calls, characters, average and largest answer
per tool, the ten largest answers and the truncated share.

## Install

```bash
cd mcp-server
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate on macOS/Linux
pip install -e .
```

`pip install -e .` pulls the only dependency, `mcp>=2.0`.

> The SDK renamed `FastMCP` to `MCPServer` in mcp 2.0. `server.py` imports either,
> so an existing `mcp<2` environment also works.

## Check it without a client

`kb_index.py` is pure standard library, so the index and the ranking can be
exercised on their own:

```bash
python kb_index.py                          # index report: areas, topics, warnings
python kb_index.py "filter a lookup field"  # try a query
```

A healthy report ends with no warnings — a warning means a recipe lost its header
block and only got a title derived from its file name.

`test_kb_index.py` pins the tokenizer, the ranking of a few known queries and the id
lookup. Run it after touching `kb_index.py`:

```bash
python test_kb_index.py          # or: pytest
```

## Wire it into a client

Replace `<KB>` with the absolute path to this knowledge base folder (the one
containing `code/` and `no-code/`), and `<PY>` with the interpreter from the
virtual environment (`<KB>/mcp-server/.venv/Scripts/python.exe` on Windows,
`<KB>/mcp-server/.venv/bin/python` elsewhere).

### Claude Code

```bash
claude mcp add creatio-kb -- <PY> <KB>/mcp-server/server.py
```

Or in `.mcp.json` at the root of the project you develop Creatio in:

```json
{
  "mcpServers": {
    "creatio-kb": {
      "command": "<PY>",
      "args": ["<KB>/mcp-server/server.py"]
    }
  }
}
```

### Codex CLI

```bash
codex mcp add creatio-kb -- <PY> <KB>/mcp-server/server.py
```

Written to `~/.codex/config.toml` as `[mcp_servers.creatio-kb]` with `command` and `args`.

### GitHub Copilot CLI

```bash
copilot mcp add creatio-kb -- <PY> <KB>/mcp-server/server.py
```

Written to `~/.copilot/mcp-config.json` as `"creatio-kb": {"type": "local", "command": ..., "args": [...]}`.

### Cursor — `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "creatio-kb": {
      "command": "<PY>",
      "args": ["<KB>/mcp-server/server.py"]
    }
  }
}
```

### Claude Desktop — `claude_desktop_config.json`

```json
{
  "mcpServers": {
    "creatio-kb": {
      "command": "<PY>",
      "args": ["<KB>/mcp-server/server.py"]
    }
  }
}
```

### Knowledge base in another location

The server assumes the knowledge base is the parent folder of `mcp-server/`.
Point it elsewhere with an environment variable:

```json
{
  "mcpServers": {
    "creatio-kb": {
      "command": "<PY>",
      "args": ["<KB>/mcp-server/server.py"],
      "env": { "CREATIO_KB_ROOT": "D:/knowledge/creatio-knowledge-base" }
    }
  }
}
```

## Companion skill

`../skill/creatio-kb/SKILL.md` tells an agent (Claude Code, Codex, Copilot) *when* to reach for these
tools. The MCP server supplies the data; the skill supplies the habit of consulting
it before writing Creatio code. The kit's `agent_setup.py` installs it into the agent's personal
skills folder; by hand, copy the folder into `.claude/skills/` (Claude Code) or `.agents/skills/`
(Codex, Copilot) of the project you work in.

## How indexing works

- Recipes are discovered under `code/Frontend/ClassicUI`, `code/Frontend/FreedomUI`,
  `code/Frontend/RemoteModule`, `code/Frontend/Mobile`, `code/Backend/C#`, `code/Backend/SQL`
  (their ids drop the `code/` prefix: `Frontend/ClassicUI/...`) and, as area
  `Clio`, the Markdown under `no-code/`. A folder with `package.json` inside (a copyable
  project template) is skipped.
- The title and description come from the header block: `// --- Title ---` in `.js`
  and `.ts` files, `/// <summary>` in `.cs`, the leading `--` comment in `.sql`, the first
  `# ` heading plus frontmatter `description:` in `.md`. A `SKILL.md` is indexed under its
  folder name (`no-code/clio-pages`).
- Without an `area`, Clio pages are scaled by `W_CLIO_UNFILTERED` unless the query names
  clio or a kebab-case command, so CLI pages do not answer platform questions.
- A recipe id is its path without the extension, e.g.
  `Frontend/ClassicUI/Fields/HowToFilterLookupField`.
- Tokenisation splits dotted and camelCase identifiers, so `crt.OpenLookupPageRequest`
  is findable as `crt.OpenLookupPageRequest`, `OpenLookupPageRequest`, and
  `lookup page`.
- A bare file name in `get_recipe` resolves when unique; when Classic UI and Freedom UI
  both have it, the tool lists the two full ids instead of failing.

## Adding recipes

Drop a new file into the right area folder and keep the header block format — it is
what supplies the title and summary. Nothing else needs updating; the index picks it
up on the next tool call.
