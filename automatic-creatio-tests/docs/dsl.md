# DSL Reference

## Syntax

Write one command per line. Blank lines and lines beginning with `#` are ignored. Double quotes preserve spaces and make a literal value; unquoted values may name static values or elements where the command permits them. The first command must be `use <user>`.

Copy the `.act.exp` examples under `Cases/` and `ProcessCases/` to `.act` files to adapt them.

## Commands

| Command | Syntax | Target | Example |
| --- | --- | --- | --- |
| use | `use <user>` (a browser opens at the first page, never for a backend case) | none | `use testUser` |
| open | `open <page> [for <record>]` \| `open process-task <process> on <page>` | none | `open ContactForm for ContactRecord` |
| check | `check <code> [not] exists` \| `check <code> is [not] required\|readonly\|editable\|shown` \| `check <code> columns` \| `check console\|network no errors [except "<regex>"]` \| `check dialog [not] shown\|contains "<text>"\|matches "<regex>"\|count <op> <n>` | `IExistable`; `required`/`readonly` need `IStateAware`, `editable` needs `IEditableAware`, `shown` needs `IVisibilityAware`, `columns` needs `IColumned`; `console` none | `check Input_Text is required` |
| check-value | `check-value <code> eq|ne|gt|ge|lt|le|contains|startswith|endswith <value>` | `IValueElement` | `check-value Input_Text eq "Sample Name 123"` |
| set | `set <code> "value" | set <code> <sourceCodeOrStaticValue>` | `IValueElement` | `set Input_Text DefInput` |
| click | `click <code>` | `IClickable` | `click SaveButton` |
| goto | `goto <code>` | `INavigableToRecord` | `goto ComboBox_Account` |
| clear | `clear <code>` | `IClearable` | `clear ComboBox_Contact` |
| wait | `wait <number> second|minute` | none | `wait 2 second` |
| end | `end` | none | `end` |
| analyse | `analyse ["<page path>"] [<pageName>]` | none | `analyse "/0/Shell/#Card/Contacts_FormPage/edit/<id>" ContactForm` |
| analyse | `analyse ["<page path>"] [<pageName>]` | none | `analyse "/0/Shell/#Card/Contacts_FormPage/edit/{id}" ContactForm` |
| add-record | `add-record <code> set Column=Value;Column=Value` | `IRecordAddable` | `add-record AddressList set Address type=Business;Full address=Main st. 1` |
| start | `start <process> [with Param=Value;Param=Value]` | none (a configured process) | `start UsrOrder_Process with Amount=10` |
| check-result | `check-result <parameter> eq|ne|gt|ge|lt|le|contains|startswith|endswith <value>` \| `check-result <parameter> exists` | none (an output of the last started process) | `check-result Verdict eq "big"` |
| check-record | `check-record <object> Column=Value;Column=Value [not] exists` \| `check-record <object> <filter> has <column> <op> <value>` | none (read over OData) | `check-record UsrOrder UsrName=Order 1 exists` |
| insert | `insert <object> as <alias> [keep] set Column=Value;... [expect error "<text>"]` | none (OData) | `insert UsrOrder as Order set UsrName=Bed;UsrAmount=500` |
| update | `update <object> $alias\|<guid> set Column=Value;... [expect error "<text>"]` | none (OData) | `update UsrOrder $Order set UsrAmount=5000` |
| delete | `delete <object> $alias\|<guid>` | none (OData) | `delete UsrOrder $Order` |
| delete-record | `delete-record <object> Column=Value;...` | none (OData, at most 20 records) | `delete-record UsrOrderLog UsrOrder/Id=$Order` |
| remember | `remember <code> as $name` \| `remember dialog as $name` | `IValueElement` | `remember UsrNumber as $first` |
| remember-record | `remember-record <object> Column=Value;... as $name` | none (OData, exactly one record) | `remember-record UsrOrder UsrName=Bed as $order` |
| check-count | `check-count <object> Column=Value;... eq\|ne\|gt\|ge\|lt\|le <number>\|$name` | none (OData) | `check-count UsrOrderLog UsrOrder/Id=$Order eq 1` |
| check-distinct | `check-distinct <object> <column> where Column=Value;...` | none (OData) | `check-distinct UsrOrder UsrNumber where UsrName=Bed` |
| check-row | `check-row <code> Column=Value;Column=Value [not] exists` | `IRowed` | `check-row Products Product=Pump;Quantity=2 exists` |
| select-row | `select-row <code> Column=Value;Column=Value` | `IRowed` | `select-row Products Product=Pump` |
| open-row | `open-row <code> Column=Value;Column=Value` | `IRowed` | `open-row Orders Name=14004` then `on OrderClassic` |
| delete-row | `delete-row <code> Column=Value;Column=Value` | `IRowed` | `delete-row Products Product=Pump` |
| on | `on <page>` | none (a configured page) | `on ProductClassic` |
| tab | `tab new [as <name>]` \| `tab <number\|name>` | none | `tab new as second` then `open UsrOrderPage for $B` |
| answer | `answer "<button caption>"` | none (the visible dialog) | `answer "Don't save"` |
| select-in-dialog | `select-in-dialog "<value>; <value>"` | none (the visible record selection window) | `select-in-dialog "Supervisor"` then `answer "Select"` |
| upload | `upload <code> "<path under TestData>"` | `IUploadable` (`FileUpload`) | `upload AttachmentList "requisites-ok.xlsx"` |
| snapshot | `snapshot "<name>"` | none | `snapshot "after-stage-menu"` |
| navigate | `navigate <page> [for <record>]` | none (a configured page) | `navigate UsrOrderPage for $B` |
| wait-record | `wait-record <object> <filter> [not] exists` \| `wait-record <object> <filter> has <column> <op> <value>`, each `within <n> second\|minute` | none (OData, polled) | `wait-record UsrOrder Id=$B has UsrStatus eq Done within 30 second` |
| wait-count | `wait-count <object> Column=Value;... eq\|ne\|gt\|ge\|lt\|le <number>\|$name within <n> second\|minute` | none (OData, polled) | `wait-count UsrQueue Order/Id=$B ge 2 within 60 second` |
| check-process | `check-process <process> [for $record] started \| running \| step "<caption>" completed\|running [within <n> second\|minute]` | none (OData, the process log) | `check-process UsrOrder_Process for $B step "Status" completed within 2 minute` |
| seed | `seed <object> $alias\|<guid> set Column=Value;...` | none (dev-only, SQL through clio) | `seed UsrOrder $A set UsrStatus=0042909f-...` |
| fire-timer | `fire-timer <process> [for $record]` | none (dev-only, SQL through clio) | `fire-timer UsrOrder_Process for $B` |

### Dev-only cases: `seed`, `fire-timer`

Two commands change a site behind its business logic, so a case needs two statements of intent to use them: the header `# dev-only` in the case, and `"AllowDevOnly": true` in
`creatio.env.config.json` of the environment (with `"ClioEnvironment": "<clio name>"`, the environment the SQL runs through; the SQL goes through `clio execute-sql-script`, never
a direct database connection). A case with the header on an environment without the flag fails validation, before anything runs, so it cannot run on a test or production site; the
two commands without the header are validation errors too.

```
# dev-only
use Supervisor
insert UsrOrder as A set UsrName=Bed;UsrAmount=10
seed UsrOrder $A set UsrStatus=0042909f-aaaa-4bbb-8ccc-ddddeeeeffff;UsrAmount=77     # a direct update: no events, no listeners, no validators
start UsrTimerProbe_Process
fire-timer UsrTimerProbe_Process                                                      # the pending timer of this case's run fires in 20 s
check-process UsrTimerProbe_Process step "Wait a day" completed within 2 minute
```

`seed` is `update` without the business logic: a GUID value goes to the lookup column (`UsrStatus` -> `UsrStatusId`), `true` / `false` / `null` / numbers are literals, anything else a quoted string; names are validated
as identifiers. `fire-timer <process> [for $record]` takes the pending timer (`qrtz_triggers`) of the process's runs that started in this case and sets its `next_fire_time` to now + 20 s (the statement of the MCP `fire_timer`:
`update qrtz_triggers set next_fire_time = <ticks> where trigger_name = ... and job_group = <timer element id>`); none or several timers is an error naming them, and nothing is written. `for $record` is read like
`check-process`'s: it does not narrow the lookup (a run is linked by time). The text report carries one line per action: `dev-only: line 7: data prepared behind the business logic: seed ...`.

### Checking a process the case did not start

`start` / `check-result` see only the process the case started. A process a signal or a timer started (a status change, a record insert) is read from the site's process
log over OData instead:

```
update UsrOrder $B set UsrStatus=Done
check-process UsrOrder_Process for $B started within 30 second
check-process UsrOrder_Process for $B step "Status" completed within 2 minute
check-process UsrOrder_Process running            # waits on a timer, not finished
```

`started` needs a run of the process, `running` a run with no `CompleteDate`, `step "<caption>" completed|running` an element of such a run with that caption (case-blind) that has,
or has not, completed (`SysProcessElementLog`). The runs counted are those that started after the line before the last action began: the platform links a run to a record only in
binary process data, so the start time is the link, and `for $record` is accepted to say which record the check is about but does not narrow the query. Consecutive `check-process` lines
look back from the same moment; the run the case's last `start` of the same process began is counted too, whenever it began (S45-T09). `within` polls like `wait-record`; without it the check reads once. A site whose process log is empty fails with `process logging is off for <process>`,
never with "step not found"; a missing step lists the steps the runs did have.

### Waiting for a process

An asynchronous process changes a record a second or twenty after the click; `wait 25 second` then `check-record` is slow when
the process is fast and flaky when it is slow. `wait-record` and `wait-count` are the `check-record` and `check-count` lines (same filter,
same operators, `$name` values, the `has` form, `exists` and `not exists`) followed by a required `within <n> second|minute`:

```
click CloseButton
wait-record UsrOrder Id=$B has UsrStatus eq Done within 30 second
wait-count UsrQueue Order/Id=$B ge 2 within 60 second
```

The condition is read over OData every second (every two seconds after the first ten; `pollIntervalMs` in `run.config.json`), and the line
passes at the first read that holds; the last read is taken at the end of the budget. On failure the message says how long it waited,
how many reads it took and what the last read showed (`gave up after 3 s (4 read(s), 3 s allowed): 'UsrOrder' where ... has UsrStatus = "Draft",
which is not eq "Done".`). Only a false condition is read again: an error of the read itself (a wrong column, the service down) fails at once.
The budget is not the case's step timeout: a wait of a minute is a minute of the run. Validation reports a missing or malformed `within`
and every error of the check line, naming `wait-record` / `wait-count`.

### A process's pre-configured page: `open process-task`

A pre-configured page (a Freedom UI page a running process task shows, a mini page over the current one) has no address of
its own: the application opens it from the task's element id. `open process-task <process> on <page>` does the same: it takes
the newest waiting element of the newest running run of the process that started since the case began (`SysProcessLog`,
`SysProcessElementLog` over OData; it waits up to `pageCheckTimeoutMs` for one), asks the application to open it
(`crt.OpenProcessPageRequest`, the request the communication panel's task list sends), over the page open in the tab or over
the Shell when none is, and binds the configured `<page>` (as `on` does), so `set` / `click` / `check` work on it. The page
file is written from the page schema (`pages.py from-schema <package> <Page>`; the template's `SaveButton` and `CancelButton`
are the buttons the process element completes on; `analyse` cannot reach the page, it takes an address). No run waiting fails
with `no running task of <process> ...`. The run the case started itself is counted by `check-process` whenever it began, so the
check after the button sees it.

```
start UsrS45T09_Process
open process-task UsrS45T09_Process on UsrS45T09Page
click SaveButton
check-process UsrS45T09_Process step "Add order" completed within 20 second
```

### Navigating inside the application: `navigate`

`navigate <page> [for <record>]` is `open` for a user who is already in the application: it sets `location.hash` of the page open in the current tab to the
page's Shell address, so the application moves itself and the card it leaves goes the way it goes when a person clicks (it stops listening, its `destroy` runs);
`open` loads the URL, which ends the old card differently and, in Classic, reloads everything. A page must be open in the tab first (a new `tab new` has none), and
the page's address must be a Shell `#` address, else use `open`. A marker set on `window` before the change proves there was no reload; if it is lost the run logs
a warning. Later lines resolve codes against the new page, as after `open`. The Classic `goto` of a lookup is unchanged.

```
open UsrOrderPage for $A
navigate UsrOrderSection
navigate UsrOrderPage for $B           # the first card was left by navigation, not destroyed by a load
```

### Looking at the screen: `snapshot`

`snapshot "after-stage-menu"` writes `Reports/snapshots/<case>-<name>.json`: the open menus with their items, the visible dialogs with their text and
buttons, the masks that block clicks, the current stage, the tabs of the page with the active one, the URL and the number of the browser tab. It checks nothing
and never changes the result of the case. It is the reconnaissance step before a case is written: put it where the screen is in doubt, run the case, read the file
(instead of a private browser probe).

### Uploading a file

`upload <code> "<path>"` puts a file of `TestData/` (`testDataDirectory` in `run.config.json`) into an element of type `FileUpload`: the element's own
`input[type=file]` when it has one, otherwise a click on its trigger button answered with the file chooser it opens (`trigger` in the page file names the
button's `element-name`; the Freedom attachments list has its `AttachmentAddButton` beside it). The path is relative; a path that leaves `TestData/`, an absolute
path and a file that is not there are validation errors, before a browser opens. `upload <Button> "<path>"` on a plain `Button` whose own handler opens a file chooser (no file list on the page) clicks it inside the chooser event, sets the file and waits for the page to go idle; the report says `upload through the button's file chooser`, and a button that opens no chooser within the element timeout fails with `no file chooser opened by <Button>`. An element whose `tab` names a `ToggleTab` has that group set to the caption whose `panels` entry is the element before the line runs (a group with no such entry fails the line). After it, `check dialog` / `answer` read what the page said:

```
set CardButtonToggleGroup "Attachments"
upload AttachmentList "requisites-broken.xlsx"
check dialog contains "HeaderException"
```

### Dialogs

A confirmation, a validation message and an error window are modal dialogs the element lines never see. `check dialog` and `answer`
read and press the visible one, in both generations (Classic's message box, Freedom UI's Material dialog); no element has to be
configured, `dialog` is a word of the language, not a code.

```
click BackButton no-answer                 # the page asks "save the changes?"; the case answers
check dialog shown
check dialog count eq 1                    # one window, not two
check dialog contains "unsaved changes"    # case-blind; "matches" takes a regex over the whole text
remember dialog as $text                   # the text of the dialog (the last one when several are open)
answer "cancel"                            # a button by its caption, case-blind (Classic shows captions upper-cased)
check dialog not shown
```

`check dialog [not] shown | contains "<text>" | matches "<regex>" | count eq|ne|gt|ge|lt|le <n>` waits up to the element
timeout for the condition, then fails with the number of dialogs the page shows, their text and their buttons. A `count`
that must stay small (`eq`, `le`, `lt`) is confirmed again after half a second, so the second of two windows is caught.
`answer` waits for the dialog and the button; an unknown caption fails naming the buttons that are there. Only the visible
dialogs count, and one nested in another counts once.

`set <stage bar> "<stage>" no-answer` (Classic) clicks the stage and leaves the confirmation open, without waiting for the save
and without reading the stage column; without `no-answer` the stage bar answers its confirmation itself, as before. `click <code>
no-answer` is accepted for the same reading of the line: a click never answers a dialog, so the word changes nothing at run time.

`click <Button> expect error "<text>"` (Freedom UI buttons) is the UI twin of `insert ... expect error`: the click runs without the `isSave` wait and the pass is a refusal that shows the text (case-blind) in a message under a control, the error toast or a dialog; a save that went through or another text fails the line with `expected the refusal "<text>", the page showed: <what it showed>`. The text is required.
`no-answer` on any other element of `set` is a validation error.

### List pages (Freedom UI sections)

A section's list page (`#Section/<Object>_ListPage`) analyses like a form: `analyse "/0/Shell/#Section/UsrOrder_ListPage" UsrOrderList` writes its buttons (`AddButton`, the custom ones), the grid (`DataGrid`, with the columns it shows) and each lookup quick filter chip (`QuickFilter`); the search box, the folder tree, the summaries strip and the page title have no element type and are listed as such. Two things to know: a grid with no columns configured renders "No columns added" and has no rows to check, and a `New` button opens the form only when the object has a page to open (the button carries `entityName` / `entityPageName`, or the object's related-page binding names one).

- `set QuickFilterByContact "Supervisor"` opens the chip, ticks exactly the listed values (several with `;`: `"A; B"`) and unticks the rest, closes it and waits for the page to go idle; a value the chip does not list fails the step with the first 20 it shows. `check-value QuickFilterByContact eq "Supervisor"` reads the ticked ones.
- `check-row DataTable Name=A exists` / `not exists`, `select-row` and `open-row` address a grid row by the rendered text of its cells (Column=Value). A row that is not there is reported with the rows the grid showed (the first 20). `delete-row` is not supported on a Freedom UI grid: delete the record over OData (`delete`, `delete-record`).
- `click AddButton`, then `on UsrOrderForm`, is the way to the add form; there is no `create` command.

`select-in-dialog "A; B"` ticks the rows of a record selection window (the grid a `crt.OpenSelectionWindowRequest` opens) whose display value equals each text, case-blind; the window's own buttons are then pressed with `answer "Select"` and `check dialog not shown` reads that it closed. The checkbox of a row exists while the row is hovered, so the line hovers it first; it waits until the window's rows stop changing. A value that is not a row fails the step with the rows the window showed (the first 20): `the window has no row "X". It shows {1 | A}; {2 | B}.` With no window it fails with `no dialog is shown`. See the case `s42-links` (open the window, tick, Select, `wait-count` of the link rows, save).

### Browser tabs

`tab new` opens a blank tab in the same browser context (cookies and session shared) and makes it the current one; `open`
then loads a page into it. `tab 1` / `tab second` switch back (numbers count from 1, a name comes from `tab new as <name>`).
Every tab stays open until the case ends, so a card in tab 1 keeps its subscriptions while tab 2 changes the same record:

```
use Supervisor
open UsrOrderPage for $A
tab new as second
open UsrOrderPage for $B
set Stage "Done"
tab 1
check-record UsrOrder Id=$A has UsrStatus eq <Draft>
```

`open` and `navigate` work in the current tab only; the other tabs are left as they are. Each tab remembers its own page, so
element codes resolve against the page of the tab the script is in. A tab number or name that no earlier `tab new` made, a
name used twice, a name that is a number or `new`, and `tab new` before any page is open are validation errors. The console
log in `Reports/console` marks every line with `[tab N]` once the case has more than one tab, so the second tab's
`pageerror` is visible. `use <other user>` closes every tab (a context belongs to one user).

`for` takes a static value name (the record id lives in `static.values.json` or comes with `--static ContactRecord=<id>`),
a `$variable`, or a literal id (a quoted string, or an unquoted GUID: `open ContactForm for c4ed336c-3e9b-40fe-8b82-5632476472b4`,
the one literal example kept here; the bundled cases use names). An unquoted word that is none of them fails validation and
lists the known static values. `--static name=value` (repeatable) adds or replaces a static value for one run, for the id of
a record a fixture call created seconds ago.

`check <code> exists` also verifies that the rendered caption matches the `label` in the page file under `Configuration/pages`; required and readonly are never asserted implicitly, they are separate lines.

`check <code> is shown` / `is not shown` waits up to the element timeout for a business rule's effect: the
control present and laid out, or absent / `display:none`. A control a rule hides is absent from the Freedom UI
DOM, so no analysis of one record sees it; its entry in the page file carries `"conditional": true` (written by
`pages.py from-schema`, or by hand; `analyse` keeps it). The validator warns on `exists` / `not exists` for such
an entry, and on `set` / `check-value` before an `is shown` line for it on the same page. The code must be in the
page file: an unknown code is a validation error naming `pages.py from-schema <package> <page>` and
`analyse --include-hidden`, never a runtime lookup (a case is validated completely before a browser opens).
Both generations answer from the control's root element with Playwright's visibility rule: a control a Freedom
rule drops is "not shown" (measured). A Classic control hidden with `display:none` would read "not shown", one
moved off-screen (`x-hide-offsets`) would still read "shown"; neither was measured on a Classic bed yet.
`check X not exists` has the short `absenceTimeoutMs` budget, except within `elementTimeoutMs` after a line that changed the page (`set`, `clear`, `click`,
`answer`, `upload`): the rule that hides X runs a moment later, so absence is awaited for the full element budget (a pass still returns at once). No `wait` is needed between the change and the check.

`check <code> columns` compares the columns the element renders -- names and left-to-right order --
with the `columns` listed for it in its page file. The expectation lives in configuration rather than
in the script for the same reason a caption does: a column list is a property of the page, so a
renamed column is one edit to the page file instead of one edit per case that touches the grid. A
line whose element declares no `columns` is rejected during validation, before a browser is started:
with nothing to compare against it could never fail.

`add-record <code> set Column=Value;Column=Value` adds one record to an element that accepts one in
place. The list is split on `;`, then each pair on its first `=`, so a value may itself contain an
`=`; whitespace around names and values is dropped. Quoting the list is optional -- the tokens are
joined back together -- so both of these are the same line:

```
add-record ContactList set Full name=Jon Doe;Job title=Developer
add-record ContactList set "Full name=Jon Doe;Job title=Developer"
```

Every column named is checked against the `columns` in the page file during validation, so a
misspelled column fails before a browser is started. Values are entered the way the cell asks for
them: a checkbox column takes `true` or `false`, a lookup column takes the text of an offered option
and is resolved through its autocomplete, and everything else is typed in.

Not every column of an editable grid can be filled. Creatio renders some of them as links or coloured
labels, and those stay read-only in the list whatever the grid's own setting is; naming one fails with
`did not open for editing`. Of the rest, only the first column and checkbox columns open on a single
click -- the others need a double click, which the framework does for you.

The record is entered in place and reaches the database when the page is saved, exactly as a value
written with `set` does -- `add-record` saves nothing on its own. Note that Creatio replaces a page's
Close button with Save and Cancel as soon as the page has unsaved changes, so those two buttons are
only addressable after something has changed.

`check-row`, `select-row`, `open-row` and `delete-row` address one row of an element that lists
records by the values in its cells, named by the column captions as `check-record` names them for
OData. Nothing is ever addressed by position. `check-row` asserts presence, `select-row` clicks the
row, `open-row` opens its record with a double click (the script then says `on <page>`), and
`delete-row` deletes it through the element's own delete action and answers the confirmation;
columns are checked against the element's `columns` during validation when the page file declares
them. Today the Classic `Detail` offers rows.

`on <page>` says which configured page the browser is on after Creatio navigated by itself, after a
button that opened another record or a link that was followed. Nothing is navigated: the open page
is rebound, waited for, and the lines below resolve their codes against that page.

`analyse` describes a page and writes `Configuration/pages/<pageName>.json`: every field, button,
tab and stage bar it can address, plus a list of controls that have no element type yet. Given an
address it navigates there itself, so the page does not have to be configured first; given no
argument it describes the page `open` left on screen.

Analysis and testing belong in separate scripts, in separate folders. A script is validated in full
before any of it runs, so elements `analyse` discovers are not addressable on the line below it --
but they are addressable by the test cases, because the run has two phases. See "Analysis phase"
below. The same work is available without a script as `creatio-tests analyse "<path>"`; its output has a `tabs:` line (`none` for a page without a tab panel, which analyses like any other). In Git Bash a `/0/Shell/...` argument is rewritten to `C:/Program Files/Git/0/Shell/...` (0 controls, no error): set `MSYS_NO_PATHCONV=1` for the command.

`end` logs readable values from the current page without changing the outcome. `analyse` describes a live page and writes its page configuration; it can also be run as the CLI subcommand `analyse`.

## Backend cases

The backend tier: cases with no page. Two kinds share it - a process case (below) starts business
processes and reads their results, a case that writes ("Cases that write") inserts, updates and deletes
records over OData with aliases and cleanup and asserts what a listener, a trigger of a SQL script or a
default did (`check-record ... has`, `check-count`). That is how an entity event listener and a SQL
script are proved - `ProcessCases/usr-order-backend.act` is one, run on the test site.

A process case starts business processes over the process engine service, reads their result
parameters back and checks the records they left behind over OData. No page is opened, and a run made only of process cases never launches a browser - the case above runs
in about a second.

```
use Supervisor
start UsrOrder_Process with Amount=500;Contact=0c48c818-08f0-4f70-9b58-be512227f3bf
check-result Verdict eq "big"
check-result Total ge "5"
check-record UsrOrder UsrName=Order 1;UsrAmount=500 exists
check-record UsrOrderLog UsrOrder/Id=0c48c818-08f0-4f70-9b58-be512227f3bf not exists
```

The runner scans the case folders recursively (`Cases/<Package>/...`).

Process cases live in their own folders (`ProcessCasesFolders`, default `./ProcessCases`) and
run after the UI cases; `--filter` and `--validate-only` see them the same way. They are a
different kind of test - what the backend does, not what a user sees - which is why they are
kept apart from the page cases rather than mixed into them.

`start` names a process described under `Configuration/processes` (one file per process, see
below). Values after `with` are checked against the parameter's type before the run, an output
parameter cannot be passed in, and a bare value may name a static value. The engine's answer
decides the line: a process that did not start (unknown, unpublished, an exception) fails with
the engine's message.

`check-result` reads an output or variable parameter of the process the script last started,
with the operators and typing of `check-value`: numbers compare as numbers, dates as dates, the
rest as text. A lookup result is its id.

`check-record` builds an OData filter from the list: a GUID, `true`/`false` and a number go
unquoted, everything else is a string; a lookup column given a GUID is
addressed as the path `UsrContact/Id` in the filter (`UsrContact=<guid>` filters `UsrContact/Id eq <guid>`; Creatio
refuses `UsrContactId eq <guid>` there with `500 Column by path UsrContactId not found`) and as `UsrContactId` in a
`$select` and a body (`has UsrContact eq <guid>`, `insert ... set UsrContact=<guid>`); a column already ending in `Id` is left alone. `[not] exists` asserts existence, which is
enough to prove that a process created, found or removed what it should have; `has <column> <op>
<value>` compares a column of the record (see "Cases that write").

```jsonc
// Configuration/processes/UsrOrder_Process.json
{
  "name": "UsrOrder_Process",
  "parameters": [
    { "code": "Amount", "type": "Money", "direction": "in" },
    { "code": "Contact", "type": "Lookup", "direction": "in" },
    { "code": "Verdict", "type": "Text", "direction": "out" },
    { "code": "Total", "type": "Integer", "direction": "variable" }
  ]
}
```

`direction` is `in`, `out` or `variable` (both). The file is what the process schema declares;
the knowledge base's `proc.py test-config <package> <Process> --out <file>` writes it from the
package, so a process built as files describes itself for its tests.

## Cases that write

A case may write data the way a user would and then assert what the backend did in response - an
entity event listener, a database trigger created by a SQL script, a default, a computed column.
OData is the case's CRUD API and nothing more: a SQL script runs at `clio push-pkg`, a case proves its
effect, it never runs SQL.

```
# writes
# ac: AC-01
use Supervisor
insert UsrOrder as Order set UsrName=Listener bed;UsrAmount=500
check-record UsrOrder Id=$Order has UsrAmount eq 500
update UsrOrder $Order set UsrAmount=5000
check-record UsrOrderLog UsrOrder/Id=$Order;UsrKind=Big exists
check-count UsrOrderLog UsrOrder/Id=$Order eq 1
delete-record UsrOrderLog UsrOrder/Id=$Order
delete UsrOrder $Order
```

- **Writes.** `insert` posts the record and binds its Id to the alias: `insert ... as Order` makes
  `$Order`. `update` patches and `delete` deletes a record named by `$alias` or a GUID. `delete-record`
  deletes every record matching a filter - the records a page or a process created, which the case
  has no alias for; more than 20 matches is refused with the count, no match fails. Values are typed
  like the filters: a GUID, `true`/`false` and a number unquoted, the rest text; a lookup given a GUID
  is written to its `Id` column (`UsrStatus=<guid>` writes `UsrStatusId`); a value naming a static value
  is written as that value. The writes go as the first configured user, with `BPMCSRF` and
  `ForceUseSession`; a refused write fails the line with what Creatio answered.
- **Expected refusal.** `insert ... expect error "<text>"` and `update ... expect error "<text>"` pass when the OData write FAILS and its error
  text (`error.message` and `error.innererror.message`, where a listener's message is) contains `<text>` (case-blind; `expect error` alone accepts any
  error). A saved write fails the step (`expected an error ... but the record was saved: <id>`, and cleanup deletes it); another text fails naming both.
  A refused `insert` binds no alias. Not for `delete`. `Cases/s45-expect-error.act` is one.
- **Cleanup.** Every record a case inserts is deleted when the case ends, newest first - passed,
  failed or stopped early - unless the `insert` line says `keep`. `delete` and `delete-record`
  take a record off that list. A record the cleanup cannot delete fails the case as a run error naming
  it: data left behind is not a pass.
- **Variables.** `$name` holds text: an insert alias, `remember <code> as $name` (what an element
  shows), `remember-record <object> <filter> as $name` (the Id of the one matching record; none or
  several fail). A `$name` is substituted in every unquoted argument - filters, values, `update` /
  `delete` targets, `open <page> for $name`, `check-value <code> eq $name`. A name used before the line
  that defines it is a validation error. `$name+N` / `$name-N` computes an integer and is allowed only
  as the value `check-value` compares with: `check-value UsrNumber eq $first+1`.
- **Record asserts.** `check-record <object> <filter> has <column> <op> <value>` reads the column of
  the matching record (no record fails on its own) and compares it with the operators of
  `check-value`: a number as a number and a date as a date when both sides parse, the rest as text. A
  lookup compares by id - give a GUID and the `Id` column is read. `check-count` counts the filtered
  set (`/$count`, `$count=true` where a version refuses the bare segment). `check-distinct` fails when
  two matching records share the column's value - two records saved at once got different numbers.
- **`# writes`** is a header directive (a `#` line before the first command). It makes the case
  stop at its first failure whatever `continueOnFailure` says - a failed `set` must not be followed
  by a Save - and validation refuses an inserted alias that is neither deleted later in the case nor
  marked `keep`. Cleanup runs for every case either way; the directive makes the author say it. After a failure the case's later `delete-record` lines (the records a page or a process created, which no alias knows) still run, and the report puts `cleanup: ...` lines under the failure (`cleanup: deleted <Entity> <id>` for inserted records, `cleanup: delete failed <reason>` when one stays); a `delete-record` that finds nothing is silent, and the case stays FAILED.
- **`# bed bench`** (a `#` line before the first command) marks a case written against the benchmark package, whose `Usr` names are real: `scripts/gate.py` copies it without the `--rename` mapping; a case without the line is renamed.
- **`# ac: AC-02`** names the acceptance criterion the case proves. Run with
  `--task-folder <dir>` (and optionally `--task <id>`), every case writes
  `<dir>/evidence/AC-02-report-N.txt` - each line with its outcome, the failed steps, the console
  errors - and `AC-02-report-N.table.md`, a draft row of the tester's report table
  (`| AC | Result | Evidence |`). N is the next number free; a case without `# ac:` is named by its file.
- **Console.** `check console no errors [except "<regex>"]` fails when the browser console logged an
  error (or the page threw) on any page the case opened so far, apart from the ones the regex matches;
  the regex is compiled during validation. `captureConsole: true` in `run.config.json` also puts each
  case's console errors into the text, HTML and JUnit reports.
- **Network.** `check network no errors [except "<regex>"]` fails when a request of the case's pages failed
  or was answered 4xx / 5xx (the regex is matched against `METHOD url`). Every run writes the requests of each case
  with their durations to `Reports/network/<stamp>-<case>.log` (the slowest ten first, then every request in the order
  it finished); the text report names the file with the count, the number of errors and the slowest request.
- **Screenshot.** A case that fails keeps a screenshot of the page at its first failed command,
  `Reports/screenshots/<case>.png` (the newest run overwrites it); the text report names it.
- **Trace.** `--trace` (or `"trace": true` in `run.config.json`) records a Playwright trace per case and user,
  `Reports/traces/<case>-<user>.zip` (screenshots, DOM snapshots, network, console); open it with
  `playwright show-trace <file>` (or trace.playwright.dev). It adds a few seconds and some MB per case, so it is a flag.
- **Console log.** Every run writes the whole browser console of each case that produced one to
  `Reports/console/<stamp>-<case>.log`: one timestamped line per message of every type (`log`, `warning`,
  `error`, ...), page error, failed request and 4xx / 5xx response, with the script location when the
  browser gives one. The text report names the file (`console log (N lines): <path>`), and the `last_report`
  MCP tool appends the logs of the newest run. This is the file to read when a page misbehaves and the
  case alone does not say why.
- **`on <page>`** now checks the claim: before rebinding it waits up to `pageCheckTimeoutMs` for at
  least one element of that page's file (elements on no tab first) and otherwise fails naming the
  ones it looked for, instead of a later line failing with a bare "not found".

A process case and a page case can both write; the examples are `ProcessCases/order-writes.act.exp`
and `Cases/order-page-writes.act.exp`.

## Element Types

| `type` | Creatio control | Value kind | Extra members |
| --- | --- | --- | --- |
| Button | `crt-button` | None | `isSave`, `doubleClick`, `settleMs`, `disappearTimeoutMs`; `pinned` |
| CasesBar | `crt-entity-stage-progress-bar` | Stage | `values`, `subvalues`; `pinned` |
| DataGrid | `crt-data-grid` | None | `columns`; `pinned` |

A `DataGrid` has two properties Creatio configures independently, the way a field has required and
read-only: whether inline editing is on, and whether it sits inside an expansion panel. All four
combinations occur. Inline editing is read from the row Creatio adds to the table footer for
appending a record, which it renders only for a grid that takes edits in place; the per-cell
editing-disabled marker says only that one column is read-only, and an editable grid with a
calculated or image column carries plenty of those.

A grid carries no caption of its own, so its `label` is the caption of the panel that holds it, and
a grid placed directly on a page has an empty label. That label is also how the grid is reached: when
it is not on screen, the framework brings that panel into view and opens it if it is closed. Creatio
renders a panel's contents only once it scrolls into view, so an expanded panel further down the page
holds nothing until something looks at it.

Creatio renders tabs in two shapes, and they are opposites in the DOM. A tab panel gives every tab
its own `element-name`, so each tab is an element of type `Tab` and `click <code>` switches to it. A
toggle group has one `element-name` for the whole group and names the tabs inside it only by their
captions, so the group is one element of type `ToggleTab` and the open tab is its value:

```
click GeneralInfoTab                              # a tab of a tab panel
set ViewToggle "Tab 2"                            # a tab of a toggle group
check-value ViewToggle eq "Tab 2"
```

The distinction is the `type` in the page file, which is also what tells `analyse` how to read the
control. `tabs` lists the captions the group offers, in display order; a toggle group has no caption
of its own, so its `label` is empty. `panels` maps a tab's caption to the `element-name` of the panel it opens (`"panels": {"Attachments": "AttachmentList"}`): `set` on such a tab is done when the panel is visible, clicks once more if it is not, and fails with `panel <name> did not open after 2 clicks`; a case that needed the second click carries `note: toggle <group>: '<tab>' opened on the 2nd click` in the report. `click` does not accept a `ToggleTab` and `set` does not accept
a `Tab`: which of the two a control is decides how it is driven.

`columns` lists the grid's column captions in display order, as `analyse` found them. Only the
columns a person sees are recorded: Creatio gives every grid a leading cell for the row controls and
a trailing cell that absorbs the free width, and both announce themselves as column headers without
naming any data.
| Tab | `crt-tab-panel-header-item` | None | `pinned` |
| ToggleTab | `crt-button-toggle-group` | Tab | `tabs`; `panels`; `pinned` |
| QuickFilter | `crt-quick-filter` | Lookup | - |
| FileUpload | `crt-file-list` | Upload | `trigger` (the `element-name` of the add button when it is not inside the list) |
| Text | `crt-input` | Text | `pinned` |
| RichText | `crt-rich-text-editor` | Text | `pinned` |
| Email | `crt-email-input` | Text | `pinned` |
| Phone | `crt-phone-input` | Text | `pinned` |
| Link | `crt-web-input` | Text | `pinned` |
| Integer, Decimal | `crt-number-input` | Number | `pinned` |
| Date, Time, DateTime | `crt-datetimepicker` | DateTime | `pinned` |
| Boolean | `crt-checkbox` | Boolean | `pinned` |
| Lookup | `crt-combobox` | Lookup | `pinned` |

`pinned: true` marks an entry as a human decision. The analyser leaves that entry untouched on later runs, including decisions that cannot be inferred from the DOM.

An element may also declare `"tab": "<TabCode>"`. Validation warns when a case addresses it
without first opening that tab. This warning does not prevent execution: Creatio may remember
the previously selected tab.

## Classic UI

A page file declares its generation with `type`: `FreedomUI` (the default) or `ClassicUI`. The two
share the DSL, the commands and the type names, and nothing else: a Classic page is Ext JS, addressed
by predictable DOM ids rather than `element-name`. The page's generation decides which `Text` or
`Lookup` an element is, so a Freedom-only type on a Classic page is refused when the configuration
loads, with the message naming the generation it does exist for.

A control that is not there fails its line with `'<code>' was not found on the page.` (no stack trace, in both generations). A Classic field
that is in the page at zero width fails at once with `<code> is in the page but invisible (zero width)` instead of running out the timeout. A Classic toolbar button
is found by `[data-item-marker="<Name>Button"]` first, then by the ids `{prefix}{Name}Button-wrapperEl` and `-textEl`.

A Classic page needs its `schema`, the page schema name. Every control id on the page starts with it:
`ContactPageV2NameTextEdit-el` is the input of the element named `Name` on `ContactPageV2`, rendered
by a `TextEdit`; `-wrap` is its box and `ContactPageV2NameLabel` its caption. The DSL addresses the
element by `code`; when the element's name in the schema's `diff` differs from the code, the page
file carries it as `name`. Pages built with the section wizard name their fields
`LOOKUP<guid>` or `STRING<guid>`, so the page file maps a readable code onto that:

```jsonc
// Configuration/pages/OrderClassic.json
{
  "name": "OrderClassic",
  "url": "/0/Shell/#CardModuleV2/UsrOrder1Page",
  "type": "ClassicUI",
  "schema": "UsrOrder1Page",
  "elements": [
    { "code": "UsrName",   "label": "Number",   "type": "Text" },
    { "code": "UsrType",   "label": "Type",     "type": "Lookup",   "name": "LOOKUPceebb14a-c7fc-443b-a434-6d47069519d4" },
    { "code": "UsrDate",   "label": "Date",     "type": "DateTime", "name": "DATETIME7fa68919-649f-46d7-8f33-3149f642c4a3" },
    { "code": "CloseButton", "label": "Close",  "type": "Button" },
    { "code": "GeneralInfoTab", "label": "General", "type": "Tab" },
    { "code": "Tabs", "label": "", "type": "TabPanel", "tabs": ["General", "Products"] },
    { "code": "Stage", "label": "", "type": "CasesBar", "values": ["New", "In progress", "Done"], "subvalues": { "Done": ["Done", "Cancelled"] } },
    { "code": "Products", "label": "Products", "type": "Detail", "name": "UsrOrderProductDetail", "columns": ["Product", "Quantity"] },
    { "code": "AddProduct", "label": "", "type": "Button", "name": "AddRecordButton", "detail": "UsrOrderProductDetail" }
  ]
}
```

| `type` | Classic control(s) | Value kind | Extra members |
| --- | --- | --- | --- |
| Text | `TextEdit` | Text | `name`; `pinned` |
| RichText | `MemoEdit` | Text | `name`; `pinned` |
| Integer | `IntegerEdit` | Number | `name`; `pinned` |
| Decimal | `FloatEdit`, `MoneyEdit` | Number | `name`; `pinned` |
| Boolean | `CheckBoxEdit` | Boolean | `name`; `pinned` |
| Date | `DateEdit` | DateTime | `name`; `pinned` |
| Time | `TimeEdit` | DateTime | `name`; `pinned` |
| DateTime | `DateEdit` + `TimeEdit` | DateTime | `name`; `pinned` |
| Lookup | `LookupEdit`, `ComboBoxEdit` | Lookup | `name`; `pinned` |
| Button | `{Prefix}{Name}Button-wrapperEl` / `-textEl` | None | `name`, `detail`, `settleMs`; `pinned` |
| Tab | `li[data-item-index]` of `{Schema}TabsTabPanel` | None | `name`, `panel`, `settleMs`; `pinned` |
| TabPanel | `{Schema}{Name}TabPanel` | Tab | `tabs`, `settleMs`; `pinned` |
| Detail | `{Detail}Container`, grid `grid-{Detail}DataGridGrid-wrap` | Number (row count) | `name`, `columns`; `pinned` |
| CasesBar | `SectionActionsDashboardActionsControlContainer` (`BaseStageControl`) | Stage | `values`, `subvalues`, `container`, `settleMs`; `pinned` |

A `DateTime` column renders two controls under one name, a date and a time; the element writes both
and reads one value. A `Decimal` covers both the float and the money control because a money field
is a float with a currency behind it. A `Lookup` covers the drop-down list and the searchable
lookup: both open a list under the input when text is typed, and `set` types the value and picks
the item whose caption matches exactly.

The DSL speaks ISO dates and invariant numbers whatever the user's culture. Classic shows
`06.11.2026` and `12,50` to a Ukrainian user, so typed fields are read from the page's view model
rather than from the rendered text, and a date is written in the culture the page itself reports
(`Terrasoft.Resources.CultureSettings`), never from a format hard-coded in the framework.

Tabs have no ids: the headers are `li` items whose `data-item-index` is the tab's position in the
page's `TabsCollection`, hidden tabs counted. A tab is therefore addressed by its name in the schema
(`GeneralInfoTab`, `Tabdebe3cb6TabLabel`), and the framework turns the name into the index through
the view model. The panel is `Tabs` unless `panel` says otherwise. Content of a visited tab stays in
the DOM, hidden, when another tab is opened; a control on a tab that was never opened is absent.

Classic renders tabs in one shape, but the DSL offers both views of it, as it does for Freedom UI:
a `Tab` is one tab by its schema name, for `click`; a `TabPanel` (named `Tabs` on nearly every
page) is the panel as one element whose value is the open tab's caption, for `set` and `check-value`:

```
click GeneralInfoTab                 # by schema name
set Tabs "Products"                  # by caption
check-value Tabs eq "Products"
```

A `Detail` is the grid of related records, addressed by the **detail schema name**
(`UsrOrderProductDetail`), because everything inside a detail is prefixed by that schema rather
than by the page. Its value is its row count, read from the grid's loaded collection, so
`check-value Products eq "3"` and `check-value Products gt "0"` read naturally and `set` is
refused. `check Products columns` compares the rendered captions with `columns`, and
`check Products is editable` tells a detail that takes edits in place (Classic renders it as a
configuration grid) from one that opens a page per record. A detail's own buttons are ordinary
`Button` elements with the `detail` option (`UsrOrderProductDetailAddRecordButtonButton-wrapperEl`),
and their `name` is the full schema name of the button, `AddRecordButton`, as it is for page
buttons such as `CloseButton`. A detail on a tab that was never opened is absent, as any control is.

A detail's rows are addressed by their cells: `check-row Products Product=Pump exists`,
`select-row`, `delete-row`. A detail that edits in place also takes `add-record Products set
Product=Pump;Quantity=2`: the row the add button opens is filled through the editors it renders (a
lookup through its list, a checkbox by a click, a date in the page's culture) and saved with the
row's own save action. **A detail saves its own records**: a row added or deleted is in the database
at once, whatever the page's Save button does afterwards. A detail that opens a page per record
takes `click` on its add button followed by `on <page>`.

The page's own `SaveButton` takes `"isSave": true`, as in Freedom UI: after the click, a message
box is read as the reason the save failed, and the button has to leave the toolbar, which is how
Classic shows a clean page. Classic analysis marks `SaveButton` automatically.
`DiscardChangesButton` is the Cancel that appears beside it.

A Classic **section** inside the Shell (`#SectionModuleV2/<Section>`) is analysed and driven the
same way: its list is a `Detail` named after the section schema (there is no detail container, so
the grid itself is the root), its toolbar buttons are `Button`s (`SeparateModeAddRecordButton`,
`SeparateModeActionsButton` ...), and a record opens with `open-row` followed by `on <page>`. Two
things to know: a section whose schema name is wrong never finishes loading (the Shell keeps its
splash up), and a record opened from its section renders in combined mode, with the list beside the
card and no Close button in the card's toolbar.

The `CasesBar` is the stage bar of the actions dashboard (the DCM bar). It is one shared module,
so it needs no schema-derived id and the page file says only `"type": "CasesBar"`. Its value is the
committed stage as the page's stage column holds it, which is the sub-stage when one is selected;
`set` clicks a stage, or opens the parent's menu for a sub-stage, answers the confirmation the page
may ask, and waits. **In Classic a stage change is not an edit: the dashboard validates the page and
saves the record at once**, so `set` on the stage bar writes to the database even though nothing
else on the page did. `values` and `subvalues` are documentation the analyser fills in; the element
asks the control itself which stage hides which sub-stages. A stage the case does not allow from the
current one is refused as not enabled. A message the page shows on the way -- a validation error
naming an empty required field, a note that the move went through, a modal asking for something
first -- is dismissed and quoted: in the log when the stage still changed, in the failure when it did
not, so a case never fails with a bare "holds X" when the page said why.

`analyse` describes a Classic page when the address is a `#CardModuleV2/<Schema>` one, and
`schemas --classic` lists the instance's Classic pages (`...Page`, `...PageV2`, `...1Page`) with the
address to paste. Rather than reading the DOM alone, the analyser asks each control's Ext component
for the column it binds and the column's type, so the page file it writes names a field by its
column (`UsrTypeCargo`) and records the schema name (`LOOKUPceebb14a-...`) as `name`. A second element
bound to the same column, typically a copy of a header field on another tab, keeps its schema name as
its code. A DateTime column's date and time controls become one `DateTime` element; details are named
by their schema and carry their `columns`; a detail's buttons are `Button` elements coded detail
schema plus button name, with `detail` set; the tab panel becomes `Tabs` with its captions and the
stage bar `Stage` with its `values` and `subvalues`. Every tab is opened in turn, because a tab
renders its content on first opening, and the tab the page arrived on is restored. `SaveButton` and
`DiscardChangesButton` are always written although a clean page does not render them: BasePageV2
gives them to every page, and they appear the moment the page is dirty.

Three things a Classic page does that look like test failures and are not. Once a page has unsaved
changes, Classic replaces its Close button with Save and Cancel, so `check CloseButton exists`
holds before the first `set` and `check CloseButton not exists` after it. A business rule may lock
a field the moment it gets a value, so a `set` that succeeds can be followed by a `clear` that is
refused as read-only; the refusal names the field. And the actions dashboard and the details are
modules of their own that finish loading after the page's fields, so the stage bar and the details
wait for their own content before answering rather than relying on the page being ready.

## Values

Values cross command layers as text. Dates accept `yyyy-MM-ddTHH:mm:ss`, `yyyy-MM-ddTHH:mm`, or `yyyy-MM-dd`; date values are returned as `yyyy-MM-ddTHH:mm:ss`.

| Target kind | Accepted copied source kinds |
| --- | --- |
| Text | Text, Number, Boolean, DateTime, Lookup, Stage |
| Number | Number |
| Boolean | Boolean |
| DateTime | DateTime |
| Lookup | Text, Lookup |
| Stage | Text, Lookup, Stage |

Boolean literals are exactly `true` or `false`; numbers use invariant decimal syntax.

## Finding A Page

Analysing a page needs its schema name, and the name is rarely what you would guess: contacts live on
`Contacts_FormPage`, plural, while `ContactPageV2` is the classic UI page for the same entity. Nothing
in the browser lists them, so the runner reads them over OData:

```bash
creatio-tests schemas Contact          # form pages whose name contains "Contact"
creatio-tests schemas                  # every form page on the instance
creatio-tests schemas --list-pages     # section pages instead
creatio-tests schemas Order --classic  # Classic UI pages (ContactPageV2, UsrOrder1Page ...)
```

Each result comes with the address that opens it, ready to paste into `analyse`:

```
  Contacts_FormPage
      /0/Shell/#Card/Contacts_FormPage/edit/<recordId>
```

## Analysis Phase

A run has two phases. Analysis scripts live in the folders named by `AnalysisFolders` and run first;
test cases live in `CasesFolders` and run second. Between the phases the element catalog is reloaded
from the pages directory, so the cases are validated against the configuration analysis has just
written rather than whatever was on disk when the process started.

```jsonc
// creatio.env.config.json
"CasesFolders":    ["./Cases"],
"AnalysisFolders": ["./Analysis"]
```

**Analysis is off by default.** Once a page is described its configuration is committed and reused,
so re-analysing on every run costs a browser session per page and tells you nothing new. A pipeline
runs the cases alone; analysis is for the moment a page has actually changed.

```bash
creatio-tests                  # cases only, analysis skipped
creatio-tests --analyse        # analysis first, then the cases against fresh configuration
creatio-tests --analyse-only   # describe the pages and stop
```

`RunAnalysis: true` in `run.config.json` turns it on without a flag. A failed analysis script stops
the run before the cases: configuration they were meant to write is missing, so any result the cases
produced would be misleading.

The analyser opens every tab by default. Freedom UI renders only the open tab, and Creatio remembers
which tab was open when the page was closed, so neither the initial tab nor controls on closed tabs
can be assumed. The analyser restores the tab that was open on arrival after walking the others.

## Element Types The Analyser Cannot Settle

Date, time, and date-time controls share a host tag. The analyser uses the picker icon first
(`Calendar`, `Time`, or `Date/Time`), then the displayed value. For an editable empty control with
no picker icon it reports: `the control is empty and shows no picker icon; open the picker to see
which it is, then set the type and mark the entry "pinned": true`.

A read-only empty date/time control has neither icon nor value, so its exact type cannot be
established. It is reported as `read-only and empty, so the exact type cannot be established;
presence and caption are still assertable`. Keep it as a presence-only element: a test can use
`check <code> exists`, `check <code> is readonly`, and caption matching, but cannot make a
value-type assertion that depends on whether it is Date, Time, or DateTime.

## Configuration Files

All paths are relative to the working directory.

| File | Fields |
| --- | --- |
| `creatio.env.config.json` (copy `creatio.env.config.example.json`) | `BaseUrl`, optional `AuthUrl`, `Users` (`Username`, `Password`, optional `Name`: what a case writes after `use` when the login should stay out of the cases), optional `CasesFolders`, `AnalysisFolders` and `ProcessCasesFolders`, optional `AllowDevOnly` and `ClioEnvironment` (`# dev-only` cases) |
| `creatio.site.config.json` | `AuthPath`, optional `ODataBasePath`, optional `ProcessStartPath` (default `/0/ServiceModel/ProcessEngineService.svc/RunProcess`) |
| `processes/*.json` | one file per process a case may start: `name` and `parameters` (`code`, `type`, `direction`) |
| `pages/*.json` | one file per page: `name`, `url`, `type` (`FreedomUI`, the default, or `ClassicUI`), `schema` (Classic only: the page schema name), and `elements` (`code`, `label`, `type`, optional `tab` (the page tab the control lies on: `analyse` writes it for a control shown on one tab only; a command on such a control opens that tab first, so no `click <Tab>` line is needed) and `pinned`, plus type-specific options such as a Classic element's `name` or a Save button's `isSave`). The page is implied by the file, so elements never repeat it. |
| `objects.config.json` | `objects`: `name`, `sectionPage`, `formPage`, `newButton`, `saveButton`, `fields` mapping codes to static-value names |
| `static.values.json` | object mapping static names to scalar values |
| `run.config.json` | `headless`, `continueOnFailure`, `runAnalysis`, `viewportWidth`, `viewportHeight`, `elementTimeoutMs`, `absenceTimeoutMs`, `pageCheckTimeoutMs` (the `on <page>` check, 15000), `pollIntervalMs` (`wait-record` / `wait-count`, 1000), `testDataDirectory` (`upload`, `TestData`), `pageLoadTimeoutMs`, `captureConsole` (console errors into the reports), `trace` (a Playwright trace per case), `reportsDirectory`, `reports`, `skipFilePrefix` |

`viewportWidth` and `viewportHeight` (1600 x 950 by default) fix the size of the browser window every
case runs in. This is part of a run's definition rather than a property of whoever's machine it runs
on: Creatio lays a page out differently in a narrow window, to the point where a side panel's hover
actions overlap the tab headers and a tab cannot be clicked at all, and controls further down a page
are never rendered. Analysis uses the same size, so what it records and what a case can reach agree.

```jsonc
// Configuration/pages/ContactForm.json -- one file per page
{
  "name": "ContactForm",
  "url": "/0/Shell/#Card/Contacts_FormPage",
  "type": "FreedomUI",
  "elements": [
    { "code": "JobTitle", "label": "Full job title", "type": "Text" },
    { "code": "Account", "label": "Account", "type": "Lookup" },
    { "code": "GeneralInfoTab", "label": "Contact info", "type": "Tab" },
    { "code": "CloseButton", "label": "Close", "type": "Button" }
  ]
}
```

Every `.json` file under `Configuration/pages` is loaded, including subdirectories, so pages can be
grouped however suits the project. The file name is only a label; a page's identity is its `name`.

## Validation

The first pass checks all lines before a browser action runs: unknown commands, malformed arguments, absent pages/elements, unsupported capabilities, incompatible copies, invalid literals, and object workflow references.

```text
Unknown command 'opne'. Known commands: add-record, analyse, check, check-value, click, clear, end, goto, open, set, use, wait.
Element 'X' on page 'ContactForm': Unknown element type 'Slider' for a FreedomUI page. Known types for FreedomUI pages: Boolean, Button, CasesBar, DataGrid, Date, DateTime, Decimal, Email, Integer, Link, Lookup, Phone, RichText, Tab, Text, QuickFilter, Time, ToggleTab.
Element 'Email' on page 'OrderClassic': Unknown element type 'Email' for a ClassicUI page. It exists for FreedomUI pages only. Known types for ClassicUI pages: Boolean, Button, Date, DateTime, Decimal, Integer, Lookup, RichText, Tab, Text, Time.
'wait' expects the unit 'second' or 'minute'.
```

## Recipes

To add a command, copy [ClickCommand.cs](../src/CreatioAutoTests.Core/Commands/ClickCommand.cs), select or implement an `ICommandValidator`, declare its capability interfaces in `SupportedTargets`, and add tests. Reflection discovers the command; no registry, enum, or switch changes.

To add an element, copy [TextField.cs](../src/CreatioAutoTests.Core/Frontend/Fields/TextField.cs), choose a suitable base, apply `[UiElement]`, and provide an options class where needed. Reflection discovers the element; no registry, enum, or switch changes.

To add a Classic element, copy [Classic/Fields/TextField.cs](../src/CreatioAutoTests.Core/Frontend/Classic/Fields/TextField.cs) instead: `Generation = UiGeneration.ClassicUI` and the `Controls` it renders as take the place of a host tag, and the same type name may already exist for Freedom UI.