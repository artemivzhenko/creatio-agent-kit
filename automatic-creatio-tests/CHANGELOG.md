# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`upload` through a button, `tab` on a toggle panel (S45-T08).** `upload <Button> "file"` takes the file through the chooser the button's own handler opens (`no file chooser opened by <Button>` when none does). An element whose `tab` names a `ToggleTab` now opens that panel before the line (it was skipped silently, so the line ran on a closed panel). Cases `s45-upload-tab`, `s45-upload-through-button`.
- **`select-in-dialog "A; B"` (S44-T08).** Ticks the rows of a record selection window by display value; `answer "Select"` closes it. A missing row is reported with the rows shown. `s42-links` now covers the Select path and the link rows.
- **List pages (S44-T07).** `QuickFilter` element (`crt-quick-filter`, lookup chip): `set` ticks the listed values, `check-value` reads them. A Freedom UI `DataGrid` takes `check-row`, `select-row` and `open-row` (rows addressed by cell text; a missing row is reported with the rows shown). `analyse` of a list page writes the grid with its columns and the chips. Case `s44-order-list`.

### Removed

- **The `create` command (S11-T08).** It followed a section's New button into a form; no bed has a section with a working New and `analyse` finds nothing on a Freedom UI list page, so nobody could run it. `add-record` and the `# writes` cases cover the same ground.

### Changed

- **A failed `# writes` case still runs its later `delete-record` lines and reports the cleanup (S11-T19).** `cleanup:` lines under the failure; the case stays failed.
- **A toggle that opens a panel is done when the panel is there (S11-T18).** `ToggleTab` takes `panels` (tab caption -> panel `element-name`); `set` waits for the panel, clicks once more, then fails `panel <name> did not open after 2 clicks`; the report notes a second click. Fixes the `s34-upload` flake.
- **The elements of a page are made once per page (S11-T10).** `ExecutionSession` keeps the elements a tab materialised, one per page and code, and drops them on any change of the page (`open`, `navigate`, adopt, user change, a closed page, the same page opened again). Fewer objects and locators per command; the existence wait of each command is unchanged.
- **`scripts/gate.py` (S11-T11).** One command: build, unit tests, `--validate-only`, the live run of the repository's cases on a test site (the README, "Running").

- **A command on an element of another tab opens the tab (S11-T06).** `analyse` writes `tab` for a control shown on one page tab only (read from the per-tab passes of the walk); the executor clicks that tab before the first command on its elements, and again when a later line is on another tab. Validation inserts nothing and no longer warns "lies on tab"; the `click <Tab>` line stays valid. `--verbose` logs `opened tab <code>`.

### Fixed

- **The picker icon and the dropdown's service row are read in the user's language (S11-T09).** One table (`InterfaceLanguage`: en-US, ru-RU, uk-UA) replaces the English-only `Calendar` / `Time` / `Date/Time` switch of `analyse` and the "Add new" test of the lookup; a ru-RU profile used to analyse every date control as `DateTime` with "no picker icon" and now gets `Date`, `DateTime`, `Time`. uk-UA words are not read from a live page (the test site serves no uk-UA resources); an unknown label still falls to the value rule.

- **The first-run flake of `set` on a lookup (S11-T04, S34-T03).** The autocomplete panel re-renders when the search answers; the option found in the unfiltered list (`Nth(3)`) was gone by the click, and Playwright's `TimeoutException` (not a `PlaywrightException`) escaped the option-text read and waited the full element timeout. The read now has a short timeout and treats a vanished row as empty, the pick finds the option again when its click misses (4 attempts), and the option is awaited for the element budget instead of 5 s.
- **`check X not exists` right after a change waits for the rule (S11-T13).** Within `elementTimeoutMs` of a `set` / `clear` / `click` / `answer` / `upload` line, absence is awaited for the element budget instead of `absenceTimeoutMs`; a pass returns at once.
- **`analyse` of a Classic page without an active tab no longer throws (S11-T17).** The tab walk read a property of an empty `FirstOrDefault`; it now has no active index, and the output says `tabs: none`.
- **`use` no longer launches a browser (S11-T16).** The browser context and its login are made when the first page is opened, so a backend case (`ProcessCases`) never starts Chromium. The lookup filter `<Col>/Id eq <guid>` (`ODataValues.FilterColumn`) was already in place.
- **A hidden or missing control fails the line cleanly (S11-T12).** `set` / `check-value` on a control not on the page report `'<code>' was not found on the page.`
  (a `CommandFailedException`, no stack trace); a zero-width Classic field fails at once; a Classic button is found by its `data-item-marker` first.
- **Folders are relative to `--root` (S35-T02).** `Cases`, `AnalysisFolders`, `Reports` and `TestData` were relative to the working directory, so a run started from
  another folder found no cases and passed.

### Added

- **Tabs, dialogs, waiting for a process (S34-T01..T03).** `tab new [as <name>]` / `tab <number|name>`: several browser tabs of one session, each
  with its own page, the console log marking `[tab N]`; `check dialog [not] shown|contains|matches|count`, `answer "<caption>"`, `remember dialog as $x`
  and `no-answer` on `set` (Classic stage bar) and `click`; `upload`, `snapshot`, `navigate`, `check-process`, `# dev-only` with `seed` and `fire-timer`, `wait-record` / `wait-count ... within <n> second|minute` poll the `check-record` /
  `check-count` condition (`pollIntervalMs` in `run.config.json`).
- **Tracing.** `--trace` records a Playwright trace per case (`Reports/traces/<case>-<user>.zip`); a failed case
  keeps a screenshot of the page at the failing command (`Reports/screenshots/`); every case's requests with their
  durations go to `Reports/network/<stamp>-<case>.log` and the text report names them with the error count and the
  slowest request; `check network no errors [except "<regex>"]` fails on failed or 4xx / 5xx requests.
- **Records by name.** `open <page> for <static value | $variable | id>`: an unquoted word that is none of them fails
  validation and lists the static values; `--static <name>=<value>` (repeatable) gives a static value for one run. The
  bundled cases open `UsrHiddenRecord`, `ContactRecord` ... (their ids are in `static.values.json`), no GUID is left in `Cases/`.
- **Console log per case.** Every run writes the whole browser console of each case (every message
  type, page errors, failed and 4xx / 5xx requests, timestamped, with script locations) to
  `Reports/console/<stamp>-<case>.log`; the text report names the file and `last_report` returns the
  logs of the newest run with the report. `check console no errors` and `captureConsole` are unchanged.
- **Cases that write.** `insert <object> as <alias> set ...`, `update`, `delete` and
  `delete-record <object> <filter>` (refused above 20 matches) write over OData through one client
  (`CreatioODataClient`: `BPMCSRF`, `ForceUseSession`, a refused write fails the line with Creatio's
  answer); every inserted record is deleted when the case ends unless the `insert` says `keep`, and
  a record the cleanup cannot delete fails the case. `check-record ... has <column> <op> <value>`,
  `check-count` and `check-distinct` assert what the backend did. Variables: an insert alias,
  `remember <code> as $x`, `remember-record <object> <filter> as $x`, substituted in every unquoted
  argument, `$x+N` as the value `check-value` compares with; a variable used before its line is a
  validation error. Header directives: `# writes` (stop at the first failure; an inserted alias must
  be deleted or kept) and `# ac: AC-nn` (the acceptance criterion the case proves). `--task-folder
  <dir>` (and `--task <id>`) write `<dir>/evidence/<AC>-report-N.txt` and a draft report row per
  case. `check console no errors [except "<regex>"]` fails on browser errors of the pages opened so
  far; `captureConsole` puts them in every report. `on <page>` checks the page before rebinding and
  names the elements it looked for. The MCP `run` tool takes `task_folder` and `task`.

- **Classic UI.** A page file may declare `"type": "ClassicUI"` with the page `schema`, and the same
  DSL then drives a Classic (7.x) page inside the 8.x Shell. Element types keep their names --
  `Text`, `RichText`, `Integer`, `Decimal`, `Boolean`, `Date`, `Time`, `DateTime`, `Lookup`,
  `Button`, `Tab` -- and exist once per generation; the page's type picks the class, and a
  Freedom-only type on a Classic page is refused when the configuration loads. Classic controls are
  found by the ids Creatio builds from schema, element name and control class, with `name` in the
  page file when the schema's name differs from the code (section-wizard pages name fields
  `LOOKUP<guid>`). Typed fields read the page's view model through `Ext.getCmp`, so numbers and
  dates come back invariant and ISO whatever the user's culture shows, and dates are written in the
  culture the page reports. A `Lookup` covers the drop-down and the searchable lookup; a `DateTime`
  writes its date and time controls; a `Tab` is addressed by its schema name and resolved to the
  header through `TabsCollection`; a `Button` may belong to a detail. Verified on Creatio 8.3.0,
  Ukrainian interface, against a wizard-built order page of some hundred fields.
- **Classic tabs, details and the stage bar.** `TabPanel` is the tab panel as one element whose
  value is the open tab's caption (`set Tabs "Products"`). `Detail` is a detail by its schema name:
  its value is the row count read from the grid's collection, `check X columns` compares the
  rendered captions, `check X is editable` tells a configuration grid from a plain one, and its
  buttons are `Button` elements with the `detail` option. `CasesBar` is the DCM stage bar of the
  actions dashboard: the value is the committed stage from the page's stage column, `set` clicks a
  stage or picks a sub-stage from its parent's menu, answers the confirmation the page may ask and
  waits for the save Classic performs on a stage change. The stage bar and the details wait for
  their own module to finish loading, which happens after the page's fields.
- **Classic sections.** A `#SectionModuleV2/<Section>` address is analysed like a page: the list is
  a `Detail` named after the section schema with its columns, the toolbar buttons are `Button`s, and
  `open-row` opens a record from the list with a double click. The Classic runtime now also waits
  for pages that have no fields of their own.
- **Rows.** `check-row`, `select-row`, `open-row` and `delete-row` address a row of a listing element by its
  cell values, named by column captions (`IRowed`); the Classic `Detail` offers them, and takes
  `add-record` when it edits in place: the row is filled through the editors it renders and saved
  with its own save action. A detail saves its own records, so both writes reach the database at
  once. `on <page>` rebinds the open page after Creatio navigated by itself. A Classic `Button` with
  `isSave` waits for the save to go through and reports the message box when it does not.
- **Classic analyser.** `analyse` given a `#CardModuleV2/<Schema>` address describes a Classic page:
  each control is asked, through its Ext component, which column it binds and what type the column
  is, so fields are coded by column with the schema name kept as `name`, a DateTime column's two
  controls fold into one element, details come with their columns and buttons, the tab panel and
  the stage bar with their captions. Every tab is opened in turn and the original one restored; a
  header field met on every tab is recorded once. `SaveButton` and `DiscardChangesButton` are
  always written, since a clean page never renders them. `schemas --classic` lists the Classic pages.
- **`IPageRuntime`.** The one page-level difference between the generations -- how to tell that a
  page has finished rendering -- lives behind an interface with a Freedom and a Classic
  implementation; the session picks one by the page's type, or by the address for `analyse`.
- **User aliases.** A user in `creatio.env.config.json` may carry a `Name`, and a case writes that
  after `use` instead of the login, so the bundled cases run against any environment.

- **Process cases.** A backend tier kept apart from the page cases: scripts under
  `ProcessCases/` (`ProcessCasesFolders`) start a business process over the process engine
  service (`start <process> [with Param=Value;...]`), assert its result parameters
  (`check-result <parameter> <op> <value>`, the operators and typing of `check-value`) and the
  records it left behind over OData (`check-record <object> Column=Value;... [not] exists`).
  Processes are described under `Configuration/processes/` (parameters, types, directions), so
  an unknown process, an output passed in, or a value of the wrong type fails in validation. The
  browser is now launched on first use, so a run of process cases alone never opens one: the
  bundled case runs in about a second.

- **Data grids.** New element type `DataGrid` (`crt-data-grid`), with `check <code> [not] exists` and
  `check <code> is [not] editable`. Editability and placement inside an expansion panel are two
  properties Creatio configures independently, so all four combinations occur and each is asserted
  separately. A grid has no caption of its own: its `label` is the caption of the panel holding it,
  which is also how the grid is reached — the framework opens and scrolls to that panel before it
  reads anything.
- **Column assertions.** `check <code> columns` compares the rendered column names and their
  left-to-right order with the `columns` recorded in the page file. The failure message names the
  first position that differs, because a renamed column and two swapped columns are different page
  changes that a bare pass/fail cannot tell apart. A line whose element declares no `columns` is
  rejected during validation rather than passing vacuously.
- **`add-record`.** `add-record <code> set Column=Value;Column=Value` adds a record to a grid that
  allows inline editing. The list is split on `;` and each pair on its first `=`, and quoting it is
  optional. Column names are checked against the page file during validation, so a misspelled column
  fails before a browser starts; values are entered according to what the cell renders -- a checkbox
  takes `true`/`false`, a lookup is resolved through its autocomplete, everything else is typed. The
  row reaches the database when the page is saved, the same way a value written with `set` does.
  Creatio opens most cell editors only on a double click, so a single click is tried first and the
  second spent only where it is needed; a column Creatio renders as a link or a coloured label is
  read-only in the list and is reported as such.
- **Toggle tabs.** New element type `ToggleTab` (`crt-button-toggle-group`) for the second shape
  Creatio renders tabs in. It is the opposite of a tab panel in the DOM: one `element-name` for the
  whole group, with the tabs inside named only by their captions. So the group is the element and the
  open tab is its value -- `set X "Tab 2"` switches, `check-value X eq "Tab 2"` asserts -- and no new
  command was needed. `analyse` records the captions as `tabs`, and the `type` in the page file is
  what separates the two kinds. Adds the `Tab` value kind, which copies into text and nothing else.
- `analyse` opens every collapsed expansion panel and scrolls each one into view before its final
  pass, and records the columns of each grid it finds.
- `analyse` walks the tabs of every toggle group as it already walks the tabs of a tab panel, and
  scrolls each tab from top to bottom before reading it. Creatio renders much of a page only as it
  approaches the viewport, so without this how much of a page was found depended on the size of the
  window and on which tab the page happened to open on.
- `viewportWidth` and `viewportHeight` in `run.config.json` (1600 x 950 by default) fix the size of
  the browser window, for both cases and analysis.

### Fixed

- `check <code> is not shown` no longer counts as the `is shown` line the validator wants before a
  `set` / `check-value` on a rule-toggled control; `is shown` confirms it, `is not shown` withdraws it.
  `IsShownAsync` honours its cancellation token. The `order-page-writes` example has its page file
  (`Configuration/pages/UsrOrderForm.json`), so every `.act.exp` example validates.
- `clear` refuses a read-only field up front, as `set` does, instead of waiting out the element
  timeout on an input that will never take the keystroke.
- Grid editability is read from the footer row Creatio adds for appending a record, not from the
  absence of a per-cell editing-disabled marker. That marker means one column is read-only, so an
  editable grid holding a calculated or image column was reported as not editable.
- A Save button is now considered gone when it stops showing, not only when Creatio removes it from
  the page. Some pages collapse the button instead of removing it, and there a save that plainly
  succeeded was reported as a failure.
- A toggle group no longer reports the caption of its first tab as its own name.
- Analysis no longer lets the first pass decide what the rest of the walk may find: a control met
  while hidden was marked as seen and then skipped on every later pass, even once it became visible.
  Which tab the page opened on therefore silently changed the result.
- The browser window is no longer whatever size Playwright defaults to. At 1280 x 720 Creatio's
  side-panel overlay covers the tab headers, so `click <tab>` could not be performed at all on a
  contact page.
- An option list is written to a page file only when the element type declares a member that can take
  it, so analysis can no longer record something the next run would refuse to load.
- A control with no caption of its own no longer inherits the caption of the expansion panel it sits
  in. That fallback exists for grids, and element types now declare whether it applies to them, so a
  grid's toolbar buttons are no longer all recorded under the grid's panel caption.

## [1.0.0] — 2026-09-03

First release. A complete rewrite of the original framework, sharing none of its structure.

### The language

Tests are `.act` files, one command per line, in a DSL with twelve commands: `use`, `open`, `check`,
`check-value`, `set`, `click`, `goto`, `clear`, `wait`, `create`, `end` and `analyse`. See
[docs/dsl.md](docs/dsl.md).

### How it is built

- **Two passes.** A test case is parsed and validated in full before a browser opens, so a typo costs
  milliseconds rather than minutes. Every problem in a file is reported at once, with line numbers.
- **Reflection registries.** An element type or a command is one class carrying one attribute.
  Nothing central is edited to add either — no switch, no enum, no factory.
- **Capabilities rather than types.** A command declares the interface it needs, so a new element type
  works with every command that matches it. `Tab` gained `click` and `check` support without either
  command changing.
- **Values cross layers as text.** Every format and Creatio quirk lives inside its element class, so
  the command layer contains no type switches at all.

### What it can drive

Fifteen element types: `Text`, `RichText`, `Email`, `Phone`, `Link`, `Integer`, `Decimal`, `Date`,
`Time`, `DateTime`, `Boolean`, `Lookup`, `Button`, `Tab` and `CasesBar`.

### Analysing a page

`analyse` opens a Freedom UI page and writes its configuration: every field, button, tab and stage bar
it can address, plus the controls it cannot. It opens each tab in turn, because Freedom UI keeps only
the open one in the DOM. Available as a DSL command and as a CLI subcommand.

A run has two phases: analysis scripts first, the catalog reloaded from what they wrote, then the test
cases. Analysis is off by default — once a page is described the configuration is reused.

### Finding a page

`schemas` lists the instance's Freedom UI page schemas over OData, each with the address that opens
it. Analysing a page needs its schema name, and nothing in the browser shows the list.

### Configuration

One file per page under `Configuration/pages`, each holding the page and its elements. Environment,
site, static values, objects and run settings are separate files.

### Running

A CLI with two modes, and a text, JUnit XML or HTML report. `--validate-only` lints a whole suite
without a browser.

### Known limitations

- `create` is implemented and validated but has never been executed against a live Creatio. Treat it
  as experimental.
- Verified against one instance: Creatio 8.3.2, .NET Framework, English interface.
- An element's tab is not recorded in configuration, so a control on a closed tab reports as missing
  rather than as "on another tab".
- A read-only, empty date or number control cannot have its exact type established by anyone; it is
  recorded and reported as presence-only.
