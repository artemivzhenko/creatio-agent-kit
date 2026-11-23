# retrospective.md - the prompt

The human gives the text below the line to the author or the tester (any agent that worked with the kit's MCP
servers on the project), during or after the work. The answer is one file, `retrospective.md` in the task folder,
written so that it can be handed to other teams and other agents: the kit's maintainers merge its section 8 into
the platform facts register and its sections 4-7 into new tools. The agent writes it from two logs, `tool_stats`
and the `report_gap` lines in `dev/gaps/`, not from memory (rule 6).

---
You are working on this project with the kit's MCP servers, skills and recipes. Write one Markdown file about that
work so far: `retrospective.md` in the task folder (one file, nothing else, no attachments, no links to files outside
it). It will be given to other teams and other AI agents who have never seen this project, so it must stand on its
own and must contain nothing that identifies the project.

## Rules for the whole file

1. **No real names.** No client, company, person, site, environment, server, URL, database, package, project name;
   no prefix other than `Usr`; no client-specific objects, columns, lookups, business values, GUIDs, logins. Write
   `UsrOrder`, `UsrOrder_FormPage`, "the client package", "the test site", "the production site". If a fact needs
   a concrete name to make sense, invent a generic one. Re-read the file for names before you finish.
2. **Platform, not project.** A Creatio fact is about the platform (its behaviour, its tables, its tools, clio, the
   designer, the SDK) and holds on any site of that version. A project fact (how this client's process works, why
   this field exists) does not go in.
3. **Evidence or nothing.** Every fact says how you saw it: `run` (you ran it and saw the result), `sql` (a query
   and what it returned, in generic names), `source` (which platform file or class), `docs` (which Academy page).
   A guess is marked `unverified`. Write the platform version you saw it on (for example `8.3.2`) and the database
   (PostgreSQL / MS SQL).
4. **English**, plain sentences, one idea per bullet. No praise, no apologies. Numbers in a table, not in prose.
5. Sections in this order, every section present (write `nothing` if empty). Under this list write one line with
   the platform version and the database of the sites you worked on (`project.json` `environment.version`).
6. **Start from the logs, not from memory.** Call `tool_stats(days=<the days of this work>)` and read
   `dev/gaps/gaps.jsonl` of the kit (the file `report_gap` answers with). Section 4 starts from the `misbehaved`
   lines; section 5 must account for every `env_sql` call in the stats table (what each was for, grouped); section
   6 lists every script under `dev/gaps/scripts/` written for this work, with its `gaps.jsonl` line; section 7 is
   derived from the `missing` lines. Add what the logs miss, but do not drop what they hold.

## 1. What was done

Three to eight lines: the kind of work (new object + page, a process, an integration, a migration, UI tests...),
how many schemas / processes / cases roughly, which tiers of proof you used (unit, probe, OData backend cases,
process cases, UI cases).

## 2. What went well

Which tools, skills, recipes and rules saved you time or caught a mistake. Name the tool and the moment
(`describe_schema` before reading files found the replacing layer; `verify_pushed` showed the site ran the old
body; the `IsChanged` rule in `push_package`). One line each.

## 3. What went badly

Where you lost time, were wrong, or had to redo work. For each: what happened, what you expected, what you did
instead, how long it cost (rough). Include wrong answers from a tool or a recipe, with the exact wording that
misled you.

## 4. Tools that misbehaved

Every MCP tool, toolkit command, skill or recipe you called that did not do what its description says or answered
less than you needed: the call as you made it (arguments in generic names), what came back, what you expected, what
was missing or wrong, and what you did to get the real answer. Include an answer that was right but too long, cut
or in a shape you could not use. One block per tool, the worst first. This is the section the kit's authors read
first.

## 5. What you did by hand

Everything you did without a tool of the kit: queries typed into `env_sql`, files read one by one, a value looked
up in the designer, a page element found by trial, a package pushed twice to see the difference. For each: the
goal, the steps, how often you repeated it. These lines become new tools.

## 6. Scripts and probes you wrote yourself

Every script, SQL file, Playwright probe, PowerShell or Python snippet you wrote because no MCP tool or toolkit
did it. For each: what it does (one line), its input and output, the generic code inline in a fenced block (names
replaced per rule 1), and which existing tool it should become part of (or "a new tool: `<name>(args)`").

## 7. Tools you missed

The tool you wished you had, as a call signature and one sentence of what it returns, in the order of how often
you needed it: `find_element_by_caption(path, text) -> element name, page, container`. Say what you used instead.

## 8. Creatio platform facts

The knowledge dump. One bullet per fact, in this shape:

- **F-<n> <one-sentence fact>.** How seen: `run | sql | source | docs | unverified`; version `8.x.y`, database.
  Why it matters (one sentence). Where it bit you (one sentence, generic).

Cover whatever you met, for example: schema and package behaviour (layers, replacing, `Custom`, `IsChanged`,
`ModifiedOnUtc`, install order, SQL scripts, data bindings), processes (publish, compile, signals, timers, logs,
parameter mapping, filters), pages (Freedom UI requests, handlers, business rules, Classic diff and rules, the DOM
the tests see), data access (OData paths, ESQ quirks, services, CSRF), rights and roles, system settings, clio
commands (what a command really does, exit codes, noise on success), the designer (what it rewrites), performance
numbers you measured (rows, seconds, what was measured). Put the surprising ones first.

## 9. Traps for the next agent

Five to fifteen lines, each "If you see X, it means Y, do Z". The things that would have saved you a day.

## 10. Open questions

What you could not verify and how someone with more rights or another site could (one line each).
