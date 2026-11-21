"""
MCP server exposing the Creatio knowledge base.

All the indexing and ranking lives in kb_index.py; this file is only the MCP
transport plus the tool descriptions the model reads.

Run directly for stdio:  python server.py
"""

from __future__ import annotations

import os
import json
from pathlib import Path

# The SDK renamed FastMCP to MCPServer in mcp 2.0. Both expose the same .tool()
# decorator and .run(), so one shim covers either version.
try:
    from mcp.server.mcpserver import MCPServer as _Server  # mcp >= 2.0
except ImportError:  # pragma: no cover - older SDK
    from mcp.server.fastmcp import FastMCP as _Server  # mcp 1.x

import tool_stats as stats_log
from kb_index import KnowledgeBase, default_root, recipe_part

mcp = _Server(
    "creatio-kb",
    instructions=(
        "Curated Creatio development recipes for this solution: Classic UI (7.x) "
        "pages, details and sections, Freedom UI (8.x) pages and Angular remote "
        "modules, Mobile SDK handler modules, and C# server code. "
        "Search this knowledge base BEFORE writing Creatio code - it carries the "
        "project's idioms, naming rules and known traps that general knowledge "
        "does not have. Start with search_recipes, then get_recipe for the full "
        "example. Before writing code read get_code_style: guide='csharp' for C#, "
        "guide='frontend' for Classic UI, Freedom UI, remote modules and mobile - the "
        "formatting, naming and architecture rules of Creatio platform code. "
        "The Clio area covers the clio CLI (packages, SQL, schemas, pages, apps, "
        "rights, its own MCP server): search_recipes(query, area='Clio') finds the "
        "block skill and the command reference; get_recipe('execute-sql-script') "
        "returns a command's full syntax, options and examples; get_recipe("
        "'clio-sql-and-data') returns the block's workflow and verified traps."
    ),
)

_register = mcp.tool


def _counted_tool(*args, **kwargs):
    """`mcp.tool()` with every tool's call logged (tool_stats.py: names and sizes, never values); the one place tools are registered."""
    decorate = _register(*args, **kwargs)
    return lambda fn: decorate(stats_log.instrument(fn))


mcp.tool = _counted_tool

_ROOT: Path = default_root()
_KB: KnowledgeBase | None = None
_FINGERPRINT: tuple[int, float] | None = None


def _fingerprint(root: Path) -> tuple[int, float]:
    """Cheap staleness check: file count plus the newest mtime."""
    count = 0
    newest = 0.0
    for sub in ("code", "no-code"):
        base = root / sub
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in (".js", ".ts", ".cs", ".sql", ".md"):
                count += 1
                newest = max(newest, path.stat().st_mtime)
    return count, newest


def kb() -> KnowledgeBase:
    """Return the index, rebuilding it when the knowledge base changed on disk."""
    global _KB, _FINGERPRINT
    current = _fingerprint(_ROOT)
    if _KB is None or current != _FINGERPRINT:
        _KB = KnowledgeBase(_ROOT)
        _FINGERPRINT = current
    return _KB


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


@mcp.tool()
def kb_overview() -> str:
    """
    Map of the Creatio knowledge base: areas, topics and how many recipes each holds.

    Call this first when you do not know what the knowledge base covers. For a
    concrete task, go straight to search_recipes instead.
    """
    base = kb()
    lines = [f"Creatio knowledge base at {base.root}", f"{len(base.recipes)} recipes.", ""]
    for area, topics in base.areas().items():
        lines.append(f"{area} ({sum(topics.values())})")
        for topic, count in topics.items():
            lines.append(f"   {count:>3}  {topic}")
        lines.append("")
    lines.append(
        "Areas: ClassicUI (Creatio 7.x pages, details, sections), "
        "FreedomUI (8.x pages), RemoteModule (Angular custom view elements), "
        "Mobile (Mobile SDK handler modules), Backend (C# server code), SQL, "
        "Clio (the clio CLI: one skill per functional block at the root and one "
        "reference page per command under reference/), "
        "Tools (tools/<name> - the file toolkits that build processes, business "
        "rules, objects and SQL scripts as package files). "
        "RemoteModule and Mobile recipes each sit next to a copyable project "
        "folder named in the recipe header."
    )
    return "\n".join(lines)


@mcp.tool()
def search_recipes(query: str, area: str = "", limit: int = 8) -> str:
    """
    Find knowledge base recipes for a Creatio task, by keyword or by symptom.

    ALWAYS call this before writing Creatio code - the recipes carry the exact
    idioms, the naming rules and the known traps for this codebase, which are not
    guessable from general knowledge.

    query: what you are trying to do, in plain words or as an API name.
           Examples: "filter a lookup field", "run a business process",
           "crt.OpenLookupPageRequest", "make a detail editable",
           "execute sql script", "push package to environment".
    area:  optional filter - "ClassicUI", "FreedomUI", "RemoteModule", "Mobile",
           "Backend", "SQL", "Clio" (the clio CLI and its MCP server) or "Tools"
           (the file toolkits: objects, process, rules, pages, data, push ...).
           Leave empty to search everything; Classic UI and Freedom UI often have
           a recipe each for the same task, and seeing both tells you which UI
           generation the answer belongs to.
    limit: how many results (default 8).

    Returns a ranked list of ids with titles and summaries. Read a full recipe
    with get_recipe.
    """
    base = kb()
    results = base.search(query, area=area or None, limit=max(1, min(limit, 25)))
    if not results:
        return (
            f'No recipe matched "{query}"'
            + (f" in area {area}" if area else "")
            + ".\nTry fewer or more general words, or call kb_overview to see what exists."
        )

    lines = [f'{len(results)} recipe(s) for "{query}"' + (f" in {area}" if area else "") + ":", ""]
    for recipe, score in results:
        lines.append(f"[{recipe.area}] {recipe.id}   (score {score:.1f})")
        lines.append(f"    {recipe.title}")
        summary = recipe.summary(300)
        if summary:
            lines.append(f"    {summary}")
        lines.append("")
    lines.append("Use get_recipe(<id>) to read the full recipe with its code.")
    return "\n".join(lines)


@mcp.tool()
def get_recipe(recipe_id: str, part: str = "all") -> str:
    """
    Return the text of one recipe: the explanation header and the runnable code.

    part: `all` (default, the whole file), `traps` (only the header lines that start with Trap / Do not /
          Verified / Gap - ask for this FIRST, before writing code of that kind), `summary` (the header block, or
          the text before the first `##` of a .md recipe), `code` (the code without the header, or the fenced blocks).

    recipe_id: the id from search_recipes, for example
               "Frontend/ClassicUI/Fields/HowToFilterLookupField".
               A bare file name is accepted when it is unambiguous; for clio a
               command name ("execute-sql-script"), a block skill name
               ("clio-sql-and-data") or a file toolkit ("tools/objects",
               "tools/pages", "tools/process", "tools/rules", "tools/sqlscripts",
               "tools/dcm", "tools/usertask", "tools/data", "tools/classicui", "tools/resources",
               "tools/scaffold", "tools/describe", "tools/push", "tools/uitests")
               works directly.

    The code is a template, not a drop-in: schema names, column names and the
    generated attribute suffixes (PDS_Name_a1b2c3d) must be replaced with the
    real ones from the project.
    """
    base = kb()
    recipe = base.get(recipe_id)
    if recipe is None:
        twins = base.same_name(recipe_id)
        if twins:
            lines = [f'"{recipe_id}" exists in more than one area. Pick one:', ""]
            lines += [f"[{r.area}] {r.id}" for r in twins]
            return "\n".join(lines)
        return (
            f'No recipe with id "{recipe_id}". '
            "Use search_recipes to find the right id."
        )
    header = (
        f"# {recipe.title}\n"
        f"area: {recipe.area}"
        + (f" / {recipe.topic}" if recipe.topic else "")
        + f"\nfile: {recipe.rel_path}\n"
        + "-" * 70
        + "\n"
    )
    try:
        return header + recipe_part(recipe, part)
    except ValueError as e:
        return f"error: {e}"


@mcp.tool()
def find_api(symbol: str, limit: int = 10) -> str:
    """
    Reverse lookup: which recipes use a given Creatio API symbol.

    Use this when you already have a symbol in hand and want to see it used
    correctly - from a code review, an error message, or existing project code.

    symbol: an API name such as "crt.OpenLookupPageRequest", "EntitySchemaQuery",
            "UseAdminRights", "LookupMultiAddMixin", "ProcessModuleUtilities".
            A bare name also matches a dotted one ("OpenLookupPageRequest" finds
            "crt.OpenLookupPageRequest").

    Returns the recipes that mention it, the most frequent user first.
    """
    base = kb()
    hits = base.find_api(symbol, limit=max(1, min(limit, 25)))
    if not hits:
        return (
            f'No recipe mentions "{symbol}". '
            "It may be spelled differently - try search_recipes with a description instead."
        )
    lines = [f'Recipes using "{symbol}":', ""]
    for recipe, count in hits:
        lines.append(f"[{recipe.area}] {recipe.id}   ({count} mention(s))")
        lines.append(f"    {recipe.title}")
    lines.append("")
    lines.append("Use get_recipe(<id>) to read one.")
    return "\n".join(lines)


@mcp.tool()
def list_recipes(area: str = "", topic: str = "") -> str:
    """
    Browse recipe ids and titles, optionally narrowed to an area and a topic.

    area:  "ClassicUI", "FreedomUI", "RemoteModule", "Mobile", "Backend", "SQL", "Clio" or "Tools".
    topic: a folder inside the area, e.g. "Details", "BaseMethods", "ESQ",
           "reference" (clio command pages; the block skills sit at the root).
           Call kb_overview to see the available topics.

    Prefer search_recipes when you have a task in mind; this tool is for
    surveying what exists.
    """
    base = kb()
    items = base.list(area=area or None, topic=topic or None)
    if not items:
        return (
            "Nothing matched"
            + (f" area={area}" if area else "")
            + (f" topic={topic}" if topic else "")
            + ". Call kb_overview to see the available areas and topics."
        )
    lines = [f"{len(items)} recipe(s):", ""]
    for recipe in items:
        lines.append(f"[{recipe.area}] {recipe.id}")
        lines.append(f"    {recipe.title}")
    return "\n".join(lines)


@mcp.tool()
def get_code_style(section: str = "", guide: str = "csharp") -> str:
    """
    The code style and architecture guides of Creatio code, derived from the platform's own sources.

    guide="csharp" (default): back-end C# - formatting (tabs, CRLF, #region layout), naming, DI via
    [DefaultBinding], error handling, logging, concurrency, XML docs, a review checklist.
    guide="frontend": client code - Classic UI schemas (define, attributes, messages, methods, diff,
    business rules, JSDoc tags), Freedom UI schemas (viewConfigDiff, handlers, requests, validators,
    converters), the Angular remote modules and the mobile handler modules, a review checklist.

    Read the right guide BEFORE writing or reviewing Creatio code: recipes show WHAT to call;
    the guide says how the code must look.

    section: optional - a section number ("4") or words from its heading
             ("logging", "review checklist"). Empty returns the whole guide.
    """
    text = kb().code_style(section, guide)
    if text is None:
        return f"No {guide} guide next to the knowledge base (csharp = CREATIO_CODE_STYLE.md, frontend = CREATIO_FRONTEND_CODE_STYLE.md)."
    if not text:
        return f'No section matches "{section}". Call get_code_style() with no argument to see the headings.'
    return text


def _tools_path() -> None:
    import sys
    tools = str(_ROOT / "no-code" / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)


_tools_path()
from creatio_schemas.describe import DEFAULT_LIMIT  # noqa: E402


@mcp.tool()
def describe_package(package: str, kind: str = "", limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """
    What a Creatio package holds, one line per schema and SQL script: kind, name,
    caption, counts (columns, elements, rules, page elements) and the parent or the
    replaced base. Call this BEFORE reading any file of a package.

    package: the package folder, e.g. C:/work/packages/UsrPkg (a clio workspace package).
    kind:    optional filter - object, process, rules, page, sql, client, addon, source, csharp, dcm, user-task,
             data (the Data/<Name> bindings with the table they seed and their row counts; listed only when asked).
             C# files under Files/cs are listed as `csharp` by signatures (roles, method count); source code schemas as `source`.
    offset:  skip this many lines first - the tail `... N more; next: offset=<k>` of a cut answer says what to pass.
    """
    _tools_path()
    from creatio_schemas.describe import describe_package as _dp
    try:
        return _dp(package, kind, limit, offset)
    except (FileNotFoundError, KeyError, ValueError) as e:
        return f"error: {e}"


@mcp.tool()
def describe_schema(package: str, schema: str, limit: int = DEFAULT_LIMIT, offset: int = 0, env: str = "") -> str:
    """
    The summary of one schema - columns and flags of an object, elements, parameters
    and flows of a process, rules of a rule addon, elements and data sources of a
    Freedom UI page, engine and dependencies of a SQL script. 6x-40x fewer tokens than
    the schema's files. At most `limit` lines (0 = all); when cut, the last line says
    how many more there are - ask describe_item for the one part you need instead of
    raising the limit. `env=<clio name>` on a process names the lookup rows of its filters and set values that
    no data binding of the workspace holds (`UsrStatus = Done (0042909f-...)`), from the site: one read-only select
    per lookup table; `describe_item` takes the same `env=<name>` inside its query.
    """
    _tools_path()
    from creatio_schemas.describe import describe_schema as _ds
    try:
        return _ds(package, schema, limit, offset, env.strip() or None)
    except (FileNotFoundError, KeyError, ValueError) as e:
        return f"error: {e}"


@mcp.tool()
def describe_item(package: str, schema: str, query: str = "topics", limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """
    One part of a schema, chosen by a query "<topic> [<name>] [key=value ...]";
    "topics" lists what the schema can answer. Examples:
      object : "columns type=Lookup", "column UsrAmount", "flags", "base", "map" (columns by type with captions)
      process: "elements kind=FormulaTask", "element ReadOrders", "params", "flows from=Start",
               "script Calc" (the C# body of a script task, decoded - not the escaped CH1 in metadata.json); filters print a lookup
               row as its name when the workspace's bindings hold it, and with `env=<clio name>` (e.g. "elements env=dev") also the
               rows of base packages and hand-made ones, read from the site
      rules  : "rules", "rule <name>"
      dcm    : "stages", "stage Stage1", "steps stage=Stage1", "step DcmElement1", "moves from=Stage1", "filter"
      user task: "params", "param RecordId", "methods", "method InternalExecute", "source"
      data   : (a Data/<Name> binding) "columns", "rows limit=20 culture=en-US", "row <key>"
      classic: (a 7.x client schema) "diff op=insert", "element UsrTotal", "methods", "method onSaved", "messages",
               "attributes", "details", "find UsrTotal", "where UsrTotal" (caption, control, column with its caption, the
               parentName chain, the layout cell, the layer; a detail with its filter column), "where" alone (opens from / shown on),
               "map tab=UsrInfoTab" (the inserts as a captioned tree), "method init" (in every layer of the workspace, first to
               last, callParent marked; "method init env=dev" over the site's layers), "callers onSaveClick" (file:line across the
               workspace's client schemas), "outline" (attributes, messages, methods with lines)
      C#     : (schema name, or "Files/cs/X.cs" / "X.cs" / "X") "classes", "members UsrService kind=method visibility=public",
               "member UsrService.GetLabel" (one body), "usings", "regions", "operations" (ESQ, raw SQL, SysSettings,
               process start, HTTP ... with line numbers), "find GetTypedColumnValue"
      page   : "sections", "elements parent=SideAreaProfileContainer", "element UsrName",
               "attributes bound=true", "data-sources", "handlers", "handler crt.SaveRecordRequest",
               "validators", "converters", "containers", "find <text>", "map tab=GeneralInfoTab" (the page as a captioned tree), "about UsrStatus" (where + lookup target, rules, handlers
               with line numbers, validators, converters, the framework's cases), "where UsrName" (caption, type, control ->
               attribute -> column with its caption, the parent chain, the layer; culture=uk-UA, format=json),
               "where" alone (opens from: the section, the object, the record type or the default page, from the SysModuleEdit
               bindings; "where env=<clio name>" from the site's tables)
      any    : "files", "resources culture=uk-UA", "resource Caption", "missing culture=ru-RU from=en-US"
    Nothing is returned that was not asked for: a page is a database, this is the query.
    A list is cut at `limit` lines; `offset` (or `offset=40` in the query) continues after the lines already read: the tail of a page after
    the first says `... N more; next: offset=<k>`. A body (handler, member, method, script) takes `lines=10-40` or `around=<text> [n=8]`
    for a window with the body's line numbers; a body over 120 lines starts with a line that names those keys.
    """
    _tools_path()
    from creatio_schemas.describe import QueryError, describe_item as _di, parse_query
    try:
        if "limit" not in parse_query(query)[2]:
            query = f"{query} limit={limit}"
        if offset and "offset" not in parse_query(query)[2]:
            query = f"{query} offset={offset}"
        return _di(package, schema, query)
    except (FileNotFoundError, KeyError, ValueError, QueryError) as e:
        return f"error: {e.args[0] if e.args else e}"



@mcp.tool()
def index_workspace(path: str, rebuild: bool = False, stats: bool = False, env: str = "") -> str:
    """
    Build or refresh the package index - the project's knowledge-base file
    (<workspace>/.creatio-index/index.sqlite, one store for every package): for every schema its kind, caption,
    summary, files and the schemas it refers to. `path` is a clio workspace root, a
    packages folder or one package. The index checks itself against the disk on every
    describe_* / find_schema call, so run this only after a `clio pull-pkg` to see what
    changed, or with rebuild=True to start over. stats=True adds the store: size, format, FTS5, rows per table, per
    package its build time and unreadable count. With `paths.platform` in project.json it also reads the local platform
    install's captions once (the `platform <version>: N captions ...` line), the fallback of a base column's caption.
    env=<clio environment> (read-only SQL): also the site's columns of every object's table that the workspace does not
    define, with the package that defines each (`package not found` for a physical column) and its caption, and the site's
    schemas of the workspace's prefixes that no workspace package holds (UId clashes listed); `columns`, `map`,
    describe_schema, find_schema and resolve_caption show them until the next env pass. Run it first in a task that adds
    columns or objects.
    """
    _tools_path()
    from creatio_schemas.describe import index_workspace as _iw
    try:
        return _iw(path, rebuild, stats, env or None)
    except (FileNotFoundError, KeyError, ValueError) as e:
        return f"error: {e}"


@mcp.tool()
def list_lookups(path: str, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """
    Which lookup holds this status or type, with its values: every lookup object of a workspace or
    package - an object whose parent chain reaches
    BaseLookup, through the workspace's own objects or the stock ones - one line each:
    package, caption, parent chain, own columns, data bindings with the rows they bind,
    how many schemas refer to it. The starting list for de-duplication, binding-value
    checks and lookup clean-ups. `path` is a clio workspace root, a packages folder or one
    package. Objects whose parent is outside both the workspace and the stock list are
    reported separately as not decided. `offset` skips lines of each of the two lists.
    """
    _tools_path()
    from creatio_schemas.describe import lookups as _lk
    try:
        return _lk(path, limit, offset)
    except (FileNotFoundError, KeyError, ValueError) as e:
        return f"error: {e}"


@mcp.tool()
def resolve_caption(path: str, text: str, kind: str = "", culture: str = "", limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """
    The workspace by what the users call things: a caption (or a `Usr` name) in, the objects, pages, columns, page elements,
    process parameters and lookup values that carry it out, one line each, best match first (the whole caption, then a whole
    word, then a part; at equal match: object, page, column, element, parameter, lookup value). Call this FIRST on a task text
    that names things in business words ('Cash flow request', 'Date of request', the status 'Rejected'), then `describe_item` /
    `where` on the hit. `kind` narrows (object, page, column, element, parameter, lookup, process, rule); `culture` is another
    culture or `all` (default: each package's primary culture); lookup values are searched in the primary culture only (the index
    keeps each binding's first 40). No hit: `no caption holds "<text>"; closest: ...`. `path` is a workspace root or a package.
    """
    _tools_path()
    from creatio_schemas.describe import QueryError
    from creatio_schemas.describe.caption_search import resolve_caption as _resolve
    try:
        return _resolve(path, text, kind, culture, limit, offset)
    except (FileNotFoundError, KeyError, ValueError, QueryError) as e:
        return f"error: {e}"


@mcp.tool()
def find_schema(path: str, schema: str, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """
    Where a schema lives and what touches it, without searching: the package, kind,
    summary, every file with its absolute path, the schemas it refers to and the schemas
    and data bindings that refer to it (across the workspace). Call this before reading
    or changing a schema: it gives the files to open and the impact of the change.
    `path` is a clio workspace root, a packages folder or one package. `offset` skips lines of each list.
    """
    _tools_path()
    from creatio_schemas.describe import find_schema as _fs
    try:
        return _fs(path, schema, limit, offset)
    except (FileNotFoundError, KeyError, ValueError) as e:
        return f"error: {e}"


@mcp.tool()
def find_text(path: str, pattern: str, kind: str = "", context: int = 0, limit: int = DEFAULT_LIMIT) -> str:
    """
    A regex over the lines of every file the package index knows - the answer to "where
    is this text" without a Grep over raw schema files: one line per hit,
    `<Package>/<Item> (<kind>) <line>: <text>` (trimmed to 160 characters), `context`
    lines before and after each (`<line>- <text>`). `kind` keeps the items of one kind
    (object, page, process, rules, sql, csharp, data, ...); resource XML is skipped unless
    kind="resource", which searches only it. `path` is a clio workspace root, a packages
    folder or one package. Then describe_item on the schema it names.
    """
    _tools_path()
    from creatio_schemas.describe.index import find_text as _ft
    try:
        return _ft(path, pattern, kind, context, limit)
    except (FileNotFoundError, KeyError, ValueError) as e:
        return f"error: {e}"


@mcp.tool()
def schema_deps(path: str, schema: str, direction: str = "both", kind: str = "", via: str = "", limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """
    The typed dependency graph around one schema, from the workspace index: `depends on` (its
    parent, lookup columns, data sources, signals, sub-processes, details, mixins, bindings) and
    `dependents` (every object, process, page, DCM, rule, binding or C# listener of the workspace
    that builds on it). One line per edge: `<kind> <name>  <via>: <columns>  [ref]` - no `[ref]`
    means the metadata stores the UId; `[name]` means a name resolved in a context that names the
    object (a page's data source), and a column ending with `?` could not be shown on that object.
    Call it before changing an object or page to see the impact, and instead of grepping for who
    uses a schema. `direction` both | out | in; `kind` and `via` filter the edges (kind: object,
    process, page, dcm, rules, data, csharp; via: lookup, signal, data-source, detail, ...).
    `path` is a clio workspace root, a packages folder or one package. `offset` skips lines of each of the two lists.
    """
    _tools_path()
    from creatio_schemas.describe.deps import dependencies
    try:
        return dependencies(path, schema, direction, kind, via, limit, offset)
    except (FileNotFoundError, KeyError, ValueError) as e:
        return f"error: {e}"


@mcp.tool()
def schema_impact(path: str, schemas: str, tasks: str = "", current: str = "", md: bool = False, limit: int = DEFAULT_LIMIT, kind: str = "") -> str:
    """
    What a change to these schemas touches: every typed dependent (pages, processes, rules, DCM,
    bindings, listeners) of each schema, and - with `tasks` (the loop's tasks folder from
    project.json paths.tasks) - the other active task folders that change or depend on them, from
    their schemas.json. The author runs it while writing plan.md: `md=True` returns the `## Impact`
    table to paste and the `affects:` line for schemas.json; a `CONFLICT` means another active task
    changes a schema of this plan or one of its dependents - stop and ask the human. The tester
    reads `## Impact` to pick what to regression-test. `schemas` comma-separated; `current` this
    task's folder name (left out of the lock check). Ends with the counts.
    `kind` keeps only dependents of that kind (page, process, rules ...) when a lookup has too many.
    """
    _tools_path()
    from creatio_schemas.describe.deps import impact
    names = [s.strip() for s in schemas.split(",") if s.strip()]
    if not names:
        return "error: name at least one schema"
    try:
        text, conflicts = impact(path, names, tasks or None, current or None, md, limit, kind)
    except (FileNotFoundError, KeyError, ValueError) as e:
        return f"error: {e}"
    return text + f"\nexit code {1 if conflicts else 0}"


@mcp.tool()
def merge_plan(path: str, schemas: str = "", env: str = "", limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """What collapsing the replacing layers of a schema into one would do, without writing anything: per schema
    `<Schema> <kind>: <N> layers, target <package>` (the lowest package, every other layer's package depends on it),
    `layer <pkg>: +n columns / elements / methods` in the order the platform applies them, `siblings: ... (order
    guessed)` when two layers have no dependency between them, `conflict ...` lines (one column name with two UIds,
    one UId with two types, two layers changing one page element, one method overridden in two layers, a callParent
    in a callback or with its value used, a lookup to an object of a package above the target), `depends: <target>
    gains ...`; then `<M> schemas, <L> layers to remove, <C> conflicts` and the exit code (1 on a conflict).
    `schemas` comma-separated (default: every schema replaced by more than one package of the workspace); `env`
    (a clio environment) takes the layer order from the site instead of guessing it from DependsOn. Run it before
    planning a layer merge; safe on a client workspace (no index is written). `offset` skips lines of the plan."""
    _tools_path()
    from creatio_schemas.describe.merge import merge_plan as _plan
    try:
        text, conflicts = _plan(path, [s.strip() for s in schemas.split(",") if s.strip()] or None, _env(env) if env else None, limit, offset)
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"
    return text + f"\nexit code {1 if conflicts else 0}"


@mcp.tool()
def merge_layers(path: str, schema: str, target: str = "", env: str = "") -> str:
    """The replacing layers of one OBJECT or PAGE (Freedom or Classic) collapsed into one layer of the target package -
    printed, NEVER written: the merge plan lines, then `write <file>` / `delete <folder>` for each file, or `stopped: ...
    - nothing written` (a conflict, siblings whose order only the site knows, a site row that still points at a layer to
    remove, a Classic method that cannot fold). A page: its diff arrays concatenated in fold order, a Classic method in two
    layers folded into one (the upper body with the lower body in place of its callParent). `target`: the package to merge
    into (default the lowest layer's; every layer's package must depend on it). `env` (a clio environment) gives the
    site's layer order and runs the references check. To apply, the author runs `describe.py merge <workspace> <Schema>
    -e <env> --apply` and pushes the packages; prove it with schema_snapshot before and after."""
    _tools_path()
    from creatio_schemas.describe.merge import merge_schema
    try:
        text, code = merge_schema(path, schema, target or None, _env(env) if env else None, apply=False)
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"
    return text + f"\nexit code {code}"


@mcp.tool()
def merge_package(path: str, child: str, parent: str, env: str = "") -> str:
    """One CHILD package folded into its PARENT - printed, NEVER written: one line per item, `layer <kind> <Name> -> <parent>
    ... merge` for a schema both replace (merged through merge_layers' engines), `move <kind> <Name> -> <parent> uid kept` for
    what the child owns (processes, own objects and pages, bindings, SQL scripts, Files/cs), `depends <pkg>: DependsOn <child>
    -> <parent>` for the packages to redirect, `note` lines, and `stop` lines (a name clash, a Custom layer on the site, a rule
    layer in both) with `exit code 1`. `env` (a clio environment) adds the site's checks. To apply, the author runs
    `describe.py merge-package <workspace> <child> --into <parent> --apply`, pushes the PARENT FIRST (the moved schema rows keep
    their Id), then the redirected packages, and removes the child's application on the site."""
    _tools_path()
    from creatio_schemas.describe.package_merge import merge_package as _merge_package
    try:
        text, code = _merge_package(path, child, parent, _env(env) if env else None, apply=False)
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"
    return text + f"\nexit code {code}"


@mcp.tool()
def merge_run(path: str, child: str, parent: str, env: str, evidence: str) -> str:
    """The rehearsal of the whole package-merge procedure, NEVER merging or pushing: the plan (plan.txt), the baseline cases
    generated from the child (cases/) unless the folder has some, every case run on the site `env` (before/report.*; a red case
    stops), a snapshot of every object and page of the plan (before/<Schema>.snapshot), then `rehearsal: nothing written`. Evidence
    goes to the `evidence` folder; the last line is the first stop or the rehearsal line, `exit code` 1 on a stop. To merge, the
    author runs `describe.py merge-run <workspace> <child> --into <parent> -e <env> --evidence <folder> --apply`, removes the
    child's application when it pauses (exit 3), and reruns with `--continue` (compare, tests after)."""
    _tools_path()
    from creatio_schemas.describe.merge_run import Engines, merge_run as _run
    try:
        text, code = _run(path, child, parent, evidence, env, False, False, Engines(Path(path), env))
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"
    return text + f"\nexit code {code}"


@mcp.tool()
def push_package(package: str, env: str, probe: bool = False, dry_run: bool = False,
                 project: str = "", tasks: str = "", task: str = "", force: bool = False,
                 baseline: str = "", skip_drift: bool = False, skip_foreign_files: bool = False,
                 skip_sql_dates: bool = False, skip_compile_package: bool = False) -> str:
    """
    Install a package using push v2: check drift (schemas of the package modified on the
    environment after the package's last git commit, found through SysPackage) and dropped
    dependencies (DependsOn and csproj references present in git HEAD and gone now), check
    task ownership, update changed SQL dates, clear IsChanged (SysSchema, SysPackageSchemaData,
    SysPackageSqlScript), push-pkg and check compilation. Assembly packages are compiled
    with compile-package --wait. compile-configuration runs only for processes with script
    or user tasks and may take minutes. probe also checks objects and SQL scripts; dry_run
    prints commands without launching processes or writing files: it sends nothing to the environment.

    project and task select the current task for ownership checks; tasks overrides the
    project tasks folder. Without either tasks or project the ownership check is skipped.
    force, baseline and the skip flags have the same meaning as in the push CLI.

    The answer is one line per step (drift, package schemas, bindings with their count, process dates, compile,
    publish, probes) and `details: <file>` - the whole log, in the task folder when `task` is given. It stops when the
    install would delete schemas absent from the package (git HEAD or the site has them), and on a binding value in a
    force-update column the site holds otherwise (the install keeps the other columns); a changed process gets a new
    descriptor ModifiedOnUtc (the install regenerates it only then); a publish error comes back whole.
    """
    package = _package_path(package, project)
    if not package.strip() or not (Path(package) / "descriptor.json").is_file():
        return "error: package must be a folder with descriptor.json, or a package name found under the project's workspace (project.json paths.workspace) or the current folder's packages/"
    if not env.strip():
        return "error: env must not be empty"
    _tools_path()
    from creatio_schemas import push as _push
    lines: list[str] = []
    # the answer is the summary, the whole log a file (a dry run's answer is its commands)
    details = {} if dry_run else {"details": _push.details_path(Path(package), Path(task) if task else None)}
    try:
        code = _push.push(Path(package), env, _push.Clio(env), probe, dry_run, log=lines.append,
                          project=Path(project) if project else None, tasks=Path(tasks) if tasks else None,
                          task=Path(task) if task else None, force=force,
                          baseline=Path(baseline) if baseline else None, skip_drift=skip_drift,
                          skip_foreign_files=skip_foreign_files, skip_sql_dates=skip_sql_dates,
                          skip_compile_package=skip_compile_package, **details)
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        lines.append(f"error: {e.args[0] if e.args else e}")
        code = 2
    lines.append(f"exit code {code}")
    return "\n".join(lines)


def _package_path(package: str, project: str = "") -> str:
    """A package folder as given, or a package name looked up under the project's workspace (`paths.workspace` of
    project.json, relative to it) and then under the current folder (`packages/<name>`, `<name>`)."""
    if not package.strip() or (Path(package) / "descriptor.json").is_file():
        return package
    roots = [Path.cwd()]
    if project and Path(project).is_file():
        try:
            ws = (json.loads(Path(project).read_text(encoding="utf-8-sig")).get("paths") or {}).get("workspace")
        except ValueError:
            ws = None
        if ws:
            roots.insert(0, Path(project).resolve().parent / ws)
    for root in roots:
        for candidate in (root / "packages" / package, root / package):
            if (candidate / "descriptor.json").is_file():
                return str(candidate)
    return package


def _env(env: str):
    from creatio_schemas.environment import Environment
    if not env.strip():
        raise ValueError("env must be a clio environment name")
    return Environment.from_clio(env.strip())


@mcp.tool()
def env_sql(env: str, sql: str, limit: int = DEFAULT_LIMIT, out: str = "", write: bool = False) -> str:
    """Run SQL on a Creatio environment through clio and return the rows as JSON (one object per row). Several
    statements (`;` at a line end) run one by one and each answers under `-- statement k` with its own rows, or
    `affected: N` when it has none. A statement that is not select / with / show / explain is refused unless
    `write=true`; with it the answer ends with `affected: N`. `out=<file.csv>` writes every row of the last statement
    that returned rows (UTF-8 with BOM, `;`) and answers `N rows -> file` and the first five. Table and column names:
    `describe_table` first, not a guess. An `[ERR]` from the database comes back as `error: ...`."""
    import csv
    import json
    import re
    from creatio_schemas.describe import cut
    from creatio_schemas.environment import split_statements
    statements = split_statements(sql)
    bare = [re.sub(r"--[^\n]*|/\*.*?\*/", " ", st, flags=re.S).strip().lower() for st in statements]
    if not write and any(not re.match(r"(select|with|show|explain)\b", b) for b in bare):
        return "error: a writing statement needs write=true"
    answers, last_rows, affected = [], [], 0
    try:
        db = _env(env)
        for k, st in enumerate(statements, 1):
            counts = []
            rows = db.sql(st, counts=counts)
            if rows:
                last_rows = rows
            elif counts and isinstance(counts[0], int):
                affected += counts[0]
            answers.append((k, rows, counts[0] if counts else None))
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"
    lines = []
    for k, rows, n in answers:
        body = [json.dumps(r, ensure_ascii=False, default=str) for r in rows]
        if out and rows is last_rows:
            columns = list(dict.fromkeys(c for r in rows for c in r))
            path = Path(out)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8-sig", newline="") as fh:
                w = csv.writer(fh, delimiter=";", lineterminator="\n")
                w.writerow(columns)
                w.writerows([("" if r.get(c) is None else r.get(c)) for c in columns] for r in rows)
            body = [f"{len(rows)} rows -> {path}"] + body[:5]
        shown = cut(body, limit, "rows") if not (out and rows is last_rows) else body
        if len(answers) > 1:
            lines.append(f"-- statement {k}")
        lines += shown or [f"affected: {n}" if isinstance(n, int) else "(no rows)"]
    if write and affected:
        lines.append(f"affected: {affected}")
    return "\n".join(lines) or "(no rows)"


@mcp.tool()
def describe_table(env: str, table: str) -> str:
    """The real shape of a database table on a site, so no column name is guessed: one line per column
    (`name type[(length)] [null]`), then `primary key: ...` and `foreign key: <column> -> <table>.<column>`.
    Creatio table names are the object names (`UsrOrder`); a column of a lookup is `<Column>Id`. Read-only."""
    import re
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table or ""):
        return "error: give a table name (letters, digits, underscore)"
    from creatio_schemas.integrity import table_lines
    try:
        db = _env(env)
        lines = table_lines(db, table)
        if not lines:
            return f"no table {table} on the site (information_schema.columns is empty)"
        keys = db.sql('select kcu.column_name::text as "column", tc.constraint_type::text as "kind", ccu.table_name::text as "target", '
                      'ccu.column_name::text as "target_column" from information_schema.table_constraints tc '
                      'join information_schema.key_column_usage kcu on kcu.constraint_name = tc.constraint_name and kcu.table_schema = tc.table_schema '
                      'left join information_schema.constraint_column_usage ccu on ccu.constraint_name = tc.constraint_name and ccu.table_schema = tc.table_schema '
                      f"where tc.table_schema = current_schema() and tc.table_name = '{table}' and tc.constraint_type in ('PRIMARY KEY', 'FOREIGN KEY') order by 1")
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"
    out = [l.split(" ", 3)[3] for l in lines]  # `table T column <name> <type>...` -> `<name> <type>...`
    pk = [k["column"] for k in keys if k["kind"] == "PRIMARY KEY"]
    if pk:
        out.append("primary key: " + ", ".join(pk))
    out += [f"foreign key: {k['column']} -> {k['target']}.{k['target_column']}" for k in keys if k["kind"] == "FOREIGN KEY"]
    return "\n".join(out)


@mcp.tool()
def env_call(env: str, method: str, path: str, body: str = "") -> str:
    """Call a site path with login and CSRF: `rest/<Svc>/<Method>`, `ServiceModel/<Svc>.svc/<Method>`,
    `odata/<Entity>`, `ServiceModel/ProcessEngineService.svc/RunProcess`. `method` GET/POST/PATCH/DELETE, `body` a JSON
    text. Returns `status: N` and the JSON answer (a JSON string inside an XML answer is unwrapped), or
    `error: <status>: <reason>` with the reason taken from the WCF fault page. Writes whatever the call writes."""
    import http.client
    import json
    try:
        r = _env(env).request(method.upper(), path.lstrip("/"), json.loads(body) if body.strip() else None)
    except (OSError, KeyError, ValueError, RuntimeError, http.client.HTTPException) as e:
        return f"error: {e.args[0] if e.args else e}"
    if not r.ok:
        return f"error: {r.error}"
    answer = r.json()
    return f"status: {r.status}\n" + (json.dumps(answer, ensure_ascii=False, indent=2) if answer is not None else r.text.strip())


@mcp.tool()
def env_odata(env: str, entity: str, select: str = "", filter: str = "", top: int = 20) -> str:
    """Read records of an object through OData 4: `select` comma-separated columns (a lookup is `<Column>Id`),
    `filter` an OData expression (`Name eq 'x'`; a lookup is compared as `UsrContact eq <guid>` and sent as the path
    `UsrContact/Id eq <guid>`, the form the platform wants in a filter), at most `top` rows, as JSON - one object per line."""
    import json
    try:
        rows = _env(env).odata(entity, [c.strip() for c in select.split(",") if c.strip()] or None, filter or None, top)
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) or "(no rows)"


def _answer(env: str, work, limit: int = DEFAULT_LIMIT) -> str:
    """`work(Environment)` -> text, cut to `limit` lines; a failure is `error: ...`."""
    from creatio_schemas.describe import cut
    _tools_path()
    try:
        text = work(_env(env))
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"
    return "\n".join(cut(text.splitlines(), limit, "lines")) or "(nothing)"


@mcp.tool()
def run_process(env: str, process: str, params: str = "", results: str = "") -> str:
    """Start a business process on a clio environment (ProcessEngineService.svc/RunProcess) and read its run back in one
    answer: `ok` or `FAILED <reason>` with the process id, each result parameter, then the run's `SysProcessLog` row -
    status, start, end and the first line of the error (`process_error` gives the whole error and the element it stopped
    on). `params` is a JSON object (`{"OrderId": "<guid>", "Quantity": 3}`), `results` a comma list of result parameter
    names. Ends with `exit code 1` when the engine refused it or the run is not completed (failed, or still waiting).
    Runs the process: whatever it writes is written."""
    import json
    from creatio_schemas.runs import render_log
    try:
        values = json.loads(params) if params.strip() else {}
        if not isinstance(values, dict):
            raise ValueError("params must be a JSON object")
    except ValueError as e:
        return f"error: params: {e.args[0] if e.args else e}"
    names = [r.strip() for r in results.split(",") if r.strip()]

    def work(e):
        run = e.run_process(process.strip(), values, names)
        lines = [f"{process}: {'ok' if run['success'] else 'FAILED ' + str(run['error'])}  processId {run['processId'] or '-'}"]
        lines += [f"  {n} = {json.dumps(run['results'].get(n), ensure_ascii=False)}" for n in names]
        log = None
        if run["processId"]:
            try:
                log = e.process_log(run["processId"])
                lines.append(render_log(log, run["processId"]))
            except (ValueError, RuntimeError) as err:
                lines.append(f"log: not read - {err.args[0] if err.args else err}")
        return "\n".join(lines + [f"exit code {0 if run['success'] and (log is None or log['state'] == 'completed') else 1}"])

    return _answer(env, work)


@mcp.tool()
def process_runs(env: str, process: str = "", record: str = "", since: str = "", until: str = "", limit: int = 20,
                 window: int = 30, time_zone: str = "", noise: str = "", steps: bool = False) -> str:
    """What ran when this record changed (`record=UsrOrder:<id>`), or the runs of one process: the business-process runs of `SysProcessLog`, each with its start (UTC and `time_zone`), process, status,
    log id, owner and the first line of its error. `process` (name or UId - every copy of that schema) gives its newest
    `limit` runs; `record` (`<Entity>:<Id>`) gives every run that started within `window` seconds of a change of that
    record or of a row pointing at it (its details), oldest first - "what ran when the manager pressed the button".
    `since` / `until` (`2026-11-11T08:00`, UTC unless a zone is written) bound the start. `noise` (comma list of names or
    prefixes, as `project.json` `environment.noiseProcesses`) hides those processes with a line saying how many. `steps` prints
    under each run the elements it went through (`SysProcessElementLog`: caption, status, start .. end in UTC). A process with no run
    on a site whose `SysProcessLog` is empty answers `process logging is off`. Read-only."""
    from creatio_schemas.runs import process_runs as _runs, render_runs
    return _answer(env, lambda e: render_runs(_runs(e, process.strip() or None, record.strip() or None, since.strip() or None,
                                                    until.strip() or None, max(1, min(limit, 200)), max(0, window),
                                                    [n.strip() for n in noise.split(",") if n.strip()], time_zone or None, steps)))


@mcp.tool()
def process_timers(env: str, process: str, record: str = "", window: int = 30, time_zone: str = "") -> str:
    """The pending timers of a process (every copy of its schema), soonest first: the fire time in UTC and `time_zone`, the
    timer element's caption, its state, and the run and element ids. A timer is a Quartz trigger (`qrtz_triggers`) whose group is
    the id of the run's element in `SysProcessElementLog`; its time is .NET ticks, converted here. `record` (`<Entity>:<Id>`) keeps
    the runs that started within `window` seconds of a change of that record or of a row pointing at it. Read-only."""
    from creatio_schemas.runs import process_timers as _timers, render_timers
    return _answer(env, lambda e: render_timers(_timers(e, process.strip(), record.strip() or None, max(0, window), time_zone or None)))


@mcp.tool()
def fire_timer(env: str, process: str, record: str, project: str, timer: str = "", delay: int = 20, time_zone: str = "") -> str:
    """Moves one pending timer of the run around `record` (`<Entity>:<Id>`) to now + `delay` seconds, so the step after it can be
    checked without waiting a day: `update qrtz_triggers set next_fire_time = <ticks> where trigger_name = ... and job_group = <element id>`.
    WRITES to the site, and is refused unless `project` (a project.json path) marks the environment `"kind": "dev"` with a `clioName`
    equal to `env`: `refused: <env> is not a dev environment`. `timer` (a part of the element's caption, or its id) picks one when
    several timers wait. The only tool of this server that changes a site's scheduler."""
    from creatio_schemas.runs import fire_timer as _fire, render_fire

    def work(e):
        try:
            return render_fire(_fire(e, process.strip(), record.strip(), project.strip() or None, env, timer.strip(), max(0, delay), time_zone or None))
        except PermissionError as refusal:  # an OSError: _answer would print it as "error: ..."
            return str(refusal.args[0])

    return _answer(env, work)


@mcp.tool()
def process_error(env: str, log_id: str, time_zone: str = "") -> str:
    """One run's error in full (`SysProcessLog.ErrorDescription` without the platform's stack frames, the message chain
    kept) and the element it stopped on (`SysProcessElementLog`: caption, status, start). `log_id` is the id
    `process_runs` or `run_process` printed. Read-only."""
    from creatio_schemas.runs import process_error as _error, render_error
    return _answer(env, lambda e: render_error(_error(e, log_id.strip(), time_zone or None)))


@mcp.tool()
def find_record(env: str, id: str, objects: str = "", everywhere: bool = False, time_zone: str = "") -> str:
    """Which table holds this Id? Scans the base tables that have a uuid `Id` (`objects`, comma-separated names, first;
    the workspace's objects are the usual hint) in unions of 50 and stops at the first batch that holds it unless
    `everywhere`. Answers the table, the record's caption (Name, Caption, Title...), and the dates and authors of its
    creation and last change in UTC and `time_zone` (`+03:00` or an IANA name). Read-only."""
    from creatio_schemas.records import find_record as _find, render_hits
    return _answer(env, lambda e: render_hits(_find(e, id, [o.strip() for o in objects.split(",") if o.strip()], everywhere, time_zone or None)))


@mcp.tool()
def record_context(env: str, entity: str, id: str, columns: str = "", depth: int = 1, time_zone: str = "", limit: int = DEFAULT_LIMIT) -> str:
    """One record as the database holds it: its columns with every lookup named (`Name` of the referenced row, found
    through the foreign keys), then the tables that have a row pointing at it with the count and the first 20 rows.
    `columns` is a comma list with `*` wildcards (default: every column with a value); `depth` 0 the record only,
    1 + the rows pointing at it, 2 + their lookups named. Read-only."""
    from creatio_schemas.records import record_context as _context, render_context
    return _answer(env, lambda e: render_context(_context(e, entity, id, columns, max(0, min(depth, 2)), time_zone or None)), limit)


@mcp.tool()
def record_history(env: str, record: str, column: str = "", clusters: int = 0, time_zone: str = "", limit: int = DEFAULT_LIMIT) -> str:
    """The change log of one record (`record=UsrOrder:<id>`) from the object's `Sys<Entity>Log`: per change when, who and per
    column `was -> became` (an insert lists the columns that have a value; a lookup is logged by its text). `column` keeps the
    changes of one column. `clusters` (milliseconds) adds, for each change, the other records of the entity the same user changed
    within that many milliseconds - "closing one order closed the user's other orders in the same millisecond". An object with no
    log table answers `change tracking is off for <Entity>`. Read-only."""
    from creatio_schemas.records import record_history as _history, render_history

    def work(e):
        answer = _history(e, record.strip(), column.strip(), max(0, clusters), time_zone or None)
        answer["column"] = column.strip()
        return render_history(answer)

    return _answer(env, work, limit)


@mcp.tool()
def column_transitions(env: str, column: str, from_: str = "", to: str = "", since: str = "", out: str = "", time_zone: str = "",
                       limit: int = DEFAULT_LIMIT) -> str:
    """Every change of one column over all records of an object, from its change log: `column=UsrOrder.UsrStatus`, each line the time,
    the record, `from -> to` and who. `from_` / `to` (case-blind) keep matching transitions, `since` (`2026-11-01` or `2026-11-01T08:00`, UTC)
    the later ones. `out` writes every transition to a CSV (UTF-8 with a BOM, `;`) and the answer names the file. An insert is a transition
    from empty; a lookup reads as the log has it (its text). Reads at most 50000 log rows. Read-only."""
    from creatio_schemas.records import column_transitions as _transitions, render_transitions, transitions_csv

    def work(e):
        answer = _transitions(e, column.strip(), from_ if from_ != "" else None, to if to != "" else None, since.strip() or None, time_zone or None)
        text = render_transitions(answer, limit or len(answer["rows"]) or 1)
        return text + (f"\n{len(answer['rows'])} rows -> {transitions_csv(answer, out)}" if out.strip() else "")

    return _answer(env, work, 0)


@mcp.tool()
def role_members(env: str, role: str, units: bool = False) -> str:
    """The users a role reaches through `SysAdminUnitInRole` - the closure, nested roles and the org structure included,
    not only the direct members `SysUserInRole` lists - each with the unit the membership came through. `units` adds
    organization units and roles. Read-only."""
    from creatio_schemas.access import render_members, role_members as _members
    return _answer(env, lambda e: render_members(_members(e, role, units)))


@mcp.tool()
def user_roles(env: str, user: str) -> str:
    """The roles of a user (login or contact name) through `SysAdminUnitInRole`, each direct or through another unit. Read-only."""
    from creatio_schemas.access import render_roles, user_roles as _roles
    return _answer(env, lambda e: render_roles(_roles(e, user)))


@mcp.tool()
def role_diff(env: str, role: str, users: str) -> str:
    """Which of these users (comma-separated logins or contact names) are not in the role: `in <role>: ...` and
    `not in <role>: ...`, then `exit code 1` when anyone is missing. Read-only."""
    from creatio_schemas.access import role_diff as _diff
    missing = []

    def work(e):
        result = _diff(e, [u.strip() for u in users.split(",") if u.strip()], role)
        missing.extend(result["missing"])
        return f"in {role}: {', '.join(result['present']) or '-'}\nnot in {role}: {', '.join(result['missing']) or '-'}"

    text = _answer(env, work)
    return text if text.startswith("error:") else text + f"\nexit code {1 if missing else 0}"


@mcp.tool()
def sys_setting(code: str, envs: str, workspace: str = "", time_zone: str = "") -> str:
    """A system setting's value on each clio environment of the comma list `envs` - per value row who it is for, the value
    (a lookup by name), the date and the author - and, with `workspace` (a folder with `packages/`), every data binding of
    the workspace that sets it and the value a push would write. Read-only."""
    from creatio_schemas.access import render_setting, sys_setting as _setting
    from creatio_schemas.environment import Environment
    _tools_path()
    try:
        answer = _setting(code, {n.strip(): Environment.from_clio(n.strip()) for n in envs.split(",") if n.strip()}, workspace or None, time_zone or None)
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"
    return render_setting(answer)


@mcp.tool()
def schema_diff(package: str, schemas: str = "", against: str = "", limit: int = DEFAULT_LIMIT) -> str:
    """
    What did my edit change, in schema terms, before a push or a commit: the working copy against git HEAD
    (default), another revision, or a folder holding the package (a pulled copy of the
    environment). Per item the lines the describe layer prints: `+` added (a column, an
    element, a rule), `-` removed, `~ key old -> new` changed; `+ Name kind (new)` /
    `- Name kind (removed)` for whole items. `schemas` limits it to a space-separated
    list of items. against="env:<clio env>": the site's copy of the named `schemas` (what a designer edit changed; read-only). The tester's reading of what the author changed; never a JSON hunk. `limit` cuts the lines (0 = all).
    """
    _tools_path()
    from creatio_schemas.describe import cut
    from creatio_schemas.describe.diff import schema_diff as _sd
    try:
        lines = _sd(package, schemas.split() or None, against or None).splitlines()
        return "\n".join(cut(lines[:-1], limit, "lines") + lines[-1:])  # the last line is the count
    except (FileNotFoundError, KeyError, ValueError) as e:
        return f"error: {e}"


@mcp.tool()
def review_download(package: str, keep: str = "", limit: int = DEFAULT_LIMIT) -> str:
    """A pulled package (a folder that holds it, or its path) sorted against git HEAD before anything is committed:
    files that differ only in line endings or a BOM (nothing changed), the items changed in content (`schema_diff`'s
    lines, renames by UId), dependencies dropped or added (descriptor.json, csproj), resource folders with no schema,
    files git does not track. `keep` (space-separated items) adds the `git checkout HEAD -- <path>` lines that would
    restore every other changed file; this tool only prints them - `describe.py review --keep ... --apply` runs them.
    `limit` cuts the content lines (0 = all)."""
    _tools_path()
    from creatio_schemas.describe.review import render, review
    try:
        return render(review(package, keep.split() if keep.strip() else None), limit)
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e}"


@mcp.tool()
def verify_pushed(package: str, env: str, schemas: str = "", bin: str = "") -> str:
    """Is the site running the pushed code (after push_package, before trusting a test): per schema of the package (or
    `schemas`, comma-separated) the site's SysSchema metadata and body (md5) against the working copy - `same`, `same (line
    endings)`, `differs (metadata|body: site <md5> repo <md5>)`, `not on the site`; a script process: `not published: ...` when
    its generated source is missing or older than its schema, `compile error: CS....` when it does not compile (with `bin`, the
    Creatio assemblies); a client schema: `not served: ...` when conf/content/<Schema>.js does not hold the new body (the site's
    client cache). Read-only. Ends with `N same, M not`."""
    _tools_path()
    from creatio_schemas.cli import resolve_package
    from creatio_schemas.environment import open_environment
    from creatio_schemas.verify import render, verify
    try:
        results = verify(resolve_package(package), open_environment(env), [s.strip() for s in schemas.split(",") if s.strip()] or None,
                         Path(bin) if bin else None)
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"
    return render(results)


@mcp.tool()
def precommit_check(workspace: str) -> str:
    """The staged files of a workspace that must not be committed - over 5 MB, an archive (.rar .zip .7z .gz .bak),
    a binary (.dll .exe .pdb) outside Files/Bin of an assembly package, a file outside packages/ and the known roots -
    one line each, then `exit code 1`; `ok` when there is none. Also a staged object whose new columns or new schema the last
    `index_workspace(env=)` pass found on the site in another package (reuse it). Lines that do not stop (`no site pass yet`, a
    physical column) follow as `note:` lines. Read-only (git is only read)."""
    _tools_path()
    from creatio_schemas.describe.review import precommit
    try:
        notes: list[str] = []
        problems = precommit(workspace, notes)
    except (FileNotFoundError, RuntimeError) as e:
        return f"error: {e}"
    return "\n".join(problems + [f"note: {n}" for n in notes] + ["exit code 1"]) if problems else "\n".join([f"note: {n}" for n in notes] + ["ok"])


def _ci(script: str, argv: list[str]) -> str:
    """Run a ci-cd command line (pipeline.py or clio-ext/clio-ext.py) in-process, its output captured; ends with `exit code N`."""
    import importlib.util
    import io
    from contextlib import redirect_stderr, redirect_stdout
    path = _ROOT.parent / "ci-cd" / script
    if not path.is_file():
        return f"error: {path} not found (the kit's ci-cd folder is not next to the knowledge base)"
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    out = io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(out):
            spec.loader.exec_module(module)
            code = module.main(argv)
    except SystemExit as e:  # sys.exit("message") inside a stage, or argparse
        code = e.code if isinstance(e.code, int) else 1
        if e.code and not isinstance(e.code, int):
            out.write(f"{e.code}\n")
    return out.getvalue().rstrip() + f"\nexit code {code}"


def _names(package: str) -> list[str]:
    return ["--package", package.strip()] if package.strip() else []


@mcp.tool()
def ci_check(packages: str, package: str = "", cyrillic: bool = False) -> str:
    """The package rules of the CI pipeline (`ci-cd/pipeline.py check`), the stage that runs before a merge: every schema folder has
    `metadata.json`, `descriptor.json`, `properties.json`; no duplicate schema UId across the packages; no `alert(` or `debugger`
    in a `.js` schema; one `.sql` per `SqlScripts/<Name>/` named after its folder; one `.dll` per `Assemblies/<Name>/`; with
    `cyrillic` also no Cyrillic outside comments. `packages` is the folder that holds the package folders, `package` a
    comma-separated subset. One line per problem, `package rules: ok` when there is none; ends with `exit code` 0/1. Read-only."""
    return _ci("pipeline.py", ["check", packages] + _names(package) + (["--cyrillic"] if cyrillic else []))


@mcp.tool()
def ci_hierarchy(packages: str) -> str:
    """The install order of the packages of a folder and their dependency report (`clio-ext.py hierarchy`): levels from
    `descriptor.json` DependsOn (level 0 depends on nothing inside the folder), per package what it depends on, what lies outside
    the folder and who uses it, then PROBLEMS (a descriptor `Name` that differs from its folder, a `ProjectPath` that does not
    exist). Read it before a deploy of several packages or a dependency change. Read-only (the files go to a temp folder)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.txt"
        text = _ci("clio-ext/clio-ext.py", ["hierarchy", "-p", packages, "--out", str(Path(tmp) / "order.txt"), "--report", str(report)])
        if report.is_file():
            return report.read_text(encoding="utf-8").rstrip() + "\n" + text.splitlines()[-1]
    return text


@mcp.tool()
def ci_lint(packages: str, locale: str = "uk-UA", package: str = "") -> str:
    """The two content checks of clio-ext on a packages folder: schemas without `resource.<locale>.xml` (`find-missing-loc`) and
    Read Data elements of business processes that read every column of their object (`validate-processes`, `package` limits it
    to one package). Each part ends with its own `exit code`; both 0 when the folder is clean. Read-only."""
    loc = _ci("clio-ext/clio-ext.py", ["find-missing-loc", "-p", packages, "-l", locale])
    processes = _ci("clio-ext/clio-ext.py", ["validate-processes", "-p", packages] + (["-k", package.strip()] if package.strip() else []))
    return f"--- missing localization ({locale}) ---\n{loc}\n--- process Read Data elements ---\n{processes}"


@mcp.tool()
def ci_build(packages: str, out: str, package: str = "") -> str:
    """The build stage of the CI pipeline (`pipeline.py build`): `clio compress` per package into `out`/<Package>.gz and one
    `out`/Pkg.zip, the artifact the deploy takes; the packages in dependency order (or `package`, comma-separated, in that order).
    Needs clio on the PATH. Writes into `out` only; ends with `exit code` 0/1."""
    return _ci("pipeline.py", ["build", packages, "--out", out] + _names(package))


@mcp.tool()
def ci_deploy(packages: str, env: str, package: str = "", restart: bool = True, redis: bool = True, compile_all: bool = False) -> str:
    """The deploy stage of the CI pipeline (`pipeline.py deploy`) on the clio environment `env`: `IsChanged` cleared in
    `SysSchema`, `SysPackageSchemaData` and `SysPackageSqlScript`, `clio push-pkg` per package in dependency order (or `package`,
    comma-separated, in that order), `compile-configuration` (`compile_all` for a full rebuild), `restart-web-app --wait-ready`
    unless `restart` is false, `clear-redis-db` unless `redis` is false, `healthcheck`. For ONE package with probes of the changed
    items use `push_package`. WRITES to the site; stops at the first failed command; ends with `exit code` 0/1."""
    flags = (["--no-restart"] if not restart else []) + (["--no-redis"] if not redis else []) + (["--all"] if compile_all else [])
    return _ci("pipeline.py", ["deploy", packages, "-e", env] + _names(package) + flags)


@mcp.tool()
def ci_push_all(packages: str, env: str, package: str = "", retry: bool = False, continue_on_error: bool = False) -> str:
    """Only the push of several packages (`clio-ext.py push-all`), one `clio push-pkg` at a time in dependency order (or `package`,
    comma-separated, in that order) after `IsChanged` is cleared; stops at the first failure, or with `continue_on_error` pushes
    the rest. The failed ones go to `error-pkg.txt` next to the packages folder and `retry` pushes exactly that list again.
    One log line per step in `logs/<date>.log` next to the packages folder. No compile, restart or Redis: `ci_deploy` does the
    whole stage. WRITES to the site; ends with `exit code` 0/1."""
    argv = ["push-all", "-p", packages, "-e", env] + _names(package) + (["--continue-on-error"] if continue_on_error else [])
    if retry:
        argv += ["--list", str(Path(packages).resolve().parent / "error-pkg.txt")]
    return _ci("clio-ext/clio-ext.py", argv)


@mcp.tool()
def run_tests(env: str = "", project: str = "", category: str = "", test: str = "", package: str = "") -> str:
    """The in-Creatio tests of a project (the integration tier) through the runner `project.json` `tests.runner` names:
    the failed tests first with their messages, the passed ones, `N passed, M failed`, then a warning when the test
    package (`package`, default `tests.package`) changed on the site after its last successful compilation - the tests
    then ran on the old dll. `category` or `test` (a test class) selects; `env` a clio name, or `project` a project.json.
    Ends with `exit code 1` when a test failed, 2 when nothing could be run. Runs the tests: whatever they write is written."""
    import importlib.util
    import io
    from contextlib import redirect_stderr, redirect_stdout
    _tools_path()
    spec = importlib.util.spec_from_file_location("env_unit", _ROOT / "no-code" / "tools" / "env" / "unit.py")
    unit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(unit)
    if bool(category.strip()) == bool(test.strip()):
        return "error: give category or test (a test class), one of them"
    argv = ["run", "--category", category.strip()] if category.strip() else ["run", "--class", test.strip()]
    argv += ["--project", project] if project.strip() else ["-e", env.strip()]
    argv += ["--package", package.strip()] if package.strip() else []
    out = io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(out):
            code = unit.main(argv)
    except SystemExit as e:  # argparse refused the arguments
        code = e.code if isinstance(e.code, int) else 2
    return out.getvalue().rstrip() + f"\nexit code {code}"


@mcp.tool()
def find_in_processes(path: str, pattern: str, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """
    Search the DECODED text of every business process in a workspace or package: script task lines
    (not the escaped string in metadata.json), flow conditions, formulas, element filters (a lookup
    GUID shown with its caption when a data binding names it), the column values of Add/Modify data,
    parameter defaults. Lines `Package / Process / Element [type] / where: text`; case-blind, a regex
    when the pattern parses as one. Use it before grep over metadata.json.
    """
    _tools_path()
    from creatio_schemas.describe.writes import find_in_processes as _find
    from creatio_schemas.describe import QueryError
    try:
        return _find(path, pattern, limit, offset)
    except (FileNotFoundError, KeyError, QueryError) as e:
        return f"error: {e.args[0] if e.args else e}"


@mcp.tool()
def who_sets(path: str, target: str, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """
    Every place that WRITES a column: `<Entity>.<Column>` or `<Entity>.<Column> = <value>`. Process
    Add/Modify data steps and script tasks, C# (Files/cs and source schemas: SetColumnValue, Update().Set),
    client pages (this.set, $context.<Column> =), SQL scripts. One line per place with kind and
    file:line. Ask it before changing a column's meaning. Read-only.
    """
    _tools_path()
    from creatio_schemas.describe.writes import who_sets as _who
    from creatio_schemas.describe import QueryError
    try:
        return _who(path, target, limit, offset)
    except (FileNotFoundError, KeyError, QueryError) as e:
        return f"error: {e.args[0] if e.args else e}"


@mcp.tool()
def who_reads_message(path: str, sender: str, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """
    The publishers (`MsgChannelUtilities.PostMessage*` naming the sender) and the subscribers
    (`ServerChannel` handlers with a `Header.Sender` check naming it) of a websocket message sender,
    over C# and client code of a workspace or package. Read-only.
    """
    _tools_path()
    from creatio_schemas.describe.writes import who_reads_message as _who
    from creatio_schemas.describe import QueryError
    try:
        return _who(path, sender, limit, offset)
    except (FileNotFoundError, KeyError, QueryError) as e:
        return f"error: {e.args[0] if e.args else e}"


@mcp.tool()
def page_audit(path: str, page: str, all: bool = False) -> str:
    """
    What makes a Freedom UI page slow, one line per finding over a threshold: elements per tab (over
    80), grids with no master filter, attributes through 3+ joins, comboboxes (over 25), page and
    object business rules (over 20, any disabled, duplicated), object columns (over 100), handler
    timers. Last line `<Page>: <n> finding(s)`. `all=true` prints every count. Read-only.
    """
    _tools_path()
    from creatio_schemas.cli import resolve_package
    from creatio_schemas.page import PageSchema
    from creatio_schemas.page.audit import audit
    try:
        pg = PageSchema(resolve_package(path), page)
        lines = audit(pg, all)
    except (FileNotFoundError, KeyError, ValueError) as e:
        return f"error: {e.args[0] if e.args else e}"
    return "\n".join(lines +[f"{page}: {len(lines)} " + ("count(s)" if all else "finding(s)")])


@mcp.tool()
def resolve_uid(path: str, text: str) -> str:
    """
    Which lookup value, schema, column or process element is this GUID, and what is the GUID of a
    dotted name: what a UId names in the workspace - a schema, a column (`column UsrOrder.UsrAmount`), a process
    element or parameter - or the UId of a dotted name (`UsrOrder.UsrAmount`,
    `UsrOrder_Process.ReadData.ResultEntity`). Given a text with UIds in it (a meta path from
    SysSchema metadata, a filter, a stack of them), every UId is named and the text comes back with
    the names in place: the reverse of what the designer stores. A UId that is not in the
    workspace (a lookup row, a system record) says so - env_sql finds those.
    """
    _tools_path()
    from creatio_schemas.describe.uids import resolve
    try:
        return resolve(path, text)
    except (FileNotFoundError, KeyError, ValueError) as e:
        return f"error: {e}"


@mcp.tool()
def schema_layers(path_or_env: str, schema: str, rule: str = "", workspace: str = "") -> str:
    """Is this page, object or method overridden in another package or in Custom on the site, and why are my changes not
    visible after a push: the copies of a schema on the environment in the order the platform applies them (the last wins):
    package, replacing or not, modified on / by, IsChanged, body size and md5. Run it BEFORE planning a change to a page
    or object that the platform or another package already has, and as the tester's first preflight step: a copy in the
    customisation package (Custom) is applied after every package you push and silently overrides it - the answer then ends
    with `Custom layer present: <package>`. `path_or_env` is a clio environment name or the path of project.json (its
    environment.customLayer names the customisation package). `rule`: a business rule UId - its state (absent / enabled /
    disabled / removed) in every layer. `workspace`: the workspace holding the schema - a schema the site renamed (the UId stays, a push from
    git brings the old name back) is then found by its UId and the answer says `name on site: X (workspace: Y)`. Reads the environment (SELECTs), writes nothing."""
    import json
    from creatio_schemas.describe.layers import CUSTOM_LAYER, render, schema_layers as _layers
    from creatio_schemas.environment import open_environment
    project = path_or_env if path_or_env.endswith(".json") else None
    try:
        env = open_environment(None if project else path_or_env, project)
        custom = json.loads(Path(project).read_text(encoding="utf-8-sig")).get("environment", {}).get("customLayer") if project else None
        return render(_layers(env, schema, rule or None, custom or CUSTOM_LAYER, workspace or None), env.clio_name or env.url)
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"


@mcp.tool()
def schema_snapshot(schema: str, env: str = "", workspace: str = "", columns: str = "", out: str = "", limit: int = 0,
                    page_file: str = "") -> str:
    """An OBJECT as text lines, to prove a layer merge changed nothing. `workspace`: the effective schema over every layer
    on disk (`layers: a > b`, `column <Name> <uid> <type> [lookup X] [required] [default v]`, `index ...`; the site's layer
    order when `env` is also given). `env`: what the site holds (`table T column <col> <type>`, `rows <n>`,
    `checksum <col> <md5>` of every column's values ordered by Id, `copy <package> extendParent=<bool>` per layer).
    Take it BEFORE and AFTER, then `snapshot_compare`. `columns`: a comma list to checksum (default every column but Id;
    name them on a big table). `out`: a file to write the lines to (the evidence). Reads with SELECTs and files, writes
    nothing to the site or the workspace. A PAGE: the folded elements (`element <name> <type> [parent] [caption]`,
    `removed <name>`), `handler <request> #<n>` / `method <name>`, converter / validator / attribute ... keys on disk, the
    `copy` lines on the site, and with `page_file` (the file creatio-tests `analyse` wrote from the live page) one
    `page <code> <type> <label>` line per element."""
    from creatio_schemas.describe import cut
    from creatio_schemas.integrity import snapshot
    _tools_path()
    try:
        if not workspace and not env and not page_file:
            return "error: give a workspace (disk lines), an env (site lines), or both"
        lines = snapshot(workspace or None, schema, _env(env) if env else None, [c.strip() for c in columns.split(",") if c.strip()] or None,
                         page_file=page_file or None)
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"
    if out:
        Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "\n".join(cut(lines, limit, "lines")) or "(nothing)"


@mcp.tool()
def snapshot_compare(before: str, after: str, ignore_layers: bool = False) -> str:
    """Two snapshot files (`schema_snapshot` out=...) compared: `+ - ~` lines, or `same` when nothing differs.
    A difference ends with `exit code 1` - after a layer merge it is the bug report. `ignore_layers` leaves out the lines a
    merge changes by design (`layers:`, `siblings`, `copy`, `layer ...`)."""
    from creatio_schemas.integrity import compare
    try:
        diff = compare(Path(before).read_text(encoding="utf-8").splitlines(), Path(after).read_text(encoding="utf-8").splitlines(), ignore_layers)
    except OSError as e:
        return f"error: {e}"
    return "\n".join(diff + ["exit code 1"]) if diff else "same"


@mcp.tool()
def cases_from_package(package: str, out: str, env: str = "", user: str = "Supervisor") -> str:
    """The baseline test cases of a package, written from its schemas into `out` (the UI test utility's root): Cases/<Package>/<Object>.act
    for an own object (insert the required columns, read back, update, read back, delete - over OData), ProcessCases/<Package>/<Process>.act +
    Configuration/processes/<Process>.json for a process without a user task, Configuration/pages/<Page>.json + Cases/<Package>/<Page>.act for a
    Freedom UI form page. One line per file (`wrote`, `same`, `kept` = an edited case is never overwritten), `stop <Schema>: ...` for a value or a
    field the generator will not guess (a lookup without `env`, a required column the page does not show) and `not generated: ...`. Run the
    result with the creatio-tests `validate` / `run` tools. `env` lets a lookup take the first row of its object. Writes files into `out` only."""
    _tools_path()
    from creatio_schemas.cases import cases_from_package as generate
    try:
        report = generate(package, out, _env(env) if env else None, user)
    except (OSError, KeyError, ValueError, RuntimeError) as e:
        return f"error: {e.args[0] if e.args else e}"
    return "\n".join(report) + f"\nexit code {1 if any(l.startswith('stop') for l in report) else 0}" if report else "(no schema to write cases for)"


@mcp.tool()
def tool_stats(days: int = 1) -> str:
    """What this server returned to the agents over the last `days` days (today included): calls, characters, the average and the
    largest answer per tool, the ten largest answers (tool and argument names, never values) and the share of answers that were cut
    with a `... N more` tail. Read it to see which tool costs the most context. The same table is `python mcp-server/tool_stats.py [days]`.
    Off when the server runs with CREATIO_KB_STATS=0. Reads `mcp-server/.stats/<date>.jsonl`, writes nothing."""
    return stats_log.summarise(stats_log.read(days))


def main() -> None:
    """Console entry point: serve over stdio."""
    global _ROOT
    _ROOT = default_root()
    if not (_ROOT / "code").is_dir():
        raise SystemExit(
            f"No knowledge base found at {_ROOT}. "
            "Set CREATIO_KB_ROOT to the folder that contains code/ and no-code/."
        )
    mcp.run()


if __name__ == "__main__":
    main()
