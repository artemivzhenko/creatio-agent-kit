"""Checks for the Classic UI tools:  python tests/test_classicui_tools.py  (the fixture follows the shapes of the platform's pages)."""

import contextlib
import difflib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent))

from classicui import main  # noqa: E402
from creatio_schemas.classicui import ClassicSchema  # noqa: E402
from creatio_schemas.diff import SchemaDiff  # noqa: E402
from creatio_schemas.files import CRLF, write_text  # noqa: E402
from creatio_schemas.text import mask  # noqa: E402

FIXTURES = HERE / "fixtures" / "UsrPkg"


def read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def test_round_trip_is_byte_identical():
    for name in ("UsrOrderPage", "UsrOrderSection"):
        s = ClassicSchema(FIXTURES, name)
        for path, (text, bom) in s.files().items():
            assert read(path) == ("﻿" if bom else "") + text, path
        s.describe()
        assert s.diff() == "", name


def test_header_and_sections():
    page = ClassicSchema(FIXTURES, "UsrOrderPage")
    assert page.summary() == "edit page of UsrOrder, 14 diff operations, 9 methods, 3 details"
    assert page.kind == "edit page" and page.parent == "BasePageV2" and page.module_name == "UsrOrderPage"
    assert page.dependencies == ["BusinessRuleModule", "ConfigurationConstants", "UsrOrderPageResources"]
    assert list(page.sections) == ["entitySchemaName", "messages", "mixins", "attributes", "details", "modules", "businessRules", "methods",
                                   "diff", "rules"]
    assert page.messages() == {"UsrOrderTotalChanged": {"mode": "Terrasoft.MessageMode.BROADCAST", "direction": "Terrasoft.MessageDirectionType.PUBLISH"}}
    assert page.mixins() == {"UsrPrintMixin": "Terrasoft.UsrPrintMixin"}
    assert page.attributes()["UsrTotal"] == {"dataValueType": "Terrasoft.DataValueType.FLOAT", "dependencies": "[...]"}
    assert page.details()["Files"] == {"schemaName": "FileDetailV2", "entitySchemaName": "UsrOrderFile", "filter": "{...}"}
    assert page.entries("modules") == {} and page.entries("nope") == {}
    text = page.describe()
    assert "sections: entitySchemaName, messages 1, mixins 1, attributes 2, details 3, modules 0, businessRules 0, methods 9, diff 14, rules 1" in text
    # S30-T04: the summary counts the operations and names the parents and the methods; the names of the elements are `diff op=<operation>`
    assert "diff: insert 11 (under UsrInfoContainer 3, UsrInfoTab 3, LeftContainer 2, ...), merge 1, move 1 (under Header 1), remove 1" in text
    assert "UsrNumber" not in text.split("diff:")[1].split("\n")[0] and "methods: onEntityInitialized, recalculateTotal," in text
    section = ClassicSchema(FIXTURES, "UsrOrderSection")
    assert section.summary() == "section of UsrOrder, 2 diff operations, 3 methods, 0 details" and section.kind == "section"


def test_diff_operations_and_elements():
    ops = ClassicSchema(FIXTURES, "UsrOrderPage").diff_operations()
    assert [op["operation"] for op in ops].count("insert") == 11
    amount = next(op for op in ops if op["name"] == "UsrAmount")  # the name only in values
    assert amount["parentName"] == "UsrInfoContainer" and amount["index"] is None and amount["values"] == ["name", "bindTo", "layout"]
    first = ops[0]
    assert first["name"] == "UsrNumber" and first["index"] == "0" and first["propertyName"] == "items" and first["line"] == 134
    assert next(op for op in ops if op["name"] == "UsrPrintButton")["handlers"] == {"click": "onPrintClick"}
    remove = ops[-1]
    assert remove == dict(remove, operation="remove", name="NotesAndFilesTab", parentName=None, values=[])
    status = ClassicSchema(FIXTURES, "UsrOrderPage").element("UsrStatus")
    assert [op["operation"] for op in status] == ["insert", "move"] and '"parentName": "Header"' in status[1]["source"]
    try:
        ClassicSchema(FIXTURES, "UsrOrderPage").element("Nope")
    except KeyError:
        pass
    else:
        raise AssertionError("an unknown element must raise")


def test_methods_survive_braces_in_strings_comments_and_regexes():
    page = ClassicSchema(FIXTURES, "UsrOrderPage")
    names = [m["name"] for m in page.methods()]
    assert names == ["onEntityInitialized", "recalculateTotal", "isNumberValid", "setValidationConfig", "validateNumber", "onPrintClick",
                     "isPrintVisible", "getStatusCaption", "onUsrDiscountChange"]
    assert page.method("isNumberValid").endswith('return /^ORD-\\d{4}["\']?$/.test(value || "");\r\n\t\t\t\t}')
    assert page.method("recalculateTotal").count("\n") == 5 and page.method("onUsrDiscountChange") == "onUsrDiscountChange: Terrasoft.emptyFn"
    assert page.methods()[0] == {"name": "onEntityInitialized", "line": 66, "size": 6}
    try:
        page.method("nope")
    except KeyError as e:
        assert "onPrintClick" in str(e)
    else:
        raise AssertionError("an unknown method must raise")
    found = page.find("usrtotal")
    assert (80, "methods.recalculateTotal", 'this.set("UsrTotal", amount - discount);') in found and found[0][1] == "attributes"
    # the mask: a regex literal is blanked, a division is not
    assert mask('a = /[{"]/g; b = c / 2;') == 'a = /    /g; b = c / 2;'
    assert mask("x = `a{${b}`;\n// }") == "x = `      `;\n    "


def test_validate_warns_and_reads_workspace_parents():
    problems = ClassicSchema(FIXTURES, "UsrOrderPage").validate()
    assert problems == ["warning: parentName not declared here or in the workspace parents (expected from BasePageV2): "
                        "Header, LeftContainer, ProfileContainer, Tabs",
                        "warning: handlers bound to methods not defined here or in the workspace parents (expected from BasePageV2): "
                        "click -> onCloseClick"]
    assert ClassicSchema(FIXTURES, "UsrOrderPage").errors() == []
    tmp = Path(tempfile.mkdtemp()) / "packages"
    shutil.copytree(FIXTURES, tmp / "UsrPkg")
    try:
        child = tmp / "UsrPkg" / "Schemas" / "UsrOrderMiniPage"
        shutil.copytree(tmp / "UsrPkg" / "Schemas" / "UsrOrderSection", child)
        write_text(child / "descriptor.json", read(child / "descriptor.json").replace("UsrOrderSection", "UsrOrderMiniPage")
                   .replace("BaseSectionV2", "UsrOrderPage"), False)
        (child / "UsrOrderSection.js").unlink()
        write_text(child / "UsrOrderMiniPage.js", CRLF.join([
            'define("UsrOrderMiniPage", [], function() {', "\treturn {", "\t\tdiff: [",
            '\t\t\t{"operation": "insert", "parentName": "UsrInfoContainer", "propertyName": "items", "values": {"name": "UsrNote"}},',
            '\t\t\t{"operation": "merge", "name": "UsrPrintButton", "values": {"click": {"bindTo": "onPrintClick"}}},',
            '\t\t\t{"operation": "remove", "values": {}}', "\t\t]", "\t};", "});", ""]), False)
        mini = ClassicSchema(tmp / "UsrPkg", "UsrOrderMiniPage")
        # properties.json (copied from the section) decides the kind before the parent's name does
        assert mini.kind == "section" and mini.validate() == ["warning: diff item at line 6: remove without a name"]
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


def test_bodies_without_a_literal_object():
    tmp = Path(tempfile.mkdtemp()) / "packages"
    shutil.copytree(FIXTURES, tmp / "UsrPkg")
    try:
        js = tmp / "UsrPkg" / "Schemas" / "UsrOrderSection" / "UsrOrderSection.js"
        write_text(js, '{"Settings": {"a": 1}}', False)  # a mobile settings file: JSON, no define
        s = ClassicSchema(tmp / "UsrPkg", "UsrOrderSection")
        assert s.summary() == "no define() module (1 lines)" and s.sections == {} and s.methods() == [] and s.diff_operations() == []
        assert not ClassicSchema.is_classic(tmp / "UsrPkg", "UsrOrderSection") and ClassicSchema.is_classic(FIXTURES, "UsrOrderPage")
        write_text(js, 'define("UsrOrderSection", ["Base"], function(Base) {\r\n\treturn Ext.apply(Base, {});\r\n});', False)
        s = ClassicSchema(tmp / "UsrPkg", "UsrOrderSection")
        assert s.module_name == "UsrOrderSection" and s.dependencies == ["Base"] and s.sections == {}
        assert s.summary() == "section, 0 diff operations, 0 methods, 0 details"
        s.schema_type = None  # no properties.json: the parent's name decides
        assert s.kind == "section"
        s.descriptor.set("Parent", {"UId": "d3cc497c-f286-4f13-99c1-751c468733c0", "Name": "BaseModule"})
        assert s.kind == "client schema"
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


def test_cli():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["inspect", str(FIXTURES), "UsrOrderPage"]) == 0
        assert main(["validate", str(FIXTURES), "UsrOrderSection"]) == 0
        assert main(["methods", str(FIXTURES), "UsrOrderSection"]) == 0
        assert main(["method", str(FIXTURES), "UsrOrderSection", "onTotalChanged"]) == 0
        assert main(["diff", str(FIXTURES), "UsrOrderPage", "--op", "insert", "--parent", "UsrInfoContainer"]) == 0
        assert main(["method", str(FIXTURES), "UsrOrderSection", "nope"]) == 2
    text = out.getvalue()
    assert "edit page of UsrOrder" in text and "onRecalculateClick" in text and "this.reloadGridData();" in text
    assert "insert  UsrAmount in UsrInfoContainer.items  line" in text and "insert  UsrTotal in UsrInfoContainer.items[2]" in text
    assert "UsrNumber" not in text.split("UsrInfoContainer.items")[-1]


@contextlib.contextmanager
def workspace():
    """A temp packages folder with a copy of the fixture (UsrPkg) and an empty second package (UsrPkg2)."""
    tmp = Path(tempfile.mkdtemp()) / "packages"
    shutil.copytree(FIXTURES, tmp / "UsrPkg")
    (tmp / "UsrPkg2").mkdir()
    desc = read(FIXTURES / "descriptor.json").lstrip("﻿")
    uid = json.loads(desc)["Descriptor"]["UId"]
    write_text(tmp / "UsrPkg2" / "descriptor.json", desc.replace(uid, "c0ffee00-0000-4000-8000-000000000002").replace('"UsrPkg"', '"UsrPkg2"'), True)
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


def on_disk(s) -> bool:
    return all(read(path) == ("﻿" if bom else "") + text for path, (text, bom) in s.files().items())


def refused(fn, kind, text=""):
    try:
        fn()
    except kind as e:
        assert text in str(e), (text, str(e))
        return
    raise AssertionError(f"expected {kind.__name__}")


RULE = "6e0f3b9a-1c2d-4e5f-8a9b-0c1d2e3f4a5b"


def test_body_writers_splice_only_their_span():
    with workspace() as ws:
        s = ClassicSchema(ws / "UsrPkg", "UsrOrderPage")
        before, ops, methods = s.body, s.diff_operations(), [m["name"] for m in s.methods()]
        s.set_rule(RULE, enabled=False, column="UsrStatus")
        s.set_rule(RULE, removed=True)  # the second call edits the override in place
        s.add_mixin("UsrXMixin")
        s.add_mixin("UsrXMixin", "Terrasoft.UsrXMixinV2")  # existing: value replaced, dependency not doubled
        s.add_method("usrHello", "usrHello: function() {\n\treturn 1;\n}")
        s.replace_method("onUsrDiscountChange", "function() {\n\tthis.recalculateTotal();\n}")
        s.set_message("UsrPing", "ptp", "publish")
        s.set_message("UsrOrderTotalChanged", "broadcast", "bidirectional")
        s.save()
        s = ClassicSchema(ws / "UsrPkg", "UsrOrderPage")
        assert on_disk(s) and "\n" not in s.body.replace("\r\n", "")  # the body's CRLF everywhere
        assert s.mixins() == {"UsrPrintMixin": "Terrasoft.UsrPrintMixin", "UsrXMixin": "Terrasoft.UsrXMixinV2"}
        assert s.dependencies.count("UsrXMixin") == 1
        assert [m["name"] for m in s.methods()] == methods + ["usrHello"] and "this.recalculateTotal();" in s.method("onUsrDiscountChange")
        assert s.messages()["UsrPing"] == {"mode": "Terrasoft.MessageMode.PTP", "direction": "Terrasoft.MessageDirectionType.PUBLISH"}
        assert s.messages()["UsrOrderTotalChanged"]["direction"] == "Terrasoft.MessageDirectionType.BIDIRECTIONAL"
        assert s.diff_operations()[0]["source"] == ops[0]["source"] and len(s.diff_operations()) == len(ops)
        assert s.entries("businessRules") == {"UsrStatus": {RULE: "{...}"}}
        assert '\t\t\t\t\t\t"enabled": false,\r\n\t\t\t\t\t\t"removed": true\r\n' in s.body
        removed = [ln for ln in difflib.ndiff(before.splitlines(), s.body.splitlines()) if ln.startswith("- ")]
        assert removed == ['- define("UsrOrderPage", ["BusinessRuleModule", "ConfigurationConstants", "UsrOrderPageResources"],',
                           '- \t\t\t\tUsrPrintMixin: "Terrasoft.UsrPrintMixin"',
                           "- \t\t\tbusinessRules: /**SCHEMA_BUSINESS_RULES*/{}/**SCHEMA_BUSINESS_RULES*/,",
                           "- \t\t\t\tonUsrDiscountChange: Terrasoft.emptyFn"], removed  # every other line is kept
        refused(lambda: s.add_method("usrHello", "function() {}"), KeyError, "replace_method")
        refused(lambda: s.replace_method("nope", "function() {}"), KeyError)
        refused(lambda: s.set_message("X", "loud", "publish"), ValueError)
        refused(lambda: s.set_rule(RULE), ValueError)
        refused(lambda: s.set_rule("00000000-0000-0000-0000-00000000000f", enabled=False), ValueError, "name its column")
        bare = ClassicSchema(ws / "UsrPkg", "UsrOrderSection")
        bare._deps_at = None
        refused(lambda: bare.add_dependency("UsrX"), ValueError, "dependency list")
        bare._return_at = None
        refused(lambda: bare._section("mixins"), ValueError, "returned object")


def item_uid(s, key):
    return next(i["UId"] for i in SchemaDiff(s.metadata_text).added_items("MetaData.Schema.B2") if i["A2"] == key)


def test_strings_go_to_the_diff_metadata_and_resources():
    with workspace() as ws:
        s = ClassicSchema(ws / "UsrPkg", "UsrOrderPage")
        old = s.metadata_text
        s.add_string("UsrHello", {"en-US": "Hello"})
        s.add_string("UsrHello", {"en-US": "Hello again"})  # once in the metadata
        s.save()
        s = ClassicSchema(ws / "UsrPkg", "UsrOrderPage")
        assert s.metadata_text.startswith(old + "\r\n+ MetaData.Schema.B2 {") and s.metadata_text.count("UsrHello") == 1
        item = json.loads(s.metadata_text.split("+ MetaData.Schema.B2 ", 1)[1])
        assert item["A3"] == item["A4"] == s.descriptor.data["UId"] and item["A5"] == "7f0d5a7e-2d0c-4c1e-9a7e-5b1c3f2a9d01"
        assert s.resources.get("LocalizableStrings.UsrHello.Value") == "Hello again" and on_disk(s)
        # the shape of real replacing schemas: own items, parent strings rebound, the order; a new item goes before ~
        meta = CRLF.join(['= MetaData.Schema.UId "11111111-0000-0000-0000-000000000001"', '= MetaData.Schema.A5 "a5a5a5a5-0000-0000-0000-000000000001"',
                          '+ MetaData.Schema.B2 {\r\n  "UId": "22222222-0000-0000-0000-000000000001",\r\n  "A2": "UsrOld"\r\n}',
                          '= MetaData.Schema.B2.["33333333-0000-0000-0000-000000000001"].A4 "11111111-0000-0000-0000-000000000001"',
                          '~ MetaData.Schema.B2 [\r\n  "33333333-0000-0000-0000-000000000001",\r\n  "22222222-0000-0000-0000-000000000001"\r\n]',
                          '= MetaData.Schema.B6 "b6b6b6b6-0000-0000-0000-000000000001"', "+ MetaData.Schema.B7 true"])
        s.metadata_text = meta
        s.add_string("UsrNew", {"en-US": "New"})
        head, tail = s.metadata_text.split("~ MetaData.Schema.B2")
        assert head.startswith(meta.split("~ MetaData.Schema.B2")[0]) and '"A2": "UsrNew"' in head
        assert tail.endswith('= MetaData.Schema.B6 "b6b6b6b6-0000-0000-0000-000000000001"\r\n+ MetaData.Schema.B7 true')
        assert item_uid(s, "UsrNew") in tail and json.loads(head.split("+ MetaData.Schema.B2 ")[-1])["A5"] == "a5a5a5a5-0000-0000-0000-000000000001"
        full = ClassicSchema(ws / "UsrPkg", "UsrOrderPage")
        full.metadata_text = '{"MetaData": {}}'
        refused(lambda: full.add_string("UsrX", {"en-US": "x"}), ValueError, "diff form")
        refused(lambda: s.add_string("bad key", {"en-US": "x"}), ValueError)
        refused(lambda: s.add_string("UsrY", {}), ValueError)


def test_create_replacing_and_inherited_rule():
    with workspace() as ws:
        page = ClassicSchema(ws / "UsrPkg", "UsrOrderPage")
        page.set_rule(RULE, enabled=True, column="UsrStatus")
        page.save()
        r = ClassicSchema.create_replacing(ws / "UsrPkg2", "UsrOrderPage", ["en-US", "ru-RU"])
        assert r.replacing and r.parent == "UsrOrderPage" and r.descriptor.data["Parent"]["UId"] == page.descriptor.data["UId"]
        meta = r.metadata_text.split("\r\n")
        assert [ln.split(" ")[1] for ln in meta] == ["MetaData.Schema." + k for k in ("UId", "A5", "B6", "B8", "B7", "HD1")]
        assert '"c0ffee00-0000-4000-8000-000000000002"' in meta[2] and not r.metadata_text.endswith("\n")
        assert r.body.startswith('define("UsrOrderPage", [], function() {\n\treturn {\n\t\tattributes: {},')
        assert r.sections.keys() >= {"businessRules", "diff", "methods", "mixins", "messages"}
        assert r.resources.get("Caption") == "Order edit page" and set(r.resources.cultures) == {"en-US", "ru-RU"} and on_disk(r)
        assert read(r.descriptor.path).startswith("﻿") and '"ExtendParent": true' in r.descriptor.text
        r.set_rule(RULE, enabled=False)  # only the parent has it: copied whole from the workspace parent, then disabled
        r.save()
        r = ClassicSchema(ws / "UsrPkg2", "UsrOrderPage")
        assert r.entries("businessRules") == {"UsrStatus": {RULE: "{...}"}} and r.body.count('"enabled"') == 1 and '"enabled": false' in r.body
        assert '\t\t\t\t"' + RULE + '": {\n\t\t\t\t\t"uId"' in r.body  # the parent's lines re-indented to this body
        assert r.diff_against_parent().startswith("--- UsrPkg/UsrOrderPage.js\n+++ UsrPkg2/UsrOrderPage.js")
        c = ClassicSchema.create_replacing(ws / "UsrPkg2", "ContactPageV2", parent_uid="d3cc497c-0000-4000-8000-000000000009", entity="Contact")
        assert '\t\tentitySchemaName: "Contact",\n' in c.body and c.entity == "Contact" and c.resources.cultures.keys() == {"en-US", "ru-RU"}  # the package's cultures
        assert c.diff_against_parent() is None
        refused(lambda: ClassicSchema.create_replacing(ws / "UsrPkg2", "AccountPageV2"), ValueError, "SysSchema")
        refused(lambda: ClassicSchema.create_replacing(ws / "UsrPkg2", "ContactPageV2", parent_uid="x"), FileExistsError)
        refused(lambda: ClassicSchema.create_replacing(ws / "UsrPkg2", "bad name", parent_uid="x"), ValueError, "valid")


def test_adopt_rebinds_the_pulled_copy():
    with workspace() as ws:
        pulled = ws.parent / "pulled" / "Custom"
        shutil.copytree(FIXTURES, pulled)
        src = ClassicSchema(pulled, "UsrOrderSection")
        old_uid = src.descriptor.data["UId"]
        s = ClassicSchema.adopt(ws / "UsrPkg2", "UsrOrderSection", pulled)
        assert s.descriptor.data["UId"] != old_uid and old_uid not in s.metadata_text and s.descriptor.data["UId"] in s.metadata_text
        assert '= MetaData.Schema.A5 "c0ffee00-0000-4000-8000-000000000002"' in s.metadata_text  # UsrPkg2 has no schemas: its UId
        assert s.body == src.body and s.resources.cultures == src.resources.cultures
        s2 = ClassicSchema.adopt(ws / "UsrPkg2", "UsrOrderPage", pulled / "Schemas" / "UsrOrderPage")  # the schema folder itself
        assert s2.name == "UsrOrderPage" and s2.diff_against_parent() is None  # BasePageV2 is not in the workspace
        refused(lambda: ClassicSchema.adopt(ws / "UsrPkg2", "UsrOrderSection", pulled), FileExistsError)
        refused(lambda: ClassicSchema.adopt(ws / "UsrPkg2", "UsrNope", pulled), FileNotFoundError)
        obj = pulled / "Schemas" / "UsrObj"
        obj.mkdir()
        write_text(obj / "descriptor.json", '{"Descriptor": {"UId": "x", "Name": "UsrObj", "ManagerName": "EntitySchemaManager"}}', True)
        write_text(obj / "metadata.json", "{}", True)
        refused(lambda: ClassicSchema.adopt(ws / "UsrPkg2", "UsrObj", pulled), ValueError, "client schemas")


def test_create_module_and_mixin():
    with workspace() as ws:
        m = ClassicSchema.create_module(ws / "UsrPkg2", "UsrXMixin", mixin=True)
        assert m.kind == "module" and m.module_name == "UsrXMixin" and ClassicSchema.is_classic(ws / "UsrPkg2", "UsrXMixin") and on_disk(m)
        assert 'Ext.define("Terrasoft.configuration.mixins.UsrXMixin", {' in m.body and 'alternateClassName: "Terrasoft.UsrXMixin"' in m.body
        meta = json.loads(read(m.dir / "metadata.json").lstrip("﻿"))["MetaData"]["Schema"]
        assert meta["HD1"] == "50e3acc0-26fc-4237-a095-849a1d534bd3" and meta["HD4"] == 1 and meta["B6"] == "c0ffee00-0000-4000-8000-000000000002"
        assert read(m.dir / "UsrXMixin.less") == " " and m.resources.get("Caption") == "UsrXMixin"
        plain = ClassicSchema.create_module(ws / "UsrPkg2", "UsrHelpers", caption="Helpers")
        assert plain.body == 'define("UsrHelpers", [], function() {\n\treturn {};\n});\n' and plain.resources.get("Caption") == "Helpers"
        refused(lambda: ClassicSchema.create_module(ws / "UsrPkg2", "UsrOrderPage"), FileExistsError)


def test_writer_cli():
    with workspace() as ws:
        pkg = str(ws / "UsrPkg")
        method = ws.parent / "m.js"
        method.write_text("function() {\n\treturn 2;\n}", encoding="utf-8")
        body = ws / "UsrPkg" / "Schemas" / "UsrOrderPage" / "UsrOrderPage.js"
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            before = read(body)
            assert main(["add-mixin", pkg, "UsrOrderPage", "UsrXMixin", "--dry-run"]) == 0
            assert read(body) == before  # dry run
            assert main(["add-mixin", pkg, "UsrOrderPage", "UsrXMixin"]) == 0
            assert main(["add-string", pkg, "UsrOrderPage", "UsrHello", "en-US=Hello"]) == 0
            assert main(["add-string", pkg, "UsrOrderPage", "UsrHello", "Hello"]) == 2
            assert main(["set-rule", pkg, "UsrOrderPage", RULE, "--enabled", "false", "--column", "UsrStatus"]) == 0
            assert main(["set-rule", pkg, "UsrOrderPage", RULE, "--removed", "maybe"]) == 2
            assert main(["add-method", pkg, "UsrOrderPage", "usrTwo", "--file", str(method)]) == 0
            assert main(["add-method", pkg, "UsrOrderPage", "usrTwo", "--file", str(method), "--replace"]) == 0
            assert main(["set-message", pkg, "UsrOrderPage", "UsrPing", "--mode", "PTP", "--direction", "SUBSCRIBE"]) == 0
            assert main(["replace", str(ws / "UsrPkg2"), "UsrOrderPage", "--cultures", "en-US"]) == 0
            assert main(["replace", str(ws / "UsrPkg2"), "AccountPageV2"]) == 2
            assert main(["adopt", str(ws / "UsrPkg2"), "UsrOrderSection", "--from", str(FIXTURES)]) == 0
        text = out.getvalue()
        s = ClassicSchema(ws / "UsrPkg", "UsrOrderPage")
        assert "UsrXMixin" in s.mixins() and "usrTwo" in [m["name"] for m in s.methods()] and "UsrPing" in s.messages()
        assert "return 2;" in s.method("usrTwo") and s.resources.get("LocalizableStrings.UsrHello.Value") == "Hello"
        assert "created UsrOrderPage replacing UsrOrderPage" in text and "Schemas/UsrOrderPage/metadata.json" in text
        assert "adopted UsrOrderSection into UsrPkg2" in text and "(the body of BaseSectionV2 is not in the workspace" in text


def test_where_and_map_read_the_diff_with_captions():
    from creatio_schemas.describe import QueryError, describe_item
    from creatio_schemas.describe.sections import shown_on

    tmp = Path(tempfile.mkdtemp())
    try:
        pkg = tmp / "UsrPkg"
        shutil.copytree(FIXTURES, pkg)
        shutil.copytree(HERE.parent.parent / "objects" / "tests" / "fixtures" / "UsrPkg", tmp / "UsrObjPkg")  # UsrOrder with captions
        status = describe_item(pkg, "UsrOrderPage", "where UsrStatus").splitlines()
        assert status == ["UsrStatus 'Status'  ENUM  bindTo UsrStatus -> UsrOrder.UsrStatus 'Status'", "  in Header (row 1, col 0)",
                          "  layer: added in UsrPkg"], status  # the move wins over the insert's parent
        amount = describe_item(pkg, "UsrOrderPage", "where UsrAmount").splitlines()
        assert amount[0] == "UsrAmount 'Amount'  field  bindTo UsrAmount -> UsrOrder.UsrAmount 'Amount'", amount
        assert amount[1] == "  in Tabs > UsrInfoTab 'Order info' > UsrInfoContainer (row 0, col 0)", amount  # the chain with the tab's caption
        detail = describe_item(pkg, "UsrOrderPage", "where UsrOrderProductDetail").splitlines()
        assert detail[1] == "  detail UsrOrderProductDetailV2 of UsrOrderProduct filtered by UsrOrderProduct.UsrOrder = Id", detail
        inherited = describe_item(pkg, "UsrOrderPage", "where ESNTab").splitlines()  # only merged here
        assert inherited == ["ESNTab (caption not in workspace)", "  layer: merge in UsrPkg, inherited from BasePageV2"], inherited
        try:
            describe_item(pkg, "UsrOrderPage", "where UsrStatu")
            raise AssertionError("no error")
        except QueryError as e:
            assert str(e).startswith("no element UsrStatu in the diff of UsrOrderPage; closest: UsrStatus, UsrTotal"), e

        tree = describe_item(pkg, "UsrOrderPage", "map").splitlines()
        assert tree[:2] == ["ProfileContainer (parent page)", "  UsrNumber  field"], tree
        tab = describe_item(pkg, "UsrOrderPage", "map tab=UsrInfoTab").splitlines()
        assert tab == ["UsrInfoTab 'Order info'", "  UsrInfoContainer  GRID_LAYOUT", "    UsrAmount 'Amount'  field", "    UsrDiscount  field",
                       "    UsrTotal  field",
                       "  UsrOrderProductDetail  DETAIL  detail UsrOrderProductDetailV2 of UsrOrderProduct filtered by UsrOrderProduct.UsrOrder = Id",
                       "  Files  DETAIL  detail FileDetailV2 of UsrOrderFile filtered by UsrOrderFile.UsrOrder = Id"], tab  # cells by layout
        assert "map" in describe_item(pkg, "UsrOrderPage", "topics") and "where" in describe_item(pkg, "UsrOrderPage", "topics")

        # the page and the section without a name; a detail schema names the page that shows it
        assert describe_item(pkg, "UsrOrderPage", "where").startswith("opens from: not registered in this workspace")
        assert describe_item(pkg, "UsrOrderSection", "where") == "section of UsrOrder"
        assert shown_on(pkg, "UsrOrderProductDetailV2") == [
            "shown on UsrOrderPage as UsrOrderProductDetail, of UsrOrderProduct filtered by UsrOrderProduct.UsrOrder = Id"]
        assert shown_on(pkg, "UsrNoDetailV2") == ["shown on no page of this workspace"]

        # a column the workspace does not caption: the platform install's caption (S31-T09), read from the store's platform_captions
        from creatio_schemas.describe import store
        from creatio_schemas.describe.index import index_path
        assert describe_item(pkg, "UsrOrderPage", "where UsrNumber").splitlines()[0].endswith("UsrOrder.UsrNumber (caption not in workspace)")
        con = store.connect(index_path(pkg))
        con.execute("insert into platform_captions values ('CrtBase', 'UsrOrder', 'Columns.UsrNumber.Caption', 'en-US', 'Number')")
        con.commit()
        con.close()
        assert describe_item(pkg, "UsrOrderPage", "where UsrNumber").splitlines()[0].endswith("UsrOrder.UsrNumber 'Number' (CrtBase)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _layered(root: Path) -> Path:
    """packages/UsrA (own UsrOrderPage) <- UsrB <- UsrC (replacing copies), and UsrOtherPage in UsrC calling into it."""
    bodies = {
        "UsrA": "define('UsrOrderPage', [], function() {\n\treturn {\n\t\tmethods: {\n\t\t\tinit: function() {\n\t\t\t\tthis.callParent(arguments);\n"
                "\t\t\t},\n\t\t\tonSave: function() {\n\t\t\t\treturn true;\n\t\t\t}\n\t\t}\n\t};\n});\n",
        "UsrB": "define('UsrOrderPage', [], function() {\n\treturn {\n\t\tmethods: {\n\t\t\tinit: function() {\n\t\t\t\tthis.callParent(arguments);\n"
                "\t\t\t\tthis.onSave();\n\t\t\t}\n\t\t}\n\t};\n});\n",
        "UsrC": "define('UsrOrderPage', [], function() {\n\treturn {\n\t\tattributes: {\n\t\t\t\"UsrFlag\": {dataValueType: 1}\n\t\t},\n"
                "\t\tmessages: {\n\t\t\t\"UsrSaved\": {mode: 1}\n\t\t},\n\t\tmethods: {\n\t\t\tinit: function() {\n\t\t\t\tthis.set(\"UsrFlag\", true);\n"
                "\t\t\t}\n\t\t}\n\t};\n});\n",
    }
    deps = {"UsrA": [], "UsrB": ["UsrA"], "UsrC": ["UsrB"]}
    for n, (pkg, body) in enumerate(bodies.items()):
        p = root / "packages" / pkg
        (p / "Schemas" / "UsrOrderPage").mkdir(parents=True)
        (p / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": pkg, "UId": f"00000000-0000-0000-0000-00000000000{n}",
                                                                     "DependsOn": [{"Name": d} for d in deps[pkg]]}}), encoding="utf-8")
        d = p / "Schemas" / "UsrOrderPage"
        (d / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": f"10000000-0000-0000-0000-00000000000{n}", "Name": "UsrOrderPage",
                                                                     "ManagerName": "ClientUnitSchemaManager", "ExtendParent": pkg != "UsrA",
                                                                     "Parent": {"Name": "UsrOrderPage" if pkg != "UsrA" else "BasePageV2"}}}),
                                       encoding="utf-8")
        (d / "metadata.json").write_text('{"MetaData": {}}', encoding="utf-8")
        (d / "UsrOrderPage.js").write_text(body, encoding="utf-8")
    other = root / "packages" / "UsrC" / "Schemas" / "UsrOtherPage"
    other.mkdir()
    (other / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": "20000000-0000-0000-0000-000000000000", "Name": "UsrOtherPage",
                                                                     "ManagerName": "ClientUnitSchemaManager"}}), encoding="utf-8")
    (other / "metadata.json").write_text('{"MetaData": {}}', encoding="utf-8")
    (other / "UsrOtherPage.js").write_text("define('UsrOtherPage', [], function() {\n\treturn {\n\t\tmethods: {\n\t\t\trun: function(page) {\n"
                                           "\t\t\t\t// this.onSave( in a comment does not count\n\t\t\t\tpage.onSave();\n\t\t\t}\n\t\t}\n\t};\n});\n", encoding="utf-8")
    return root / "packages" / "UsrC"


def test_a_method_in_every_layer_its_callers_and_the_outline():
    from creatio_schemas.describe import QueryError, describe_item

    tmp = Path(tempfile.mkdtemp())
    try:
        top = _layered(tmp)
        out = describe_item(top, "UsrOrderPage", "method init").split("\n")
        assert out[:4] == ["UsrOrderPage.init: 3 of 3 layers define it, applied first to last (the last one runs first)",
                           "  UsrA: line 4, 3 lines, callParent", "  UsrB: line 4, 4 lines, callParent",
                           "  UsrC: line 10, 3 lines, no callParent: the layers below do not run"], out
        assert "--- UsrB line 4 ---" in out and out[out.index("--- UsrC line 10 ---") + 1].startswith("init: function") and "UsrFlag" in out[-2]
        save = describe_item(top, "UsrOrderPage", "method onSave").split("\n")
        assert save[:4] == ["UsrOrderPage.onSave: 1 of 3 layers define it, applied first to last (the last one runs first)",
                            "  UsrA: line 7, 3 lines, no callParent: the layers below do not run", "  UsrB: -", "  UsrC: -"], save
        try:
            describe_item(top, "UsrOrderPage", "method nope")
            raise AssertionError("no error")
        except QueryError as e:
            assert str(e).startswith("no method nope in any layer of UsrOrderPage (UsrA, UsrB, UsrC)"), e
        assert describe_item(top, "UsrOrderPage", "callers onSave").splitlines() == [
            "UsrB/UsrOrderPage.js:6  this.onSave();", "UsrC/UsrOtherPage.js:6  page.onSave();"]  # not the comment, not the definition
        assert describe_item(top, "UsrOrderPage", "callers nothing") == "nothing calls nothing in the workspace"
        assert describe_item(top, "UsrOrderPage", "outline").splitlines() == [
            "attributes (1), line 3:", "  UsrFlag                                  line 4", "messages (1), line 6:",
            "  UsrSaved                                 line 7", "methods (1), line 9:", "  init                                     line 10"]
        assert describe_item(top, "UsrOtherPage", "method run").startswith("run: function")  # one copy: the body, as always

        # env=: the site's layers, their bodies from the site; a layer only on the site, one not pushed yet
        from creatio_schemas.classicui.methods import method_lines
        from creatio_schemas.classicui import ClassicSchema
        site_custom = "define('UsrOrderPage', [], function() {\n\treturn {\n\t\tmethods: {\n\t\t\tinit: function() {\n\t\t\t\tthis.callParent(arguments);\n\t\t\t}\n\t\t}\n\t};\n});\n"

        class Site:
            def sql(self, text):
                if '"SysPackage" where "Name" in' in text:
                    return [{"package": "UsrA", "level": "1"}, {"package": "UsrB", "level": "2"}, {"package": "Custom", "level": "9"}]
                rows = [("UsrA", "false", (top.parent / "UsrA" / "Schemas" / "UsrOrderPage" / "UsrOrderPage.js").read_text(encoding="utf-8"), "2"),
                        ("UsrB", "true", "define('UsrOrderPage', [], function() { return {}; });", "1"), ("Custom", "true", site_custom, "0")]
                if "generate_series" in text:  # the layers query has no body column (S48-T04): each body is read by its Id
                    import base64
                    import hashlib
                    data = next(b for p, _, b, _ in rows if f"'id-{p}'" in text).encode()
                    return [{"i": "0", "b64": base64.b64encode(data).decode(), "md5": hashlib.md5(data).hexdigest()}]
                return [{"id": f"id-{p}", "package": p, "extendParent": e, "modifiedOn": "", "modifiedBy": "", "isChanged": "false",
                         "manager": "ClientUnitSchemaManager", "size": "1", "md5": "x", "sl": "0", "pl": l} for p, e, b, l in rows]

        text = method_lines(ClassicSchema(top, "UsrOrderPage"), "init", Site(), "dev").split("\n")
        assert text[:4] == ["UsrOrderPage.init on dev: 3 of 4 layers define it, applied first to last (the last one runs first)",
                            "  UsrA  (site): line 4, 3 lines, callParent", "  UsrB  (site): -", "  Custom  (site only): line 4, 3 lines, callParent",
                            ], text[:4]
        assert text[4] == "  UsrC  (not on the site): line 10, 3 lines, no callParent: the layers below do not run", text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class FakeEnv:
    """env.sql answers from a function of the query text; the queries are kept."""

    def __init__(self, answer):
        self.answer, self.queries = answer, []

    def sql(self, text):
        self.queries.append(text)
        return self.answer(text)


def test_new_schema_with_a_parent():
    with workspace() as ws:
        d = ClassicSchema.create_new(ws / "UsrPkg2", "UsrItemDetail", "BaseGridDetailV2", entity="UsrItem", caption="Items", cultures=["en-US"])
        meta = d.metadata_text.split("\r\n")
        assert [" ".join(ln.split(" ")[:2]) for ln in meta] == ["= MetaData.Schema." + k for k in ("UId", "A2", "A5", "B6", "B8")] + \
            ["- MetaData.Schema.B7", "+ MetaData.Schema.B7", "= MetaData.Schema.HD1"], meta
        assert meta[-1] == '= MetaData.Schema.HD1 "01eb38ee-668a-42f0-999d-c2534f979089"' and meta[-2] == "+ MetaData.Schema.B7 false"
        assert d.parent == "BaseGridDetailV2" and not d.replacing and "ExtendParent" not in d.descriptor.text and d.kind == "detail"
        assert d.schema_type == "GridDetailViewModelSchema" and d.entity == "UsrItem" and d.module_name == "UsrItemDetail"
        assert d.resources.get("Caption") == "Items" and on_disk(d) and d.validate() == [] and d.diff_operations() == []
        # a workspace parent: its UId and its SchemaType
        p = ClassicSchema.create_new(ws / "UsrPkg2", "UsrOrderSubPage", "UsrOrderPage")
        assert p.descriptor.data["Parent"]["UId"] == "6938833f-2dad-4181-ad5e-b6a12ac1267d" and p.schema_type == "EditViewModelSchema"
        # neither: the site's row with --env, else refused with the query
        env = FakeEnv(lambda q: [{"uid": "abcabcab-0000-4000-8000-000000000001"}])
        s = ClassicSchema.create_new(ws / "UsrPkg2", "UsrAbcSection", "AbcSectionV2", env=env)
        assert s.descriptor.data["Parent"]["UId"] == "abcabcab-0000-4000-8000-000000000001" and "'AbcSectionV2'" in env.queries[0]
        assert s.schema_type == "ModuleViewModelSchema"
        refused(lambda: ClassicSchema.create_new(ws / "UsrPkg2", "UsrX", "AbcPageV2"), ValueError, "SysSchema")
        refused(lambda: ClassicSchema.create_new(ws / "UsrPkg2", "UsrX", "AbcPageV2", env=FakeEnv(lambda q: [])), ValueError, "on the site")
        refused(lambda: ClassicSchema.create_new(ws / "UsrPkg2", "UsrOrderPage", "BasePageV2"), FileExistsError)


def test_diff_add_appends_one_operation():
    with workspace() as ws:
        s = ClassicSchema(ws / "UsrPkg", "UsrOrderPage")
        before, ops = s.body, s.diff_operations()
        text = s.add_diff("insert", "UsrTerms", "Header", index=3, values={"bindTo": "UsrTerms", "layout": {"colSpan": 8, "rowSpan": 1, "column": 0, "row": 18}})
        assert text.startswith('{\n\t"operation": "insert",\n\t"name": "UsrTerms",\n\t"values": {\n\t\t"bindTo": "UsrTerms",')
        s.add_diff("remove", "UsrOldField")
        s.add_diff("move", "UsrStatus", "LeftContainer", index=0)
        s.save()
        s = ClassicSchema(ws / "UsrPkg", "UsrOrderPage")
        assert on_disk(s) and "\n" not in s.body.replace("\r\n", "")  # CRLF kept
        new = s.diff_operations()[len(ops):]
        assert [(o["operation"], o["name"], o["parentName"], o["index"]) for o in new] == [
            ("insert", "UsrTerms", "Header", "3"), ("remove", "UsrOldField", None, None), ("move", "UsrStatus", "LeftContainer", "0")]
        assert '"layoutName": "Header"' in new[0]["source"] and new[0]["values"] == ["bindTo", "layout"]
        cut = ops[-1]["at"] + len(ops[-1]["source"])
        assert s.body[:cut] == before[:cut] and s.body.endswith(before[cut:])  # only the new items between
        assert '\r\n\t\t\t\t{\r\n\t\t\t\t\t"operation": "remove",\r\n\t\t\t\t\t"name": "UsrOldField"\r\n\t\t\t\t}' in s.body
        refused(lambda: s.add_diff("insert", "UsrTerms", "Header"), ValueError, "already")
        refused(lambda: s.add_diff("insert", "UsrX"), ValueError, "parent")
        refused(lambda: s.add_diff("remove", "UsrX", "Header"), ValueError, "only the name")
        refused(lambda: s.add_diff("delete", "UsrX"), ValueError, "op is one of")
        # an empty diff (the new schema's) gets its first item inside the markers
        d = ClassicSchema.create_new(ws / "UsrPkg2", "UsrItemDetail", "BaseGridDetailV2")
        d.add_diff("merge", "DataGrid", "Detail", values={"type": 1})
        assert "diff: /**SCHEMA_DIFF*/[\n\t\t\t{\n\t\t\t\t\"operation\": \"merge\"," in d.body and d.body.count("/**SCHEMA_DIFF*/") == 2
        assert d.diff_operations()[0]["name"] == "DataGrid"


def test_add_string_overrides_a_string_of_the_parent_chain():
    with workspace() as ws:
        page = ClassicSchema(ws / "UsrPkg", "UsrOrderPage")
        page.add_string("UsrHint", {"en-US": "Hint"})
        page.save()
        hint = item_uid(page, "UsrHint")
        child = ClassicSchema.create_new(ws / "UsrPkg2", "UsrOrderSubPage", "UsrOrderPage", cultures=["en-US"])
        said = child.add_string("UsrHint", {"en-US": "Other hint"})
        assert said.startswith(f"UsrHint: overrides the string {hint} of UsrPkg/UsrOrderPage"), said
        uid, a5 = child.descriptor.data["UId"], child._diff().value("MetaData.Schema.A5")
        assert f'= MetaData.Schema.B2.["{hint}"].A4 "{uid}"\r\n= MetaData.Schema.B2.["{hint}"].A5 "{a5}"\r\n= MetaData.Schema.B6' in child.metadata_text
        assert "+ MetaData.Schema.B2" not in child.metadata_text and child.resources.get("LocalizableStrings.UsrHint.Value") == "Other hint"
        child.add_string("UsrHint", {"en-US": "Again"})  # the override is written once
        assert child.metadata_text.count(hint) == 2
        assert child.add_string("UsrOwn", {"en-US": "Own"}).startswith("UsrOwn: a new string of UsrOrderSubPage")  # the parent lacks it
        assert child.add_string("UsrOwn", {"en-US": "Own 2"}) == "UsrOwn: a string of UsrOrderSubPage already"
        # a parent only the site holds: its MetaData by --env
        d = ClassicSchema.create_new(ws / "UsrPkg2", "UsrItemDetail", "BaseGridDetailV2")
        env = FakeEnv(lambda q: [{"name": "BaseGridDetailV2", "uid": None}, {"name": "BaseDetailV2", "uid": "9d45150e-4614-4ebc-bd6a-72c206c111e9"}])
        assert "of BaseDetailV2 on the site" in d.add_string("Caption", {"en-US": "Items"}, env)
        assert '"A2"\\s*:\\s*"Caption"' in env.queries[0] and "'01eb38ee-668a-42f0-999d-c2534f979089'" in env.queries[0]
        assert '= MetaData.Schema.B2.["9d45150e-4614-4ebc-bd6a-72c206c111e9"].A4' in d.metadata_text
        assert d.add_string("UsrNone", {"en-US": "x"}, FakeEnv(lambda q: [])).startswith("UsrNone: a new string")


def test_new_and_diff_add_cli():
    with workspace() as ws:
        pkg = str(ws / "UsrPkg2")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            assert main(["new", pkg, "UsrItemDetail", "--parent", "BaseGridDetailV2", "--entity", "UsrItem", "--cultures", "en-US"]) == 0
            assert main(["new", pkg, "UsrNope", "--parent", "AbcPageV2"]) == 2
            body = ws / "UsrPkg2" / "Schemas" / "UsrItemDetail" / "UsrItemDetail.js"
            before = read(body)
            assert main(["diff", "add", pkg, "UsrItemDetail", "--op", "insert", "--name", "UsrTerms", "--parent", "Header", "--bind-to", "UsrTerms",
                         "--row", "18", "--col", "0", "--col-span", "8", "--dry-run"]) == 0
            assert read(body) == before
            assert main(["diff", "add", pkg, "UsrItemDetail", "--op", "insert", "--name", "UsrTerms", "--parent", "Header", "--bind-to", "UsrTerms",
                         "--row", "18", "--col", "0", "--col-span", "8", "--values", "enabled=false", "caption=Terms"]) == 0
            assert main(["diff", "add", pkg, "UsrItemDetail", "--op", "remove", "--name", "UsrTerms", "--parent", "Header"]) == 2
            assert main(["add-string", pkg, "UsrItemDetail", "UsrHint", "en-US=Hint"]) == 0
        text = out.getvalue()
        assert "created UsrItemDetail (detail) with parent BaseGridDetailV2 (01eb38ee-668a-42f0-999d-c2534f979089)" in text
        assert '"layout": {' in text and '"colSpan": 8' in text and "UsrHint: a new string of UsrItemDetail" in text
        op = ClassicSchema(ws / "UsrPkg2", "UsrItemDetail").element("UsrTerms")[0]
        assert op["values"] == ["enabled", "caption", "bindTo", "layout"] and '"enabled": false' in op["source"] and '"caption": "Terms"' in op["source"]


def _classic_layers(root: Path, bodies: dict) -> Path:
    """packages/<pkg>/Schemas/UsrOrderPage per body (the first one the own copy, each next one depending on the one before)."""
    names = list(bodies)
    for n, (pkg, body) in enumerate(bodies.items()):
        d = root / "packages" / pkg / "Schemas" / "UsrOrderPage"
        d.mkdir(parents=True)
        (d.parent.parent / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": pkg, "UId": f"00000000-0000-0000-0000-00000000000{n}",
                                                                                 "DependsOn": [{"Name": names[n - 1]}] if n else []}}), encoding="utf-8")
        (d / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": f"10000000-0000-0000-0000-00000000000{n}", "Name": "UsrOrderPage",
                                                                     "ManagerName": "ClientUnitSchemaManager", "ExtendParent": n > 0}}), encoding="utf-8")
        (d / "UsrOrderPage.js").write_text(body, encoding="utf-8")
    return root / "packages" / names[-1]


def _cell(name, row, col, span, op="insert", parent="Header"):
    where = f'"parentName": "{parent}", "propertyName": "items", ' if op != "merge" else ""
    return (f'{{"operation": "{op}", "name": "{name}", {where}"values": {{"layout": {{"colSpan": {span}, "rowSpan": 1, "column": {col}, '
            f'"row": {row}}}}}}}')


def _classic_body(rules: str, ops: list[str]) -> str:
    return ('define("UsrOrderPage", ["BusinessRuleModule"], function(BusinessRuleModule) {\n\treturn {\n' + rules
            + '\t\tdiff: /**SCHEMA_DIFF*/[\n\t\t\t' + ",\n\t\t\t".join(ops) + '\n\t\t]/**SCHEMA_DIFF*/\n\t};\n});\n')


def test_validate_exits_1_on_a_javascript_syntax_error():
    import shutil as _sh
    if not _sh.which("node"):
        return  # jscheck prints `node not found` and cannot fail
    tmp = Path(tempfile.mkdtemp())
    try:
        pkg = tmp / "UsrPkg"
        shutil.copytree(FIXTURES, pkg)
        assert main(["validate", str(pkg), "UsrOrderSection"]) == 0
        body = pkg / "Schemas" / "UsrOrderSection" / "UsrOrderSection.js"
        body.write_bytes(body.read_bytes() + b"\nvar = ;\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert main(["validate", str(pkg), "UsrOrderSection"]) == 1
        assert "js syntax: ERROR" in out.getvalue(), out.getvalue()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rule_state_reads_through_the_methods_reader():
    from creatio_schemas.describe.layers import rule_state
    body = _classic_body('\t\tbusinessRules: /**SCHEMA_BUSINESS_RULES*/{\n\t\t\t"UsrX": {"u1": {"uId": "u1", "enabled": false}}\n\t\t}/**SCHEMA_BUSINESS_RULES*/,\n', [])
    assert (rule_state(body, "u1"), rule_state(body, "u2"), rule_state("  ", "u1")) == ("disabled", "absent", "no body")


def test_layout_and_rules_over_the_workspace_and_the_site_layers():
    import base64
    import hashlib
    from creatio_schemas.classicui.layout import grid_lines, layout_lines, rule_lines

    rule = "86cb5577-7d80-4105-bf73-9210af082df0"
    base = _classic_body(
        '\t\tbusinessRules: /**SCHEMA_BUSINESS_RULES*/{\n'
        f'\t\t\t"UsrContract": {{"{rule}": {{"uId": "{rule}", "enabled": true, "removed": false, "ruleType": 1, "baseAttributePatch": "Account",\n'
        '\t\t\t\t"comparisonType": 3, "autoClean": true, "autocomplete": false, "type": 1, "attribute": "UsrAccount"}}\n\t\t}/**SCHEMA_BUSINESS_RULES*/,\n'
        '\t\trules: {"UsrStatus": {"UsrStatusRequired": {"ruleType": BusinessRuleModule.enums.RuleType.BINDPARAMETER,\n'
        '\t\t\t"property": BusinessRuleModule.enums.Property.REQUIRED, "conditions": [{"leftExpression": {"type": 1, "attribute": "UsrType",\n'
        '\t\t\t"attributePath": "Code"}, "comparisonType": Terrasoft.ComparisonType.EQUAL, "rightExpression": {"type": 0, "value": "A"}}]}}},\n',
        [_cell("UsrName", 0, 0, 12), _cell("UsrAmount", 0, 12, 12), _cell("UsrDate", 1, 0, 12)])
    upper = _classic_body(
        f'\t\tbusinessRules: /**SCHEMA_BUSINESS_RULES*/{{\n\t\t\t"UsrContract": {{"{rule}": {{"uId": "{rule}", "enabled": false}}}}\n'
        '\t\t}/**SCHEMA_BUSINESS_RULES*/,\n',
        [_cell("UsrAmount", 2, 12, 12, "merge"), '{"operation": "remove", "name": "UsrDate"}', _cell("UsrNote", 1, 0, 12)])
    custom = _classic_body(
        f'\t\tbusinessRules: /**SCHEMA_BUSINESS_RULES*/{{\n\t\t\t"UsrContract": {{"{rule}": {{"uId": "{rule}", "removed": true}}}}\n'
        '\t\t}/**SCHEMA_BUSINESS_RULES*/,\n',
        [_cell("UsrCode", 2, 0, 12), _cell("UsrFlag", 0, 6, 2), _cell("UsrName", 5, 0, 4, "move", "Footer"), _cell("UsrName", 0, 0, 12, "move")])
    tmp = Path(tempfile.mkdtemp())
    try:
        top = _classic_layers(tmp, {"UsrA": base, "UsrB": upper})
        parent = tmp / "packages" / "UsrBase" / "Schemas" / "UsrBasePage"  # the parent page fills Header first (a Classic Header comes from it)
        parent.mkdir(parents=True)
        (parent.parent.parent / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": "UsrBase", "UId": "00000000-0000-0000-0000-0000000000b0"}}),
                                                              encoding="utf-8")
        (parent / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": "10000000-0000-0000-0000-0000000000b0", "Name": "UsrBasePage",
                                                                          "ManagerName": "ClientUnitSchemaManager"}}), encoding="utf-8")
        (parent / "UsrBasePage.js").write_text(_classic_body("", [_cell("UsrTop", 3, 0, 24)]), encoding="utf-8")
        own = tmp / "packages" / "UsrA" / "Schemas" / "UsrOrderPage" / "descriptor.json"
        own.write_text(own.read_text(encoding="utf-8").replace('"ExtendParent": false', '"ExtendParent": false, "Parent": {"Name": "UsrBasePage"}'),
                       encoding="utf-8")
        site = {"UsrA": ("false", "81"), "UsrB": ("true", "107"), "Custom": ("true", "400")}

        def answer(q):
            if '"ParentId"' in q:
                return []  # the site names no parent
            if "generate_series" in q:  # body.read of the one copy only on the site
                data = custom.encode()
                return [{"i": "0", "b64": base64.b64encode(data).decode(), "md5": hashlib.md5(data).hexdigest()}]
            if '"SysPackage" where "Name" in' in q:
                return [{"package": p, "level": hl} for p, (_, hl) in site.items()]
            rows = [{"id": f"id-{p}", "package": p, "extendParent": e, "manager": "ClientUnitSchemaManager", "modifiedOn": "", "size": "1", "md5": "x",
                     "sl": "0", "pl": "0", "hl": hl} for p, (e, hl) in site.items()]
            return rows[::-1]  # the base after the replacing copies, as the design-time function levels it on 8.3.2
        env = FakeEnv(answer)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert main(["layout", str(top), "UsrOrderPage"]) == 0  # the workspace only; the package names the workspace
        assert out.getvalue().splitlines() == [
            "UsrOrderPage.Header over 3 layers (UsrBasePage:UsrBase > UsrA > UsrB), 24 columns, the last layer wins",
            "  row 0: 0-11 UsrName | 12-23 free", "  row 1: 0-11 UsrNote | 12-23 free", "  row 2: 0-11 free | 12-23 UsrAmount", "  row 3: 0-23 UsrTop",
            "  UsrName  row 0 col 0 span 12x1  (placed last in UsrA)", "  UsrNote  row 1 col 0 span 12x1  (placed last in UsrB)",
            "  UsrAmount  row 2 col 12 span 12x1  (placed last in UsrB)", "  UsrTop  row 3 col 0 span 24x1  (placed last in UsrBasePage:UsrBase)"], out.getvalue()
        lines = layout_lines(top, "UsrOrderPage", "Header", env)
        assert lines[:4] == ["UsrOrderPage.Header over 3 layers (UsrA > UsrB > Custom (site)), 24 columns, the last layer wins",
                             "  row 0: 0-5 UsrName | 6-7 UsrName+UsrFlag (overlap) | 8-11 UsrName | 12-23 free",
                             "  row 1: 0-11 UsrNote | 12-23 free", "  row 2: 0-11 UsrCode | 12-23 UsrAmount"], lines
        assert "  UsrFlag  row 0 col 6 span 2x1  (placed last in Custom)" in lines and "  UsrName  row 0 col 0 span 12x1  (placed last in Custom)" in lines
        assert sum("generate_series" in q for q in env.queries) == 1  # only the copy the workspace lacks is read from the site
        refused(lambda: layout_lines(top, "UsrOrderPage", "Footer"), KeyError, "nothing is placed in Footer")
        assert grid_lines([("UsrX", 1, 1, 1, 1)], 2, 1) == ["  row 1: 1 UsrX | 2 free"]  # Freedom counts from 1
        rules = rule_lines(top, "UsrOrderPage", env)
        assert rules == [
            "UsrOrderPage: 2 rule(s) over 3 layers (UsrA > UsrB > Custom (site)); column, UId, kind, state, conditions, filter, layers",
            f"  UsrContract  {rule}  FILTRATION  removed  filter UsrContract.Account = UsrAccount, autoClean  defined in UsrA, state last changed in Custom  layers: UsrA enabled > UsrB disabled > Custom removed",
            "  UsrStatus  UsrStatusRequired  BINDPARAMETER REQUIRED  enabled  (rules section)  when UsrType.Code = 'A'  defined in UsrA, state last changed in UsrA  layers: UsrA enabled"], rules
        assert rule_lines(top, "UsrOrderPage", None, rule.upper())[1].endswith("defined in UsrA, state last changed in UsrB  layers: UsrA enabled > UsrB disabled")
        refused(lambda: rule_lines(top, "UsrOrderPage", None, "UsrNope"), KeyError, "no rule UsrNope in the layers of UsrOrderPage (UsrA, UsrB)")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert main(["rules", str(top), "UsrOrderPage", "--rule", "UsrStatusRequired"]) == 0
        assert "BINDPARAMETER REQUIRED" in out.getvalue()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_new_schema_is_stamped_with_the_projects_platform_version():
    """S52-T04: --project stamps environment.platformVersion (padded to four parts), --version beats it, none keeps the default."""
    import contextlib, io, json, shutil, tempfile
    pass
    tmp = Path(tempfile.mkdtemp())
    try:
        project = tmp / "project.json"
        project.write_text(json.dumps({"environment": {"platformVersion": "8.3.2"}}), encoding="utf-8")
        stamps = []
        for extra in ([], ["--project", str(project)], ["--project", str(project), "--version", "8.3.4.2753"]):
            pkg = tmp / f"p{len(stamps)}" / "UsrPkg"
            shutil.copytree(FIXTURES, pkg)
            with contextlib.redirect_stdout(io.StringIO()):
                assert main(["new", str(pkg), "UsrStampDetail", "--parent", "BaseGridDetailV2", "--entity", "UsrItem", "--cultures", "en-US"] + extra) == 0
            props = json.loads((pkg / "Schemas" / "UsrStampDetail" / "properties.json").read_text(encoding="utf-8-sig"))["Properties"]
            stamps.append(props["CreatedInVersion"])
        assert stamps == ["8.2.3.1351", "8.3.2.0", "8.3.4.2753"], stamps
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for fn in [v for k, v in list(globals().items()) if k.startswith("test_")]:
        fn()
        print("ok", fn.__name__)
