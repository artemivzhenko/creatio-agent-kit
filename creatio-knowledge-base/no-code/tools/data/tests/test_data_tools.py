"""Checks for the data binding tools:  python tests/test_data_tools.py  (the fixture bindings are real ones, names made generic)."""

import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent))

from creatio_schemas.data import DataBinding  # noqa: E402
from creatio_schemas.data.binding import JsonFile, coerce  # noqa: E402
from creatio_schemas.files import DVT_OF  # noqa: E402
from data import main  # noqa: E402

FIXTURES = HERE / "fixtures" / "UsrPkg"
BINDINGS = ("UsrStatus", "SysSettings_UsrMaxRows", "SysSettingsValue_UsrMaxRows")
NEW = "03edf152-0b98-4b17-91d6-574473b46241"  # UsrStatus row "New"
ALL_EMPLOYEES = "a29a3ba5-4b0d-de11-9a51-005056c00008"


def read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


@contextlib.contextmanager
def workspace():
    """A writable copy of the fixture package inside its own packages folder."""
    tmp = Path(tempfile.mkdtemp()) / "packages"
    shutil.copytree(FIXTURES, tmp / "UsrPkg")
    try:
        yield tmp / "UsrPkg"
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


def test_round_trip_is_byte_identical():
    for name in BINDINGS:
        b = DataBinding(FIXTURES, name)
        for path, (text, bom) in b.files().items():
            assert read(path) == ("﻿" if bom else "") + text, path
        b.describe()
        b.rows()
        assert b.diff() == "", name


def test_reads_columns_rows_and_describe():
    b = DataBinding(FIXTURES, "UsrStatus")
    assert b.describe() == "UsrStatus: binds UsrOrderStatus, 3 rows, columns Id Name(loc) Description(loc), install with package"
    assert b.schema_name == "UsrOrderStatus" and b.key_columns == ["Id"] and b.cultures == ["en-US", "ru-RU"]
    assert b.columns["Name"]["uid"] == "736c30a7-c0ec-4fa9-b034-2552b319b633" and not b.columns["Name"]["key"]
    assert b.localized == ["Name", "Description"]
    assert b.rows()[0] == {"Id": NEW, "Name": {"en-US": "New", "ru-RU": "Новый"}, "Description": {"en-US": "", "ru-RU": ""}}
    assert [r["Name"] for r in b.rows("ru-RU")] == ["Новый", "В работе", "Выполнен"]
    assert b.row(NEW.upper())["Name"]["en-US"] == "New"
    v = DataBinding(FIXTURES, "SysSettingsValue_UsrMaxRows")
    row = v.rows()[0]
    assert row["IntegerValue"] == 10000 and row["SysAdminUnit"] == ALL_EMPLOYEES and v.localized == []
    assert v.display_values(v.key_of(row)) == {"SysSettings": "Max rows", "SysAdminUnit": "All employees"}
    s = DataBinding(FIXTURES, "SysSettings_UsrMaxRows")
    assert s.rows()[0]["Code"] == "UsrMaxRows" and row["SysSettings"] == s.rows()[0]["Id"]
    try:
        b.row("nope")
    except KeyError:
        pass
    else:
        raise AssertionError("an unknown key must raise")


def test_validate_finds_each_problem():
    for name in BINDINGS:
        assert DataBinding(FIXTURES, name).validate() == [], name
    b = DataBinding(FIXTURES, "SysSettingsValue_UsrMaxRows")
    cells = b.data.obj["PackageData"][0]["Row"]
    cells.append({"SchemaColumnUId": "11111111-1111-1111-1111-111111111111", "Value": 1})
    next(c for c in cells if c["SchemaColumnUId"] == b.columns["SysAdminUnit"]["uid"])["Value"] = "All employees"
    b.data.obj["PackageData"].append(json.loads(json.dumps(b.data.obj["PackageData"][0])))
    problems = "\n".join(b.validate())
    assert "which the descriptor does not list" in problems and "lookup SysAdminUnit = 'All employees' is not a UId" in problems
    assert "duplicate key" in problems
    s = DataBinding(FIXTURES, "UsrStatus")
    s.loc["ru-RU"].obj["PackageData"][0]["Row"][0]["Value"] = "22222222-2222-2222-2222-222222222222"
    assert s.validate() == ["Localization/data.ru-RU.json: row 22222222-2222-2222-2222-222222222222 is not in data.json"]
    s.descriptor.set("Columns", [dict(c, IsKey=False) for c in s.descriptor.data["Columns"]])
    assert any(p.startswith("warning: no key column") for p in s.validate()) and s.errors() != []


def test_edit_rows_and_save():
    with workspace() as pkg:
        v = DataBinding(pkg, "SysSettingsValue_UsrMaxRows")
        key = v.key_of(v.rows()[0])
        v.set_value(key, "IntegerValue", "500")
        v.set_value(key, "BooleanValue", "true")
        v.set_value(key, "SysAdminUnit", "33333333-3333-3333-3333-333333333333")
        for column, value in (("SysAdminUnit", "All employees"), ("Nope", "1"), ("BooleanValue", "yes")):
            try:
                v.set_value(key, column, value)
            except (KeyError, ValueError):
                pass
            else:
                raise AssertionError(f"{column}={value} must be refused")
        v.save()
        again = DataBinding(pkg, "SysSettingsValue_UsrMaxRows")
        assert again.rows()[0]["IntegerValue"] == 500 and again.rows()[0]["BooleanValue"] is True
        assert again.display_values(key)["SysAdminUnit"] == "" and again.display_values(key)["SysSettings"] == "Max rows"
        assert again.diff() == "" and "\t" not in read(again.data.path) and read(again.data.path).startswith("﻿{\r\n  \"PackageData\"")

        b = DataBinding(pkg, "UsrStatus")
        b.set_value(NEW, "Name", "Новая", "ru-RU")
        try:
            b.set_value(NEW, "Name", "x")
        except ValueError as e:
            assert "localised" in str(e)
        else:
            raise AssertionError("a localised column needs a culture")
        added = b.add_row({"Name": "On hold"})
        both = b.add_row({"Id": "44444444-4444-4444-4444-444444444444", "Name": {"en-US": "Closed", "ru-RU": "Закрыт"}})
        try:
            b.add_row({"Id": both})
        except ValueError:
            pass
        else:
            raise AssertionError("a duplicate key must be refused")
        b.remove_row("6249ed1f-9d7c-4556-8273-00bd2db4e0e0")
        assert b.errors() == []
        b.save()
        again = DataBinding(pkg, "UsrStatus")
        assert [r["Name"]["ru-RU"] for r in again.rows()] == ["Новая", "Выполнен", "On hold", "Закрыт"]
        assert again.row(added)["Name"] == {"en-US": "On hold", "ru-RU": "On hold"}
        assert all(c["SchemaColumnUId"] == again.columns["Id"]["uid"] for r in again.data.obj["PackageData"] for c in r["Row"])
        assert again.diff() == ""


def test_create_without_columns_binds_every_column_but_the_system_ones():
    with workspace() as pkg:
        own = DataBinding.create(pkg, "UsrAll", "UsrOrderStatus", ["Id"], [], all_columns=True)
        assert sorted(c["ColumnName"] for c in own.descriptor.data["Columns"]) == ["Description", "Id", "Name"]
        plat = DataBinding.create(pkg, "UsrLookupAll", "Lookup", ["Id"], [], all_columns=True)
        names = [c["ColumnName"] for c in plat.descriptor.data["Columns"]]
        assert "Name" in names and not {"CreatedOn", "CreatedBy", "ModifiedOn", "ModifiedBy", "ProcessListeners"} & set(names), names
        narrow = DataBinding.create(pkg, "UsrNarrow", "UsrOrderStatus", ["Id"], [], columns=["Name"])
        assert [c["ColumnName"] for c in narrow.descriptor.data["Columns"]] == ["Id", "Name"]
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(["new", str(pkg), "UsrCli", "--table", "UsrOrderStatus"]) == 0
        assert sorted(c["ColumnName"] for c in DataBinding(pkg, "UsrCli").descriptor.data["Columns"]) == ["Description", "Id", "Name"]


def test_create_binds_an_object_of_the_workspace():
    with workspace() as pkg:
        b = DataBinding.create(pkg, "UsrPriority", "UsrOrderStatus", ["Id"], [{"Name": "High"}, {"Name": {"en-US": "Low", "ru-RU": "Низкий"}}],
                               ["en-US", "ru-RU"])
        cols = b.descriptor.data["Columns"]
        assert [(c["ColumnName"], c["ColumnUId"], c["IsKey"]) for c in cols] == [
            ("Id", "ae0e45ca-c495-4fe7-a39d-3ab7278e1617", True), ("Name", "736c30a7-c0ec-4fa9-b034-2552b319b633", False)]
        assert cols[1]["DataTypeValueUId"] == DVT_OF["MediumText"] and b.descriptor.data["Schema"]["Name"] == "UsrOrderStatus"
        assert read(pkg / "Data" / "UsrPriority" / "filter.json") == "" and b.validate() == []
        again = DataBinding(pkg, "UsrPriority")
        assert [r["Name"] for r in again.rows("ru-RU")] == ["High", "Низкий"] and again.diff() == ""
        assert len(again.data.obj["PackageData"][0]["Row"]) == 1  # the localised Name lives in Localization/ only
        empty = DataBinding.create(pkg, "UsrEmpty", "UsrOrderStatus", ["Id"], [], ["en-US"], ["Name"])
        key = empty.add_row({"Name": "Later"})  # the object says Name is localisable, the empty files cannot
        assert empty.row(key)["Name"] == {"en-US": "Later"}
        empty.loc = {}  # no Localization files: the platform keeps Name in data.json, so does add_row
        key = empty.add_row({"Name": "Flat"})
        assert empty.row(key)["Name"] == "Flat"
        key = empty.add_row({"Name": {"de-DE": "Spaeter"}})
        assert empty.cultures == ["de-DE"] and empty.row(key)["Name"] == {"de-DE": "Spaeter"}
        for args, error in ((("UsrX", "UsrNowhere", ["Id"], []), KeyError), (("Usr X", "UsrOrderStatus", ["Id"], []), ValueError),
                            (("UsrPriority", "UsrOrderStatus", ["Id"], []), FileExistsError), (("UsrY", "UsrOrderStatus", ["Id"], [{"Nope": 1}]), KeyError)):
            try:
                DataBinding.create(pkg, *args)
            except error:
                pass
            else:
                raise AssertionError(f"create{args} must raise {error.__name__}")


def test_platform_catalog_loads_and_has_the_five_tables():
    from creatio_schemas.data.binding import PLATFORM_BINDINGS, platform_table
    catalog = json.loads(PLATFORM_BINDINGS.read_text(encoding="utf-8"))
    assert catalog["version"].startswith("8.3.2")
    for table in ("Lookup", "SysEntitySchemaOperationRight", "SysSettings", "SysSettingsValue", "SysModuleEntity", "SysModule",
                  "SysModuleInWorkplace"):
        t = platform_table(table)
        assert t and len(t["uid"]) == 36 and t["columns"]["Id"]["UId"] == "ae0e45ca-c495-4fe7-a39d-3ab7278e1617", table
        assert all(c["S2"] for c in t["columns"].values()), table
    assert platform_table("Lookup")["columns"]["Name"].get("E21") is True and platform_table("UsrNowhere") is None


def test_create_binds_a_platform_table_from_the_catalog():
    from creatio_schemas.data.binding import platform_table
    with workspace() as pkg:
        entity = "5d2a1c3e-0000-4000-8000-000000000001"
        reg = DataBinding.create(pkg, "UsrLookup_UsrOrderStatus", "Lookup", ["Id"], [{"Name": "Order statuses", "SysEntitySchemaUId": entity}])
        lookup = platform_table("Lookup")
        assert reg.descriptor.data["Schema"] == {"UId": lookup["uid"], "Name": "Lookup"}
        assert {c["ColumnName"]: c["ColumnUId"] for c in reg.descriptor.data["Columns"]}["Name"] == lookup["columns"]["Name"]["UId"]
        again = DataBinding(pkg, "UsrLookup_UsrOrderStatus")
        assert again.rows()[0]["Name"] == {"en-US": "Order statuses"} and again.rows()[0]["SysEntitySchemaUId"] == entity  # Name localised
        right = DataBinding.create(pkg, "UsrOrderRights", "SysEntitySchemaOperationRight", ["Id"],
                                   [{"SysAdminUnit": ALL_EMPLOYEES, "SubjectSchemaUId": entity, "CanRead": "true", "Position": "0"}])
        row = right.rows()[0]
        assert row["CanRead"] is True and row["Position"] == 0 and row["SysAdminUnit"] == ALL_EMPLOYEES and right.validate() == []
        key = DataBinding(pkg, "UsrLookup_UsrOrderStatus").add_row({"Name": "Later"})  # a later add-row: Name still localised
        assert DataBinding(pkg, "UsrLookup_UsrOrderStatus").loc["en-US"].obj["PackageData"] and key


def test_create_with_env_reads_the_table_from_the_site():
    import creatio_schemas.data.binding as binding
    seen = []

    def fake(env, table, package):
        seen.append((env, table, package))
        return {"uid": "5d2a1c3e-0000-4000-8000-000000000002",
                "columns": {"Id": {"UId": "ae0e45ca-c495-4fe7-a39d-3ab7278e1617", "S2": DVT_OF["Guid"]},
                            "Caption": {"UId": "5d2a1c3e-0000-4000-8000-000000000003", "S2": DVT_OF["MediumText"], "E21": True}}}

    saved, binding.site_table = binding.site_table, fake
    try:
        with workspace() as pkg:
            b = DataBinding.create(pkg, "UsrSiteTable", "SysUsrTable", ["Id"], [{"Caption": "x"}], env="dev")
            assert seen == [("dev", "SysUsrTable", "UsrPkg")] and b.descriptor.data["Schema"]["UId"] == "5d2a1c3e-0000-4000-8000-000000000002"
            assert b.rows()[0]["Caption"] == {"en-US": "x"}  # localisable on the site: Localization/, not data.json
            try:
                DataBinding.create(pkg, "UsrNone", "SysUsrOther", ["Id"], [])
                raise AssertionError("must be refused")
            except KeyError as err:
                assert "--env <env>" in str(err) and "Lookup" in str(err)
    finally:
        binding.site_table = saved


def test_site_table_of_a_package_not_on_the_site_reads_it_below_custom():
    import creatio_schemas.entity.hierarchy as hierarchy
    from creatio_schemas.data.binding import site_table
    asked = []

    def fake(clio, obj, package):
        asked.append(package)
        if package != "Custom":
            raise KeyError(f"no object {obj} in the hierarchy of package {package}")
        return {"uid": "5D2A1C3E-0000-4000-8000-000000000004", "schema": {"D2": [{"A2": "Id", "UId": "u", "S2": "t", "E9": True}]}}

    saved, hierarchy.fetch_base = hierarchy.fetch_base, fake
    try:
        t = site_table("dev", "Lookup", "UsrPkg")
    finally:
        hierarchy.fetch_base = saved
    assert asked == ["UsrPkg", "Custom"] and t == {"uid": "5d2a1c3e-0000-4000-8000-000000000004", "columns": {"Id": {"UId": "u", "S2": "t"}}}


def test_json_file_keeps_the_style_of_the_file():
    with workspace() as pkg:
        path = pkg / "x.json"
        path.write_text('{\n\t"PackageData": [\n\t\t{\n\t\t\t"Value": "\\/Date(1793376038931+0200)\\/"\n\t\t}\n\t]\n}\n', encoding="utf-8", newline="")
        f = JsonFile(path)
        assert f.render() == read(path) and not f.bom
        f.obj["PackageData"].append({"Value": "a/b"})
        assert f.render() == ('{\n\t"PackageData": [\n\t\t{\n\t\t\t"Value": "\\/Date(1793376038931+0200)\\/"\n\t\t},\n\t\t{\n\t\t\t"Value": "a/b"\n\t\t}\n\t]\n}\n')
    assert coerce(DVT_OF["Float2"], "1.5") == 1.5 and coerce(DVT_OF["Integer"], "null") == "null" and coerce(DVT_OF["MediumText"], "7") == "7"


def test_cli():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["inspect", str(FIXTURES), "UsrStatus"]) == 0
        assert main(["validate", str(FIXTURES), "SysSettings_UsrMaxRows"]) == 0
        assert main(["rows", str(FIXTURES), "UsrStatus", "--limit", "1", "--culture", "ru-RU"]) == 0
    text = out.getvalue()
    assert "binds UsrOrderStatus" in text and f'{NEW}  Name="Новый"' in text and "... 2 more" in text
    with workspace() as pkg:
        rows = pkg.parent / "rows.json"
        rows.write_text(json.dumps([{"Name": "High"}]), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert main(["new", str(pkg), "UsrPriority", "--table", "UsrOrderStatus", "--columns", "Description", "--cultures", "en-US,ru-RU",
                         "--rows", str(rows)]) == 0
            assert main(["add-row", str(pkg), "UsrPriority", "Name=Low", "Description=-"]) == 0
            key = out.getvalue().split("add row ")[1].split()[0]
            assert main(["set", str(pkg), "UsrPriority", key, "Name", "Низкий", "--culture", "ru-RU"]) == 0
            assert main(["remove-row", str(pkg), "UsrPriority", key, "--dry-run"]) == 0
            assert main(["set", str(pkg), "UsrPriority", key, "Nope", "1"]) == 2
        assert "columns Id Description(loc) Name(loc)" in out.getvalue() and "(dry run: nothing written)" in out.getvalue()
        assert [r["Name"] for r in DataBinding(pkg, "UsrPriority").rows("ru-RU")] == ["High", "Низкий"]


class FakeEnvironment:
    """Two pages of Contact rows: the first full (PAGE rows), the second short."""

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def odata(self, entity, select=None, filter=None, top=None, orderby=None, skip=None, expand=None):
        self.calls.append((entity, select, filter, top, orderby, skip, expand))
        return self.rows[skip or 0:(skip or 0) + top]


def test_duplicates_over_the_environment():
    import data as tool
    rows = [{"Id": f"id-{i}", "Phone": f"+1 ({i % 3})"} for i in range(tool.PAGE)] + [{"Id": "last", "Phone": " +1 (0) "}]
    env = FakeEnvironment(rows)
    tool.open_environment = lambda e, p: env  # the CLI's -e would read clio's settings
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["duplicates", "Contact", "Phone", "-e", "dev", "--normalize", "trim,digits", "--where", "Name ne ''", "--limit", "2"]) == 1
    text = out.getvalue()
    assert text.splitlines()[0].startswith('"+1 (0)"  168 records  ids: id-0, id-3') and "+158 more" in text
    assert "... 1 more groups" in text and "3 duplicate groups, 501 records in them (Contact.Phone, normalize: trim,digits)" in text
    assert env.calls[0] == ("Contact", ["Id", "Phone"], "Name ne ''", tool.PAGE, "Id", 0, None) and env.calls[1][5] == tool.PAGE
    # a lookup column: the Name of the referenced record, through $expand
    env = FakeEnvironment([{"Id": "a", "AccountId": "1", "Account": {"Name": "Acme"}}, {"Id": "b", "AccountId": "2", "Account": {"Name": "acme "}},
                           {"Id": "c", "AccountId": None, "Account": None}])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["duplicates", "Contact", "Account", "-e", "dev", "--lookup", "--normalize", "trim,lower", "--json"]) == 1
    result = json.loads(out.getvalue())
    assert result["groups"] == [{"value": "Acme", "count": 2, "ids": ["a", "b"]}] and result["records"] == 2
    assert env.calls[0][1] == ["Id", "AccountId"] and env.calls[0][6] == "Account($select=Name)"
    assert main(["duplicates", "Contact", "Phone", "-e", "dev", "--normalize", "nope"]) == 2
    # no duplicates: exit 0
    env.rows = [{"Id": "a", "Account": {"Name": "A"}}]
    with contextlib.redirect_stdout(io.StringIO()):
        assert main(["duplicates", "Contact", "Account", "-e", "dev", "--lookup"]) == 0


if __name__ == "__main__":
    for fn in [v for k, v in list(globals().items()) if k.startswith("test_")]:
        fn()
        print("ok", fn.__name__)
