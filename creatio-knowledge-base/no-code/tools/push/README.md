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
python push.py verify <package> -e <environment> [<Schema> ...] [--bin ..]  is the site running this code: one line per schema; exit 1
```
<!-- commands:end -->

## How it works

The command checks environment drift since the package's last git commit (the schemas of the package
- joined through `SysPackage` by the descriptor's `UId` - modified on the environment after that commit),
checks that no dependency was dropped (a `DependsOn` entry of `descriptor.json` or a `Reference` /
`ProjectReference` of `Files/*.csproj` that git HEAD has and the working copy lost; `--force` lets it
through), checks changed files against other active task locks, and updates the dates of changed SQL
scripts. It then clears `IsChanged` in `SysSchema`, `SysPackageSchemaData` and `SysPackageSqlScript`, runs `push-pkg`, reads the compilation log, compiles assembly packages with
`compile-package --wait`, optionally checks a baseline and publishes processes with script or user
tasks. `IsChanged` is cleared because designer-edited schemas otherwise count as modified locally
and `push-pkg` skips them.

After drift, the `package schemas` step compares the schema folders of the package with git HEAD (`git ls-tree HEAD
Schemas/`) and, when the site answers, with the package's rows in `SysSchema`: a schema that HEAD or the site has and the
folder does not stops the push with `package install deletes schemas absent from the package: <names>`, `--force` or not.
The install of a trimmed package deletes those schemas on the site (on a client site it then failed on a foreign key and
rolled back). Without git and without a site answer the step says `not checked (no git, no site)`.

A package that lost a schema on purpose - a merge folded its layer into another package - is pushed with
`--allow-removed <Schema,...>` (MCP `allow_removed`): the stop is lifted for exactly those schemas, and only when each is
absent from the folder and the site's references check of `describe.py merge` (every NO ACTION key to `SysSchema.Id`,
`env/README.md` "References to a layer a merge removes") finds no row pointing at the package's layer; otherwise the push
stops with `--allow-removed names a schema still in the package folder: <names>` or `<Schema> is still referenced:
<table>.<column> N rows`. The step answers `ok; removal allowed: <names>`.

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

The `process dates` step advances the descriptor `ModifiedOnUtc` of every process whose `metadata.json` changed (git
status against HEAD; without git, a `metadata.json` written more than 2 s after its descriptor): the install regenerates a
process only when that date moved, and twice a process ran its old code after a push without it. Only the date changes:
the BOM and CRLF stay byte for byte. The same step advances the descriptor date of every binding whose `data.json`
changed (the same two rules): the install applies a binding only when its date differs from the site's, so a changed
`data.json` alone is silently not installed; the `bindings` check still stops a force-update column that differs on the
site. `--skip-sql-dates` skips it with the SQL dates; a dry run prints `update ModifiedOnUtc for changed processes` and
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
  assemblies, every `Terrasoft.*.dll` of the Creatio `bin` (the messaging pair included) and the newest
  `conf/bin/<n>/Terrasoft.Configuration.dll` next to it, together with the package's `Files/cs` so a script may call the
  package's own classes; an error inside the process source is `process <X>: script does not compile: CS0103: ...`,
  exit 1, before the compilation log and the probes;
- no binaries (no `--bin`, no `$CREATIO_BIN`, no `TestCoreLibPath` in the workspace's `tests/Directory.Build.props`
  of S15, or no SDK): `process <X>: script compile not checked (no binaries)`, the step passes.

A class of another package the local binaries do not have is a false `CS0103` / `CS0246`: give `--bin` the site's own
`Terrasoft.WebApp/bin` then.

`push.py` does them all in order, stopping at the first failure.
Also available as the MCP tool `push_package`, with the same v2 safety options.

```bash
python push.py UsrPkg -e dev                      # push and check
python push.py UsrPkg -e dev --probe              # also run probes
python push.py UsrPkg -e dev --dry-run            # print commands only
python push.py UsrPkg -e dev --project project.json --task tasks/001-order
python push.py UsrPkg -e dev --tasks tasks --task tasks/001-order --baseline tasks/001-order/evidence/errors.txt
```

`--project` reads `paths.tasks` from the supplied project; `--tasks` overrides it. When a tasks
folder is supplied, `--task` must identify the current task folder directly inside it. Without a
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
compiles with `--bin`). A client schema is also fetched from `conf/content/<Schema>.js` (with `Accept: */*`; the JSON accept the
environment's own calls send gets a 406): the served file wraps the body and holds it unchanged, except the module name, which the
site writes in double quotes (`define("X"`). Exit 1 on any line that is not `same`.

## Traps

- The script-or-user-task detection reads the package's process metadata files looking for
  `ProcessSchemaScriptTask` or `ProcessSchemaUserTask` class names - it does not parse the
  metadata structure, just searches text.
- `--probe` checks objects and SQL scripts. Rules need attribute values and processes are
  proved by process cases, so neither is probed here. It also compares the default culture's `Caption` of every pushed schema (its
  `resource.en-US.xml`) with `SysSchema.Caption` on the site and logs `caption of <X> not updated: site '<a>', package '<b>'` - a
  note, not a failure (after a push the caption of a process stayed old although the resource file carried the new one).
