---
description: Creatio 8.3 platform facts verified in work (PostgreSQL): processes and their runtime, publish and compile, SysSchema and layers, push-pkg and IsChanged, roles, OData 4, services and CSRF, Classic UI DOM, Freedom UI remote modules, clio quirks, Windows tooling; each with how it was seen and which tool, test or skill carries it; a closing list of what is not verified. Search phrases - process must be published, column at path not found, Custom layer, IsChanged, ModifiedOnUtc, SysAdminUnitInRole, filter path Column/Id, BPMCSRF, DataSourceFilters, BK15, meta path, ServerChannel, MessageBox.
---
# Creatio platform facts: must be published, replacing layers and Custom, IsChanged and ModifiedOnUtc on push-pkg, SysAdminUnitInRole, BPMCSRF, SysProcessLog, clio quirks

Verified facts about Creatio 8.3 on PostgreSQL, collected in work on client sites and anonymised: every name here
is `Usr`, "the site" or "the client package". Each fact has an id, how it was seen (`source`: platform source code;
`sql`: a database query; `run`: an execution on a site; `build`: a compiler or an install) and `used by`: the tool,
test, recipe or skill that carries it (`-` when nothing does yet). Facts not verified are at the end and must not
become recipes as they stand.

## Processes

**P-A1 `MsgChannelUtilities.PostMessage` reaches the process user's channel only.** It finds the channel by
`CurrentUser.Id`; an offline user gets a log line `Channel not found for user`. `PostMessageToAll` reaches
everyone. A process started from a Quartz job or `ProcessExecutor` runs as the job user (Supervisor), so a popup
posted that way goes to Supervisor. To reach one user: `SysAdminUnit` by `ContactId`, then
`MsgChannelManager.Instance.FindItemByUId(sysAdminUnitId)` and `channel.PostMessage(new SimpleMessage {...})`
with `Header.Sender`. 8.3, source + run. used by: `who_reads_message` (S33-T02), `HowToPostMessageToCurrentUser`.

**P-A2 Compiling against `MsgChannelManager` / `SimpleMessage` outside the site** needs `Terrasoft.Messaging.Common.dll`,
`Terrasoft.Messaging.Common.Standard.dll` (type forwarding) and `netstandard`; otherwise CS1069 and CS0103. 8.3,
build. used by: `push` script compile reference list (S29-T02), `HowToPostMessageToCurrentUser`.

**P-A3 A script task is generated into `namespace Terrasoft.Core.Process` with the process's own `using` list.**
`using Terrasoft.Configuration` may be absent, then a configuration class fails with CS0103. Write the full name
`Terrasoft.Configuration.<Class>`. 8.3, source + build. used by: `HowToWorkWithScriptTaskParameters`, the C# style guide, `push` compile.

**P-A4 A process whose script did not compile fails at start with "the process must be published before it is
started".** No `SysProcessLog` row, the returned id is `Guid.Empty`. `clio compile-package` prints only
`Start/End rebuild ... Done`, `compile-configuration` shows other packages' errors only; the error surfaced only in
a build run outside clio. 8.3, run. used by: `push` script compile step (S29-T02), `run_process` message.

**P-A5 A process without script tasks has no `SysSchemaSource` row;** the row appears when a script task is added and
the package installed, with `ModifiedOn` = install time. 8.3, sql. used by: `push` script compile step.

**P-A6 A raw newline inside a JSON string of process metadata installs fine; Python's `json.loads` rejects it.**
Keep `\r\n` escapes in the files; read with `strict=False`. 8.3, run. used by: `clio.py`, `Environment.sql`
(S25).

**P-A7 Who a process runs as.** Signal-started: `SysProcessLog.OwnerId` is the user who saved the record and the
records it creates have that `CreatedById`. From a Quartz job: the job user. Quartz tables are lower-case on
PostgreSQL (`qrtz_job_details`), `job_data` is binary with `UserName` and `IsSystemUser`. 8.3, sql. used by:
`process_timers` (S33-T06).

**P-A8 Logs of a finished process.** `SysProcessElementLog` per `SysProcessId`: `Caption`, `StartDate`,
`CompleteDate`, `ErrorDescription`. `SysProcessData.PropertiesData` is bytea, parameter values of a finished run
cannot be read by SQL. Two copies of one process with the same signal both run on each change, their element logs
interleave within milliseconds. 8.3, sql. used by: `process_runs`, `process_error`, `process_runs steps=`
(S33-T06), `check-process` (S34-T07).

**P-A9 `SysProcessDisabled` exists (`SysSchemaId`).** A process absent from it ran by its signals; that a row
disables a process is not verified (N-5).

**P-1.1 The runtime reads element parameter values from the schema mappings, not from the element.** The value is
stored twice: `BK4[].BP2[].L8` in the element and `BK15[]` in the mappings (`GT2 = [Element:{uid}].[Parameter:{uid}]`,
value in `GT1.GS2`); `BK15` is what runs. A filter changed only in `L8` stays old at runtime and the platform's
validation does not complain. 8.3, run. used by: `proc.py validate` mapping agreement (S22-T03).

**P-1.2 A conditional flow formula (`CI3`) is a meta path**, not the readable form:
`[#[IsOwnerSchema:false].[IsSchema:false].[Element:{uid}].[Parameter:{uid}].[EntityColumn:{uid}]#]`. The readable
`{Element:Name.Parameter:...}` makes every run fail with `InvalidOperationException ... Expression expected (at
index 0)` from `DynamicExpresso.Parsing.Parser`: macros are substituted before DynamicExpresso parses. 8.3, run.
used by: `expressions` module, `proc.py` flow conditions.

**P-1.3 A data-step result column in formulas and filters** is `[Element:{uid}].[Parameter:{ResultEntity}].[EntityColumn:{uid}]`;
in a filter parameter `dataValueType` is 26. 8.3, run. used by: `proc.py filter`.

**P-1.4 `DataSourceFilters` is JSON inside a JSON string** (`serializedFilterEditData`, `dataSourceFilters`); the
right side that names a process parameter is a `ParameterExpression` (`expressionType` 2) with `value.value` = the
meta path. 8.3, source. used by: `proc.py filter`, `find_in_processes` (S33-T02).

**P-1.5 The columns ReadData reads** are one parameter, column UIds joined by `;`, order irrelevant (the designer
re-saves them in another order). 8.3, source. used by: `proc.py` data steps.

**P-1.6 Renaming a schema keeps its UId.** One process may live under different names on different sites; a push
from git restores the old name. 8.3, run. used by: `resolve_uid`, `process_runs` by UId.

**P-1.7 The "record changed" start signal** holds the object, the trigger columns (UIds) and the record filter as
one unit edited together in the designer. 8.3, source. used by: `proc.py` signal elements.

**P-1.8 Publish.** See P-A3 and P-A4: a script compile error leaves the process unpublished, `compile-package`
does not show it. used by: `push` (S29-T02).

**P-1.9 Runs are `SysProcessLog`** (`SysSchemaId` -> `SysSchema.Id`, `StatusId` -> `SysProcessStatus`,
`ErrorDescription` with the stack); steps are `SysProcessElementLog`. Find every run of a process by
`SysSchema.UId`: names and package copies differ. 8.3, sql. used by: `process_runs`, `process_error`.

**P-1.10 A timer process with a "every minute" cron fills `SysProcessLog` with a run per minute**; filter them
out when reading. 8.3, sql. used by: `process_runs` noise filter.

**P-1.11 `SysSchema.Caption` of a process stayed old after a push** although the resource file had the new caption.
8.3, run. Cause not found (N-10).

## Schemas, packages, layers

**P-2.1 Replacing layers apply in package-dependency order, the `Custom` package last.** A copy in `Custom` (never in
git) overrides every package edit and cannot be deleted by the tools ("installed from an archive"). Look at every
copy of a schema in `SysSchema` before changing a page or an object. 8.3, run + source. used by: `schema_layers`,
`layers.py`, `merge-plan`, the author skill.

**P-2.2 `SysSchema` on PostgreSQL:** the package is `SysPackageId` (no `PackageUId`), `MetaData` is bytea
(`convert_from("MetaData", 'UTF8')`), `IsChanged` also exists on `SysPackageSchemaData` and `SysPackageSqlScript`.
8.3, sql. used by: `layers.py`, `push.py`, `integrity.py`.

**P-2.3 `IsChanged` is set by edits on the site** (designer, wizards) and a push conflicts with it; reset it in all
three tables before `push-pkg`. 8.3, run. used by: `push` step 1.

**P-2.4 A package SQL script reinstalls on `push-pkg` only when its `descriptor.json` `ModifiedOnUtc` changed;**
otherwise the old body stays and the log says installed. 8.3, build. used by: `push` `sql dates`; the same for
process metadata in S33-T01.

**P-2.5 An assembly package (Type 1):** when the configuration build fails on other packages' errors, `push-pkg` does
not rebuild the dll (new services 404, tests not found); `clio compile-package <Pkg>` fixes it; an old dll shows as
"Could not load type". 8.3, build. used by: `push` compile step.

**P-2.6 An assembly package does not see part of the configuration** (for example `Terrasoft.Mail.Sender`,
`MacrosHelperV2`); reflection or own code. 8.3, build. used by: the C# recipes (S29-T09).

**P-2.7 A data binding overwrites the site's value on install.** A `SysSettingsValue` binding set a production
setting back to its package value right after a deploy; system setting values in bindings are dangerous. 8.3,
run. used by: `push` binding check (S33-T01 narrows it to force-update columns), `sys_setting workspace=`.

**P-2.8 A package pulled from a site differs from git** in line endings (LF for CRLF) on almost every file, in
`descriptor.json` and `.csproj` dependencies (the site's, packages missing there disappear), and keeps resource
folders without schemas. 8.3, run. used by: `review_download`, `schema_diff`.

**P-2.9 Real packages hold empty `Data/*/data.json`, `Data` folders without a descriptor, `.cs` in cp1251;**
indexers must survive them. source. used by: `index.py`, `bindings_of` (S25).

**P-2.10 Classic page metadata:** the designer-written sections are marked `/**SCHEMA_DETAILS*/`,
`/**SCHEMA_BUSINESS_RULES*/`, `/**SCHEMA_DIFF*/`; attributes, methods and messages are hand-written. source.
used by: `classicui` writers.

**P-2.11 Freedom page rules live in the addon `<Page>BusinessRule`**, metadata in the diff form (`= + - ~`).
source. used by: `rules` toolkit, `about` topic.

**P-2.12 Object metadata is the diff form** (`+ MetaData.Schema.D2 {...}`), a column's name is `A2` with its UId
beside it. source. used by: `entity/schema.py`.

**P-2.13 A data binding is installed by `push-pkg` only when its descriptor `ModifiedOnUtc` differs from the
site's `SysPackageSchemaData.ModifiedOn`** (an older date counts too); a changed `data.json` under an unchanged
date is not applied. Applied, it rewrites the force-update columns of an existing row and keeps the site's
value in the others; `SysPackageSchemaData.ModifiedOn` follows the descriptor. 8.3, run (S33-T01, five pushes
of the test package). used by: `push` bindings check and binding dates.

## Data, rights, settings

**P-3.1 Role membership:** `SysUserInRole` holds direct members only; the closure (nested roles, org structure) is
`SysAdminUnitInRole` (`SysAdminUnitId`, `SysAdminUnitRoleId`); users are `SysAdminUnit` with
`SysAdminUnitTypeValue = 4`. 8.3, sql + source. used by: `role_members`, `user_roles`, `role_diff`.

**P-3.2 There is no `SysFuncRoleId` column** on this version; the columns of `SysFuncRoleInOrgRole` are `FuncRoleId`
and `OrgRoleId`. 8.3, sql. used by: `access.py` (S25).

**P-3.3 `SysSettings.GetValue` in C# is written with its full name** `Terrasoft.Core.Configuration.SysSettings`: an
entity of the same name exists in `Terrasoft.Configuration`. build. used by: the C# style guide, `HowToReadAndWriteSysSettings`.

**P-3.4 Licensed objects refuse a write from an unlicensed user** (`LicException`); a write through
`SystemUserConnection` passes; the standard "Add data" step did not check the licence. 8.3, run. used by: `HowToUseSystemUserConnection`.

**P-3.5 `SetColumnValue` for a lookup takes `<Name>Id`**, otherwise the value is not saved. build. used by:
`HowToUpdateRecordWithESQ`, the C# style guide.

**P-3.6 `Contact.Email` may be empty while `ContactCommunication` holds a primary email.** 8.3, sql. used by: -.

**P-3.7 A new boolean column gets the database default (false) on existing rows**, not a value from logic. 8.3,
run. used by: `objects` add-column note.

**P-3.8 Approvals are `SysApproval`** (`EntityId`, `IsCanceled`, a status lookup); a client's own approval tables
exist beside it and processes cancel them independently. 8.3, sql + source. used by: -.

**P-3.9 `ModifiedOn` of records and `SysProcessLog.StartDate` share one zone and agree to the second;** the user
sees their own zone, so a search window must be converted or the log looks empty. 8.3, sql. used by:
`records.local_time`, `process_runs` `time_zone`.

**P-B1 An ESQ on a column that does not exist on this site fails the whole query**
(`ItemNotFoundException: column at path X not found in schema Y`), including every message built from it. The
usual cause: a designer column in a package of one site only, never exported. 8.3, run + sql. used by:
`diff against env` (S22-T04), `index --env` (S31-T10), `HowToGuardESQAgainstMissingColumn`. The guard:
`esq.RootSchema.FindSchemaColumnByPath(path)` returns `null` for a missing path (one level or a lookup path), and
`GetSchemaColumnByPath` throws `ItemNotFoundException` - 8.3.2, run: an `EntitySchema` built over the local
`Terrasoft.Core.dll`, both methods called (2026-11-21, was N-1).

**P-B2 `SysSchemaSource` of a source-code schema has two rows:** `<Name>Schema.cs` (the generated class) and
`<Name>.cs` (the code). Check `<Name>.cs`. 8.3, sql. used by: `push` script compile, `verify_pushed` (S33-T05).

**P-B3 `SysSchema` has no compile-status column** (`Id, UId, Name, SysPackageId, ManagerName, MetaData, Checksum,
IsChanged, LastError, MetaDataModifiedOn, StructureModifiedOn, Descriptor, IsNetStandard, ...`); "published"
cannot be read from it, `LastError` was empty during P-A4. 8.3, sql. used by: `push`, `schema_layers`.

**P-B4 The database `TimeZone` is UTC and `CreatedOn` is stored in UTC.** 8.3, sql. used by: `records.py`.

## PostgreSQL

**P-4.1 Identifiers are case-sensitive:** unquoted `UsrOrder` becomes `usrorder` (`relation does not exist`); quote
every table and column. sql. used by: `env_sql` docs, `integrity.py`, the SQL recipes.

**P-4.2 `pg_trgm`, `fuzzystrmatch`, `unaccent` are available on PG 16** and installed by `CREATE EXTENSION IF NOT
EXISTS` from a BeforePackage SQL script. run. used by: `sqlscripts` recipes.

**P-4.3 `unaccent()` is STABLE, not usable in an index;** an IMMUTABLE wrapper over the dictionary
(`public.unaccent('public.unaccent'::regdictionary, $1)`) is. run. used by: `HowToUseCustomQueryFunction`.

**P-4.4 `Func.CustomFunction("name", ...)` in ESQ generates `public.name(...)` itself;** passing `public.name` gives
`public.public.name`. run. used by: `HowToUseCustomQueryFunction`.

**P-4.5 `CustomQueryFunction` is an `IQueryColumnExpressionConvertible`, not a `QueryColumnExpression`;** the type
error appears only at build. build. used by: the ESQ recipes.

## OData 4

**P-5.1 `$select` names a lookup as `<Column>Id`; `$filter` uses the path `<Column>/Id`.** `<Column>Id` in a
filter gives 500 "column at path not found", wrapped in an `ObjectContent` serialisation error. 8.3, run. used by:
`env_odata`, `Environment.odata`, the DSL `check-record` filters.

**P-5.2 An OData insert runs the object's logic** (listeners, signal processes) as a UI save; a listener may reset a
column on insert (set it with a separate PATCH); required columns are checked. 8.3, run. used by: the tester
skill, `seed` as the way around it (S34-T08).

**P-5.3 Deleting test records:** OData DELETE as the user; rows with a foreign key to the record first. 8.3, run.
used by: the DSL `delete`, `cases_from_package` cleanup.

**P-5.4 Multi-line values come back in JSON raw;** strict parsers fail. 8.3, run. used by: `clio.py` strict=False.

## Services and calls

**P-6.1 REST and WCF need the login cookies and the `BPMCSRF` token;** a WCF error is an HTML page with the exception
inside; `ProcessEngineService.svc/<Process>/Execute?ResultParameterName=...` answers a JSON string inside XML. 8.3,
run. used by: `Environment`, `env_call`, `run_process`.

**P-6.2 A process over HTTP:** GET `ServerModel/ProcessEngineService.svc/<Process>/Execute?<Param>=<v>&ResultParameterName=<p>`
(the path is `ServiceModel/...`). 8.3, run. used by: `run_process`, `run_tests`.

**P-6.3 Server-to-browser messages are `Terrasoft.ServerChannel`, event `ON_MESSAGE`, with a `Sender`.** 8.3, run.
used by: `who_reads_message` (S33-T02), Classic recipes.

**P-6.4 A page that calls `init()` again from a server-message handler duplicates its sandbox and ServerChannel
subscriptions.** source. used by: `page_audit` (a candidate line), Classic recipes.

## Classic UI (7.x) DOM and model

**P-7 (one fact, many lines; 8.3 Shell, run unless marked).** No iframe: `/0/Nui/ViewModule.aspx#...` redirects to
`/0/Shell/#CardModuleV2/<Schema>/...`, a new record is `#CardModuleV2/<Schema>/add`; the loading mask is
`#loading-animation` (about 5 s). Control ids `{Schema}{DiffName}{Control}-el` / `-wrap`, label `{Schema}{Name}Label`;
control types `TextEdit`, `MemoEdit`, `IntegerEdit`, `FloatEdit` (also for Money), `DateEdit` + `TimeEdit` under one
name for DateTime, `CheckBoxEdit` (a hidden native input: a plain click does not work), `ComboBoxEdit`, `LookupEdit`.
State: `t-label-is-required`, `base-edit-disabled` on `-wrap` with `readonly` on the input, `t-btn-disabled`.
Model: `Ext.getCmp(<id without -el>)` gives `$className`, `enabled`, `isRequired`, `bindings.value.modelItem`;
`model.get(col)` is typed (Date, number, `{value, displayValue}`). Culture from `Terrasoft.Resources.CultureSettings`
(`d.m.Y`, `G:i`, decimal `,`, thousands space; input accepts `,` and `.`). A value commits on `change` (focus out).
Dropdowns render `div.listview` at the end of `body` with `li[data-value][data-item-marker]`; `LookupEdit` searches
on `keyup` (`searchDelay` 500), so text inserted without key events does not search; Enter opens the selection
window. Tabs `li[data-item-index=N]` in `#{Schema}TabsTabPanel-tabpanel-items`, active `ts-tabpanel-active-item`, N
is the position in `TabsCollection` (hidden tabs skip indexes), visited tabs stay in the DOM. Details
`{DetailSchema}Container`, grid `grid-{DetailSchema}DataGridGrid-wrap` (`grid-empty`; inline-editable ones
`configuration-grid`), rows `div.grid-listed-row[data-item-marker]`, component `{DetailSchema}DataGridGrid`
(`collection.getCount()`, `columnsConfig`), add button `{DetailSchema}AddRecordButtonButton-wrapperEl`; details and
the action panel load after the fields. Toolbar buttons: `[data-item-marker="SaveButton"]` is reliable, the id form
not always. A dirty card hides `CloseButton` and shows `SaveButton` and `CancelButton`. DCM:
`Terrasoft.controls.BaseStageControl`, id `SectionActionsDashboardActionsControlContainer`, stages
`.stage-item[data-item-marker]` with `stage-current` / `stage-passed`, sub-stages in a menu rendered in `body`;
a stage click runs `ValidateCard` then `saveMasterEntity`: **a stage change is a database write**. MessageBox
`.ts-messagebox-box`, buttons `span.t-btn-wrapper[data-item-marker="OK"]` (captions upper-cased by CSS). A
zero-width field is in the DOM but not visible. Business rules in the schema code (source): `ruleType` 0 =
BINDPARAMETER (`property` 0 visible, 1 enabled, 2 required), 1 = FILTRATION, 3 = set value. The AMD module variable
(`currentModule`) is shared by every instance of the page in the session (source). A mixin is `Ext.define` plus
`<Schema>Resources`; the 8.x pages' own modal windows are Freedom `mat-dialog-container` /
`.cdk-overlay-pane.modal-container`. used by: the framework's `Frontend/Classic` (S29-T08 brings the rest in),
`docs/dsl.md`, S34-T02 dialogs.

## Freedom UI (8.x)

**P-8.1 `sdk.Model.load({primaryColumnValue})` does not filter** and returns every row; filter by Id through a
`FilterGroup`. 8.3, run. used by: the remote-module recipes.

**P-8.2 A "page" built from copied HTML inside a Classic dialog runs none of the real page's rules and validations.**
source. used by: -.

**P-C1 `Model.create('<Entity>')` then `model.load({attributes: [...]})` from an Angular element** returns rows as
plain objects keyed by attribute; only text columns and the no-filter call were exercised (N-3). 8.3, run.

**P-C2 A plain `href` inside the element's shadow DOM navigates the Shell** to `#Section/<ListPage>` in the same
tab. 8.3, run.

**P-C3 A page resource string is an input of a custom element** (`"linkCaption": "#ResourceString(Key)#"`) when both
exist: the `B2` entry in the page's `metadata.json` diff (UId in the order line too) and `LocalizableStrings.Key.Value`
in `Resources/<Page>.ClientUnit/resource.<culture>.xml`. 8.3, run. used by: `pages.py set-value` (S29-T07).

**P-C4 A designer list page with every standard element removed keeps `SectionContentWrapper`;** an element with
`parentName: SectionContentWrapper, propertyName: items` renders full width under the title, no `layoutConfig`.
8.3, run. used by: the remote-module recipes.

**P-C5 `:host { width: 100% }` with a padding overflows the parent;** `box-sizing: border-box` on `:host` fixes it.
run. used by: the remote-module recipes.

**P-C6 The devkit typings (`@creatio-devkit/common` 0.822) do not describe `model.load` options** (`ɵ` re-exports
of `@creatio/base`, not shipped). source. used by: -.

## clio

**P-9.1 `execute-sql-script` on a SQL error prints `<SQLSTATE>: <text>` and `Done` with exit 0;** a parser that
looks for `[ERR]` only misses it. run. used by: `environment.sql_failed` (`_SQLSTATE_RE`).

**P-9.2 Several statements in one file give one row counter.** run. used by: `Environment.sql` (one call per
statement), S33-T03.

**P-9.3 The table output wraps wide columns;** `-v csv -d <file>` or `substr` / `md5` in SQL. run. used by:
`Environment.sql` (`-v json -d`), `schema_layers` md5.

**P-9.4 From PowerShell the double quotes of inline SQL are lost;** SQL in a file with `-f` is reliable. run. used
by: `Environment.sql` file form.

**P-9.5 `-d <file>` wrote nothing on some queries** while the same SQL without `-d` worked; cause unknown (N-11).
used by: S33-T01 "drift not checked".

**P-9.6 `push-pkg` prints noise on success** (an HTML 500 page, `AppInfoValidator`, "Error while saving the metadata
of application ...", "Cannot combine app info"); exit code always 0. run. used by: `push` step parsing.

**P-9.7 `compile-package --wait` is not accepted by the installed clio** (prints help); without it works. run. used
by: `push` compile step.

**P-9.8 `last-compilation-log` shows `Terrasoft.Configuration` only, other packages' errors included.** run. used
by: `push` compile log check.

**P-D2 Git Bash rewrites an argument starting with `/`** (`/0/Shell/...` becomes a Windows path); pass the full URL
or `MSYS_NO_PATHCONV=1`. run. used by: `docs/dsl.md`.

**P-D3 UTF-8 Cyrillic literals in a SQL script file are stored correctly;** only the console output may look
garbled. run. used by: S33-T09.

**P-D4 `clio restart` may be blocked by the agent's permission policy;** plan for a person to restart. used by:
the author skill.

## Windows and Git Bash

**P-10.1 `python` may be the Microsoft Store stub;** `py` sometimes answers "Permission denied" and a retry works;
a direct interpreter path always works. used by: S33-T09, `agent_setup.py`.

**P-10.2 Byte damage:** a heredoc in Git Bash loses backslashes, `sed -i` strips CRLF, Python output in cp1251
fails on Cyrillic without `PYTHONUTF8=1`. used by: the agents' briefs, S33-T01 (CRLF kept), S33-T09.

**P-10.3 Git:** GitHub Desktop stashes on a branch switch; `git stash` on a clean tree saves nothing and the next
`stash pop` applies and drops someone else's stash. used by: the agents' briefs (the agents never run git).

## Integrations and queues

**P-11.1 A static `HttpClient` for the whole application process** shares timeouts and headers across every call.
source. used by: `RestClient`, the C# style guide.

**P-11.2 A database queue with no retry limit under a per-minute timer** produced tens of millions of attempts over a
few thousand rows and millions of external requests a day; a retry limit and closing unrecoverable errors are
mandatory. run. used by: `HowToDrainQueueTableWithAttemptLimit`, the C# style guide.

**P-11.3 An in-memory C# queue with a Quartz worker loses its content on an application restart;** dedupe by key
and a 60 s window. source. used by: `HowToDrainQueueTableWithAttemptLimit`, the C# style guide.

## Not verified (do not turn into recipes as they stand)

| Id | Claim | Owner | The check that would verify it |
|---|---|---|---|
| N-2 | `HandlerChainService.instance.process({type: 'crt.UpdateRecordRequest', ...})` from a remote element without `$context` | middle | one case line on the test site |
| N-3 | `model.load` with a `FilterGroup` from a remote element; lookup values as `{value, displayValue}` | middle | one case line on the test site |
| N-4 | the Freedom record URL `#Card/<FormPage>/edit/<Id>` from a remote element | middle | one case line on the test site |
| N-5 | a row in `SysProcessDisabled` stops a process | senior | a process case on the test site |
| N-6 | `SysSchema.ModifiedOn` changes on `push-pkg` (seen for a process, not for other schemas); check a push by md5 of the body | senior | S33-T05 `verify_pushed` |
| N-7 | ReadData with an empty filter reads an arbitrary row | middle | a process case on the test site |
| N-8 | the "record changed" signal does not fire on an insert that already holds the value | middle | a process case on the test site |
| N-9 | per-minute timer runs overlap when the previous run has not finished | senior | a log reading on the test site |
| N-10 | why `SysSchema.Caption` of a process stayed old after a resource push | senior | S33-T05 |
| N-11 | why `clio execute-sql-script -d <file>` wrote nothing on some queries | senior | S33-T01 drift step |
| N-12 | a binding row the site lacks is not inserted by `push-pkg` (seen on `SysModuleInWorkplace` only, five pushes) | senior | one binding of a fresh `UsrTest_` row pushed to the test site, S33-T05 |
| N-13 | after a new entity the OData controller `/0/odata/<Entity>` is rebuilt asynchronously (1-2 min): a 404 right after the push is expected, not a failure (clio core-rules, docs) | senior | a push of a new object, then OData reads every 15 s on the test site |
| N-14 | the core serialises compilation per environment and rejects a second concurrent compile; a restart mid-compile breaks it (clio core-rules, docs) | senior | two `compile` calls in a row on the test site |
| N-15 | the compilation history gets one row per project as each build ends; the application reloads about two minutes after the last row; a restarted instance warms up 1-10 minutes (clio core-rules-details, docs) | senior | `compile-status` polling against `SysCompilationHistory` on the test site |
| N-16 | a `process-name` compile of a business process reloads the configuration on .NET Framework only; on a .NET host it reloads nothing (clio core-rules, docs) | senior | the test site is .NET Framework: a `compile-package` after a script change, then a run without restart |
| N-17 | an `en-US` caption with non-Latin text is rejected by the platform (clio core-rules, docs) | middle | `objects.py column caption` with a Cyrillic en-US, push, read the error |
| N-18 | `SysProcessLog` times can be the environment user's local time marked `Z` (clio core-rules-details, docs) | middle | one process run, `process_runs` against the site clock |
| N-19 | OData rejects a row with an `Edm.Stream` column (`SysFile.Data`, `SysImage.Data`) before writing; a foreign-key rejection can come from an entity event handler, not the mapping (clio core-rules-details, docs) | middle | a backend case on the test site |
| N-20 | an Interface Designer save keeps only the code inside the five markers of a Freedom UI page; helpers above `return` disappear (clio routing, docs) | middle | a page with a helper, one Designer save on the test site, `schema_diff` |
| N-21 | `HandlerChainService.instance.process` without `scopes: [...request.scopes]` does not reach the page's own handlers (clio page-schema-handlers, docs; measured by clio on a newer build) | middle | one case line on the test site, 8.3 |
| N-22 | `entity.Validating` + `EntityValidationMessage` from a listener aborts the save and shows the text in Freedom UI and over OData; a thrown exception shows differently (clio entity-event-listener, docs; the kit's recipe throws) | senior | a listener on `UsrOrder` on the test site, a UI case and a backend case (S40-T05) |
| N-23 | a `SysSettingsValue_<Code>` binding with `IsForceUpdate` false does not overwrite a site value (clio sys-settings, docs); P-2.7 saw an overwrite | senior | a setting pushed twice with a changed site value on the test site (S40-T05) |
| N-24 | a process with add / modify data elements and no script runs without a compile (clio process-modeling, docs); the kit saw "Publish the process before starting it" for one pushed as files on 8.2.3 (P-A4 is about a script) | senior | a script-free process pushed to the test site, run without compile (S40-T05) |
| N-25 | `push-pkg` inserts a bound row the target lacks (clio data-bindings, verified by clio on a second environment); N-12 saw one not inserted | senior | the N-12 check (S40-T05) |
| N-26 | an ESQ lookup filter takes the logical lookup name (`UsrOwner`) with a `Guid` and resolves `UsrOwnerId` itself (clio esq-filters-backend, docs); the kit's recipes filter by `<Name>Id` | middle | one ESQ in a unit test against the site (S40-T05) |
