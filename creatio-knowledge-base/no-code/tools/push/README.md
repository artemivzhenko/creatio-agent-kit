---
description: Push a Creatio package to an environment in one command - clear IsChanged, push-pkg, check that every script task compiled, check compilation log, publish processes with scripts, and probe the changes.
---

# Push command

Push a package to an environment with drift, task ownership and compilation checks. Pure Python standard library.

| File | What it does |
| --- | --- |
| `push.py` | CLI (the commands are listed under Commands) |
| [`../creatio_schemas/push.py`](../creatio_schemas/README.md) | the library (`push`) |
| `tests/` | `python tests/test_push_tools.py` |

## Commands

<!-- commands:start -->
```
python push.py <package> -e <environment>          push and check
python push.py <package> -e <environment> --probe  also run probes
python push.py <package> -e <environment> --dry-run print commands only
python push.py <package> -e <environment> --bin <Terrasoft.WebApp/bin>   compile script tasks against these assemblies
python push.py <package> -e <environment> --build [--project <project.json>]  first build Files/Bin/<Pkg>.dll against the site version's bin
python push.py verify <package> -e <environment> [<Schema> ...] [--bin ..]  is the site running this code: one line per schema; exit 1
python push.py served <Schema> -e <environment> [--out <file>] [--grep <text>]  the served conf/content text: size, md5, matching lines
python push.py page <package> <Page> -e <environment> [--dry-run] [--force]  one Freedom UI page over clio update-page, then verify
python push.py deps <package> -e <environment> [--add <Package>[,<Package>]] [--dry-run]  fill DependsOn UId/version from the site's SysPackage
```
<!-- commands:end -->

## How it works

The command checks environment drift since the package's last git commit (the schemas of the package
- joined through `SysPackage` by the descriptor's `UId` - modified on the environment after that commit; a schema whose
folder descriptor is dated at or after the site's `ModifiedOn` is the push's own: the install stamps the site with that date and a
download writes the site's date into the folder, so a schema pulled after a designer save and edited here passes),
checks that no dependency was dropped (a `DependsOn` entry of `descriptor.json` or a `Reference` /
`ProjectReference` of `Files/*.csproj` that git HEAD has and the working copy lost; `--force` lets it
through), checks changed files against other active task locks, and updates the dates of changed SQL
scripts. It then clears `IsChanged` in `SysSchema`, `SysPackageSchemaData` and `SysPackageSqlScript`, runs `push-pkg`, reads the compilation log, compiles assembly packages with
`compile-package --wait`, optionally checks a baseline and publishes processes with script or user
tasks. The first line is `clio: <version>` (`clio ver`, read once per push). A clio that answers `Option 'wait' is
unknown` gets `compile-package` without it, and the step polls `CompilationHistory` (P-9.10) every 15 s up to 600 s (clio's
own `--wait-timeout`) for a row written after the start for `<Pkg>.csproj` or `Terrasoft.Configuration.ODataEntities.csproj`
(on the 8.3.2 test site a package build writes both, the ODataEntities row about 20 s later; the client sites of D55 wrote the
ODataEntities row only): `ok (clio <version>: no --wait, polled N s)`, `...; no <Pkg>.csproj row, ...ODataEntities.csproj ok)`
when only the second came; any new row with `Result` false is a failure. `IsChanged` is cleared because designer-edited schemas otherwise count as modified locally
and `push-pkg` skips them; `SysLocalizableValue.IsChanged` is cleared too, for the rows of the package's own schemas only (S48-T03:
a schema made in the designer kept its strings `IsChanged=true` and push-pkg did not overwrite its Caption), and the step says
`ok (SysSchema, SysPackageSchemaData, SysPackageSqlScript, SysLocalizableValue of the package's schemas)`.

**How the compile verdict is read** (S48-T01). A clio with `--wait` (8.1.0.158): `compile-package` exits 0 on a good build;
a non-zero exit is a failure, with two exceptions. `another compilation is in progress` (P-9.9: the install's own build still
runs) is retried every 15 s up to 600 s, one line per retry, on the summary too (`  ... another compilation is in progress: retry in 15 s (N s waited)`).
`Package compilation failed for '<Pkg>' (build result 0)` with no `CSnnnn` line is `ok (clio said failed, but the build result
is BuildResultType Success/NoChanges and no error line)`: `buildResult` is `Terrasoft.Core.Packages.BuildResultType`
(Success=0, Error=1, NoChanges=2, read from the 8.3.2 `Terrasoft.Core.dll`), and clio failed on the answer's `success` flag.
A clio without `--wait` is polled as described above. The `compilation log` step reads the `Succeeded:` flag of the summary
as well as the error count; for an assembly package (its own build is compile-package's) it stops only on an error in the
package's own files, `compile FAILED: <the first error line>`, and otherwise answers `ok (Finished building project:
Succeeded: False. Errors: 2. ... none in <Pkg>; compile-package decides)` instead of a bare `ok`. While one clio call runs
(push-pkg, compile-package, any other) the push prints `  ... still running (N s)` every 60 s, on the summary too.

After drift, the `package schemas` step compares the schema folders of the package with git HEAD (`git ls-tree HEAD
Schemas/`) and, when the site answers, with the package's rows in `SysSchema`: a schema that HEAD or the site has and the
folder does not stops the push with `package install deletes schemas absent from the package: <names>`, `--force` or not.
A site row whose `UId` is a folder here under another name (`descriptor.json`) is a rename, not a deletion: the step says
`ok; renamed <old> -> <new>` and the old name in HEAD does not stop it either; when the site renamed first (the old name
is in HEAD only), the committed `descriptor.json` UId of the old folder decides the same way (S48-T03); without a site answer
HEAD's names decide.
A select with zero rows is an empty answer: clio 8.1.0.158 writes `[]` to the `-d` file (and the count for an update; 8.3.2
test site), an older clio writes no file for it and prints `Done`. A missing file after `Results saved to`, or without `Done`,
is a lost answer and raises `wrote no result` - in `Clio.sql` and in `Environment.sql` alike (`environment.sql_answer`; the
second read a lost answer as zero rows before S48-T03).
The install of a trimmed package deletes those schemas on the site (on a client site it then failed on a foreign key and
rolled back). Without git and without a site answer the step says `not checked (no git, no site)`.

**A stale assembly** (S44-T06): for an assembly package the `stale bin` step compares `Files/Bin/<Pkg>.dll` with
`Files/cs` (and `Files/src/cs`): a source or a folder newer than the dll - an edit, or a file deleted there after the build
(the folder's time moves) - or no dll at all while sources exist stops the push with the file and the minutes: `push-pkg`
installs that dll as it is, and the site keeps running the old classes (seen: a deleted probe service still answered).
Build the package and push again; `--skip-stale-bin` (MCP `skip_stale_bin`) passes on purpose and the step says so.
A source newer than the dll by less than 5 s is one checkout, not a stale dll; with git, `Files/cs` as committed (`git status
--porcelain Files/cs` empty) answers `ok (Files/cs as committed: the committed dll is its build)` (S48-T02). The stop names the
way out: `push.py --build, or --skip-stale-bin when that fails on foreign errors`; a `--build` whose every error is in a file
outside the package says `all N foreign (not in <Pkg>'s own files): --skip-stale-bin is right then, the server build decides`.
**`--build`** (S46-T09) does that build as a step before `stale bin`: `dotnet build Files/<Pkg>.csproj -c Release
-p:CoreTargetFramework=net472 -p:CoreLibPath=<bin> -p:DebugType=none` with obj in temp, so the package gets the dll only;
the step answers `build: built against <version> (<bin>); 2 MSB3245 (unresolved: ATF.Repository, ErrorOr)` (the template's
`Libs` references, left out of the package). `<bin>` is `--bin`, else `paths.platformBin` of `--project`; its
`Terrasoft.Core.dll` version must start with the project's `environment.platformVersion`, and no bin, or another version, stops
the push at `build` naming both places (the decision: `project/README.md`). The script compile check then uses the same bin.
The unit tests (`dotnet test` of `tests-init`'s command) rebuild the dll against the local test binaries: push with `--build`.
A package that is not an assembly package but whose `Files/cs` holds `.cs` files answers `stale bin: WARN Files/cs is never
compiled - not an assembly package (Type 1, ProjectPath)` (a warning, not a stop). Without git the `foreign files` step answers
`skipped (no git; schema_impact is the lock between tasks)` and the push goes on (with or without `--task`); with git it still stops on another task's files.
The CLI writes the whole log to `push-<Pkg>-<time>.log` (the task folder, else temp) and prints the summary and `details: <file>`.

**DependsOn from the site** (S46-T04): `push.py deps <package> -e <env> [--add A,B] [--dry-run]` reads `SysPackage` once and fills every entry with an empty `UId` or `PackageVersion` and adds the `--add` names (one line each: `filled`, `added`, `unchanged`, `not on the site` - exit 1). The push's `dependencies` step stops on such an entry (`<Name> has no UId/version - run push.py deps`) and says `ok (no git: not compared)` without git.

**One page without the install** (S44-T03): `push.py page <package> <Page> -e <env> [--dry-run] [--force]` (MCP
`push_package(page=...)`) saves that Freedom UI page's body from the working copy with clio `update-page` - replace mode, into
this package (`--target-package-uid`), against the checksum `get-page` reads just before (another session's save in between
is a conflict; `--force` overwrites it) - and then runs `verify` for that schema. Nothing else of the package moves: not
its bindings (a push cannot skip one: a package pushed without its `Data/` loses its binding rows on the site, P-2.18 - so
the bindings stop above names this verb), not its other schemas. The site must let the designer edit the package: one
installed from an archive, or whose maintainer is not the site's `Maintainer` setting, answers "created by third-party
publisher or installed from the file archive", and the verb says to push the package instead (the test site's own test
package is such a one: the save was refused there, the dry run passed).

A package that lost a schema on purpose - a merge folded its layer into another package - is pushed with
`--allow-removed <Schema,...>` (MCP `allow_removed`): the stop is lifted for exactly those schemas, and only when each is
absent from the folder and the site's references check of `describe.py merge` (every NO ACTION key to `SysSchema.Id`,
`env/README.md` "References to a layer a merge removes") finds no row pointing at the package's layer; otherwise the push
stops with `--allow-removed names a schema still in the package folder: <names>` or `<Schema> is still referenced:
<table>.<column> N rows`. The step answers `ok; removal allowed: <names>`. The schema's own rows are not references to
it: `SysLocalizableValue` (its Caption, parameter captions, images), `SysSchemaContent` and `SysPackageResourceChecksum` rows
of the removed schema are left out of the count (S48-T03; on the 8.3.2 test site a removed user task held 2 + 1 such rows and
the install deleted it with them).

When the compilation log has errors, the step groups the compiler lines by package (`Pkg/<Pkg>/` in the path, else the
`<Schema>.<Package>.cs` name the configuration build gives a schema's source), prints the first error of each and stops
with `compile FAILED: N error(s) in <Pkg>, M error(s) in <Other>` - `(none in <this package>)` when the errors are someone
else's: the push still exits 1 (the site does not compile), but the line says whose code to fix.

The `bindings` step reads every `Data/<Name>` of the package and, for the rows whose key (the binding's `IsKey` columns,
else `Id`) already exists on the site, compares each column the binding writes with the site's value. Measured on the
test site (S33-T01): the install applies a binding only when its `descriptor.json` `ModifiedOnUtc` differs from the
site's `SysPackageSchemaData.ModifiedOn` of it (a changed `data.json` alone is not applied); when applied, it rewrites the
**force-update** columns of an existing row and keeps the site's value in every other column. So a difference in a
force-update column is a conflict: one line `<object> <key>: <Column> site <value> -> package <value> (force update)`,
and the push stops unless `--force`. The other differences are one line, `N value(s) on the site differ and are not
overwritten`, the values themselves in the details file. The statement per binding, 50 keys per `or`:
`select "<key>", "<column>"... from "<object>" where ("<key>" = '<value>') or ...` - a lookup column is its `<Name>Id`,
localizable, binary and audit columns are not compared, empty and `null` are equal, numbers compare by value. A
binding whose object the site does not have yet (the select fails) is listed as `not compared` and does not stop it.

A drift check that clio cannot run at all (`execute-sql-script wrote no result`: the environment, the network) is
`drift: not checked (clio returned no result)` and the push goes on; a schema changed on the site still stops it.
A schema newer than the commit whose site `md5(MetaData)` and largest `SysSchemaContent` md5 equal the folder's
`metadata.json` and `.js` / `.cs` (line endings tolerated, as `verify`) and that is not `IsChanged` (a designer save sets it) is this task's own earlier push or a merge pushed
unchanged: `drift: ok (3 newer than the commit, same as the working copy)` (S48-T02). Any other is drift, named with the site's
`ModifiedOn`, `ModifiedBy` and `IsChanged`: `drift: FAILED UsrOrderPage (changed on the site 2026-11-26 10:12 by Supervisor,
IsChanged)`; `--force` pushes over it and says `forced (N changed: ...)`.

The `process dates` step advances the descriptor `ModifiedOnUtc` of every process whose `metadata.json` changed (git
status against HEAD; without git, a `metadata.json` written more than 2 s after its descriptor): the install regenerates a
process only when that date moved, and twice a process ran its old code after a push without it. Only the date changes:
the BOM and CRLF stay byte for byte. The same step advances the descriptor date of every binding whose `data.json`
changed (the same two rules): the install applies a binding only when its date differs from the site's, so a changed
`data.json` alone is silently not installed; the `bindings` check still stops a force-update column that differs on the
site. The same two rules advance the descriptor of every client schema (Classic or Freedom) whose `<Name>.js` or
`metadata.json` changed - the install regenerates `conf/content` only for a schema whose date moved (`client <Name>`) - and,
with git, the package's own `descriptor.json` when a `DependsOn` entry was added or dropped against HEAD: push-pkg skipped a
changed `DependsOn` while the descriptor date equalled the site's `SysPackage.ModifiedOn` (`package (descriptor.json,
DependsOn changed)`; S48-T03). `--skip-sql-dates` skips it with the SQL dates; a dry run prints `update ModifiedOnUtc for changed processes` and
`update ModifiedOnUtc for changed bindings`.

Right after `push-pkg`, the `script compile` step proves every process of the package with a script task compiled. A
script that does not compile leaves the process unpublished: every start answers "publish the process before starting
it" with process id `Guid.Empty` and no `SysProcessLog` row, while `compile-configuration` and `SysSchema.LastError`
stay silent about it. The step reads the generated source, the `SysSchemaSource` row `<Process>.cs` (namespace
`Terrasoft.Core.Process`, the usings the process declares, clio returns it base64), and:

- no row: `process <X>: no generated source after the install`, exit 1;
- a row older than the process's own `SysSchema.ModifiedOn`: `process <X>: generated source older than its schema (not
  regenerated by the install)`, exit 1 - the install regenerates the source of a changed process only, after its row;
- the source compiled locally with the .NET SDK's `csc` as a net4.x library against the .NET Framework reference
  assemblies, every managed `*.dll` of the Creatio `bin` (`Newtonsoft.Json.dll` included, not what the reference
  assemblies provide, not the 3 native ones) and the newest
  `conf/bin/<n>/Terrasoft.Configuration.dll` next to it, together with the package's `Files/cs` so a script may call the
  package's own classes; an error inside the process source is `process <X>: script does not compile: CS0103: ...`,
  exit 1, before the compilation log and the probes;
- no binaries (no `--bin`, no `paths.platformBin` in the `--project` file, no `$CREATIO_BIN`, no `TestCoreLibPath` in the workspace's `tests/Directory.Build.props`
  of S15, or no SDK): `process <X>: script compile not checked (no binaries)`, the step passes.

The binaries are taken in this order: `--bin`, `paths.platformBin` of `--project`, `$CREATIO_BIN`, the workspace's
`TestCoreLibPath`.

A class of another package the local binaries do not have is a false `CS0103` / `CS0246`: give `--bin` the site's own
`Terrasoft.WebApp/bin` then.

`push.py` does them all in order, stopping at the first failure. A failure after `push-pkg` says the package is on
the site: `push FAILED at script compile; the package is on the site (push-pkg ok): run clio compile-configuration -e <env>
and push.py verify <Package>` (the later steps: `run the push again`).
Also available as the MCP tool `push_package`, with the same v2 safety options.

```bash
python push.py UsrPkg -e dev                      # push and check
python push.py UsrPkg -e dev --probe              # also run probes
python push.py UsrPkg -e dev --dry-run            # print commands only
python push.py UsrPkg -e dev --project project.json --task tasks/001-order
python push.py UsrPkg -e dev --tasks tasks --task tasks/001-order --baseline tasks/001-order/evidence/errors.txt
```

`--project` reads `paths.tasks` from the supplied project; `--tasks` overrides it. When a tasks
folder is supplied, `--task` must identify the current task folder directly inside it (a bare name such as `001-order`
resolves under `--tasks`, else under the project's `paths.tasks`; an absolute path or a folder that exists from here is
taken as it is - the push log `details:` lands in that folder; a name that is no folder there is refused with the list of
the folders that are: `no '001' there; pass one of: 001-order, 002-shipment`). Without a
tasks folder the ownership check is skipped. `--force` allows drift; `--skip-drift`,
`--skip-foreign-files`, `--skip-sql-dates` and `--skip-compile-package` explicitly skip their
respective checks or steps. `--baseline` creates a file containing the current compilation error
lines on first use; later runs fail on new error lines. Without a baseline, non-assembly packages
still fail on configuration compilation errors.

`<package>` is a path or a name: `push.py UsrPkg` finds `packages/UsrPkg` under the current folder or
next to `--project`, and says `no package folder named UsrPkg; give its path (packages/UsrPkg)` otherwise.
A database error (a SQLSTATE line from clio, which exits 0) fails the step: a drift check that cannot run
does not pass.

Output: one line per step, then a summary line with timing or the failed step. A failed step prints 200 characters of its error and the
details file the whole text (clio's output is not cut); a failed publish prints the whole error
(the message chain without the stack frames) and `publish: pushed schemas among the failed: <names>` or `publish: no
schema of this package is named in the error`. The MCP tool answers the summary only - the step lines and `details:
<file>`, the whole log (in the task folder when `task` is given, else the temp folder). A dry run performs
no subprocess calls or writes, reads `dry run` on every step that would have run, and ends with
`dry run of <pkg> -> <env>: N steps, nothing sent`.

## Is the site running it: `push.py verify` (S33-T05)

`python push.py verify <package> -e <env> [<Schema> ...] [--bin <Terrasoft.WebApp/bin>]` (MCP `verify_pushed`), read-only, after a
push and before trusting a test. One statement reads every `SysSchema` row of the package: `md5("MetaData")` and the md5 of the largest
`SysSchemaContent`. On the test site these are, byte for byte, the md5 of `metadata.json` and of the `.js` / `.cs` file as the
repository holds them (30 of 30 schemas of a package), so a line per schema:

```
UsrOrder          same
UsrLf             same (line endings)              equal once CRLF / LF are swapped: a git checkout converted the file
UsrOrderPage      differs (body: site d204f8e8 repo cc6255d2)
UsrGone           not on the site
UsrProcess        not published: generated source older than its schema
UsrProcess        compile error: CS0103: The name 'UsrMissingHelper' does not exist ... (+1 more)
UsrOrderPage      not served: conf/content holds another body (the site's client cache is older)
29 same, 1 not
```

A script process is also checked the way the push checks it (its generated `SysSchemaSource` exists, is newer than the schema and
compiles with `--bin`). A client schema is also fetched from `conf/content/<Schema>.js` (with `Accept: */*` under `0/`; the JSON
accept the environment's own calls send gets a 406). The site serves the composed body of every layer, so the whole text of a middle layer is never
inside it: the check looks for the layer's own members (a Freedom page: its `viewConfigDiff` operations except removes and its handler
`request` names; a Classic schema: its diff operations, methods and rule UIds; read by the layout readers) and says
`same, served (12 of 12 members)` or `not served: 3 of 12 members missing (<first three>)` or `not served: conf/content has no such file`.
A schema with no members (a bare module) is still matched by its whole text. Exit 1 on any line that is not `same`.

`python push.py served <Schema> -e <env> [--out <file>] [--grep <text>]` prints the served text's size and md5, saves it with `--out`
and prints the lines holding `--grep` with their numbers (exit 1 when the site serves no such file). A schema's `<Schema>Resources`
module is not a file of its own on the 8.3.2 test site (404 at every path tried; the Classic body only names it in a `define`
dependency): its strings are checked in `SysLocalizableValue`.

## Traps

- The script-or-user-task detection reads the package's process metadata files looking for
  `ProcessSchemaScriptTask` or `ProcessSchemaUserTask` class names - it does not parse the
  metadata structure, just searches text.
- `--probe` checks objects and SQL scripts. Rules need attribute values and processes are
  proved by process cases, so neither is probed here. It also compares the default culture's `Caption` of every pushed schema (its
  `resource.en-US.xml`) with `SysSchema.Caption` on the site and logs `caption of <X> not updated: site '<a>', package '<b>'` - a
  note, not a failure (after a push the caption of a process stayed old although the resource file carried the new one).
  A replacing object whose parent is not in the workspace is skipped by its probe (`skipped: parent <Parent> not in the workspace ...`); the step prints `probes: ok (2 skipped: <names>)`, a skip is not a failure.
