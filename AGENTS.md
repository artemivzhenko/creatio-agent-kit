# AGENTS.md

Orientation for any AI agent (Claude, Codex, Copilot or another) working in this repository. Read it first, then
the `AGENTS.md` of the part you touch: [creatio-knowledge-base/AGENTS.md](creatio-knowledge-base/AGENTS.md) (recipes,
toolkits, the MCP server; what not to "fix") and [automatic-creatio-tests/AGENTS.md](automatic-creatio-tests/AGENTS.md)
(the test framework: the DSL, the layers, the invariants).

## Rules for anything you write here

- **No real names.** No name of a client, customer, partner, project, environment, site, server, database,
  workspace folder or package; no schema prefix but `Usr`; no client's own schema, column, lookup, process, role,
  setting or user name; no client business value (captions, statuses, codes, amounts, addresses, e-mails, GUIDs of
  real rows); no URL, host or path of a real site; no line of a real log, error or screenshot that carries any of
  these. If it would tell a reader which client it is, it is out. This holds in code, tests, fixtures, docs,
  comments, file and folder names, commit messages, and in chat text handed over for pasting.
  Placeholders only, from this vocabulary: stock objects by their product names (`Account`, `Contact`, `Order`,
  `Invoice`, `Product`, `Case`, `Opportunity`, `Lead`, `Activity`, `Contract`); custom things with the `Usr` prefix
  and a generic noun (`UsrOrder`, `UsrShipment`, `UsrStatus`, `UsrOrderPage`, `UsrOrder_FormPage`, `UsrPkg`,
  `UsrTests`, `UsrRunTests_Process`); the environment `dev` and the words "the test site", "the client site",
  "the client package", "the client workspace"; the user `Supervisor`; GUIDs of the form
  `5d2a1c3e-0000-4000-8000-00000000000N`; `https://dev.example.com`. A real name has one home: the commands you
  run against a site. A real name in a change is a defect of the change, not a nit.
- **English only** in code, comments, docs, test names and reports.
- **No git write commands** from an agent: no commit, branch, checkout, stash, reset, push. The human commits.
  `git status` and `git diff` are fine.
- **Package files are bytes.** The toolkits write them; never touch a file under `packages/` or a fixture with
  `sed -i` or an editor that changes line endings or the BOM.
- **Every new branch of logic gets a test** in the toolkit's `tests/test_*.py` on a fixture with `Usr` names
  (plain functions, no pytest), or in the framework's `tests/`. Fixtures are never copies of a client package.
- **Never connect to a site** nobody named for the work; workspaces of other sites are read-only. Before every
  `clio push-pkg` run `clio execute-sql-script 'update "SysSchema" set "IsChanged"=false' -e <env>`.
