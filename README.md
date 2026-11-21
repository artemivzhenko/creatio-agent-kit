# Creatio agent kit

Everything an AI agent needs to build and prove Creatio customisations as package files: a knowledge base of
recipes and verified platform facts, Python toolkits that write business processes, rules, objects, pages, cases,
data bindings and SQL scripts byte for byte, a describe layer that answers questions about a package without
reading its files, a UI and backend test framework with its own DSL, two MCP servers that give all of it to an
agent as tools, and four agent skills (Claude Code, Codex, Copilot) that turn the tools into roles.

## Layout

| Folder | What it holds | Start at |
|---|---|---|
| [creatio-knowledge-base/](creatio-knowledge-base/README.md) | 177 code recipes (Classic UI, Freedom UI, C#, SQL), the clio reference, `no-code/tools/` (17 package toolkits, the describe layer, the environment layer), the `creatio-kb` MCP server (44 tools), the skills `creatio-kb`, `creatio-author`, `creatio-tester`, `creatio-loop`, the platform facts register | its README |
| [automatic-creatio-tests/](automatic-creatio-tests/README.md) | the test framework: `.act` cases in a small DSL over Playwright for Freedom UI and Classic UI pages, process cases and OData backend cases without a browser, the `creatio-tests` MCP server (11 tools) | its README, [docs/dsl.md](automatic-creatio-tests/docs/dsl.md) |
| [ci-cd/](ci-cd/README.md) | the pipeline of a package repository: `pipeline.py` with the stages check, build, register, deploy (IsChanged cleared, push-pkg, compile, restart, Redis), unit tests inside Creatio, UI cases; templates for GitHub Actions, GitLab CI and Jenkins; `clio-ext.py`, the developer's commands around clio (push-all in dependency order, hierarchy, localization and process checks, OAuth service); the check, hierarchy, lint, build, deploy and push-all stages are also `ci_*` tools of the knowledge-base MCP server | its README |
| [postman/](postman/) | a Postman collection for manual API checks against a site; a helper, not part of the pipeline | - |
| [AGENTS.md](AGENTS.md) | the rules for any AI that changes this repository | - |

## Quick start

Requires Python 3.10+, .NET 8 SDK, at least one agent CLI (Claude Code, Codex CLI or GitHub Copilot CLI), and
clio for the package round trip.

```bash
git clone <this repository>
cd creatio-agent-kit
py -3 agent_setup.py                 # python3 on macOS and Linux; --dry-run prints the commands, --check plans only
py -3 agent_setup.py --agents codex  # one agent instead of every one found: claude, codex, copilot
```

The script creates the virtual environments of both MCP servers once, then, for every agent CLI it finds, registers
`creatio-kb`, `creatio-tests`, `context7`, `microsoft-learn` and (with the .NET 10 SDK) `roslyn-codelens` at user
scope with the interpreter of each venv, so the paths follow the clone, and copies the four Creatio skills into the
agent's personal skills folder (`~/.claude/skills` for Claude Code, `~/.agents/skills` for Codex and Copilot). Claude
Code also gets the ponytail plugin and graphify. Re-running it is safe. Then:

```bash
cd automatic-creatio-tests && dotnet build && dotnet test        # the framework, no browser needed
powershell -File src/CreatioAutoTests.Cli/bin/Debug/net8.0/playwright.ps1 install chromium   # once
```

## How a task runs

On a project the tools run as two roles under one task-folder contract: the **author** builds the task from
`project.json` (the environment, the package, the paths) with the toolkits, pushes with `clio push-pkg`, probes
and runs the unit tests; the **tester** proves every acceptance criterion with the tier it needs (unit, probe,
OData backend case, process case, `.act` UI case), keeps the evidence and writes the report. The contract, the
files of a task folder and the proof tiers are the skill
[creatio-loop](creatio-knowledge-base/skill/creatio-loop/SKILL.md); the roles are
[creatio-author](creatio-knowledge-base/skill/creatio-author/SKILL.md) and
[creatio-tester](creatio-knowledge-base/skill/creatio-tester/SKILL.md); the recipes come through
[creatio-kb](creatio-knowledge-base/skill/creatio-kb/SKILL.md).

## Tests

| What | Command |
|---|---|
| a package toolkit | `python creatio-knowledge-base/no-code/tools/<toolkit>/tests/test_<toolkit>_tools.py` (plain functions, no pytest; `describe/tests/test_describe.py`) |
| the knowledge base index and the MCP tools | `creatio-knowledge-base/mcp-server/.venv/Scripts/python.exe creatio-knowledge-base/mcp-server/test_kb_index.py`, `... test_server_tools.py` |
| the tool docs in sync | `python creatio-knowledge-base/no-code/tools/tests/test_sync_tool_docs.py` |
| every CLI writes UTF-8; the record history and timer tools | `python creatio-knowledge-base/no-code/tools/tests/test_utf8_cli.py`, `python creatio-knowledge-base/no-code/tools/env/tests/test_env_history.py` |
| the test framework | `dotnet test` in `automatic-creatio-tests/` |
| the framework's MCP server | `automatic-creatio-tests/mcp-server/.venv/Scripts/python.exe automatic-creatio-tests/mcp-server/test_server.py` |

## Licence

MIT. See [LICENSE](LICENSE).

## What is not in the repository

Kept outside the repository: `project.json` files with credentials, the MCP servers' virtual environments, `.creatio-index/` stores written next to packages,
and the framework's `Reports/` and `Configuration/creatio.env.config.json`.
