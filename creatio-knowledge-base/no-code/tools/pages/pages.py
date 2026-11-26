#!/usr/bin/env python3
"""Freedom UI pages stored in a package (library: ../creatio_schemas/page).

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

`new` makes a page for an object that already exists (scaffold makes pages only with a new object): the template's page,
then a field per --fields column (default: every own column of the object); an existing page is refused. It is built in
a scratch copy and validated first; --dry-run lists the files it would write. `--template mini` makes a process's
pre-configured page (parent BaseMiniPageTemplate, no --entity, one label showing --caption): a page task opens it and
completes on its buttons (`proc.py element ... buttons`).

The page body (<Page>.js) is edited through its JSON marker sections; a bound field gets the
control the designer would give the column's type and a PDS attribute, a grid gets its data
source and collection attribute. Field captions come from the column captions - no resource
strings are written. Every writing command accepts --dry-run. After `clio push-pkg` (clear
SysSchema.IsChanged first) the page renders the new controls; `analyse` of the UI test utility
shows what the browser got.

`from-schema` writes the UI test utility's page file (Configuration/pages/<name>.json) from the page
schema, without a browser: one element per control the utility has a type for, `code` = the element
name, the label as the page shows it, grids with their columns, the template's own buttons and tabs.
`--compare` prints what differs from an existing page file (exit code 1 when anything does).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scaffold"))

from creatio_schemas.cli import CommandLine, parse_assignments  # noqa: E402
from creatio_schemas import jscheck  # noqa: E402
from creatio_schemas.files import write_text  # noqa: E402
from creatio_schemas.page import PageSchema, compare_page_files  # noqa: E402


def new(_, a):
    import shutil
    from scaffold import changed_files, scratch_copy
    from creatio_schemas.resources import Resources
    from creatio_schemas.workspace import BASE_COLUMNS, Workspace
    package = Path(a.package).resolve()
    ws = Workspace(package)
    if ws.find(a.page, "ClientUnitSchemaManager") or (package / "Schemas" / a.page).exists():
        raise FileExistsError(f"{a.page} exists")
    if a.fields and a.template != "form":
        raise ValueError("--fields goes with --template form")
    if (a.template == "mini") == bool(a.entity):
        raise ValueError("--template mini takes no --entity" if a.entity else "--entity is required")
    found = ws.find(a.entity, "EntitySchemaManager") if a.entity else None
    if a.entity and not found:
        raise KeyError(f"object {a.entity} is not in the workspace")
    caption = a.caption or (a.page if a.template == "mini" else "")
    if not caption:
        try:
            base = Resources(found[0]["dir"].parent.parent / "Resources" / f"{a.entity}.Entity").get("Caption", "en-US") or a.entity
        except (OSError, KeyError):
            base = a.entity
        caption = base + (" form" if a.template == "form" else "")
    scratch = scratch_copy(package)
    try:
        page = PageSchema.create(scratch, a.page, a.entity or "", a.template, caption, a.cultures.split(",") if a.cultures else None)
        if a.template == "form":
            for col in a.fields.split(",") if a.fields else [c for c in page.workspace.columns(a.entity) if c not in BASE_COLUMNS]:
                page.add_field(col.strip())
        page.save()
        problems = [p for p in PageSchema(scratch, a.page).validate()]
        if problems:
            raise ValueError("validation refuses the page:\n  " + "\n  ".join(problems))
        files = changed_files(scratch, package)
        for rel, f in files.items():
            print(f"  {rel.as_posix()}")
            if not a.dry_run:
                (package / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, package / rel)
    finally:
        shutil.rmtree(scratch.parent.parent, ignore_errors=True)
    print(f"{len(files)} file(s) " + ("would be written (dry run: nothing written)" if a.dry_run else f"written to {package.name}; validation: ok"))


def env_of(a):
    from creatio_schemas.environment import open_environment
    return open_environment(a.env) if a.env else None


def replace(_, a):
    page = PageSchema.create_replacing(Path(a.package), a.page, a.parent_uid, a.caption, a.cultures.split(",") if a.cultures else None, env_of(a))
    print(f"created {page.name} replacing {page.replacing} ({page.descriptor.data['Parent']['UId']}):")
    for path in sorted(page.files()):
        print(f"  {path.relative_to(page.package).as_posix()}")


def grid_caption(page, a):
    if not all("=" in v for v in a.values):
        raise ValueError('give culture=text pairs, e.g. en-US="Amount"')
    print(f"caption of {a.grid}.{a.column}: #ResourceString({page.grid_caption(a.grid, a.column, parse_assignments(a.values))})#")


def inspect(page, a):
    print(page.describe())


def validate(page, a):
    problems = page.validate()
    for p in problems:
        print(p)
    print("ok" if not problems else f"{len(problems)} problem(s)")
    print("\n".join(jscheck.lines(page.body_path)))
    return 1 if page.errors() else 0


def add_field(page, a):
    op = page.add_field(a.column, parent=a.parent, row=a.row, col=a.col, span=a.span)
    print(f"add {a.column}: {op['values']['type']} in {a.parent} row {op['values']['layoutConfig']['row']}")


def add_grid(page, a):
    if not a.master:
        print(f"warning: no --master: the grid lists every row of {a.entity}")
    op = page.add_grid(a.name, a.entity, a.columns.split(","), parent=a.parent, rows=a.rows, editable=a.editable, master=a.master,
                       add_button=a.add_button or bool(a.panel and not a.no_add_button), entity_page=a.entity_page,
                       literal_captions=a.literal_captions, panel=a.panel, before=a.before, env=env_of(a) if a.before else None)
    print(f"add {a.name}: grid of {a.entity} in {op['parentName']}[{op['index']}]" + (f" of panel {a.panel!r}" if a.panel else ""))


def set_value(page, a):
    page.set_value(a.element, a.property, a.value, a.text, a.culture)
    print(f"set {a.element}.{a.property} = {a.value}")


def remove(page, a):
    page.remove(a.element)
    print(f"remove {a.element}")


def from_schema(page, a):
    culture = a.culture
    if not culture:  # the labels the browser shows: the package's primary culture, from the index
        from creatio_schemas.describe.index import PackageIndex
        idx = PackageIndex(page.package)
        idx.refresh()
        culture = idx.data.get("culture")
    data, notes = page.page_file(a.name, culture)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"  # the layout analyse writes: two spaces, LF, no BOM
    if a.out:
        write_text(Path(a.out), text, False)
        print(f"wrote {a.out}: {len(data['elements'])} element(s)")
    elif not a.compare:
        sys.stdout.write(text)
    for note in notes:
        print(f"# {note}")
    if a.compare:
        diff = compare_page_files(json.loads(Path(a.compare).read_text(encoding="utf-8-sig")), data)
        print("\n".join(diff) if diff else f"no difference from {a.compare}")
        return 1 if diff else 0
    return 0


def audit(page, a):
    from creatio_schemas.page.audit import audit as run

    lines = run(page, a.all)
    for line in lines:
        print(line)
    if page.replacing:
        print(f"# a replacing copy of {page.replacing}: the counts cover this layer only")
    print(f"{page.name}: {len(lines)} " + ("count(s)" if a.all else "finding(s)"))
    return 1 if lines and not a.all else 0


def layout(_, a):
    from creatio_schemas.environment import open_environment
    from creatio_schemas.page.layout import layout_lines
    print("\n".join(layout_lines(Path(a.package), a.page, a.container, open_environment(a.env) if a.env else None)))


def build() -> CommandLine:
    c = CommandLine(__doc__, "page")
    p = c.command("new", new, "a form or list page for an object that exists; a process's mini page")
    p.add_argument("--entity", help="the object (form and list)")
    p.add_argument("--fields", help="comma-separated columns, in this order; default every own column of the object")
    p.add_argument("--caption", help="default: the object's caption + ' form'; mini: the page name")
    p.add_argument("--template", choices=["form", "list", "mini"], default="form")
    p.add_argument("--cultures", help="comma-separated; default the package's cultures")
    p.add_argument("--dry-run", action="store_true", help="list the files, write nothing")
    p = c.command("replace", replace, "a replacing copy of a base Freedom page: descriptor, diff metadata, properties, resources, empty body")
    p.add_argument("--env", help="clio environment: the page's UId from the site when the workspace and the catalog lack it")
    p.add_argument("--parent-uid", help="the base page's UId, given")
    p.add_argument("--caption", help="default: the copy's caption in the workspace, else the page name")
    p.add_argument("--cultures", help="comma-separated; default the package's cultures")
    p = c.command("layout", layout, "a grid container over every layer (site copies with --env): the element in each cell, free cells")
    p.add_argument("--container", required=True)
    p.add_argument("--env", help="clio environment: the site's copies too, each body read from the site")
    c.command("inspect", inspect, "elements, attributes, data sources and problems")
    c.command("validate", validate, "problems; exit code 1 on errors")
    p = c.command("add-field", add_field, "a field bound to a column of the page's object", writes=True)
    p.add_argument("column")
    p.add_argument("--parent", default="SideAreaProfileContainer")
    p.add_argument("--row", type=int)
    p.add_argument("--col", type=int, default=1)
    p.add_argument("--span", type=int, default=1)
    p = c.command("add-grid", add_grid, "a grid listing another object's records", writes=True)
    p.add_argument("name")
    p.add_argument("--entity", required=True)
    p.add_argument("--columns", required=True, help="comma-separated column names of the entity")
    p.add_argument("--parent", default="GeneralInfoTabContainer")
    p.add_argument("--rows", type=int, default=6, help="rowSpan in the parent grid container")
    p.add_argument("--editable", action="store_true")
    p.add_argument("--master", metavar="COLUMN", help="the entity's lookup column to this page's record: writes the detail filter (dependencies)")
    p.add_argument("--add-button", action="store_true", help="a New button above the grid (crt.CreateRecordRequest, the master column preset)")
    p.add_argument("--page", dest="entity_page", help="the page the New button opens; default <entity>_FormPage")
    p.add_argument("--literal-captions", action="store_true", help="column captions as plain text (a probe); default: resource strings")
    p.add_argument("--panel", metavar="TITLE", help="the designer's detail: an expansion panel with this title, tools (add, refresh), the grid inside")
    p.add_argument("--no-add-button", action="store_true", help="with --panel: tools without the add button")
    p.add_argument("--before", metavar="ELEMENT", help="at this element's index in its parent (this page's, else the replaced page's)")
    p.add_argument("--env", help="clio environment: read the replaced page from the site for --before")
    p = c.command("grid-caption", grid_caption, "a grid column's caption as a page string, in each culture given", writes=True)
    p.add_argument("grid")
    p.add_argument("column", help="the column's code, path or the part after <DS>_")
    p.add_argument("values", nargs="+", metavar="culture=text")
    p = c.command("set-value", set_value, "one property of an element; a #ResourceString(Key)# value gets its B2 entry and string", writes=True)
    p.add_argument("element")
    p.add_argument("property", help="a.b.c sets a nested property")
    p.add_argument("value")
    p.add_argument("--text", help="the string's text for #ResourceString(Key)# (needed when the page has no such string yet)")
    p.add_argument("--culture", help="the culture of --text; default en-US; the page's other cultures stay without the key (`resources.py missing` lists them)")
    p = c.command("remove", remove, "drop an element with its attribute and data source", writes=True)
    p.add_argument("element")
    p = c.command("audit", audit, "what makes the page slow: counts over thresholds; exit code 1 on any finding")
    p.add_argument("--all", action="store_true", help="print every count, thresholds ignored")
    p = c.command("from-schema", from_schema, "the UI test utility's page file, from the page schema")
    p.add_argument("--name", help="the page name cases `open`; default <Object>Form for <Object>_FormPage")
    p.add_argument("--culture", help="the culture of the labels (the browser's language); default the package's primary culture")
    p.add_argument("--out", help="file to write (default: print)")
    p.add_argument("--compare", metavar="PAGE_FILE", help="print the differences from this page file")
    return c


def main(argv=None) -> int:
    return build().run(sys.argv[1:] if argv is None else argv, lambda a: None if a.command in ("new", "replace", "layout") else PageSchema(Path(a.package), a.page))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
