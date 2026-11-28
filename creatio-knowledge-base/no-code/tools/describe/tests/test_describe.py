"""Checks for the describe layer:  python tests/test_describe.py  (uses the other toolkits' fixtures)."""

import contextlib
import shutil
import io
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE.parent))

from creatio_schemas.describe import PackageIndex, QueryError, describe_item, describe_package, describe_schema, find_schema, index_workspace, parse_query  # noqa: E402
from creatio_schemas.describe.index import INDEX_FORMAT, located  # noqa: E402
from describe import main  # noqa: E402

PAGES = TOOLS / "pages" / "tests" / "fixtures" / "UsrPkg"
RULES = TOOLS / "rules" / "tests" / "fixtures" / "UsrPkg"
PROCS = TOOLS / "process" / "tests" / "fixtures" / "UsrPkg"
SQL = TOOLS / "sqlscripts" / "tests" / "fixtures" / "UsrPkg"
DCM = TOOLS / "dcm" / "tests" / "fixtures" / "UsrPkg"


def test_parse_query():
    assert parse_query("elements type=crt.Input parent=X") == ("elements", None, {"type": "crt.Input", "parent": "X"})
    assert parse_query("element UsrName") == ("element", "UsrName", {})
    assert parse_query('find "Order bed"') == ("find", "Order bed", {})
    assert parse_query("") == ("topics", None, {})


def test_compare_exits_one_on_a_difference():
    import tempfile
    folder = Path(tempfile.mkdtemp())
    a, b = folder / "a.txt", folder / "b.txt"
    a.write_text("rows 6\nchecksum UsrNote aaa\n", encoding="utf-8")
    b.write_text("rows 6\nchecksum UsrNote aaa\n", encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["compare", str(a), str(b)]) == 0
    assert out.getvalue().strip() == "same"
    b.write_text("rows 5\nchecksum UsrNote aaa\n", encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["compare", str(a), str(b)]) == 1
    assert out.getvalue().strip() == "~ rows  6 -> 5"


def test_offset_continues_a_cut_list_where_it_stopped():
    from creatio_schemas.describe.core import cut
    lines = [f"line {i}" for i in range(1, 101)]
    page = cut(lines, 40, offset=40)
    assert page[0] == "line 41" and page[39] == "line 80" and len(page) == 41, page[-2:]
    assert page[-1] == "  ... 20 more; next: offset=80; add limit=0 for all"
    assert cut(lines, 40, offset=80) == lines[80:], "the last page has no tail"
    assert cut(lines, 0, offset=95) == lines[95:], "limit=0 with an offset: everything after it"
    assert cut(lines, 40, offset=100) == ["  (offset 100 is past the end: 100 lines)"]
    assert cut(lines, 40, "rows", offset=10)[-1].endswith("; rows")
    assert cut(lines, 40) == lines[:40] + ["  ... 60 more; add limit=0 for all"], "no offset: the answer it always was"
    for bad in (dict(limit=-1), dict(offset=-1)):
        try:
            cut(lines, **bad)
        except QueryError:
            pass
        else:
            raise AssertionError(bad)
    # the same through the query grammar, the package list and the CLI
    whole = describe_item(PAGES, "UsrOrder", "columns limit=0").splitlines()
    second = describe_item(PAGES, "UsrOrder", "columns limit=5 offset=5").splitlines()
    assert second[:5] == whole[5:10] and second[5] == f"  ... {len(whole) - 10} more; next: offset=10; add limit=0 for all", second
    assert describe_item(PAGES, "UsrOrder", "columns limit=5 offset=999").strip().startswith("(offset 999 is past the end")
    listed = describe_package(PAGES, "", 2, 1).splitlines()
    assert listed[1:3] == describe_package(PAGES, "", 0).splitlines()[2:4] and listed[3].startswith("  ... 2 more; next: offset=3")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert main(["package", str(PAGES), "--limit", "2", "--offset", "1"]) == 0
    assert out.getvalue().splitlines()[3].startswith("  ... 2 more; next: offset=3")
    from creatio_schemas.describe.deps import dependencies
    assert "next: offset=2" in dependencies(PAGES, "UsrOrder", "both", "", "", 1, 1) and "(offset 1 is past the end" not in dependencies(PAGES, "UsrOrder_FormPage", "both", "", "", 1, 1)
    try:
        describe_item(PAGES, "UsrOrder", "columns offset=x")
    except QueryError as e:
        assert "non-negative" in str(e)
    else:
        raise AssertionError("offset=x")


def test_a_page_summary_is_counts_and_never_the_element_list():
    import re
    from creatio_schemas.page.schema import PageSchema
    lines = describe_schema(RULES, "UsrTests_FormPage", 0).splitlines()
    assert lines[0] == "UsrTests_FormPage: page of UsrPkg, designer form (viewModelConfig), 12 elements, 2 tabs", lines[0]
    assert lines[1] == "  SideAreaProfileContainer: 10 elements (3 DateTimePicker, 2 ComboBox, 2 Input, 2 NumberInput, ...)"
    assert "  tab Attachments: 1 element (1 FileList)" in lines and "  attributes: 11; data sources: PDS (UsrPkg, 11 attributes), AttachmentListDS (SysFile)" in lines
    assert "  handlers: none" in lines and "  rules: 2 in UsrTests_FormPageBusinessRule; validators: 0, converters: 0" in lines
    assert len(lines) <= 12 and not any(l.startswith("    Usr") for l in lines), "an element line in the summary"
    # handlers by request name and size; the elements are one `describe_item` away
    page = PageSchema(RULES, "UsrTests_FormPage")
    page.body = re.sub(r"/\*\*SCHEMA_HANDLERS\*/.*?/\*\*SCHEMA_HANDLERS\*/", lambda m: '/**SCHEMA_HANDLERS*/[{ request: "usr.OpenRequest", handler: async (r, next) => next?.handle(r) }]/**SCHEMA_HANDLERS*/', page.body, flags=re.S)
    assert any(l.startswith("  handlers: usr.OpenRequest (") and l.endswith(" chars)") for l in page.describe().splitlines())
    assert len(describe_item(RULES, "UsrTests_FormPage", "elements limit=0").splitlines()) == 12


def test_a_body_can_be_read_by_lines_or_around_a_text():
    import re
    import shutil
    import tempfile
    pkg_root = Path(tempfile.mkdtemp())
    try:
        pkg = pkg_root / "UsrPkg"
        shutil.copytree(CS, pkg)
        body = "".join(f"\t\t\tx += {i};\r\n" for i in range(1, 197))
        (pkg / "Files" / "cs" / "UsrBig.cs").write_text("namespace Terrasoft.Configuration\r\n{\r\n\tpublic class UsrBig\r\n\t{\r\n\t\tpublic int Run() {\r\n\t\t\tint x = 0;\r\n"
                                                        + body + "\t\t\treturn foo(x);\r\n\t\t}\r\n\t}\r\n}\r\n", encoding="utf-8", newline="")
        whole = describe_item(pkg, "UsrBig", "member UsrBig.Run")
        lines = whole.splitlines()
        assert lines[0].endswith(" lines; lines=a-b or around=<text> for a part"), lines[0]  # over 120: the hint, then the body as it was
        count = int(lines[0].split()[0])
        assert count > 120 and len(lines) == count + 1
        window = describe_item(pkg, "UsrBig", "member UsrBig.Run lines=3-6").splitlines()
        assert window[0] == f"lines 3-6 of {count}" and len(window) == 5
        assert [re.sub(r"^ *[0-9]+  ", "", w) for w in window[1:]] == lines[1:][2:6]  # the body's own lines, numbered 3..6
        assert window[1].lstrip().startswith("3  ") and window[-1].lstrip().startswith("6  ")
        around = describe_item(pkg, "UsrBig", "member UsrBig.Run around=foo").splitlines()
        assert around[0] == f"lines {count - 9}-{count} of {count}" or "return foo(x);" in "\n".join(around), around
        assert any("return foo(x);" in l for l in around) and len(around) <= 18
        two = describe_item(pkg, "UsrBig", 'member UsrBig.Run around="x += 100;" n=2').splitlines()
        assert len(two) == 6 and "x += 100;" in two[3]  # the header, then two before, the match, two after
        assert describe_item(pkg, "UsrBig", f"member UsrBig.Run lines={count - 1}-9999").splitlines()[0] == f"lines {count - 1}-{count} of {count}"
        for bad, text in (("lines=20-10", "must be a range"), ("lines=9999", "starts after the end"), ("around=nope", "no line of the body"), ("around=foo n=x", "non-negative")):
            try:
                describe_item(pkg, "UsrBig", f"member UsrBig.Run {bad}")
            except QueryError as e:
                assert text in str(e), (bad, str(e))
            else:
                raise AssertionError(bad)
        # a short body is what it always was
        short = describe_item(CS, "UsrOrderLabel", "member UsrOrderLabel.Build")
        assert short.startswith("public static string Build(string type, int seq) {") and "lines; lines=a-b" not in short
        assert describe_item(CS, "UsrOrderLabel", "member UsrOrderLabel.Build lines=1-1").splitlines()[0].startswith("lines 1-1 of ")
    finally:
        shutil.rmtree(pkg_root, ignore_errors=True)


def test_package_level_lists_every_kind():
    out = describe_package(PAGES)
    lines = out.splitlines()
    assert lines[0].startswith("UsrPkg") and "5 items" in lines[0]
    assert any(l.startswith("  object ") and "UsrOrder " in l and "columns" in l for l in lines)
    assert any(l.startswith("  page ") and "UsrTests_FormPage" in l and "page of UsrPkg" in l for l in lines)
    only = describe_package(PAGES, "object").splitlines()
    assert len(only) == 4 and all(l.startswith("  object") for l in only[1:])
    assert "sql " in describe_package(SQL, "sql")
    assert "rules " in describe_package(RULES, "rules")
    assert "process " in describe_package(PROCS, "process")


def test_schema_summaries_are_the_inspect_output():
    assert describe_schema(PAGES, "UsrOrder").startswith("UsrOrder:")
    assert "rule(s)" in describe_schema(RULES, "UsrPkgBusinessRule")
    assert "elements:" in describe_schema(PROCS, "UsrProcess_0d4c445")


def test_a_kind_is_one_registry_entry():
    from creatio_schemas.describe import registry
    from creatio_schemas.entity import EntitySchema
    demo = registry.Kind("demo", EntitySchema, lambda p, n, d: n == "UsrOrderStatus", EntitySchema, lambda e: "a demo lookup",
                         {"hello": lambda item, name, f: f"world from {item.name}"})
    registry.register(demo)
    try:
        # the index caches kind and summary, but carries a fingerprint of the registry: a new kind rebuilds it by itself
        assert "  demo      UsrOrderStatus" in describe_package(PAGES) and "a demo lookup" in describe_package(PAGES, "demo")
        assert describe_item(PAGES, "UsrOrderStatus", "hello") == "world from UsrOrderStatus"
        assert "columns" not in describe_item(PAGES, "UsrOrderStatus", "topics") and "files" in describe_item(PAGES, "UsrOrderStatus", "topics")
        assert "  object    UsrOrder " in describe_package(PAGES)  # other objects keep their kind
    finally:
        registry.unregister("demo")
        PackageIndex(PAGES).refresh(rebuild=True)
    assert "  object    UsrOrderStatus" in describe_package(PAGES) and "columns" in describe_item(PAGES, "UsrOrderStatus", "topics")


def test_output_contract_cuts_long_answers():
    from creatio_schemas.describe import DEFAULT_LIMIT, TAIL, cut
    assert DEFAULT_LIMIT == 40 and TAIL.format(more=3) == "  ... 3 more; add limit=0 for all"
    assert cut(["a", "b", "c"], 2) == ["a", "b", "  ... 1 more; add limit=0 for all"] and cut(["a", "b"], 2) == ["a", "b"] and cut(["a"] * 99, 0) == ["a"] * 99
    DCM = TOOLS / "dcm" / "tests" / "fixtures" / "UsrPkg"
    full = describe_schema(DCM, "UsrRequestCases", limit=0)
    short = describe_schema(DCM, "UsrRequestCases", limit=10)
    assert len(full.splitlines()) > 10 and len(short.splitlines()) == 11
    assert short.splitlines()[-1].startswith(f"  ... {len(full.splitlines()) - 10} more; add limit=0 for all; this is the summary - ask describe_item for one part (topics: ")
    assert "stages" in short.splitlines()[-1] and describe_schema(DCM, "UsrRequestCases") == full  # 28 lines: under the default


def test_list_limits_and_unlimited():
    full = describe_item(PAGES, "UsrTests_FormPage", "elements limit=0").splitlines()
    short = describe_item(PAGES, "UsrTests_FormPage", "elements limit=2").splitlines()
    assert len(full) > 2 and short == full[:2] + [f"  ... {len(full) - 2} more; add limit=0 for all"]
    package_full = describe_package(PAGES, limit=0).splitlines()
    package_short = describe_package(PAGES, limit=2).splitlines()
    assert package_short == package_full[:3] + [f"  ... {len(package_full) - 3} more; add limit=0 for all"]
    for query in ("elements limit=-1", "elements limit=bad"):
        try:
            describe_item(PAGES, "UsrTests_FormPage", query)
            assert False, query
        except QueryError as e:
            assert "non-negative integer" in str(e)


def test_find_and_lookup_limits():
    from unittest.mock import patch
    from creatio_schemas.describe import lookups
    from creatio_schemas.describe import index, store
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp())

    class FakeIndex:  # the rows go to a store: the lookups read them there (S26-T02)
        def __init__(self, path, con=None):
            self.package = Path(path)
            self.path = tmp / "index.sqlite"
            self.data = {"package": "UsrPkg", "data": {}}
            self.head = self._data = self.data
            self.platform = ""
            self.schemas = {
                f"UsrLookup{i}": {"kind": "object", "parent": "BaseLookup", "caption": "", "summary": "",
                                  "files": {}, "refs": ["UsrA", "UsrB", "UsrC"]}
                for i in range(3)
            }
            self.schemas.update({
                f"UsrUnknown{i}": {"kind": "object", "parent": "UsrExternal", "caption": "", "summary": "",
                                   "files": {}, "refs": []}
                for i in range(3)
            })
            self.schemas.update({f"UsrUser{i}": {"kind": "page", "caption": "", "summary": "", "files": {}, "refs": [f"UsrLookup{j}" for j in range(3)]}
                                 for i in range(3)})
            store.save_package(self.path, "UsrPkg", {**self.data, "schemas": self.schemas})

        def refresh(self):
            pass

        def referrers(self, name):
            return [("object", f"UsrUser{i}") for i in range(3)]

        def dependents(self, name):
            return []

    with patch.object(index, "packages_of", return_value=[Path("UsrPkg")]), patch.object(index, "PackageIndex", FakeIndex):
        limited = find_schema("unused", "UsrLookup0", 1)
        assert limited.count("  ... 2 more; next: offset=1; add limit=0 for all") == 2, limited  # the first page names the next offset (S30-T03 4g)
        assert "UsrB" not in limited and "UsrUser1" not in limited
        full = find_schema("unused", "UsrLookup0", 0)
        assert "UsrC" in full and "UsrUser2" in full and "... " not in full
        limited = lookups("unused", 1)
        assert limited.count("  ... 2 more; next: offset=1; add limit=0 for all") == 2, limited  # the first page names the next offset (S30-T03 4g)
        full = lookups("unused", 0)
        assert "UsrLookup2" in full and "UsrUnknown2" in full and "... " not in full
        # offset continues each list where the first page stopped (S30-T03)
        page = find_schema("unused", "UsrLookup0", 1, 1)
        assert "refers to: UsrB" in page and "UsrA" not in page and page.count("  ... 1 more; next: offset=2") == 2, page
        page = lookups("unused", 1, 1).splitlines()
        assert page[1].startswith("  UsrLookup1 ") and page[2] == "  ... 1 more; next: offset=2; add limit=0 for all", page
        assert page[-2].strip().startswith("UsrUnknown1 ") and page[-1] == "  ... 1 more; next: offset=2; add limit=0 for all", page
    shutil.rmtree(tmp, ignore_errors=True)


def test_object_queries():
    lookups = describe_item(PAGES, "UsrOrder", "columns type=Lookup")
    assert "UsrStatus" in lookups and "UsrName" not in lookups
    assert "base" in describe_item(PAGES, "UsrOrder", "columns own=false")
    one = describe_item(PAGES, "UsrOrder", "column UsrQuantity")
    assert one.startswith("UsrQuantity") and '"A2": "UsrQuantity"' in one
    assert "flags:" in describe_item(PAGES, "UsrOrder", "flags")
    assert "columns" in describe_item(PAGES, "UsrOrder", "topics")


def test_page_queries_return_only_the_part_asked():
    sections = describe_item(PAGES, "UsrTests_FormPage", "sections")
    assert "view-config-diff" in sections and "handlers" in sections
    elements = describe_item(PAGES, "UsrTests_FormPage", "elements type=crt.DateTimePicker")
    assert elements.count("\n") == 2 and "UsrDate" in elements and "UsrName" not in elements
    assert '"name": "UsrName"' in describe_item(PAGES, "UsrTests_FormPage", "element UsrName")
    assert "PDS.UsrName" in describe_item(PAGES, "UsrTests_FormPage", "attributes bound=true")
    assert "UsrPkg" in describe_item(PAGES, "UsrTests_FormPage", "data-sources")
    assert "SideAreaProfileContainer:" in describe_item(PAGES, "UsrTests_FormPage", "containers")
    assert "view_config_diff" in describe_item(PAGES, "UsrTests_FormPage", "find UsrIsActive").lower().replace("-", "_")
    assert describe_item(PAGES, "UsrTests_FormPage", "handlers") == "(no handlers)"
    assert describe_item(PAGES, "UsrOrder_FormPage", "elements") == "(no matching element)"  # the template form has no fields yet
    try:
        describe_item(PAGES, "UsrTests_FormPage", "attribute Nope")
    except QueryError as e:
        assert "no attribute Nope" in str(e)
    else:
        raise AssertionError("an unknown attribute must be refused")


def test_handlers_are_split_by_brace_matching():
    from creatio_schemas.page import PageSchema
    page = PageSchema(PAGES, "UsrTests_FormPage")
    page.body = page.body.replace("handlers: /**SCHEMA_HANDLERS*/[]/**SCHEMA_HANDLERS*/",
                                  'handlers: /**SCHEMA_HANDLERS*/[\n{ request: "crt.SaveRecordRequest", handler: async (request, next) => { const s = "}"; return await next?.handle(request); } },\n'
                                  "{ request: 'crt.HandleViewModelInitRequest', handler: async (request, next) => { return next?.handle(request); } }\n]/**SCHEMA_HANDLERS*/")
    hs = page.handlers()
    assert [r for r, _ in hs] == ["crt.SaveRecordRequest", "crt.HandleViewModelInitRequest"]
    assert 'const s = "}"' in hs[0][1] and hs[0][1].endswith("}")


def test_process_rules_sql_queries():
    assert "FormulaTask" in describe_item(PROCS, "UsrProcess_0d4c445", "elements") or "elements" in describe_item(PROCS, "UsrProcess_0d4c445", "topics")
    assert "->" in describe_item(PROCS, "UsrProcess_0d4c445", "flows")
    assert "In" in describe_item(PROCS, "UsrProcess_0d4c445", "params") or "(no parameters)" in describe_item(PROCS, "UsrProcess_0d4c445", "params")
    rules = describe_item(RULES, "UsrPkgBusinessRule", "rules")
    assert rules.count("\n") + 1 == len(describe_item(RULES, "UsrPkgBusinessRule", "rules").splitlines())
    first = rules.splitlines()[0].split()[0]
    assert "when" in describe_item(RULES, "UsrPkgBusinessRule", f"rule {first}")
    scripts = describe_package(SQL, "sql").splitlines()[1:]
    name = scripts[0].split()[1]
    assert len(describe_item(SQL, name, "body")) > 10
    assert "cultures:" in describe_item(PAGES, "UsrOrder", "resources")


def test_a_page_task_lists_its_buttons_and_the_flow_each_leads_to():
    import json
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "packages"
    shutil.copytree(PROCS, tmp / "UsrPkg")
    try:
        path = tmp / "UsrPkg" / "Schemas" / "UsrDeleteOldLogs_Process" / "metadata.json"
        meta = json.loads(path.read_text(encoding="utf-8-sig"))
        elements = meta["MetaData"]["Schema"]["BK4"]
        task = next(e for e in elements if e["A2"] == "DeleteDataUserTask1")
        save, cancel = "b0000000-0000-4000-8000-000000000001", "b0000000-0000-4000-8000-000000000002"
        items = [{"ItemUId": save, "Caption": {"isLczValue": True, "value": "Save it"}, "Name": {"value": "UsrSaveButton"}},
                 {"ItemUId": cancel, "Caption": {"isLczValue": True}, "Name": {"value": "UsrCancelButton"}}]
        task["BP2"].append({"BL1": "Terrasoft.Core.Process.ProcessSchemaParameter", "UId": "b0000000-0000-4000-8000-000000000003", "A2": "Buttons",
                            "L8": {"GS1": 1, "GS2": json.dumps({"$values": items})}})
        flow = next(e for e in elements if e["A2"] == "SequenceFlow2")
        flow.update({"BL1": "Terrasoft.Core.Process.ProcessSchemaConditionalFlow", "GV2": json.dumps({"b0000000-0000-4000-8000-000000000004": [save]})})
        path.write_text(json.dumps(meta), encoding="utf-8")
        element = describe_item(tmp / "UsrPkg", "UsrDeleteOldLogs_Process", "element DeleteDataUserTask1")
        assert "buttons:" in element and "UsrSaveButton  'Save it'  -> SequenceFlow2 to TerminateEvent1" in element, element
        assert "UsrCancelButton  'UsrCancelButton'  -> (no flow)" in element, element  # an unlocalised caption shows the code
        assert "SequenceFlow2" in describe_item(tmp / "UsrPkg", "UsrDeleteOldLogs_Process", "flows from=DeleteDataUserTask1")
        assert "when button UsrSaveButton" in describe_item(tmp / "UsrPkg", "UsrDeleteOldLogs_Process", "flows from=DeleteDataUserTask1")
        assert "buttons:" not in describe_item(tmp / "UsrPkg", "UsrDeleteOldLogs_Process", "element TerminateEvent1")
        from creatio_schemas import ProcessSchema
        assert "SequenceFlow2: DeleteDataUserTask1 -> TerminateEvent1 when button UsrSaveButton" in ProcessSchema(tmp / "UsrPkg", "UsrDeleteOldLogs_Process").describe()  # proc.py inspect
        # the designer's own GV2 form (S45-T09): "$type" beside the element key, each list wrapped in "$values"
        flow["GV2"] = json.dumps({"$type": "Dictionary", "b0000000-0000-4000-8000-000000000004": {"$type": "Collection", "$values": [save]}})
        path.write_text(json.dumps(meta), encoding="utf-8")
        assert "UsrSaveButton  'Save it'  -> SequenceFlow2 to TerminateEvent1" in describe_item(tmp / "UsrPkg", "UsrDeleteOldLogs_Process", "element DeleteDataUserTask1")
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


def test_index_follows_the_disk():
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "packages"
    shutil.copytree(PAGES, tmp / "UsrPkg")
    try:
        first = index_workspace(tmp)
        assert "UsrPkg: 5 schemas" in first and "+5 added" in first
        assert (tmp.parent / ".creatio-index" / "index.sqlite").is_file()  # S26-T01: one store per workspace
        assert "up to date" in index_workspace(tmp)
        # a pulled schema appears: the next call indexes it, nothing else is re-read
        shutil.copytree(RULES / "Schemas" / "UsrPkgBusinessRule", tmp / "UsrPkg" / "Schemas" / "UsrPkgBusinessRule")
        again = index_workspace(tmp)
        assert "+1 added" in again and "UsrPkgBusinessRule" in again
        # a changed file is noticed by size/mtime
        meta = tmp / "UsrPkg" / "Schemas" / "UsrOrder" / "metadata.json"
        meta.write_text(meta.read_text(encoding="utf-8") + " ", encoding="utf-8")
        assert "~1 changed" in index_workspace(tmp)
        where = find_schema(tmp, "UsrPkg")
        assert "object in UsrPkg" in where and "Schemas/UsrPkg/metadata.json" in where
        assert "UsrTests_FormPage (page)" in where and "UsrPkgBusinessRule (rules)" in where
        assert "cultures" in where  # resource files folded into one line
        idx = PackageIndex(tmp / "UsrPkg")
        assert "UsrOrderStatus" in idx.schemas["UsrOrder"]["refs"]  # a lookup column refers by UId
        assert "no schema named Nope" in find_schema(tmp, "Nope")
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


CS = HERE / "fixtures" / "UsrPkg"


DATA = TOOLS / "data" / "tests" / "fixtures" / "UsrPkg"
OBJECTS = TOOLS / "objects" / "tests" / "fixtures" / "UsrPkg"


def test_index_binding_resources_and_format_rebuild():
    import json
    import shutil
    import tempfile
    from unittest.mock import patch
    from creatio_schemas.describe import lookups
    from creatio_schemas.resources import Resources

    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "UsrPkg"
        shutil.copytree(DATA, pkg)
        original = PackageIndex(pkg)
        original.refresh()
        assert [k["value"] for k in original.data["data"]["UsrStatus"]["keys"]] == ["New", "In progress", "Done"]
        binding = pkg / "Data" / "UsrStatus"
        desc = {"Descriptor": {"Schema": {"Name": "UsrOrderStatus"}, "Columns": [
            {"ColumnName": "Code", "ColumnUId": "usr-code"},
            {"ColumnName": "Name", "ColumnUId": "usr-name"},
        ]}}
        (binding / "descriptor.json").write_text(json.dumps(desc), encoding="utf-8")
        rows = {"PackageData": [
            {"Row": [{"SchemaColumnUId": "usr-code", "Value": "UsrFirst"}]},
            {"Row": [{"SchemaColumnUId": "usr-code", "Value": "UsrSecond"}]},
        ]}
        (binding / "data.json").write_text(json.dumps(rows), encoding="utf-8")
        localization = binding / "Localization"
        (localization / "data.json").write_text(json.dumps(rows), encoding="utf-8")
        idx = PackageIndex(pkg)
        idx.refresh()
        entry = idx.data["data"]["UsrStatus"]
        assert entry["rows"] == 2 and entry["columns"] == ["Code", "Name"]
        assert [k["value"] for k in entry["keys"]] == ["UsrFirst", "UsrSecond"]
        res = Resources(pkg / "Resources" / "UsrOrderStatus.Entity")
        resources = idx.schemas["UsrOrderStatus"]["resources"]
        assert resources == {"cultures": sorted(res.cultures), "keys": len(res.cultures.get("en-US", {})),
                             "missing": {c: len(keys) for c, keys in res.missing().items()}}
        assert "resources:" in find_schema(pkg, "UsrOrderStatus")
        assert "Data/UsrStatus (2 rows, UsrPkg)" in find_schema(pkg, "UsrOrderStatus")
        with patch("creatio_schemas.describe.index.read_text", side_effect=AssertionError("unexpected file read")):
            assert "Data/UsrStatus (2 rows)" in lookups(pkg)
        from creatio_schemas.describe import store  # S26-T01: the index is rows of the store, not a JSON file
        old = store.load_package(idx.path, pkg.name)
        old["format"] = 1
        old["data"]["UsrStatus"]["rows"] = 99
        store.save_package(idx.path, pkg.name, old)
        rebuilt = PackageIndex(pkg)
        rebuilt.refresh()
        assert rebuilt.data["format"] == INDEX_FORMAT and rebuilt.data["data"]["UsrStatus"]["rows"] == 2
        assert store.load_package(idx.path, pkg.name)["format"] == INDEX_FORMAT


def test_data_bindings_answer_columns_and_rows():
    assert describe_schema(DATA, "UsrStatus").startswith("UsrStatus: binds UsrOrderStatus, 3 rows, columns Id Name(loc) Description(loc)")
    listed = describe_package(DATA, "data")
    assert "  data      UsrStatus" in listed and "SysSettings_UsrMaxRows" in listed and len(listed.splitlines()) == 4
    cols = describe_item(DATA, "UsrStatus", "columns")
    assert cols.splitlines()[0].startswith("Id ") and "key" in cols.splitlines()[0] and "(loc)" in cols
    rows = describe_item(DATA, "UsrStatus", "rows limit=1 culture=en-US")
    assert len(rows.splitlines()) == 2 and rows.endswith("... 2 more; add limit=0 for all") and 'Name="New"' in rows
    key = rows.splitlines()[0].split()[0]
    assert "Name = " in describe_item(DATA, "UsrStatus", f"row {key}")
    try:
        describe_item(DATA, "UsrStatus", "row nope")
        raise AssertionError("expected QueryError")
    except QueryError:
        pass


CLASSIC = TOOLS / "classicui" / "tests" / "fixtures" / "UsrPkg"


def test_classic_ui_schemas_answer_diff_and_methods():
    listed = describe_package(CLASSIC)
    assert "  classic   UsrOrderPage" in listed and "diff operations" in listed and "  classic   UsrOrderSection" in listed
    assert describe_schema(CLASSIC, "UsrOrderPage").startswith("UsrOrderPage:")
    diff = describe_item(CLASSIC, "UsrOrderPage", "diff op=insert")
    assert diff.splitlines() and all(line.startswith("insert ") for line in diff.splitlines())
    first = diff.splitlines()[0].split()[1]
    assert first in describe_item(CLASSIC, "UsrOrderPage", f"element {first}") and "values" in describe_item(CLASSIC, "UsrOrderPage", f"element {first}")
    methods = describe_item(CLASSIC, "UsrOrderPage", "methods")
    name = methods.splitlines()[0].split()[0]
    assert describe_item(CLASSIC, "UsrOrderPage", f"method {name}").startswith(name)
    assert "diff" in describe_item(CLASSIC, "UsrOrderPage", "topics") and "details" in describe_item(CLASSIC, "UsrOrderPage", "topics")
    try:
        describe_item(CLASSIC, "UsrOrderPage", "element Nope")
        raise AssertionError("expected QueryError")
    except QueryError:
        pass


def test_keys_topic_names_the_metadata_keys():
    full = describe_item(CS, "UsrOrderService", "keys")  # a source code schema made as full JSON
    assert "A2           Name" in full and "B6           PackageUId" in full and "B8           CreatedInVersion" in full
    diff = describe_item(PAGES, "UsrOrder", "keys")  # an object made in the designer: a diff against its parent
    assert diff.startswith("diff form against the parent's metadata") and "= A5                     CreatedInPackageId" in diff and "+ D2 " in diff
    assert describe_item(TOOLS / "sqlscripts" / "tests" / "fixtures" / "UsrPkg", describe_package(TOOLS / "sqlscripts" / "tests" / "fixtures" / "UsrPkg", "sql").splitlines()[1].split()[1], "keys") == "(no metadata.json)"


def test_lookups_follow_the_parent_chain():
    from creatio_schemas.describe import lookups
    out = lookups(PAGES)
    assert out.splitlines()[0].startswith("1 lookups in UsrPkg")
    assert "  UsrOrderStatus" in out and "parent BaseLookup" in out and "0 own columns" in out and "bindings: none" in out and "used by 1" in out
    assert "not decided" not in out
    cli = io.StringIO()
    with contextlib.redirect_stdout(cli):
        assert main(["lookups", str(PAGES)]) == 0
    assert "UsrOrderStatus" in cli.getvalue()


def test_csharp_by_signatures():
    out = describe_package(CS)
    assert "  source    UsrOrderService" in out and "DTO, web service; 3 methods" in out
    assert "  csharp    Files/cs/UsrOrderEventListener.cs" in out and "entity event listener of UsrOrder; 3 methods" in out
    assert len(describe_package(CS, "csharp").splitlines()) == 3
    text = describe_schema(CS, "UsrOrderService")
    assert "[ServiceContract] [AspNetCompatibilityRequirements] public class UsrOrderService : BaseService  - web service, 3 members" in text
    assert "[OperationContract] [WebInvoke] public OrderLabelResponse GetLabel(string orderId)  (42)" in text
    assert "operations: ESQ read, Update (raw SQL)" in text
    # a plain file by path, by file name or by stem; nested types, enums, expression-bodied members, comments with braces
    for name in ("Files/cs/UsrOrderLabel.cs", "UsrOrderLabel.cs", "UsrOrderLabel"):
        label = describe_schema(CS, name)
        assert "public static class UsrOrderLabel  - static helper, 6 members, lines 22-46" in label
        assert "    private class Cache  - class, 2 members" in label and "values: Short, Padded" in label
        assert "method      public static bool IsLabel(string text)  (34)" in label
    assert describe_item(CS, "UsrOrderLabel", "member UsrOrderLabel.Build").startswith("public static string Build(string type, int seq) {")
    assert describe_item(CS, "UsrOrderLabel", "member UsrOrderLabel.Build").rstrip().endswith("}")
    assert describe_item(CS, "UsrOrderLabel", "member Build").count("Build(") == 2  # the interface's and the class's
    members = describe_item(CS, "UsrOrderService", "members UsrOrderService kind=method visibility=public")
    assert "GetLabel" in members and "RebuildAll" in members and "ReadOrder" not in members
    assert describe_item(CS, "UsrOrderService", "operations").splitlines()[1].strip().startswith("59  Update (raw SQL)")
    assert "entity event listener of UsrOrder" in describe_item(CS, "UsrOrderEventListener", "classes")
    assert describe_item(CS, "UsrOrderLabel", "regions") == "(no regions)" and len(describe_item(CS, "UsrOrderService", "regions").splitlines()) == 4
    assert "   25  private static readonly string Separator" in describe_item(CS, "UsrOrderLabel", "find Separator")
    assert "Terrasoft.Core.Entities.Events" in describe_item(CS, "UsrOrderEventListener", "usings")
    try:
        describe_item(CS, "UsrOrderLabel", "member Nope")
        raise AssertionError("expected QueryError")
    except QueryError as exc:
        assert "no member Nope" in str(exc) and "UsrOrderLabel.Build" in str(exc)
    idx = PackageIndex(CS)
    idx.refresh()
    assert idx.schemas["UsrOrderService"]["kind"] == "source" and "web service" in idx.schemas["UsrOrderService"]["summary"]
    # Files/cs files are index items of their own: one file, no descriptor, no resources; referred to by their types
    label = idx.schemas["Files/cs/UsrOrderLabel.cs"]
    assert label["kind"] == "csharp" and list(label["files"]) == ["Files/cs/UsrOrderLabel.cs"] and label["caption"] == "" and label["manager"] is None
    assert "Files/cs/UsrOrderLabel.cs" in idx.schemas["UsrOrderService"]["refs"]  # the service calls UsrOrderLabel.Build
    found = find_schema(CS, "UsrOrderLabel")
    assert found.startswith("Files/cs/UsrOrderLabel.cs  csharp in UsrPkg") and "used by: UsrOrderService (source)" in found
    assert find_schema(CS, "UsrOrderLabel.cs").splitlines()[0] == found.splitlines()[0]
    assert "refers to: Files/cs/UsrOrderLabel.cs" in find_schema(CS, "UsrOrderService")


def test_broken_items_cost_one_line_each():
    import shutil
    import tempfile
    from creatio_schemas.csharp import CSharpSource
    from creatio_schemas.data import DataBinding
    from creatio_schemas.describe import lookups

    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "packages" / "UsrPkg"
        shutil.copytree(DATA, pkg)
        shutil.copytree(CS / "Files", pkg / "Files", dirs_exist_ok=True)
        (pkg / "Data" / "UsrEmpty").mkdir()
        shutil.copy(pkg / "Data" / "UsrStatus" / "descriptor.json", pkg / "Data" / "UsrEmpty" / "descriptor.json")
        (pkg / "Data" / "UsrEmpty" / "data.json").write_bytes(b"")  # an empty data.json
        (pkg / "Data" / "UsrNoDescriptor").mkdir()  # a Data folder without its descriptor
        (pkg / "Data" / "UsrNoDescriptor" / "data.json").write_text("{}", encoding="utf-8")
        cs = pkg / "Files" / "cs"
        (cs / "UsrLegacy.cs").write_bytes("namespace Terrasoft.Configuration\r\n{\r\n\t// Комментарий в кодировке Windows\r\n"
                                          "\tpublic class UsrLegacy\r\n\t{\r\n\t\tpublic string Hello() {\r\n\t\t\treturn \"Привет\";\r\n\t\t}\r\n\t}\r\n}\r\n".encode("cp1251"))
        (cs / "UsrBroken.cs").write_bytes(b"public class UsrBroken { \x98\xff }")  # 0x98 is undefined in cp1251 too
        (cs / "UsrTuple.cs").write_text("public class UsrTuple\r\n{\r\n\tprivate (string url, Guid id) GetPair() {\r\n\t\treturn (\"\", Guid.Empty);\r\n\t}\r\n"
                                        "\tpublic UsrTuple(int a) : base(a) {\r\n\t}\r\n}\r\npublic enum UsrState { New, Done = 2 }\r\n", encoding="utf-8")

        legacy = CSharpSource(pkg, cs / "UsrLegacy.cs")
        assert legacy.error is None and "Привет" in legacy.text and [m["name"] for m in legacy.members()] == ["Hello"]
        broken = CSharpSource(pkg, cs / "UsrBroken.cs")
        assert broken.summary().startswith("unreadable: UnicodeDecodeError") and broken.types == []
        tup = CSharpSource(pkg, cs / "UsrTuple.cs")  # the IndexError of a tuple return type, the KeyError of an enum value's source
        assert [(m["kind"], m["name"]) for m in tup.members("UsrTuple")] == [("method", "GetPair"), ("constructor", "UsrTuple")]
        assert tup.member("Done") == "Done = 2" and tup.member("New") == "New"
        for name, text in (("UsrEmpty", "empty file"), ("UsrNoDescriptor", "descriptor.json: missing")):
            try:
                DataBinding(pkg, name)
            except ValueError as e:
                assert text in str(e) and name in str(e), e
            else:
                raise AssertionError(name)

        listing = describe_package(pkg)
        assert "Files/cs/UsrLegacy.cs" in listing and "(cp1251)" in listing.split("Files/cs/UsrLegacy.cs")[1].splitlines()[0], listing
        assert "cannot read: UnicodeDecodeError" in listing and "Data/UsrEmpty" in listing and "Data/UsrNoDescriptor" in listing
        errors = describe_package(pkg, "error")
        assert len(errors.splitlines()) == 4 and "Files/cs/UsrBroken.cs" in errors and "empty file" in errors, errors
        where = find_schema(pkg, "UsrOrderStatus")
        assert "bindings: Data/UsrStatus (3 rows" in where and where.endswith(f"3 items unreadable (describe.py package {pkg} --kind error lists them)"), where
        assert find_schema(pkg, "UsrBroken.cs").startswith("Files/cs/UsrBroken.cs  cannot read, in UsrPkg: UnicodeDecodeError")
        lk = lookups(pkg)
        assert "UsrOrderStatus" in lk and "bindings: Data/UsrStatus (3 rows)" in lk and lk.endswith("3 items unreadable (describe.py package "
                                                                                                    f"{pkg} --kind error lists them)"), lk
        assert describe_item(pkg, "UsrOrderStatus", "columns")  # the rest of the package still answers
        (pkg / "Data" / "UsrEmpty" / "data.json").write_text('{"PackageData": []}', encoding="utf-8")
        assert find_schema(pkg, "UsrOrderStatus").endswith("2 items unreadable (describe.py package " f"{pkg} --kind error lists them)")


LAYER_RULE = "0b7c2c9e-4c1d-4b8e-9f3a-1d2e3f4a5b6c"


def _layer_body(props: str) -> str:
    rule = f'"{LAYER_RULE}": {{"uId": "{LAYER_RULE}"{props}}}' if props is not None else ""
    return ('define("UsrMyEntity1Page", [], function() {\n\treturn {\n\t\tbusinessRules: /**SCHEMA_BUSINESS_RULES*/{\n'
            f'\t\t\t"Owner": {{{rule}}}\n\t\t}}/**SCHEMA_BUSINESS_RULES*/,\n\t\tdiff: /**SCHEMA_DIFF*/[]/**SCHEMA_DIFF*/\n\t}};\n}});\n')


class FakeLayersEnv:
    """The layers query answers `rows`; a chunk read of body.py answers the `body` of the row whose id it names (S48-T04)."""
    clio_name, url = "dev", "https://dev.example/"

    def __init__(self, rows, count="0"):
        self.rows, self.sql_text, self.count = rows, [], count
        self.bodies = {r["id"]: r.get("body", "").encode("utf-8") for r in rows if "id" in r}

    def sql(self, text):
        import base64
        import hashlib
        import re

        from creatio_schemas.describe.body import CHUNK
        self.sql_text.append(text)
        if '"b64"' in text:
            first, last = map(int, re.search(r"generate_series\((\d+), (\d+)\)", text).groups())
            data = self.bodies[re.search(r'"Id" = \'([^\']*)\'', text).group(1)]
            return [{"i": str(i), "b64": base64.encodebytes(data[i * CHUNK:(i + 1) * CHUNK]).decode(), "md5": hashlib.md5(data).hexdigest()}
                    for i in range(first, last + 1) if i * CHUNK < len(data)]
        if 'count(*)::text "n"' in text:
            return [{"n": self.count}]
        return self.rows


def _row(pkg, sl, pl, body="", ext="true"):
    return {"id": pkg, "package": pkg, "extendParent": ext, "modifiedOn": "2026-11-10 09:15:00.123", "modifiedBy": "Supervisor", "isChanged": "false",
            "manager": "ClientUnitSchemaManager", "size": str(len(body)), "md5": "0123456789abcdef0123456789abcdef", "body": body, "sl": sl, "pl": pl}


def test_layers_order_rule_states_and_the_custom_layer():
    from creatio_schemas.describe.layers import layers_sql, render, rule_state, schema_layers, to_json
    import creatio_schemas.environment as environment
    import json

    sql = layers_sql("UsrO'Page", "Custom")
    assert "body" not in sql and "convert_from" not in sql  # no body column: the bodies come one layer at a time, only for --rule (S48-T04)
    assert "where s.\"Name\" = 'UsrO''Page'" in sql and "\"SysSchemaContent\"" in sql and "md5(" in sql and "(select \"Id\" from \"SysPackage\" where \"Name\" = 'Custom')" in sql
    assert rule_state("", LAYER_RULE) == "no body" and rule_state(_layer_body(None), LAYER_RULE) == "absent"
    assert rule_state(_layer_body(""), LAYER_RULE) == "enabled" and rule_state(_layer_body(', "enabled": false'), LAYER_RULE) == "disabled"
    assert rule_state(_layer_body(', "enabled": true, "removed": true'), LAYER_RULE) == "removed"
    assert rule_state("not a module at all", LAYER_RULE) == "absent"
    rows = [_row("Custom", "0", "0", _layer_body(', "removed": true')), _row("CrtBase", "1", "5", _layer_body(""), ext="false"),
            _row("UsrPkg", "0", "2", _layer_body(', "enabled": false')), _row("UsrOrphan", "-1", "-1")]
    env = FakeLayersEnv(rows)
    result = schema_layers(env, "UsrMyEntity1Page", LAYER_RULE)
    assert "UsrMyEntity1Page" in env.sql_text[0] and sum('"b64"' in s for s in env.sql_text) == 4  # one read per layer
    # outside the hierarchy first, then farthest first: the base (schema level 1), package level descending; Custom last
    assert [x["package"] for x in result["layers"]] == ["UsrOrphan", "CrtBase", "UsrPkg", "Custom"]
    assert [x["rule"] for x in result["layers"]] == ["no body", "enabled", "disabled", "removed"] and result["custom"] == ["Custom"]
    assert result["layers"][1]["level"] == 5 and result["layers"][0]["level"] is None and "body" not in result["layers"][0]
    text = render(result, "dev")
    assert text.splitlines()[0] == "UsrMyEntity1Page on dev: 4 copies, applied first to last (the last one wins)"
    assert "replacing" in text.splitlines()[1] and "01234567 " in text and "2026-11-10 09:15:00 " in text and text.endswith("Custom layer present: Custom - it cannot be deleted by the tools; the human removes it on the site")
    assert json.loads(to_json(result))["custom"] == ["Custom"]
    assert render(schema_layers(FakeLayersEnv([]), "UsrNope"), "dev") == "UsrNope on dev: no SysSchema copy of that name"
    plain = schema_layers(FakeLayersEnv(rows[1:3]), "UsrMyEntity1Page")
    assert plain["custom"] == [] and "rule" not in plain["layers"][0] and "Custom layer" not in render(plain)
    # a chain UsrA < UsrB < UsrC: the design-time function gives B and C the same levels and returned C first; the runtime
    # folds by SysPackage.HierarchyLevel, then the name - the order merge's layers_in_order uses (S27-T09 / S44 INBOX line)
    chain = [dict(_row("CrtBase", "1", "5", ext="false"), hl="3"), dict(_row("UsrA", "0", "2"), hl="23"),
             dict(_row("UsrC", "0", "1"), hl="30"), dict(_row("UsrB", "0", "1"), hl="29")]
    assert [x["package"] for x in schema_layers(FakeLayersEnv(chain), "UsrMyEntity1Page")["layers"]] == ["CrtBase", "UsrA", "UsrB", "UsrC"]
    chain[3]["hl"] = ""  # a level missing: the function's order stays
    assert [x["package"] for x in schema_layers(FakeLayersEnv(chain), "UsrMyEntity1Page")["layers"]] == ["CrtBase", "UsrA", "UsrC", "UsrB"]
    # 8.3.2 (S48-T08): the base copy levelled after replacing ones, copies outside the customisation package's hierarchy;
    # the served body holds the base first, then every replacing copy by HierarchyLevel
    site = [dict(_row("UsrC", "-1", "-1"), hl="363"), dict(_row("UsrA", "0", "2"), hl="107"), dict(_row("CrtBase", "0", "16", ext="false"), hl="81"),
            dict(_row("UsrB", "-1", "-1"), hl="168")]
    assert [x["package"] for x in schema_layers(FakeLayersEnv(site), "UsrMyEntity1Page")["layers"]] == ["CrtBase", "UsrA", "UsrB", "UsrC"]
    assert '"HierarchyLevel"::text "hl"' in layers_sql("UsrX", "Custom")
    # the customisation package named by project.json, not by the default
    assert schema_layers(FakeLayersEnv(rows), "UsrMyEntity1Page", custom_layer="UsrPkg")["custom"] == ["UsrPkg"]

    original = environment.open_environment
    try:
        seen = {}

        def fake_open(env_name=None, project=None, **kw):
            seen.update(env=env_name, project=project)
            if not env_name and not project:
                raise ValueError("name the environment")
            return FakeLayersEnv(rows)
        environment.open_environment = fake_open
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            assert main(["layers", "UsrMyEntity1Page", "-e", "dev", "--rule", LAYER_RULE]) == 1  # Custom has a copy
            assert main(["layers", "UsrMyEntity1Page", "-e", "dev", "--custom-layer", "UsrNoSuchPkg"]) == 0
            assert main(["layers", "UsrMyEntity1Page"]) == 2
        text = out.getvalue()
        assert "rule " + LAYER_RULE + ": removed in the layer applied last (Custom)" in text and "Custom layer present: Custom - it cannot be deleted by the tools; the human removes it on the site" in text
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project.json"
            project.write_text(json.dumps({"environment": {"clioName": "dev", "customLayer": "UsrPkg"}}), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                assert main(["layers", "UsrMyEntity1Page", "--project", str(project), "--json"]) == 1
            assert json.loads(out.getvalue())["custom"] == ["UsrPkg"] and seen["project"] == str(project)
    finally:
        environment.open_environment = original


def test_a_failed_layers_query_answers_why_never_no_copy():
    import json

    from creatio_schemas.describe.layers import schema_layers
    from creatio_schemas.environment import Environment

    def failure(outputs):
        """The error of schema_layers over a scripted clio: each call takes the next (exit code, text, rows or None)."""
        def clio_run(args):
            code, text, rows = outputs.pop(0)
            if rows is not None:
                Path(args[args.index("-d") + 1]).write_text(json.dumps(rows), encoding="utf-8")
            return code, text
        try:
            schema_layers(Environment("https://s", "u", "p", clio_name="dev", clio_run=clio_run), "UsrOrderPage")
        except RuntimeError as e:
            return str(e)
        raise AssertionError("expected RuntimeError")

    # a PostgreSQL site whose clio prints the database line without [ERR] and exits 0: the line, no note
    pg_error = "42883: function tsp_UsrNoSuchFunction(unknown) does not exist\nDone"
    text = failure([(0, pg_error, None), (0, "Done", [{"v": "PostgreSQL 16.4, compiled by msvc, 64-bit"}])])
    assert text == "the layers query failed on dev: 42883: function tsp_UsrNoSuchFunction(unknown) does not exist", text
    # MS SQL: its `Msg N, Level N` line is the error, and version() fails as well - the PostgreSQL note comes first
    mssql = "Msg 102, Level 15, State 1, Line 1\nIncorrect syntax near '::'.\nDone"
    text = failure([(0, mssql, None), (0, "Msg 195, Level 15, State 10, Line 1\n'version' is not a recognized built-in function name.", None)])
    assert text == "dev is not PostgreSQL - the kit's site SQL is PostgreSQL\nthe layers query failed on dev: Msg 102, Level 15, State 1, Line 1", text
    assert "no SysSchema copy" not in text
    # no rows while SysSchema counts copies of the name: clio's answer was lost, not "no copy" (S48-T04)
    try:
        schema_layers(FakeLayersEnv([], count="8"), "ActivityMiniPage")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "clio's answer had no rows while SysSchema holds copies of that name" in str(e), e


def test_body_reads_one_copy_in_chunks_and_lists_several():
    from creatio_schemas.describe.body import CHUNK, PER_CALL, schema_body

    big = "// UsrOrderPage\r\n" + "ä" * (CHUNK * PER_CALL)  # more than one call of chunks, a two-byte character across chunk edges
    copies = [_row("UsrPkg", "0", "1", big), _row("CrtBase", "1", "5", "{}", ext="false")]

    class BodyEnv(FakeLayersEnv):
        def sql(self, text):
            rows = super().sql(text)
            return [dict(r, size=str(len(r["body"].encode()))) for r in rows] if rows is self.rows else rows
    env = BodyEnv(copies)
    assert schema_body(env, "UsrOrderPage", "usrpkg") == big and sum('"b64"' in s for s in env.sql_text) == 3  # 21 chunks: 10 + 10 + 1
    assert "UsrOrderPage" in env.sql_text[0] and "'SourceCodeSchemaManager'" in env.sql_text[0] and '"MetaData"' in env.sql_text[0]
    assert schema_body(BodyEnv(copies[1:]), "Contact") == "{}"
    try:
        schema_body(BodyEnv(copies), "UsrOrderPage")
        raise AssertionError("expected LookupError")
    except LookupError as e:
        assert str(e).splitlines()[0] == "UsrOrderPage: 2 copies on the site - name one with --package:" and "  CrtBase  2 bytes  md5 01234567  2026-11-10 09:15:00" in str(e), e
    try:
        schema_body(BodyEnv(copies), "UsrOrderPage", "UsrNoSuchPkg")
        raise AssertionError("expected KeyError")
    except KeyError as e:
        assert e.args[0] == "UsrOrderPage has no copy in package UsrNoSuchPkg on the site"
    env = BodyEnv(copies)
    env.bodies["UsrPkg"] = env.bodies["UsrPkg"][:-1] + b"x"  # a chunk lost or changed on the way: the md5 says so
    env.sql = lambda text, sql=env.sql: [dict(r, md5="0" * 32) for r in sql(text)] if '"b64"' in text else sql(text)
    try:
        schema_body(env, "UsrOrderPage", "UsrPkg")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "do not match the site's md5" in str(e), e
    import creatio_schemas.environment as environment
    import tempfile
    original = environment.open_environment
    try:
        environment.open_environment = lambda env_name=None, project=None, **kw: BodyEnv(copies)
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                assert main(["body", "UsrOrderPage", "-e", "dev"]) == 1  # several copies: the list
                assert main(["body", "UsrOrderPage", "-e", "dev", "--package", "CrtBase"]) == 0
                assert main(["body", "UsrOrderPage", "-e", "dev", "--package", "UsrPkg", "--out", str(Path(tmp) / "b.js")]) == 0
            assert "  UsrPkg  " in out.getvalue() and "{}\n" in out.getvalue(), out.getvalue()
            assert (Path(tmp) / "b.js").read_bytes() == big.encode("utf-8")
    finally:
        environment.open_environment = original


def test_typed_dependencies_resolve_by_uid_and_context():
    from creatio_schemas.describe.deps import Edge, dependencies
    # an object: parent and lookups by UId (the stock asset names Contact and BaseEntity), merged per target
    out = dependencies(PAGES, "UsrOrder")
    assert "  object BaseEntity  parent" in out and "  object Contact  lookup: CreatedBy, ModifiedBy, UsrContact, UsrManager" in out
    assert "  object UsrOrderStatus  lookup: UsrStatus" in out and "  page UsrOrder_FormPage  data-source: PDS  [name]" in out
    # a page: every data source by name, its attribute columns proved on that object's effective columns
    out = dependencies(PAGES, "UsrTests_FormPage", "out")
    assert "  object UsrPkg  data-source: PDS, UsrName, UsrComment" in out and "UsrName?" not in out and "  page PageWithTabsFreedomTemplate  parent" in out
    assert "  object SysFile  data-source: AttachmentListDS, Name  [name]" in out and "dependents" not in out  # a stock object: its columns from the stock catalogue
    assert "  object UsrOrder  data-source: UsrOrderListDS, UsrName, UsrQuantity  [name]" in out  # the data source's own attributes are columns too
    from creatio_schemas.describe.deps import Resolver
    from creatio_schemas.workspace import Workspace
    r = Resolver(Workspace(PAGES))
    assert r.column_names("UsrOrder", ["UsrStatusId", "UsrStatus.Name", "Nope", "null", "ModifiedById"]) == ["UsrStatusId", "UsrStatus.Name", "Nope?", "ModifiedById"]
    # filters, direction and the topic form
    assert dependencies(PAGES, "UsrOrderStatus", "in", kind="object").splitlines() == ["UsrOrderStatus  object in UsrPkg", "dependents:", "  object UsrOrder  lookup: UsrStatus"]
    assert "dependents: nothing typed in the workspace of kind process" in dependencies(PAGES, "UsrOrderStatus", "in", kind="process")
    assert describe_item(PAGES, "UsrOrder_FormPage", "uses via=data-source").endswith("  object UsrOrder  data-source: PDS  [name]")
    assert dependencies(PAGES, "Nope").startswith("no schema named Nope")
    # other kinds: a process data element, a Classic page's details and mixin, a data binding, a C# listener
    assert "  object 368340c2-dddc-46fe-ac7f-d3485b497f95  delete-data: DeleteDataUserTask1" in dependencies(PROCS, "UsrDeleteOldLogs_Process", "out")
    classic = dependencies(TOOLS / "classicui" / "tests" / "fixtures" / "UsrPkg", "UsrOrderPage", "out")
    assert "  page UsrOrderProductDetailV2  detail: UsrOrderProductDetail  [name]" in classic and "  page UsrPrintMixin  mixin: UsrPrintMixin  [name]" in classic
    assert "  object UsrOrder  entity  [name]" in classic and "  page BasePageV2  parent  [name]" in classic
    assert "  object UsrOrderStatus  binds: Id, Name, Description  [name]" in dependencies(TOOLS / "data" / "tests" / "fixtures" / "UsrPkg", "Data/UsrStatus", "out")
    assert "  object UsrOrder  listener: UsrOrderEventListener, UsrStatusId?, UsrAmount?  [name]" in dependencies(CS, "Files/cs/UsrOrderEventListener.cs", "out")
    # the edges live in the index and find_schema shows both directions
    idx = PackageIndex(PAGES)
    idx.refresh()
    assert idx.data["format"] == INDEX_FORMAT and {d["via"] for d in idx.schemas["UsrOrder"]["deps"]} == {"parent", "lookup"}
    assert idx.dependents("UsrOrder")[0][:2] == ("page", "UsrOrder_FormPage")
    assert Edge.from_dict(idx.schemas["UsrOrder"]["deps"][1]).line().startswith("object ")
    found = find_schema(PAGES, "UsrOrder")
    assert "  depends on: object BaseEntity  parent; object Contact  lookup" in found and "  dependents: page UsrOrder_FormPage (data-source); page UsrTests_FormPage (data-source)" in found


TEXT_CS = """namespace Terrasoft.Configuration
{
	[EntityEventListener(SchemaName = "UsrOrder")]
	public class UsrOrderListener : BaseEntityEventListener
	{
		public override void OnSaving(object sender, EntityBeforeEventArgs e) {
			var order = (Entity)sender;
			Guid status = order.GetTypedColumnValue<Guid>("UsrStatusId");
			order.SetColumnValue("UsrNope", 1);
		}
	}

	public class UsrQueries
	{
		public void Run(UserConnection uc) {
			var esq = new EntitySchemaQuery(uc.EntitySchemaManager, "UsrPkg");
			esq.AddColumn("UsrName");
			esq.AddColumn("UsrContactLookup.Name");
			var update = new Update(uc, "UsrOrderStatus").Set("Name", Column.Parameter("x")).Set("UsrMissing", Column.Parameter(1));
			var joined = new Select(uc).Column("Id").From("UsrOrder").InnerJoin("UsrPkg").On("UsrPkg", "Id").IsEqual("UsrOrder", "Id");
			var process = uc.ProcessSchemaManager.GetInstanceByName("UsrTest_Process");
			string again = "UsrOrderStatus";
			// "UsrOrder" in a comment is no word of the code
		}
	}
}
"""


def test_text_extractors_add_words_of_code_sql_and_rules():
    import shutil
    import tempfile
    from creatio_schemas.describe.deps import Edge, Resolver, _merge, _sql_tables
    from creatio_schemas.process import ProcessSchema
    from creatio_schemas.workspace import Workspace

    assert [e.ref for e in _merge([Edge("object", "A", None, "x", "text"), Edge("object", "a", "u1", "x", "name"), Edge("object", "A", None, "x", "text")])] == ["name"]
    assert _merge([Edge("object", "A", None, "x", "text"), Edge("object", "A", "u1", "x", "uid")])[0].to_uid == "u1"
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "packages" / "UsrPkg"
        shutil.copytree(PAGES, pkg)
        (pkg / "Files" / "cs").mkdir(parents=True)
        (pkg / "Files" / "cs" / "UsrText.cs").write_text(TEXT_CS, encoding="utf-8")
        out = dependencies_out(pkg, "Files/cs/UsrText.cs")
        assert "  object UsrOrder  listener: UsrOrderListener, UsrStatus, UsrNope?  [name]" in out, out  # UsrStatusId is the lookup UsrStatus
        assert "  object UsrPkg  esq: UsrName, UsrContactLookup.Name  [name]" in out  # a path: its first part is checked
        assert "  object UsrOrderStatus  query: Name, UsrMissing?  [name]" in out
        assert "  object UsrOrder  query  [name]" in out and "  object UsrPkg  query  [name]" in out  # a join: two tables, no columns
        assert "UsrTest_Process" not in out and "string" not in out  # another manager's schema; a word already reached
        (pkg / "Files" / "cs" / "UsrText.cs").write_text(TEXT_CS.replace('"UsrOrderStatus";', '"UsrTests_FormPage"; string w = "UsrOrderStatus" + "x";')
                                                       .replace('new Update(uc, "UsrOrderStatus")', 'new Update(uc, "UsrOther")'), encoding="utf-8")
        out = dependencies_out(pkg, "Files/cs/UsrText.cs")
        assert "  object UsrOrderStatus  string  [text]" in out and "UsrTests_FormPage" not in out, out  # a page name is no object
        # SQL: tables of every statement form, quoted or not; a comment, a string and a CTE are not tables
        r = Resolver(Workspace(pkg))
        sql = ('-- update "UsrPkg"\nwith cte as (select 1)\ninsert into "UsrOrder" ("Name") select "Name" from cte join usrorderstatus s on true;\n'
               "update [dbo].[UsrPkg] set x = 'from \"Contact\"';\ndelete from public.\"Contact\";\nalter table if exists \"UsrNoSuch\" add y int;\n")
        assert [e.line() for e in _sql_tables(sql, r)] == ["object UsrOrder  table  [text]", "object UsrOrderStatus  table  [text]",
                                                           "object UsrPkg  table  [text]", "object Contact  table  [text]"]
        # Freedom page: a workspace client schema in SCHEMA_DEPS is a module; a package of the devkit is not
        page = pkg / "Schemas" / "UsrTests_FormPage" / "UsrTests_FormPage.js"
        page.write_text(page.read_text(encoding="utf-8").replace("/**SCHEMA_DEPS*/[]", '/**SCHEMA_DEPS*/["@creatio-devkit/common", "UsrOrder_FormPage"]', 1), encoding="utf-8")
        assert "  page UsrOrder_FormPage  module  [name]" in dependencies_out(pkg, "UsrTests_FormPage")
    # a process script task: the same words, the element first
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "packages" / "UsrPkg"
        shutil.copytree(PROCS, pkg)
        proc = ProcessSchema(pkg, "UsrProcess_0d4c445")
        proc.add_element("script", "ScriptTask1")
        proc.set_script("ScriptTask1", 'var esq = new EntitySchemaQuery(UserConnection.EntitySchemaManager, "Contact");\nesq.AddColumn("Name");\nesq.AddColumn("UsrNope");\nreturn true;')
        proc.save()
        contact = next(l for l in dependencies_out(pkg, "UsrProcess_0d4c445").splitlines() if l.startswith("  object Contact  esq:"))
        assert contact == "  object Contact  esq: ScriptTask1, Name, UsrNope?  [name]", contact  # a stock object: the stock catalogue's columns (S20-T04)
    # rules: an object's rule names its columns; a page rule's attributes reach the data source's object
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "packages" / "UsrPkg"
        shutil.copytree(RULES, pkg)
        assert "  object UsrPkg  column: UsrNumber, UsrIsActive, UsrName, UsrComment, UsrContactLookup, UsrAccount, UsrContactLookup.Account, UsrAmount  [name]" in dependencies_out(pkg, "UsrPkgBusinessRule")
        out = dependencies_out(pkg, "UsrTests_FormPageBusinessRule")
        assert "  page UsrTests_FormPage  target" in out and "  object UsrPkg  column: UsrIsActive, UsrNumber  [name]" in out
    # Classic: the columns rules bind, a lookup attribute's object; messages give nothing
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "packages" / "UsrPkg"
        shutil.copytree(CLASSIC, pkg)
        js = pkg / "Schemas" / "UsrOrderPage" / "UsrOrderPage.js"
        js.write_text(js.read_text(encoding="utf-8").replace('"UsrStatus": {\n\t\t\t\t\tlookupListConfig', '"UsrStatus": {\n\t\t\t\t\treferenceSchemaName: "UsrOrderStatus",\n\t\t\t\t\tlookupListConfig', 1)
                      .replace("businessRules: /**SCHEMA_BUSINESS_RULES*/{}", 'businessRules: /**SCHEMA_BUSINESS_RULES*/{"UsrTotal": {"Bind": {"conditions": '
                               '[{"leftExpression": {"attribute": "UsrAmount"}}]}}}', 1), encoding="utf-8")
        out = dependencies_out(pkg, "UsrOrderPage")
        assert "  object UsrOrderStatus  lookup: UsrStatus  [name]" in out, out
        assert "  object UsrOrder  rule: UsrTotal?, UsrAmount?, UsrStatus?, UsrNumber?  [name]" in out  # UsrOrder is not in this workspace: every column ends with ?
        assert "UsrOrderTotalChanged" not in out


def test_export_writes_a_file_per_item_and_removes_the_gone_ones():
    import shutil
    import tempfile
    from creatio_schemas.describe.export import default_out, export

    assert default_out(PAGES) == PAGES.resolve().parent / ".creatio-export"  # a package folder outside `packages/`: next to it
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "export"
        (out / "UsrPkg").mkdir(parents=True)
        (out / "UsrPkg" / "UsrGone.md").write_text("an item that no longer exists", encoding="utf-8")
        (out / "UsrPkg" / "notes.txt").write_text("not ours", encoding="utf-8")
        (out / "OtherPkg").mkdir()
        (out / "OtherPkg" / "X.md").write_text("another package's file", encoding="utf-8")
        assert export(PAGES, out) == f"6 files written, 1 removed, 1 package(s) -> {out}"
        files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
        assert files == ["OtherPkg/X.md", "UsrPkg/UsrOrder.md", "UsrPkg/UsrOrderStatus.md", "UsrPkg/UsrOrder_FormPage.md",
                         "UsrPkg/UsrPkg.md", "UsrPkg/UsrTests_FormPage.md", "UsrPkg/_package.md", "UsrPkg/notes.txt"], files
        text = (out / "UsrPkg" / "UsrOrder.md").read_bytes().decode("utf-8")
        assert "\r" not in text and text.startswith("# UsrOrder\n\n```text\nUsrOrder: 'Order'  own object")
        assert "\n## Depends on\n\n```text\nobject BaseEntity  parent\n" in text
        assert "\n## Dependents\n\n```text\npage UsrOrder_FormPage  data-source: PDS  [name]\n" in text
        assert f"\n## Files\n\n```text\n{PAGES.resolve() / 'Resources' / 'UsrOrder.Entity' / 'resource.en-US.xml'}  (" in text
        assert "  page      UsrTests_FormPage" in (out / "UsrPkg" / "_package.md").read_text(encoding="utf-8")
    # a data binding goes to Data/, an unreadable item is one line, the package file lists it; a gone binding's folder goes
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "packages" / "UsrPkg"
        shutil.copytree(DATA, pkg)
        (pkg / "Data" / "UsrEmpty").mkdir()
        shutil.copy(pkg / "Data" / "UsrStatus" / "descriptor.json", pkg / "Data" / "UsrEmpty" / "descriptor.json")
        (pkg / "Data" / "UsrEmpty" / "data.json").write_bytes(b"")
        out = Path(tmp) / "export"
        export(pkg, out)
        assert (out / "UsrPkg" / "Data" / "UsrEmpty.md").read_text(encoding="utf-8").startswith("Data/UsrEmpty: cannot read: ") and \
            len((out / "UsrPkg" / "Data" / "UsrEmpty.md").read_text(encoding="utf-8").splitlines()) == 1
        assert "## Cannot read" in (out / "UsrPkg" / "_package.md").read_text(encoding="utf-8")
        assert "binds UsrOrderStatus" in (out / "UsrPkg" / "Data" / "UsrStatus.md").read_text(encoding="utf-8")
        assert "data Data/UsrStatus  binds: Id, Name, Description  [name]" in (out / "UsrPkg" / "UsrOrderStatus.md").read_text(encoding="utf-8")
        for name in [p.name for p in (pkg / "Data").iterdir()]:
            shutil.rmtree(pkg / "Data" / name)
        assert export(pkg, out).split(", ")[1] == "4 removed" and not (out / "UsrPkg" / "Data").exists()
        assert default_out(pkg) == Path(tmp).resolve() / ".creatio-export"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            assert main(["export", str(pkg), "--out", str(out)]) == 0
        assert stdout.getvalue().startswith("2 files written, 0 removed")


def dependencies_out(path, name):
    from creatio_schemas.describe.deps import dependencies
    return dependencies(path, name, "out", limit=0)


def test_impact_lists_dependents_and_the_locks_of_other_active_tasks():
    import json
    import tempfile
    from creatio_schemas.describe.deps import impact
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        for folder, data, done in (("013-other", {"schemas": ["UsrOrder_FormPage"], "affects": ["UsrOrderStatus"]}, False),
                                   ("011-done", {"schemas": ["UsrOrder"]}, True), ("012-this", {"schemas": ["UsrOrder"]}, False)):
            (t / folder).mkdir()
            (t / folder / "schemas.json").write_text(json.dumps(data), encoding="utf-8")
            if done:
                (t / folder / "success-report.md").write_text("ok", encoding="utf-8")
        text, conflicts = impact(PAGES, ["UsrOrder", "UsrOrderStatus"], t, "012-this")
        assert conflicts == 1 and "    page UsrOrder_FormPage (data-source) - task 013-other changes it" in text
        assert "UsrOrderStatus  object in UsrPkg  [task 013-other depends on it]" in text and "    object UsrOrder (lookup)" in text
        assert "affects: UsrOrder_FormPage, UsrTests_FormPage" in text and "011-done" not in text  # a finished task locks nothing; what the task changes is not what it affects
        assert text.endswith("2 dependents of 2 schema(s); 1 conflict(s) with other active tasks")
        md, _ = impact(PAGES, ["UsrOrder"], t, "012-this", md=True)
        assert md.splitlines()[:4] == ["## Impact", "", "| Schema | Dependents | Other active tasks |", "|---|---|---|"]
        assert "| `UsrOrder` | page UsrOrder_FormPage (data-source), page UsrTests_FormPage (data-source) | task 013-other changes it (page UsrOrder_FormPage) |" in md
        # the current task's own lock is not a conflict; a schema another task changes is
        assert impact(PAGES, ["UsrOrder"], t, "012-this")[1] == 1 and impact(PAGES, ["UsrOrder_FormPage"], t, "012-this")[1] == 1
        assert impact(PAGES, ["UsrOrder_FormPage"], t, "013-other")[1] == 0
    text, conflicts = impact(PAGES, ["Nope"])
    assert text.startswith("Nope  (not in the workspace)") and conflicts == 0 and "locks not checked" in text
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["impact", str(PAGES), "UsrOrderStatus", "--md"]) == 0
    assert out.getvalue().startswith("## Impact")


def test_cli():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["deps", str(PAGES), "UsrOrder", "--in", "--kind", "page"]) == 0
    assert out.getvalue().splitlines()[:3] == ["UsrOrder  object in UsrPkg", "dependents:", "  page UsrOrder_FormPage  data-source: PDS  [name]"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["package", str(PAGES), "--kind", "page"]) == 0
        assert main(["find", str(PAGES), "UsrOrder"]) == 0
        assert main(["item", str(PAGES), "UsrOrder", "columns type=Lookup"]) == 0
    assert "UsrTests_FormPage" in out.getvalue() and "UsrStatus" in out.getvalue()
    with contextlib.redirect_stderr(io.StringIO()):
        assert main(["item", str(PAGES), "UsrOrder", "nonsense"]) == 2




def test_schema_diff_names_the_added_column_against_head_and_a_folder():
    import shutil
    import subprocess
    import tempfile

    from creatio_schemas.describe.diff import diff_lines, schema_diff
    from creatio_schemas.entity import EntitySchema

    assert diff_lines(["UsrA  Text 'A'", "UsrB  Text 'B'", "flows:"], ["UsrA  Text 'A2'", "UsrC  Int 'C'", "flows:"]) == [
        "~ UsrA  Text 'A' -> Text 'A2'", "- UsrB Text 'B'", "+ UsrC Int 'C'"]
    assert diff_lines(["x -> y", "x -> z"], ["x -> z", "x -> w"]) == ["- x -> y", "+ x -> w"]  # a repeated key: whole lines
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "packages" / "UsrPkg"
        shutil.copytree(OBJECTS, pkg)
        other = Path(tmp) / "packages" / "UsrOther"  # a lookup into another package: HEAD is extracted alone, the name must still resolve
        (other / "Schemas" / "UsrOtherStatus").mkdir(parents=True)
        (other / "descriptor.json").write_text('{"Descriptor": {"UId": "pkg-other", "Name": "UsrOther", "DependsOn": []}}', encoding="utf-8")
        (other / "Schemas" / "UsrOtherStatus" / "descriptor.json").write_text(
            '{"Descriptor": {"UId": "77777777-7777-4777-8777-777777777777", "Name": "UsrOtherStatus", "ManagerName": "EntitySchemaManager"}}', encoding="utf-8")
        entity = EntitySchema(pkg, "UsrOrder")
        entity.add_column("UsrOther", "Lookup", "Other", ref="UsrOtherStatus")
        entity.save()
        subprocess.run(git + ["init", "-q"], cwd=tmp, check=True)
        subprocess.run(git + ["add", "."], cwd=tmp, check=True)
        subprocess.run(git + ["commit", "-q", "-m", "base"], cwd=tmp, check=True)
        assert schema_diff(pkg) == "UsrPkg: no differences against HEAD"
        entity = EntitySchema(pkg, "UsrOrder")
        entity.add_column("UsrWeight", "Float", "Weight")
        entity.save()
        shutil.rmtree(pkg / "Schemas" / "UsrOrderStatus")
        text = schema_diff(pkg)
        lines = text.splitlines()
        assert lines[0] == "UsrOrder  object" and lines[1] == "  columns" and "    + UsrWeight Float 'Weight'" in lines
        assert "- UsrOrderStatus  object (removed)" in lines and text.count("+ UsrWeight") == 1  # the summary does not repeat it
        assert not any("~ UsrStatus" in l for l in lines), lines  # the removed target is the `- UsrOrderStatus` line, not a change of every column pointing at it
        assert lines[-1] == "UsrPkg against HEAD: 1 changed, 0 new, 1 removed; lines +1 -0 ~0"
        only = schema_diff(pkg, ["UsrOrder"], str(OBJECTS.parent))  # a folder of packages instead of git
        assert only.splitlines()[0] == "UsrOrder  object" and "(removed)" not in only
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert main(["diff", str(pkg), "UsrOrder", "--against", str(OBJECTS)]) == 0
        assert "+ UsrWeight Float 'Weight'" in out.getvalue()
        shutil.move(pkg / "Schemas" / "UsrOrder", pkg / "Schemas" / "UsrOrder2")  # the same UId under a new name
        text = schema_diff(pkg)
        assert text.splitlines()[0] == "~ UsrOrder -> UsrOrder2  object (renamed)" and "+ UsrWeight Float" in text, text
        assert "- UsrOrder  object (removed)" not in text and "+ UsrOrder2  object (new)" not in text
        assert schema_diff(pkg, ["UsrOrder2"]).splitlines()[0].startswith("~ UsrOrder -> UsrOrder2")
        try:
            schema_diff(pkg, ["UsrNoSuch"])
            raise AssertionError("an unknown item must be refused")
        except FileNotFoundError as e:
            assert "UsrNoSuch" in str(e)
        try:
            schema_diff(pkg, against="no-such-rev")
            raise AssertionError("an unknown revision must be refused")
        except QueryError as e:
            assert "no-such-rev" in str(e)


def test_impact_on_a_workspace_without_the_schema_answers_its_row():
    """S52-T05: an empty packages/, and a package that does not hold the schema: the row, no dependents, no refusal."""
    import shutil
    import tempfile
    from creatio_schemas.describe.deps import impact
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        (ws / "packages").mkdir(parents=True)
        for text, conflicts in (impact(ws, ["UsrNewThing"]), impact(ws, ["UsrNewThing"], md=True)):
            assert conflicts == 0 and "affects: (none)" in text, text
        assert "UsrNewThing  (not in the workspace)" in impact(ws, ["UsrNewThing"])[0]
        assert "| `UsrNewThing` | none typed | - |" in impact(ws, ["UsrNewThing"], md=True)[0]
        shutil.copytree(PAGES, ws / "packages" / "UsrPkg")
        text, conflicts = impact(ws, ["UsrNewThing"], md=True)
        assert conflicts == 0 and "| `UsrNewThing` | none typed | - |" in text and "affects: (none)" in text, text
    try:
        impact(Path(tmp) / "missing", ["UsrNewThing"])
        raise AssertionError("a folder that is not there must still be refused")
    except FileNotFoundError:
        pass


def test_impact_filters_dependents_by_kind():
    from creatio_schemas.describe.deps import impact
    text, _ = impact(PAGES, ["UsrOrder"], kind="page")
    lines = [l.strip() for l in text.splitlines() if l.startswith("    ")]
    assert lines and all(l.startswith("page ") for l in lines), lines
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert main(["impact", str(PAGES), "UsrOrder", "--kind", "nope"]) == 0
    assert "dependents: none typed" in out.getvalue()


def test_uids_resolve_both_ways_and_name_a_text():
    from creatio_schemas.describe.uids import resolve
    from creatio_schemas.process import ProcessSchema
    from creatio_schemas.workspace import Workspace
    ws = Workspace(PAGES)
    order = ws.find("UsrOrder", "EntitySchemaManager")[0]["uid"]
    assert ws.find(order) == ws.find("usrorder") == ws.find("UsrOrder") and ws.find("UsrOrder", "ProcessSchemaManager") == []  # by UId, name (case-blind), manager
    status = ws.column_uids("UsrOrder")["UsrStatus"]
    assert resolve(PAGES, order).startswith(f"{order}  schema UsrOrder (Entity) in UsrPkg"), resolve(PAGES, order)
    assert resolve(PAGES, status) == f"{status}  column UsrOrder.UsrStatus"
    assert resolve(PAGES, "UsrOrder.UsrStatus") == f"{status}  column UsrOrder.UsrStatus"
    assert resolve(PAGES, "UsrOrder").startswith(f"{order}  schema UsrOrder")
    p = ProcessSchema(PROCS, "UsrProcess_0d4c445")
    start = p.element("StartEvent1")["UId"].lower()
    assert resolve(PROCS, start) == f"{start}  process UsrProcess_0d4c445 element StartEvent1 (StartEvent)"
    assert resolve(PROCS, "UsrProcess_0d4c445.StartEvent1").startswith(start)
    text = resolve(PROCS, f"[#[IsOwnerSchema:false].[Element:{{{start}}}].[Parameter:{{00000000-0000-0000-0000-000000000001}}]#]")
    assert "not in the workspace" in text and text.splitlines()[-1] == "[#[IsOwnerSchema:false].[Element:{StartEvent1}].[Parameter:{00000000-0000-0000-0000-000000000001}]#]", text
    assert "not in the workspace" in resolve(PAGES, "UsrNoSuch.X")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert main(["uid", str(PAGES), "UsrOrder.UsrStatus"]) == 0
    assert status in out.getvalue()


def test_diff_forms_of_the_platform_files_and_located_errors():
    import json
    import shutil
    import tempfile
    from creatio_schemas.workspace import parse_diff
    column = '{\r\n  "UId": "u1",\r\n  "A2": "UsrCode"\r\n}'
    # an operation line written before the value's last `}`, and a blank last line: both read as the platform means them
    text = '+ MetaData.Schema.D2 {\r\n  "UId": "u1",\r\n~ MetaData.Schema.D2 [order]\r\n  "A2": "UsrCode"\r\n}\r\n= MetaData.Schema.A2 "UsrX"\r\n\r\n'
    assert parse_diff(text) == [("+", "MetaData.Schema.D2", column), ("~", "MetaData.Schema.D2", "[order]"), ("=", "MetaData.Schema.A2", '"UsrX"')]
    assert parse_diff(text.replace("\r\n", "\n")) == parse_diff(text)  # an LF file reads the same
    assert json.loads(parse_diff(text)[0][2]) == {"UId": "u1", "A2": "UsrCode"}
    assert parse_diff('+ MetaData.Schema.D2 {"A2": "a{b"}\r\n- MetaData.Schema.D2 x') == [("+", "MetaData.Schema.D2", '{"A2": "a{b"}'), ("-", "MetaData.Schema.D2", "x")]  # braces in strings
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "Schemas" / "UsrX").mkdir(parents=True)
        (tmp / "Schemas" / "UsrX" / "metadata.json").write_bytes('﻿{"MetaData": {"Ж": 1,, }}'.encode("utf-8"))
        try:
            json.loads((tmp / "Schemas" / "UsrX" / "metadata.json").read_text(encoding="utf-8-sig"))
        except ValueError as e:
            assert located(tmp, ["Schemas/UsrX/descriptor.json", "Schemas/UsrX/metadata.json"], e).startswith("Schemas/UsrX/metadata.json:25: JSONDecodeError: ")
        (tmp / "Schemas" / "UsrX" / "body.js").write_bytes(b"var a = '\x98';")  # a byte neither UTF-8 nor cp1251 decodes
        try:
            (tmp / "Schemas" / "UsrX" / "body.js").read_bytes().decode("cp1251")
        except UnicodeDecodeError as e:
            assert located(tmp, ["Schemas/UsrX/body.js"], e).startswith("Schemas/UsrX/body.js:9: UnicodeDecodeError: ")
        try:
            {}["ManagerName"]
        except KeyError as e:
            assert located(tmp, [], e) == f"KeyError: 'ManagerName' (raised at {Path(__file__).name}:{e.__traceback__.tb_lineno})"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _repo(root: Path, package_src: Path) -> Path:
    """A throwaway git repository holding <root>/packages/UsrPkg, committed once (the test's own, never a workspace)."""
    import shutil
    import subprocess
    pkg = root / "packages" / "UsrPkg"
    shutil.copytree(package_src, pkg)
    git = ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "core.autocrlf=false"]
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=root, check=True)
    subprocess.run(git + ["add", "-A"], cwd=root, check=True)
    subprocess.run(git + ["commit", "-q", "-m", "fixture"], cwd=root, check=True)
    return pkg


def test_review_sorts_a_pulled_package_and_restores_what_is_not_kept():
    import json
    import shutil
    import subprocess
    import tempfile
    from creatio_schemas.describe.diff import schema_diff
    from creatio_schemas.describe.review import render, review
    root = Path(tempfile.mkdtemp())
    try:
        pkg = _repo(root, OBJECTS)
        meta = pkg / "Schemas" / "UsrOrderStatus" / "metadata.json"
        raw = meta.read_bytes()
        meta.write_bytes(raw.replace(b"\r\n", b"\n") if b"\r\n" in raw else raw.replace(b"\n", b"\r\n"))  # line endings only
        desc = pkg / "descriptor.json"
        data = json.loads(desc.read_text(encoding="utf-8-sig"))
        dropped = data["Descriptor"]["DependsOn"].pop()["Name"]
        desc.write_text(json.dumps(data, indent=2), encoding="utf-8")  # a dependency dropped, the BOM gone
        order = pkg / "Schemas" / "UsrOrder" / "descriptor.json"
        order.write_text(order.read_text(encoding="utf-8-sig").replace('"Name": "UsrOrder"', '"Name": "UsrOrder", "Caption": "Changed"', 1), encoding="utf-8")
        (pkg / "Resources" / "UsrGone.Entity").mkdir()
        (pkg / "Resources" / "UsrGone.Entity" / "resource.en-US.xml").write_text("<x/>", encoding="utf-8")
        answer = review(pkg)
        assert answer["eol_only"] == ["Schemas/UsrOrderStatus/metadata.json"], answer["eol_only"]
        assert answer["dependencies"] == {"dropped": [dropped], "added": []} and answer["orphans"] == ["UsrGone.Entity"]
        assert answer["untracked"] == ["Resources/UsrGone.Entity/resource.en-US.xml"] and answer["content"] == schema_diff(pkg)
        text = render(answer)
        assert text.startswith("UsrPkg: 4 changed file(s) against HEAD\nline endings or BOM only (1) - nothing changed:") and f"dependencies: dropped {dropped}" in text, text
        assert "resource folders with no schema: Resources/UsrGone.Entity" in text and "would restore" not in text
        plan = review(pkg, keep=["UsrOrder"])
        assert sorted(plan["restore"]) == ["Schemas/UsrOrderStatus/metadata.json", "descriptor.json"] and not plan["applied"], plan["restore"]
        assert "would restore (run with --apply) from HEAD (2):\n  git checkout HEAD -- " in render(plan)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert main(["review", str(pkg), "--keep", "UsrOrder", "--apply"]) == 0
        assert "restored from HEAD (2):" in out.getvalue()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True).stdout
        assert "UsrOrder/descriptor.json" in status and "descriptor.json\n" not in status.replace("UsrOrder/descriptor.json", "") and "UsrOrderStatus" not in status, status
        assert review(pkg)["dependencies"] == {"dropped": [], "added": []}  # the dependency is back
        with contextlib.redirect_stderr(io.StringIO()):
            assert main(["review", str(root)]) == 2  # not a package folder
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_precommit_refuses_archives_binaries_large_and_stray_files():
    import shutil
    import subprocess
    import tempfile
    from creatio_schemas.describe.review import precommit
    root = Path(tempfile.mkdtemp())
    try:
        pkg = _repo(root, OBJECTS)  # an assembly package (Type 1)
        (pkg / "Files" / "Bin").mkdir(parents=True)
        (pkg / "Files" / "Bin" / "UsrPkg.dll").write_bytes(b"MZ")
        (pkg / "Files" / "UsrPkg.pdb").write_bytes(b"x")
        (pkg / "Files" / "backup.zip").write_bytes(b"PK")
        (pkg / "Files" / "big.json").write_bytes(b"0" * (5 * 1024 * 1024 + 1))
        (root / "notes.txt").write_text("x", encoding="utf-8")
        (root / "README.md").write_text("x", encoding="utf-8")
        (root / "unstaged.rar").write_bytes(b"x")
        subprocess.run(["git", "add", "packages", "notes.txt", "README.md"], cwd=root, check=True)
        problems = precommit(root)
        assert problems == ["notes.txt: outside packages/ (known roots: .gitignore, .gitattributes, .editorconfig, README.md, project.json, .clio, .vscode, tasks, docs)",
                            "packages/UsrPkg/Files/UsrPkg.pdb: a binary outside Files/Bin of an assembly package",
                            "packages/UsrPkg/Files/backup.zip: an archive",
                            "packages/UsrPkg/Files/big.json: 5.0 MB (over 5 MB)"], problems
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert main(["precommit", str(root)]) == 1
        assert "backup.zip: an archive" in out.getvalue()
        subprocess.run(["git", "reset", "-q"], cwd=root, check=True)
        assert precommit(root) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _binding(pkg: Path, name: str, schema: str, columns: list[str], rows: list[list]) -> None:
    """A Data/<name> binding with the given column names (the first is the key) and rows of values, written as the platform does."""
    import json
    folder = pkg / "Data" / name
    folder.mkdir(parents=True)
    uids = {c: f"{i:08x}-0000-4000-8000-000000000000" for i, c in enumerate(columns, 1)}
    descriptor = {"Descriptor": {"UId": "99999999-0000-4000-8000-000000000001", "Name": name, "InstallType": 0, "Schema": {"UId": "88888888-0000-4000-8000-000000000001", "Name": schema},
                                 "Columns": [{"ColumnUId": uids[c], "IsForceUpdate": False, "IsKey": i == 0, "ColumnName": c, "DataTypeValueUId": "x"} for i, c in enumerate(columns)]}}
    (folder / "descriptor.json").write_text("﻿" + json.dumps(descriptor), encoding="utf-8")
    data = {"PackageData": [{"Row": [{"SchemaColumnUId": uids[c], "Value": v} for c, v in zip(columns, row)]} for row in rows]}
    (folder / "data.json").write_text("﻿" + json.dumps(data), encoding="utf-8")


def test_precommit_stops_a_system_setting_value_binding_unless_the_project_allows_the_code():
    import json
    import shutil
    import subprocess
    import tempfile
    from creatio_schemas.describe.review import precommit
    root = Path(tempfile.mkdtemp())
    try:
        pkg = _repo(root, OBJECTS)
        setting = "aaaaaaaa-0000-4000-8000-000000000001"
        _binding(pkg, "SysSettings_UsrMaxRows", "SysSettings", ["Id", "Code", "ValueTypeName"], [[setting, "UsrMaxRows", "Integer"]])
        _binding(pkg, "SysSettingsValue_UsrMaxRows", "SysSettingsValue", ["Id", "SysSettings", "IntegerValue"], [["bbbbbbbb-0000-4000-8000-000000000001", setting, 500]])
        subprocess.run(["git", "add", "packages"], cwd=root, check=True)
        problems = precommit(root)
        assert problems == ["packages/UsrPkg/Data/SysSettingsValue_UsrMaxRows/data.json: sets system setting UsrMaxRows = 500 on every environment it is installed on"], problems
        # the setting binding itself (its definition) is not a value; a project that allows the code lets it through
        (root / "project.json").write_text(json.dumps({"allowedSettingBindings": ["UsrMaxRows"]}), encoding="utf-8")
        subprocess.run(["git", "add", "project.json"], cwd=root, check=True)
        assert precommit(root) == []
        (root / "project.json").write_text(json.dumps({"allowedSettingBindings": ["UsrOther"]}), encoding="utf-8")
        assert len(precommit(root)) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _layer_workspace(root: Path, packages: dict) -> Path:
    """packages: {name: (depends_on, {schema: replacing})} -> <root>/packages/<name>/ with the descriptors only."""
    import json
    for name, (deps, schemas) in packages.items():
        pkg = root / "packages" / name
        pkg.mkdir(parents=True)
        (pkg / "descriptor.json").write_text("﻿" + json.dumps({"Descriptor": {"UId": f"pkg-{name}", "Name": name,
                                                                                   "DependsOn": [{"UId": f"pkg-{d}", "Name": d} for d in deps]}}), encoding="utf-8")
        for schema, replacing in schemas.items():
            (pkg / "Schemas" / schema).mkdir(parents=True)
            (pkg / "Schemas" / schema / "descriptor.json").write_text(json.dumps({"Descriptor": {
                "UId": f"uid-{name}-{schema}", "Name": schema, "ExtendParent": replacing, "ManagerName": "EntitySchemaManager"}}), encoding="utf-8")
    return root


def test_layers_name_the_site_gives_a_renamed_schema():
    import shutil
    import tempfile
    from creatio_schemas.describe.layers import render, schema_layers

    class RenamedSite:
        clio_name, url = "dev", "https://dev.example/"

        def __init__(self, name):
            self.name, self.sql_text = name, []

        def sql(self, text):
            self.sql_text.append(text)
            if 'select distinct "Name"' in text:
                return [{"name": self.name}]
            return [_row("UsrA", "0", "2", ext="false")]

    root = Path(tempfile.mkdtemp())
    try:
        _layer_workspace(root, {"UsrA": (["CrtBase"], {"UsrOrder_Process": False})})
        site = RenamedSite("UsrOrderRenamed_Process")
        result = schema_layers(site, "UsrOrder_Process", workspace=root)
        assert result["siteName"] == "UsrOrderRenamed_Process"
        assert "'uid-usra-usrorder_process'" in site.sql_text[0]  # the workspace's UId, lower case
        assert "\"Name\" = 'UsrOrderRenamed_Process'" in site.sql_text[1]  # the layers are read under the site's name
        lines = render(result, "dev").splitlines()
        assert lines[1] == "  name on site: UsrOrderRenamed_Process (workspace: UsrOrder_Process)", lines
        # the same name on both sides, or no workspace: no line and no extra query
        same = RenamedSite("UsrOrder_Process")
        assert schema_layers(same, "UsrOrder_Process", workspace=root)["siteName"] is None
        assert "name on site" not in render(schema_layers(same, "UsrOrder_Process", workspace=root), "dev")
        plain = RenamedSite("x")
        schema_layers(plain, "UsrOrder_Process")
        assert len(plain.sql_text) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_layers_in_order_by_dependencies_and_by_the_site():
    import shutil
    import tempfile
    from creatio_schemas.describe.merge import layers_in_order

    root = Path(tempfile.mkdtemp())
    try:
        # UsrA <- UsrB, UsrA <- UsrC (siblings); UsrD (no layer) <- UsrB, UsrC; UsrE <- UsrD: E comes after both through D
        _layer_workspace(root, {
            "UsrE": (["UsrD"], {"Contact": True}),
            "UsrC": (["UsrA"], {"Contact": True}),
            "UsrB": (["UsrA", "CrtBase"], {"Contact": True, "UsrThing": True}),
            "UsrD": (["UsrB", "UsrC"], {}),
            "UsrA": (["CrtBase"], {"Contact": True, "UsrThing": False}),
        })
        layers = layers_in_order(root, "Contact")
        assert [x.package for x in layers] == ["UsrA", "UsrB", "UsrC", "UsrE"], layers
        assert [x.siblings for x in layers] == [(), ("UsrC",), ("UsrB",), ()]
        assert all(x.replacing and x.source == "workspace" for x in layers) and layers[0].uid == "uid-UsrA-Contact"
        assert layers[3].folder == root / "packages" / "UsrE" / "Schemas" / "Contact"
        own = layers_in_order(root / "packages", "UsrThing")
        assert [(x.package, x.replacing) for x in own] == [("UsrA", False), ("UsrB", True)]
        assert layers_in_order(root, "Contact", manager="ClientUnitSchemaManager") == [] and layers_in_order(root, "UsrNope") == []
        # the site's order wins; the vendor base has no folder; UsrE is not on the site yet: after the site's copies
        site = [_row("CrtBase", "1", "9", ext="false"), _row("UsrA", "0", "4"), _row("UsrC", "0", "3"), _row("UsrB", "0", "2")]
        for row in site:
            row["manager"] = "EntitySchemaManager"
        env = FakeLayersEnv(site)
        layers = layers_in_order(root, "Contact", env)
        assert [(x.package, x.source) for x in layers] == [("CrtBase", "site"), ("UsrA", "site"), ("UsrC", "site"), ("UsrB", "site"), ("UsrE", "workspace")]
        assert layers[0].folder is None and not layers[0].replacing and layers[0].uid == "" and layers[2].uid == "uid-UsrC-Contact"
        assert all(x.siblings == () for x in layers) and len(env.sql_text) == 2 and '"HierarchyLevel"' in env.sql_text[1]

        class LevelEnv(FakeLayersEnv):  # the runtime order: HierarchyLevel, then the name - UsrB before UsrC on one level
            def sql(self, text):
                self.sql_text.append(text)
                levels = {"UsrA": "4", "UsrB": "5", "UsrC": "5"}
                return [{"package": p, "level": v} for p, v in levels.items()] if text.startswith('select "Name"::text "package"') else self.rows
        layers = layers_in_order(root, "Contact", LevelEnv(site))
        assert [x.package for x in layers] == ["CrtBase", "UsrA", "UsrB", "UsrC", "UsrE"]
        assert list(root.rglob(".creatio-index")) == []  # read-only: nothing written into the workspace
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _two_layer_workspace(root: Path) -> None:
    """The objects fixture (a replacing Account in UsrPkg, its fetched base) plus UsrPkg2, a second layer that adds UsrRating."""
    import json
    import shutil
    from creatio_schemas import EntitySchema

    fixtures = TOOLS / "objects" / "tests" / "fixtures"
    shutil.copytree(fixtures / "UsrPkg", root / "packages" / "UsrPkg")
    shutil.copytree(fixtures / ".creatio-bases", root / ".creatio-bases")
    shutil.copytree(fixtures / ".creatio-bases" / "UsrPkg", root / ".creatio-bases" / "UsrPkg2")
    second = root / "packages" / "UsrPkg2"
    shutil.copytree(fixtures / "UsrPkg", second)
    shutil.rmtree(second / "Schemas")
    shutil.rmtree(second / "Resources")
    d = json.loads((second / "descriptor.json").read_text("utf-8-sig"))
    d["Descriptor"].update({"Name": "UsrPkg2", "UId": "11111111-2222-4333-8444-555555555555", "DependsOn": [{"Name": "UsrPkg", "UId": "x"}]})
    (second / "descriptor.json").write_text(json.dumps(d), "utf-8")
    layer = EntitySchema.create_replacing(second, "Account")
    layer.add_column("UsrRating", "Integer", "Rating", default=3, required=True)
    layer.save()


def test_snapshot_disk_lines_are_the_effective_object_over_the_layers():
    import shutil
    import tempfile
    from creatio_schemas.integrity import compare, snapshot

    root = Path(tempfile.mkdtemp())
    try:
        _two_layer_workspace(root)
        lines = snapshot(root, "Account")
        assert lines[0] == "layers: UsrPkg > UsrPkg2", lines[0]
        columns = {l.split()[1]: l for l in lines if l.startswith("column ")}
        assert "Name" in columns and "GPSE" in columns, "the columns of the base and of the first layer"
        assert columns["UsrRating"].endswith("Integer required default 3") and columns["Owner"].split()[3:5] == ["Lookup", "lookup"]
        assert any(l.startswith("index ") for l in lines)
        assert compare(lines, snapshot(root, "Account")) == []  # equal snapshots compare empty
        # a copy of the workspace with the second layer's column removed shows as `- column UsrRating ...`
        other = Path(tempfile.mkdtemp())
        try:
            shutil.rmtree(other)
            shutil.copytree(root, other)
            from creatio_schemas import EntitySchema
            layer = EntitySchema(other / "packages" / "UsrPkg2", "Account")
            layer.remove_column("UsrRating")
            layer.save()
            diff = compare(lines, snapshot(other, "Account"))
            assert len(diff) == 1 and diff[0].startswith("- column UsrRating "), diff
        finally:
            shutil.rmtree(other, ignore_errors=True)
        try:
            snapshot(root, "UsrNope")
        except KeyError as e:
            assert "UsrNope" in str(e)
        else:
            raise AssertionError("expected KeyError")
        # the base of a replacing layer that is neither on disk nor fetched stops the snapshot
        shutil.rmtree(root / ".creatio-bases")
        try:
            snapshot(root, "Account")
        except RuntimeError as e:
            assert "objects.py base" in str(e)
        else:
            raise AssertionError("expected RuntimeError")
    finally:
        shutil.rmtree(root, ignore_errors=True)


SHORT_TEXT, LOOKUP = "325a73b8-0f47-44a0-8412-7606f78003ac", "b295071f-7ea9-4e62-8d1a-919bf3732ff2"
PAGE_BODY = """define("UsrOrderPage", [], function() {{
	return {{
		entitySchemaName: "UsrOrder",
		methods: {{{methods}
		}},
		diff: /**SCHEMA_DIFF*/[{diff}]/**SCHEMA_DIFF*/
	}};
}});
"""


def _object_layer(pkg: Path, name: str, columns: list, replacing: bool = True) -> None:
    """A replacing object (`+ MetaData.Schema.D2 {column}` lines) or an own one; columns: (name, uid, type[, ref uid])."""
    import json
    folder = pkg / "Schemas" / name
    folder.mkdir(parents=True)
    uid = f"00000000-0000-4000-8000-{abs(hash((pkg.name, name))) % 10 ** 12:012d}"
    (folder / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": uid, "Name": name, "Parent": {"UId": "16be3651-8fe2-4159-8dd0-a803d4683dd3", "Name": name},
                                                                        "ExtendParent": replacing, "ManagerName": "EntitySchemaManager"}}), encoding="utf-8")
    lines = [f'= MetaData.Schema.UId "{uid}"']
    for col in columns:
        c = {"UId": col[1], "A2": col[0], "A3": uid, "A4": uid, "A5": f"pkg-{pkg.name}", "S2": col[2]}  # created / modified in this layer
        if len(col) > 3:
            c["S4"] = col[3]
        lines.append("+ MetaData.Schema.D2 " + json.dumps(c, indent=2).replace("\n", "\r\n"))
    (folder / "metadata.json").write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))


def _page_layer(pkg: Path, methods: dict, diff: list) -> None:
    import json
    folder = pkg / "Schemas" / "UsrOrderPage"
    folder.mkdir(parents=True)
    (folder / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": f"page-{pkg.name}", "Name": "UsrOrderPage", "ExtendParent": True,
                                                                        "Parent": {"UId": "base-page", "Name": "UsrOrderPage"}, "ManagerName": "ClientUnitSchemaManager"}}), encoding="utf-8")
    (folder / "metadata.json").write_text("{}", encoding="utf-8")
    body = PAGE_BODY.format(methods=",".join(f"\n\t\t\t{k}: function() {{\n\t\t\t\t{v}\n\t\t\t}}" for k, v in methods.items()),
                            diff=", ".join(json.dumps({"operation": op, "name": n}) for n, op in diff))
    (folder / "UsrOrderPage.js").write_text(body, encoding="utf-8")


def test_merge_plan_targets_conflicts_and_dependencies():
    import shutil
    import tempfile
    from creatio_schemas.describe.merge import _call_parent, merge_plan

    assert _call_parent("save: function() { Ext.bind(function() { this.callParent(arguments); }, this)(); }") == (True, False)
    assert _call_parent("save: function() { var x = this.callParent(arguments); return x; }") == (False, True)
    assert _call_parent("save: function() { if (a == this.callParent(arguments)) {} return this.callParent(arguments); }") == (False, False)
    root = Path(tempfile.mkdtemp())
    try:
        # UsrA <- UsrB, UsrA <- UsrC (siblings); UsrB also depends on UsrExtra, which the target gains
        _layer_workspace(root, {"UsrA": (["CrtBase"], {}), "UsrB": (["UsrA", "UsrExtra"], {}), "UsrC": (["UsrA"], {}), "UsrExtra": (["CrtBase"], {})})
        pk = root / "packages"
        status = "11111111-0000-4000-8000-000000000001"
        _object_layer(pk / "UsrA", "Contact", [("UsrA1", "a1000000-0000-4000-8000-000000000001", SHORT_TEXT)])
        _object_layer(pk / "UsrB", "Contact", [("UsrB1", "b1000000-0000-4000-8000-000000000001", SHORT_TEXT),
                                               ("UsrDup", "d1000000-0000-4000-8000-000000000001", SHORT_TEXT),
                                               ("UsrStatus", "b2000000-0000-4000-8000-000000000001", LOOKUP, status)])
        _object_layer(pk / "UsrC", "Contact", [("UsrDup", "d2000000-0000-4000-8000-000000000002", SHORT_TEXT)])
        _object_layer(pk / "UsrB", "UsrBStatus", [], replacing=False)
        (pk / "UsrB" / "Schemas" / "UsrBStatus" / "descriptor.json").write_text(
            '{"Descriptor": {"UId": "%s", "Name": "UsrBStatus", "ManagerName": "EntitySchemaManager"}}' % status, encoding="utf-8")
        _object_layer(pk / "UsrB", "UsrThing", [])  # in two siblings only: no package below both
        _object_layer(pk / "UsrC", "UsrThing", [])
        _page_layer(pk / "UsrA", {"onEntityInitialized": "this.callParent(arguments);"}, [("UsrName", "insert")])
        _page_layer(pk / "UsrB", {"onEntityInitialized": "var r = this.callParent(arguments); return r;"}, [("UsrName", "merge"), ("Tab1", "merge")])
        text, conflicts = merge_plan(root, limit=0, direction="down")
        lines = text.splitlines()
        assert lines[0] == "Contact object: 3 layers, target UsrA", lines
        assert lines[1:4] == ["  layer UsrA: +1 column", "  layer UsrB: +3 columns", "  layer UsrC: +1 column"], lines
        assert "  siblings: UsrB, UsrC (order guessed)" in lines
        assert "  conflict lookup UsrStatus -> UsrBStatus (its package UsrB depends on the target): UsrB" in lines
        assert "  conflict column UsrDup (two UIds): UsrB and UsrC" in lines and "  depends: UsrA gains UsrExtra" in lines
        page = lines.index("UsrOrderPage classic: 2 layers, target UsrA")
        assert lines[page + 1:page + 3] == ["  layer UsrA: +1 element, +1 method", "  layer UsrB: +2 elements, +1 method"], lines
        assert "  conflict method onEntityInitialized: UsrA and UsrB" in lines and "  conflict callParent return value used, method onEntityInitialized: UsrB" in lines
        assert not any("conflict element" in l for l in lines)  # an insert below and a merge above is the usual form
        assert "UsrThing object: 2 layers, no common lowest package: UsrB, UsrC" in lines
        assert lines[-1] == "3 schemas, 3 layers to remove, 4 conflicts, 1 without a common lowest package" and conflicts == 4
        one, _ = merge_plan(root, ["contact", "UsrNope"], direction="down")
        assert one.splitlines()[0] == "UsrNope: no copy in the workspace" and one.endswith("1 schemas, 2 layers to remove, 2 conflicts")
        assert merge_plan(root, ["UsrBStatus"], direction="down")[0].splitlines()[0] == "UsrBStatus: 0 replacing layers in the workspace, nothing to merge"
        assert merge_plan(root, limit=2, direction="down")[0].splitlines()[2].startswith("  ... ")
        second = merge_plan(root, limit=2, offset=2, direction="down")[0].splitlines()  # the next page of the plan, the totals line as always
        assert second[:2] == lines[2:4] and "next: offset=4" in second[2] and second[-1] == lines[-1], second
        assert list(root.rglob(".creatio-index")) == []
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert main(["merge-plan", str(root), "Contact", "--direction", "down"]) == 1
        assert "target UsrA" in out.getvalue()
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(["merge-plan", str(root), "UsrBStatus", "--direction", "down"]) == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_merge_plan_counts_processes_and_dcm_and_refuses_them():
    import json
    import shutil
    import tempfile
    from creatio_schemas.describe.merge import merge_object, merge_plan

    root = Path(tempfile.mkdtemp())
    try:
        _layer_workspace(root, {"UsrA": (["CrtBase"], {}), "UsrB": (["UsrA"], {})})
        pk = root / "packages"
        for package, source, name in (("UsrA", PROCS, "UsrDeleteOldLogs_Process"), ("UsrB", PROCS, "UsrDeleteOldLogs_Process"),
                                      ("UsrA", DCM, "UsrRequestCases"), ("UsrB", DCM, "UsrRequestCases")):
            shutil.copytree(source / "Schemas" / name, pk / package / "Schemas" / name)
            shutil.copytree(source / "Resources" / (name + (".Process" if source is PROCS else ".Dcm")), pk / package / "Resources" / (name + (".Process" if source is PROCS else ".Dcm")))
            descriptor = pk / package / "Schemas" / name / "descriptor.json"
            data = json.loads(descriptor.read_text("utf-8-sig"))
            data["Descriptor"]["ExtendParent"] = True
            descriptor.write_text(json.dumps(data), "utf-8")
        text, conflicts = merge_plan(root, limit=0, direction="down")
        lines = text.splitlines()
        process = lines.index("UsrDeleteOldLogs_Process process: 2 layers, target UsrA")
        assert lines[process + 1:process + 3] == ["  layer UsrA: +3 elements", "  layer UsrB: +3 elements"], lines  # the fixture process has no parameters
        assert "  conflict process: not merged by this toolkit (T06)" in lines
        dcm = lines.index("UsrRequestCases dcm: 2 layers, target UsrA")
        assert "stage" in lines[dcm + 1] and "  conflict dcm: not merged by this toolkit (T06)" in lines
        assert conflicts == 2 and lines[-1] == "2 schemas, 2 layers to remove, 2 conflicts"
        out, code = merge_object(root, "UsrDeleteOldLogs_Process", direction="down")
        assert code == 1 and "merge writes objects and pages only" in out and "conflict process" in out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_merge_plan_counts_rule_layers_and_names_their_conflicts():
    import shutil
    import tempfile
    from creatio_schemas.describe.merge import merge_object, merge_plan
    from creatio_schemas.rules import RuleSchema

    root = Path(tempfile.mkdtemp())
    try:
        _layer_workspace(root, {"UsrA": (["CrtBase"], {}), "UsrB": (["UsrA"], {})})
        pk = root / "packages"
        name = "ContactAddressBusinessRule"
        for package in ("UsrA", "UsrB"):
            shutil.copytree(RULES / "Schemas" / name, pk / package / "Schemas" / name)
            shutil.copytree(RULES / "Resources" / (name + ".Addon"), pk / package / "Resources" / (name + ".Addon"))
        edited = RuleSchema(pk / "UsrA", name).base_edits()
        assert edited and "BRS1" in edited[0], edited  # the fixture's replacing addon edits one base rule
        uid = edited[0].split('["')[1].split('"]')[0]
        text, conflicts = merge_plan(root, limit=0, direction="down")
        lines = text.splitlines()
        assert lines[0] == f"{name} rules: 2 layers, target UsrA", lines
        assert lines[1:3] == ["  layer UsrA: +1 rule, ~1 base rule edited", "  layer UsrB: +1 rule, ~1 base rule edited"], lines
        own = [l for l in lines if l.startswith("  conflict rule ")]
        assert len(own) == 1 and own[0].endswith(": UsrA and UsrB"), lines  # the copied own rule has one UId in both layers
        assert conflicts == 1  # the same base-rule edit in two layers is not a conflict: the diffs concatenate in fold order
        # the base rule removed in the upper layer and edited in the lower one: the card's conflict
        top = RuleSchema(pk / "UsrB", name)
        top.remove_base(uid)
        top.save()
        text, conflicts = merge_plan(root, limit=0, direction="down")
        assert f"  conflict rule {uid} (removed in UsrB, edited in UsrA): UsrB and UsrA" in text.splitlines(), text
        assert conflicts == 2 and text.splitlines()[-1] == "1 schemas, 1 layers to remove, 2 conflicts"
        out, code = merge_object(root, name, direction="down")
        assert code == 1 and "merge writes objects and pages only" in out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_merge_writes_one_layer_and_stops_on_what_it_cannot_prove():
    import json
    import shutil
    import tempfile
    from creatio_schemas.describe.merge import merge_object, merged_diff, layers_in_order, platform_drops
    from creatio_schemas.diff import SchemaDiff
    from creatio_schemas.resources import Resources
    from creatio_schemas.workspace import parse_diff

    assert platform_drops("+", "MetaData.Schema.EG1.BK4.[\"x\"].C2") and platform_drops("-", "MetaData.Schema.D20.FA4")
    assert not platform_drops("-", "MetaData.Schema.EG1.C2") and not platform_drops("+", "MetaData.Schema.D20.FA4")
    root = Path(tempfile.mkdtemp())
    try:
        # UsrBase <- UsrA (target) <- UsrB <- UsrC; UsrB also depends on UsrExtra
        _layer_workspace(root, {"UsrBase": (["CrtBase"], {}), "UsrA": (["UsrBase"], {}), "UsrB": (["UsrA", "UsrExtra"], {}),
                                "UsrC": (["UsrB"], {}), "UsrExtra": (["CrtBase"], {})})
        pk = root / "packages"
        cols = {"UsrA": ["UsrA1"], "UsrB": ["UsrB1", "UsrB2"], "UsrC": ["UsrC1"]}
        for i, (name, names) in enumerate(cols.items()):
            _object_layer(pk / name, "Contact", [(c, f"c{i}{j}000000-0000-4000-8000-000000000000", SHORT_TEXT) for j, c in enumerate(names)])
            meta = pk / name / "Schemas" / "Contact" / "metadata.json"
            text = meta.read_bytes().decode("utf-8")
            meta.write_bytes(text.replace("\r\n", f'\r\n= MetaData.Schema.B6 "pkg-{name}"\r\n- MetaData.Schema.D20.FA4\r\n', 1).encode("utf-8"))
            (meta.parent / "properties.json").write_text(json.dumps({"Properties": {"IsVirtual": "False", "From": name}}), encoding="utf-8")
        for name, items in (("UsrA", {"Columns.UsrA1.Caption": "A one"}), ("UsrC", {"Columns.UsrA1.Caption": "A one, by C", "Columns.UsrC1.Caption": "C one"})):
            res = Resources.empty(pk / name / "Resources" / "Contact.Entity", ["en-US"])
            for k, v in items.items():
                res.set(k, v)
            for p, (t, b) in res.files().items():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(("﻿" if b else "") + t, encoding="utf-8")
        snapshot = sorted(str(p) for p in root.rglob("*"))
        text, code = merge_object(root, "Contact", direction="down")
        assert code == 0 and text.splitlines()[0] == "Contact object: 3 layers, target UsrA", text
        assert "write packages/UsrA/Schemas/Contact/metadata.json" in text and "delete packages/UsrB/Schemas/Contact" in text
        assert "delete packages/UsrC/Resources/Contact.Entity" in text and text.endswith("3 layers -> 1 (dry run; --apply writes)")
        assert sorted(str(p) for p in root.rglob("*")) == snapshot  # a dry run writes nothing
        layers = [x for x in layers_in_order(root, "Contact") if x.replacing]
        merged = merged_diff(layers, layers[0], "pkg-UsrA")
        ops = parse_diff(merged)
        assert [json.loads(v)["A2"] for op, p, v in ops if p == "MetaData.Schema.D2" and op == "+"] == ["UsrA1", "UsrB1", "UsrB2", "UsrC1"]
        assert [v for op, p, v in ops if p == "MetaData.Schema.UId"] == ['"uid-UsrA-Contact"'.replace("uid-UsrA-Contact", layers[0].uid)]
        assert [v for op, p, v in ops if p == "MetaData.Schema.B6"] == ['"pkg-UsrA"']
        assert [p for op, p, v in ops if "D20.FA4" in p] == ["MetaData.Schema.D20.FA4"]  # the top layer's only
        # the merged diff folds to the same columns as the layers one after another
        base = {"D2": [], "D20": {"FA4": True}}
        one_by_one = base
        for x in layers:
            one_by_one = SchemaDiff((x.folder / "metadata.json").read_text(encoding="utf-8")).apply(one_by_one)
        assert SchemaDiff(merged).apply(base)["D2"] == one_by_one["D2"]
        text, code = merge_object(root, "Contact", apply=True, direction="down")
        assert code == 0 and text.endswith("merged Contact into UsrA: 3 layers -> 1"), text
        assert not (pk / "UsrB" / "Schemas" / "Contact").exists() and not (pk / "UsrC" / "Resources" / "Contact.Entity").exists()
        a = pk / "UsrA" / "Schemas" / "Contact"
        assert json.loads((a / "descriptor.json").read_text(encoding="utf-8"))["Descriptor"]["UId"] == layers[0].uid
        written = (a / "metadata.json").read_bytes().decode("utf-8")
        columns = [json.loads(v) for op, p, v in parse_diff(written) if p == "MetaData.Schema.D2"]
        assert {(c["A3"], c["A4"], c["A5"]) for c in columns} == {(layers[0].uid, layers[0].uid, "pkg-UsrA")}  # the merged layer owns them
        assert all(x.uid not in written for x in layers[1:]) and "pkg-UsrB" not in written and "\r\r" not in written
        assert json.loads((a / "properties.json").read_text(encoding="utf-8"))["Properties"]["From"] == "UsrC"  # the top layer's flags
        assert [d["Name"] for d in json.loads((pk / "UsrA" / "descriptor.json").read_text(encoding="utf-8-sig"))["Descriptor"]["DependsOn"]] == ["UsrBase", "UsrExtra"]
        merged_res = Resources(pk / "UsrA" / "Resources" / "Contact.Entity")
        assert merged_res.get("Columns.UsrA1.Caption") == "A one, by C" and merged_res.get("Columns.UsrC1.Caption") == "C one"
        assert merge_object(root, "Contact", direction="down")[0].splitlines()[0] == "Contact: 1 replacing layer in the workspace, nothing to merge"

        # the UId rule the other way: a target without a layer takes the top layer's UId, every layer goes
        shutil.rmtree(root)
        _layer_workspace(root, {"UsrBase": (["CrtBase"], {}), "UsrA": (["UsrBase"], {}), "UsrB": (["UsrA"], {})})
        for name in ("UsrA", "UsrB"):
            _object_layer(pk / name, "Contact", [(f"{name}1", f"{name.lower()}-col", SHORT_TEXT)])
        top_uid = json.loads((pk / "UsrB" / "Schemas" / "Contact" / "descriptor.json").read_text(encoding="utf-8"))["Descriptor"]["UId"]
        assert merge_object(root, "Contact", target="UsrB", direction="down")[1] == 1  # not below UsrA
        text, code = merge_object(root, "Contact", target="UsrBase", apply=True, direction="down")
        assert code == 0 and "delete packages/UsrA/Schemas/Contact" in text and "delete packages/UsrB/Schemas/Contact" in text, text
        assert json.loads((pk / "UsrBase" / "Schemas" / "Contact" / "descriptor.json").read_text(encoding="utf-8"))["Descriptor"]["UId"] == top_uid
        assert '= MetaData.Schema.B6 "pkg-UsrBase"' in (pk / "UsrBase" / "Schemas" / "Contact" / "metadata.json").read_text(encoding="utf-8")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    root = Path(tempfile.mkdtemp())
    try:  # siblings without the site, and a planted conflict: both stop and write nothing
        _layer_workspace(root, {"UsrA": (["CrtBase"], {}), "UsrB": (["UsrA"], {}), "UsrC": (["UsrA"], {})})
        pk = root / "packages"
        _object_layer(pk / "UsrA", "Contact", [("UsrA1", "a1", SHORT_TEXT)])
        _object_layer(pk / "UsrB", "Contact", [("UsrB1", "b1", SHORT_TEXT)])
        _object_layer(pk / "UsrC", "Contact", [("UsrC1", "c1", SHORT_TEXT)])
        snapshot = sorted(str(p) for p in root.rglob("*"))
        text, code = merge_object(root, "Contact", apply=True, direction="down")
        assert code == 1 and text.endswith("stopped: siblings: their order is a guess without the site; run with -e - nothing written"), text
        _object_layer(pk / "UsrB", "Contact2", [("UsrDup", "d1", SHORT_TEXT)])
        _object_layer(pk / "UsrA", "Contact2", [("UsrDup", "d2", SHORT_TEXT)])
        snapshot = sorted(str(p) for p in root.rglob("*"))
        text, code = merge_object(root, "Contact2", apply=True, direction="down")
        assert code == 1 and "conflict column UsrDup (two UIds): UsrA and UsrB" in text and "stopped: 1 conflicts" in text, text
        assert sorted(str(p) for p in root.rglob("*")) == snapshot
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert main(["merge", str(root), "Contact2", "--direction", "down"]) == 1
        assert "nothing written" in out.getvalue()

        # with the site: the siblings' order is known, the references check runs; a site-only layer among them stops
        class SiteEnv(FakeLayersEnv):
            def sql(self, text):
                self.sql_text.append(text)
                if text.startswith('select "Name"::text "package"'):  # merge's levels query, not the layers one
                    return [{"package": p, "level": str(n)} for n, p in enumerate(("UsrA", "CrtSales", "UsrB", "UsrC"))]
                if "information_schema" in text:
                    return []  # no NO ACTION foreign key to SysSchema.Id
                if 'and p."Name" in (' in text:
                    return [{"id": f"id-{p}", "package": p} for p in ("UsrB", "UsrC")]
                return self.rows

        class RefEnv(SiteEnv):
            def sql(self, text):
                if "information_schema" in text:
                    return [{"table": "SysProcessLog", "column": "SysSchemaId"}]
                if "count(*)" in text:
                    return [{"ref": "SysProcessLog.SysSchemaId", "id": "id-UsrC", "n": "3"}]
                return super().sql(text)

        site = [_row("CrtBase", "1", "9", ext="false"), _row("UsrA", "0", "4"), _row("UsrB", "0", "2"), _row("UsrC", "0", "1")]
        vendor = _row("CrtSales", "0", "3")
        for row in site + [vendor]:
            row["manager"] = "EntitySchemaManager"
        text, code = merge_object(root, "Contact", env=SiteEnv(site), direction="down")
        assert code == 0 and "  references: none to the 2 layers removed" in text and text.endswith("(dry run; --apply writes)"), text
        text, code = merge_object(root, "Contact", env=RefEnv(site), direction="down")
        assert code == 1 and "  references: SysProcessLog.SysSchemaId 3 rows point at UsrC's Contact" in text and "stopped: 1 references" in text, text
        text, code = merge_object(root, "Contact", env=SiteEnv(site + [vendor]), apply=True, direction="down")
        assert code == 1 and "  layer CrtSales: on the site only, not merged" in text, text
        assert "stopped: a layer on the site only folds after the target: CrtSales; the merge would put the removed layers' lines before it" in text, text
        assert sorted(str(p) for p in root.rglob("*")) == snapshot
    finally:
        shutil.rmtree(root, ignore_errors=True)


FREEDOM_BODY = """define("UsrPage_FormPage", /**SCHEMA_DEPS*/{deps}/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/({args})/**SCHEMA_ARGS*/ {{
	return {{
		viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/{view}/**SCHEMA_VIEW_CONFIG_DIFF*/,
		viewModelConfigDiff: /**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/{vm}/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/,
		modelConfigDiff: /**SCHEMA_MODEL_CONFIG_DIFF*/[]/**SCHEMA_MODEL_CONFIG_DIFF*/,
		handlers: /**SCHEMA_HANDLERS*/[{handlers}]/**SCHEMA_HANDLERS*/,
		converters: /**SCHEMA_CONVERTERS*/{{{converters}}}/**SCHEMA_CONVERTERS*/,
		validators: /**SCHEMA_VALIDATORS*/{{}}/**SCHEMA_VALIDATORS*/
	}};
}});
"""

CLASSIC_BODY = """define("UsrPage", [{deps}], function({args}) {{
	return {{
		entitySchemaName: "Contact",
		attributes: {{{attributes}}},
		methods: {{{methods}
		}},
		diff: /**SCHEMA_DIFF*/[{diff}]/**SCHEMA_DIFF*/
	}};
}});
"""


def _client_layer(pkg: Path, name: str, body: str, caption_keys: dict | None = None) -> None:
    import json
    folder = pkg / "Schemas" / name
    folder.mkdir(parents=True)
    uid = f"00000000-0000-4000-9000-{abs(hash((pkg.name, name))) % 10 ** 12:012d}"
    (folder / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": uid, "Name": name, "Parent": {"UId": "base-page", "Name": name},
                                                                        "ExtendParent": True, "ManagerName": "ClientUnitSchemaManager"}}), encoding="utf-8")
    meta = [f'= MetaData.Schema.UId "{uid}"', f'= MetaData.Schema.B6 "pkg-{pkg.name}"']
    meta += [f'= MetaData.Schema.B2.["{k}"].A4 "{uid}"' for k in (caption_keys or {})]
    (folder / "metadata.json").write_bytes(("\r\n".join(meta) + "\r\n").encode("utf-8"))
    (folder / f"{name}.js").write_bytes(body.encode("utf-8"))


def test_merge_pages_fold_freedom_arrays_and_classic_methods():
    import json
    import shutil
    import tempfile
    from creatio_schemas.describe.merge import merge_schema
    from creatio_schemas.integrity import compare, snapshot
    from creatio_schemas.page.fold import fold, element_lines
    from creatio_schemas.page.schema import PageSchema

    root = Path(tempfile.mkdtemp())
    try:
        _layer_workspace(root, {"UsrA": (["CrtBase"], {}), "UsrB": (["UsrA"], {}), "UsrC": (["UsrB"], {})})
        pk = root / "packages"
        ins = [{"operation": "insert", "name": "UsrBox", "values": {"type": "crt.FlexContainer"}, "parentName": "Main", "propertyName": "items", "index": 0},
               {"operation": "insert", "name": "UsrNote", "values": {"type": "crt.Input", "caption": "Note"}, "parentName": "UsrBox", "propertyName": "items", "index": 0}]
        upd = [{"operation": "merge", "name": "UsrNote", "values": {"caption": "Note, by B"}}, {"operation": "remove", "name": "BaseButton"}]
        mv = [{"operation": "move", "name": "UsrBox", "parentName": "Side", "propertyName": "items", "index": 1}]
        handler = '{{\n\t\t\t\trequest: "crt.HandleViewModelInitRequest",\n\t\t\t\thandler: async (request, next) => {{\n\t\t\t\t\tawait next?.handle(request);\n\t\t\t\t\trequest.$context.UsrTrace = (request.$context.UsrTrace || "") + "{0}";\n\t\t\t\t}}\n\t\t\t}}'
        for name, view, hs, conv, deps, args in (("UsrA", ins, [handler.format("A")], '"usr.Upper": function(v) { return v; }', "[]", ""),
                                                   ("UsrB", upd, [], '"usr.Upper": function(v) { return (v || "").toUpperCase(); }', '["@creatio-devkit/common"]', "sdk"),
                                                   ("UsrC", mv, [handler.format("C")], "", '["@creatio-devkit/common"]', "sdk")):
            _client_layer(pk / name, "UsrPage_FormPage", FREEDOM_BODY.format(deps=deps, args=args, view=json.dumps(view, indent="\t"), vm="[]",
                                                                            handlers=", ".join(hs), converters=conv), {"Caption": 1})
        before = snapshot(root, "UsrPage_FormPage")
        assert before[0] == "layers: UsrA > UsrB > UsrC", before
        assert "element UsrNote crt.Input parent UsrBox caption Note, by B" in before and "element UsrBox crt.FlexContainer parent Side" in before
        assert "removed BaseButton" in before
        assert before.count("handler crt.HandleViewModelInitRequest #1") == 1 and "converter usr.Upper" in before
        snap = sorted(str(p) for p in root.rglob("*"))
        text, code = merge_schema(root, "UsrPage_FormPage", direction="down")
        assert code == 0 and text.splitlines()[0] == "UsrPage_FormPage page: 3 layers, target UsrA", text
        assert "  converter usr.Upper: UsrB's kept, UsrA's dropped" in text and sorted(str(p) for p in root.rglob("*")) == snap
        text, code = merge_schema(root, "UsrPage_FormPage", apply=True, direction="down")
        assert code == 0 and text.endswith("merged UsrPage_FormPage into UsrA: 3 layers -> 1"), text
        assert not (pk / "UsrB" / "Schemas" / "UsrPage_FormPage").exists()
        merged = PageSchema(pk / "UsrA", "UsrPage_FormPage")
        # a merge / move of an element the array itself inserts is folded into the insert (the Shell skips it otherwise)
        assert [op["operation"] for op in merged.view_config_diff] == ["insert", "insert", "remove"]
        assert merged.view_config_diff[1]["values"]["caption"] == "Note, by B" and merged.view_config_diff[0]["parentName"] == "Side"
        assert element_lines(fold(merged.view_config_diff), "type") == element_lines(fold(ins + upd + mv), "type")
        assert [r for r, _ in merged.handlers()] == ["crt.HandleViewModelInitRequest"] * 2
        raw = merged.raw_sections()
        assert raw["SCHEMA_DEPS"] == '["@creatio-devkit/common"]' and raw["SCHEMA_ARGS"] == "(sdk)" and "toUpperCase" in raw["SCHEMA_CONVERTERS"]
        after = snapshot(root, "UsrPage_FormPage")
        assert compare(before, after) == ["~ layers:  UsrA > UsrB > UsrC -> UsrA",
                                          "- layer handler crt.HandleViewModelInitRequest UsrC",
                                          "+ layer handler crt.HandleViewModelInitRequest UsrA"] or compare(before, after, ignore_layers=True) == [], compare(before, after)
        assert compare(before, after, ignore_layers=True) == []
        meta = (pk / "UsrA" / "Schemas" / "UsrPage_FormPage" / "metadata.json").read_bytes().decode("utf-8")
        assert meta.count('= MetaData.Schema.B6 "pkg-UsrA"') == 1 and "pkg-UsrB" not in meta

        # a planted difference: an element removed from a layer shows in the compare
        planted = [l for l in after if l != "element UsrBox crt.FlexContainer parent Side"]
        assert compare(after, planted) == ["- element UsrBox crt.FlexContainer parent Side"]

        # Classic: onEntityInitialized in three layers folds into one method with one callParent
        cls = {"UsrA": ("this.set(\"X\", (this.get(\"X\") || \"\") + \"A\");", '"UsrA1": {dataValueType: Terrasoft.DataValueType.TEXT}', '{"operation": "insert", "name": "UsrA1", "values": {"bindTo": "UsrA1"}}'),
               "UsrB": ("this.set(\"X\", this.get(\"X\") + \"B\");", '"UsrA1": {dataValueType: Terrasoft.DataValueType.INTEGER}', '{"operation": "merge", "name": "UsrA1", "values": {"enabled": false}}'),
               "UsrC": ("this.set(\"X\", this.get(\"X\") + \"C\");", "", "")}
        for name, (line, attr, diff) in cls.items():
            methods = f"\n\t\t\tonEntityInitialized: function() {{\n\t\t\t\tthis.callParent(arguments);\n\t\t\t\t{line}\n\t\t\t}}"
            _client_layer(pk / name, "UsrPage", CLASSIC_BODY.format(deps="", args="", attributes=attr, methods=methods, diff=diff))
        classic_before = snapshot(root, "UsrPage")
        assert "method onEntityInitialized" in classic_before and "layer method onEntityInitialized UsrA > UsrB > UsrC" in classic_before
        text, code = merge_schema(root, "UsrPage", apply=True, direction="down")
        assert code == 0 and "  method onEntityInitialized: folded UsrA > UsrB > UsrC" in text and "  attributes UsrA1: UsrB's kept" in text, text
        body = (pk / "UsrA" / "Schemas" / "UsrPage" / "UsrPage.js").read_text(encoding="utf-8")
        assert body.count("callParent") == 1 and body.index('+ "A"') < body.index('+ "B"') < body.index('+ "C"'), body
        assert "INTEGER" in body and "TEXT" not in body and body.count('"operation"') == 2
        assert compare(classic_before, snapshot(root, "UsrPage"), ignore_layers=True) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)

    root = Path(tempfile.mkdtemp())
    try:  # the stops: a callParent whose value is used, and an element changed in two layers without the site's order
        _layer_workspace(root, {"UsrA": (["CrtBase"], {}), "UsrB": (["UsrA"], {})})
        pk = root / "packages"
        for name, line in (("UsrA", "this.callParent(arguments);"), ("UsrB", "var r = this.callParent(arguments); this.x(r);")):
            methods = f"\n\t\t\tonEntityInitialized: function() {{\n\t\t\t\t{line}\n\t\t\t}}"
            _client_layer(pk / name, "UsrPage", CLASSIC_BODY.format(deps="", args="", attributes="", methods=methods, diff=""))
        for name in ("UsrA", "UsrB"):
            view = [{"operation": "merge", "name": "BaseField", "values": {"visible": name == "UsrB"}}]
            _client_layer(pk / name, "UsrPage_FormPage", FREEDOM_BODY.format(deps="[]", args="", view=json.dumps(view), vm="[]", handlers="", converters=""))
        snap = sorted(str(p) for p in root.rglob("*"))
        text, code = merge_schema(root, "UsrPage", apply=True, direction="down")
        assert code == 1 and "conflict method onEntityInitialized (UsrA > UsrB): callParent's value is used" in text and text.endswith("nothing written"), text
        text, code = merge_schema(root, "UsrPage_FormPage", apply=True, direction="down")
        assert code == 1 and "conflict element BaseField (merge): UsrA and UsrB" in text and "stopped: 1 conflicts - nothing written" in text, text
        assert sorted(str(p) for p in root.rglob("*")) == snap

        class SiteEnv:  # the site's order: with it an element changed in two layers is folded in that order
            clio_name, url = "dev", ""

            def sql(self, text):
                if text.startswith('select "Name"::text "package"'):  # merge's levels query, not the layers one
                    return [{"package": "UsrA", "level": "3"}, {"package": "UsrB", "level": "4"}]
                if "tsp_GetSysSchemaParents" in text:
                    return [_row("UsrA", "0", "3"), _row("UsrB", "0", "2")]
                return []
        text, code = merge_schema(root, "UsrPage_FormPage", env=SiteEnv(), direction="down")
        assert code == 0 and "conflict element BaseField" in text and "references: none to the 1 layers removed" in text, text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _rm_tree(root: Path) -> None:
    """rmtree that also removes git's read-only object files (Windows)."""
    import os
    import shutil
    import stat

    def writable(func, path, _):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(root, onexc=writable) if Path(root).exists() else None


def test_merge_package_merges_layers_moves_the_rest_and_redirects_dependencies():
    import json
    import shutil
    import subprocess
    import tempfile
    from creatio_schemas.describe.diff import schema_diff
    from creatio_schemas.describe.package_merge import merge_package

    root = Path(tempfile.mkdtemp())
    try:
        _layer_workspace(root, {"UsrBase": (["CrtBase"], {}), "UsrChild": (["UsrBase", "CrtCoreBase"], {}),
                                "UsrSibling": (["UsrChild"], {}), "UsrOther": (["UsrChild"], {})})
        pk = root / "packages"
        for name in ("UsrBase", "UsrChild"):
            _object_layer(pk / name, "Contact", [(f"{name}1", f"{name.lower()}-col", SHORT_TEXT)])
        desc = json.loads((pk / "UsrBase" / "descriptor.json").read_text(encoding="utf-8-sig"))
        desc["Descriptor"]["Type"] = 1  # an assembly package: it can take Files/cs
        (pk / "UsrBase" / "descriptor.json").write_text(json.dumps(desc), encoding="utf-8")
        proc = TOOLS / "process" / "tests" / "fixtures" / "UsrPkg"
        shutil.copytree(proc / "Schemas" / "UsrDeleteOldLogs_Process", pk / "UsrChild" / "Schemas" / "UsrNotify_Process")
        for res in (proc / "Resources").glob("UsrDeleteOldLogs_Process.*"):
            shutil.copytree(res, pk / "UsrChild" / "Resources" / res.name.replace("UsrDeleteOldLogs_Process", "UsrNotify_Process"))
        shutil.copytree(TOOLS / "data" / "tests" / "fixtures" / "UsrPkg" / "Data" / "UsrStatus", pk / "UsrChild" / "Data" / "UsrStatus")
        src = pk / "UsrChild" / "Schemas" / "UsrOrderService"
        src.mkdir(parents=True)
        (src / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": "src-uid", "Name": "UsrOrderService", "ManagerName": "SourceCodeSchemaManager"}}), encoding="utf-8")
        (src / "UsrOrderService.cs").write_text("namespace Terrasoft.Configuration { public class UsrOrderService { } }", encoding="utf-8")
        (pk / "UsrChild" / "Files" / "cs").mkdir(parents=True)
        (pk / "UsrChild" / "Files" / "cs" / "UsrHelper.cs").write_text("namespace Terrasoft.Configuration { static class UsrHelper { } }", encoding="utf-8")
        _object_layer(pk / "UsrOther", "Contact", [("UsrOther1", "other-col", SHORT_TEXT)])  # a third package's layer, above both
        git = ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "core.autocrlf=false"]
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(git + ["add", "-A"], cwd=root, check=True)
        subprocess.run(git + ["commit", "-q", "-m", "fixture"], cwd=root, check=True)
        snap = sorted(str(p) for p in root.rglob("*") if ".git" not in p.parts)

        text, code = merge_package(root, "UsrChild", "UsrBase")
        lines = text.splitlines()
        assert code == 0 and lines[0].startswith("layer   object  Contact") and "-> UsrBase   (2 layers: UsrChild, UsrBase)   merge" in lines[0], text
        assert any(l.startswith("move    process UsrNotify_Process") and l.endswith("-> UsrBase   uid kept") for l in lines), text
        flat = [" ".join(l.split()) for l in lines]
        assert "move source UsrOrderService -> UsrBase uid kept" in flat and "move data Data/UsrStatus -> UsrBase" in flat
        assert "move source Files/cs -> UsrBase 1 files" in flat and "depends UsrSibling: DependsOn UsrChild -> UsrBase" in lines
        assert "depends UsrOther: DependsOn UsrChild -> UsrBase" in lines
        assert "depends UsrBase: gains CrtCoreBase" in lines and any(l.startswith("note    dependencies:") for l in lines)
        assert text.endswith("(dry run; --apply writes)") and sorted(str(p) for p in root.rglob("*") if ".git" not in p.parts) == snap

        text, code = merge_package(root, "UsrChild", "UsrBase", apply=True)
        assert code == 0 and text.endswith("UsrChild: empty - remove the application on the site, then delete the folder"), text
        assert sorted(p.name for p in (pk / "UsrChild").iterdir()) == ["descriptor.json"]
        assert (pk / "UsrBase" / "Schemas" / "UsrNotify_Process" / "metadata.json").is_file() and (pk / "UsrBase" / "Data" / "UsrStatus").is_dir()
        assert (pk / "UsrBase" / "Files" / "cs" / "UsrHelper.cs").is_file() and (pk / "UsrBase" / "Resources" / "UsrNotify_Process.Process").is_dir()
        sib = json.loads((pk / "UsrSibling" / "descriptor.json").read_text(encoding="utf-8-sig"))["Descriptor"]["DependsOn"]
        assert [d["Name"] for d in sib] == ["UsrBase"] and sib[0]["UId"] == "pkg-UsrBase"
        base = json.loads((pk / "UsrBase" / "descriptor.json").read_text(encoding="utf-8-sig"))["Descriptor"]["DependsOn"]
        assert [d["Name"] for d in base] == ["CrtBase", "CrtCoreBase"]
        assert (pk / "UsrOther" / "Schemas" / "Contact").is_dir()  # the third package's layer is not touched
        merged = (pk / "UsrBase" / "Schemas" / "Contact" / "metadata.json").read_bytes().decode("utf-8")
        assert "UsrBase1" in merged and "UsrChild1" in merged and "UsrOther1" not in merged
        diff = schema_diff(pk / "UsrBase")
        assert "+ UsrNotify_Process  process (new)" in diff and "+ Data/UsrStatus  data (new)" in diff and "UsrChild1" in diff, diff

        # the name clash: the parent holds its own schema of the child's name with another UId
        _rm_tree(root)
        root = Path(tempfile.mkdtemp())
        pk = root / "packages"
        _layer_workspace(root, {"UsrBase": (["CrtBase"], {}), "UsrChild": (["UsrBase"], {})})
        _object_layer(pk / "UsrBase", "UsrThing", [], replacing=False)
        _object_layer(pk / "UsrChild", "UsrThing", [], replacing=False)
        snap = sorted(str(p) for p in root.rglob("*"))
        text, code = merge_package(root, "UsrChild", "UsrBase", apply=True)
        assert code == 1 and "stop    object  UsrThing" in text and "name clash, different UId" in text and text.endswith("nothing written"), text
        assert sorted(str(p) for p in root.rglob("*")) == snap
        assert merge_package(root, "UsrBase", "UsrChild")[1] == 1 and merge_package(root, "UsrNope", "UsrBase")[1] == 2
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert main(["merge-package", str(root), "UsrChild", "--into", "UsrBase"]) == 1
        assert "name clash" in out.getvalue()
    finally:
        _rm_tree(root)


def test_merge_run_calls_the_steps_in_order_and_stops_on_red_or_difference():
    import tempfile
    from creatio_schemas.describe.merge_run import Engines, merge_run

    PLAN = "\n".join([
        "layer   object  UsrOrder                     -> UsrBase   (2 layers: UsrChild, UsrBase)   merge",
        "move    process UsrNotify_Process            -> UsrBase   uid kept",
        "move    page    UsrOrder_FormPage            -> UsrBase   uid kept",
        "depends UsrSibling: DependsOn UsrChild -> UsrBase"])

    class Fake(Engines):
        site = ["UsrCore", "UsrExtra"]  # the dependency rows of the parent on the site; a test adds one

        def __init__(self, red_before=False, drift=False, plan_code=0, merged=False):
            self.calls, self.red_before, self.drift, self.plan_code, self.merged = [], red_before, drift, plan_code, merged

        def audit(self, page):
            self.calls.append("audit:" + page)
            return ["comboboxes 0"]

        def descriptor_depends(self, package):
            return ["UsrCore", "UsrExtra"] if package == "UsrBase" else []

        def site_depends(self, package):
            return list(Fake.site)

        def merge_package(self, child, parent, apply):
            self.calls.append("merge" if apply else "plan")
            self.merged = self.merged or apply
            return (PLAN if not self.plan_code else "stop    object  UsrX  clash\nstopped: 1 stops - nothing written"), self.plan_code

        def cases(self, child, out):
            self.calls.append("cases")
            (out / "Cases" / "UsrChild").mkdir(parents=True)
            (out / "Cases" / "UsrChild" / "UsrOrder.act").write_text("# case", encoding="utf-8")
            return ["wrote Cases/UsrChild/UsrOrder.act", "not generated: Classic page X"]

        def run_tests(self, root, dest):
            self.calls.append("tests-after" if self.merged else "tests-before")
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "report.txt").write_text("Cases: 3", encoding="utf-8")
            return (2, 1, "red") if self.red_before and not self.merged else (3, 0, "ok")

        def snapshot(self, schema):
            self.calls.append("snap:" + schema)
            return [f"object {schema}", "layers:  UsrBase" if self.merged else "layers:  UsrChild", "column A"] + (["column B"] if self.drift and self.merged else [])

        def push(self, package):
            self.calls.append("push:" + package)
            return 0, "pushed"

        def order(self, packages):
            return packages

    def go(ev, apply=False, resume=False, **kw):
        eng = Fake(**kw)
        text, code = merge_run("ws", "UsrChild", "UsrBase", ev, "env", apply, resume, eng)
        return eng, text, code

    root = Path(tempfile.mkdtemp())
    try:
        # a rehearsal ends after the snapshots and writes nothing but the evidence
        eng, text, code = go(root / "a")
        assert code == 0 and text.endswith("rehearsal: nothing written"), text
        assert eng.calls == ["plan", "cases", "tests-before", "snap:UsrOrder", "snap:UsrOrder_FormPage", "audit:UsrOrder_FormPage"], eng.calls
        assert (root / "a" / "before" / "audit.txt").read_text(encoding="utf-8") == "=== UsrOrder_FormPage\ncomboboxes 0\n"
        assert (root / "a" / "plan.txt").is_file() and (root / "a" / "before" / "UsrOrder.snapshot").is_file() and (root / "a" / "before" / "report.txt").is_file()
        assert not (root / "a" / "merge.txt").exists()
        # a red case before stops before the merge
        eng, text, code = go(root / "b", apply=True, red_before=True)
        assert code == 1 and "tests before: 1 red of 3" in text and "merge" not in eng.calls, text
        # a stop in the plan ends before any test
        eng, text, code = go(root / "c", apply=True, plan_code=1)
        assert code == 1 and eng.calls == ["plan"] and "stop: plan" in text
        # the merged descriptor names a package the site does not hold for the parent: stop before the push, --continue pushes
        Fake.site = ["UsrCore"]
        eng, text, code = go(root / "g", apply=True)
        assert code == 1 and text.endswith("stop: parent UsrBase lacks the dependency UsrExtra on the site: add it in the configuration, then --continue"), text
        assert not [c for c in eng.calls if c.startswith("push")] and (root / "g" / "push-pending.txt").is_file()
        Fake.site = ["UsrCore"]  # still missing: the same stop again
        assert go(root / "g", resume=True)[2] == 1
        Fake.site = ["UsrCore", "UsrExtra"]  # added in the configuration
        eng, text, code = go(root / "g", resume=True)
        assert code == 3 and eng.calls == ["push:UsrBase", "push:UsrSibling"] and (root / "g" / "paused.txt").is_file(), (text, eng.calls)
        assert not (root / "g" / "push-pending.txt").exists()
        # the full run: merge, push the parent then the dependents, pause
        eng, text, code = go(root / "d", apply=True)
        assert code == 3 and "paused: remove the application of UsrChild" in text and (root / "d" / "paused.txt").is_file(), text
        assert eng.calls[-3:] == ["merge", "push:UsrBase", "push:UsrSibling"], eng.calls
        # --continue: compare, tests after, the last line
        eng, text, code = go(root / "d", resume=True, merged=True)
        assert code == 0 and text.endswith("merged UsrChild into UsrBase: 1 layers, 2 moves, tests 3/3 before and after, compare same"), text
        assert eng.calls == ["snap:UsrOrder", "snap:UsrOrder_FormPage", "audit:UsrOrder_FormPage", "tests-after"], eng.calls
        assert (root / "d" / "after" / "audit.txt").is_file()
        assert (root / "d" / "compare.txt").read_text(encoding="utf-8").count(": same") == 2 and not (root / "d" / "paused.txt").exists()
        # a difference after the push: exit 1, both snapshots on disk, no tests after
        go(root / "e", apply=True, drift=True)
        eng, text, code = go(root / "e", resume=True, drift=True, merged=True)
        assert code == 1 and "stop: compare differs: UsrOrder, UsrOrder_FormPage" in text and "tests-after" not in eng.calls, text
        assert (root / "e" / "before" / "UsrOrder.snapshot").is_file() and (root / "e" / "after" / "UsrOrder.snapshot").is_file()
        assert "+ column B" in (root / "e" / "compare.txt").read_text(encoding="utf-8")
        # --continue without a pause is refused
        assert go(root / "f", resume=True)[2] == 1
    finally:
        _rm_tree(root)


def _res_xml(culture: str, items: dict) -> str:
    body = "\n".join(f'\t\t\t<Item Name="{k}" Value="{v}" />' for k, v in items.items())
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<Resources Culture="{culture}">\n\t<Group Type="String">\n\t\t<Items>\n{body}\n'
            f'\t\t</Items>\n\t</Group>\n</Resources>\n')


def test_index_format_6_carries_captions_in_the_primary_culture():
    import json
    import shutil
    import tempfile
    from creatio_schemas.describe.core import open_item
    from creatio_schemas.describe.index import INDEX_FORMAT, captions_of, primary_culture
    from creatio_schemas.page import PageSchema

    assert INDEX_FORMAT == 6
    root = Path(tempfile.mkdtemp())
    try:
        pkg = root / "packages" / "UsrPkg"
        shutil.copytree(OBJECTS, pkg)
        page = PageSchema.create(pkg, "UsrOrder_FormPage", "UsrOrder")
        page.add_field("UsrName")
        page.add_field("UsrStatus")
        page.save()

        # one culture: that one; the columns of an own object carry their caption, a page element its name, type, parent and control
        idx = PackageIndex(pkg)
        idx.refresh()
        assert idx.data["culture"] == "en-US" and idx.data["cultures"]["en-US"] > 20
        assert idx.schemas["UsrOrder"]["columns"]["UsrName"] == "Name" and idx.schemas["UsrOrder"]["columns"]["UsrDueDate"] == "Due date"
        els = {e["name"]: e for e in idx.schemas["UsrOrder_FormPage"]["elements"]}
        assert els and all({"name", "type", "parent", "caption"} <= set(e) for e in els.values()), els
        field = next(e for e in els.values() if e["type"] == "crt.Input")
        assert field["caption"] == "Name" and field["parent"] and field["control"].startswith("$"), field

        # a second culture with more keys becomes the primary one; a key it lacks is null; the index is rebuilt in it
        order_res = pkg / "Resources" / "UsrOrder.Entity"
        uk = {"Caption": "Zamovlennia", "Columns.UsrName.Caption": "Nazva", "Columns.UsrStatus.Caption": "Stan",
              **{f"Columns.UsrFiller{i}.Caption": f"Filler {i}" for i in range(80)}}
        (order_res / "resource.uk-UA.xml").write_text(_res_xml("uk-UA", uk), encoding="utf-8-sig")
        idx = PackageIndex(pkg)
        changes = idx.refresh()
        assert idx.data["culture"] == "uk-UA" and idx.data["cultures"]["uk-UA"] > len(uk) and "UsrOrder" in changes["changed"], changes
        assert idx.schemas["UsrOrder"]["columns"]["UsrName"] == "Nazva" and idx.schemas["UsrOrder"]["columns"]["UsrDueDate"] is None
        els = {e["name"]: e for e in idx.schemas["UsrOrder_FormPage"]["elements"]}
        assert next(e for e in els.values() if e["type"] == "crt.Input")["caption"] == "Nazva"
        assert PackageIndex(pkg).refresh() == {"added": [], "changed": [], "removed": []}  # nothing to redo the next time
        # the culture goes away: the captions come back in en-US (every item re-read)
        (order_res / "resource.uk-UA.xml").unlink()
        idx = PackageIndex(pkg)
        idx.refresh()
        assert idx.data["culture"] == "en-US" and idx.schemas["UsrOrder"]["columns"]["UsrName"] == "Name"
        first = describe_item(pkg, "UsrOrder", "resources").splitlines()[0]
        assert first.startswith("primary culture: en-US (") and "keys; " in first and first.endswith(", ...)"), first

        # a tie: the same key counts in both cultures -> project.json's culture, else en-US
        for res in (pkg / "Resources").iterdir():
            en = res / "resource.en-US.xml"
            if en.is_file():
                (res / "resource.uk-UA.xml").write_text(en.read_text(encoding="utf-8-sig").replace('Culture="en-US"', 'Culture="uk-UA"'), encoding="utf-8-sig")
        counts = {"en-US": 5, "uk-UA": 5}
        assert primary_culture(counts, pkg) == "en-US"
        (root / "project.json").write_text(json.dumps({"culture": "uk-UA"}), encoding="utf-8")
        assert primary_culture(counts, pkg) == "uk-UA" and primary_culture({"en-US": 5, "uk-UA": 6}, pkg) == "uk-UA"
        assert primary_culture({"en-US": 9, "uk-UA": 5}, pkg) == "en-US" and primary_culture({"ru-RU": 3}, pkg) == "ru-RU" and primary_culture({}, pkg) == "uk-UA"

        # process elements and parameters, user task parameters, rules: the same field, null where the key is missing
        proc = open_item(TOOLS / "process" / "tests" / "fixtures" / "UsrPkg", "UsrDeleteOldLogs_Process")
        got = captions_of("process", proc, "en-US")
        assert got["elements"]["DeleteDataUserTask1"] == "Delete old logs" and got["elements"]["SequenceFlow1"] is None
        assert captions_of("process", proc, "uk-UA")["elements"]["DeleteDataUserTask1"] is None
        rules = open_item(TOOLS / "rules" / "tests" / "fixtures" / "UsrPkg", "ContactAddressBusinessRule")
        assert captions_of("rules", rules, "en-US") == {"rules": {"BusinessRule_0a2df3a": "Zip read-only for the test marker"}}
        task = open_item(TOOLS / "usertask" / "tests" / "fixtures" / "UsrPkg", "UsrRunCase_UserTask")
        assert captions_of("user-task", task, "en-US")["parameters"]["RecordId"] == "RecordId"
    finally:
        _rm_tree(root)


def test_index_lookup_values_carry_the_caption_of_the_primary_culture():
    import json
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "UsrPkg"
        shutil.copytree(DATA, pkg)
        binding = pkg / "Data" / "UsrStatus"
        desc = {"Descriptor": {"Schema": {"Name": "UsrOrderStatus"}, "Columns": [
            {"ColumnName": "Code", "ColumnUId": "usr-code", "IsKey": True}, {"ColumnName": "Name", "ColumnUId": "usr-name"}]}}
        (binding / "descriptor.json").write_text(json.dumps(desc), encoding="utf-8")
        rows = {"PackageData": [{"Row": [{"SchemaColumnUId": "usr-code", "Value": "new"}]},
                                {"Row": [{"SchemaColumnUId": "usr-code", "Value": "done"}, {"SchemaColumnUId": "usr-name", "Value": "Done"}]}]}
        (binding / "data.json").write_text(json.dumps(rows), encoding="utf-8")
        loc = binding / "Localization"
        loc.mkdir(exist_ok=True)
        for culture, names in (("en-US", {"new": "New", "done": "Done"}), ("uk-UA", {"new": "Novyi"})):
            body = {"PackageData": [{"Row": [{"SchemaColumnUId": "usr-code", "Value": code}, {"SchemaColumnUId": "usr-name", "Value": name}]}
                                    for code, name in names.items()]}
            (loc / f"data.{culture}.json").write_text(json.dumps(body), encoding="utf-8")
        idx = PackageIndex(pkg)
        idx.refresh()
        assert idx.data["culture"] == "en-US"
        assert idx.data["data"]["UsrStatus"]["keys"] == [{"value": "new", "caption": "New"}, {"value": "done", "caption": "Done"}]
        (pkg / "Resources" / "UsrOrderStatus.Entity" / "resource.uk-UA.xml").write_text(
            _res_xml("uk-UA", {f"Columns.UsrK{i}.Caption": "x" for i in range(60)}), encoding="utf-8-sig")
        idx = PackageIndex(pkg)
        idx.refresh()
        assert idx.data["culture"] == "uk-UA"
        # a value without a caption in the primary culture keeps its own name as the caption
        assert idx.data["data"]["UsrStatus"]["keys"] == [{"value": "new", "caption": "Novyi"}, {"value": "done", "caption": "Done"}]


def _captioned_page(root: Path):
    """A workspace with the objects fixture (UsrOrder: Name, Status, Amount ...) and a form page of it with a captioned tab, a grid, two fields
    and a grid of details; every string in en-US and, for the tab and one field, in uk-UA. Returns the package folder."""
    import shutil
    from creatio_schemas.page import PageSchema

    pkg = root / "packages" / "UsrPkg"
    shutil.copytree(OBJECTS, pkg)
    (pkg / "Resources" / "UsrOrder.Entity" / "resource.uk-UA.xml").write_text(
        _res_xml("uk-UA", {"Columns.UsrName.Caption": "Nazva", "Columns.UsrStatus.Caption": "Stan"}), encoding="utf-8-sig")
    page = PageSchema.create(pkg, "UsrOrder_FormPage", "UsrOrder", cultures=["en-US", "uk-UA"])
    page.view_config_diff.append({"operation": "insert", "name": "UsrMainTab", "values": {"type": "crt.TabContainer", "caption": "$Resources.Strings.UsrMainTab"},
                                  "parentName": "Tabs", "propertyName": "tabs", "index": 0})
    page.view_config_diff.append({"operation": "insert", "name": "UsrMainGrid", "values": {"type": "crt.GridContainer", "columns": ["minmax(32px, 1fr)"]},
                                  "parentName": "UsrMainTab", "propertyName": "items", "index": 0})
    page.add_field("UsrName", parent="UsrMainGrid")
    page.add_field("UsrStatus", parent="UsrMainGrid")
    page.view_config_diff.append({"operation": "insert", "name": "UsrLines", "values": {"type": "crt.DataGrid", "label": "$Resources.Strings.UsrLines",
                                                                                          "items": "$UsrLines"},
                                  "parentName": "UsrMainTab", "propertyName": "items", "index": 1})
    page.resources.set("LocalizableStrings.UsrMainTab.Value", "Main", ["en-US"])
    page.resources.set("LocalizableStrings.UsrMainTab.Value", "Holovna", ["uk-UA"])
    page.resources.set("LocalizableStrings.UsrLines.Value", "Lines", ["en-US"])
    page.save()
    return pkg


def test_where_names_the_element_its_column_the_parents_and_the_layer():
    import json
    import tempfile

    root = Path(tempfile.mkdtemp())
    try:
        pkg = _captioned_page(root)
        out = describe_item(pkg, "UsrOrder_FormPage", "where UsrName").splitlines()
        assert out[0] == "UsrName 'Name'  crt.Input  control $UsrName -> attribute UsrName -> PDS UsrOrder.UsrName 'Name'", out
        assert out[1] == "  in Tabs > UsrMainTab 'Main' > UsrMainGrid (row 1, col 1)", out
        assert out[2] == "  layer: added in UsrPkg" and len(out) == 3
        # an element with no control: the line stops after the type and the caption; the container of the parent page is inherited
        assert describe_item(pkg, "UsrOrder_FormPage", "where UsrMainTab").splitlines()[0] == "UsrMainTab 'Main'  crt.TabContainer"
        inherited = describe_item(pkg, "UsrOrder_FormPage", "where Tabs").splitlines()
        assert inherited[0] == "Tabs (caption not in workspace)" and inherited[-1].startswith("  layer: inherited from ")
        # another culture is read from the resources; the culture is named when it is not the primary
        uk = describe_item(pkg, "UsrOrder_FormPage", "where UsrName culture=uk-UA").splitlines()
        assert uk[0].startswith("UsrName 'Nazva' (uk-UA)") and "UsrOrder.UsrName 'Nazva'" in uk[0] and "UsrMainTab 'Holovna'" in uk[1], uk
        # json: the same as one object
        data = json.loads(describe_item(pkg, "UsrOrder_FormPage", "where UsrStatus format=json"))
        assert data["caption"] == "Status" and data["column"] == "UsrOrder.UsrStatus" and data["column_caption"] == "Status"
        assert [p["name"] for p in data["parents"]] == ["Tabs", "UsrMainTab", "UsrMainGrid"] and data["parents"][1]["caption"] == "Main"
        assert data["layer"] == "added in UsrPkg" and data["position"] == "row 2, col 1"
        # a name that is not an element: the three closest
        try:
            describe_item(pkg, "UsrOrder_FormPage", "where UsrNam")
            raise AssertionError("no error")
        except QueryError as e:
            assert str(e).startswith("no element UsrNam in UsrOrder_FormPage; closest: UsrName") and "UsrMainGrid" not in str(e), e
        try:
            describe_item(pkg, "UsrOrder_FormPage", "where UsrName culture=xx-XX")
            raise AssertionError("no error")
        except QueryError as e:
            assert "has no culture xx-XX" in str(e)
        assert "where" in describe_item(pkg, "UsrOrder_FormPage", "topics")
    finally:
        _rm_tree(root)


def _raw_binding(pkg: Path, name: str, schema: str, rows: list[dict], loc: dict | None = None) -> None:
    """A binding as the platform exports it: cells by column UId only; `loc` = {culture: [rows]} of the localised columns."""
    import json

    cols = list(dict.fromkeys(c for r in rows for c in r))
    uid = {c: f"00000000-0000-0000-0000-{i:012d}" for i, c in enumerate(cols)}
    ddir = pkg / "Data" / name
    (ddir / "Localization").mkdir(parents=True)
    desc = {"Descriptor": {"UId": "00000000-0000-0000-0001-000000000000", "Name": name, "Schema": {"Name": schema}, "InstallType": 0,
                           "Columns": [{"ColumnName": c, "ColumnUId": uid[c], "IsKey": c == "Id", "IsForceUpdate": False, "DataTypeValueUId": ""}
                                       for c in cols]}}
    (ddir / "descriptor.json").write_text(json.dumps(desc), encoding="utf-8")
    (ddir / "data.json").write_text(json.dumps({"PackageData": [{"Row": [{"SchemaColumnUId": uid[c], "Value": v} for c, v in r.items()]}
                                                                for r in rows]}), encoding="utf-8")
    for culture, texts in (loc or {}).items():
        (ddir / "Localization" / f"data.{culture}.json").write_text(json.dumps({"PackageData": [
            {"Row": [{"ColumnName": c, "SchemaColumnUId": uid.get(c, ""), "Value": v} for c, v in r.items()]} for r in texts]}), encoding="utf-8")


def test_where_on_the_page_names_the_section_the_object_and_the_record_type():
    import json
    import tempfile
    from creatio_schemas.describe import sections
    from creatio_schemas.page import PageSchema

    root = Path(tempfile.mkdtemp())
    try:
        pkg = _captioned_page(root)
        for name in ("UsrOrderVip_FormPage", "UsrOrderOld_FormPage"):
            PageSchema.create(pkg, name, "UsrOrder").save()
        uid = {n: json.loads((pkg / "Schemas" / n / "descriptor.json").read_text(encoding="utf-8-sig"))["Descriptor"]["UId"]
               for n in ("UsrOrder", "UsrOrder_FormPage", "UsrOrderVip_FormPage")}
        entity, vip, module = "aaaaaaaa-0000-0000-0000-000000000001", "aaaaaaaa-0000-0000-0000-000000000002", "aaaaaaaa-0000-0000-0000-000000000003"
        _raw_binding(pkg, "SysModuleEntity_UsrOrder", "SysModuleEntity",
                     [{"Id": entity, "SysEntitySchemaUId": uid["UsrOrder"], "TypeColumnUId": "23be70f8-b8ac-45a4-bfca-5b0d51624019"}])
        _raw_binding(pkg, "SysModule_UsrOrders", "SysModule", [{"Id": module, "Code": "UsrOrders", "SysModuleEntity": entity, "Caption": "Orders"}],
                     {"en-US": [{"Id": module, "Caption": "Orders"}], "uk-UA": [{"Id": module, "Caption": "Zamovlennia"}]})
        _raw_binding(pkg, "SysModuleEdit_UsrOrder", "SysModuleEdit", [
            {"Id": "aaaaaaaa-0000-0000-0000-000000000004", "SysModuleEntity": entity, "TypeColumnValue": "null", "CardSchemaUId": uid["UsrOrder_FormPage"]},
            {"Id": "aaaaaaaa-0000-0000-0000-000000000005", "SysModuleEntity": entity, "TypeColumnValue": vip, "CardSchemaUId": uid["UsrOrderVip_FormPage"]}])
        _raw_binding(pkg, "UsrOrderStatus_Vip", "UsrOrderStatus", [{"Id": vip, "Name": "VIP"}])

        assert describe_item(pkg, "UsrOrder_FormPage", "where") == "opens from: section UsrOrders 'Orders', object UsrOrder, default page (no type)"
        assert describe_item(pkg, "UsrOrderVip_FormPage", "where") == (
            f"opens from: section UsrOrders 'Orders', object UsrOrder, record type UsrStatus = 'VIP' ({vip})")
        assert describe_item(pkg, "UsrOrderOld_FormPage", "where") == f"opens from: {sections.NOT_REGISTERED}"
        assert describe_schema(pkg, "UsrOrderVip_FormPage", limit=0).splitlines()[-1].startswith("opens from: section UsrOrders")  # after the summary
        assert describe_schema(pkg, "UsrOrder", limit=0).splitlines()[-1] == f"pages: UsrOrder_FormPage (default), UsrOrderVip_FormPage (type 'VIP' ({vip}))"
        assert "pages:" not in describe_schema(pkg, "UsrOrderStatus")
        assert sections.registrations(pkg, uid["UsrOrder_FormPage"], "uk-UA")[0]["caption"] == "Zamovlennia"  # the culture asked for

        class FakeEnv:  # the site's rows: another package registers the old page for the VIP type
            def __init__(self):
                self.asked = []

            def sql(self, text):
                self.asked.append(text)
                return [{"code": "UsrOrders", "caption": "Orders", "section_schema": "UsrOrders_ListPage", "object": "UsrOrder",
                         "entity_uid": entity, "type_column": "23BE70F8-B8AC-45A4-BFCA-5B0D51624019", "type": vip.upper()}]

        env = FakeEnv()
        old = json.loads((pkg / "Schemas" / "UsrOrderOld_FormPage" / "descriptor.json").read_text(encoding="utf-8-sig"))["Descriptor"]["UId"]
        assert sections.opens_from(pkg, "UsrOrderOld_FormPage", old, env=env, env_name="dev") == [
            f"opens from: section UsrOrders 'Orders' (SysModule UsrOrders_ListPage), object UsrOrder, record type UsrStatus = 'VIP' ({vip}) (site dev)"]
        sql = env.asked[0]
        assert f"where e.\"CardSchemaUId\" = '{old.lower()}'" in sql and '"SysModuleEdit" e' in sql and '"SysModule" m' in sql
        empty = type("Empty", (), {"sql": lambda self, text: []})()
        assert sections.opens_from(pkg, "UsrOrderOld_FormPage", old, env=empty, env_name="dev") == ["opens from: not registered on the site (site dev)"]
    finally:
        _rm_tree(root)


def _archive(path: Path, files: dict) -> None:
    """A platform package archive: gzip of (int32 UTF-16 length, name, int32 byte length, bytes) records."""
    import gzip
    import struct

    with gzip.open(path, "wb") as f:
        for name, text in files.items():
            data = text.encode("utf-8-sig")
            f.write(struct.pack("<i", len(name)) + name.encode("utf-16-le") + struct.pack("<i", len(data)) + data)


def test_platform_captions_fill_the_base_columns_once():
    import json
    import tempfile
    from creatio_schemas.describe import platform
    from creatio_schemas.describe.index import index_path
    from creatio_schemas.page import PageSchema

    root = Path(tempfile.mkdtemp())
    try:
        pkg = _captioned_page(root)
        page = PageSchema(pkg, "UsrOrder_FormPage")
        page.add_field("CreatedOn", parent="UsrMainGrid")
        page.save()
        before = describe_item(pkg, "UsrOrder_FormPage", "where CreatedOn").splitlines()[0]
        assert before.endswith("UsrOrder.CreatedOn (caption not in workspace)"), before  # no paths.platform: today's output
        assert "platform" not in index_workspace(root / "packages")

        install = root / "install" / "Packages"
        install.mkdir(parents=True)
        _archive(install / "CrtCore.gz", {"descriptor.json": json.dumps({"Descriptor": {"Name": "CrtCore", "PackageVersion": "8.3.2.0"}}),
                                          "Resources\\BaseEntity.Entity\\resource.en-US.xml": _res_xml("en-US", {"Columns.CreatedOn.Caption": "Created on"}),
                                          "Resources\\BaseEntity.Entity\\resource.de-DE.xml": _res_xml("de-DE", {"Columns.CreatedOn.Caption": "Erstellt"}),
                                          "Schemas\\BaseEntity\\metadata.json": "{}"})
        _archive(install / "CrtBase.gz", {"Resources\\UsrBase.Entity\\resource.en-US.xml": _res_xml("en-US", {"Caption": "Base", "Columns.UsrCode.Caption": "Code",
                                                                                                              "Indexes.X.Caption": "skipped"}),
                                          "Resources\\UsrBasePage.ClientUnit\\resource.en-US.xml": _res_xml("en-US", {"LocalizableStrings.UsrTab.Value": "Tab"})})
        (root / "project.json").write_text(json.dumps({"paths": {"platform": "install"}}), encoding="utf-8")
        out = index_workspace(root / "packages").splitlines()
        assert out[-1].startswith("platform 8.3.2.0: 4 captions of 2 packages (en-US) in "), out  # de-DE is no culture of the workspace
        assert index_workspace(root / "packages").splitlines()[-1] == "platform 8.3.2.0: 4 captions, up to date"
        after = describe_item(pkg, "UsrOrder_FormPage", "where CreatedOn").splitlines()[0]
        assert after.endswith("UsrOrder.CreatedOn 'Created on' (CrtCore)"), after  # a system column: the BaseEntity caption
        db = index_path(pkg)
        assert platform.caption(db, "usrbase", "Columns.UsrCode.Caption", "uk-UA") == ("Code", "CrtBase")  # en-US when the culture has none
        assert platform.caption(db, "UsrBase", "Indexes.X.Caption", "en-US") is None
        assert platform.caption(db, "UsrBasePage", "LocalizableStrings.UsrTab.Value", "en-US") == ("Tab", "CrtBase")
        assert "platform 8.3.2.0" in index_workspace(root / "packages", stats=True)  # meta.platform_version in the stats line

        # the folder form of an install (Terrasoft.Configuration/Pkg): the same rows; a path with neither is one line
        folders = root / "pkg"
        (folders / "CrtBase" / "Resources" / "UsrBase.Entity").mkdir(parents=True)
        (folders / "CrtBase" / "Resources" / "UsrBase.Entity" / "resource.en-US.xml").write_text(
            _res_xml("en-US", {"Columns.UsrCode.Caption": "Code"}), encoding="utf-8-sig")
        assert list(platform.rows(folders, {"en-US"})) == [("CrtBase", "UsrBase", "Columns.UsrCode.Caption", "en-US", "Code")]
        (root / "project.json").write_text(json.dumps({"paths": {"platform": "nowhere"}}), encoding="utf-8")
        assert index_workspace(root / "packages").splitlines()[-1].startswith("platform: "), "a wrong path is one line"
    finally:
        _rm_tree(root)


class FakeSite:
    """The three statements of the --env pass, answered by their text; every statement is kept."""

    def __init__(self, workspace_uid: str):
        self.asked, self.uid = [], workspace_uid

    def sql(self, text):
        self.asked.append(text)
        if "information_schema.columns" in text:
            return [{"object": "UsrOrder", "column": c, "type": t, "length": n} for c, t, n in (
                ("Id", "uuid", ""), ("UsrName", "character varying", "250"), ("UsrStatusId", "uuid", ""), ("UsrRegionId", "uuid", ""),
                ("UsrLegacyCode", "character varying", "50"))] + [{"object": "UsrOrderStatus", "column": "Name", "type": "character varying", "length": "250"}]
        if "SysLocalizableValue" in text:
            return [{"object": "UsrOrder", "key": "Columns.UsrRegion.Caption", "package": "UsrOtherPkg", "replacing": "false", "depth": "0", "caption": "Region"},
                    {"object": "UsrOrderStatus", "key": "Columns.Name.Caption", "package": "UsrPkg2", "replacing": "true", "depth": "0", "caption": "Title"},
                    {"object": "UsrOrderStatus", "key": "Columns.Name.Caption", "package": "CrtBase", "replacing": "false", "depth": "1", "caption": "Name"}]
        return [{"name": "UsrRegion", "uid": "aaaaaaaa-0000-0000-0000-00000000000a", "manager": "EntitySchemaManager", "package": "UsrOtherPkg", "caption": "Region"},
                {"name": "UsrRegion_FormPage", "uid": "aaaaaaaa-0000-0000-0000-00000000000b", "manager": "ClientUnitSchemaManager", "package": "UsrOtherPkg",
                 "caption": ""},
                {"name": "UsrOrder", "uid": "AAAAAAAA-0000-0000-0000-00000000000C", "manager": "EntitySchemaManager", "package": "UsrPkg", "caption": "Order"},
                {"name": "UsrOrderStatus", "uid": self.uid, "manager": "EntitySchemaManager", "package": "UsrPkg", "caption": "Status"}]


def test_index_env_stores_the_site_columns_and_schemas_beyond_the_workspace():
    import json
    import tempfile
    import creatio_schemas.environment as environment
    from creatio_schemas.describe import site
    from creatio_schemas.describe.caption_search import resolve_caption

    root = Path(tempfile.mkdtemp())
    saved = environment.open_environment
    try:
        pkg = _captioned_page(root)
        status_uid = json.loads((pkg / "Schemas" / "UsrOrderStatus" / "descriptor.json").read_text(encoding="utf-8-sig"))["Descriptor"]["UId"]
        fake = FakeSite(status_uid)
        environment.open_environment = lambda name, project=None: fake
        objects = sorted(n for n in ("Account", "UsrOrder", "UsrOrderStatus", "UsrPkg") if (pkg / "Schemas" / n).is_dir())
        out = index_workspace(root / "packages", env="dev").splitlines()
        day = out[-3][len("site dev ("):][:10]
        missing = ", ".join(o for o in objects if o not in ("UsrOrder", "UsrOrderStatus"))
        assert out[-3] == f"site dev ({day}): 3 columns beyond the workspace in 2 objects, 1 package not found; no table on the site: {missing}", out
        assert out[-2] == f"site dev ({day}): 2 schemas beyond the workspace in 1 packages (prefixes Usr)", out
        uid = json.loads((pkg / "Schemas" / "UsrOrder" / "descriptor.json").read_text(encoding="utf-8-sig"))["Descriptor"]["UId"].lower()
        assert out[-1] == f"  UsrOrder on the site has UId aaaaaaaa-0000-0000-0000-00000000000c, the workspace {uid}", out
        cols, owners, schemas = fake.asked
        assert "table_name in (" in cols and "'UsrOrder'" in cols and "'PrimaryCulture'" in owners and "with recursive chain" in owners
        assert 's."Name" like \'Usr%\'' in schemas and "not s.\"ExtendParent\"" in schemas

        # the readers: columns (after the workspace's), map, describe_schema, find_schema, resolve
        lines = describe_item(pkg, "UsrOrder", "columns").splitlines()
        assert lines[-2:] == ["UsrLegacyCode  character varying(50)  site: package not found", "UsrRegion  'Region'  Lookup  site: UsrOtherPkg"], lines
        assert "site:" not in describe_item(pkg, "UsrOrder", "columns type=Lookup")  # a filtered list is the workspace's only
        assert describe_item(pkg, "UsrOrderStatus", "columns").splitlines()[-1] == "Name  'Title'  character varying(250)  site: CrtBase"  # the definer
        assert describe_item(pkg, "UsrOrder", "map").splitlines()[-1].startswith("site:")
        assert f"site (dev, {day}): 2 columns beyond the workspace, 1 package not found" in describe_schema(pkg, "UsrOrder", limit=0)
        if missing:
            assert f"site (dev, {day}): no table {missing.split(', ')[0]} on the site" in describe_schema(pkg, missing.split(", ")[0], limit=0)
        assert find_schema(root / "packages", "UsrRegion") == f"UsrRegion  object 'Region'  site: UsrOtherPkg (not in workspace)  (dev, {day})"
        assert "UsrRegion 'Region'  site dev: UsrOtherPkg (not in workspace)" in resolve_caption(root / "packages", "Region")
        assert "UsrRegion_FormPage  site dev" in resolve_caption(root / "packages", "UsrRegion_Form", kind="page")

        # a second pass replaces the env's rows; without --env nothing is read and the rows stay
        index_workspace(root / "packages", env="dev")
        db = pkg.parent.parent / ".creatio-index" / "index.sqlite"
        assert len(site.columns_of(db, "UsrOrder")) == 2 and len(fake.asked) == 6
        assert not any(l.startswith("site ") for l in index_workspace(root / "packages").splitlines()) and len(fake.asked) == 6
        assert len(site.columns_of(db, "UsrOrder")) == 2
        (root / "project.json").write_text(json.dumps({"prefixes": ["Usr"]}), encoding="utf-8")
        assert site.prefixes_of(root / "packages", []) == {"Usr"} and site.prefixes_of(root, ["usrOne", "usrTwo", "UsrX"]) == {"Usr"}
        (root / "project.json").unlink()
        assert site.prefixes_of(root, ["usrOne", "usrTwo", "UsrX", "Contact"]) == {"usr"}  # two names make a prefix; one does not
    finally:
        environment.open_environment = saved
        _rm_tree(root)


def test_precommit_stops_a_staged_column_or_object_the_site_already_has():
    import shutil
    import subprocess
    import tempfile
    from creatio_schemas import EntitySchema
    from creatio_schemas.describe import store
    from creatio_schemas.describe.index import index_path
    from creatio_schemas.describe.review import precommit

    root = Path(tempfile.mkdtemp())
    try:
        pkg = _repo(root, OBJECTS)
        (root / ".gitignore").write_text(".creatio-index/\n", encoding="utf-8")
        ent = EntitySchema(pkg, "UsrOrder")
        ent.add_column("UsrArea", "ShortText", "Area")
        ent.add_column("UsrLegacyCode", "ShortText", "Code")
        ent.save()
        EntitySchema.create(pkg, "UsrRegion", "Region").save()
        subprocess.run(["git", "add", "packages"], cwd=root, check=True)
        notes = []
        assert precommit(root, notes) == [] and notes == ["no site pass yet - run index --env <name>"]  # said, and going on
        con = store.connect(index_path(pkg))
        con.executemany("insert into site_columns values (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            ("dev", "2026-11-21T08:00:00Z", "UsrPkg", "UsrOrder", "UsrArea", "Lookup", "UsrOtherPkg", "Area", 0),
            ("dev", "2026-11-21T08:00:00Z", "UsrPkg", "UsrOrder", "UsrLegacyCode", "text", None, None, 0),
            ("dev", "2026-11-21T08:00:00Z", "UsrPkg", "UsrOrder", "UsrName", "text", "UsrOtherPkg", None, 0)])  # in HEAD already: not new
        con.execute("insert into site_schemas values ('dev', '2026-11-21T08:00:00Z', 'UsrRegion', 'u', 'object', 'UsrOtherPkg', 'Region')")
        con.commit()
        con.close()
        notes = []
        problems = precommit(root, notes)
        assert problems == [
            "packages/UsrPkg/Schemas/UsrOrder/metadata.json: UsrArea exists on the site (dev, 2026-11-21) in package UsrOtherPkg: reuse it "
            "(add that package to the workspace or reference the column)",
            "packages/UsrPkg/Schemas/UsrRegion/metadata.json: UsrRegion exists on the site (dev, 2026-11-21) as object in package UsrOtherPkg: "
            "reuse it (add that package to the workspace)"], problems  # no --force offered
        assert len(notes) == 1 and notes[0].startswith("warning: UsrLegacyCode exists on the site"), notes
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            assert main(["precommit", str(root)]) == 1
        assert "UsrArea exists on the site" in out.getvalue() and "warning: UsrLegacyCode" in err.getvalue()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_schema_diff_against_the_site_writes_its_copy_and_compares_in_schema_terms():
    import base64
    import shutil
    import tempfile
    from creatio_schemas import EntitySchema
    from creatio_schemas.describe.diff import _diff_site
    from creatio_schemas.resources import Resources

    root = Path(tempfile.mkdtemp())
    try:
        pkg = root / "UsrPkg"
        shutil.copytree(OBJECTS, pkg)
        meta = (pkg / "Schemas" / "UsrOrder" / "metadata.json").read_bytes()  # the site's copy: the fixture as pushed
        strings = Resources(pkg / "Resources" / "UsrOrder.Entity").cultures["en-US"]

        class Site:
            def __init__(self):
                self.asked = []

            def sql(self, text):
                self.asked.append(text)
                if '"SysLocalizableValue"' in text:
                    return [{"key": k, "culture": "en-US", "value": "Title" if k == "Columns.UsrName.Caption" else v} for k, v in strings.items()]
                if "'UsrNope'" in text:
                    return []
                return [{"id": "aaaaaaaa-0000-0000-0000-000000000001", "meta": base64.encodebytes(meta).decode(), "content": ""}]

        ent = EntitySchema(pkg, "UsrOrder")  # the working copy: a column the designer never saw
        ent.add_column("UsrNote", "ShortText", "Note")
        ent.save()
        site = Site()
        out = _diff_site(pkg, ["UsrOrder"], "env:dev", site).splitlines()
        assert out[0] == "UsrOrder  object" and "    + UsrNote ShortText 'Note'" in out, out
        assert any(l.startswith("    ~ UsrName ") and "'Title'" in l and "'Name'" in l for l in out), out  # the caption the site holds
        assert out[-1].startswith("UsrPkg against env:dev: 1 changed, 0 new, 0 removed"), out
        assert "s.\"Name\" = 'UsrOrder' and p.\"Name\" = 'UsrPkg'" in site.asked[0] and "encode(s.\"MetaData\", 'base64')" in site.asked[0]
        assert "l.\"SysSchemaId\" = 'aaaaaaaa-0000-0000-0000-000000000001'" in site.asked[1]
        for names, message in ((["UsrNope"], "UsrNope is not on the site in package UsrPkg"), (None, "name the schemas to compare with the site")):
            try:
                _diff_site(pkg, names, "env:dev", Site())
                raise AssertionError("no error")
            except QueryError as e:
                assert str(e).startswith(message), e
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_s20_inbox_rule_edges_page_paths_list_containers_and_the_stock_lookups():
    import json
    import shutil
    import tempfile
    from unittest.mock import patch
    from creatio_schemas.describe import lookups
    from creatio_schemas.describe.core import open_item
    from creatio_schemas.describe.deps import Resolver, _rules
    from creatio_schemas.diff import SchemaDiff
    from creatio_schemas.entity.catalog import STOCK_VERSION
    from creatio_schemas.rules.model import T_ATTR
    from creatio_schemas.workspace import Workspace

    # 1. a FilterLookup action's empty source (`"BRX1": "null"`) is no column; 2. a page attribute is a column only through its
    # `PDS.X` path, and `X` declared by the data source as `Lookup.Column` resolves to that path
    item = open_item(RULES, "UsrTests_FormPageBusinessRule")
    item.rules[0]["S20"] = [{"JI0": T_ATTR, "BRX1": "null", "BRX2": "null"}, {"JI0": T_ATTR, "BRX1": "UsrTabLabel", "BRX2": "PDS"},
                            {"JI0": T_ATTR, "BRX1": "UsrOwnerName", "BRX2": None}]
    ws = Workspace(RULES)
    attrs, sources, elements = ws.page_model(item.target)
    r = Resolver(ws)
    with patch.object(ws, "page_model", lambda name: ({**attrs, "UsrTabLabel": None, "UsrOwnerName": "PDS.UsrOwnerName"}, sources, elements)), \
            patch.object(ws, "data_source_paths", lambda name: {"PDS": {"UsrOwnerName": "UsrContactLookup.Name"}}), \
            patch.object(Resolver, "column_names", lambda self, entity, names: names):  # the extractor's own output, unfiltered
        cols = [d for e in _rules(item, r) if e.via == "column" for d in e.detail]
    assert "null" not in cols and "UsrTabLabel" not in cols and "UsrContactLookup.Name" in cols and "UsrIsActive" in cols, cols
    assert ws.data_source_paths(item.target) == {"AttachmentListDS": {"Name": "Name"}}  # the reader over the fixture page

    # 3. `D2.["<uid>"].E16` on a parent without D2 leaves a list, so the `~ D2` order line and a `+ D2` column apply (no AttributeError)
    diff = SchemaDiff('= MetaData.Schema.D2.["aaaaaaaa-0000-0000-0000-000000000001"].E16 true\r\n'
                      '+ MetaData.Schema.D2 {"UId": "aaaaaaaa-0000-0000-0000-000000000002", "A2": "UsrNote"}\r\n'
                      '~ MetaData.Schema.D2 ["aaaaaaaa-0000-0000-0000-000000000002"]\r\n'
                      '= MetaData.Schema.EG1 {"UId": "aaaaaaaa-0000-0000-0000-000000000003"}\r\n'
                      '~ MetaData.Schema.EG1 ["x"]\r\n')  # an order line over an object: unresolved, not an AttributeError
    schema = diff.apply({})
    assert schema["D2"] == [{"UId": "aaaaaaaa-0000-0000-0000-000000000002", "A2": "UsrNote"}], schema
    assert diff.unresolved == ['MetaData.Schema.D2.["aaaaaaaa-0000-0000-0000-000000000001"].E16', "MetaData.Schema.EG1"], diff.unresolved

    # 4. `lookups` reads the 8.3.2 stock list: a parent only that list knows makes a lookup
    assert STOCK_VERSION == "8.3.2"
    root = Path(tempfile.mkdtemp())
    try:
        pkg = root / "UsrPkg"
        shutil.copytree(OBJECTS, pkg)
        path = pkg / "Schemas" / "UsrOrder" / "descriptor.json"
        d = json.loads(path.read_text(encoding="utf-8-sig"))
        d["Descriptor"]["Parent"] = {"UId": "aaaaaaaa-0000-0000-0000-0000000000ad", "Name": "AdPlatform"}  # not in the 8.2.3 list
        path.write_text(json.dumps(d), encoding="utf-8")
        out = lookups(pkg)
        assert out.splitlines()[0].startswith("2 lookups in UsrPkg") and "parent AdPlatform -> BaseLookup" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_map_draws_the_page_as_a_captioned_tree_and_the_object_by_column_type():
    import tempfile

    root = Path(tempfile.mkdtemp())
    try:
        pkg = _captioned_page(root)
        tree = describe_item(pkg, "UsrOrder_FormPage", "map limit=0").splitlines()
        assert tree[0] == "UsrOrder_FormPage 'UsrOrder_FormPage' - 5 elements; tab= narrows, offset= continues", tree
        assert tree[1:] == ["Tabs (inherited, 5)",
                            "  UsrMainTab 'Main' TabContainer (4)",
                            "    UsrMainGrid GridContainer (2)",
                            "      UsrName 'Name' Input",
                            "      UsrStatus 'Status' ComboBox -> UsrOrderStatus",
                            "    UsrLines 'Lines' DataGrid"], tree
        # one tab, in another culture
        one = describe_item(pkg, "UsrOrder_FormPage", "map tab=UsrMainGrid culture=uk-UA").splitlines()
        assert one[0].endswith("- 3 elements under UsrMainGrid; tab= narrows, offset= continues") and one[2] == "  UsrName 'Nazva' Input", one
        # the cut and the next page
        first = describe_item(pkg, "UsrOrder_FormPage", "map limit=2").splitlines()
        assert len(first) == 3 and first[-1].startswith("  ... 5 more;"), first
        second = describe_item(pkg, "UsrOrder_FormPage", "map limit=2 offset=2").splitlines()
        assert second[0] == "  UsrMainTab 'Main' TabContainer (4)" and second[-1].startswith("  ... 3 more; next: offset=4"), second
        try:
            describe_item(pkg, "UsrOrder_FormPage", "map tab=UsrMainGrd")
            raise AssertionError("no error")
        except QueryError as e:
            assert "no element UsrMainGrd in UsrOrder_FormPage; closest: UsrMainGrid" in str(e), e
        # the object: columns by type with captions, a lookup with its target, a base column without a caption in the workspace
        obj = describe_item(pkg, "UsrOrder", "map").splitlines()
        assert obj[0] == "UsrOrder 'Order' - 11 columns (5 own)", obj
        groups = {line.split(":")[0]: line for line in obj[1:]}
        assert list(groups) == ["lookups", "text", "dates", "numbers", "other"], list(groups)
        assert "UsrStatus 'Status' -> UsrOrderStatus" in groups["lookups"] and "UsrContact 'Contact' -> Contact" in groups["lookups"]
        assert groups["text"].endswith("UsrName 'Name' (ShortText)") and "UsrDueDate 'Due date'" in groups["dates"]
        assert "UsrAmount 'Amount' (Money)" in groups["numbers"] and "CreatedOn (caption not in workspace)" in groups["dates"]
        assert describe_item(pkg, "UsrOrder", "map culture=uk-UA").splitlines()[2].endswith("UsrName 'Nazva' (ShortText)")
    finally:
        _rm_tree(root)


def test_resolve_finds_the_workspace_by_caption_ranked_by_kind_and_culture():
    import contextlib
    import io
    import shutil
    import tempfile
    from creatio_schemas.describe.caption_search import resolve_caption

    root = Path(tempfile.mkdtemp())
    try:
        pkg = _captioned_page(root)
        shutil.copytree(DATA / "Data" / "UsrStatus", pkg / "Data" / "UsrStatus")
        # the kinds: a column, a page element, a lookup value, an object, a page; the best match first, then the kind rank
        assert resolve_caption(root, "In progress").splitlines() == ["lookup    UsrOrderStatus 'In progress' = In progress  Data/UsrStatus  UsrPkg"]
        status = resolve_caption(root, "Status").splitlines()
        assert [l.split()[0] for l in status] == ["column", "element", "object"], status  # the exact caption twice, then 'Order status' (a whole word)
        assert status[0] == "column    UsrOrder.UsrStatus 'Status'  UsrPkg" and status[1] == "element   UsrOrder_FormPage.UsrStatus 'Status'  UsrPkg"
        order = resolve_caption(root, "order").splitlines()
        assert [l.split()[:2] for l in order][:2] == [["object", "UsrOrder"], ["object", "UsrOrderStatus"]] and order[2].startswith("page      UsrOrder_FormPage"), order
        # a Usr name resolves the same way; --kind narrows
        assert resolve_caption(root, "UsrStatus", kind="column").splitlines() == ["column    UsrOrder.UsrStatus 'Status'  UsrPkg"]
        assert resolve_caption(root, "UsrMainTab").splitlines()[0] == "element   UsrOrder_FormPage.UsrMainTab 'Main'  UsrPkg"
        assert resolve_caption(root, "lines", kind="element").splitlines() == ["element   UsrOrder_FormPage.UsrLines 'Lines'  UsrPkg"]
        # another culture: a key only uk-UA has is found with --culture, or all, and names its culture; the default culture does not see it
        assert resolve_caption(root, "nazva").startswith('no caption holds "nazva"')
        uk = resolve_caption(root, "nazva", culture="all").splitlines()
        assert uk == ["column    UsrOrder.UsrName 'Nazva' (uk-UA)  UsrPkg", "element   UsrOrder_FormPage.UsrName 'Nazva' (uk-UA)  UsrPkg"], uk
        assert resolve_caption(root, "nazva", culture="uk-UA").splitlines() == uk
        assert resolve_caption(root, "holovna", culture="all", kind="element").endswith("'Holovna' (uk-UA)  UsrPkg")
        # no hit: the closest captions
        assert resolve_caption(root, "Statu s") .startswith('no caption holds "Statu s"; closest:') and "'Status'" in resolve_caption(root, "Statu s")
        try:
            resolve_caption(root, "x", kind="nonsense")
            raise AssertionError("no error")
        except QueryError as e:
            assert "unknown kind nonsense" in str(e)
        # the list is cut and continued like every other
        assert len(resolve_caption(root, "Usr", limit=2).splitlines()) == 3 and "next: offset=" in resolve_caption(root, "Usr", limit=2, offset=2)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert main(["resolve", str(root), "In progress", "--kind", "lookup"]) == 0
        assert out.getvalue().startswith("lookup    UsrOrderStatus 'In progress'")
    finally:
        _rm_tree(root)


def test_about_gathers_what_touches_an_element():
    import json
    import shutil
    import tempfile
    from creatio_schemas.page import PageSchema
    from creatio_schemas.rules import RuleSchema

    root = Path(tempfile.mkdtemp())
    try:
        pkg = _captioned_page(root)
        shutil.copytree(DATA / "Data" / "UsrStatus", pkg / "Data" / "UsrStatus")
        page = PageSchema(pkg, "UsrOrder_FormPage")
        page.attributes_w()["UsrName"]["validators"] = {"usr.NameNotEmpty": {"type": "usr.NameNotEmpty"}}
        page.element("UsrStatus")["values"]["visible"] = "$UsrName | usr.HasValue"
        page.save()
        body_path = pkg / "Schemas" / "UsrOrder_FormPage" / "UsrOrder_FormPage.js"
        handler = ("[\n  {\n    request: \"usr.SaveOrder\",\n    handler: async (request, next) => {\n"
                   "      const name = await request.$context.UsrName;\n      request.$context.UsrName = name.trim();\n      return next?.handle(request);\n    }\n  }\n]")
        text = body_path.read_text(encoding="utf-8-sig").replace("/**SCHEMA_HANDLERS*/[]/**SCHEMA_HANDLERS*/", f"/**SCHEMA_HANDLERS*/{handler}/**SCHEMA_HANDLERS*/")
        body_path.write_text(text, encoding="utf-8-sig")
        action = [{"type": "required", "items": ["UsrStatus"]}]
        prules = RuleSchema.create(pkg, "UsrOrder_FormPage")
        prules.add({"caption": "Status required when the name is filled", "when": "UsrName is not null", "actions": action})
        prules.save()
        orules = RuleSchema.create(pkg, "UsrOrder")
        orules.add({"caption": "Status required for named orders", "when": "UsrName is not null", "actions": action})
        orules.add({"caption": "Amount defaults", "when": "UsrAmount is null", "actions": [{"type": "required", "items": ["UsrAmount"]}]})
        orules.save()
        (root / "project.json").write_text(json.dumps({"paths": {"testFramework": "framework"}}), encoding="utf-8")
        (root / "framework" / "Cases").mkdir(parents=True)
        (root / "framework" / "ProcessCases").mkdir()
        (root / "framework" / "Cases" / "order-form.act").write_text("# a case\nopen UsrOrder_FormPage new\nfill 'Status' with 'New'\n", encoding="utf-8")
        (root / "framework" / "ProcessCases" / "other.act").write_text("start UsrProc\ncheck-record UsrOrder UsrStatus=1 exists\n", encoding="utf-8")

        out = describe_item(pkg, "UsrOrder_FormPage", "about UsrStatus").splitlines()
        assert out[0].startswith("UsrStatus 'Status'  crt.ComboBox  control $UsrStatus -> attribute UsrStatus -> PDS UsrOrder.UsrStatus 'Status'"), out
        assert "  lookup target: UsrOrderStatus 'Order status' (UsrPkg, 3 values: New, In progress, Done)" in out, out
        assert any(l.startswith("  page rules (UsrOrder_FormPageBusinessRule): BusinessRule_") and "'Status required when the name is filled' (enabled)" in l for l in out), out
        obj = next(l for l in out if l.startswith("  object rules (UsrOrderBusinessRule): 1 of 2 - "))
        assert "'Status required for named orders'" in obj and "Amount defaults" not in obj and obj.endswith("`rule <name>` on UsrOrderBusinessRule reads one"), obj
        assert "  converters: usr.HasValue" in out
        assert "  test Cases/order-form.act:3  fill 'Status' with 'New'" in out and "  test ProcessCases/other.act:2  check-record UsrOrder UsrStatus=1 exists" in out, out
        name = describe_item(pkg, "UsrOrder_FormPage", "about UsrName").splitlines()
        assert "  handler usr.SaveOrder (reads line 4; writes line 5); `handler usr.SaveOrder around=UsrName` reads it" in name, name
        assert "  validators: usr.NameNotEmpty" in name
        # nothing touches a container
        assert describe_item(pkg, "UsrOrder_FormPage", "about UsrMainGrid").splitlines()[-1] == "  nothing touches UsrMainGrid beyond the page"
        # json: where plus the sections
        data = json.loads(describe_item(pkg, "UsrOrder_FormPage", "about UsrStatus format=json"))
        assert data["column"] == "UsrOrder.UsrStatus" and data["lookup_target"]["object"] == "UsrOrderStatus" and data["lookup_target"]["rows"] == 3
        assert data["page_rules"]["rules"][0]["enabled"] is True and data["object_rules"]["addon"] == "UsrOrderBusinessRule" and len(data["tests"]) == 2
        # the long sections are cut
        assert len(describe_item(pkg, "UsrOrder_FormPage", "about UsrStatus limit=3").splitlines()) == 4
    finally:
        _rm_tree(root)


def test_columns_lines_carry_the_caption_after_the_name():
    import tempfile
    from creatio_schemas.describe.diff import schema_diff

    root = Path(tempfile.mkdtemp())
    try:
        pkg = _captioned_page(root)
        lines = {l.split()[0]: l.split() for l in describe_item(pkg, "UsrOrder", "columns limit=0").splitlines()}
        assert lines["UsrName"][:3] == ["UsrName", "'Name'", "ShortText"], lines["UsrName"]
        assert lines["UsrStatus"][:5] == ["UsrStatus", "'Status'", "Lookup", "->", "UsrOrderStatus"]
        assert lines["CreatedOn"][:2] == ["CreatedOn", "DateTime"] and lines["CreatedOn"][-1] == "base"  # no caption in the workspace: nothing extra
        assert "'Name'" not in lines["UsrName"][3:]  # the caption does not also close the line
        uk = {l.split()[0]: l.split() for l in describe_item(pkg, "UsrOrder", "columns culture=uk-UA limit=0").splitlines()}
        assert uk["UsrName"][:3] == ["UsrName", "'Nazva'", "ShortText"] and uk["UsrAmount"][:2] == ["UsrAmount", "Money"]  # no uk-UA caption: nothing
        # `column <Name>` and `inspect` keep their line; `describe.py diff` keeps the lines it always compared
        assert describe_item(pkg, "UsrOrder", "column UsrName").splitlines()[0].split()[:2] == ["UsrName", "ShortText"]
    finally:
        _rm_tree(root)


def test_find_text_over_the_indexed_files():
    import shutil
    import tempfile
    from creatio_schemas.describe.index import find_text
    tmp = Path(tempfile.mkdtemp())
    pkg = tmp / "packages" / "UsrPkg"
    shutil.copytree(PAGES, pkg)
    try:
        js = pkg / "Schemas" / "UsrOrder_FormPage" / "UsrOrder_FormPage.js"
        js.write_text(js.read_text(encoding="utf-8").replace(
            "handlers: /**SCHEMA_HANDLERS*/[]/**SCHEMA_HANDLERS*/",
            'handlers: /**SCHEMA_HANDLERS*/[{request: "usr.ApproveOrderRequest", handler: async (request, next) => next?.handle(request)}]/**SCHEMA_HANDLERS*/'),
            encoding="utf-8")
        out = find_text(tmp, r"usr\.ApproveOrderRequest").splitlines()  # a handler name in a page
        assert out[0] == r"1 lines match /usr\.ApproveOrderRequest/ in 1 items", out[0]
        assert out[1].startswith("UsrPkg/UsrOrder_FormPage (page) 29: handlers: ") and "usr.ApproveOrderRequest" in out[1]
        col = find_text(tmp, '"A2": "UsrAmount"').splitlines()  # a column in an object
        assert col[1] == 'UsrPkg/UsrOrder (object) 56: "A2": "UsrAmount",', col
        assert find_text(pkg, '"A2": "UsrAmount"', kind="page").startswith("no line matches")  # the kind filter
        ctx = find_text(pkg, '"A2": "UsrAmount"', kind="object", context=1).splitlines()
        assert [l.split(") ", 1)[1][:3] for l in ctx[1:4]] == ["55-", "56:", "57-"] and len(ctx) == 7, ctx
        res = next((pkg / "Resources").rglob("resource.en-US.xml"))
        res.write_text(res.read_text(encoding="utf-8-sig").replace('Value="Order"', 'Value="UsrOnlyInResources"', 1), encoding="utf-8")
        assert find_text(pkg, "UsrOnlyInResources").startswith("no line matches")  # resource XML is skipped by default
        assert find_text(pkg, "UsrOnlyInResources", kind="resource").startswith("1 lines match")
        many = find_text(pkg, '"A2"', kind="object", limit=2).splitlines()
        assert len(many) == 4 and many[-1].startswith("  ... ") and many[-1].endswith("more; add limit=0 for all"), many
        anchored = find_text(pkg, r"^\s+handlers:", kind="page").splitlines()  # a line anchor survives the whole-file prefilter
        assert anchored[0].startswith("2 lines match") and anchored[2].endswith("handlers: /**SCHEMA_HANDLERS*/[]/**SCHEMA_HANDLERS*/,"), anchored
        try:
            find_text(pkg, "(")
            raise AssertionError("a bad regex must be refused")
        except QueryError as exc:
            assert "not a regex" in str(exc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_store_round_trips_and_replaces_the_json_index():
    import shutil
    import sqlite3
    import tempfile
    import threading
    from creatio_schemas.describe import store
    assert store.FTS5 and store.has_fts5(), sqlite3.sqlite_version  # the Windows Python ships SQLite with FTS5
    tmp = Path(tempfile.mkdtemp())
    try:
        for name, src in (("UsrPkg", PAGES), ("UsrProc", PROCS)):
            shutil.copytree(src, tmp / "packages" / name)
        root = tmp / ".creatio-index"
        root.mkdir()
        (root / "UsrPkg.json").write_text('{"format": 1}', encoding="utf-8")  # an index from before S26
        idx = PackageIndex(tmp / "packages" / "UsrPkg")
        assert not (root / "UsrPkg.json").exists() and idx.path == root / "index.sqlite"
        idx.refresh()
        assert store.load_package(idx.path, "UsrPkg") == idx.data  # the same dict back
        again = PackageIndex(tmp / "packages" / "UsrPkg")
        assert again.data == idx.data and again.refresh() == {"added": [], "changed": [], "removed": []}
        con = sqlite3.connect(idx.path)
        try:
            assert con.execute("select kind, caption from nodes where package = 'UsrPkg' and name = 'UsrOrder'").fetchone() == ("object", "Order")
            assert con.execute("select count(*) from files where package = 'UsrPkg' and node = 'UsrOrder'").fetchone()[0] == len(idx.schemas["UsrOrder"]["files"])
            assert con.execute("select count(*) from edges where package = 'UsrPkg' and node = 'UsrOrder_FormPage' and to_name = 'UsrOrder'").fetchone()[0] >= 1
            assert con.execute("select key from captions where captions match 'Amount' and node = 'UsrOrder'").fetchone() == ("UsrAmount",)
            assert con.execute("pragma journal_mode").fetchone() == ("wal",)
        finally:
            con.close()
        md = tmp / "packages" / "UsrPkg" / "Schemas" / "UsrOrder" / "metadata.json"  # a stale entry: only it is re-read
        md.write_text(md.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        assert PackageIndex(tmp / "packages" / "UsrPkg").refresh()["changed"] == ["UsrOrder"]
        errors = []  # two writers on one workspace, a thread each: both packages end in the store, whole
        def build(name):
            try:
                PackageIndex(tmp / "packages" / name).refresh(rebuild=True)
            except Exception as exc:  # noqa: BLE001 - the test reports any failure of a writer
                errors.append(exc)
        threads = [threading.Thread(target=build, args=(n,)) for n in ("UsrPkg", "UsrProc", "UsrPkg", "UsrProc")]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert not errors, errors
        for name in ("UsrPkg", "UsrProc"):
            fresh = PackageIndex(tmp / "packages" / name)
            assert fresh.data["schemas"] and fresh.refresh() == {"added": [], "changed": [], "removed": []}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_workspace_lookups_read_the_store_after_a_refresh():
    import json
    import os
    import shutil
    import stat
    import sqlite3
    import tempfile
    from creatio_schemas.describe import store
    from creatio_schemas.describe.deps import dependencies
    from creatio_schemas.describe.index import find_schema, index_path
    tmp = Path(tempfile.mkdtemp())
    try:
        pkg = tmp / "packages" / "UsrPkg"
        shutil.copytree(PAGES, pkg)
        assert find_schema(tmp, "UsrOrder2").startswith("no schema named UsrOrder2")
        uid = json.loads((pkg / "Schemas" / "UsrOrder" / "descriptor.json").read_text(encoding="utf-8-sig"))["Descriptor"]["UId"].lower()
        con = sqlite3.connect(index_path(pkg))
        try:  # every entry carries its uid, the store's column with it
            assert con.execute("select uid from nodes where name = 'UsrOrder'").fetchone() == (uid,)
            assert con.execute("select count(*) from refs where to_name = 'UsrOrder'").fetchone()[0] >= 1
        finally:
            con.close()
        # a schema appears on disk: the same call refreshes the package, then its statements see the new rows
        shutil.copytree(pkg / "Schemas" / "UsrOrder", pkg / "Schemas" / "UsrOrder2")
        assert find_schema(tmp, "UsrOrder2").startswith(f"UsrOrder2  object in UsrPkg  ({pkg})")
        assert dependencies(tmp, "UsrOrder2", "in").startswith("UsrOrder2  object in UsrPkg")
        assert store.load_package(index_path(pkg), "UsrPkg")["schemas"]["UsrOrder2"]["kind"] == "object"
        # a store that refuses writes (a read-only checkout): the lookups answer from the fresh disk data, first line says so
        shutil.copytree(pkg / "Schemas" / "UsrOrder", pkg / "Schemas" / "UsrOrder3")
        os.chmod(index_path(pkg), stat.S_IREAD)
        try:
            out = find_schema(tmp, "UsrOrder3").splitlines()
            assert out[0].startswith("(index stale: built from disk - the store cannot be written here: "), out
            assert out[1].startswith(f"UsrOrder3  object in UsrPkg  ({pkg})"), out
            assert dependencies(tmp, "UsrOrder3", "in").splitlines()[1].startswith("UsrOrder3  object in UsrPkg")
            assert "UsrOrder3" not in store.load_package(index_path(pkg), "UsrPkg")["schemas"]
        finally:
            os.chmod(index_path(pkg), stat.S_IREAD | stat.S_IWRITE)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_freshness_walk_loads_no_up_to_date_package_and_sees_every_change():
    import shutil
    import sqlite3
    import tempfile
    from unittest.mock import patch
    from creatio_schemas.describe import store
    from creatio_schemas.describe.index import PackageIndex, find_schema, index_path
    tmp = Path(tempfile.mkdtemp())
    try:
        pkg = tmp / "packages" / "UsrPkg"
        shutil.copytree(PAGES, pkg)
        (pkg / "Data" / "UsrEmpty").mkdir(parents=True)  # a binding folder without files is up to date too

        def rows():
            con = sqlite3.connect(index_path(pkg))
            try:
                return con.execute("select node, path, size, mtime from files order by node, path").fetchall()
            finally:
                con.close()

        assert PackageIndex(pkg).refresh()["added"]
        before = rows()
        assert any(p.startswith("Resources/UsrOrder.Entity/") for n, p, _, _ in before if n == "UsrOrder")  # its resources count
        real, loads = store.load_package, []
        with patch.object(store, "load_package", side_effect=lambda *a: loads.append(a) or real(*a)):
            assert not any(PackageIndex(pkg).refresh().values())
            assert find_schema(tmp, "UsrOrder").startswith("UsrOrder  object in UsrPkg")
            assert loads == [], loads  # nothing changed: the entries stay in the store
            resource = next((pkg / "Resources" / "UsrOrder.Entity").glob("*.xml"))
            resource.write_bytes(resource.read_bytes() + b"\n")  # a changed resource file is its item's change
            shutil.copytree(pkg / "Schemas" / "UsrOrderStatus", pkg / "Schemas" / "UsrOrderStatus2")
            shutil.rmtree(pkg / "Schemas" / "UsrTests_FormPage")
            changes = PackageIndex(pkg).refresh()
            assert changes == {"added": ["UsrOrderStatus2"], "changed": ["UsrOrder"], "removed": ["UsrTests_FormPage"]}, changes
            assert len(loads) == 1
        after = rows()
        assert not any(n == "UsrTests_FormPage" for n, *_ in after) and any(n == "UsrOrderStatus2" for n, *_ in after)
        PackageIndex(pkg).refresh(rebuild=True)
        assert rows() == after  # a rebuild writes the same rows the walk compared against
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_index_stats_a_corrupt_store_and_the_site_tables():
    import shutil
    import sqlite3
    import tempfile
    from unittest.mock import patch
    from creatio_schemas.describe import store
    from creatio_schemas.describe.index import find_schema, index_path, index_workspace
    tmp = Path(tempfile.mkdtemp())
    try:
        for name in ("UsrPkg", "UsrPkg2"):
            shutil.copytree(PAGES, tmp / "packages" / name)
        path = index_path(tmp / "packages" / "UsrPkg")
        out = index_workspace(tmp, stats=True).splitlines()
        assert out[0].startswith("UsrPkg: ") and "added" in out[0], out
        stats = [line for line in out if line.startswith(f"{path}: ")]
        assert len(stats) == 1 and f"format {store.STORE_FORMAT}, FTS5 " in stats[0], out
        rows = next(line for line in out if line.startswith("  rows: "))
        assert "packages 2, nodes " in rows and "platform_captions 0, site_columns 0, site_schemas 0" in rows, rows
        assert any(line.startswith("  UsrPkg2: built ") for line in out)
        # one reader for a whole call over an up-to-date workspace, not one open per package and read
        real, opens = store.connect, []
        with patch.object(store, "connect", side_effect=lambda *a, **k: opens.append(k.get("write", True)) or real(*a, **k)):
            assert find_schema(tmp, "UsrOrder").startswith("UsrOrder  object in UsrPkg")
        assert opens == [False], opens
        # the three S31 tables: one row each in and out
        con = store.connect(path)
        try:
            con.execute("insert into platform_captions values ('CrtBase', 'Contact', 'Columns.Name', 'en-US', 'Full name')")
            con.execute("insert or replace into meta values ('platform_version', '8.3.2.4199')")
            con.execute("insert into site_columns values ('dev', '2026-11-21T00:00:00', 'UsrPkg', 'UsrOrder', 'UsrRegion', "
                        "'Lookup', 'UsrOther', 'Region', 0)")
            con.execute("insert into site_schemas values ('dev', '2026-11-21T00:00:00', 'UsrGone', 'u1', 'object', 'UsrOther', 'Gone')")
            con.commit()
            assert con.execute("select text from platform_captions where schema = 'contact' collate nocase").fetchone() == ("Full name",)
            assert con.execute("select package, missing from site_columns where env = 'dev' and object = 'usrorder' collate nocase").fetchone() == ("UsrOther", 0)
            assert con.execute("select uid from site_schemas where env = 'dev' and name = 'UsrGone'").fetchone() == ("u1",)
        finally:
            con.close()
        assert "platform 8.3.2.4199" in store.stats(path)[0] and "site_schemas 1" in store.stats(path)[1]
        # a corrupt file: one line, rebuilt from disk, nothing else tried
        path.write_bytes(b"not a database" * 100)
        for wal in path.parent.glob(path.name + "-*"):
            wal.unlink()
        out = index_workspace(tmp).splitlines()
        assert out[0] == f"{path}: not a store this toolkit reads (file is not a database); rebuilt from disk", out
        assert sum("not a store" in line for line in out) == 1 and "added" in out[1]
        assert find_schema(tmp, "UsrOrder").startswith("UsrOrder  object in UsrPkg")
        # an older format: one line, every package rebuilt
        con = sqlite3.connect(path)
        con.execute("update meta set value = '3' where key = 'format'")
        con.commit()
        con.close()
        assert index_workspace(tmp).splitlines()[0] == f"{path}: store format 3, this toolkit writes {store.STORE_FORMAT}; every package rebuilt"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _writes_workspace(root: Path) -> Path:
    """UsrPkg: the objects fixture + a process (an escaped script, a flow condition, a Modify data that writes UsrStatus, a Read data
    filtered by a lookup row), the lookup rows with captions, a C# listener, a page handler, a SQL script, a message publisher and subscriber."""
    import json
    import shutil
    from creatio_schemas import ProcessSchema

    pkg = root / "packages" / "UsrPkg"
    shutil.copytree(OBJECTS, pkg)
    done = "5a3b1c2d-1111-4222-8333-444455556666"
    binding = pkg / "Data" / "UsrStatus"
    binding.mkdir(parents=True)
    (binding / "descriptor.json").write_text(json.dumps({"Descriptor": {"Schema": {"Name": "UsrOrderStatus"}, "Columns": [
        {"ColumnName": "Id", "ColumnUId": "usr-id", "IsKey": True}, {"ColumnName": "Name", "ColumnUId": "usr-name"}]}}), encoding="utf-8")
    (binding / "data.json").write_text(json.dumps({"PackageData": [{"Row": [{"SchemaColumnUId": "usr-id", "Value": done},
                                                                            {"SchemaColumnUId": "usr-name", "Value": "Done"}]}]}), encoding="utf-8")
    p = ProcessSchema.create(pkg, "UsrNotify_Process", "Notify", ["en-US"])
    p.add_param("Counter", "Integer", "Variable", "Counter", 1)
    p.add_element("script", "MarkDone", "Mark done", after="StartEvent1", before="TerminateEvent1")
    p.set_script("MarkDone", 'var q = new Update(UserConnection, "UsrOrder").Set("UsrStatus", Column.Parameter(Guid.Empty));\r\nvar text = "a \\"quoted\\" word";')
    p.add_element("exclusiveGateway", "Check", after="MarkDone", before="TerminateEvent1")
    p.add_element("formula", "Big", "big", after="Check", before="TerminateEvent1")
    p.set_formula("Big", "{Parameter:Counter} + 1", "Counter")
    p.set_condition("SequenceFlow3", "{Parameter:Counter} > 10")
    read = p.add_element("readData", "ReadOrders", "Read orders", after="StartEvent1", before="MarkDone")
    p.set_entity(read, "UsrOrder")
    p.set_filter(read, f"UsrStatus = {done}")
    change = p.add_element("changeData", "SetStatus", "Set status", after="MarkDone", before="Check")
    p.set_entity(change, "UsrOrder")
    p.set_record_values(change, {"UsrAmount": "5"})
    p.save()
    cs = pkg / "Files" / "cs"
    cs.mkdir(parents=True)
    (cs / "UsrOrderListener.cs").write_text('class UsrOrderListener { void OnSaved(Entity UsrOrder) { UsrOrder.SetColumnValue("UsrStatus", 1); }\n'
                                            'void Notify() { MsgChannelUtilities.PostMessageToAll("UsrOrderChanged", "{}"); } }\n', encoding="utf-8")
    page = pkg / "Schemas" / "UsrOrder_FormPage"
    page.mkdir(parents=True)
    (page / "UsrOrder_FormPage.js").write_text('define("UsrOrder_FormPage", [], function() { return { handlers: [{ request: "x", handler: async (request) => {\n'
                                              '  request.$context.UsrStatus = null;\n  Terrasoft.ServerChannel.on("UsrOrderChanged", (msg) => { if (msg.Header.Sender === "UsrOrderChanged") {} });\n} }] }; });\n',
                                              encoding="utf-8")
    sql = pkg / "SqlScripts"
    sql.mkdir()
    (sql / "UsrFix.sql").write_text('update "UsrOrder" set "UsrStatus" = null where "UsrAmount" = 0;\n', encoding="utf-8")
    return root


def test_find_in_processes_reads_scripts_conditions_filters_and_values():
    import tempfile
    from creatio_schemas.describe.writes import find_in_processes

    root = Path(tempfile.mkdtemp())
    try:
        ws = _writes_workspace(root)
        out = find_in_processes(ws, r'quoted|\bUpdate\(')
        assert "UsrPkg / UsrNotify_Process / MarkDone [Script" in out and "script line 1" in out and "script line 2" in out, out
        assert "condition" in find_in_processes(ws, "> 10"), find_in_processes(ws, "Counter")
        flt = find_in_processes(ws, "UsrStatus =")
        assert "ReadOrders [ReadDataUserTask] / filter: UsrOrder where UsrStatus = Done" in flt, flt
        # proc.py filter: a caption is written as the row Id with the caption as displayValue; a GUID gets its caption too; an unknown caption is an error
        import json as _json
        from creatio_schemas import ProcessSchema
        ps = ProcessSchema(ws / "packages" / "UsrPkg", "UsrNotify_Process")
        ps.set_filter(ps.element("ReadOrders"), "UsrStatus = Done")
        raw = _json.loads(_json.loads(ps.element_param(ps.element("ReadOrders"), "DataSourceFilters")["L8"]["GS2"])["dataSourceFilters"])
        value = next(iter(raw["items"].values()))["rightExpression"]["parameter"]["value"]
        assert value == {"value": "5a3b1c2d-1111-4222-8333-444455556666", "displayValue": "Done"}
        edit = _json.loads(_json.loads(ps.element_param(ps.element("ReadOrders"), "DataSourceFilters")["L8"]["GS2"])["serializedFilterEditData"])
        assert next(iter(edit["items"].values()))["rightExpression"]["parameter"]["value"] == {"value": "5a3b1c2d-1111-4222-8333-444455556666", "displayValue": "Done"}
        try:
            ps.set_filter(ps.element("ReadOrders"), "UsrStatus = Nonexistent")
            raise AssertionError("an unknown caption must be refused")
        except KeyError as e:
            assert "no row 'Nonexistent'" in str(e)
        assert "set value: UsrAmount = 5" in find_in_processes(ws, "UsrAmount")
        assert find_in_processes(ws, "no such text anywhere").startswith("no process text matches")
        assert find_in_processes(ws, "(")  # not a regex: searched as text, no error
    finally:
        _rm_tree(root)


def test_find_in_processes_reads_the_lookup_rows_once_per_workspace():
    """1564 processes x 0.8 s: `setdefault(key, lookup_rows())` read the bindings for every process; the cache is checked first now."""
    import shutil
    import tempfile
    from creatio_schemas.describe.writes import find_in_processes
    from creatio_schemas.workspace import Workspace

    root = Path(tempfile.mkdtemp())
    try:
        ws = _writes_workspace(root)
        src = ws / "packages" / "UsrPkg" / "Schemas" / "UsrNotify_Process"
        shutil.copytree(src, src.parent / "UsrNotify2_Process")  # a second process in the same workspace
        calls = []  # the reads of the bindings, not the cache hits
        original = Workspace.lookup_rows
        Workspace.lookup_rows = lambda self: (calls.append(1) if getattr(self, "_rows", None) is None else None) or original(self)
        try:
            out = find_in_processes(ws, "UsrStatus =")
        finally:
            Workspace.lookup_rows = original
        assert out.count("filter: UsrOrder where UsrStatus = Done") == 2, out
        assert len(calls) == 1, calls
    finally:
        _rm_tree(root)


def test_lookup_captions_are_built_once_until_the_rows_are_replaced():
    import tempfile
    from creatio_schemas.workspace import Workspace

    root = Path(tempfile.mkdtemp())
    try:
        ws = Workspace(_writes_workspace(root) / "packages" / "UsrPkg")
        first = ws.lookup_captions()
        assert first and ws.lookup_captions() is first  # one build for two calls
        ws._rows = {}  # what `proc.py find` does while matching: the cache follows
        assert ws.lookup_captions() == {}
    finally:
        _rm_tree(root)


def test_who_sets_opens_no_resource_file_and_reads_the_bindings_only_for_a_caption():
    """Four packages, 29 s: the resources of every process (every culture), the bindings of every package and the columns of every
    written entity were read before a single hit. Now a search with no hit opens none of them; a hit reads the bindings once."""
    import tempfile
    from creatio_schemas import schema as schema_module
    from creatio_schemas.describe.writes import who_sets
    from creatio_schemas.workspace import Workspace

    root = Path(tempfile.mkdtemp())
    try:
        ws = _writes_workspace(root)
        reads, resources = [], []
        original_rows, original_res = Workspace.lookup_rows, schema_module.Resources.__init__
        Workspace.lookup_rows = lambda self: (reads.append(1) if getattr(self, "_rows", None) is None else None) or original_rows(self)
        schema_module.Resources.__init__ = lambda self, folder: resources.append(folder) or original_res(self, folder)
        try:
            assert "nothing sets Account.Name" in who_sets(ws, "Account.Name")
            assert (reads, resources) == ([], []), (reads, resources)
            assert who_sets(ws, "UsrOrder.UsrAmount").startswith("process  UsrPkg / UsrNotify_Process / SetStatus")
            assert (len(reads), resources) == (1, []), (reads, resources)
        finally:
            Workspace.lookup_rows, schema_module.Resources.__init__ = original_rows, original_res
    finally:
        _rm_tree(root)


def test_who_sets_and_who_reads_message_answer_across_kinds():
    import tempfile
    from creatio_schemas.describe.writes import who_reads_message, who_sets

    root = Path(tempfile.mkdtemp())
    try:
        ws = _writes_workspace(root)
        out = who_sets(ws, "UsrOrder.UsrStatus")
        kinds = {line.split()[0] for line in out.splitlines()}
        assert kinds == {"script", "C#", "client", "sql"}, out
        assert "Files/cs/UsrOrderListener.cs:1" in out and "UsrOrder_FormPage.js:2" in out and "UsrFix.sql:1" in out
        assert who_sets(ws, "UsrOrder.UsrAmount").startswith("process  UsrPkg / UsrNotify_Process / SetStatus"), who_sets(ws, "UsrOrder.UsrAmount")
        assert "nothing sets UsrOrder.UsrName = x" in who_sets(ws, "UsrOrder.UsrName = x")
        msg = who_reads_message(ws, "UsrOrderChanged")
        assert [line.split()[0] for line in msg.splitlines()] == ["publish", "subscribe"], msg
        assert who_reads_message(ws, "Nobody").startswith("no publisher")
        for bad in ("UsrOrder", ""):
            try:
                who_sets(ws, bad)
                raise AssertionError("a bad target must be refused")
            except QueryError:
                pass
    finally:
        _rm_tree(root)


def test_describe_package_says_so_when_the_store_cannot_be_written():
    import shutil
    import sqlite3
    import tempfile
    from creatio_schemas.describe import index as index_module

    root = Path(tempfile.mkdtemp())
    real = index_module.store.save_package
    try:
        pkg = root / "packages" / "UsrPkg"
        shutil.copytree(OBJECTS, pkg)

        def read_only(*args, **kwargs):
            raise sqlite3.OperationalError("attempt to write a readonly database")

        index_module.store.save_package = read_only
        out = describe_package(pkg)
        assert out.splitlines()[0].startswith("(index stale: built from disk") and "UsrOrder" in out, out
    finally:
        index_module.store.save_package = real
        _rm_tree(root)


class _SiteRows:
    """A site's `Environment.sql`: the rows of the first needle (longest first) the statement contains; every statement is kept."""

    def __init__(self, answers):
        self.answers, self.statements = answers, []

    def sql(self, text, counts=None):
        self.statements.append(text)
        for needle in sorted(self.answers, key=len, reverse=True):
            if needle in text:
                answer = self.answers[needle]
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return []


def test_describe_schema_env_names_the_lookup_rows_only_the_site_holds():
    import json
    import tempfile
    from unittest.mock import patch
    from creatio_schemas import ProcessSchema, environment
    from creatio_schemas.describe import describe_item, describe_schema

    done, cancelled, ghost = "5a3b1c2d-1111-4222-8333-444455556666", "0042909f-aaaa-4bbb-8ccc-ddddeeeeffff", "99999999-aaaa-4bbb-8ccc-000000000000"
    root = Path(tempfile.mkdtemp())
    try:
        pkg = _writes_workspace(root) / "packages" / "UsrPkg"
        ps = ProcessSchema(pkg, "UsrNotify_Process")
        ps.workspace.lookup_value = lambda schema, text: (text, text)  # a filter the designer wrote with the bare Id: no caption was stored
        second = ps.add_element("readData", "ReadSite", "Read site rows", after="StartEvent1", before="ReadOrders")
        ps.set_entity(second, "UsrOrder")
        ps.set_filter(second, f"UsrStatus = {cancelled}")
        third = ps.add_element("readData", "ReadGhost", "Read ghost", after="StartEvent1", before="ReadSite")
        ps.set_entity(third, "UsrOrder")
        ps.set_filter(third, f"UsrStatus = {ghost}")
        change = ps.element("SetStatus")
        ps.set_record_values(change, {"UsrAmount": "5", "UsrStatus": cancelled})
        ps.save()
        before = describe_schema(pkg, "UsrNotify_Process", 0)
        plain_item = describe_item(pkg, "UsrNotify_Process", "element ReadSite")
        assert "filter: UsrOrder where UsrStatus = Done\n" in before and f"filter: UsrOrder where UsrStatus = {cancelled}\n" in before, before  # the bare Id: no caption stored
        assert f"values: UsrAmount = 5, UsrStatus = {cancelled}\n" in before, before
        site = _SiteRows({'from "UsrOrderStatus" where "Id" in': [{"Id": cancelled.upper(), "Name": "Cancelled"}]})
        with patch.object(environment, "open_environment", lambda name, project=None, **kw: site):
            after = describe_schema(pkg, "UsrNotify_Process", 0, 0, "dev")
            # the site names the row of a filter and of a set value; the binding's row keeps its caption; a row the site does not know stays bare
            assert f"filter: UsrOrder where UsrStatus = Cancelled ({cancelled})\n" in after and f"values: UsrAmount = 5, UsrStatus = Cancelled ({cancelled})\n" in after, after
            assert "filter: UsrOrder where UsrStatus = Done\n" in after and f"UsrStatus = {ghost}\n" in after and f"Cancelled ({ghost})" not in after, after
            # one read-only select per lookup table, with only the Ids the bindings do not know
            selects = [s for s in site.statements]
            assert len(selects) == 1 and selects[0].startswith('select "Id", "Name" from "UsrOrderStatus" where "Id" in (') and done not in selects[0], selects
            assert cancelled in selects[0] and ghost in selects[0] and all(s.lstrip().lower().startswith("select") for s in selects)
            # no env=: byte-identical to before; describe_item takes env= inside its query
            assert describe_schema(pkg, "UsrNotify_Process", 0) == before and describe_schema(pkg, "UsrNotify_Process", 0, 0, None) == before
            item = describe_item(pkg, "UsrNotify_Process", "element ReadSite env=dev")
            assert f"    filter: UsrOrder where UsrStatus = Cancelled ({cancelled})" in item and item.startswith(plain_item.splitlines()[0]), item
            assert "values: UsrAmount = 5, UsrStatus = Cancelled" in describe_item(pkg, "UsrNotify_Process", "element SetStatus env=dev")
            assert describe_item(pkg, "UsrNotify_Process", "element ReadSite") == plain_item and "filter:" not in plain_item
        # a site that cannot answer: the bare Id stays and one note line says why, so a bare Id is not mistaken for an unknown row
        broken = _SiteRows({'from "UsrOrderStatus"': RuntimeError("sql: 42P01: no such table")})
        with patch.object(environment, "open_environment", lambda name, project=None, **kw: broken):
            out = describe_schema(pkg, "UsrNotify_Process", 0, 0, "dev")
            assert out.splitlines()[1] == "(site names not read: UsrOrderStatus: sql: 42P01: no such table)" and f"UsrStatus = {cancelled}" in out, out
        # an environment that does not exist is an error naming it
        def missing(name, project=None, **kw):
            raise KeyError("environment 'nope' is not registered in clio")
        with patch.object(environment, "open_environment", missing):
            try:
                describe_schema(pkg, "UsrNotify_Process", 0, 0, "nope")
                raise AssertionError("an unknown environment must be refused")
            except ValueError as e:
                assert str(e).startswith("env nope: ") and "not registered" in str(e)
        # other kinds ignore env=
        assert describe_schema(OBJECTS, "UsrOrder", 0, 0, "dev") == describe_schema(OBJECTS, "UsrOrder", 0)
    finally:
        _rm_tree(root)


def test_merge_up_collapses_into_the_top_package_and_stops_on_a_reference_from_below():
    """S27-T09: A < B < C, merged up into C: every column once in C, the lower layers deleted, no dependency gained; a file in a
    package below the top naming a lower layer's column stops it; two tops stop; a wrong target is named."""
    import shutil
    import tempfile
    from creatio_schemas.describe.merge import merge_object, merge_plan
    from creatio_schemas.workspace import parse_diff

    root = Path(tempfile.mkdtemp())
    try:
        _layer_workspace(root, {"UsrA": (["CrtBase"], {}), "UsrB": (["UsrA"], {}), "UsrC": (["UsrB"], {})})
        pk = root / "packages"
        for i, (name, cols) in enumerate({"UsrA": ["UsrA1"], "UsrB": ["UsrB1"], "UsrC": ["UsrC1"]}.items()):
            _object_layer(pk / name, "Contact", [(c, f"c{i}{j}000000-0000-4000-8000-000000000000", SHORT_TEXT) for j, c in enumerate(cols)])
        deps_before = {n: (pk / n / "descriptor.json").read_bytes() for n in ("UsrA", "UsrB", "UsrC")}
        text, conflicts = merge_plan(root, ["Contact"])
        assert text.splitlines()[0] == "Contact object: 3 layers, target UsrC" and "  depends: unchanged" in text and not conflicts, text
        text, code = merge_object(root, "Contact", apply=True)
        assert code == 0 and text.endswith("merged Contact into UsrC: 3 layers -> 1"), text
        assert "delete packages/UsrA/Schemas/Contact" in text and "delete packages/UsrB/Schemas/Contact" in text and "gains" not in text
        assert not (pk / "UsrA" / "Schemas" / "Contact").exists() and not (pk / "UsrB" / "Schemas" / "Contact").exists()
        written = (pk / "UsrC" / "Schemas" / "Contact" / "metadata.json").read_text(encoding="utf-8")
        names = [__import__("json").loads(v)["A2"] for op, pth, v in parse_diff(written) if pth == "MetaData.Schema.D2" and op == "+"]
        assert names == ["UsrA1", "UsrB1", "UsrC1"], names  # every column once, in fold order
        assert '= MetaData.Schema.B6 "pkg-UsrC"' in written
        assert {n: (pk / n / "descriptor.json").read_bytes() for n in deps_before} == deps_before  # no DependsOn touched
    finally:
        shutil.rmtree(root, ignore_errors=True)

    root = Path(tempfile.mkdtemp())
    try:  # a page in A names B's column: after the merge that column lives in C, out of A's reach
        _layer_workspace(root, {"UsrA": (["CrtBase"], {}), "UsrB": (["UsrA"], {}), "UsrC": (["UsrB"], {})})
        pk = root / "packages"
        for i, name in enumerate(("UsrA", "UsrB", "UsrC")):
            _object_layer(pk / name, "Contact", [(f"{name}1", f"c{i}0000000-0000-4000-8000-000000000000", SHORT_TEXT)])
        page = pk / "UsrA" / "Schemas" / "UsrA_FormPage"
        page.mkdir(parents=True)
        (page / "UsrA_FormPage.js").write_text('define("UsrA_FormPage", [], function() { return {"control": "$PDS_UsrB1"}; });\n', encoding="utf-8")
        (pk / "UsrA" / "Files" / "cs").mkdir(parents=True)
        (pk / "UsrA" / "Files" / "cs" / "UsrHelper.cs").write_text('class UsrHelper { string c = "UsrB1Id"; string d = "UsrB10"; }\n', encoding="utf-8")
        text, conflicts = merge_plan(root, ["Contact"])
        lines = [l.strip() for l in text.splitlines() if "reference from below" in l]
        assert lines == ["conflict reference from below: UsrA/Files/cs/UsrHelper.cs uses Contact.UsrB1 (added by UsrB's layer)"], text
        assert conflicts == 1  # the page names `$PDS_UsrB1`, not the column word itself; `UsrB10` is another word
        (page / "UsrA_FormPage.js").write_text('define("UsrA_FormPage", [], function() { return {"path": "PDS.UsrB1"}; });\n', encoding="utf-8")
        text, code = merge_object(root, "Contact", apply=True)
        assert code == 1 and "conflict reference from below: UsrA/Schemas/UsrA_FormPage/UsrA_FormPage.js uses Contact.UsrB1" in text, text
        assert (pk / "UsrB" / "Schemas" / "Contact").exists()  # nothing written
        assert merge_object(root, "Contact", direction="down")[1] == 0  # downward the column stays below every reader: no such stop
        # a wrong target is named; the downward check of the same target is the other way round
        text, code = merge_object(root, "Contact", target="UsrB")
        assert code == 1 and "target UsrB is not above every layer: UsrC" in text, text
    finally:
        shutil.rmtree(root, ignore_errors=True)

    root = Path(tempfile.mkdtemp())
    try:  # two tops: B and C both stand on A, neither depends on the other
        _layer_workspace(root, {"UsrA": (["CrtBase"], {}), "UsrB": (["UsrA"], {}), "UsrC": (["UsrA"], {})})
        pk = root / "packages"
        for i, name in enumerate(("UsrA", "UsrB", "UsrC")):
            _object_layer(pk / name, "Contact", [(f"{name}1", f"c{i}0000000-0000-4000-8000-000000000000", SHORT_TEXT)])
        text, conflicts = merge_plan(root, ["Contact"])
        assert text.splitlines()[0] == "Contact object: 3 layers, no single top package: UsrB, UsrC", text
        assert text.splitlines()[-1].endswith("1 without a single top package"), text
        text, code = merge_object(root, "Contact")
        assert code == 1 and "no target; name one with --target" in text
        try:
            merge_plan(root, ["Contact"], direction="sideways")
        except ValueError as e:
            assert "up or down" in str(e)
        else:
            raise AssertionError("an unknown direction")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_commented_block_in_a_page_and_a_binding_without_rows_do_not_break_the_index():
    """A commented-out element block is valid JS the designer keeps; `PackageData: null` or no data.json is a binding without rows;
    a broken binding is one `error` entry and one `errors.log` line, never a crash of the build."""
    import json
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    try:
        pkg = tmp / "packages" / "UsrPkg"
        shutil.copytree(PAGES, pkg)
        page = pkg / "Schemas" / "UsrTests_FormPage" / "UsrTests_FormPage.js"
        body = page.read_text(encoding="utf-8-sig")
        marker = "/**SCHEMA_VIEW_CONFIG_DIFF*/["
        assert marker in body
        page.write_text(body.replace(marker, marker + '\n\t/* {\n\t\t"operation": "insert", "name": "UsrOldField",\n\t\t"values": { "type": "crt.Input", "label": "a // b" }\n\t}, */\n\t// "operation": "remove", "name": "UsrGone",\n', 1), encoding="utf-8")
        desc = json.loads((DATA / "Data" / "SysSettings_UsrMaxRows" / "descriptor.json").read_text(encoding="utf-8-sig"))
        for name, data_text in (("UsrNullRows", '{"PackageData": null}'), ("UsrNoDataFile", None), ("UsrBlankFile", "")):
            folder = pkg / "Data" / name
            folder.mkdir(parents=True)
            desc["Descriptor"]["Name"] = name
            (folder / "descriptor.json").write_text(json.dumps(desc), encoding="utf-8")
            if data_text is not None:
                (folder / "data.json").write_text(data_text, encoding="utf-8")
        listed = describe_package(pkg)
        assert "  page      UsrTests_FormPage" in listed and "cannot read: " in listed and "Data/UsrBlankFile" in listed, listed
        assert "UsrNullRows" not in describe_package(pkg, "error") and "UsrNoDataFile" not in describe_package(pkg, "error")
        elements = describe_item(pkg, "UsrTests_FormPage", "elements")
        assert "UsrOldField" not in elements and "UsrGone" not in elements and "AttachmentList" in elements, elements
        assert describe_item(pkg, "UsrNullRows", "rows") == "(no rows)" and describe_item(pkg, "UsrNoDataFile", "rows") == "(no rows)"
        assert "0 rows" in describe_schema(pkg, "UsrNullRows")
        log = (tmp / "packages" / ".creatio-index" / "errors.log").read_text(encoding="utf-8") if (tmp / "packages" / ".creatio-index" / "errors.log").is_file() else (tmp / ".creatio-index" / "errors.log").read_text(encoding="utf-8")
        assert log.count("\n") == 1 and "\tUsrPkg\tdata\tData/UsrBlankFile\t" in log and "empty file" in log, log
        answer = index_workspace(pkg, rebuild=True)
        assert "    unreadable (1): Data/UsrBlankFile - ValueError: Data/UsrBlankFile/data.json: empty file" in answer and "errors.log: " in answer, answer
        from creatio_schemas.describe import store
        blocker = tmp / "blocker"
        blocker.write_text("not a folder", encoding="utf-8")
        try:
            store.connect(blocker / "index.sqlite")
            raise AssertionError("expected OSError")
        except OSError as e:
            assert str(e).startswith(str(blocker)) and "the index folder cannot be opened" in str(e) and "junction or symlink" in str(e), e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_site_pass_with_zero_columns_is_a_pass_and_scaffold_says_no_duplicate():
    """S46-T08 item 4: the pass is the stored row with its date, not the column count."""
    import tempfile
    from creatio_schemas.describe.index import index_path
    from creatio_schemas.describe.site import NO_PASS, column_clash, pass_date, schema_clash, site_pass

    root = Path(tempfile.mkdtemp())
    try:
        pkg = root / "packages" / "UsrPkg"
        pkg.mkdir(parents=True)
        assert schema_clash(pkg, "UsrNew") == ("note", NO_PASS)
        site_pass(index_path(pkg), None, "dev", {}, {}, set())  # nothing beyond the workspace: env is never asked
        assert schema_clash(pkg, "UsrNew") is None  # a pass: no clash, no NO_PASS note
        assert column_clash(pkg, "UsrOrder", "UsrArea") is None
        sys.path.insert(0, str(TOOLS / "scaffold"))
        import scaffold
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert scaffold.stopped(pkg, ["UsrNew"], False) is False
        assert err.getvalue().strip() == f"site pass of {pass_date(index_path(pkg))}: no duplicate", err.getvalue()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_merge_pages_read_single_quoted_deps_and_name_the_layer_of_a_bad_one():
    import json
    import shutil
    import tempfile
    from creatio_schemas.describe.merge import merge_schema

    for deps_b, want in (("['@creatio-devkit/common',]", None), ("['@creatio-devkit/common'", "UsrB UsrPage_FormPage: SCHEMA_DEPS is not an array literal")):
        root = Path(tempfile.mkdtemp())
        try:
            _layer_workspace(root, {"UsrA": (["CrtBase"], {}), "UsrB": (["UsrA"], {})})
            for name, deps in (("UsrA", "[]"), ("UsrB", deps_b)):
                view = json.dumps([{"operation": "merge", "name": "Base" + name, "values": {"visible": True}}])
                _client_layer(root / "packages" / name, "UsrPage_FormPage", FREEDOM_BODY.format(deps=deps, args="sdk" if name == "UsrB" else "", view=view, vm="[]", handlers="", converters=""))
            text, code = merge_schema(root, "UsrPage_FormPage", direction="down")
            assert (code == 0) == (want is None) and (want is None or want in text), text
        finally:
            shutil.rmtree(root, ignore_errors=True)


def test_merge_deps_read_as_a_js_array_literal():
    from creatio_schemas.describe.merge import js_string_list
    assert js_string_list("['@creatio-devkit/common', \"UsrA\", ]") == ["@creatio-devkit/common", "UsrA"]
    assert js_string_list(" [] ") == []
    for bad, why in (("x", "is not an array literal"), ("[UsrA]", "not a quoted string"), ("['a' 'b']", "no comma after 'a'"), ("['a", "is not an array")):
        try:
            js_string_list(bad)
        except ValueError as e:
            assert why in str(e), (bad, str(e))
        else:
            assert False, bad


def test_data_sources_answer_attributes_that_are_dicts():
    from types import SimpleNamespace
    from creatio_schemas.describe.queries import q_pg_sources
    pg = SimpleNamespace(data_sources={"DS": {"scope": "page", "config": {"entitySchemaName": "UsrOrder", "attributes": [{"name": "UsrName"}, "UsrNote"]}}})
    assert q_pg_sources(pg, None, {}).endswith('attributes={"name": "UsrName"}, UsrNote'), q_pg_sources(pg, None, {})


def test_columns_check_names_a_missing_column_and_follows_a_lookup_path():
    from creatio_schemas.describe.columns_check import columns_check, references
    site = {"UsrPkg": ["Id", "UsrName", "UsrContactId"], "Contact": ["Id", "Name"]}  # UsrAmount is planted missing

    class Env:
        def sql(self, text):
            name = text.split("relname = '")[1].split("'")[0] if "pg_constraint" in text else text.split("table_name in ('")[1].split("'")[0]
            if "pg_constraint" in text:
                return [{"column": "UsrContactId", "ref": "Contact"}] if name == "UsrPkg" else []
            return [{"object": name, "column": c} for c in site.get(name, [])]

    env = Env()
    text, code = columns_check(PAGES, env, "UsrTests_FormPage")
    assert code == 1 and "UsrTests_FormPage: attribute UsrAmount: UsrPkg.UsrAmount is missing on the site" in text, text
    assert "UsrPkg.UsrName" not in text
    from creatio_schemas.describe.columns_check import SiteColumns
    s = SiteColumns(env)
    assert s.missing("UsrPkg", "UsrContact.Name") is None and s.missing("UsrPkg", "UsrContact.Nope") == "Contact.Nope"
    assert s.missing("UsrNo", "Id") == "UsrNo (object)"
    cs = Path(__import__("tempfile").mkdtemp()) / "UsrPkg"
    (cs / "Files" / "cs").mkdir(parents=True)
    (cs / "Files" / "cs" / "UsrQ.cs").write_text('var q = new EntitySchemaQuery(m, "UsrPkg"); q.AddColumn("UsrName"); q.AddColumn("UsrContact.Name");', encoding="utf-8")
    assert references(cs) == [("UsrQ", "AddColumn", "UsrPkg", "UsrName"), ("UsrQ", "AddColumn", "UsrPkg", "UsrContact.Name")]
    shutil.rmtree(cs.parent, ignore_errors=True)


def test_columns_check_reads_classic_bindto_and_rule_columns():
    import tempfile
    from creatio_schemas.describe.columns_check import columns_check
    body = ('define("UsrOrderPage", [], function() {\n\treturn {\n\t\tentitySchemaName: "UsrOrder",\n\t\tattributes: {"UsrLocal": {}},\n'
            '\t\tbusinessRules: /**SCHEMA_BUSINESS_RULES*/{\n\t\t\t"UsrGone": {"u1": {"uId": "u1", "enabled": true}},\n\t\t\t"UsrLocal": {"u2": {"uId": "u2"}}\n'
            '\t\t}/**SCHEMA_BUSINESS_RULES*/,\n\t\tdiff: /**SCHEMA_DIFF*/[\n\t\t\t{"operation": "insert", "name": "UsrName", "values": {"bindTo": "UsrName",\n'
            '\t\t\t\t"visible": {"bindTo": "isShown"}, "caption": {"bindTo": "UsrCaptionGone"}, "click": {"bindTo": "onUsrClick"}}}\n\t\t]/**SCHEMA_DIFF*/\n\t};\n});\n')
    tmp = Path(tempfile.mkdtemp())
    try:
        shutil.copytree(TOOLS / "classicui" / "tests" / "fixtures" / "UsrPkg", tmp / "UsrPkg")  # the Classic fixture, its body replaced
        (tmp / "UsrPkg" / "Schemas" / "UsrOrderPage" / "UsrOrderPage.js").write_text(body, encoding="utf-8")

        class Env:
            def sql(self, text):
                return [] if "pg_constraint" in text else [{"object": "UsrOrder", "column": c} for c in ("Id", "UsrName")]

        text, code = columns_check(tmp / "UsrPkg", Env(), "UsrOrderPage")
        assert code == 1 and text.splitlines() == [
            "UsrOrderPage: diff UsrName bindTo: UsrOrder.UsrCaptionGone is missing on the site (path UsrOrder.UsrCaptionGone)",
            "UsrOrderPage: businessRules column: UsrOrder.UsrGone is missing on the site (path UsrOrder.UsrGone)"], text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_descriptor_touch_keeps_the_date_form_the_file_has():
    from creatio_schemas.schema import Descriptor
    for old in ('\/Date(1)\/', "/Date(1)/"):
        d = Descriptor(Path("x"), '{"Descriptor": {"ModifiedOnUtc": "' + old + '"}}')
        d.touch()
        new = d.text.split('"ModifiedOnUtc": "')[1].split('"')[0]
        assert new != old and new.startswith("\/" if old.startswith("\\") else "/") and new.endswith(")\/" if old.startswith("\\") else ")/"), (old, new)


def test_platform_version_comes_from_the_project():
    import json
    import shutil
    import tempfile
    from unittest.mock import patch
    from creatio_schemas.platform_version import platform_version, stamp

    tmp = Path(tempfile.mkdtemp())
    try:
        def project(**data):
            (tmp / "project.json").write_text(json.dumps(data), encoding="utf-8")
            return tmp / "project.json"

        assert platform_version(project(environment={"platformVersion": "8.3.2.4199"})) == "8.3.2.4199"
        assert platform_version(project(environment={"platformVersion": "8.3.2"})) == "8.3.2"
        assert platform_version(None) == "" and platform_version(project(environment={})) == ""
        # no version named: the binaries of paths.platformBin (relative to project.json), never a schema's CreatedInVersion
        with patch("creatio_schemas.describe.platform.version_of", return_value="8.2.3.1351") as seen:
            assert platform_version(project(paths={"platformBin": "bin"})) == "8.2.3.1351"
            assert seen.call_args.args[0] == tmp / "bin"
        with patch("creatio_schemas.describe.platform.version_of", return_value=None):
            assert platform_version(project(paths={"platformBin": "bin"})) == ""
        # a short version takes the bin's full one when the bin matches, else stays short
        short = project(environment={"platformVersion": "8.3.2"}, paths={"platformBin": "bin"})
        with patch("creatio_schemas.describe.platform.version_of", return_value="8.3.2.4199"):
            assert platform_version(short) == "8.3.2.4199"
        with patch("creatio_schemas.describe.platform.version_of", return_value="8.2.3.1351"):
            assert platform_version(short) == "8.3.2"
        # the writers' keyword: explicit wins, short is padded, nothing known leaves the writer's default
        assert stamp("8.3.4.1", project(environment={"platformVersion": "8.3.2"})) == {"version": "8.3.4.1"}
        assert stamp(None, project(environment={"platformVersion": "8.3.2"})) == {"version": "8.3.2.0"}
        assert stamp(None, None) == {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_stock_catalogue_follows_the_platform_version():
    import json
    from creatio_schemas.entity.catalog import ASSETS, STOCK_ENTITIES, stock, stock_columns

    old, new = stock("8.2.3.1351"), stock("8.3.2")
    assert old.entities == json.loads((ASSETS / "entities_8.2.3.json").read_text(encoding="utf-8"))["entities"]
    assert stock("8.2.9").entities is old.entities and stock("8.2.2").entities is old.entities  # same file; older than every file: the oldest
    assert new.entities is STOCK_ENTITIES and stock("").entities is STOCK_ENTITIES and stock("8.3").entities is STOCK_ENTITIES
    assert stock("8.3.4.2753").entities is new.entities and stock("garbage").entities is new.entities  # nearest lower; unknown: the newest
    assert stock("8.2.3") is stock("8.2.3.1351")  # cached per file set
    assert old.lookups != new.lookups and old.columns("Contact") == new.columns("Contact") == stock_columns("Contact")  # columns: the one file there is


def test_the_index_stores_the_platform_and_picks_the_catalogue_by_it():
    import json
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    try:
        pkg = tmp / "UsrPkg"
        shutil.copytree(PAGES, pkg)
        proj = tmp / "project.json"
        for version in ("8.3.2.4199", "8.2.3"):
            proj.write_text(json.dumps({"environment": {"platformVersion": version}}), encoding="utf-8")
            index_workspace(pkg, project=str(proj))
            assert PackageIndex(pkg).head["platform"] == version
        index_workspace(pkg)  # no project: the stored version stays
        assert PackageIndex(pkg).head["platform"] == "8.2.3"
        assert PackageIndex(pkg).platform == "8.2.3"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_replacing_dependency_entry_keeps_the_install_behavior_of_the_replaced_one():
    from creatio_schemas.describe.package_merge import _entry

    parent = {"UId": "p", "PackageVersion": "1.0", "Name": "UsrBase", "Type": 0, "InstallBehavior": 4}
    assert _entry(parent, {"Name": "UsrChild", "InstallBehavior": 1}) == {"UId": "p", "PackageVersion": "1.0", "Name": "UsrBase", "Type": 0, "InstallBehavior": 1}
    assert "InstallBehavior" not in _entry(parent, {"Name": "UsrChild"}) and "InstallBehavior" not in _entry(parent)


def test_the_8_3_kinds_are_named():
    import json
    import shutil
    import tempfile
    from creatio_schemas.classicui import ClassicSchema

    tmp = Path(tempfile.mkdtemp())
    try:
        pkg = tmp / "UsrPkg"
        shutil.copytree(PAGES, pkg)
        svc = pkg / "Schemas" / "UsrApi"
        svc.mkdir()
        (svc / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": "u-1", "Name": "UsrApi", "ManagerName": "ServiceSchemaManager", "Caption": "Api"}}), encoding="utf-8")
        (svc / "properties.json").write_text(json.dumps({"Properties": {"BaseUri": "https://example.invalid/api", "Type": "Rest"}}), encoding="utf-8")
        assert "  service   UsrApi" in describe_package(pkg) and "service Rest https://example.invalid/api" in describe_package(pkg, "service")
        classic = TOOLS / "classicui" / "tests" / "fixtures" / "UsrPkg"
        shutil.copytree(classic, tmp / "UsrClassic")
        props = tmp / "UsrClassic" / "Schemas" / "UsrOrderPage" / "properties.json"
        for schema_type, label in (("None", "dashboard or home page"), ("MobileSchema", "mobile page")):
            props.write_text(json.dumps({"Properties": {"SchemaType": schema_type}}), encoding="utf-8")
            assert ClassicSchema(tmp / "UsrClassic", "UsrOrderPage").kind == label
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for fn in [v for k, v in list(globals().items()) if k.startswith("test_")]:
        fn()
        print("ok", fn.__name__)
