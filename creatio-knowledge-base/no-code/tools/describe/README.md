---
description: Describe layer - what a Creatio package holds, what a schema is and one part of it (columns, elements, flows, rules, page elements, attributes, handlers, data sources) on request, without reading metadata or page bodies; 6x-40x fewer tokens than the files; describe_package, describe_schema, describe_item, index_workspace, find_schema as MCP tools and a CLI; a self-checking package index gives the files of a schema and who uses it without searching.
---

# Describe layer

Reading a schema file costs 6x-40x the tokens its summary does (an object 9.5k chars against
1.5k, a process 488k against 12k). This layer sits between the package files and the agent:
ask, do not read.

**The summary is counts.** `describe_schema` of a Freedom UI page prints the elements counted per container and type
(`tab GeneralInfo: 120 elements (46 ComboBox, 31 Input, ...)`, the eight biggest containers, then a count of the rest), the attributes and the
data sources with their attribute counts, the handlers by request name and size, the rule count (and how many are disabled) and the validator and
converter counts - about ten lines whatever the size of the page, never the element list (`describe_item <Page> "elements"` is that, `element <name>`
one of them). A Classic page prints its `diff` as operations with counts and the busiest parents (`insert 11 (under UsrInfoContainer 3, ...)`,
`diff op=insert` lists them) and its `methods` by name only (`method <name>` reads one).

| Call | Answers |
| --- | --- |
| `describe_package(<package>, kind="")` | one line per schema and SQL script: kind, name, caption, counts, parent or replaced base |
| `describe_schema(<package>, <Schema>)` | the toolkit's summary (what `inspect` prints) |
| `describe_item(<package>, <Schema>, "<query>")` | one part, chosen by the query; nothing else |
| `index_workspace(<path>, rebuild=False)` | builds or refreshes the index of every package under a workspace root, a packages folder or one package; reports added / changed / removed |
| `find_schema(<path>, <Schema>)` | the package, kind, summary, every file (absolute paths), the schemas it refers to, the schemas and data bindings that refer to it |
| `schema_diff(<package>[, schemas, against])` | the working copy against git HEAD, a revision or a folder, in schema terms: `+` `-` `~` lines per item (see "Schema diff") |

The same calls are MCP tools of the `creatio-kb` server and the CLI `describe.py package |
schema | item`. `<package>` is the package folder (`packages/UsrPkg` in a clio workspace).

Verified on two production workspaces (579 and 475 schemas, 33 and 56 MB, files only): every
schema opens and answers its summary and queries - objects, processes, rules, Freedom UI pages
(designer and template body forms, trailing commas included), mobile pages (plain JSON
bodies, read-only), DCM cases and user tasks; a package of 579 schemas lists in ~1.5 s from the
index. C# - source code schemas and Files/cs - answers by signatures (see below). Classic UI
client schemas and data bindings are listed with their files until their topics land.

## Commands

<!-- commands:start -->
```
python describe.py package <package> [--kind object|process|rules|page|sql|client|addon|source|csharp|dcm|user-task]
python describe.py schema  <package> <Schema>
python describe.py item    <package> <Schema> "<topic> [<name>] [key=value ...]"
python describe.py item    <package> <Schema> topics                 # what this schema can answer
python describe.py index   <workspace|package> [--rebuild] [--stats] [-e <env>]  # build/refresh the index (.creatio-index/index.sqlite); -e: the site's extra columns and schemas
python describe.py find    <workspace|package> <Schema>              # package, files, refers to, used by
python describe.py find-text <workspace|package> <regex> [--kind page|object|...|resource] [--context 1] [--limit N]  # a regex over the indexed files
```

| command | what it does |
| --- | --- |
| `package` | one line per schema |
| `schema` | the summary of one schema |
| `item` | one part of a schema |
| `index` | build or refresh the package index |
| `resolve` | the workspace by what users call things: a caption (or a Usr name) -> objects, pages, columns, elements, parameters, lookup values, ranked |
| `who-sets` | every place that writes <Entity>.<Column> [= value]: process steps and scripts, C#, pages, SQL scripts |
| `who-reads-message` | the publishers and subscribers of a message sender |
| `find` | where a schema lives and what touches it |
| `find-text` | a regex over every file the index knows: <Package>/<Item> (<kind>) <line>: <text>; resource XML only with --kind resource |
| `lookups` | every lookup object (parent chain reaches BaseLookup) with bindings and users |
| `deps` | typed dependencies of a schema over the workspace: what it builds on and who builds on it |
| `impact` | the dependents of the schemas a task changes, and the other active tasks that change or affect them; exit 1 on a conflict |
| `layers` | the copies of a schema on an environment, applied first to last; exit 1 when the Custom layer has one |
| `snapshot` | an object as lines: effective columns over the workspace layers (disk), table columns / rows / checksums / copies (site) |
| `merge-plan` | the plan of collapsing each schema's replacing layers into one: target, additions, conflicts, dependencies; read-only, exit 1 on a conflict |
| `merge` | the replacing layers of one object or page collapsed into one layer of the target package; prints the files, --apply writes them; exit 1 when it stops |
| `merge-package` | one child package folded into its parent: layers merged, the rest moved with the UId kept, DependsOn redirected; --apply writes; exit 1 on a stop |
| `merge-run` | merge-package with tests, snapshots and push around it, evidence in a folder; without --apply a rehearsal; exit 1 on a stop, red case or difference, 3 when paused |
| `compare` | two snapshot files: + - ~ lines; exit 1 on a difference |
| `export` | a snapshot for reading without the tools: one text file per schema, one per package |
| `diff` | the working copy against git HEAD, a revision or a folder, in schema terms: + added, - removed, ~ changed lines |
| `uid` | what a UId names in the workspace (a schema, a column, a process element or parameter), a dotted name's UId, or a text with every UId named |
| `review` | a pulled package against git HEAD: line endings / BOM only, content changes, dependencies, orphan resources; --keep restores the rest |
| `precommit` | the staged files that must not be committed: over 5 MB, archives, binaries outside Files/Bin, files outside packages/; exit 1 |
<!-- commands:end -->

## The package index

`<workspace>/.creatio-index/index.sqlite` (next to `packages/`, one file for every package of the workspace; add the
folder to the workspace's `.gitignore`, it is a cache - delete it and the next call rebuilds it) holds, per schema, SQL script, data binding and plain C#
file under `Files`: kind, caption, summary line, parent or target, every file with size and
mtime, and the schemas of the workspace it refers to - by name or by UId found in its text files.
A `Files/cs` item is the one file, named by its package-relative path, with no descriptor or
resources; other items refer to it through the types it declares, so `find_schema UsrOrderLabel`
finds the file and who calls it. `describe_package` and
`find_schema` answer from it: a 578-schema package lists in 1.5 s instead of 35 s, and the agent
gets the files to open and the impact of a change in one call.

The versioned index also stores binding targets, row counts, columns and up to 40 Code or Name
values, plus each schema's resource cultures, en-US key count and missing-key counts. An older
index format is rebuilt automatically.

The store (`describe/store.py`, stdlib `sqlite3`, S26-T01) keeps each package's dict in rows: `packages` (one row, the
header fields as `head`), `nodes` (one per schema and `Data/<name>` binding: `kind`, `caption`, `summary`, `parent`, and the
builders' `entry` JSON unchanged), `files` (path, size, mtime), `edges` (the typed deps: `to_kind`, `to_name`, `to_uid`, `via`,
`ref`, `detail`), `refs`, `captions` (FTS5, `unicode61`: what `resolve` searches),
`meta`. A refresh writes one package in one transaction; WAL and a 5 s busy timeout let two sessions share the workspace (the
second writer waits; a reader sees the last committed package). A `<Package>.json` from before is deleted on first use (one
line on stderr) and the package rebuilt from disk; a corrupt store file is deleted and rebuilt. A Python whose SQLite lacks FTS5
gets a plain `captions` table (`meta.fts5 = 0`); the readers then use `LIKE`.

**Operating the store (S26-T03).** `describe.py index <workspace> --stats` (MCP `index_workspace(path, stats=True)`) adds,
after the refresh lines: the file, its size (with the WAL), `meta.format` and FTS5, the platform version when S31-T09 wrote
one, rows per table, and per package its build time (`refreshed_at`: when its rows were last written) and unreadable count.
`--rebuild` re-reads every package as before (the S31 tables are not touched). A store file that is not a database, or one
another toolkit wrote, is one line first (`<path>: not a store this toolkit reads (<error>); rebuilt from disk`) and is
deleted and rebuilt, nothing else tried; a store of an older format is one line (`store format 3, this toolkit writes 4;
every package rebuilt`): each package's head carries the format it was saved with and an older one is rebuilt from disk.
Concurrency: WAL, a 5 s busy timeout, one transaction per package refresh. A second agent reading during a refresh or a
rebuild sees the old rows of a package until that package's commit, then the new ones, never half a package; a second
writer waits up to 5 s. Local disk only. A workspace call opens one reader for all its packages (35 opens cost ~0.3 s on
the biggest client workspace; on the test workspace a lookup went from ~57 to ~40 ms). The file is never read raw: the
`describe_first` hook denies a `Read` or `Grep` under `.creatio-index/` and names these tools.

The tables the S31 passes fill (format 4; a package refresh never touches them, a pass replaces the rows of its `env`;
`at` is the ISO time of the pass, so a stale pass shows):

    platform_captions (package text, schema text, key text, culture text, text text)    S31-T09, from the local install;
        index on (schema collate nocase, key); meta.platform_version = the install's CrtCore version
    site_columns (env text, at text, package_of_object text, object text, name text, type text, package text,
                  caption text, missing integer)                                        S31-T10: columns of the site's table
        the workspace does not define; a table missing on the site is one row, missing = 1, name null;
        index on (env, object collate nocase)
    site_schemas (env text, at text, name text, uid text, kind text, package text, caption text)
                                                                                        S31-T11: schemas of the workspace's
        prefixes on the site that no workspace package defines; index on (env, name collate nocase)

**Workspace queries (S26-T02).** The lookups over the whole workspace are statements over those rows, after the usual
refresh of every package: `find_schema` (the item by name, its bindings, `dependents` from `edges.to_name`, `used by` from
`refs`), `lookups` (the `object` nodes and their parents, binding rows, one `group by` for the use counts), `schema_deps`
in direction `in` and `schema_impact` (`edges`), `find-text` (the file list from `files`, the text still from disk) and
`resolve` (`captions` filtered by `fold(text)`, Python's casefold, so a part of a word and any script match; the ranking and
the "closest" fallback as before). The store's format 3 adds `refs (package, node, to_name)` (the names an item's text
refers to; a binding refers to its object), a binding's object as its node's `parent`, the `uid` of every entry (`nodes.uid`)
and every row `resolve` searches in `captions` (a schema's own caption, element lists, lookup values). The answers are the
same lines: 323 answers over the 91 items of the test workspace are identical before and after. `Workspace` (workspace.py)
and the builders keep their scan, `resolve_uid` with them (it reads `Workspace`). What a call costs is the refresh, not the
statements: on the test workspace (3 packages, 91 items) a lookup is ~150 ms, of which ~145 ms is the freshness walk over
every item's files and ~3 ms the statements (before the T04 walk below). A store that cannot be written (a read-only checkout) does not fail them:
the fresh rows go into a throwaway store for the call and the answer starts with `(index stale: built from disk - the
store cannot be written here: ...)`, as `describe package` does.

Format 6 (S31-T01) adds the captions, read in the package's **primary culture**: the culture with the most resource keys across
the package (one culture = that one; a tie goes to `culture` in the workspace's `project.json`, then `en-US`). The package header
carries `culture` and `cultures` (keys per culture); an object entry `columns` `{name: caption}` (own columns), a Freedom page entry
`elements` (`name`, `type`, `parent`, `control`, `caption`), a process `parameters` and `elements`, a user task `parameters`, a rules
addon `rules` `{BusinessRule_x: caption}`, a lookup binding `keys` `[{value, caption}]` (the caption of the primary culture's
`Localization/data.<culture>.json`, else the row's own `Name`, else the value). A key the primary culture lacks is `null`. When the
primary culture changes (a culture added or removed), every item is re-read in it. `describe_item <Schema> resources` starts with
`primary culture: <culture> (<keys>; <other cultures>)`. Nothing else printed changes; the fields wait for `where`, `map`, `resolve`,
`about` (S31-T02..T05). Size: the fixture index grows 7-11 %, a 36-schema package of the test site 106 171 -> 124 099 bytes (+16 %).

The index checks itself on every use: a file whose size or mtime changed, a schema folder that
appeared (after `clio pull-pkg`) or disappeared is re-read before the answer, and when names
appear or disappear every item's references are rescanned. There is no refresh hook to wire into
a pull script; `describe.py index <workspace>` after a pull only tells what changed. The check (S26-T04) is one
`os.scandir` walk per package over `Schemas`, `SqlScripts`, `Resources` and `Data` (an item's files are its folder's and
each `Resources/<name>.*` folder's), compared with the store's `files` rows; the entries of an up-to-date package are not
read from the store at all, only what an answer asks for. A workspace lookup on the test workspace went from ~180 to ~55 ms,
on the biggest client workspace (35 packages, ~29 700 files) from ~9.1 s to ~1.1 s (what is left: the directory listing
itself, ~0.45 s, and one store connection per package, ~0.3 s). `--rebuild`
starts over. A change of the toolkit itself (a new kind, another `summary` or `opens`) changes no
package file, so the index does not see it: such a change bumps `INDEX_FORMAT` in `index.py`, or
run `describe.py index <workspace> --rebuild` after updating the toolkit. A change of the *kinds* (a kind added, removed or reordered in `registry.py`)
needs neither: the index header carries a registry fingerprint and rebuilds itself on mismatch.

A broken item costs one line, never the answer: a schema, C# file or data binding that cannot be
read (an empty `data.json`, a `Data/` folder without its descriptor, a parser error) is stored as
`{"error": "<type>: <message>"}` - the message names the file - and listed as `cannot read:` in
`describe.py package`; `describe.py package <pkg> --kind error` lists only those. `find` and
`lookups` skip them and end with `N items unreadable (describe.py package <pkg> --kind error lists
them)`; asked for a broken item by name, `find` answers its error in one line. A file that is not
UTF-8 is read as cp1251 (a `.cs` saved in the Windows code page) and its item's summary ends with
`(cp1251)`; a writer that saves such a file writes it as UTF-8. `CSharpSource` never raises: a file
it cannot read answers `summary()` = `unreadable: <reason>`.

## The platform captions (S31-T09)

A base column (`CreatedOn`, `Owner`, `Account.Type`) or a base page's string is captioned in the platform's packages, not in the
workspace. With `paths.platform` in `project.json` (the local install's root, its `Packages` folder of `<Package>.gz` archives, or a
`Terrasoft.Configuration/Pkg` folder of package folders) `index` reads the install once into the store's `platform_captions`: for
every package the `Resources/<Schema>.Entity` and `.ClientUnit` strings (`Caption`, `Columns.<Name>.Caption`,
`LocalizableStrings.<Name>.Value`) in the workspace's primary cultures and `en-US`. `index` prints one line,
`platform 8.3.2.4199: 60083 captions of 316 packages (en-US, uk-UA) in 7.1 s`, then `..., up to date` while the path, the version and
the cultures stay. The version is `Terrasoft.Core.dll`'s file version (else `CrtCore`'s `PackageVersion`, which says `7.8.0` on 8.3.2),
in `meta.platform_version` and the `--stats` line, so a mismatch with the site's version is visible.

The `where` lines of a Freedom and a Classic page fall back to it: `-> PDS UsrOrder.CreatedOn 'Created on' (CrtCoreBase)` instead of
`(caption not in workspace)`; a system column is captioned from `BaseEntity`. The culture asked for, else `en-US`. Without
`paths.platform` nothing changes. On this machine (8.3.2, the full product line: 398 archives, 1.2 GB) two cultures are 60 083 rows,
12 MB of store, 7.1 s once.

## The site's columns and schemas (S31-T10, T11)

The workspace holds the client's packages; the table on the site holds every layer's columns, and the site has schemas in packages
nobody checked out. `describe.py index <workspace> -e <clio env>` (MCP `index_workspace(path, env=)`) adds, after the refresh, three
read-only statements for the whole workspace (3.9 s on the test environment):

- `information_schema.columns` of every object's table of the index. A column the workspace does not define (a lookup's `XId` is the
  workspace's `X`) is a row of `site_columns`: env, time, object, name, type, package, caption.
- Its package: the `SysLocalizableValue` keys `Columns.<Name>.Caption` of the object's `SysSchema` copies and their parents
  (`ParentId` up, so a lookup's `Name` is `BaseLookup`'s): the own schema that captions it, the deepest first, before a replacing
  copy. Measured against reading each layer's metadata: one statement of ~1 s for every object at once, against a body per layer and
  object, so the keys it is. No key anywhere (a physical column from a SQL script, a designer leftover): `package not found`.
- Its caption: the shallowest copy's in the site's `PrimaryCulture`, else the platform captions (T09), else none.
- A table the site does not have: one row with `missing`.
- `SysSchema` rows (not replacing) whose name starts with a prefix of the workspace (`project.json` `prefixes`, else every prefix two
  of the workspace's own schema names share: `Usr`, `ia`) and that no workspace package defines: `site_schemas` (env, time, name,
  UId, kind, package, caption). A name the workspace has with another UId is a line of the report (renamed or recreated on the site).

```
site dev (2026-11-21): 90 columns beyond the workspace in 7 objects, 3 package not found
site dev (2026-11-21): 0 schemas beyond the workspace in 0 packages (prefixes Usr)
  UsrOrder on the site has UId <a>, the workspace <b>
```

Then `columns` of an object ends with `UsrRegion  'Region'  Lookup  site: UsrOtherPkg` / `UsrLegacyCode  character varying(50)  site:
package not found` (a filtered list stays the workspace's), `map` adds a `site:` group, `describe_schema` a
`site (dev, 2026-11-21): 4 columns beyond the workspace, 1 package not found` line, `find_schema UsrRegion` answers
`UsrRegion  object 'Region'  site: UsrOtherPkg (not in workspace)  (dev, <date>)` and `resolve` lists the site schemas by caption.
The date is the pass's: a pass replaces its env's rows; without `-e` nothing is read and the rows stay until the next pass.

## Typed dependencies

`describe.py deps <workspace|package> <Schema> [--in|--out] [--kind object] [--via lookup]` (MCP
`schema_deps`; topics `uses` and `used-by` of every item; `find` prints both directions) answers
"what does this build on" and "who builds on this" from edges the index stores per item
(`creatio_schemas/describe/deps.py`, format 3). An edge is `to_kind to_name via ref detail`:

- `via` is one closed word per kind - object `parent`, `lookup`; process `signal`, `read-data`,
  `add-data`, `modify-data`, `delete-data`, `sub-process`, `user-task`, `param`; dcm `entity`,
  `step`; rules `target`, `column`; page `parent`, `data-source`, `module`; classic `parent`,
  `entity`, `detail`, `mixin`, `module`, `lookup`, `rule`; data `binds`; sql `after`, `table`;
  csharp/source `listener`, `esq`, `query`, `string`.
- The words of code: `esq` - `new EntitySchemaQuery(esm, "X")` or `GetInstanceByName("X")`, with
  the columns `esq.AddColumn("Y")` names until the block ends; `query` - `Select ... From("X")`,
  `Into("X")`, `new Update(uc, "X")`, a join, with the `Column` / `Set` columns when the statement
  names one table; `listener` also lists the columns the listener reads or sets on its object
  (`XId` of a lookup `X` counts as `X`); `string` - a bare literal that is a workspace object's
  name and no other edge reaches. A process script task gives the same words, the element first in
  `detail`. `table` - a SQL script's table after `from`, `join`, `update`, `into`, `alter table`
  that is a workspace or stock object (a CTE, a temp table, a comment, a string is not). `column` -
  the attributes a business rule's conditions and actions name, on the target object, or for a page
  rule on its data source's object. Classic `rule` - the columns `businessRules` / `rules` bind,
  on the page's entity; `lookup` - an attribute's `referenceSchemaName`; Freedom `module` - a
  workspace client schema in `SCHEMA_DEPS`.
- `ref` says how sure the edge is: `uid` - the metadata stores the UId (an object's lookup column,
  a process signal, a DCM step); `name` - a name resolved in a context that names the object (a
  page's data source, a listener's `SchemaName`, a Classic page's `entitySchemaName`, the object an
  ESQ or a query constructor names, a rule's target); `text` - a word found in code or SQL (`string`,
  `table`): a suspicion to read, not a proof. One target reached several ways keeps the surest ref.
- `detail` lists the columns: a page's attribute columns are checked against the data source
  object's effective columns (own, replacing copies, the stock parents, the base cache from the
  environment, else the stock catalogue - `entity/assets/stock_columns_8.3.2.json`, every object
  of the 8.3.2 full product with its effective columns), so `Name` there is *that* object's column
  and not a same-named one elsewhere; a column the chain cannot show ends with `?`. An object the
  workspace and the stock 8.3.2 list (`entities_8.3.2.json`, 1527 objects) do not know is printed
  by its UId.

Reverse edges are not stored: `dependents` scans the stored ones over every package of the
workspace. The `refers to` / `used by` lines of `find` stay the untyped text matches.

## Export

`describe.py export <workspace|package> [--out <folder>]` writes a snapshot of the answers for
reading without the tools - a human in a file browser, an agent without the MCP, a broken item
someone wants to see: `<Package>/_package.md` (the `package` lines, then the items that cannot
be read) and one `<Schema>.md` per item - the `schema` summary, `## Depends on`, `## Dependents`
(the typed edges, as `deps` prints them) and `## Files` with absolute paths; bindings under
`Data/`, C# files under `Files/cs/`. An unreadable item is a one-line file with its error. UTF-8,
LF. Each run overwrites the files, removes the files of items that are gone and touches nothing
else in the folder. Nothing reads the snapshot back: the index is the store, this is an export of
it (the whole of a 900-item workspace in about 12 s).

The folder defaults to `<workspace>/.creatio-export` - gitignore it next to `.creatio-index`. For a
client workspace pass `--out` elsewhere: never write inside a client workspace.

## Impact of a change

`describe.py impact <workspace> <Schema>... [--tasks <folder>] [--current <task>] [--md]` (MCP
`schema_impact`) is the graph working for the loop: for every schema a task changes, its typed
dependents, and - with the loop's tasks folder - the other active task folders (no
`success-report.md`) that change one of them (`schemas` of their `schemas.json`: a **conflict**,
exit 1) or depend on it (`affects`: a heads-up). `--md` prints the `## Impact` table the author
pastes into `plan.md` and the `affects:` line that fills `schemas.json`; the tester reads the
table to pick what to regression-test. What the task changes is never listed as what it affects.

## Schema diff

`describe.py diff <package> [<Schema>...] [--against HEAD|<rev>|<folder>]` (MCP `schema_diff`) is the change in
schema terms: the working copy against git HEAD (default), another revision, or a folder holding the package
(a pulled copy of the environment, a workspace, a folder of packages). Per item the lines the describe layer
prints - the summary and every list topic of its kind, unlimited - compared by their first word:

```
UsrOrder  object
  columns
    ~ UsrStatus  Lookup -> UsrOrderStatus 'Status' -> Lookup -> c59697c2-... 'Status'
    + UsrWeight Float 'Weight'
- UsrOrderStatus  object (removed)
UsrPkg against HEAD: 1 changed, 0 new, 1 removed; lines +1 -0 ~1
```

`+` added, `-` removed, `~ key  old -> new` changed; a key that repeats on a side (flows, rows) is compared by
whole lines. The summary adds only what the lists did not say; header lines, `files`, the index topics, `keys`
and the count-only `resources` are left out (a changed caption shows through its column's or element's line).
Nothing is written: the revision is extracted to a temporary folder and removed. The tester reads it to know
what the author changed before mapping the regression rows; the author, to check a pull did what it should.

`--against env:<clio env>` (S22-T04; MCP `against="env:dev"`) compares with the site's copy of the named schemas - after a human
repaired a process in the designer, what did they change. The copy is the package of that name on the site, written into a
temporary copy of the working package the way `clio pull-pkg` lays it out: `metadata.json` is `SysSchema.MetaData` and the body
(`.js` / `.cs`) the largest `SysSchemaContent`, byte for byte (read as base64), the resource strings the copy's
`SysLocalizableValue` rows; the descriptor and `properties.json` stay the working copy's. Then the same comparison: on the test
environment a pushed package gives `no differences against env:dev`, a column added to the working copy is exactly
`+ UsrProbeNote ShortText 'Probe note'`. Name the schemas (`diff <package> <Schema> --against env:dev`); one the site does not have
is `error: <Schema> is not on the site in package <P>`.

## Review of a pulled package, and a pre-commit check

`describe.py review <package>` (MCP `review_download`) sorts the working copy against git HEAD: files that differ only
in line endings or a BOM (compared over the bytes - BOM dropped, CRLF read as LF - what
`git diff --stat -w --ignore-cr-at-eol` would call empty), the items changed in content (the schema diff above, renames
by UId included), dependencies dropped or added (descriptor.json `DependsOn` and the csproj references, the push's own
helper), resource folders whose schema is not in the package, and files git does not track. `--keep <Schema>...`
lists `git checkout HEAD -- <path>` for every changed tracked file outside the kept items (their `Schemas/`,
`Resources/<Item>.*`, `SqlScripts/`, `Data/` files) - the descriptor too, so dropped dependencies come back -
and `--apply` runs those lines. Untracked files are listed, never deleted. The MCP tool only prints.

`describe.py precommit <workspace>` (MCP `precommit_check`) lists the staged files that must not be committed and exits
1: over 5 MB, archives (`.rar .zip .7z .gz .bak`), binaries (`.dll .exe .pdb`) outside `packages/<P>/Files/Bin` of an
assembly package (descriptor `Type` 1), files outside `packages/` and the known roots (`.gitignore`, `.gitattributes`,
`.editorconfig`, `README.md`, `project.json`, `.clio`, `.vscode`, `tasks`, `docs`), and a staged `Data/SysSettingsValue*/data.json` -
`<path>: sets system setting <Code> = <value> on every environment it is installed on` (a binding overwrites the value everywhere
the package goes: a production value was replaced by a test value at deploy time). The setting codes a project accepts go into the
workspace's `project.json`, `"allowedSettingBindings": ["UsrMaxRows"]`. A staged object whose new columns (against HEAD) or whose
new schema the last `index -e` pass found on the site in another package (S31-T12): `<path>: UsrRegion exists on the site (dev,
<date>) in package UsrOtherPkg: reuse it ...`, no `--force` (the human decides at the tool); a physical column and `no site pass yet`
go to stderr and do not stop. As a hook, `.git/hooks/pre-commit`:

```sh
#!/bin/sh
python "<knowledge base>/no-code/tools/describe/describe.py" precommit "$(git rev-parse --show-toplevel)"
```

## UIds

`describe.py uid <workspace> <text>` (MCP `resolve_uid`) names what a UId points at - a schema (own or
replacing copy), a column (`column UsrOrder.UsrAmount`), a process element or parameter - and goes the
other way for a dotted name (`UsrOrder.UsrAmount`, `UsrOrder_Process.ReadData.ResultEntity`,
`UsrOrder_Process.OrderId`). A text with UIds in it - a meta path copied from `SysSchema` metadata, a
filter, several of them - comes back with every UId named, then the text with the names in place:

```
59bdd0b9-...  process UsrOrder_Process element ReadData (UserTask)
c7dfd892-...  process UsrOrder_Process element ReadData parameter ResultEntity
ef3edc7c-...  column UsrOrder.UsrAmount

[Element:{ReadData}].[Parameter:{ResultEntity}].[EntityColumn:{UsrAmount}]
```

Schemas come from the workspace scan, columns from every object's metadata, process items from the
processes - each map is built only when a question needs it. A UId the workspace does not hold (a lookup
row, a system record) says so; `env_sql` finds those.

## Lookups

`describe.py lookups <workspace|package>` (MCP `list_lookups`) lists every object whose parent
chain reaches `BaseLookup` - through the workspace's own objects or the stock ones
(`entity/assets/stock_lookups_8.3.2.json`, 496 names; the 8.2.3 list of 272 is the fallback) - with package, caption, the chain, own
columns, the data bindings that seed it (rows counted) and how many items refer to it. That is
the list a de-duplication or binding-value task starts from. An object whose parent is outside
both the workspace and the stock list is reported as *not decided* rather than guessed.

## Snapshot of an object

`describe.py snapshot <Schema> [--workspace <ws>] [-e <env>] [--columns a,b] [--out <file>]` (library
`creatio_schemas/integrity.py::snapshot`) prints what an object is as lines, and `describe.py compare <before> <after>`
prints the `+ - ~` lines between two of them (`diff_lines`, the same as `diff`) and exits 1 on any difference: an empty
compare after a layer merge is the proof that nothing observable changed.

Disk (`--workspace`), the effective object over every layer in `describe/merge.py::layers_in_order` (the site's order with
`-e`, else dependency order with `siblings ordered by name` when two layers are not ordered by `DependsOn`):

```
layers: UsrPkg > UsrPkg2
column UsrRating 6bfc7215-... Integer required default 3
column Owner 7c85a229-... Lookup lookup Contact default 4f367ca9-...
index IAccountAlternativeName on AlternativeName
```

The first layer's parent (its own copy, or the base `objects.py base` fetched) takes each layer's diff in turn
(`SchemaDiff.apply`, the code `EntitySchema.effective` runs for one layer). A vendor base that is neither on disk nor
fetched stops the snapshot with the `objects.py base` command to run: it would describe the additions only.

Site (`-e`), one statement each, written in [env](../env/README.md#snapshot-of-an-object): `table <T> column <col> <type>`,
`rows <n>`, `checksum <col> <md5>`, `copy <package> extendParent=<bool>`. The MCP tools are `schema_snapshot` and
`snapshot_compare`. A planted difference is tested: a copy of the fixture workspace with one layer's column removed compares
as `- column UsrRating ...`.

## Merge plan

`describe.py merge-plan <workspace> [<Schema>...] [-e <env>] [--limit N]` (MCP `merge_plan`; library
`describe/merge.py::merge_plan`): for each schema with a replacing copy in more than one package of the workspace
(or the named ones), what collapsing those layers into one would do. Read-only: it opens the layer files and
writes nothing, no `.creatio-index` either, so it runs on a client workspace as it is.

```
Contact object: 3 layers, target UsrA
  layer UsrA: +1 column
  layer UsrB: +3 columns
  layer UsrC: +1 column
  siblings: UsrB, UsrC (order guessed)
  conflict lookup UsrStatus -> UsrBStatus (its package UsrB depends on the target): UsrB
  conflict column UsrDup (two UIds): UsrB and UsrC
  depends: UsrA gains UsrExtra
UsrThing object: 2 layers, no common lowest package: UsrB, UsrC
3 schemas, 3 layers to remove, 4 conflicts, 1 without a common lowest package
```

- **Target**: the package every other layer's package depends on, directly or through other workspace packages
  (`DependsOn`). Without one the schema is skipped with `no common lowest package: <the bottom layers>`.
- **Layers** in `layers_in_order` (the site's order with `-e`, a copy only on the site says `on the site only, not
  merged`); the counts come from the describe answers: an object's added columns, a client schema's `diff` items
  and `methods`, a page's `viewConfigDiff` items and `handlers`, a process's elements and parameters, a DCM's stages, a rule
  addon's own rules and the base rules it edits.
- **Conflicts**, each a stop for the merge: one column name with two UIds; one column UId with two types; two layers
  with a `merge` / `remove` / `move` on one element (an `insert` below and a `merge` above is the normal form); one
  method overridden in two layers (`three-deep override` from three), and in such a method a `callParent` inside a
  nested function or with its value assigned; a lookup column whose object lives in a package that depends on the
  target (the merged layer could not see it); an unreadable layer. Rule addons: the same own rule UId in two layers,
  and a base rule removed in one layer and edited in another (several layers editing one base rule is not a conflict:
  the diffs concatenate in fold order, as the platform folds them).
- **Processes, DCM and rule addons** are counted (`+3 elements, +2 parameters`, `+6 stages`, `+1 rule, ~2 base rules
  edited`); a process or a DCM carries `conflict process: not merged by this toolkit (T06)`, and `merge` refuses all
  three kinds (`merge writes objects and pages only`, exit 1).
- **`depends:`** the packages a removed layer's package depends on that the target does not reach yet, leaving out
  the layer packages and any package that depends on the target (that would be a cycle).
- Exit code 1 when there is a conflict, 2 on an error.

## Merge of an object

`describe.py merge <workspace> <Object> [--target <pkg>] [-e <env>] [--apply]` (MCP `merge_layers`, which prints only;
library `describe/merge.py::merge_object`): the replacing layers of one object collapsed into one layer of the target
package. It prints the merge plan for the object, then `write <file>` / `delete <folder>` per file, and writes only with
`--apply`. It stops with `stopped: ... - nothing written` and exit 1 on a plan conflict, on siblings without `-e` (their
order is the site's `SysPackage.HierarchyLevel`, which the files cannot show), on a layer that stores the whole schema,
on a layer the site holds and the workspace does not (a vendor package) that folds after the target - the merge would put the
removed layers' lines before it - and with `-e` on a site row that still points at a layer to remove (the statements are in `env/README.md`, "References
to a layer a merge removes").

- **The diff**: every layer's lines in fold order (the site's `HierarchyLevel` with `-e`, the dependency depth and the name
  without it), as the platform folds them. The lines that say whose layer it is (`UId`, `A5`, `B6`, `B8`, `D36.A3`, `EG1.UId`,
  `EG1.A2`, `EG1.A5`, `EG1.B8`, `EG1.BK8`) come from one layer only; `B6` is the target package. From every layer but the
  top, the lines `EntitySchemaManager.ActualizeSchemaDifferencePackage` drops are left out (an add on a path holding
  `EG1` and `C2`, a remove on `D20.FA*`). The UIds of the removed layers and of their packages become the merged layer's
  and the target's, so each column's `A3` / `A4` / `A5` (created in schema, modified in schema, created in package) names
  the layer that now holds it.
- **The UId**: the target's own layer's when it has one, else the top layer's (`--target` may name a package below every
  layer that holds none).
- **The other files**: `descriptor.json` and `<Object>.cs` of that same layer, `properties.json` of the top layer (the
  object flags of the whole fold), the resource files merged key by key with the upper layer winning.
- **The removed layers**: `Schemas/<Object>` and `Resources/<Object>.Entity` deleted from their packages; `push-pkg` of
  each package then drops its `SysSchema` row, and the table columns and their data stay (S24-T01). No backup step.
- **`DependsOn`**: the target gains the `depends:` packages of the plan, each entry copied from the removed package's
  descriptor.
- Push the packages in any order (the target first is the natural one). Proved on the test site: three layers (two of them
  siblings) merged, the three packages pushed, the snapshot's columns, table, rows and checksums the same before and
  after, the merged layer pulled back byte-identical.

## Merge of a package

`describe.py merge-package <workspace> <child> --into <parent> [-e <env>] [--apply]` (MCP `merge_package`, which prints only;
library `describe/package_merge.py`): one child package folded into its parent. One line per item of the child:

```
layer   object  AccountType                  -> UsrBase   (2 layers: UsrChild, UsrBase)   merge
move    object  UsrProbeMove                 -> UsrBase   uid kept
move    process UsrProbeMove_Process         -> UsrBase   uid kept
move    data    Data/UsrStatus               -> UsrBase
move    source  Files/cs                     -> UsrBase   1 files
depends UsrSibling: DependsOn UsrChild -> UsrBase
depends UsrBase: gains CrtCoreBase
note    process UsrProbeMove_Process         2 runs logged: the schema row keeps its Id when the parent is pushed first, so they stay valid
note    dependencies: push-pkg keeps an installed package's own (S24-T05) - apply the depends lines on the site too
```

- **Layer**: a schema the child replaces and the parent replaces too, merged through `merge` with only those two packages'
  layers (a third package's layer that folds between them is a stop, one above both keeps its place), objects first, then
  pages. A rule addon layer in both is a stop: its merge is not built (S24-T07 counted it).
- **Move**: everything else - the child's own schemas, a replacing layer the parent does not have, SQL scripts, data
  bindings, `Files/cs` (into an assembly parent only; a csproj that lists the files one by one is a stop) - with its resource
  folders, the UId kept. A schema of the child's that a third package replaces is a `note` (its ParentUId keeps pointing at it).
- **Stops** (exit 1, nothing written): a name clash (the parent has a schema of that name of its own, or with another UId), a
  rule layer in both, a Custom layer on the site for a moved schema (`-e`), a stop of a layer merge, a file the parent already has.
- **`depends`**: every other package that depends on the child is redirected to the parent; the parent gains what the child
  depended on and it does not reach. `push-pkg` does not change an installed package's dependencies (S24-T05), so the site
  needs them applied on its own.
- `--apply` writes the layers, moves the rest, rewrites the descriptors and leaves the child with its descriptor.json only.
  **Push the parent first**: installing the parent with a schema the child still holds moves that SysSchema row to the parent
  with its `Id` (verified on the test site: the table, its rows, a process's logged runs stay attached); pushing the child first
  deletes the schema and the parent's push creates a new row. Then push the child (now empty) and the redirected packages.

## The whole procedure: merge-run

`describe.py merge-run <workspace> <child> --into <parent> -e <env> --evidence <folder> [--apply] [--continue] [--tests-root <folder>]`
(MCP `merge_run`, a rehearsal only; library `describe/merge_run.py`): steps 2-8 of the story's procedure, each leaving a file:

| Step | Evidence |
|---|---|
| plan (`merge-package` printed; a stop ends the run) | `plan.txt` |
| cases: `cases-from-package` of the child into `cases/` unless it holds `.act` files already (edit them freely: they are kept) | `cases.txt`, `cases/` |
| tests before: every case under `cases/` on the site; a red case ends the run | `before/report.*`, `before/run.txt` |
| snapshots before: every object and page of the plan, and `pages.py audit --all` of each page | `before/<Schema>.snapshot`, `before/audit.txt` (`after/audit.txt` after the push) |
| without `--apply` the run ends here: `rehearsal: nothing written` | |
| merge, then push of the parent and of the packages in the `depends` lines, lower first | `merge.txt`, `push.log` |
| before the push: the merged `descriptor.json` `DependsOn` against the site's `SysPackageDependency` of the parent (`push-pkg` does not update it); a missing one stops with `parent <P> lacks the dependency <D> on the site: add it in the configuration, then --continue` (exit 1); after adding it, `--continue` pushes and pauses | `push-pending.txt` |
| pause (exit 3): the child's application is removed on the site by hand, then rerun the same line with `--continue` | `paused.txt` |
| snapshots after + compare (layer lines ignored: a merge changes them by design) | `after/<Schema>.snapshot`, `compare.txt` |
| tests after: the same cases | `after/report.*` |

The last line is `merged <child> into <parent>: N layers, M moves, tests K/K before and after, compare same` or the first stop.
Exit 0 done or rehearsed, 1 on a stop / red case / difference, 2 usage, 3 paused. `--tests-root` (default `CREATIO_TESTS_ROOT`, else
`../automatic-creatio-tests`) is the UI test utility whose `Configuration` is copied into `cases/` for the run - **its instance must
be the `-e` site**; the environment file holds a password, so it is copied for the run only and deleted after it. No case ran is a
stop (nothing would prove the merge); a schema the generator skips (`not generated:` in `cases.txt`) is the baseline's gap: read it.
`before/passed.txt` keeps the case count `--continue` compares with.

## Find text

`describe.py find-text <workspace|package> <regex> [--kind object|page|process|...|resource] [--context N] [--limit N]` (MCP `find_text`;
library `describe/index.py` `find_text`) runs a Python regex over the lines of every file the index lists for an item (`files` of each
schema, SQL script, data binding and plain C# file). One line per hit, `<Package>/<Item> (<kind>) <line>: <text>`, the text stripped and
cut at 160 characters; `--context 1` adds the line before and after as `<line>- <text>`. The first line counts the matching lines and
items; the list follows the output contract (40 lines, then the tail). Resource XML (`Resources/`) and binary files are skipped; `--kind
resource` searches resource XML only, any other `--kind` keeps the items of that kind. A bad regex is a `not a regex` error. Then
`describe_item` on the item it names, or a `Read` of that line with `offset` / `limit`. It reads the files on every call (fine for 500
schemas); after S26 the SQLite store answers it.

A Claude Code `PreToolUse` hook can deny a raw `Read` / `Grep` of package schema files and point at `describe_item` and `find_text` instead; the
agents that build this kit run one.

## Resolve: the workspace by caption

`describe.py resolve <workspace|package> "<text>" [--kind object|page|column|element|parameter|lookup|process|rule] [--culture all|<c>] [--limit N --offset N]`
(MCP `resolve_caption`; library `describe/caption_search.py`) searches the captions of the index (T01) case-insensitively: the whole caption first, then a whole
word, then a part, and at equal match object > page / process / DCM / rules > column > page or process element > parameter > lookup value. A `Usr` name resolves the
same way. One line per hit: `column    UsrOrder.UsrDate 'Дата заявки'  UsrPkg`, `lookup    UsrOrderStatus 'Відхилено' = Rejected  Data/UsrStatus  UsrPkg`.
`--culture <c>` or `all` re-reads the items' resources in that culture (the hit names it); lookup values are searched in the primary culture only (a binding's
index keeps its first 40 values). No hit: `no caption holds "<text>"; closest: 'A', 'B'`. The first call on a task text that names things in business words.

## Snapshot and merge of a page

`snapshot` and `merge` take a page (Freedom or Classic, `ClientUnitSchemaManager`) the same way as an object; the library
is `creatio_schemas/page/fold.py` (the fold, the snapshot lines, the Classic method fold) and `describe/merge.py::merge_page`
(`merge` picks it by the manager of the schema's copies).

**Snapshot lines.** Disk (`--workspace`): `layers: a > b`, then the fold of every layer's operations in that order -
`element <name> <type> [parent <p>] [caption <c>]` per element the fold leaves (Freedom: `viewConfigDiff`, the type and the
caption or label), `removed <name>` for one a layer removed; Classic: `element <name> [parent <p>] values <keys>` from `diff`.
Then Freedom `handler <request> #<n>` (the chain position) and `converter` / `validator` keys; Classic `method <name>` and the
`attribute` / `message` / `detail` / `mixin` / `module` keys. Site (`-e`): the `copy` lines; with `--page-file` (the file the
UI test utility's `analyse` wrote from the live page) one `page <code> <type> <label> [columns ..] [tabs ..]` line per element.
The lines that name layers - `layers:`, `siblings`, `copy`, `layer handler <request> <pkg>`, `layer method <name> <a > b>` -
change by design in a merge: `compare --ignore-layers` leaves them out, and that compare is the proof (`same`, exit 0).

**Merge.** The same run as for an object (the plan, the stops, `references`, the UId rule, `DependsOn`, resources by key, the
other layers deleted); `metadata.json` is the layers' diffs concatenated with the source's identity lines (no drops: those are
the entity manager's).

- Freedom: the `viewConfigDiff`, `viewModelConfigDiff` and `modelConfigDiff` arrays concatenated in fold order; the handlers
  one after another in the same array (proved: a handler per layer appending its letter after `next` gives the same `CBA`
  before and after); converters and validators by key, the upper winning (a plan line names the dropped one); `define()`'s
  modules and parameters unioned (a module that would need a parameter the merged list cannot give it is a stop). In
  `viewConfigDiff` a `merge`, `move` or `remove` of an element the merged array itself inserts is folded into that `insert`
  (`absorb`): the Shell does not apply a merge to an element its own array inserts (on the test site the label of the earlier
  insert stayed), and the designer never writes such a pair. An element changed in two layers (the plan's `conflict element`)
  stops without `-e` and merges with it, in the site's order.
- Classic: the `diff` arrays concatenated; `attributes`, `messages`, `details`, `mixins`, `modules`, `rules`, `businessRules`
  by key, the upper winning; a method in one layer moves as it is, a method in two folds **pairwise, bottom up**: the upper body
  with its `this.callParent(arguments);` replaced by the lower body (which keeps its own callParent), so three layers fold in two
  steps. It stops (and says why) on different parameters, no or two callParent calls, a callParent in a callback or with its value
  used, an early `return` of the lower body above upper code after callParent, and a `let` / `const` both bodies declare.
- The `.less` files of the layers, one after another.

Proved on the test site (S24-T05): a Freedom page and a Classic page, each in three packages (two of them siblings), the case
`usr-probe-page-merge` green before and after, `compare --ignore-layers` `same` for both.

## Layers on an environment

`describe.py layers <Schema> -e <env> [--rule <UId>] [--json]` (or `--project project.json`;
library `creatio_schemas/describe/layers.py`) is the one command that reads the environment: every
`SysSchema` copy of the name, applied first to last - package, replacing or not, ModifiedOn and
ModifiedBy, IsChanged, the body's size and md5 (`SysSchemaContent`, else the `MetaData` column).
The order is the package hierarchy of the customisation package (the platform function
`tsp_GetSysSchemaParentsInPackageHierarchyByPackage`, as the object toolkit's base fetch uses it);
copies outside that hierarchy are listed first. With `--rule` each layer says whether the business
rule with that UId is `absent`, `enabled`, `disabled` or `removed` in its body, and the line under
the table names its state in the layer applied last.

Where a layer's body is (measured on the test site, S33-T05 / T07): a client schema's `.js` and a C# schema's `.cs` are the largest
`SysSchemaContent.Content` row of the copy, byte for byte the repository file; every kind's `metadata.json` is `SysSchema.MetaData`.
A Classic page's method over the site's layers is `describe_item <Page> "method <name> env=<clio env>"` (below).

When a copy lives in the customisation package - `Custom`, or `environment.customLayer` of
project.json, or `--custom-layer` - the last line is `Custom layer present: <package> - it cannot be deleted by the tools; the human removes it on the site` and the exit
code is 1: that copy is applied after every package a task pushes and overrides it. The author runs
it before the plan, the tester as the first preflight step; `--json` is the evidence. One SQL call
through `Environment.sql` (tools/env), PostgreSQL only. `--workspace <ws>`: a schema renamed on the site keeps its UId (a push from
git brings the old name back, so one process lives under two names); the site's name for the workspace schema's UId is then read and
the answer says `name on site: <X> (workspace: <Y>)` under the header, the layers listed under the site's name.

The same order over a workspace, for code: `creatio_schemas/describe/merge.py::layers_in_order(workspace, schema,
env=None, manager=None)` returns `Layer(package, folder, replacing, uid, manager, source, siblings)` applied first
to last, in the order the runtime folds them (`SysPackage.HierarchyLevel`: the dependency depth, then the name in
ordinal order). With `env`: the site's copies (`source = "site"`; a site-only copy has `folder = None`), the replacing
ones re-sorted by the site's `HierarchyLevel` (the design-time function above has no tiebreak for siblings); a workspace
copy not on the site yet comes last. Without it, the workspace's copies: the own copy first, then the replacing ones by
their depth over the workspace's `DependsOn` and the name; two copies with no dependency path either way name each
other in `siblings` - their depth may differ through vendor packages the workspace does not hold, so the order is a
guess. It reads descriptors only and writes nothing into the workspace. The layer merge (S24) takes its order from it.

## The output contract

An answer is never a dump. `describe_schema` is the summary: header, counts, problems, and at
most `DEFAULT_LIMIT` (40) lines; a list topic of `describe_item` shows at most that many items.
When something was left out the last line is the tail `  ... N more; add limit=0 for all`.
The parameter is `limit=` in a query, `limit` on the MCP tools, `--limit` on the CLI; `0` means
everything. `offset=` (`--offset`, `offset` on the MCP tools) skips lines first, so a tail continues instead of repeating the page: the page
after the first ends `  ... 20 more; next: offset=80; add limit=0 for all`, an offset past the end is one note line
(`(offset 100 is past the end: 100 lines)`), the default 0 leaves every answer as it was (the first page's tail does not name the offset: that
would change every existing answer). It is on `describe_package`, `describe_schema`, `describe_item` (`columns offset=40`) and `schema_deps`
(applied to each of its two lists), `find_schema` and `list_lookups` (each of their lists) and `merge_plan` (the plan
lines; the totals line always stays).
Constants: `creatio_schemas/describe/core.py` (`DEFAULT_LIMIT`, `TAIL`, `NEXT_TAIL`, `cut`).
The rule for the reader: a part of a schema is asked for with `describe_item`, not read from a
longer dump and not from the file - the file is opened only for what no topic returns, at the
path `find_schema` gives.

## The query grammar

`<topic> [<name>] [key=value ...]` - `topics` lists what a schema can answer; `limit=N` cuts a
list topic (default 40, `0` = all), `offset=K` starts after the first K lines.
The body topics (`handler`, `member`, `method`, `script`) take `lines=a-b` (the body's lines a to b, numbered) or `around=<text>` (the first
line that holds the text with `n=` lines on each side, default 8; quote a text with spaces: `around="x += 1"`); a body over 120 lines asked
without either starts with `<n> lines; lines=a-b or around=<text> for a part`, so the keys are learned from the answer.
The MCP `describe_item` tool also accepts `limit`; an explicit `limit=` in the query takes
precedence. Package, find and lookup lists accept `--limit` on the CLI and `limit` on MCP.

| Kind | Topics |
| --- | --- |
| every schema | `files`, `resources [culture=]`, `resource <key>`, `missing [culture=] [from=en-US]` (keys a culture lacks) |
| object | `columns [type=Lookup] [flag=required] [own=true] [culture=]` (the caption of the package's primary culture follows the name: `UsrDate  'Date'  DateTime`; a column with no caption in it prints nothing extra),  `column <Name>` (line + raw JSON), `flags`, `base`, `map [culture=]` (the columns grouped by type - lookups with their object, text, dates, numbers, flags, other - each with its caption; `(caption not in workspace)` for a base column) |
| process | `elements [kind=FormulaTask]`, `element <Name>` (values, flows in and out), `params [direction=In]`, `flows [from=] [to=]`, `script <Element>` |
| rules | `rules [enabled=false]`, `rule <Name|caption|uid>` |
| sql | `body`, `deps` |
| dcm | `stages`, `stage <name|caption>` (steps, conditions, moves in and out), `steps [stage=]`, `step <name>`, `moves [from=] [to=]`, `filter [raw=true]` |
| user-task | `params [direction=]`, `param <name>`, `methods`, `method <name>` (one method's C#), `source` |
| classic (a 7.x client schema: `define()` module) | `diff [op=insert\|merge\|remove\|move] [parent=]`, `element <name>` (its operations with source), `methods`, `method <name>`, `messages`, `attributes`, `details`, `mixins`, `find <text>`, `method <name> [env=]` (S33-T07: with more than one copy in the workspace, or `env=`, the body in every layer first to last - the workspace's by DependsOn, the site's by `schema_layers` and `HierarchyLevel` with each body from `SysSchemaContent`, `(site only)` / `(not on the site)` marked - each with its line, size and `callParent` or `no callParent: the layers below do not run`; one copy: its body as before), `callers <method>` (`this.<m>(` and `<module>.<m>(` in the workspace's client schemas, comments and strings left out, `<package>/<Schema>.js:<line>  <text>`), `outline` (attributes, messages, methods with line numbers), `where <name> [culture=]` (S31-T08: the insert's caption - a `Resources.Strings` key, a literal, else its column's - the short `itemType` / `contentType`, `bindTo` -> the column with its caption, the `parentName` chain with captions (a `move` wins), the `layout` cell, the layer: added here / `merge in <pkg>, inherited from <parent>`; a detail adds its schema, object and filter column), `where` alone (an edit page: `opens from`; a detail schema: `shown on <Page> as <name>, of <Object> filtered by <Object>.<Column> = Id`; a section: its object and `pages`), `map [tab=<name>] [culture=]` (the inserts as a tree by `parentName`, a grid's cells by layout row and column, others by `index`; the roots are the parent page's containers; details with their schema and filter column) |
| data (a `Data/<Name>` binding; `--kind data` lists them) | `columns` (uid, key, type, localised), `rows [limit=] [culture=]`, `row <key>` (values with lookup display names) |
| C# (source code schema, or `Files/cs/X.cs` by path, file name or stem) | `classes [role=] [kind=] [generated=true]` (types with bases, attributes, role, member count), `members [<Type>] [kind=] [visibility=]` (one-line signatures), `member <Type.Name>` (one body), `usings`, `regions`, `operations [kind=]` (ESQ, raw SQL, Entity save, SysSettings, process start, HTTP, ClassFactory ... by line), `find <text>` |
| page (Freedom UI) | `sections` (names and sizes), `elements [type=crt.Input] [parent=SideAreaProfileContainer]`, `element <Name>`, `attributes [bound=true]`, `attribute <Name>`, `data-sources`, `handlers` (request -> size), `handler <request>` (one handler's code), `validators`, `converters`, `containers`, `find <text>`, `map [tab=<container>] [culture=] [limit= offset=]` (the page as an indented tree: name, caption, short type, a ComboBox's lookup object, a grid's object, a container's element count; the roots sit under the container of the parent page they fill), `about <name> [culture=] [format=json]` (`where`, then the lookup target with its values, the page and object rules that name the element, the handlers that read or write it with line numbers, its validators and converters, the framework's cases that hold its caption or name; `nothing touches X beyond the page`), `where <name> [culture=] [format=json]` (the element's caption, type, control, the attribute -> data source column with its caption, the parent chain with captions and the grid position, the layer: added here / inherited; a name that is not an element: `closest:` three names); `where` with no name: the page's `opens from` lines, below) |

A page is treated as a database: its body is split into view config, attributes, data sources,
handlers, converters and validators, and each query returns one slice. `handlers` names the
requests and their sizes; the code of one comes with `handler crt.SaveRecordRequest`. Base
members of a replacing object are marked `base`.

```bash
python describe.py package packages/UsrPkg --kind page
python describe.py item packages/UsrPkg UsrOrder "columns type=Lookup"
python describe.py item packages/UsrPkg UsrOrder_FormPage "elements parent=SideAreaProfileContainer"
python describe.py item packages/UsrPkg UsrOrder_Process "element ReadOrders"
python describe.py item packages/UsrPkg UsrOrder_Process "element ReadOrders env=dev"   # lookup rows the bindings do not hold, named from the site (S33-T10)
```

### Which section opens a page (S31-T07)

`describe_schema <Page>` of a Freedom page prints, after its summary, one `opens from:` line per `SysModuleEdit` row of the
workspace whose `CardSchemaUId` is the page's UId; `describe_item <Page> "where"` (no name) prints the same lines alone:

```
opens from: section UsrOrders 'Orders' (SysModule UsrOrders_ListPage), object UsrOrder, default page (no type)
opens from: section UsrOrders 'Orders', object UsrOrder, record type UsrStatus = 'VIP' (<id>)
opens from: not registered in this workspace (a parent package may register it)
```

The row's `SysModuleEntity` gives the object and the type column (by UId), `SysModule` the section code and caption (the package's
primary culture), `TypeColumnValue` the record type: its `Name` from the lookup's bindings, else the bare Id; none is the default page.
A Classic schema gets the line only when a binding registers it. `describe_schema <Object>` prints `pages: UsrOrder_FormPage (default),
UsrOrderVip_FormPage (type 'VIP' (<id>))`. `where env=<clio name>` reads the same three tables on the site (read-only SQL), so a
page another package registers is answered; the line ends `(site <env>)`. A test case decides from these lines which record to open.

## C# by signatures

A source code schema (`Schemas/<Name>/<Name>.cs`) and every file under `Files/cs` are read by
regex and brace matching over a copy with comments and string contents blanked - not a compiler
(roslyn-codelens is the tool for depth). Each type gets a **role** from its base or attribute:
web service (`BaseService` / `[ServiceContract]`), entity event listener of `<Schema>`, user task,
app event listener, scheduler job, background task, DTO (`[DataContract]`), DI binding,
exception, interface, enum, static helper, class; anything deriving from the platform's generated
bases or living under `Autogenerated/` is `generated` and hidden from `classes` unless asked.
`describe_package` lists the Files/cs files as `csharp` lines. Verified on 463 files of the
local workspaces (93 types, 721 members, 1 s, no parse errors).

## The registry of kinds

`creatio_schemas/describe/registry.py` is the one place the layer knows a kind: a `Kind` entry
says how to recognise an item (`opens`), build it (`make`), summarise it and which topics it
answers. `open_item`, `kind_of`, `summary`, `topics_of`, the index and the CLI read that list.
Adding a kind is one `register(Kind(...))` with the kind's class, summary and topic handlers -
the kind's own module never imports the describe layer. Order matters: the first entry whose
`opens` says yes wins, so specific kinds sit before the generic `source` / `client` fallbacks.

What a new kind has to know, beyond the `Kind` fields:

- `opens(package, name, descriptor)` gets `descriptor=None` for an item outside `Schemas/` (SQL
  scripts, data bindings, C# files); such kinds test `d is None` and sit before every kind that
  needs a descriptor.
- `register(kind)` inserts first by default (`first=True`), so the new kind wins ties; pass
  `first=False` to append it.
- `open_item` stamps `_kind` on the item; an item built without it is matched by class, first
  entry wins - `source` and `csharp` share `CSharpSource`, so build those through `open_item`.
- `rename(item)` lets one entry answer two kinds (`page` / `mobile`, the fallback's `client` /
  `mobile` / `schema`); `_KIND_LABEL` in `core.py` holds the labels of kinds without a toolkit.
- A kind's `topics` are merged with `COMMON` (`files`, `resources`, `resource`); on a clash
  `COMMON` wins (`topics_of`).
- The index caches `kind` and `summary`: see "The package index" above for the rebuild.

## Kinds without a toolkit

Mobile settings, images and the other addons are listed at package level with their files and
sizes (`describe_item ... files`); resources as a kind of their own are S13-T05.

## Checks

`python tests/test_describe.py` - runs on the other toolkits' fixtures.
