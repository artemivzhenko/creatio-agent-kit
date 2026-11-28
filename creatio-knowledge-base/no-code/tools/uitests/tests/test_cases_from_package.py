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
from creatio_schemas.cases import HEADER_START, Stop, cases_from_package, coverage_report, page_case, sample, tests_root  # noqa: E402
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
        assert "wrote UsrPkg/integration/UsrOrder.act" in report and "wrote UsrPkg/integration/UsrProcess_0d4c445.act" in report
        assert "wrote UsrPkg/integration/UsrProcess_0d4c445.json" in report and "wrote UsrPkg/pages/UsrOrderForm.json" in report
        case = (out / "UsrPkg" / "integration" / "UsrOrder.act").read_text(encoding="utf-8").splitlines()
        assert case[0].startswith(HEADER_START) and case[1] == "# schema: UsrOrder" and "use Supervisor" in case
        assert any(l.startswith("insert UsrOrder as R set UsrName=UsrName") and "UsrEmail=test" in l for l in case)  # the required columns only
        assert "check-record UsrOrder Id=$R exists" in case and "delete UsrOrder $R" in case
        update = next(l for l in case if l.startswith("update UsrOrder $R set "))
        assert f"check-record UsrOrder Id=$R has {update.split()[4].split('=')[0]} eq {update.split('=')[1]}" in case
        process = (out / "UsrPkg" / "integration" / "UsrProcess_0d4c445.act").read_text(encoding="utf-8")
        assert "start UsrProcess_0d4c445" in process and process.startswith(HEADER_START)
        assert '"parameters"' in (out / "UsrPkg" / "integration" / "UsrProcess_0d4c445.json").read_text(encoding="utf-8")
        # a page whose form lacks the required columns is a stop, in the case and in the report, never a guess
        assert "stop UsrOrder_FormPage: required column UsrName is not an element of UsrOrder_FormPage" in report
        assert "# stop: required column UsrName" in (out / "UsrPkg" / "e2e" / "UsrOrder_FormPage.act").read_text(encoding="utf-8")
        page_file = (out / "UsrPkg" / "pages" / "UsrOrderForm.json").read_text(encoding="utf-8")
        assert '"SaveButton"' in page_file
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_edited_case_survives_a_second_run():
    tmp = Path(tempfile.mkdtemp())
    try:
        pkg, out = package(tmp), tmp / "out"
        cases_from_package(pkg, out)
        edited = out / "UsrPkg" / "integration" / "UsrOrder.act"
        edited.write_text(edited.read_text(encoding="utf-8").replace(HEADER_START, "# mine"), encoding="utf-8")
        regenerated = out / "UsrPkg" / "integration" / "UsrPkg.act"
        regenerated.write_text(regenerated.read_text(encoding="utf-8") + "# appended\n", encoding="utf-8")
        report = cases_from_package(pkg, out)
        assert "kept UsrPkg/integration/UsrOrder.act (edited: no generated header)" in report
        assert "wrote UsrPkg/integration/UsrPkg.act" in report and "# appended" not in regenerated.read_text(encoding="utf-8")  # still generated: rewritten
        assert edited.read_text(encoding="utf-8").startswith("# mine")
        assert "same UsrPkg/integration/UsrProcess_0d4c445.json" in report
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
        assert code == 1 and "stop UsrOrder_FormPage" in printed.getvalue() and (out / "UsrPkg" / "integration" / "UsrOrder.act").is_file()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_root_layout_is_the_test_utilitys_own_root():
    tmp = Path(tempfile.mkdtemp())
    try:
        report = cases_from_package(package(tmp), tmp / "out", layout="root")
        assert "wrote Cases/UsrPkg/UsrOrder.act" in report and "wrote ProcessCases/UsrPkg/UsrProcess_0d4c445.act" in report
        assert "wrote Configuration/pages/UsrOrderForm.json" in report and "wrote Configuration/processes/UsrProcess_0d4c445.json" in report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_coverage_report_counts_the_cases_per_schema_and_names_what_is_not_covered():
    tmp = Path(tempfile.mkdtemp())
    try:
        pkg, out = package(tmp), tmp / "out"
        cases_from_package(pkg, out)
        unit = out / "UsrPkg" / "unit"
        unit.mkdir()
        (unit / "UsrOrderStatusTests.cs").write_text("// a test", encoding="utf-8")  # counted by its file name
        (out / "UsrPkg" / "e2e" / "hand.act").write_text("# my case" + chr(10) + "# schema: UsrPkg, UsrOrder" + chr(10), encoding="utf-8")  # counted by its header
        (pkg / "Files" / "cs").mkdir(parents=True)
        (pkg / "Files" / "cs" / "UsrHelper.cs").write_text("class UsrHelper {}", encoding="utf-8")
        lines = coverage_report(pkg, out)
        assert "UsrOrder (object): unit 0 | integration 1 | e2e 1" in lines and "UsrOrderStatus (object): unit 1 | integration 1 | e2e 0" in lines
        assert "UsrPkg (object): unit 0 | integration 1 | e2e 1" in lines
        assert "UsrOrder_FormPage (page): unit 0 | integration 0 | e2e 1" in lines  # the generator's page case, even though it holds a stop
        assert "UsrProcess_0d4c445 (process): unit 0 | integration 1 | e2e 0" in lines
        assert [l for l in lines if l.startswith("not covered")] == ["not covered: UsrHelper (class)"] and lines[-1] == "covered 6 of 7"
        # the same through the command line: no file is written, the exit code is 0
        before = sorted(p for p in out.rglob("*"))
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = main(["cases-from-package", str(pkg), "--out", str(out), "--report"])
        assert code == 0 and "covered 6 of 7" in printed.getvalue() and before == sorted(p for p in out.rglob("*"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_out_defaults_to_the_workspace_tests_folder_of_the_project():
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "project.json").write_text('{"package": {"workspace": "ws"}}', encoding="utf-8")
        assert tests_root(tmp / "project.json") == tmp.resolve() / "ws" / "tests"
        (tmp / "empty.json").write_text("{}", encoding="utf-8")
        try:
            tests_root(tmp / "empty.json")
        except ValueError as e:
            assert "package.workspace" in str(e)
        else:
            raise AssertionError("expected ValueError")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
