# Project environment synchronization

`python no-code/tools/project.py sync <project.json> | --project <project.json> [--framework <folder>]`
copies `environment.url`, `login`, and `password` from the project into the test
framework's `Configuration/creatio.env.config.json`. The framework defaults to
`paths.testFramework`, relative to `project.json` when not absolute.

`Users` is merged by `Username` (S49-T03): the project's login is updated or added as the first user (the framework's
default), every other configured user is kept, so a task's test users survive a sync. `AllowDevOnly` is written both ways
(`true` when `environment.kind` is `dev`), `ClioEnvironment` is `environment.clioName` and is removed when the project has
none. The config is one file for every site: a run prints `site: <BaseUrl> (clio <ClioEnvironment>)` as its first line.

The tests layout (S51-T01): when `package.workspace` has a `tests/` folder, `sync` also writes `CasesFolders` = every
`<workspace>/tests/<Pkg>/e2e`, `ProcessCasesFolders` = every `.../integration`, `PagesFolders` = every `.../pages` (with
`--package <Pkg>` that package's only), replacing the three lists: the shared config then serves the project's tests, not the
kit's `Cases/`. A package folder without one of them prints `skipped <Pkg>/<tier>: no folder`; `--package` of a package with no
`tests/<Pkg>` is an error. A project without `package.workspace` or without `tests/` keeps the lists as they are. The
framework's `--package <Pkg>` (MCP `run(package=)`) then re-tests the package from those folders.

The tests layout (S51-T01): when `package.workspace` has a `tests/` folder, `sync` also writes `CasesFolders` = every
`<workspace>/tests/<Pkg>/e2e`, `ProcessCasesFolders` = every `.../integration`, `PagesFolders` = every `.../pages` (with
`--package <Pkg>` that package's only), replacing the three lists: the shared config then serves the project's tests, not the
kit's `Cases/`. A package folder without one of them prints `skipped <Pkg>/<tier>: no folder`; `--package` of a package with no
`tests/<Pkg>` is an error. A project without `package.workspace` or without `tests/` keeps the lists as they are. The
framework's `--package <Pkg>` (MCP `run(package=)`) then re-tests the package from those folders.

`paths.platform` (optional, S31-T09): the local platform install (its root, `Packages`, or `Terrasoft.Configuration/Pkg`);
`describe.py index` reads the base captions from it once (`describe/README.md`, "The platform captions").

Existing unrelated configuration and case folders are retained; new files use
`./Cases`. The command prints changed field names, never credentials. The project
file is the source of truth; do not copy credentials back from the framework.
When an existing file changes it is rewritten as JSON; its comments and formatting
are not retained.

## The unit-test project: `tests-init` (S46-T09)

`python no-code/tools/project.py tests-init <project.json>` makes `package.workspace` run the package's unit tests, each step
answering `exists` on a second run: a clio workspace (`clio create-workspace --empty`; `Packages` and `ApplicationVersion`
from `package.name` and `environment.platformVersion`), the package project `Files/<Pkg>.csproj` + `Directory.Build.targets`
(clio's template: `add-package` in a scratch workspace, its `Libs/*.dll` left out), `clio new-test-project --package <Pkg>` (its files then moved into `tests/<Pkg>/unit/`, the S51 layout: the project's
`../../` paths get one level more and the solution's entry follows; a project already directly in `tests/<Pkg>/` is used where
it is, with `test project: exists at the legacy location tests/<Pkg>/ - move it to unit/`),
the test binaries copied from `paths.unitTestBin` into clio's layout `.application/net-framework/core-bin` (+ the newest
`conf/bin/*/Terrasoft.Configuration.dll` into `.application/net-framework/bin`; a copy, not a link, so a clio refresh never
deletes inside an install), `app.config` beside the test project with a binding redirect for every `Terrasoft.*` / `Creatio.*` assembly
of those binaries (the clio test kit is built on 8.3.2.4166 / 8.3.3.1767; without it `FileLoadException` in `SetUp`), then
`paths.unitTests`, `paths.solution` and `commands.unitTests` into project.json and the line `run the unit tests: dotnet test
"<solution>" -c dev-nf`. No `paths.unitTestBin` and no binaries in the layout: the line says so and the exit is 1.

**Which binaries (the decision).** Two local installs serve two builds, and project.json is the only place their paths live:
`paths.platformBin` is the site version's `Terrasoft.WebApp/bin`, the one `push.py --build` compiles the package's dll against
for the push, and `paths.unitTestBin` is any local bin the clio test kit accepts (8.3.2 or newer), the one the unit tests run on.
A version is matched by prefix only where it matters, for the push: `Terrasoft.Core.dll`'s FileVersion of the bin must start
with `environment.platformVersion` (`8.2.3` matches `8.2.3.1351`), else the push stops at `build`; there is no version map
outside the project (`--bin` overrides `paths.platformBin` for one push).

## Commands

<!-- commands:start -->
| command | what it does |
| --- | --- |
| `sync` | write the framework environment from project.json |
| `tasks-from-csv` | one task folder per row of a tracker's CSV export |
| `tests-init` | make the workspace run the package's unit tests; write the run command into project.json |
<!-- commands:end -->

