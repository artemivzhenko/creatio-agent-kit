---
description: Creatio Freedom UI pages of 8.x as package files - put a field of any column type (text, number, checkbox, date, time, date-time, lookup, rich text, phone, email, web) or a grid of another object on a form page by editing the page body's JSON sections; push installs it; the UI test utility's analyse shows what rendered.
---

# Page tools

Scripts that change a **Freedom UI page** stored in a package: add the fields of the page's
object, add a grid of another object, remove an element. Pure Python standard library.

| File | What it does |
| --- | --- |
| `pages.py` | CLI (the commands are listed under Commands) |
| [`../creatio_schemas/page/`](../creatio_schemas/README.md) | the library (`PageSchema`, `CONTROL_OF`) |
| `tests/` | `python tests/test_pages_tools.py` - round trip and build checks on real 8.2.3 pages of both body forms |

Verified on Creatio 8.2.3 (the test environment): the 17 columns of `UsrOrder` (every type below) and a grid
were placed on `UsrOrder_FormPage` with these scripts only, `clio push-pkg` installed the page,
and the UI test utility's `analyse` found all 18 controls with the expected element types
(Text, Integer, Decimal, Boolean, Date, Time, DateTime, Lookup, RichText, Phone, Email, Link,
DataGrid). Two pages read from the package render back byte-for-byte.

## A page for an object that exists

`pages.py new <package> <Page> --entity <Object> [--fields A,B] [--caption ..] [--template form|list]` writes the template page and one field per column (default: every own column of the object), validated in a scratch copy first; an existing page is refused, `--dry-run` lists the files.
`--template mini` (no `--entity`) writes a process's pre-configured page instead: parent `BaseMiniPageTemplate`, group
`MiniPage`, one label showing `--caption` (P-8.16); a `preconfiguredPage` task opens it (`ClientUnitSchemaUId`) and
completes on the template's buttons (`proc.py element ... buttons`).

## A replacing copy of a base page

`pages.py replace <package> <Page> [--env <env>] [--parent-uid <UId>] [--caption ..] [--cultures ..]` writes the four files of a
replacing copy (D64): `descriptor.json` with `Parent` = the page and `ExtendParent: true`, the diff `metadata.json` (`UId`, `A5`, `B6`,
`+ B7 true`, `HD1` = the page's UId), `properties.json` (`Page`, `AngularSchema`), the resources with the caption, and the empty body
(`viewConfigDiff: []`, `viewModelConfigDiff: []`, `modelConfigDiff: []`, `handlers: []`, every marker the parser reads). The page's UId:
`--parent-uid`, a copy in another package of the workspace, `BASE_PAGES` in `creatio_schemas/page/catalog.py`, else the site's
`SysSchema` row (`--env`). `add-grid`, `grid-caption`, `set-value` and `validate` then work on it as on an own page; `set-value` on an
element of the replaced page appends a `merge` op for it; `inspect` and `audit` say the counts cover this layer only. `add-field` needs
the object's columns in the workspace (the replaced page's object usually is not).

## A detail as the designer makes it

`add-grid <package> <Page> <Name> --entity <E> --columns .. --master <Column> --panel "Title" [--no-add-button] [--before <Element>]
[--editable]` writes the detail the 8.3.2 designer writes (read off a designer-made detail of a base page): `<P>ExpansionPanel`
(`crt.ExpansionPanel`, `title` a page string `<P>ExpansionPanel_title`) whose `tools` hold `<P>ToolsContainer` > `<P>ToolsFlexContainer`
> `<P>AddButton` (`crt.CreateRecordRequest`, the master column preset to `$Id`; left out with `--no-add-button`) and `<P>RefreshButton`
(`crt.LoadDataRequest` reload of `<Name>DS`), whose `items` hold `<P>ListContainer` > the `crt.DataGrid` (columns with `path` and a
lookup's `referenceSchemaName`, `features.editable` with `itemsCreation: false`); the data source and the collection attribute as for
any grid, and the dependency on `PDS.Id` in a root `merge` of `modelConfigDiff`. `<P>` is `<Name>` less a `List` suffix. `--before X`
puts the grid (or its panel) at X's index in X's parent: X from this body, else from the replaced page - its copies in the workspace,
else on the site (`--env`); two different places are refused with the list. The settings menu, export, import and search of the
designer's detail are not written. The writers append their operations: the body's operations keep every byte, only the items an
edit changes (`set-value`, `grid-caption`) are rendered again, and a new attribute or data source goes into a `merge` op of its own.

`pages.py grid-caption <package> <Page> <Grid> <Column> en-US=".." [uk-UA=".."]` makes one column's caption a page string:
`#ResourceString(<code>)#` in the column, the `B2` entry, the text in each culture given (`<Column>`: the code, the path or the part after
`<DS>_`). `resources.py set <package> <Page> <Key> ...` on a Freedom page writes the same form, `LocalizableStrings.<Key>.Value` with its
`B2` entry (D95: a plain key is never shown); `Caption` and dotted keys stay as they are.

## A resource string as an element value

`pages.py set-value <package> <Page> <Element> <Property> <Value> [--text "..."] [--culture en-US]` sets one property of an
element; `a.b.c` walks the path (`layoutConfig.colSpan 2`), creating the objects on the way. When the value is `#ResourceString(Key)#` the page needs two halves that the platform reads together, and the writer adds
both: the `+ MetaData.Schema.B2 {UId, A2: Key, A3/A4: the page UId, A5: the page's own A5}` entry in `metadata.json` with its UId at the
front of the `~ MetaData.Schema.B2 [...]` order line, and `LocalizableStrings.Key.Value` in `--culture` (default en-US). The page's other
cultures get no key, so `resources.py missing` lists them. A new key without `--text` is refused; a key the page already owns changes nothing.

`validate` ends with two JS lines - `js syntax:` (`node --check`, or `node not found: JS syntax not checked`) and `js load:` (a stub `define()` load with the counts of `viewConfigDiff`, attributes, data sources, handlers). It reports the two half-written states: a `#ResourceString(Key)#` that has a string but no `B2` entry (the page would show the
key), and one with a `B2` entry but no string. A reference with neither is left alone: grid-column captions and the parent page's
strings use the same syntax and need no entry of the page's own.

## A detail grid as the designer writes it

`add-grid ... --master <Column>` adds the designer's detail filter to `modelConfigDiff` (`dependencies: {<Grid>DS: [{attributePath: <Column>,
relationPath: PDS.Id}]}`); without it the command warns `no --master: the grid lists every row of <Entity>`. `--add-button` inserts a
`<Grid>AddButton` (`crt.Button`, caption a resource string) above the grid whose click is `crt.CreateRecordRequest` for `<Entity>_FormPage`
(or `--page`), with the master column preset to `$Id`. Column captions are resource strings `#ResourceString(<Grid>DS_<Column>)#` with their
B2 entries (clio `validate-page` refuses literal captions); `--literal-captions` keeps plain text for a probe. `set-value` turns `true` / `false`
into JSON booleans and digits into numbers.

## A grid container over every layer

`pages.py layout <package> <Page> --container <Name> [--env <env>]` folds the `viewConfigDiff` of every copy of the page (its parent
chain first) in the order the platform applies them - insert, merge, move, remove, the last layer wins - and prints the container's
grid by `layoutConfig` (row and column from 1; the column count is the container's `columns`): one line per row with the element in
each column range, `free` where nothing is, then one line per element with the layer that placed it last. The package only names
the workspace; with `--env` the copies only on the site (a base page with nine copies, `Custom`) are read from the site, one body each.

## Audit

`pages.py audit <package> <Page> [--all]` (MCP `page_audit`) prints one line per finding and ends with
`<Page>: <n> finding(s)`; exit code 1 when any line was printed. The thresholds are one dict, `THRESHOLDS` in
`creatio_schemas/page/audit.py`.

| Line | Printed when |
| --- | --- |
| `elements <n> on tab <Tab>` | over 80 elements under one `crt.TabContainer` (nearest tab ancestor) |
| `grid <Name> (<Entity>): no master filter` | a detail grid (data source not the page's own) whose attribute or data source has no `filter` / `PredefinedFilter` / `filterAttributes`, and its data source is not under `dependencies` of a `modelConfigDiff` merge |
| `attribute <Name>: path <P> (<k> joins)` | 3 joins or more (segments between the data source and the column); `attributes through 2+ joins: <n>` follows |
| `comboboxes <n>` | over 25 |
| `page rules <n> (<d> disabled)` | over 20, or any disabled (the page's `*BusinessRule` addon in the workspace) |
| `object rules <n> (<d> disabled, <f> filter rules, <dup> duplicates)` | over 20, or any disabled or duplicated |
| `object columns <n> (workspace layers)` | over 100 - counts what the workspace holds (the base columns of the platform are not read) |
| `handlers <n>, <bytes> bytes; setTimeout/setInterval <t>` | any timer |

`--all` prints every count and exits 0.

## Commands

<!-- commands:start -->
```
python pages.py new       <package> <Page> --entity UsrOrder [--fields UsrName,UsrAmount] [--caption "Order form"] [--template form|list|mini]
                          [--cultures en-US,ru-RU] [--dry-run]
python pages.py inspect   <package> <Page>
python pages.py layout    <package> <Page> --container <Name> [--env <env>]
python pages.py add-field <package> <Page> <Column> [--parent SideAreaProfileContainer] [--row N] [--col N] [--span N]
python pages.py replace   <package> <Page> [--env <env>] [--parent-uid <UId>] [--caption ..] [--cultures en-US,uk-UA]
python pages.py add-grid  <package> <Page> <Name> --entity UsrOrder --columns UsrName,UsrAmount [--parent GeneralInfoTabContainer] [--rows 6] [--editable]
                          [--master UsrOrder] [--add-button] [--page UsrOrderItem_FormPage] [--literal-captions]
                          [--panel "Items" [--no-add-button]] [--before <Element>] [--env <env>]
python pages.py grid-caption <package> <Page> <Grid> <Column> en-US="Amount" [uk-UA=".."]
python pages.py set-value <package> <Page> <Element> <Property|a.b.c> <Value> [--text "Caption"] [--culture en-US]
python pages.py remove    <package> <Page> <Element>
python pages.py validate  <package> <Page>
python pages.py audit     <package> <Page> [--all]
python pages.py from-schema <package> <Page> [--name UsrOrderForm] [--out Configuration/pages/UsrOrderForm.json] [--compare <page file>] [--culture en-US]
```

| command | what it does |
| --- | --- |
| `new` | a form or list page for an object that exists; a process's mini page |
| `replace` | a replacing copy of a base Freedom page: descriptor, diff metadata, properties, resources, empty body |
| `layout` | a grid container over every layer (site copies with --env): the element in each cell, free cells |
| `inspect` | elements, attributes, data sources and problems |
| `validate` | problems; exit code 1 on errors or a JavaScript syntax error |
| `add-field` | a field bound to a column of the page's object |
| `add-grid` | a grid listing another object's records |
| `grid-caption` | a grid column's caption as a page string, in each culture given |
| `set-value` | one property of an element; a #ResourceString(Key)# value gets its B2 entry and string |
| `remove` | drop an element with its attribute and data source |
| `audit` | what makes the page slow: counts over thresholds; exit code 1 on any finding |
| `from-schema` | the UI test utility's page file, from the page schema |
<!-- commands:end -->

## The loop

```bash
python pages.py inspect   UsrPkg UsrOrder_FormPage
python pages.py add-field UsrPkg UsrOrder_FormPage UsrAmount --dry-run          # the diff, nothing written
python pages.py add-field UsrPkg UsrOrder_FormPage UsrAmount                    # profile column, next free row
python pages.py add-field UsrPkg UsrOrder_FormPage UsrNotes --parent GeneralInfoTabContainer
python pages.py add-grid  UsrPkg UsrOrder_FormPage UsrItems --entity UsrOrderItem --columns UsrName,UsrQty
clio execute-sql-script -e dev -s 'update "SysSchema" set "IsChanged"=false'   # or the push skips the page
clio push-pkg UsrPkg -e dev
creatio-tests analyse "/0/Shell/#Card/UsrOrder_FormPage/edit/<id>" --name UsrOrderForm --list
```

`<package>` is the package folder (`packages/UsrPkg` in a clio workspace); the page's object
and the grid's object are read from the workspace, so an unknown column is refused before
anything is written.

## What a field is

One `insert` in `viewConfigDiff` (`type`, `label: "$Resources.Strings.<Column>"`, `control:
"$<Column>"`, `labelPosition: "auto"`, `layoutConfig`) and one attribute `<Column>:
{modelConfig: {path: "PDS.<Column>"}}` - exactly the designer's output. The control follows the
column type (`CONTROL_OF`):

| Column type | Control | Extra |
| --- | --- | --- |
| ShortText, MediumText, LongText, MaxSizeText | `crt.Input` | |
| Integer, Float*, Money | `crt.NumberInput` | |
| Boolean | `crt.Checkbox` | |
| Date / DateTime / Time | `crt.DateTimePicker` | `pickerType` date / datetime / time |
| Lookup | `crt.ComboBox` | |
| RichText | `crt.RichTextEditor` | |
| PhoneText / EmailText / WebText | `crt.PhoneInput` / `crt.EmailInput` / `crt.WebInput` | |

Field captions come from the column captions: **no resource strings are written**, the page's
resources keep only its own `Caption`.

A grid is an `insert` of `crt.DataGrid` plus a collection attribute (`isCollection`, the
`<Name>DS_<Column>` sub-attributes) and a `crt.EntityDataSource` of scope `viewElement`; the
grid is unfiltered (every record of the object). Column captions are read from the object's
resources.

## Two body forms (verified)

A page the designer saved has `viewModelConfig` and `modelConfig` objects; a page clio
created from a template has `viewModelConfigDiff` and `modelConfigDiff` arrays of `merge`
operations (`path: ["attributes"]`, `path: ["dataSources"]`). The tools write into whichever
the page has and keep its indentation (tabs for the designer, two spaces for clio). Handlers
and anything else outside the JSON sections are kept as text.

## The page file of the UI test utility

`from-schema` writes `Configuration/pages/<name>.json` of `automatic-creatio-tests` from the page
schema - no browser, no record, no environment. Describe a page from the package first; run
`analyse` when the page is not in a package or its parent's elements matter. The labels are read in the package's primary culture (the index's,
S31-T01) - the language the browser shows - or in `--culture <c>`; `# label unknown` stays only for an element the culture has no string for.

```bash
python pages.py from-schema UsrPkg UsrOrder_FormPage --out <testFramework>/Configuration/pages/UsrOrderForm.json
python pages.py from-schema UsrPkg UsrOrder_FormPage --compare <testFramework>/Configuration/pages/UsrOrderForm.json
python pages.py from-schema UsrPkg UsrOrder_FormPage --culture en-US --out ...   # the browser's language is not the package's
```

- `"conditional": true` marks an element a business rule of the page (`<Page>BusinessRule`) shows or hides with a
  `show` / `hide` action: Freedom UI drops a hidden control from the DOM, so a case asserts it with
  `check X is [not] shown`, and the validator warns on `exists` for it. An element the page itself hides
  (`visible: false`) is still written when a rule shows it. `analyse` keeps the key; `--compare` ignores it.
- `code` is the element's `name`: the utility addresses an element by `element-name`, which is that
  name (all 11 own controls of the designer-made test page, and all 18 of the tool-made order page,
  matched what `analyse` wrote).
- `type` from the component (`creatio_schemas/page/catalog.py`): `crt.Input` Text, `crt.NumberInput`
  Integer for an Integer column else Decimal, `crt.DateTimePicker` by `pickerType` (date, time,
  datetime; else the column's type), `crt.Checkbox` Boolean, `crt.ComboBox` Lookup, `crt.RichTextEditor`,
  `crt.EmailInput`, `crt.PhoneInput`, `crt.WebInput` Link, `crt.Button`, `crt.TabContainer` Tab,
  `crt.DataGrid` with its column captions, `crt.EntityStageProgressBar` CasesBar,
  `crt.ButtonToggleGroup` ToggleTab. Containers, labels, widgets, menus are listed at the end as
  `# not written (<type>): ...`.
- `label` as the page shows it: a literal; `#ResourceString(X)#` = the page string
  `LocalizableStrings.X.Value`; `$Resources.Strings.X` = that string, else the caption of the column
  the attribute `X` (or `<DataSource>_<Column>`) reads. A caption the workspace cannot resolve (a
  platform object's column) is written empty and named in `# label unknown`: fix it by hand or with
  `analyse` - `check <code> exists` compares it.
- A page's own schema does not list its template's elements. For `PageWithTabsFreedomTemplate` the
  ones `analyse` found are added (`CloseButton`, `BackButton`, `SetRecordRightsButton`,
  `AttachmentAddButton`, `AttachmentRefreshButton`, `GeneralInfoTab`, `CardButtonToggleGroup`),
  minus those the page removes or hides; for any other parent the output says the parent's elements
  are unknown. Elements the page hides with `visible: false` are left out and named; elements a
  business rule hides are written (they exist on some records).
- The file is written as `analyse` writes it (two spaces, LF, elements by type then code): for
  both test pages the output is byte-identical to `analyse`'s file (`tests/fixtures/expected/`).
  `--compare` lists elements only in the schema, only in the file, and type, label, column and tab
  differences; exit code 1 when there are any.

Read from all 244 local Freedom UI pages without an error: 2451 elements written, 593 labels left
empty for an object outside the workspace, 87 elements hidden by their page.

## Traps

- **A page saved in the designer is "modified locally"** and `push-pkg` skips it with a
  warning while reporting success. Clear `SysSchema.IsChanged` (and `IsLocked`) before the
  push - see the clio-packages skill.
- The containers a field can go into are in the template, not in the page file:
  `SideAreaProfileContainer` (the profile column) and `GeneralInfoTabContainer` (the first
  tab) for `PageWithTabsFreedomTemplate`; `clio get-page` writes the merged bundle when
  another one is needed.
- Rows are not checked against the parent's grid: a field placed on a row another element
  spans is simply rendered after it.

## Not covered

Tab containers and new containers (an expansion panel only as `add-grid --panel`); moving or resizing an element; the
list page's columns (`PageSchema.create(..., "list")` writes the empty list page clio's `create-page`
writes; `PageSchema.create(..., "form")` the empty form page - both byte for byte, used by
`tools/scaffold`); handlers.
