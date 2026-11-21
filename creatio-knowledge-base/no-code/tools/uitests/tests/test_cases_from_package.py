"""cases-from-package on fixture packages: python tests/test_cases_from_package.py (no site; a fake env answers the lookup)."""

import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE.parent))

from creatio_schemas import EntitySchema  # noqa: E402
from creatio_schemas.cases import HEADER_START, Stop, cases_from_package, page_case, sample  # noqa: E402
from creatio_schemas.page.schema import PageSchema  # noqa: E402
from uitests import main  # noqa: E402

PAGES = TOOLS / "pages" / "tests" / "fixtures" / "UsrPkg"
PROCS = TOOLS / "process" / "tests" / "fixtures" / "UsrPkg"


def package(tmp: Path) -> Path:
    """The pages fixture (objects UsrOrder, UsrOrderStatus, UsrPkg and two form pages) plus a process from the process fixture."""
    pkg = tmp / "UsrPkg"
    shutil.copytree(PAGES, pkg)
    name = "UsrProcess_0d4c445"
    shutil.copytree(PROCS / "Schemas" / name, pkg / "Schemas" / name)
    shutil.copytree(PROCS / "Resources" / (name + ".Process"), pkg / "Resources" / (name + ".Process"))
    return pkg


class FakeEnv:
    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def odata(self, entity, select=None, filter=None, top=None):
        self.asked.append(entity)
        return self.rows.get(entity, [])


def test_an_object_a_process_and_a_page_give_their_cases_and_configuration():
    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / "out"
        report = cases_from_package(package(tmp), out)
        assert "wrote Cases/UsrPkg/UsrOrder.act" in report and "wrote ProcessCases/UsrPkg/UsrProcess_0d4c445.act" in report
        assert "wrote Configuration/processes/UsrProcess_0d4c445.json" in report and "wrote Configuration/pages/UsrOrderForm.json" in report
        case = (out / "Cases" / "UsrPkg" / "UsrOrder.act").read_text(encoding="utf-8").splitlines()
        assert case[0].startswith(HEADER_START) and "use Supervisor" in case
        assert any(l.startswith("insert UsrOrder as R set UsrName=UsrName") and "UsrEmail=test" in l for l in case)  # the required columns only
        assert "check-record UsrOrder Id=$R exists" in case and "delete UsrOrder $R" in case
        update = next(l for l in case if l.startswith("update UsrOrder $R set "))
        assert f"check-record UsrOrder Id=$R has {update.split()[4].split('=')[0]} eq {update.split('=')[1]}" in case
        process = (out / "ProcessCases" / "UsrPkg" / "UsrProcess_0d4c445.act").read_text(encoding="utf-8")
        assert "start UsrProcess_0d4c445" in process and process.startswith(HEADER_START)
        assert '"parameters"' in (out / "Configuration" / "processes" / "UsrProcess_0d4c445.json").read_text(encoding="utf-8")
        # a page whose form lacks the required columns is a stop, in the case and in the report, never a guess
        assert "stop UsrOrder_FormPage: required column UsrName is not an element of UsrOrder_FormPage" in report
        assert "# stop: required column UsrName" in (out / "Cases" / "UsrPkg" / "UsrOrder_FormPage.act").read_text(encoding="utf-8")
        page_file = (out / "Configuration" / "pages" / "UsrOrderForm.json").read_text(encoding="utf-8")
        assert '"SaveButton"' in page_file
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_edited_case_survives_a_second_run():
    tmp = Path(tempfile.mkdtemp())
    try:
        pkg, out = package(tmp), tmp / "out"
        cases_from_package(pkg, out)
        edited = out / "Cases" / "UsrPkg" / "UsrOrder.act"
        edited.write_text(edited.read_text(encoding="utf-8").replace(HEADER_START, "# mine"), encoding="utf-8")
        regenerated = out / "Cases" / "UsrPkg" / "UsrPkg.act"
        regenerated.write_text(regenerated.read_text(encoding="utf-8") + "# appended\n", encoding="utf-8")
        report = cases_from_package(pkg, out)
        assert "kept Cases/UsrPkg/UsrOrder.act (edited: no generated header)" in report
        assert "wrote Cases/UsrPkg/UsrPkg.act" in report and "# appended" not in regenerated.read_text(encoding="utf-8")  # still generated: rewritten
        assert edited.read_text(encoding="utf-8").startswith("# mine")
        assert "same Configuration/processes/UsrProcess_0d4c445.json" in report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_lookup_needs_env_or_it_is_a_stop():
    column = {"A2": "UsrStatus", "S2": "x"}
    try:
        sample(column, "Lookup", None, ref="UsrOrderStatus")
    except Stop as e:
        assert str(e) == "lookup UsrStatus: no value - give --env or edit"
    else:
        raise AssertionError("expected Stop")
    env = FakeEnv({"UsrOrderStatus": [{"Id": "11111111-1111-4111-8111-111111111111"}]})
    cache = {}
    assert sample(column, "Lookup", env, cache, ref="UsrOrderStatus") == "11111111-1111-4111-8111-111111111111"
    sample(column, "Lookup", env, cache, ref="UsrOrderStatus")
    assert env.asked == ["UsrOrderStatus"]  # one read per object
    try:
        sample(column, "Lookup", FakeEnv({}), ref="UsrEmpty")
    except Stop as e:
        assert "UsrEmpty has no row" in str(e)
    else:
        raise AssertionError("expected Stop")
    assert sample({"A2": "UsrN"}, "Integer") == "1" and sample({"A2": "UsrM"}, "Money") == "100" and sample({"A2": "UsrB"}, "Boolean") == "false"
    try:
        sample({"A2": "UsrBlob"}, "Binary")
    except Stop as e:
        assert "no sample value for type Binary" in str(e)
    else:
        raise AssertionError("expected Stop")


def test_a_page_that_shows_the_required_columns_gets_a_full_case():
    tmp = Path(tempfile.mkdtemp())
    try:
        pkg = package(tmp)
        entity, page = EntitySchema(pkg, "UsrOrder"), PageSchema(pkg, "UsrOrder_FormPage")
        elements = [{"code": "UsrName", "label": "Name", "type": "Text"}, {"code": "UsrEmail", "label": "Email", "type": "Email"},
                    {"code": "SaveButton", "label": "Save", "type": "Button"}]
        text, stops = page_case(page, entity, "UsrOrderForm", "Supervisor", {"elements": elements})
        lines = text.splitlines()
        assert stops == [] and "open UsrOrderForm" in lines and "click SaveButton" in lines
        assert any(l.startswith('set UsrName "UsrName') for l in lines) and any(l.startswith('set UsrEmail "test') for l in lines)
        assert any(l.startswith("check-record UsrOrder UsrName=UsrName") and l.endswith(" exists") for l in lines)
        assert any(l.startswith("delete-record UsrOrder UsrName=") for l in lines)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_command_line_reports_and_exits_one_on_a_stop():
    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / "out"
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = main(["cases-from-package", str(package(tmp)), "--out", str(out)])
        assert code == 1 and "stop UsrOrder_FormPage" in printed.getvalue() and (out / "Cases" / "UsrPkg" / "UsrOrder.act").is_file()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
