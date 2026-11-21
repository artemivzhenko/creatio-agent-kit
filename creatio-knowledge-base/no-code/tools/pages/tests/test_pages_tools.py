"""
Checks for the page tools. Pure standard library:  python tests/test_pages_tools.py
(also collected by pytest). The fixtures are a Creatio 8.2.3 export of UsrPkg: UsrTests_FormPage
(saved by the designer: viewModelConfig form) and UsrOrder_FormPage (created by clio from a
template: viewModelConfigDiff form), with the objects they bind to.
"""

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent))

from creatio_schemas.page import PageSchema  # noqa: E402
from pages import main  # noqa: E402

FIXTURES = HERE / "fixtures" / "UsrPkg"
PAGES = ("UsrTests_FormPage", "UsrOrder_FormPage")


def read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def copy() -> Path:
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(FIXTURES, tmp / "UsrPkg")
    return tmp / "UsrPkg"


def test_validate_tolerates_an_attribute_that_is_a_list():
    page = PageSchema(FIXTURES, PAGES[0])
    page.attributes_w()["UsrListAttr"] = ["a", "b"]  # a designer may store a list under attributes (seen in a client page)
    page.validate()
    page.describe()


def test_round_trip_is_byte_identical():
    for name in PAGES:
        page = PageSchema(FIXTURES, name)
        page.describe()
        page.validate()
        for path, (text, bom) in page.files().items():
            assert read(path) == ("﻿" if bom else "") + text, f"{name}: {path.name} re-rendered differently"
        assert page.diff() == ""


def test_add_field_in_both_body_forms():
    for name, column, parent in (("UsrTests_FormPage", "UsrNumber", "SideAreaProfileContainer"),
                                 ("UsrOrder_FormPage", "UsrShipDate", "SideAreaProfileContainer")):
        pkg = copy()
        page = PageSchema(pkg, name)
        if page.has(column):
            page.remove(column)
        op = page.add_field(column, parent=parent)
        page.save()
        again = PageSchema(pkg, name)
        el = again.element(column)
        assert el["values"]["control"] == f"${column}"
        assert again.attributes[column] == {"modelConfig": {"path": f"PDS.{column}"}}
        assert el["values"]["layoutConfig"]["row"] == op["values"]["layoutConfig"]["row"]
        assert again.diff() == "", "a second render must be stable"
        assert again.validate() == []
    pkg = copy()
    page = PageSchema(pkg, "UsrOrder_FormPage")
    assert page.add_field("UsrShipDate")["values"]["pickerType"] == "date"
    assert page.add_field("UsrPickupTime")["values"]["pickerType"] == "time"
    assert page.add_field("UsrEmail")["values"]["type"] == "crt.EmailInput"
    assert page.add_field("UsrIsUrgent")["values"]["type"] == "crt.Checkbox"
    assert page.add_field("UsrStatus")["values"]["type"] == "crt.ComboBox"
    rows = [page.element(c)["values"]["layoutConfig"]["row"] for c in ("UsrShipDate", "UsrPickupTime", "UsrEmail")]
    assert rows == [1, 2, 3]
    body = page.render_body()
    assert '"UsrShipDate": {' in body and "viewModelConfigDiff" in body
    ops = json.loads(body.split("/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/")[1])
    assert ops[0]["path"] == ["attributes"] and "UsrEmail" in ops[0]["values"]


def test_add_grid_and_remove():
    pkg = copy()
    page = PageSchema(pkg, "UsrTests_FormPage")
    # the fixture's grid was written by hand (S11-T01); the tool must reproduce it
    hand = json.loads(json.dumps(page.element("UsrOrderList")))
    page.remove("UsrOrderList")
    op = page.add_grid("UsrOrderList", "UsrOrder", ["UsrName", "UsrQuantity"])
    for item in (hand, op):
        for c in item["values"]["columns"]:
            c.pop("id")
    hand["values"]["columns"][1]["width"] = 200  # the only hand-picked difference
    assert op == hand
    assert op["values"]["columns"][0]["caption"] == "Name"
    assert page.data_sources["UsrOrderListDS"]["config"]["entitySchemaName"] == "UsrOrder"
    assert page.attributes["UsrOrderList"]["isCollection"] is True
    page.save()
    again = PageSchema(pkg, "UsrTests_FormPage")
    assert again.has("UsrOrderList") and "UsrOrderListDS" in again.data_sources
    again.remove("UsrOrderList")
    assert not again.has("UsrOrderList") and "UsrOrderListDS" not in again.data_sources and "UsrOrderList" not in again.attributes
    again.save()
    assert PageSchema(pkg, "UsrTests_FormPage").diff() == ""


def test_unknown_column_and_duplicate_are_refused():
    page = PageSchema(copy(), "UsrTests_FormPage")
    for args in (("UsrNope",), ("UsrName",)):
        try:
            page.add_field(*args)
        except KeyError as e:
            assert args[0] in str(e)
        else:
            raise AssertionError(f"add_field{args} should fail")


def test_cli_dry_run_writes_nothing():
    import contextlib
    import io
    pkg = copy()
    before = read(pkg / "Schemas" / "UsrOrder_FormPage" / "UsrOrder_FormPage.js")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["add-field", str(pkg), "UsrOrder_FormPage", "UsrWeight", "--dry-run"])
    assert code == 0 and "crt.NumberInput" in out.getvalue() and "(dry run" in out.getvalue()
    assert read(pkg / "Schemas" / "UsrOrder_FormPage" / "UsrOrder_FormPage.js") == before
    with contextlib.redirect_stdout(out):
        assert main(["inspect", str(pkg), "UsrTests_FormPage"]) == 0
    assert "page of UsrPkg" in out.getvalue()


def test_handlers_survive_comments_with_apostrophes_and_braces():
    import re
    page = PageSchema(FIXTURES, "UsrOrder_FormPage")
    snippet = """[
            {
                request: "crt.HandleViewModelInitRequest",
                handler: async (request, next) => {
                    // the user's id isn't known yet { and this brace is text
                    /* a block comment with an apostrophe ' and a } brace */
                    await next?.handle(request);
                }
            },
            {
                request: "usr.SecondRequest",
                handler: async (request, next) => next?.handle(request)
            }
        ]"""
    page.body = re.sub(r"/\*\*SCHEMA_HANDLERS\*/.*?/\*\*SCHEMA_HANDLERS\*/", lambda m: f"/**SCHEMA_HANDLERS*/{snippet}/**SCHEMA_HANDLERS*/", page.body, flags=re.S)
    assert [name for name, _ in page.handlers()] == ["crt.HandleViewModelInitRequest", "usr.SecondRequest"]


def test_create_writes_what_clio_create_page_writes():
    import re
    pkg = copy()
    try:
        orig = PageSchema(pkg, "UsrOrder_FormPage")  # an empty form page made by clio from PageWithTabsFreedomTemplate
        new = PageSchema.create(pkg, "UsrOrderCopy_FormPage", "UsrOrder", "form", "Order form page")
        swap = lambda t: t.replace(orig.descriptor.data["UId"], new.descriptor.data["UId"]).replace("UsrOrder_FormPage", "UsrOrderCopy_FormPage")  # noqa: E731
        for a, b in (("UsrOrder_FormPage.js", "UsrOrderCopy_FormPage.js"), ("metadata.json", "metadata.json"), ("properties.json", "properties.json")):
            assert swap(read(pkg / "Schemas" / "UsrOrder_FormPage" / a)) == read(pkg / "Schemas" / "UsrOrderCopy_FormPage" / b), a
        undate = lambda t: re.sub(r"Date\(\d+\)", "Date(0)", t)  # noqa: E731
        assert undate(swap(orig.descriptor.text)) == undate(new.descriptor.text)
        for f in (pkg / "Resources" / "UsrOrder_FormPage.ClientUnit").glob("*.xml"):  # the caption in each of the package's 28 cultures
            assert read(f) == read(pkg / "Resources" / "UsrOrderCopy_FormPage.ClientUnit" / f.name), f.name
        listing = PageSchema.create(pkg, "UsrOrder_ListPage", "UsrOrder", "list", "Orders", ["en-US"])
        assert listing.entity == "UsrOrder" and listing.descriptor.data["Parent"]["Name"] == "ListPageV2Template" and listing.validate() == []
        assert listing.diff() == "" and list(listing.resources.cultures) == ["en-US"]
        for args, error in ((("UsrOrder_ListPage", "UsrOrder", "list"), FileExistsError), (("UsrX_Page", "UsrOrder", "card"), ValueError),
                            (("ia X", "UsrOrder", "form"), ValueError)):
            try:
                PageSchema.create(pkg, *args)
            except error:
                pass
            else:
                raise AssertionError(f"create{args} must raise {error.__name__}")
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


EXPECTED = HERE / "fixtures" / "expected"  # what the UI test utility's analyse wrote for the two pages after their push


def test_page_file_from_schema_equals_what_analyse_wrote():
    from creatio_schemas.page import compare_page_files
    data, notes = PageSchema(FIXTURES, "UsrTests_FormPage").page_file()
    assert json.dumps(data, indent=2, ensure_ascii=False) + "\n" == read(EXPECTED / "UsrTestsForm.json")  # byte for byte
    assert notes == ["not written (crt.Feed): Feed", "not written (crt.FileList): AttachmentList"]
    # the order page was analysed after the 17 fields and the grid were put on it with these tools
    pkg = copy()
    try:
        page = PageSchema(pkg, "UsrOrder_FormPage")
        expected = json.loads(read(EXPECTED / "UsrOrderForm.json"))
        assert all(line.startswith("only in the file: ") for line in compare_page_files(expected, page.page_file()[0]))
        for e in expected["elements"]:
            if e["code"] in page.workspace.columns("UsrOrder"):
                page.add_field(e["code"])
        page.add_grid("UsrOrdersGrid", "UsrOrder", ["UsrName", "UsrQuantity", "UsrAmount"])
        assert compare_page_files(expected, page.page_file()[0]) == []
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


def test_a_page_rule_marks_its_targets_conditional():
    from creatio_schemas import RuleSchema
    from creatio_schemas.page import compare_page_files
    plain = PageSchema(FIXTURES, "UsrTests_FormPage").page_file()[0]
    assert not any("conditional" in e for e in plain["elements"])  # no rule schema, no key
    pkg = copy()
    try:
        rules = RuleSchema.create(pkg, "UsrTests_FormPage")
        rules.add({"conditions": [{"left": "UsrIsActive", "op": "equal", "value": True}], "actions": [{"type": "hide", "items": ["UsrIsActive"]}]})
        rules.add({"conditions": [{"left": "UsrIsActive", "op": "empty"}], "actions": [{"type": "show", "items": ["UsrOrderList"]}, {"type": "required", "items": ["UsrIsActive"]}]})
        rules.save()
        page = PageSchema(pkg, "UsrTests_FormPage")
        assert page.rule_toggled() == {"UsrIsActive", "UsrOrderList"}  # `required` does not hide anything
        data = page.page_file()[0]
        assert sorted(e["code"] for e in data["elements"] if e.get("conditional")) == ["UsrIsActive", "UsrOrderList"]
        assert all(e.get("conditional") is True for e in data["elements"] if e["code"] in ("UsrIsActive", "UsrOrderList"))
        assert {k: v for k, v in data.items() if k != "elements"} == {k: v for k, v in plain.items() if k != "elements"}
        assert [e for e in data["elements"] if not e.get("conditional")] == [e for e in plain["elements"] if e["code"] not in ("UsrIsActive", "UsrOrderList")]
        assert compare_page_files(plain, data) == []  # --compare: `conditional` is not a difference
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


def test_page_file_labels_types_and_template_elements():
    page = PageSchema(FIXTURES, "UsrTests_FormPage")
    ops = page.view_config_diff
    by_name = {op.get("name"): op for op in ops}
    page.resources.set("LocalizableStrings.UsrName_caption.Value", "Order name", ["en-US"])
    by_name["UsrName"]["values"]["label"] = "#ResourceString(UsrName_caption)#"       # a page string
    by_name["UsrComment"]["values"]["label"] = "Plain text"                           # a literal
    by_name["UsrNumber"]["values"]["label"] = "$Resources.Strings.PDS_Nope_x1"         # nothing to resolve
    by_name["UsrDateTime"]["values"].pop("pickerType")                                # no picker type: the column's type
    by_name["UsrAccount"]["values"]["visible"] = False                                 # hidden by the page itself
    ops.append({"operation": "merge", "name": "GeneralInfoTab", "values": {"caption": "Main"}})
    ops.append({"operation": "remove", "name": "BackButton"})
    data, notes = page.page_file("Custom")
    got = {e["code"]: e for e in data["elements"]}
    assert data["name"] == "Custom" and got["UsrName"]["label"] == "Order name" and got["UsrComment"]["label"] == "Plain text"
    assert got["UsrNumber"]["label"] == "" and any("label unknown" in n and "UsrNumber" in n for n in notes)
    assert got["UsrDateTime"]["type"] == "DateTime" and "UsrAccount" not in got and any("hidden" in n and "UsrAccount" in n for n in notes)
    assert got["GeneralInfoTab"]["label"] == "Main" and "BackButton" not in got
    assert got["UsrNumber"]["type"] == "Integer" and got["UsrAmount"]["type"] == "Decimal" and got["UsrOrderList"]["columns"] == ["Name", "Quantity"]
    page.rule_toggled = lambda: {"UsrAccount"}  # a rule may show the control the page hides: the file lists what the page can show
    data, notes = page.page_file()
    shown = {e["code"]: e for e in data["elements"]}
    assert shown["UsrAccount"]["conditional"] is True and not any("UsrAccount" in n for n in notes)
    page.descriptor.set("Parent", {"UId": "00000000-0000-0000-0000-000000000001", "Name": "BaseMiniPageTemplate"})
    data, notes = page.page_file()
    assert "CloseButton" not in {e["code"] for e in data["elements"]} and any("BaseMiniPageTemplate" in n for n in notes)


def test_from_schema_command():
    import contextlib
    import io
    pkg = copy()
    try:
        out_file = pkg.parent / "UsrTestsForm.json"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert main(["from-schema", str(pkg), "UsrTests_FormPage", "--out", str(out_file)]) == 0
            assert main(["from-schema", str(pkg), "UsrTests_FormPage", "--compare", str(EXPECTED / "UsrTestsForm.json")]) == 0
            assert main(["from-schema", str(pkg), "UsrOrder_FormPage", "--compare", str(EXPECTED / "UsrOrderForm.json")]) == 1
            assert main(["from-schema", str(pkg), "UsrTests_FormPage", "--name", "X"]) == 0
        text = out.getvalue()
        assert read(out_file) == read(EXPECTED / "UsrTestsForm.json") and "wrote " in text and "# not written (crt.Feed): Feed" in text
        assert "no difference from" in text and "only in the file: UsrAmount (Decimal)" in text and '"name": "X"' in text
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


def test_from_schema_reads_the_labels_in_the_primary_culture_of_the_package():
    import contextlib
    import io
    pkg = copy()
    try:
        page = PageSchema(pkg, "UsrTests_FormPage")
        by_name = {op.get("name"): op for op in page.view_config_diff}
        by_name["UsrName"]["values"]["label"] = "#ResourceString(UsrName_caption)#"
        page.resources.set("LocalizableStrings.UsrName_caption.Value", "Order name", ["en-US"])
        page.resources.set("LocalizableStrings.UsrName_caption.Value", "Nazva zamovlennia", ["uk-UA"])
        for i in range(80):  # uk-UA holds the most keys of the package: its primary culture
            page.resources.set(f"LocalizableStrings.Filler{i}.Value", "x", ["uk-UA"])
        page.save()
        out_file = pkg.parent / "form.json"
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(["from-schema", str(pkg), "UsrTests_FormPage", "--out", str(out_file)]) == 0
        assert {e["code"]: e["label"] for e in json.loads(read(out_file))["elements"]}["UsrName"] == "Nazva zamovlennia"
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(["from-schema", str(pkg), "UsrTests_FormPage", "--out", str(out_file), "--culture", "en-US"]) == 0
        assert {e["code"]: e["label"] for e in json.loads(read(out_file))["elements"]}["UsrName"] == "Order name"
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


def _audit(pkg, page, *extra):
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["audit", str(pkg), page, *extra])
    return rc, buf.getvalue().splitlines()


def test_audit_prints_the_findings_over_a_threshold_and_exits_1():
    pkg = copy()
    try:
        page = PageSchema(pkg, "UsrOrder_FormPage")
        page.view_config_diff.append({"operation": "insert", "name": "UsrBigTab", "parentName": "Tabs", "propertyName": "tabs",
                                      "values": {"type": "crt.TabContainer"}})
        for i in range(90):
            page.view_config_diff.append({"operation": "insert", "name": f"UsrF{i}", "parentName": "UsrBigTab", "propertyName": "items",
                                          "values": {"type": "crt.Input"}})
        page.view_config_diff.append({"operation": "insert", "name": "UsrLines", "parentName": "UsrBigTab", "propertyName": "items",
                                      "values": {"type": "crt.DataGrid", "items": "$UsrLines"}})
        page.attributes_w()["UsrLines"] = {"isCollection": True, "modelConfig": {"path": "UsrLinesDS"}}
        page.data_sources_w()["UsrLinesDS"] = {"type": "crt.EntityDataSource", "scope": "viewElement", "config": {"entitySchemaName": "UsrLine"}}
        page.attributes_w()["UsrDeep"] = {"modelConfig": {"path": "PDS.Account.Owner.Contact.Name"}}
        page.save()
        rc, lines = _audit(pkg, "UsrOrder_FormPage")
        assert rc == 1
        assert "elements 91 on tab UsrBigTab" in lines
        assert "grid UsrLines (UsrLine): no master filter" in lines
        assert "attribute UsrDeep: path PDS.Account.Owner.Contact.Name (3 joins)" in lines
        assert "attributes through 2+ joins: 1" in lines
        assert lines[-1] == "UsrOrder_FormPage: 4 finding(s)"
        page = PageSchema(pkg, "UsrOrder_FormPage")  # a filter on the collection attribute clears the grid line
        page.attributes_w()["UsrLines"]["modelConfig"]["filterAttributes"] = [{"loadOnChange": True, "name": "UsrLinesDS_Filter"}]
        page.save()
        assert "grid UsrLines (UsrLine): no master filter" not in _audit(pkg, "UsrOrder_FormPage")[1]
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


def test_audit_of_a_clean_page_prints_the_last_line_and_exits_0():
    rc, lines = _audit(FIXTURES, "UsrOrder_FormPage")
    assert rc == 0 and lines == ["UsrOrder_FormPage: 0 finding(s)"]
    rc, lines = _audit(FIXTURES, "UsrOrder_FormPage", "--all")
    assert rc == 0 and "comboboxes 0" in lines and lines[-1].endswith("count(s)")


def test_a_resource_string_value_gets_its_metadata_entry_and_its_string():
    from creatio_schemas.describe.queries import answer

    pkg = copy()
    try:
        page = PageSchema(pkg, "UsrOrder_FormPage")
        page.add_field("UsrName")
        page.set_value("UsrName", "label", "#ResourceString(UsrLinkCaption)#", "Open order")
        page.save()
        meta = read(pkg / "Schemas" / "UsrOrder_FormPage" / "metadata.json")
        nl = "\r\n" if "\r\n" in meta else "\n"
        entry = json.loads(meta.split("+ MetaData.Schema.B2 ", 1)[1].split(nl + "}", 1)[0] + nl + "}")
        schema_uid = meta.split('MetaData.Schema.UId "', 1)[1].split('"', 1)[0]
        assert entry["A2"] == "UsrLinkCaption" and entry["A3"] == entry["A4"] == schema_uid
        order = json.loads(meta.split("~ MetaData.Schema.B2 ", 1)[1].split(nl, 1)[0])
        assert order[0] == entry["UId"] and len(order) == len(set(order)) and len(order) > 1
        res = PageSchema(pkg, "UsrOrder_FormPage")
        assert res.resources.get("LocalizableStrings.UsrLinkCaption.Value", "en-US") == "Open order"
        assert not [p for p in res.validate() if "ResourceString" in p]
        assert "LocalizableStrings.UsrLinkCaption.Value" in answer(res, "resources", None, {"limit": "0"})
        # the same key again changes nothing; a new key without text is refused
        res.set_value("UsrName", "caption", "#ResourceString(UsrLinkCaption)#")
        assert res._metadata.count("UsrLinkCaption") == 1
        try:
            res.set_value("UsrName", "caption", "#ResourceString(UsrOther)#")
            raise AssertionError("a new string without text must be refused")
        except ValueError as e:
            assert "give one" in str(e)
        # a key named in the body with no B2 entry is an error of validate
        res = PageSchema(pkg, "UsrOrder_FormPage")
        res.body += "\n// label: #ResourceString(UsrDangling)#"
        assert not [p for p in res.validate() if "UsrDangling" in p]  # neither half: the platform's or the parent's string, not judged
        res.resources.set("LocalizableStrings.UsrDangling.Value", "x", ["en-US"])  # a string without its B2 entry
        assert any("UsrDangling" in p and "B2" in p for p in res.validate())
        res._metadata = res._metadata.replace("UsrLinkCaption", "UsrOnlyEntry")  # an entry without its string
        res.body += " #ResourceString(UsrOnlyEntry)#"
        assert any("UsrOnlyEntry" in p and "no LocalizableStrings" in p for p in res.validate())
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


if __name__ == "__main__":
    for fn in [v for k, v in list(globals().items()) if k.startswith("test_")]:
        fn()
        print("ok", fn.__name__)
