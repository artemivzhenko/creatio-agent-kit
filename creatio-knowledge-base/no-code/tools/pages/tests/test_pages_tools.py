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
    op = page.add_grid("UsrOrderList", "UsrOrder", ["UsrName", "UsrQuantity"], literal_captions=True)
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
    page.descriptor.set("Parent", {"UId": "00000000-0000-0000-0000-000000000001", "Name": "UsrUnknownTemplate"})
    data, notes = page.page_file()
    assert "CloseButton" not in {e["code"] for e in data["elements"]} and any("UsrUnknownTemplate" in n for n in notes)
    page.descriptor.set("Parent", {"UId": "ecdcc8ff-272c-4957-9381-7d74ce17e140", "Name": "BaseMiniPageTemplate"})  # S45-T09: a pre-configured page
    data, notes = page.page_file()
    assert {"SaveButton", "CancelButton"} <= {e["code"] for e in data["elements"]} and not any("not known" in n for n in notes)


def test_from_schema_lists_the_form_templates_save_and_cancel_buttons():
    from creatio_schemas.page import compare_page_files
    data, _ = PageSchema(FIXTURES, "UsrOrder_FormPage").page_file()
    got = {e["code"]: e for e in data["elements"]}
    assert got["SaveButton"] == {"code": "SaveButton", "label": "Save", "type": "Button", "pinned": True, "isSave": True}
    assert got["CancelButton"]["label"] == "Cancel" and got["CancelButton"]["pinned"] is True
    with_buttons = {"elements": [got["SaveButton"], got["CancelButton"]]}
    assert [l for l in compare_page_files(with_buttons, data) if "Button" in l and "only in the file" in l] == []
    assert any("only in the file: SaveButton" in l for l in compare_page_files(with_buttons, {"elements": []}))


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
        assert "grid UsrLines (UsrLine): no master filter" in " ".join(lines) and "dependencies" in " ".join(lines)
        assert "attribute UsrDeep: path PDS.Account.Owner.Contact.Name (3 joins)" in lines
        assert "attributes through 2+ joins: 1" in lines
        assert lines[-1] == "UsrOrder_FormPage: 4 finding(s)"
        page = PageSchema(pkg, "UsrOrder_FormPage")  # a filter on the collection attribute clears the grid line
        page.attributes_w()["UsrLines"]["modelConfig"]["filterAttributes"] = [{"loadOnChange": True, "name": "UsrLinesDS_Filter"}]
        page.save()
        assert "no master filter" not in " ".join(_audit(pkg, "UsrOrder_FormPage")[1])
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


def test_add_grid_master_filter_button_and_resource_captions():
    pkg = copy()
    try:
        page = PageSchema(pkg, "UsrOrder_FormPage")
        page.add_grid("UsrLines", "UsrOrder", ["UsrName", "UsrQuantity"], master="UsrManager", add_button=True)
        page.save()
        page = PageSchema(pkg, "UsrOrder_FormPage")
        assert page.dependencies == {"UsrLinesDS": [{"attributePath": "UsrManager", "relationPath": "PDS.Id"}]}
        assert "no master filter" not in " ".join(_audit(pkg, "UsrOrder_FormPage")[1])
        btn, grid = page.element("UsrLinesAddButton")["values"], page.element("UsrLines")
        assert btn["clicked"] == {"request": "crt.CreateRecordRequest", "params": {
            "entityName": "UsrOrder", "entityPageName": "UsrOrder_FormPage",
            "defaultValues": [{"attributeName": "UsrManager", "value": "$Id"}]}}
        assert btn["icon"] == "add-button-icon" and btn["clickMode"] == "default"
        assert btn["layoutConfig"]["row"] + 1 == grid["values"]["layoutConfig"]["row"]
        ops = page.view_config_diff
        assert ops.index(page.element("UsrLinesAddButton")) < ops.index(grid)
        cols = grid["values"]["columns"]
        assert cols[0]["caption"] == "#ResourceString(UsrLinesDS_UsrName)#"
        assert page.resources.get("LocalizableStrings.UsrLinesDS_UsrName.Value", "en-US") == "Name"
        assert "UsrLinesDS_UsrName" in page.own_string_keys() and "UsrLinesAddButton_Caption" in page.own_string_keys()
        assert not page.validate() or not [p for p in page.validate() if "ResourceString" in p]
        lit = PageSchema(pkg, "UsrTests_FormPage")
        lit.add_grid("UsrLit", "UsrOrder", ["UsrName"], literal_captions=True)
        assert lit.element("UsrLit")["values"]["columns"][0]["caption"] == "Name" and not lit.dependencies
        try:
            page.add_grid("UsrBad", "UsrOrder", ["UsrName"], master="UsrNope")
            raise AssertionError("an unknown master column must be refused")
        except KeyError as e:
            assert "UsrNope" in str(e)
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


def test_add_grid_command_warns_without_master_and_set_value_writes_json_types():
    import contextlib
    import io
    pkg = copy()
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert main(["add-grid", str(pkg), "UsrOrder_FormPage", "UsrLines", "--entity", "UsrOrder", "--columns", "UsrName"]) == 0
        assert "warning: no --master: the grid lists every row of UsrOrder" in out.getvalue()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert main(["add-grid", str(pkg), "UsrOrder_FormPage", "UsrLines2", "--entity", "UsrOrder", "--columns", "UsrName",
                         "--master", "UsrManager", "--add-button", "--page", "UsrOther_FormPage"]) == 0
        assert "warning" not in out.getvalue()
        page = PageSchema(pkg, "UsrOrder_FormPage")
        assert page.element("UsrLines2AddButton")["values"]["clicked"]["params"]["entityPageName"] == "UsrOther_FormPage"
        for value, expected in (("true", True), ("false", False), ("42", 42), ("Caption", "Caption")):
            page.set_value("UsrLines", "probe", value)
            got = page.element("UsrLines")["values"]["probe"]
            assert got == expected and type(got) is type(expected), value
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


def test_new_makes_a_page_for_an_existing_object_and_refuses_an_existing_one():
    import contextlib
    import io
    pkg = copy()
    try:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out):
            assert main(["new", str(pkg), "UsrOrderNew_FormPage", "--entity", "UsrOrder", "--fields", "UsrName,UsrAmount", "--dry-run"]) == 0
        assert "(dry run" in out.getvalue() and not (pkg / "Schemas" / "UsrOrderNew_FormPage").exists()
        with contextlib.redirect_stdout(out):
            assert main(["new", str(pkg), "UsrOrderNew_FormPage", "--entity", "UsrOrder", "--fields", "UsrName,UsrAmount"]) == 0
            assert main(["validate", str(pkg), "UsrOrderNew_FormPage"]) == 0
        page = PageSchema(pkg, "UsrOrderNew_FormPage")
        assert page.validate() == [] and page.entity == "UsrOrder"
        assert [n for n in ("UsrName", "UsrAmount") if page.has(n)] == ["UsrName", "UsrAmount"]
        assert {"UsrName", "UsrAmount"} <= {a.get("modelConfig", {}).get("path", "").split(".")[-1] for a in page.attributes.values()}
        assert page.resources.get("Caption") == "Order form"  # the object's caption + " form"
        before = read(pkg / "Schemas" / "UsrOrderNew_FormPage" / "UsrOrderNew_FormPage.js")
        with contextlib.redirect_stderr(err):
            assert main(["new", str(pkg), "UsrOrderNew_FormPage", "--entity", "UsrOrder"]) == 2
        assert "error: UsrOrderNew_FormPage exists" in err.getvalue()
        assert read(pkg / "Schemas" / "UsrOrderNew_FormPage" / "UsrOrderNew_FormPage.js") == before
        with contextlib.redirect_stdout(out):  # no --fields: every own column
            assert main(["new", str(pkg), "UsrOrderAll_FormPage", "--entity", "UsrOrder"]) == 0
        assert PageSchema(pkg, "UsrOrderAll_FormPage").has("UsrWeight")
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


def test_new_mini_page_is_a_pre_configured_page_with_one_label():
    # S47-T02: what the bed's hand-written pre-configured page carries (parent BaseMiniPageTemplate, Group MiniPage, one label)
    import contextlib
    import io
    pkg = copy()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(["new", str(pkg), "UsrApprove_MiniPage", "--template", "mini", "--caption", 'Approve the "order"']) == 0
        sdir = pkg / "Schemas" / "UsrApprove_MiniPage"
        desc = json.loads(read(sdir / "descriptor.json").lstrip("﻿"))["Descriptor"]
        assert desc["Parent"] == {"UId": "ecdcc8ff-272c-4957-9381-7d74ce17e140", "Name": "BaseMiniPageTemplate"}
        assert json.loads(read(sdir / "properties.json").lstrip("﻿"))["Properties"]["Group"] == "MiniPage"
        assert '= MetaData.Schema.HD1 "ecdcc8ff-272c-4957-9381-7d74ce17e140"' in read(sdir / "metadata.json")
        page = PageSchema(pkg, "UsrApprove_MiniPage")
        assert page.validate() == [] and page.resources.get("Caption") == 'Approve the "order"'
        label = page.sections["SCHEMA_VIEW_CONFIG_DIFF"].value[0]
        assert (label["name"], label["values"]["type"], label["values"]["caption"], label["parentName"]) == \
            ("Label", "crt.Label", 'Approve the "order"', "MainContainer")
        codes = {e["code"] for e in page.page_file()[0]["elements"]}
        assert {"SaveButton", "CancelButton", "CloseButton"} <= codes  # the template's buttons a page task completes on
        with contextlib.redirect_stderr(io.StringIO()):
            assert main(["new", str(pkg), "UsrOther_MiniPage", "--template", "mini", "--entity", "UsrOrder"]) == 2
            assert main(["new", str(pkg), "UsrOther_FormPage"]) == 2  # a form page still needs its object
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


# -- S48-T07: replace, add-grid --panel / --before, grid-caption, dotted set-value ------------------------------------ #

def _two_packages() -> tuple[Path, Path]:
    """UsrPkg (the fixture) and an empty UsrRepl beside it in one workspace."""
    pkg = copy()
    repl = pkg.parent / "UsrRepl"
    repl.mkdir()
    desc = read(pkg / "descriptor.json").replace("90ae4ed1-55f1-40c8-b1c1-c22f5beea180", "11111111-2222-4333-8444-555555555555")
    (repl / "descriptor.json").write_text(desc.replace('"UsrPkg"', '"UsrRepl"'), encoding="utf-8")
    return pkg, repl


class FakeSite:
    """The SQL answers of a site holding `bodies` ({package: body}) of one page and its base row `uid`."""

    def __init__(self, uid: str, bodies: dict[str, str]):
        self.uid, self.bodies, self.calls = uid, bodies, []

    def sql(self, query: str) -> list[dict]:
        import base64
        import hashlib
        self.calls.append(query)
        if "generate_series" in query:
            body = self.bodies[re.search(r'"Id" = \'([^\']+)\'', query).group(1)].encode("utf-8")
            return [{"i": "0", "b64": base64.b64encode(body).decode(), "md5": hashlib.md5(body).hexdigest()}]
        if "octet_length" in query:
            return [{"id": pkg, "package": pkg, "manager": "ClientUnitSchemaManager", "modifiedOn": "", "size": "1", "md5": ""} for pkg in self.bodies]
        return [{"uid": self.uid}] if self.uid else []


def test_replace_writes_a_replacing_copy_with_the_base_uid_from_the_workspace_the_catalog_or_the_site():
    from creatio_schemas.page import catalog
    pkg, repl = _two_packages()
    try:
        base_uid = json.loads(read(pkg / "Schemas" / "UsrOrder_FormPage" / "descriptor.json").lstrip("﻿"))["Descriptor"]["UId"]
        with __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
            assert main(["replace", str(repl), "UsrOrder_FormPage", "--cultures", "en-US,uk-UA"]) == 0
        sdir = repl / "Schemas" / "UsrOrder_FormPage"
        desc = json.loads(read(sdir / "descriptor.json").lstrip("﻿"))["Descriptor"]
        assert desc["Parent"] == {"UId": base_uid, "Name": "UsrOrder_FormPage"} and desc["ExtendParent"] is True
        meta = read(sdir / "metadata.json")
        assert f'= MetaData.Schema.HD1 "{base_uid}"' in meta and '= MetaData.Schema.B6 "11111111-2222-4333-8444-555555555555"' in meta
        assert "+ MetaData.Schema.B7 true" in meta
        props = json.loads(read(sdir / "properties.json").lstrip("﻿"))["Properties"]
        assert (props["Group"], props["SchemaType"]) == ("Page", "AngularSchema")
        assert sorted(p.name for p in (repl / "Resources" / "UsrOrder_FormPage.ClientUnit").iterdir()) == ["resource.en-US.xml", "resource.uk-UA.xml"]
        page = PageSchema(repl, "UsrOrder_FormPage")
        assert page.replacing == "UsrOrder_FormPage" and page.validate() == []
        assert set(page.sections) == {"SCHEMA_VIEW_CONFIG_DIFF", "SCHEMA_VIEW_MODEL_CONFIG_DIFF", "SCHEMA_MODEL_CONFIG_DIFF"}
        assert "a replacing copy of UsrOrder_FormPage" in page.describe()
        rc, lines = _audit(repl, "UsrOrder_FormPage")
        assert rc == 0 and "# a replacing copy of UsrOrder_FormPage: the counts cover this layer only" in lines
        # a string on the replacing copy: no `~ B2` order line, the entry goes in before B6 as the designer writes it
        page.add_grid("UsrLines", "UsrOrder", ["UsrName"], master="UsrManager")
        page.save()
        meta = read(sdir / "metadata.json")
        assert meta.index("+ MetaData.Schema.B2 ") < meta.index("= MetaData.Schema.B6") and "~ MetaData.Schema.B2" not in meta
        assert PageSchema(repl, "UsrOrder_FormPage").validate() == []
        # the catalog, then the site; neither: refused
        catalog.BASE_PAGES["UsrAbcBase_FormPage"] = "aaaaaaaa-0000-4000-8000-000000000001"
        try:
            assert PageSchema.create_replacing(repl, "UsrAbcBase_FormPage").descriptor.data["Parent"]["UId"] == "aaaaaaaa-0000-4000-8000-000000000001"
        finally:
            catalog.BASE_PAGES.pop("UsrAbcBase_FormPage")
        site = FakeSite("bbbbbbbb-0000-4000-8000-000000000002", {})
        assert PageSchema.create_replacing(repl, "UsrSite_FormPage", env=site).descriptor.data["Parent"]["UId"] == site.uid
        assert "'UsrSite_FormPage'" in site.calls[0] and '"ExtendParent" = false' in site.calls[0]
        for env, said in ((None, "--env"), (FakeSite("", {}), "not a client schema")):
            try:
                PageSchema.create_replacing(repl, "UsrNowhere_FormPage", env=env)
                raise AssertionError("an unknown page must be refused")
            except ValueError as e:
                assert said in str(e)
        try:
            PageSchema.create_replacing(repl, "UsrOrder_FormPage")
            raise AssertionError("an existing copy must be refused")
        except FileExistsError:
            pass
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


DESIGNER_OPS = """[
\t\t\t{
\t\t\t\t"operation": "insert",
\t\t\t\t"name": "UsrNotesPanel",
\t\t\t\t"values": { "type": "crt.ExpansionPanel", "items": [], "tools": [] },
\t\t\t\t"parentName": "GeneralInfoTab",
\t\t\t\t"propertyName": "items",
\t\t\t\t"index": 1
\t\t\t},
\t\t\t// a commented-out block the designer keeps
\t\t\t{ "operation": "merge", "name": "CloseButton", "values": { "size": "large" } }
\t\t]"""
DESIGNER_ATTRS = """[
\t\t\t{ "operation": "merge", "path": [ "attributes" ], "values": { "UsrName": { "modelConfig": { "path": "PDS.UsrName" } } } }
\t\t]"""


def _designer_page(pkg: Path) -> Path:
    """UsrOrder_FormPage with compact ops in its sections, the way an editor or the designer may leave them (not json.dumps' layout)."""
    path = pkg / "Schemas" / "UsrOrder_FormPage" / "UsrOrder_FormPage.js"
    body = read(path).replace("/**SCHEMA_VIEW_CONFIG_DIFF*/[]", f"/**SCHEMA_VIEW_CONFIG_DIFF*/{DESIGNER_OPS}")
    body = body.replace("/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/[]", f"/**SCHEMA_VIEW_MODEL_CONFIG_DIFF*/{DESIGNER_ATTRS}")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(body)
    return path


def test_add_grid_panel_is_the_designers_detail_and_keeps_every_other_byte():
    import difflib
    pkg = copy()
    try:
        path = _designer_page(pkg)
        before = read(path)
        page = PageSchema(pkg, "UsrOrder_FormPage")
        page.add_grid("UsrLinesList", "UsrOrder", ["UsrName", "UsrStatus"], master="UsrManager", panel="Lines", before="UsrNotesPanel", add_button=True,
                      editable=True)
        page.save()
        after = read(path)
        ops = difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
        assert {op[0] for op in ops} == {"equal", "insert"}, [op for op in ops if op[0] not in ("equal", "insert")]
        page = PageSchema(pkg, "UsrOrder_FormPage")
        panel = page.element("UsrLinesExpansionPanel")
        assert (panel["parentName"], panel["index"], panel["values"]["type"]) == ("GeneralInfoTab", 1, "crt.ExpansionPanel")
        assert panel["values"]["title"] == "#ResourceString(UsrLinesExpansionPanel_title)#"
        assert page.resources.get("LocalizableStrings.UsrLinesExpansionPanel_title.Value", "en-US") == "Lines"
        assert page.element("UsrLinesToolsContainer")["propertyName"] == "tools"
        add, refresh = page.element("UsrLinesAddButton")["values"], page.element("UsrLinesRefreshButton")["values"]
        assert add["clicked"] == {"request": "crt.CreateRecordRequest", "params": {"entityName": "UsrOrder",
                                                                                    "defaultValues": [{"attributeName": "UsrManager", "value": "$Id"}]}}
        assert refresh["clicked"]["params"] == {"config": {"loadType": "reload"}, "dataSourceName": "UsrLinesListDS"}
        grid = page.element("UsrLinesList")
        assert (grid["parentName"], grid["index"]) == ("UsrLinesListContainer", 0)
        assert grid["values"]["features"] == {"editable": {"enable": True, "itemsCreation": False}}
        status = grid["values"]["columns"][1]
        assert status["path"] == "UsrStatus" and status["referenceSchemaName"] == "UsrOrderStatus"
        assert page.dependencies["UsrLinesListDS"] == [{"attributePath": "UsrManager", "relationPath": "PDS.Id"}]
        assert page.attributes["UsrName"] == {"modelConfig": {"path": "PDS.UsrName"}}  # the body's merge op untouched, still read
        assert not [p for p in page.validate() if "ResourceString" in p]
        # without the add button (the CLI: --no-add-button): the tools row has the refresh button only
        page.add_grid("UsrMoreList", "UsrOrder", ["UsrName"], panel="More")
        assert not page.has("UsrMoreAddButton") and page.element("UsrMoreRefreshButton")["index"] == 0
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


def test_add_grid_before_an_element_of_the_replaced_page_reads_the_workspace_or_the_site():
    pkg, repl = _two_packages()
    try:
        _designer_page(pkg)
        PageSchema.create_replacing(repl, "UsrOrder_FormPage")
        page = PageSchema(repl, "UsrOrder_FormPage")
        assert page._place_of("UsrNotesPanel") == ("GeneralInfoTab", 1)  # the base copy in the workspace
        shutil.rmtree(pkg / "Schemas" / "UsrOrder_FormPage")
        page = PageSchema(repl, "UsrOrder_FormPage")
        try:
            page._place_of("UsrNotesPanel")
            raise AssertionError("no copy and no env must be refused")
        except KeyError as e:
            assert "--env" in str(e)
        base = "define(...) /**SCHEMA_VIEW_CONFIG_DIFF*/" + DESIGNER_OPS + "/**SCHEMA_VIEW_CONFIG_DIFF*/"
        site = FakeSite("", {"CrtBase": base, "UsrRepl": "/**SCHEMA_VIEW_CONFIG_DIFF*/[]/**SCHEMA_VIEW_CONFIG_DIFF*/"})
        assert page._place_of("UsrNotesPanel", site) == ("GeneralInfoTab", 1)
        moved = base.replace('"index": 1', '"index": 4')
        try:
            page._place_of("UsrNotesPanel", FakeSite("", {"CrtBase": base, "CrtOther": moved}))
            raise AssertionError("two places must be refused")
        except KeyError as e:
            assert "several places" in str(e) and "CrtOther: GeneralInfoTab[4]" in str(e)
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


def test_grid_caption_writes_the_resource_string_in_each_culture():
    import contextlib
    import io
    pkg = copy()
    try:
        page = PageSchema(pkg, "UsrOrder_FormPage")
        page.add_grid("UsrLines", "UsrOrder", ["UsrName"], literal_captions=True)
        page.save()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert main(["grid-caption", str(pkg), "UsrOrder_FormPage", "UsrLines", "UsrName", "en-US=Line name", "uk-UA=Line"]) == 0
        assert "#ResourceString(UsrLinesDS_UsrName)#" in out.getvalue()
        page = PageSchema(pkg, "UsrOrder_FormPage")
        assert page.element("UsrLines")["values"]["columns"][0]["caption"] == "#ResourceString(UsrLinesDS_UsrName)#"
        assert page.resources.get("LocalizableStrings.UsrLinesDS_UsrName.Value", "en-US") == "Line name"
        assert page.resources.get("LocalizableStrings.UsrLinesDS_UsrName.Value", "uk-UA") == "Line"
        assert "UsrLinesDS_UsrName" in page.own_string_keys() and page.validate() == []
        try:
            page.grid_caption("UsrLines", "UsrNope", {"en-US": "x"})
            raise AssertionError("an unknown column must be refused")
        except KeyError as e:
            assert "UsrLinesDS_UsrName" in str(e)
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


def test_set_value_walks_a_dotted_path_and_merges_into_an_element_of_the_replaced_page():
    pkg, repl = _two_packages()
    try:
        page = PageSchema(pkg, "UsrOrder_FormPage")
        page.add_field("UsrName")
        page.set_value("UsrName", "layoutConfig.colSpan", "2")
        page.set_value("UsrName", "a.b.c", "x")
        values = page.element("UsrName")["values"]
        assert values["layoutConfig"]["colSpan"] == 2 and values["a"] == {"b": {"c": "x"}} and "a.b.c" not in values
        try:
            page.set_value("UsrName", "label.x", "y")  # label is a string
            raise AssertionError("a path through a non-object must be refused")
        except ValueError as e:
            assert "label" in str(e)
        PageSchema.create_replacing(repl, "UsrOrder_FormPage")
        copy_ = PageSchema(repl, "UsrOrder_FormPage")
        copy_.set_value("CloseButton", "size", "large")
        assert copy_.view_config_diff == [{"operation": "merge", "name": "CloseButton", "values": {"size": "large"}}]
        try:
            page.set_value("CloseButton", "size", "large")  # an own page: the element must be its own
            raise AssertionError("an unknown element of an own page must be refused")
        except KeyError:
            pass
    finally:
        shutil.rmtree(pkg.parent, ignore_errors=True)


def test_layout_folds_insert_merge_and_move_of_every_layer_into_the_grid():
    pkg, repl = _two_packages()
    try:
        page = "UsrOrder_FormPage"

        def cell(name, row, col, span=1, op="insert", parent="UsrGrid"):
            return {"operation": op, "name": name, "parentName": parent, "propertyName": "items", "index": 0,
                    "values": {"type": "crt.Input", "layoutConfig": {"column": col, "row": row, "colSpan": span, "rowSpan": 1}}}

        base = [{"operation": "insert", "name": "UsrGrid", "parentName": "SideAreaProfileContainer", "propertyName": "items", "index": 0,
                 "values": {"type": "crt.GridContainer", "columns": ["minmax(32px, 1fr)", "minmax(32px, 1fr)"]}},
                cell("UsrName", 1, 1), cell("UsrAmount", 1, 2), cell("UsrDate", 2, 1)]
        upper = [{"operation": "merge", "name": "UsrDate", "values": {"layoutConfig": {"column": 2, "row": 3}}},
                 {"operation": "move", "name": "UsrAmount", "parentName": "SideAreaProfileContainer", "propertyName": "items", "index": 1},
                 cell("UsrNote", 2, 1, 2)]
        src = pkg / "Schemas" / page
        body = read(src / f"{page}.js")
        assert "/**SCHEMA_VIEW_CONFIG_DIFF*/[]" in body
        (src / f"{page}.js").write_text(body.replace("/**SCHEMA_VIEW_CONFIG_DIFF*/[]", "/**SCHEMA_VIEW_CONFIG_DIFF*/" + json.dumps(base)), encoding="utf-8")
        dst = repl / "Schemas" / page
        shutil.copytree(src, dst)
        desc = json.loads(read(dst / "descriptor.json").lstrip("﻿"))
        desc["Descriptor"].update(ExtendParent=True, UId="22222222-3333-4444-8555-666666666666")
        (dst / "descriptor.json").write_text(json.dumps(desc), encoding="utf-8")
        (dst / f"{page}.js").write_text(body.replace("/**SCHEMA_VIEW_CONFIG_DIFF*/[]", "/**SCHEMA_VIEW_CONFIG_DIFF*/" + json.dumps(upper)), encoding="utf-8")
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert main(["layout", str(repl), page, "--container", "UsrGrid"]) == 0
        assert out.getvalue().splitlines() == [
            f"{page}.UsrGrid over 2 layers (UsrPkg > UsrRepl), 2 columns, the last layer wins",
            "  row 1: 1 UsrName | 2 free", "  row 2: 1-2 UsrNote", "  row 3: 1 free | 2 UsrDate",
            "  UsrName  row 1 col 1 span 1x1  (placed last in UsrPkg)", "  UsrNote  row 2 col 1 span 2x1  (placed last in UsrRepl)",
            "  UsrDate  row 3 col 2 span 1x1  (placed last in UsrRepl)"], out.getvalue()
    finally:
        shutil.rmtree(pkg.parent.parent, ignore_errors=True)


if __name__ == "__main__":
    for fn in [v for k, v in list(globals().items()) if k.startswith("test_")]:
        fn()
        print("ok", fn.__name__)
