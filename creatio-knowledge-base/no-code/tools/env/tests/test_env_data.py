"""Checks for data.py and creatio_schemas/testdata.py (S38):  python tests/test_env_data.py  (a scripted sql; no site, made-up rows)."""

import contextlib
import importlib.util
import io
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))

from creatio_schemas import testdata  # noqa: E402

DRAFT = "5d2a1c3e-0000-4000-8000-000000000001"
DONE = "5d2a1c3e-0000-4000-8000-000000000002"
PERSON = "5d2a1c3e-0000-4000-8000-000000000003"
GONE = "5d2a1c3e-0000-4000-8000-000000000009"
ORDER1 = "5d2a1c3e-0000-4000-8000-000000000004"
ORDER2 = "5d2a1c3e-0000-4000-8000-000000000005"


class FakeEnv:
    """sql() answers with the rows of the first needle (longest first) the statement contains; every statement is kept."""

    def __init__(self, answers):
        self.answers, self.statements = answers, []

    def sql(self, text, counts=None):
        self.statements.append(text)
        for needle in sorted(self.answers, key=len, reverse=True):
            if needle in text:
                rows = self.answers[needle]
                return rows(text) if callable(rows) else rows
        raise RuntimeError("sql: [ERR] - 42P01: nothing scripted")


def col(name, kind="character varying", nullable="YES", default="''::character varying", length="250"):
    return {"column": name, "type": kind, "length": length if kind == "character varying" else None, "nullable": nullable, "default": default}


def table(name):
    return f"table_name = '{name}' order by ordinal_position"


def fk(name):
    return f"kcu.table_name = '{name}'"


SYSTEM_COLUMNS = [col("Id", "uuid", "NO", None), col("CreatedOn", "timestamp without time zone", "YES", None),
                  col("CreatedById", "uuid", "YES", None), col("ProcessListeners", "integer", "NO", "0")]
STATUS = SYSTEM_COLUMNS + [col("Name"), col("Code", length="50"), col("Description", length="500")]


def raises(fn, kind, text=""):
    try:
        fn()
    except kind as e:
        assert text in str(e), (text, str(e))
        return
    raise AssertionError(f"expected {kind.__name__}")


def test_lookup_values_ordered_by_name_with_code_description_and_the_page_tail():
    long = "A status the order takes after the warehouse confirmed every line of it and the invoice"
    e = FakeEnv({table("UsrOrderStatus"): STATUS, "count(*)": [{"n": 3}],
                 'from "UsrOrderStatus" order by': [{"Id": DONE, "Name": "Done", "Code": "D", "Description": long}, {"Id": DRAFT, "Name": "Draft", "Code": "", "Description": ""}]})
    text = testdata.lookup_values(e, "UsrOrderStatus", limit=2)
    assert text.splitlines() == ["UsrOrderStatus: 3 rows", f"{DONE}  Done  D  {long[:57]}...", f"{DRAFT}  Draft",
                                 "  ... 1 more; next: offset=2; add limit=0 for all"], text
    assert 'select "Id", "Name", "Code", "Description" from "UsrOrderStatus" order by "Name", "Id" offset 0 limit 2' in e.statements[-1]
    plain = FakeEnv({table("UsrKind"): SYSTEM_COLUMNS + [col("Name")], "count(*)": [{"n": 1}], 'from "UsrKind" order by': [{"Id": DRAFT, "Name": "Small"}]})
    assert testdata.lookup_values(plain, "UsrKind", limit=0) == f"UsrKind: 1 rows\n{DRAFT}  Small"  # no Code column: two cells, no tail
    assert plain.statements[-1].endswith('order by "Name", "Id" offset 0')  # limit 0: every row


def test_lookup_values_names_a_missing_table_and_the_usr_hint():
    e = FakeEnv({table("UsrOrderStatus"): STATUS, "information_schema.columns": []})
    raises(lambda: testdata.lookup_values(e, "OrderStatus"), KeyError, 'no table "OrderStatus" on the site; UsrOrderStatus exists - did you mean it?')
    raises(lambda: testdata.lookup_values(e, "UsrNoSuch"), KeyError, 'no table "UsrNoSuch" on the site')
    assert not any("UsrUsrNoSuch" in s for s in e.statements)  # a Usr name gets no second guess
    e = FakeEnv({table("UsrOrder"): SYSTEM_COLUMNS + [col("UsrNumber")]})
    raises(lambda: testdata.lookup_values(e, "UsrOrder"), KeyError, "has no Name column: not a lookup")


ORDER = SYSTEM_COLUMNS + [col("UsrNumber"), col("UsrAmount", "numeric", "NO", "0"), col("UsrStatusId", "uuid", "YES", None),
                          col("UsrContactId", "uuid", "YES", None), col("UsrOwnerId", "uuid", "YES", None)]
ORDER_FK = [{"table": "UsrOrder", "column": "UsrStatusId", "ref_table": "UsrOrderStatus"},
            {"table": "UsrOrder", "column": "UsrContactId", "ref_table": "Contact"},
            {"table": "UsrOrder", "column": "UsrOwnerId", "ref_table": "Contact"}]
ROWS = [{"Id": ORDER1, "CreatedOn": "2026-11-20T10:00:00", "CreatedById": PERSON, "ProcessListeners": 0, "UsrNumber": "N-2", "UsrAmount": 10,
         "UsrStatusId": DRAFT, "UsrContactId": PERSON, "UsrOwnerId": GONE},
        {"Id": ORDER2, "CreatedOn": "2026-11-19T10:00:00", "CreatedById": PERSON, "ProcessListeners": 0, "UsrNumber": "", "UsrAmount": 5,
         "UsrStatusId": None, "UsrContactId": None, "UsrOwnerId": None}]


def sample_env():
    return FakeEnv({table("UsrOrder"): ORDER, fk("UsrOrder"): ORDER_FK, table("UsrOrderStatus"): STATUS,
                    'select * from "UsrOrder"': ROWS, "column_name = 'Name'": [{"table": "UsrOrderStatus"}, {"table": "Contact"}],
                    'as "table", "Id", "Name" from': [{"table": "UsrOrderStatus", "Id": DRAFT, "Name": "Draft"},
                                                      {"table": "Contact", "Id": PERSON, "Name": "Test Person"}]})


def test_sample_records_names_the_lookups_shows_a_dangling_id_and_hides_the_system_columns():
    e = sample_env()
    text = testdata.sample_records(e, "UsrOrder", n=2)
    assert 'select * from "UsrOrder" order by "CreatedOn" desc nulls last, "Id" limit 2' in e.statements
    lines = text.splitlines()
    assert lines[:7] == ["UsrOrder: 2 record(s) (the newest by CreatedOn)", f"UsrOrder {ORDER1}", "  UsrNumber (text) = N-2", "  UsrAmount (numeric) = 10",
                         f"  UsrStatusId (lookup UsrOrderStatus) = Draft ({DRAFT})", f"  UsrContactId (lookup Contact) = Test Person ({PERSON})",
                         f"  UsrOwnerId (lookup Contact) = {GONE} (no row)"], text
    assert '  UsrNumber (text) = ""' in lines and "  UsrStatusId (lookup UsrOrderStatus) = null" in lines
    assert lines[-1] == "columns: 5, lookups resolved: 2" and "CreatedOn (" not in text and "ProcessListeners" not in text
    names = [s for s in e.statements if 'as "table", "Id", "Name" from' in s]
    assert len(names) == 1 and names[0].count(" union all ") == 1 and len(e.statements) == 5, e.statements  # columns, select, fks, Name check, names
    shown = testdata.sample_records(e, "UsrOrder", n=1, columns="CreatedOn,CreatedBy")  # a lookup named without its Id suffix
    assert "  CreatedOn (datetime) = 2026-11-20T10:00:00" in shown and "  CreatedById (lookup Contact)" not in shown  # no foreign key scripted for it
    assert "  CreatedById (uuid) = " + PERSON in shown and shown.splitlines()[-1] == "columns: 7, lookups resolved: 2" and "ProcessListeners" not in shown


def test_sample_records_filter_is_one_reading_fragment():
    e = sample_env()
    assert testdata.sample_records(e, "UsrOrder", filter='"UsrAmount" > 1', n=99).startswith('UsrOrder: 2 record(s) where "UsrAmount" > 1')
    assert 'select * from "UsrOrder" where ("UsrAmount" > 1) order by "CreatedOn" desc nulls last, "Id" limit 50' in e.statements  # n capped at 50
    raises(lambda: testdata.sample_records(e, "UsrOrder", filter='"UsrAmount" > 1; delete from "UsrOrder"'), ValueError, "no ';'")
    raises(lambda: testdata.sample_records(e, "UsrOrder", filter='"Id" in (delete from "UsrOrder" returning "Id")'), ValueError, "'delete' is a writing word")
    assert "where \"UsrNumber\" = 'update me'" in testdata.sample_records(e, "UsrOrder", filter="\"UsrNumber\" = 'update me'")  # a word in a literal is a value
    assert "where \"UsrNumber\" = 'a; b'" in testdata.sample_records(e, "UsrOrder", filter="\"UsrNumber\" = 'a; b'")  # so is a ';'
    e.answers["information_schema.columns"] = []
    raises(lambda: testdata.sample_records(e, "Order"), KeyError, 'no table "Order" on the site; UsrOrder exists')


FIXTURE_ORDER = SYSTEM_COLUMNS + [col("UsrName", nullable="NO", default=None, length="50"), col("UsrAmount", "numeric", "NO", None),
                                  col("UsrDue", "date", "NO", None), col("UsrStatusId", "uuid", "NO", None), col("UsrContactId", "uuid", "NO", None),
                                  col("UsrNotes"), col("UsrDone", "boolean", "NO", "false")]
FIXTURE_CONTACT = SYSTEM_COLUMNS + [col("Name", nullable="NO", default=None), col("AccountId", "uuid", "NO", None)]


def fixture_env():
    return FakeEnv({table("UsrOrder"): FIXTURE_ORDER, table("Contact"): FIXTURE_CONTACT, table("Account"): SYSTEM_COLUMNS + [col("Name")],
                    fk("UsrOrder"): [{"table": "UsrOrder", "column": "UsrStatusId", "ref_table": "UsrOrderStatus"},
                                     {"table": "UsrOrder", "column": "UsrContactId", "ref_table": "Contact"}],
                    fk("Contact"): [{"table": "Contact", "column": "AccountId", "ref_table": "Account"}],
                    "with recursive up": lambda text: [{"table": "UsrOrderStatus"}] if "'UsrOrderStatus'" in text else [],
                    'from "UsrOrderStatus" order by "Name", "Id" limit 1': [{"Id": DRAFT, "Name": "Draft"}]})


def test_make_fixture_prints_the_insert_block_with_a_lookup_a_reference_and_a_chain_comment():
    e = fixture_env()
    today = date.today().isoformat()
    text = testdata.make_fixture(e, "UsrOrder", alias="A", columns="UsrNotes")
    assert text.splitlines() == [
        "# Account: set by hand, Contact needs Account",
        "insert Contact as UsrContact set Name=Name UsrContact",
        "# UsrStatus = Draft (the first UsrOrderStatus by Name)",
        f"insert UsrOrder as A set UsrName=UsrName A;UsrAmount=1;UsrDue={today};UsrStatus={DRAFT};UsrContact=$UsrContact;UsrNotes=UsrNotes A",
        "# the end of the case: delete what the block inserted, newest first", "delete UsrOrder $A", "delete Contact $UsrContact",
        "columns: 5 required (database), 1 lookups resolved, 1 references inserted"], text
    assert "UsrDone" not in text  # NOT NULL with a default: the site fills it
    assert not any(s.lstrip().lower().startswith(("insert", "update", "delete")) for s in e.statements)  # it only reads
    short = testdata.make_fixture(fixture_env(), "UsrOrder", alias="B")
    assert "UsrNotes" not in short and "UsrName=UsrName B" in short  # without columns=: the required ones only


def test_make_fixture_edge_cases():
    e = FakeEnv({table("UsrNote"): SYSTEM_COLUMNS + [col("UsrText", length="5"), col("Name", length="250")], fk("UsrNote"): []})
    assert testdata.make_fixture(e, "UsrNote", alias="N").splitlines()[0] == "insert UsrNote as N set Name=Name N"  # nothing required: Name
    assert testdata.make_fixture(e, "UsrNote", alias="N", columns="UsrText").splitlines()[0] == "insert UsrNote as N set Name=Name N;UsrText=UsrTe"  # the caption stays, the text cut to 5
    e = FakeEnv({table("UsrCut"): SYSTEM_COLUMNS + [col("UsrCode", nullable="NO", default=None, length="5"), col("UsrBlob", "bytea", "NO", None),
                                                    col("UsrAt", "timestamp without time zone", "NO", None)], fk("UsrCut"): []})
    text = testdata.make_fixture(e, "UsrCut")
    assert "# UsrBlob: set by hand, no sample for type bytea" in text and f"UsrCode=UsrCo;UsrAt={date.today().isoformat()}T12:00:00Z" in text
    e = FakeEnv({table("UsrTree"): SYSTEM_COLUMNS + [col("UsrParentId", "uuid", "NO", None)], fk("UsrTree"): [{"table": "UsrTree", "column": "UsrParentId", "ref_table": "UsrTree"}],
                 "with recursive up": []})
    assert testdata.make_fixture(e, "UsrTree").splitlines() == ["# UsrParent: set by hand, UsrTree needs UsrTree",
                                                                    "# insert UsrTree as A: no column a sample can be written to - set by hand",
                                                                    "columns: 1 required (database), 0 lookups resolved, 0 references inserted"]  # nothing inserted, nothing to delete
    raises(lambda: testdata.make_fixture(e, "UsrTree", alias="$A"), ValueError, "must be a name")


def workspace_with_order(required_in_metadata=True):
    """A one-package workspace whose UsrOrder marks UsrName, UsrNumber (text) and UsrStatus (lookup) required; the table keeps them nullable."""
    import json
    import tempfile
    pkg = Path(tempfile.mkdtemp()) / "packages" / "UsrPkg"
    schema = pkg / "Schemas" / "UsrOrder"
    schema.mkdir(parents=True)
    (pkg / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": "7d1af160-6bd7-46aa-9884-deb78ed6a6df", "Name": "UsrPkg"}}), encoding="utf-8")
    (schema / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": "6f5a53ad-3796-4386-b381-2730e76d3a4a", "Name": "UsrOrder", "ManagerName": "EntitySchemaManager",
                                                                       "Parent": {"UId": "1bab9dcf-17d5-49f8-9536-8e0064f1dce0", "Name": "BaseEntity"}}}), encoding="utf-8")
    req = {"E2": 1} if required_in_metadata else {}
    cols = [{"UId": f"00000000-0000-0000-0000-00000000000{i}", "A2": n, "S2": "x", **req, **s} for i, (n, s) in enumerate(
        (("UsrName", {}), ("UsrNumber", {}), ("UsrStatus", {"S4": "9" * 8 + "-0000-0000-0000-000000000000"}), ("UsrNotes", {"E2": 0})), 1)]
    (schema / "metadata.json").write_text(json.dumps({"MetaData": {"Schema": {"UId": "6f5a53ad-3796-4386-b381-2730e76d3a4a", "A2": "UsrOrder", "D2": cols}}}), encoding="utf-8")
    return pkg.parent.parent


def test_make_fixture_takes_the_required_columns_from_the_workspace_metadata():
    nullable = SYSTEM_COLUMNS + [col("UsrName", length="50"), col("UsrNumber", length="50"), col("UsrStatusId", "uuid"), col("UsrNotes"), col("UsrAmount", "numeric")]
    e = FakeEnv({table("UsrOrder"): nullable, fk("UsrOrder"): [{"table": "UsrOrder", "column": "UsrStatusId", "ref_table": "UsrOrderStatus"}],
                 "with recursive up": [{"table": "UsrOrderStatus"}], 'from "UsrOrderStatus" order by "Name", "Id" limit 1': [{"Id": DRAFT, "Name": "Draft"}]})
    ws = workspace_with_order()
    text = testdata.make_fixture(e, "UsrOrder", workspace=str(ws))
    assert f"insert UsrOrder as A set UsrName=UsrName A;UsrNumber=UsrNumber A;UsrStatus={DRAFT}" in text and "UsrNotes" not in text, text
    assert text.splitlines()[-1] == "columns: 3 required (workspace), 1 lookups resolved, 0 references inserted", text
    assert testdata.make_fixture(e, "UsrOrder", workspace=str(workspace_with_order(False))).splitlines()[-1].startswith("columns: 0 required (workspace)")
    plain = testdata.make_fixture(e, "UsrOrder")  # no workspace: the database rule, as before
    assert plain.splitlines()[-1].startswith("columns: 0 required (database)") and "UsrNumber" not in plain
    other = testdata.make_fixture(e, "UsrOrder", workspace=str(ws / "packages"))  # a folder of packages works too
    assert "(workspace)" in other
    e.answers['from "UsrOrderStatus" order by "Name", "Id" limit 1'] = []
    assert "# UsrStatus: no rows - insert one first (UsrOrderStatus is empty)" in testdata.make_fixture(e, "UsrOrder", workspace=str(ws))


def test_data_cli():
    mod_spec = importlib.util.spec_from_file_location("data_cli", HERE.parent / "data.py")
    mod = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(mod)
    for argv, env, code, needle in ((["fixture", "-e", "dev", "UsrOrder"], fixture_env(), 0, "insert UsrOrder as A set"),
                                    (["sample", "-e", "dev", "UsrOrder", "--filter", "1=1; drop"], sample_env(), 2, "error: filter must be one where fragment"),
                                    (["lookup-values", "-e", "dev", "UsrOrderStatus"], FakeEnv({}), 1, "error: sql: [ERR]")):
        out = io.StringIO()
        mod.open_environment = lambda name, project, **kw: env
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            assert mod.main(argv) == code, out.getvalue()
        assert needle in out.getvalue(), out.getvalue()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
