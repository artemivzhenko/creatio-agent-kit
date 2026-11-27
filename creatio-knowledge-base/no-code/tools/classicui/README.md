---
description: Creatio Classic UI (7.x) client schemas (edit pages, sections, details - define() modules with entitySchemaName, attributes, messages, mixins, details, diff, methods, rules) of 8.x packages as files - read what the schema is, its sections, diff operations, methods, warnings; write a replacing schema of a platform page, adopt a copy pulled from another package (the Custom layer), add a localizable string, disable or remove an inherited business rule by UId, add a mixin, a method or a message, each a splice of one span with a dry-run diff.
---

# Classic UI tools

Scripts for **Classic UI client schemas**: the 7.x edit pages, sections and details that a package
still carries next to its Freedom UI pages - read them, and write what a replacing page needs.
Pure Python standard library.

| File | What it does |
| --- | --- |
| `classicui.py` | CLI (the commands are listed under Commands) |
| `../creatio_schemas/classicui/schema.py` | `ClassicSchema`: the library the CLI uses |
| `../creatio_schemas/classicui/write.py` | its writers (`ClassicWriter`, mixed in) |
| `../creatio_schemas/classicui/layout.py` | `layout` and `rules` over every layer (read-only; the Freedom `pages.py layout` shares it) |
| `../creatio_schemas/text.py` | `mask`: comments and string, template and regex literals blanked (shared with the C# reader) |
| `tests/test_classicui_tools.py` | checks on an edit page and a section shaped like the platform's own |

```bash
python classicui.py inspect UsrPkg UsrOrderPage
python classicui.py diff    UsrPkg UsrOrderPage --op insert --parent Header
python classicui.py method  UsrPkg UsrOrderPage onEntityInitialized

python classicui.py replace    UsrPkg ContactPageV2 --parent-uid <uid> --entity Contact
python classicui.py set-rule   UsrPkg ContactPageV2 <rule uid> --enabled false --column Owner --dry-run
python classicui.py add-string UsrPkg ContactPageV2 UsrHint en-US="Fill in the owner"

python classicui.py new        UsrPkg UsrOrderItemDetail --parent BaseGridDetailV2 --entity UsrOrderItem --caption "Order items"
python classicui.py add-string UsrPkg UsrOrderItemDetail Caption en-US="Order items" -e dev
python classicui.py diff add   UsrPkg OrderPageV2 --op insert --name UsrTerms --parent Header --bind-to UsrTerms --row 18 --col 0 --col-span 8
python classicui.py diff add   UsrPkg OrderPageV2 --op remove --name NotesAndFilesTab
```

## Commands

<!-- commands:start -->
```
python classicui.py inspect  <package> <Schema>
python classicui.py validate <package> <Schema>
python classicui.py methods  <package> <Schema>
python classicui.py method   <package> <Schema> <name>
python classicui.py diff     <package> <Schema> [--op insert] [--parent Header]
python classicui.py layout   <package> <Schema> [--container Header] [-e env]
python classicui.py rules    <package> <Schema> [--rule <UId>] [-e env]
python classicui.py diff add <package> <Schema> --op insert|merge|remove|move --name X [--parent Header] [--bind-to X]
                             [--row 1 --col 0 --col-span 12] [--index N] [--values key=value ..]   [--dry-run]

python classicui.py new         <package> <Schema> --parent BaseGridDetailV2|BasePageV2|<Name> [--entity UsrOrder] [--caption ..] [-e env]

python classicui.py replace     <package> <Schema> [--parent-uid U | -e env] [--entity Contact] [--caption ..] [--cultures en-US,ru-RU]
python classicui.py adopt       <package> <Schema> --from <pulled package or schema folder>
python classicui.py add-string  <package> <Schema> <Key> en-US="Text" [ru-RU="..."] [-e env] [--dry-run]
python classicui.py set-rule    <package> <Schema> <RuleUId> [--enabled false] [--removed true] [--column Owner]
python classicui.py add-mixin   <package> <Schema> <Name> [--class Terrasoft.<Name>] [--module <Name>]
python classicui.py add-method  <package> <Schema> <name> --file method.js [--replace]
python classicui.py set-message <package> <Schema> <Name> --mode PTP|BROADCAST --direction SUBSCRIBE|PUBLISH|BIDIRECTIONAL
```

| command | what it does |
| --- | --- |
| `inspect` | kind, object, parent, sections with sizes, diff elements, warnings |
| `validate` | warnings; exit code 1 on a JavaScript syntax error |
| `methods` | one line per method: name, line, size |
| `method` | one method's source |
| `diff` | one line per diff operation |
| `layout` | a container's grid over every layer (site copies with -e): the element in each cell, free cells |
| `rules` | every business rule over the layers: column, UId, kind, state, conditions, filter, layers |
| `diff-add` | `diff add`: append an operation to diff (CRLF, BOM and indent kept); prints it |
| `new` | a new client schema with a parent: descriptor, diff metadata, properties, empty body, resources |
| `replace` | a replacing schema of a client schema: descriptor, diff metadata, empty body, resources |
| `adopt` | move a client schema pulled from another package into this one (new UId, A5, B6) |
| `add-string` | a localizable string: B2 metadata + resources; a key of the parent chain is overridden |
| `set-rule` | override a business rule by UId in businessRules (enabled / removed) |
| `add-mixin` | a mixin in mixins + its module in define() |
| `add-method` | a method from a file (`function(...) {...}`); --replace for an existing one |
| `set-message` | a message: mode and direction |
<!-- commands:end -->

## A container and the rules over every layer

`layout <package> <Schema> [--container Header] [-e env]` answers "where is a free cell": the copies of the schema's parent chain
(`BaseOrderPage` before `OrderPageV2`; a Classic `Header` is filled by the parent page) and of the schema itself, in the order the
platform applies them, each diff folded in turn (insert, merge of `layout`, move, remove; the last layer wins), then one line per
grid row - the column ranges of 24 with the element in each, `free` where nothing is, `A+B (overlap)` where two share a cell - and one
line per element with the layer that placed it last. The package only names the workspace: a copy in the workspace is read from its
file, with `-e` a copy only on the site is read from the site (`describe/body`), so the vendor base and `Custom` are in it.
`rules <package> <Schema> [--rule <UId>] [-e env]` lists every rule of `businessRules` and `rules` over the same layers (the schema's
own chain, not its parents), merged by column and key: the column, the UId (or key), the kind (`FILTRATION`, `BINDPARAMETER VISIBLE`,
...), the state the last layer leaves, the conditions in one line, for a filtration rule the filter it sets
(`filter City.Country = Country, autoClean`), and each layer's state after it (`UsrA enabled > Custom disabled`).

## How it is stored

```
Schemas/<Name>/<Name>.js          define("<Name>", ["Dep", ...], function(Dep, ...) { return { <sections> }; })
Schemas/<Name>/descriptor.json    ManagerName ClientUnitSchemaManager, Parent (BasePageV2, BaseSectionV2, BaseGridDetailV2 ...)
Schemas/<Name>/properties.json    SchemaType: EditViewModelSchema, ModuleViewModelSchema, GridDetailViewModelSchema, Module
Schemas/<Name>/metadata.json      the schema's parameters as a diff against the parent (= + - ~ lines, CRLF, no final newline)
Resources/<Name>.ClientUnit/      captions and LocalizableStrings per culture
```

The returned object's sections, as counted in 545 schema modules of the 8.3.2 platform pages,
sections and details: `diff` 500, `methods` 454, `entitySchemaName` 451, `attributes` 270,
`details` 238, `messages` 156, `mixins` 121, `rules` 109, `userCode` 35, `modules` 25,
`properties` 19, `columns` 9, `dataModels` 6, `businessRules` 4 - in any order, any of them missing.

- `diff` operations: insert 2172, merge 452, remove 210, move 80. The element's name is on the
  item or inside its `values` (`{"operation": "insert", "parentName": "Header", "values": {"name": ...}}`).
  40% of the `parentName`s (862 of 2140) name containers of the parent schema (`Header`, `Tabs`,
  `LeftContainer`, `ProfileContainer` ...), not of the file itself.
- `methods`: mostly `name: function(...) {...}`; also `Terrasoft.emptyFn` and other expressions.
- `/**SCHEMA_DIFF*/ ... /**SCHEMA_DIFF*/` (also `DETAILS`, `MODULES`, `BUSINESS_RULES`) markers
  wrap the designer-edited sections; they are comments to the reader.
- The body is JavaScript, not JSON: comments, trailing commas, `Terrasoft.*` constants, regex
  literals (11 modules), template literals (7). A mobile settings file under the same manager is
  plain JSON without `define` and is reported as such.

## What the tools write

An untouched schema saves its bytes back. Every writer splices one span the reader found (a
section of the returned object, one member, the `define()` dependency list) and re-parses; the new
text takes the body's newline and indent unit, everything else keeps its bytes. Each editing
command takes `--dry-run` (the diff, nothing written) and validates after saving.

| Command | Writes |
| --- | --- |
| `new <Schema> --parent <P> [--entity]` | a new client schema with a parent (not replacing): descriptor `Parent` {UId, Name}; metadata `= UId`, `= A2`, `= A5`, `= B6`, `= B8`, `- B7` + `+ B7 false`, `= HD1` (the designer's shape of a new grid detail or page); `properties.json` with `SchemaType` (the workspace parent's, else by the parent's name: `...DetailV2` GridDetailViewModelSchema, `...SectionV2` ModuleViewModelSchema, `...PageV2` EditViewModelSchema); the designer's empty body; the caption |
| `replace <Schema> [--parent-uid]` | a replacing schema: descriptor (`Parent`, `ExtendParent: true`); metadata `= UId`, `= A5` (the package's CreatedInPackageId), `= B6` (the package), `= B8`, `+ B7 true`, `= HD1` (the parent's UId - from the workspace, else `--parent-uid`; the error prints the `env/sql.py` query that finds it); the designer's empty body (`attributes`, `messages`, `mixins`, `details`, `businessRules`, `methods`, `diff`; `entitySchemaName` with `--entity`); `properties.json`; the caption in every culture of the package |
| `adopt <Schema> --from <folder>` | a client schema pulled from another package (`clio pull-pkg` + `extract-pkg-zip` by the human; the package folder or the schema folder): copied with its resources, its UId replaced by a new one and its `A5` / `B6` by the target package's in the descriptor and the metadata (the strings' `A3`/`A4`/`A5` follow); then the diff against the parent's body when a workspace package holds the parent |
| `add-string <Key> culture=value .. [-e env]` | `+ MetaData.Schema.B2 {UId, A2 key, A3/A4 the schema UId, A5}` once - before the `~ B2` order line when there is one and last in that order, else after the `A5`/`B2` lines - and `LocalizableStrings.<Key>.Value` per culture; a key the parent chain already has gets the override `= B2.["<its UId>"].A4` / `.A5` instead of an own item |
| `diff add --op .. --name ..` | one item appended to `diff` in the designer's key order (`operation`, `name`, `values`, `parentName`, `propertyName`, `index`); `--bind-to` and `--row/--col/--col-span/--row-span` fill `values.bindTo` and `values.layout` (`layoutName` = the parent), `--values k=v` the rest (a JSON value parsed, else text); printed as written |
| `set-rule <UId> [--enabled] [--removed] [--column]` | the rule's override in `businessRules`: `"<column>": {"<uid>": {"uId": ..., "enabled": false, "removed": true}}`; an override the body has is edited in place; a rule only a workspace parent has is copied whole first (the parent's rule is not changed in the parent); with no parent in the workspace `--column` says where it goes |
| `add-mixin <Name> [--class] [--module]` | `mixins: {<Name>: "Terrasoft.<Name>"}` and `"<Name>"` in `define()`'s dependencies |
| `add-method <name> --file f.js [--replace]` | a member of `methods` (`function(...) {...}` from the file, re-indented); `--replace` swaps an existing one |
| `set-message <Name> --mode --direction` | `"<Name>": {mode: Terrasoft.MessageMode.X, direction: Terrasoft.MessageDirectionType.Y}` in `messages` |

`new` takes the parent's UId from a workspace copy, else from the built-in UIds of `BaseGridDetailV2`, `BasePageV2` and
`BaseModulePageV2` (the same row on every site), else from the site's `SysSchema` row with `-e <env>`; `replace` reads the
same chain after `--parent-uid`. The body is the designer's empty one with `entitySchemaName` from `--entity`; `validate`
passes on it.

`diff add` writes one operation: an `insert` needs `--parent` and refuses a name this diff inserts already, a `remove` takes
only `--name`, `move` takes `--parent` and `--index`, `merge` its `--values`. The item takes the body's indent unit and
newline and goes after the last item (or alone between the `/**SCHEMA_DIFF*/` markers); every other byte stays.

`add-string` on a key of the parent chain (E3: `Caption` of a detail, which `BaseDetailV2` declares) writes the two override
lines - the string stays the parent's item, this schema's resources carry its value; the output says which form it wrote.
The chain is read from the workspace copies first, then with `-e <env>` from the `SysSchema.MetaData` of the parent's rows on
the site (the base rows up `ParentId`, and their replacing copies).

A missing section is added empty (with the designer's `/**SCHEMA_...*/` markers where it has them)
as the last member of the returned object. Strings of a full-form metadata (a module) are refused.
The empty module, mixin module and source code schema come from `tools/scaffold` (`scaffold.py module`, `source`).

## Verified

Writers: the 34 replacing client schemas of the local workspaces (32 Freedom pages and 2 mobile
manifests - no Classic replacing page exists locally; the diff form is the same) re-serialise byte
for byte after a no-op load, and `add_string` on each keeps every old metadata line and orders the
new item last; `replace` writes their most common line order. On the fixture each writer keeps
every line outside its span and the body's CRLF. Not pushed to an environment yet.

Reader: all 269 `ClientUnitSchemaManager` schemas with a `define` in the local package folders round-trip
byte for byte; the 712 schema modules of the compiled 8.3.2 client content parse (2948 diff
operations, every one with an operation and a name; 5146 methods, each body cut at its own brace).
The moved `mask` gives the same output as before on all 832 local C# files.

## Checks

Warnings only - most names a Classic schema uses come from the platform's parent schema, which is
not in the workspace:

- a diff item without a name (on the item or in its values);
- `parentName`s declared neither in this diff nor in the workspace copies of the parent chain - one line;
- handler bindings (`click`, `change`, `prepareList`, `afterrender`, `linkclick`, `activeRowAction` ...)
  to methods defined neither here nor in those parents - one line.

```bash
python tests/test_classicui_tools.py
```
