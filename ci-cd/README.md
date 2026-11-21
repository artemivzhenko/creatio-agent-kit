# ci-cd

The CI/CD of a Creatio package repository in one place: a pipeline script with one subcommand per stage, ready-made
pipeline templates for GitHub Actions, GitLab CI and Jenkins, and clio-ext, the developer's commands around clio. Everything runs on
Python 3.10+, the .NET 8 SDK and clio; no Terrasoft assemblies, no PowerShell needed for the pipeline itself.

## The pipeline

| Stage | When | Command | What it does |
|---|---|---|---|
| check | before a merge | `python pipeline.py check packages` | the package rules: every schema folder has `metadata.json`, `descriptor.json`, `properties.json`; no duplicate schema UId across the packages; no `alert(` or `debugger` in a `.js` schema; one `.sql` per `SqlScripts/<Name>/` named after its folder; one `.dll` per `Assemblies/<Name>/`; `--cyrillic` also refuses Cyrillic outside comments |
| build | before a merge | `python pipeline.py build packages --out Build` | `clio compress` per package, the `.gz` files and one `Build/Pkg.zip` as the artifact |
| unit tests, no site | before a merge | `dotnet test tests` | the C# unit tests of the package test project (the kit's `creatio-loop` tier `unit`) |
| register | on the runner | `python pipeline.py register ci --url --login --password` | `clio reg-web-app` from the pipeline's secrets |
| deploy | after a merge | `python pipeline.py deploy packages -e ci` | `IsChanged` cleared in `SysSchema`, `SysPackageSchemaData`, `SysPackageSqlScript` (designer-edited schemas count as modified locally and `push-pkg` skips them otherwise), `clio push-pkg` per package in order, `compile-configuration` (`--all` for a full rebuild), `restart-web-app --wait-ready`, `clear-redis-db`, `healthcheck` |
| unit | after a merge | `python pipeline.py unit -e ci --runner <process>` | the unit tests inside Creatio through the kit's `env/unit.py` (a runner process or service in the package); exit 1 on a failed test, `--evidence` keeps the runner's answer |
| ui | after a merge | `python pipeline.py ui --root uitests` | the `.act` cases with the kit's test framework; the site from `CREATIO_URL` / `CREATIO_LOGIN` / `CREATIO_PASSWORD` when `Configuration/creatio.env.config.json` is absent; the service paths, `objects.config.json` and `run.config.json` come from the framework when absent, `Configuration/pages/` (and `static.values.json`) are the project's own. Folders in the config are relative to `--root`; reports land in `<root>/Reports/` (the templates upload `uitests/Reports/`). Exit 0 all passed, 1 a case failed, 2 the run could not start |

From an agent the same stages are the `ci_check`, `ci_hierarchy`, `ci_lint`, `ci_build`, `ci_deploy` and `ci_push_all` tools of the
kit's creatio-kb MCP server (`run_tests` runs the unit stage, the creatio-tests server the UI stage); they run these
scripts in-process, which is why every clio call's output is captured and printed, not streamed.

Package order: `--package A,B,C` as given; else `.clio/workspaceSettings.json` next to the packages folder; else
dependencies first from each `descriptor.json`. Every stage exits non-zero on a failure. Tests of the site-free stages:
`python tests/test_pipeline.py`.

## A new project

1. Copy the template into the package repository: [templates/github-actions.yml](templates/github-actions.yml) to
   `.github/workflows/creatio.yml`, [templates/gitlab-ci.yml](templates/gitlab-ci.yml) to `.gitlab-ci.yml`, or
   [templates/Jenkinsfile](templates/Jenkinsfile) to `Jenkinsfile`.
2. Point it at the kit (`KIT_REPO`) and, when the install order matters, list the packages in `PACKAGES`.
3. Add the secrets: `CREATIO_URL`, `CREATIO_LOGIN`, `CREATIO_PASSWORD` (a user with `CanManageSolution`). Set
   `UNIT_RUNNER` to the test runner process of the package to run the unit tests inside Creatio.
4. The layout the templates assume: `packages/<Package>/` (a clio workspace), `tests/` with the C# unit test
   projects (optional), `uitests/` with `Cases/` and `Configuration/` (optional). Change the paths in the template
   when yours differ.
5. The deploy runs on a runner that reaches the site: a self-hosted runner for an on-premise instance.

Production is not in the templates on purpose: add a manual job for it when the team is ready.

## clio-ext: the developer's commands around clio

One Python script, [clio-ext/clio-ext.py](clio-ext/clio-ext.py), with the practices of the earlier PowerShell and Python
extensions merged; `-p` names the packages folder (default `./packages`), every push clears `IsChanged` first
(`--keep-ischanged` leaves it), every command exits non-zero on a failure.

| Command | What |
|---|---|
| `init -d <dir> [-e env] [-b branch]` | a working directory: `repo/` and `backup/` clio workspaces, `logs/`, `clio-ext.config.json` |
| `deploy -d <dir>` | `restorew` into `backup/` (the site's packages, archived by timestamp) -> `compress` -> `IsChanged` cleared -> `pushw` from `repo/` |
| `pull <package or all> -e env` | `clio pull-pkg` one package, `restorew` for all |
| `push <package or all> -e env` | `clio push-pkg` one package, `pushw` for all |
| `push-all -e env [--package A,B or --list hierarchy.txt] [--continue-on-error]` | one package at a time, dependencies first (the order of `pipeline.py`); stops at the first failure, or with `--continue-on-error` pushes the rest and writes the failed ones to `error-pkg.txt`, which `--list` takes back for a retry; one log line per step in `logs/<date>.log` |
| `hierarchy [--out hierarchy.txt] [--report package-hierarchy.txt]` | the install order by levels from `descriptor.json`, and a report: dependencies inside and outside the folder, dependents, descriptor problems (`Name`, `ProjectPath`) |
| `find-missing-loc -p <dir> [-l uk-UA]` | schemas without `resource.<locale>.xml`; exit 1 when any |
| `validate-processes -p <dir> [-k package]` | Read Data elements that read every column of an object; exit 1 when any |
| `deploy-oauth --creatio-root <dir> --identity-service-zip <zip> [...]` | the OAuth 2.0 Identity Service on IIS + PostgreSQL: certificate, IIS site and pool, the client in the database, HTTPS bindings; `--what-if`, `--rollback`, `--reset-client`, `--config-path` |

Tests: `python tests/test_clio_ext.py`. The Postman collection of manual API checks is at the kit root, [../postman/](../postman/).

## Where it came from

The package rules and the pipeline stages are a port of the PowerShell CI scripts of an earlier project repository
(`Test-PackageRule*.ps1`, `Build.ps1`, `Upload.ps1`, a GitLab pipeline with one deploy job per branch); the build no
longer needs the Terrasoft assemblies and the upload is `clio push-pkg` with the kit's `IsChanged` rule in front of it.
