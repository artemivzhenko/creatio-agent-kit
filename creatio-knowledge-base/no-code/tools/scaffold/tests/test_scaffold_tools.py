"""Checks for the scaffold:  python tests/test_scaffold_tools.py  (runs on temp copies of the pages fixture)."""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE.parent))

from creatio_schemas.classicui import ClassicSchema  # noqa: E402
from creatio_schemas.csharp import CSharpSource  # noqa: E402
from creatio_schemas.data import DataBinding  # noqa: E402
from creatio_schemas.describe import describe_item, describe_package  # noqa: E402
from creatio_schemas.entity import EntitySchema  # noqa: E402
from creatio_schemas.page import PageSchema  # noqa: E402
from scaffold import caption_of, create_package, main, parse_column, parse_lookup  # noqa: E402

PAGES = TOOLS / "pages" / "tests" / "fixtures" / "UsrPkg"
SPEC = ["--caption", "Shipment", "--column", "UsrNumber:Integer:required", "--column", "UsrNotes:MediumText",
        "--column", "UsrContact:Lookup:Contact", "--lookup", "UsrStatus:UsrShipmentStatus:New,In progress,Done", "--pages", "--cultures", "en-US,ru-RU"]


def read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


@contextlib.contextmanager
def package():
    tmp = Path(tempfile.mkdtemp()) / "packages"
    shutil.copytree(PAGES, tmp / "UsrPkg")
    try:
        yield tmp / "UsrPkg"
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


def run(*argv) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(argv))
    return code, out.getvalue()


def files(pkg: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in pkg.rglob("*") if p.is_file()}


def test_spec_grammar():
    assert parse_column("UsrNumber:Integer:required,indexed") == {"name": "UsrNumber", "type": "Integer", "ref": None, "flags": ["required", "indexed"]}
    assert parse_column("UsrContact:Lookup:Contact:required") == {"name": "UsrContact", "type": "Lookup", "ref": "Contact", "flags": ["required"]}
    assert parse_lookup("UsrStatus:UsrShipmentStatus:New, In progress ,Done")["rows"] == ["New", "In progress", "Done"]
    assert parse_lookup("UsrKind:UsrKindLookup") == {"column": "UsrKind", "object": "UsrKindLookup", "rows": []}
    assert [caption_of(n) for n in ("UsrShipDate", "UsrURLLink", "UsrOrderStatus", "Name")] == ["Ship date", "URL link", "Order status", "Name"]
    for bad in ("UsrX", ":Integer", "UsrC:Lookup"):
        try:
            parse_column(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad!r} must be refused")
    try:
        parse_lookup("UsrStatus")
    except ValueError:
        pass
    else:
        raise AssertionError("a lookup spec without its object must be refused")


def test_dry_run_then_build_then_refuse():
    with package() as pkg:
        before = files(pkg)
        code, out = run("entity", str(pkg), "UsrShipment", *SPEC, "--dry-run")
        assert code == 0 and files(pkg) == before, out  # nothing written
        assert "+++ b/Schemas/UsrShipment/metadata.json" in out and "+++ b/Data/UsrShipmentStatus/data.json" in out and "(dry run: nothing written)" in out

        code, out = run("entity", str(pkg), "UsrShipment", *SPEC)
        assert code == 0 and "29 file(s) written to UsrPkg" in out, out
        listing = describe_package(pkg)
        for line in ("object    UsrShipment ", "object    UsrShipmentStatus ", "page      UsrShipment_FormPage ", "page      UsrShipment_ListPage "):
            assert line in listing, listing

        ent, status = EntitySchema(pkg, "UsrShipment"), EntitySchema(pkg, "UsrShipmentStatus")
        assert ent.column("UsrNumber")["E2"] == 1 and ent.column("UsrStatus")["S4"] == status.uid and status.parent_name == "BaseLookup"
        assert ent.resources.get("Columns.UsrNotes.Caption") == "Notes" and ent.resources.cultures.keys() == {"en-US", "ru-RU"}
        binding = DataBinding(pkg, "UsrShipmentStatus")
        assert [r["Name"] for r in binding.rows("en-US")] == ["New", "In progress", "Done"]
        form = PageSchema(pkg, "UsrShipment_FormPage")
        types = {e["code"]: e["type"] for e in form.page_file()[0]["elements"]}
        assert {k: types[k] for k in ("UsrNumber", "UsrNotes", "UsrContact", "UsrStatus")} == {
            "UsrNumber": "Integer", "UsrNotes": "Text", "UsrContact": "Lookup", "UsrStatus": "Lookup"}
        assert PageSchema(pkg, "UsrShipment_ListPage").entity == "UsrShipment"
        items = [ent, status, binding, form, PageSchema(pkg, "UsrShipment_ListPage")]
        for item in items:  # each passes its toolkit and round-trips byte for byte
            assert item.errors() == [], (item.name, item.errors())
            for path, (text, bom) in item.files().items():
                assert read(path) == ("﻿" if bom else "") + text, path

        written = files(pkg)
        code, out = run("entity", str(pkg), "UsrShipment", *SPEC)
        assert code == 2 and "exists" in out and files(pkg) == written  # never overwritten


def test_existing_lookup_is_reused_and_errors_write_nothing():
    with package() as pkg:
        code, out = run("entity", str(pkg), "UsrParcel", "--caption", "Parcel", "--lookup", "UsrState:UsrOrderStatus")
        assert code == 0 and "lookup object" not in out and "data binding" not in out and "page " not in out, out
        assert EntitySchema(pkg, "UsrParcel").column("UsrState")["S4"] == EntitySchema(pkg, "UsrOrderStatus").uid
        before = files(pkg)
        for argv in (("--column", "UsrX:NoSuchType"), ("--column", "UsrX:Integer:no-such-flag"), ("--column", "UsrX"),
                     ("--lookup", "UsrS:UsrOrderStatus:A,B", "--column", "UsrX:Integer"), ("--pages", "--column", "UsrX:Lookup:NoSuchObject")):
            code, out = run("entity", str(pkg), "UsrBox", "--caption", "Box", *argv)
            if any("UsrOrderStatus:A,B" in x for x in argv):  # a binding of an existing lookup is made when it has rows and no binding yet
                assert code == 0 and DataBinding(pkg, "UsrOrderStatus").rows() and EntitySchema(pkg, "UsrBox")
                shutil.rmtree(pkg / "Schemas" / "UsrBox")
                shutil.rmtree(pkg / "Data" / "UsrOrderStatus")
                shutil.rmtree(pkg / "Resources" / "UsrBox.Entity")
                continue
            assert code == 2 and files(pkg) == before, (argv, out)


def test_toolkit_refusal_stops_the_write():
    import scaffold
    original = EntitySchema.errors
    EntitySchema.errors = lambda self: ["a refusal"]
    try:
        with package() as pkg:
            before = files(pkg)
            code, out = run("entity", str(pkg), "UsrBox", "--caption", "Box")
            assert code == 2 and "the toolkits refuse the result" in out and files(pkg) == before
    finally:
        EntitySchema.errors = original
    assert scaffold.EntitySchema.errors is original


def test_pages_warn_when_the_templates_package_is_not_a_dependency():
    flags = ["--caption", "Shipment", "--pages", "--dry-run"]
    with package() as pkg:
        code, out = run("entity", str(pkg), "UsrShipment", *flags)
        assert code == 0 and "warning: the page templates live in CrtUIPlatform" in out and "deps UsrPkg -e <env> --add CrtUIPlatform" in out, out
        code, out = run("entity", str(pkg), "UsrShipment", "--caption", "Shipment", "--dry-run")
        assert "warning:" not in out  # no pages, no warning
        text = (pkg / "descriptor.json").read_bytes().decode("utf-8")
        (pkg / "descriptor.json").write_bytes(text.replace('"Name": "CrtBase"', '"Name": "CrtUIPlatform"', 1).encode("utf-8"))
        code, out = run("entity", str(pkg), "UsrShipment", *flags)
        assert code == 0 and "warning:" not in out, out


def test_source_and_module():
    with package() as pkg:
        code, out = run("source", str(pkg), "UsrOrderRecalc", "--caption", "Order recalculation")
        assert code == 0 and "Schemas/UsrOrderRecalc/UsrOrderRecalc.cs" in out and "Resources/UsrOrderRecalc.SourceCode/resource.en-US.xml" in out, out
        sdir = pkg / "Schemas" / "UsrOrderRecalc"
        raw = {f.name: f.read_bytes() for f in sdir.iterdir()}
        assert set(raw) == {"UsrOrderRecalc.cs", "descriptor.json", "metadata.json", "properties.json"}
        for name in ("descriptor.json", "metadata.json", "properties.json"):  # the shape of the real ones
            assert raw[name].startswith(b"\xef\xbb\xbf") and b"\r\n" in raw[name] and not raw[name].endswith(b"\n"), name
        assert not raw["UsrOrderRecalc.cs"].startswith(b"\xef\xbb\xbf") and b"\n" not in raw["UsrOrderRecalc.cs"].replace(b"\r\n", b"")
        meta = json.loads(raw["metadata.json"].decode("utf-8-sig"))["MetaData"]["Schema"]
        assert list(meta) == ["ManagerName", "UId", "A2", "A5", "B1", "B2", "B3", "B6", "B8", "HD1"] and meta["HD1"] == "50e3acc0-26fc-4237-a095-849a1d534bd3"
        cs = CSharpSource(pkg, sdir / "UsrOrderRecalc.cs")
        assert cs.namespaces == ["Terrasoft.Configuration.UsrOrderRecalcNamespace"] and [t["name"] for t in cs.types] == ["UsrOrderRecalc"]
        assert [m["kind"] for m in cs.members()] == ["field", "constructor"], cs.members()
        assert describe_item(pkg, "UsrOrderRecalc", "topics") and "Order recalculation" in describe_package(pkg)

        code, out = run("source", str(pkg), "UsrOrderApi", "--caption", "Order API", "--service", "--cultures", "en-US,ru-RU")
        api = CSharpSource(pkg, pkg / "Schemas" / "UsrOrderApi" / "UsrOrderApi.cs")
        assert code == 0 and "[ServiceContract]" in api.text and ": BaseService" in api.text and [m["name"] for m in api.members() if m["kind"] == "method"] == ["Ping"]
        assert "using Terrasoft.Web.Common.ServiceRouting;" in api.text  # [DefaultServiceRoute] lives there: without it CS0246 (S40-T05)
        assert sorted(p.name for p in (pkg / "Resources" / "UsrOrderApi.SourceCode").iterdir()) == ["resource.en-US.xml", "resource.ru-RU.xml"]
        code, out = run("source", str(pkg), "UsrOrderApi", "--caption", "again")
        assert code == 2 and "exists" in out
        code, out = run("source", str(pkg), "bad name", "--caption", "x")
        assert code == 2 and "valid schema name" in out

        code, out = run("module", str(pkg), "UsrOrderMixin", "--mixin", "--caption", "Order mixin")
        assert code == 0 and "Schemas/UsrOrderMixin/UsrOrderMixin.less" in out and "Schemas/UsrOrderMixin/UsrOrderMixin.js" in out, out
        mixin = ClassicSchema(pkg, "UsrOrderMixin")
        assert mixin.kind == "module" and "Terrasoft.configuration.mixins.UsrOrderMixin" in mixin.body and mixin.resources.get("Caption") == "Order mixin"
        code, out = run("module", str(pkg), "UsrOrderMixin")
        assert code == 2 and "exists" in out


def test_new_schemas_stop_on_what_the_site_already_has():
    """scaffold asks like objects.py (S31-T12): a name the last `index --env` pass found on the site stops, --force goes on."""
    from creatio_schemas.describe import store
    from creatio_schemas.describe.index import index_path

    with package() as pkg:
        con = store.connect(index_path(pkg))
        con.executemany("insert into site_schemas values ('dev', '2026-11-21T08:00:00Z', ?, 'u', ?, 'UsrOtherPkg', ?)",
                        [("UsrRegion_FormPage", "page", "Region"), ("UsrRegionCalc", "source", "Calc"), ("UsrRegionModule", "client", "M")])
        con.commit()
        con.close()
        before = files(pkg)
        code, out = run("entity", str(pkg), "UsrRegion", "--caption", "Region", "--pages")
        assert code == 1 and "error: UsrRegion_FormPage exists on the site (dev, 2026-11-21) as page in package UsrOtherPkg" in out, out
        code, out = run("source", str(pkg), "UsrRegionCalc", "--caption", "Calc")
        assert code == 1 and "error: UsrRegionCalc exists on the site" in out, out
        code, out = run("module", str(pkg), "UsrRegionModule")
        assert code == 1 and "error: UsrRegionModule exists on the site" in out, out
        assert files(pkg) == before  # nothing written
        code, out = run("source", str(pkg), "UsrRegionCalc", "--caption", "Calc", "--force")
        assert code == 0 and "warning: UsrRegionCalc exists on the site (dev, 2026-11-21) as source in package UsrOtherPkg; --force given" in out, out


def test_the_scaffold_stamps_the_projects_platform_version():
    import json
    with package() as pkg:
        proj = pkg.parent / "project.json"
        proj.write_text(json.dumps({"environment": {"platformVersion": "8.3.2.4199"}}), encoding="utf-8")
        code, out = run("entity", str(pkg), "UsrBox", "--caption", "Box", "--pages", "--project", str(proj))
        assert code == 0, out
        for name in ("UsrBox", "UsrBox_FormPage"):
            props = json.loads((pkg / "Schemas" / name / "properties.json").read_text(encoding="utf-8-sig"))["Properties"]
            assert props["CreatedInVersion"] == "8.3.2.4199", (name, props)
        code, out = run("source", str(pkg), "UsrSvc", "--caption", "Svc", "--project", str(proj))
        assert code == 0 and '"B8": "8.3.2.4199"' in (pkg / "Schemas" / "UsrSvc" / "metadata.json").read_text(encoding="utf-8-sig"), out


def fake_clio(cmd, cwd=None, **kwargs):
    """clio's create-workspace and add-package: the csproj and the targets file of its template, and the placeholder class."""
    if cmd[1] == "add-package":
        files = Path(cwd) / "packages" / cmd[2] / "Files"
        (files / "cs").mkdir(parents=True)
        for n in (f"{cmd[2]}.csproj", "Directory.Build.targets", "cs/EmptyClass.cs"):
            (files / n).write_text("<Project />", encoding="utf-8")
    return subprocess.CompletedProcess(cmd, 0, "Done", "")


def test_package_builds_an_assembly_package_and_refuses_an_existing_folder():
    """S52-T05: Type 1, ProjectPath, the DependsOn entry read from the dependency's descriptor, the folders, the csproj, no placeholder."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        shutil.copytree(PAGES, ws / "packages" / "CrtCoreBase")
        dep = json.loads((ws / "packages" / "CrtCoreBase" / "descriptor.json").read_text(encoding="utf-8-sig"))["Descriptor"]
        dep.update(UId="00000000-0000-4000-8000-000000000001", Name="CrtCoreBase", PackageVersion="7.8.0")
        (ws / "packages" / "CrtCoreBase" / "descriptor.json").write_text(json.dumps({"Descriptor": dep}), encoding="utf-8")
        assert create_package(ws, "UsrNew", "Customer", ["CrtCoreBase"], dry_run=True)[0] == "descriptor.json" and not (ws / "packages" / "UsrNew").exists()
        create_package(ws, "UsrNew", "Customer", ["CrtCoreBase"], run=fake_clio)
        pkg = ws / "packages" / "UsrNew"
        raw = (pkg / "descriptor.json").read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
        d = json.loads(raw.decode("utf-8-sig"))["Descriptor"]
        assert d["Type"] == 1 and d["ProjectPath"] == "Files/UsrNew.csproj" and d["Name"] == "UsrNew" and d["PackageVersion"] == "7.8.0", d
        assert d["DependsOn"] == [{"UId": "00000000-0000-4000-8000-000000000001", "PackageVersion": "7.8.0", "Name": "CrtCoreBase"}], d
        assert all((pkg / f).is_dir() for f in ("Schemas", "Data", "Resources", "SqlScripts", "Files/cs"))
        assert (pkg / "Files" / "UsrNew.csproj").is_file() and (pkg / "Files" / "Directory.Build.targets").is_file()
        assert not list(pkg.rglob("EmptyClass.cs")) and not list((pkg / "Files" / "cs").iterdir())
        before = files(pkg)
        try:
            create_package(ws, "UsrNew", "Customer", [], run=fake_clio)
            raise AssertionError("an existing folder must be refused")
        except FileExistsError as e:
            assert str(e).startswith("exists: ")
        assert files(pkg) == before
        # a dependency neither in the workspace nor on the site stops with its name and leaves no folder; the site answers the rest
        for rows, why in ((None, "no environment"), (lambda sql: [], "not on the site")):
            try:
                create_package(ws, "UsrOther", "Customer", ["CrtBase"], rows, run=fake_clio)
                raise AssertionError(why)
            except ValueError as e:
                assert str(e).startswith("stop: dependency CrtBase "), e
        assert not (ws / "packages" / "UsrOther").exists()
        site = lambda sql: [{"Name": "CrtBase", "UId": "00000000-0000-4000-8000-000000000002", "Version": "7.8.1"}]
        create_package(ws, "UsrOther", "Customer", ["CrtBase"], site, run=fake_clio)
        d = json.loads((ws / "packages" / "UsrOther" / "descriptor.json").read_bytes().decode("utf-8-sig"))["Descriptor"]
        assert d["DependsOn"][0]["UId"].endswith("0002") and d["DependsOn"][0]["PackageVersion"] == "7.8.1"


if __name__ == "__main__":
    for fn in [v for k, v in list(globals().items()) if k.startswith("test_")]:
        fn()
        print("ok", fn.__name__)
