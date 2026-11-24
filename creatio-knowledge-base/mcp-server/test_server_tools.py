"""MCP push tool checks with a temporary fixture and no environment."""

import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CREATIO_KB_STATS_DIR", tempfile.mkdtemp(prefix="kb-stats-"))  # the calls below must not write the real .stats/

import server

TOOLS = Path(__file__).resolve().parent.parent / "no-code" / "tools"
sys.path.insert(0, str(TOOLS / "push" / "tests"))
from test_push_tools import FakeClio, add_process  # noqa: E402

push_module = importlib.import_module("creatio_schemas.push")


def test_dry_run_uses_the_library_without_starting_processes():
    source = next(p for p in (TOOLS / "process" / "tests" / "fixtures").iterdir()
                  if (p / "descriptor.json").is_file())
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "UsrPkg"
        shutil.copytree(source, pkg)
        add_process(pkg)
        fake = FakeClio()
        with patch.object(push_module, "Clio", return_value=fake), \
             patch.object(push_module.subprocess, "run", side_effect=AssertionError("dry run started a process")):
            output = server.push_package(str(pkg), "dev", dry_run=True)
        assert not fake.calls
        for cmd in ("execute-sql-script", "push-pkg", "last-compilation-log", "compile-configuration"):
            assert "clio " + cmd in output, output
        assert output.endswith("exit code 0"), output


def test_a_package_name_is_found_through_the_project_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "ws" / "packages" / "UsrPkg"
        pkg.mkdir(parents=True)
        (pkg / "descriptor.json").write_text("{}", encoding="utf-8")
        project = Path(tmp) / "project.json"
        project.write_text('{"paths": {"workspace": "ws"}}', encoding="utf-8")
        seen = []
        with patch.object(push_module, "Clio", return_value=FakeClio()), \
             patch.object(push_module, "push", side_effect=lambda package, *a, **k: seen.append(package) or 0):
            assert server.push_package("UsrPkg", "dev", project=str(project)).endswith("exit code 0")
            assert server.push_package("UsrNone", "dev", project=str(project)).startswith("error: package must be a folder")
        assert seen == [pkg]


def test_invalid_arguments_are_refused_before_calling_clio():
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(push_module, "Clio", side_effect=AssertionError("Clio must not start")):
            assert server.push_package(tmp, "dev").startswith("error:")
            (Path(tmp) / "descriptor.json").write_text("{}", encoding="utf-8")
            assert server.push_package(tmp, "  ").startswith("error:")


def test_v2_options_are_forwarded_and_failure_reason_survives():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp)
        (pkg / "descriptor.json").write_text("{}", encoding="utf-8")
        def fake_push(package, env, clio, probe, dry_run, log, **kwargs):
            assert package == pkg and env == "dev" and probe and dry_run
            assert kwargs == {
                "project": Path("project.json"), "tasks": Path("tasks"), "task": Path("tasks/UsrTask"),
                "force": True, "baseline": Path("baseline.txt"), "skip_drift": True,
                "skip_foreign_files": True, "skip_sql_dates": True, "skip_compile_package": True,
                "allow_removed": ["UsrGone", "UsrOld"],
            }
            log("push FAILED at compilation: new errors")
            return 1
        with patch.object(push_module, "Clio", return_value=FakeClio()), patch.object(push_module, "push", side_effect=fake_push):
            output = server.push_package(str(pkg), "dev", True, True, "project.json", "tasks", "tasks/UsrTask",
                                         True, "baseline.txt", True, True, True, True, "UsrGone,UsrOld")
        assert "new errors" in output and output.endswith("exit code 1")


def test_the_push_answer_is_the_summary_with_a_details_file():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "UsrPkg"
        pkg.mkdir()
        (pkg / "descriptor.json").write_text('{"Descriptor": {"Name": "UsrPkg", "UId": "00000000-0000-0000-0000-000000000001"}}', encoding="utf-8")
        add_process(pkg)
        task = Path(tmp) / "UsrTask"
        with patch.object(push_module, "Clio", return_value=FakeClio()), patch.object(push_module, "_git", return_value=None):
            output = server.push_package(str(pkg), "dev", task=str(task), skip_drift=True, skip_sql_dates=True)
        lines = output.splitlines()
        assert lines[-1] == "exit code 0" and not any(line.startswith("  ") for line in lines), output
        assert "script compile: ok (0 compiled, 1 not checked)" in lines and "publish: ok" in lines
        details = Path(next(line for line in lines if line.startswith("details: "))[len("details: "):])
        assert details.parent == task and "  process UsrProcess: script compile not checked (no binaries)" in details.read_text(encoding="utf-8")


def test_raised_failure_keeps_prior_log_and_error():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp)
        (pkg / "descriptor.json").write_text("{}", encoding="utf-8")
        def fake_push(*args, log, **kwargs):
            log("step started")
            raise RuntimeError("specific failure")
        with patch.object(push_module, "Clio", return_value=FakeClio()), patch.object(push_module, "push", side_effect=fake_push):
            output = server.push_package(str(pkg), "dev")
        assert "step started" in output and "error: specific failure" in output
        assert output.endswith("exit code 2")


env_module = importlib.import_module("creatio_schemas.environment")


class FakeEnv:
    clio_name, url = "dev", "https://site.example/"

    def __init__(self):
        self.calls = []

    def sql(self, text, counts=None):
        self.calls.append(("sql", text))
        if "boom" in text:
            raise RuntimeError("sql: [ERR] relation does not exist")
        return [{"Name": "UsrOrder", "ModifiedOn": "2026-11-10"}, {"Name": "Ünïcode", "ModifiedOn": None}]

    def request(self, method, path, body=None, params=None):
        self.calls.append((method, path, body))
        return env_module.Response(200, '{"d": 1}') if path.startswith("rest/") else env_module.Response(500, "<html>fault</html>")

    def odata(self, entity, select=None, filter=None, top=None, orderby=None, skip=None, expand=None):
        self.calls.append((entity, select, filter, top))
        return [{"Id": "1", "Name": "A"}]


def test_env_tools_use_the_environment_layer():
    fake = FakeEnv()
    with patch.object(env_module.Environment, "from_clio", staticmethod(lambda name, **kw: fake)):
        assert server.env_sql("dev", 'select 1').splitlines() == ['{"Name": "UsrOrder", "ModifiedOn": "2026-11-10"}', '{"Name": "Ünïcode", "ModifiedOn": null}']
        assert server.env_sql("dev", "select boom").startswith("error: sql: [ERR]")
        assert "1 more" in server.env_sql("dev", "select 1", limit=1)
        assert server.env_call("dev", "post", "/rest/UsrSvc/Ping", '{"a": 1}') == 'status: 200\n{\n  "d": 1\n}'
        assert fake.calls[-1] == ("POST", "rest/UsrSvc/Ping", {"a": 1})
        assert server.env_call("dev", "GET", "ServiceModel/X.svc/Y").startswith("error: 500:")
        assert server.env_call("dev", "GET", "rest/x", "{not json").startswith("error:")
        assert server.env_odata("dev", "Contact", "Id, Name", "Name eq 'A'", 5) == '{"Id": "1", "Name": "A"}'
        assert fake.calls[-1] == ("Contact", ["Id", "Name"], "Name eq 'A'", 5)
    assert server.env_sql(" ", "select 1").startswith("error: env must be")


def test_schema_layers_reads_custom_layer_from_project():
    import json
    rows = [{"package": "Base", "extendParent": "false", "sl": "0", "pl": "0", "body": "", "size": 10, "md5": "a" * 32},
            {"package": "UsrCustom", "extendParent": "true", "sl": "1", "pl": "1", "body": "", "size": 5, "md5": "b" * 32}]
    fake = FakeEnv()
    fake.sql = lambda text, counts=None: rows
    with tempfile.TemporaryDirectory() as tmp, patch.object(env_module, "open_environment", lambda env, project, **kw: fake):
        project = Path(tmp) / "project.json"
        project.write_text(json.dumps({"environment": {"customLayer": "UsrCustom"}}), encoding="utf-8")
        text = server.schema_layers(str(project), "UsrOrderPage")
        assert text.startswith("UsrOrderPage on dev: 2 copies") and text.endswith("Custom layer present: UsrCustom - it cannot be deleted by the tools; the human removes it on the site"), text
        assert "Custom layer present" not in server.schema_layers("dev", "UsrOrderPage"), "the default customisation package is Custom"
    with patch.object(env_module, "open_environment", lambda env, project, **kw: (_ for _ in ()).throw(ValueError("no such environment"))):
        assert server.schema_layers("nope", "X") == "error: no such environment"


def test_schema_deps_answers_from_the_fixture_index():
    pages = TOOLS / "pages" / "tests" / "fixtures" / "UsrPkg"
    out = server.schema_deps(str(pages), "UsrOrder", "in", kind="page")
    assert out.splitlines()[:3] == ["UsrOrder  object in UsrPkg", "dependents:", "  page UsrOrder_FormPage  data-source: PDS  [name]"], out
    assert "  object UsrOrderStatus  lookup: UsrStatus" in server.schema_deps(str(pages), "UsrOrder", "out", via="lookup")
    assert server.schema_deps(str(pages), "Nope").startswith("no schema named Nope")


def test_schema_impact_ends_with_the_exit_code():
    pages = TOOLS / "pages" / "tests" / "fixtures" / "UsrPkg"
    out = server.schema_impact(str(pages), "UsrOrderStatus, UsrOrder", md=True)
    assert out.startswith("## Impact") and "affects: UsrOrder_FormPage, UsrTests_FormPage" in out and out.endswith("exit code 0"), out
    assert server.schema_impact(str(pages), " ") == "error: name at least one schema"


def test_merge_plan_prints_and_writes_nothing():
    import json
    import shutil
    import tempfile
    root = Path(tempfile.mkdtemp())
    try:
        for name, deps in (("UsrA", []), ("UsrB", ["UsrA"])):
            folder = root / "packages" / name / "Schemas" / "Contact"
            folder.mkdir(parents=True)
            (root / "packages" / name / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": f"pkg-{name}", "Name": name, "DependsOn": [{"Name": d} for d in deps]}}), encoding="utf-8")
            (folder / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": f"uid-{name}", "Name": "Contact", "ExtendParent": True,
                                                                                "ManagerName": "EntitySchemaManager"}}), encoding="utf-8")
            (folder / "metadata.json").write_text(f'= MetaData.Schema.UId "uid-{name}"\r\n', encoding="utf-8")
        before = sorted(p.relative_to(root) for p in root.rglob("*"))
        out = server.merge_plan(str(root))  # upward by default (S27-T09): into the top package
        assert out.splitlines()[0] == "Contact object: 2 layers, target UsrB" and out.endswith("1 schemas, 1 layers to remove, 0 conflicts\nexit code 0"), out
        assert "  depends: unchanged" in out
        assert server.merge_plan(str(root), direction="down").splitlines()[0] == "Contact object: 2 layers, target UsrA"
        assert sorted(p.relative_to(root) for p in root.rglob("*")) == before
        assert server.merge_plan(str(root / "nowhere")).startswith("error: ")
        out = server.merge_layers(str(root), "Contact")
        assert "delete packages/UsrA/Schemas/Contact" in out and out.endswith("(dry run; --apply writes)\nexit code 0"), out
        assert "delete packages/UsrB/Schemas/Contact" in server.merge_layers(str(root), "Contact", direction="down")
        assert sorted(p.relative_to(root) for p in root.rglob("*")) == before  # printed, never written

        # a page: merge_layers prints its merge, schema_snapshot folds it and reads a page file
        body = ('define("UsrP", /**SCHEMA_DEPS*/[]/**SCHEMA_DEPS*/, function/**SCHEMA_ARGS*/()/**SCHEMA_ARGS*/ {{ return {{ '
                'viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[{op}]/**SCHEMA_VIEW_CONFIG_DIFF*/, '
                'handlers: /**SCHEMA_HANDLERS*/[]/**SCHEMA_HANDLERS*/, converters: /**SCHEMA_CONVERTERS*/{{}}/**SCHEMA_CONVERTERS*/, '
                'validators: /**SCHEMA_VALIDATORS*/{{}}/**SCHEMA_VALIDATORS*/ }}; }});')
        for name, op in (("UsrA", '{"operation": "insert", "name": "UsrX", "values": {"type": "crt.Input"}}'), ("UsrB", '{"operation": "remove", "name": "Base1"}')):
            folder = root / "packages" / name / "Schemas" / "UsrP"
            folder.mkdir(parents=True)
            (folder / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": f"p-{name}", "Name": "UsrP", "ExtendParent": True,
                                                                                "ManagerName": "ClientUnitSchemaManager"}}), encoding="utf-8")
            (folder / "metadata.json").write_text(f'= MetaData.Schema.UId "p-{name}"\n', encoding="utf-8")
            (folder / "UsrP.js").write_text(body.format(op=op), encoding="utf-8")
        page_file = root / "UsrP.json"
        page_file.write_text(json.dumps({"elements": [{"code": "UsrX", "type": "Text", "label": "X"}]}), encoding="utf-8")
        before = sorted(p.relative_to(root) for p in root.rglob("*"))
        out = server.merge_layers(str(root), "UsrP")
        assert out.startswith("UsrP page: 2 layers, target UsrB") and "write packages/UsrB/Schemas/UsrP/UsrP.js" in out and out.endswith("exit code 0"), out
        assert sorted(p.relative_to(root) for p in root.rglob("*")) == before
        snap = server.schema_snapshot("UsrP", workspace=str(root), page_file=str(page_file))
        assert snap.splitlines() == ["layers: UsrA > UsrB", "element UsrX crt.Input", "removed Base1", "page UsrX Text X"], snap
        out = server.merge_package(str(root), "UsrB", "UsrA")
        assert out.startswith("layer   object  Contact") and "layer   page    UsrP" in out and out.endswith("(dry run; --apply writes)\nexit code 0"), out
        assert sorted(p.relative_to(root) for p in root.rglob("*")) == before
    finally:
        shutil.rmtree(root, ignore_errors=True)




def test_schema_diff_compares_a_folder_without_git():
    from creatio_schemas.entity import EntitySchema

    source = TOOLS / "objects" / "tests" / "fixtures" / "UsrPkg"
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "UsrPkg"
        shutil.copytree(source, pkg)
        entity = EntitySchema(pkg, "UsrOrder")
        entity.add_column("UsrWeight", "Float", "Weight")
        entity.save()
        text = server.schema_diff(str(pkg), "UsrOrder", str(source))
        assert text.splitlines()[0] == "UsrOrder  object" and "+ UsrWeight Float 'Weight'" in text
        assert server.schema_diff(str(pkg), "UsrNoSuch", str(source)).startswith("error: ")


class ScriptedEnv:
    """sql() answers with the rows of the first needle (longest first) the statement contains."""

    clio_name, url = "dev", "https://site.example/"

    def __init__(self, answers):
        self.answers = answers

    def sql(self, text, counts=None):
        for needle in sorted(self.answers, key=len, reverse=True):
            if needle in text:
                return self.answers[needle]
        raise RuntimeError("sql: 42P01: nothing scripted")


def test_forensics_tools_answer_from_the_database():
    uid = "11111111-1111-1111-1111-111111111111"
    person = "22222222-2222-2222-2222-222222222222"
    role = [{"Id": person, "Name": "UsrManagers", "SysAdminUnitTypeValue": 6}]
    user = [{"Id": uid, "login": "ivan", "contact": "Ivan P"}]
    fake = ScriptedEnv({
        "information_schema.columns": [{"schema": "public", "table": "UsrOrder"}], 'where "Id" =': [{"schema": "public", "table": "UsrOrder"}],
        'select * from "': [{"Id": uid, "Name": "Order 7", "CreatedOn": "2026-11-10T22:30:00Z", "CreatedById": person}],
        'from "Contact" where "Id" in': [{"Id": person, "Name": "Ivan"}], "kcu.table_name": [], "ccu.table_name": [],
        "where \"Name\" = 'UsrManagers'": role, 'm."Name" as "member"': [{"id": uid, "member": "ivan", "contact": "Ivan P", "kind": 4}],
        'u."SysAdminUnitTypeValue" = 4': user, 'r."Name" as "role"': [{"id": person, "role": "UsrManagers", "kind": 6}],
        '"ParentRoleId", "SysAdminUnitTypeValue" from "SysAdminUnit"': [{"Id": person, "Name": "UsrManagers", "ParentRoleId": None, "SysAdminUnitTypeValue": 6}],
        'from "SysFuncRoleInOrgRole"': [], 'from "SysUserInRole" where': [{"SysUserId": uid, "SysRoleId": person}],
        'select "SysAdminUnitId" as "id"': [], 'from "SysSettings" where "Code"': [{"Id": uid, "Name": "Max", "ValueTypeName": "Integer", "ReferenceSchemaUId": None}],
        'from "SysSettingsValue" where': [{"IntegerValue": 5, "SysAdminUnitId": None}]})
    with patch.object(env_module.Environment, "from_clio", staticmethod(lambda name, **kw: fake)):
        found = server.find_record("dev", uid, "UsrOrder", time_zone="+03:00")
        assert found.startswith("UsrOrder  Name = Order 7\n  created  2026-11-10 22:30:00 UTC (01:30 +03:00) 11.11 by Ivan"), found
        assert server.record_context("dev", "UsrOrder", uid, depth=1).startswith(f"UsrOrder {uid}\n  Id = {uid}\n  Name = Order 7")
        assert server.role_members("dev", "UsrManagers") == "Ivan P  [user]  direct  login ivan"
        assert server.user_roles("dev", "ivan") == "UsrManagers  [functional role]  direct"
        assert server.role_diff("dev", "UsrManagers", "ivan") == "in UsrManagers: -\nnot in UsrManagers: ivan\nexit code 1"
        setting = server.sys_setting("UsrMax", "dev")
        assert "dev: Max [Integer]" in setting and "for all: '5'" in setting
        assert server.find_record("dev", "nope").startswith("error: ")
    fake.answers["where \"Name\" = 'UsrManagers'"] = []
    with patch.object(env_module.Environment, "from_clio", staticmethod(lambda name, **kw: fake)):
        assert server.role_members("dev", "UsrManagers") == "error: no role named 'UsrManagers' (SysAdminUnit.Name)"


def test_snapshot_tools_write_and_compare_evidence(tmp_path=None):
    import tempfile
    cols = [{"column": "Id", "type": "uuid", "length": None, "nullable": "NO"}, {"column": "UsrNote", "type": "text", "length": None, "nullable": "YES"}]
    layer = [{"package": "UsrLayer", "extendParent": "true", "sl": "1", "pl": "1"}]

    def fake(note):
        return ScriptedEnv({"information_schema.columns": cols, "count(*)": [{"n": 3}], "md5(string_agg": [{"c0": note}], 'from "SysSchema" s': layer})
    folder = Path(tempfile.mkdtemp())
    before, after = str(folder / "before.txt"), str(folder / "after.txt")
    for out, note in ((before, "aaa"), (after, "bbb")):
        with patch.object(env_module.Environment, "from_clio", staticmethod(lambda name, **kw: fake(note))):
            assert "rows 3" in server.schema_snapshot("UsrObj", "dev", out=out)
    assert server.snapshot_compare(before, before) == "same"
    assert server.snapshot_compare(before, after) == "~ checksum  UsrNote aaa -> UsrNote bbb\nexit code 1"
    assert server.snapshot_compare(before, str(folder / "none.txt")).startswith("error: ")


def test_cases_from_package_writes_cases_and_reports_stops():
    pages = TOOLS / "pages" / "tests" / "fixtures" / "UsrPkg"
    tmp = Path(tempfile.mkdtemp())
    try:
        text = server.cases_from_package(str(pages), str(tmp / "out"))
        assert "wrote Cases/UsrPkg/UsrOrder.act" in text and "stop UsrOrder_FormPage:" in text and text.endswith("exit code 1")
        assert (tmp / "out" / "Cases" / "UsrPkg" / "UsrOrder.act").is_file()
        assert server.cases_from_package(str(tmp / "missing"), str(tmp / "out2")) == "(no schema to write cases for)"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_tool_call_logs_names_and_sizes_and_the_summary_reads_the_log():
    import json
    import tool_stats
    folder = Path(tempfile.mkdtemp())
    try:
        with patch.dict(os.environ, {"CREATIO_KB_STATS_DIR": str(folder), "CREATIO_KB_STATS": "1"}):
            secret = "C:/secret/UsrPassword-value.txt"
            answer = server.snapshot_compare(secret, "other.txt")  # a cheap tool: an error text, no environment
            lines = [json.loads(l) for f in folder.glob("*.jsonl") for l in f.read_text(encoding="utf-8").splitlines()]
            assert len(lines) == 1 and lines[0]["tool"] == "snapshot_compare", lines
            assert lines[0]["args"] == {"before": len(secret), "after": len("other.txt")} and lines[0]["chars"] == len(answer) and lines[0]["truncated"] is False
            assert set(lines[0]) == {"ts", "tool", "args", "chars", "ms", "truncated"} and isinstance(lines[0]["ms"], int)
            assert "secret" not in "".join(f.read_text(encoding="utf-8") for f in folder.glob("*.jsonl")), "no argument value in the log"
            # a `... N more` tail marks the call as truncated
            tool_stats.instrument(lambda q: "a\nb\n... 7 more; offset=2", folder)("x")
            assert json.loads(next(folder.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()[-1])["truncated"] is True
        with patch.dict(os.environ, {"CREATIO_KB_STATS_DIR": str(folder), "CREATIO_KB_STATS": "0"}):
            before = next(folder.glob("*.jsonl")).read_text(encoding="utf-8")
            server.snapshot_compare("a", "b")
            assert next(folder.glob("*.jsonl")).read_text(encoding="utf-8") == before, "off with CREATIO_KB_STATS=0"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_the_summary_over_a_fixture_log():
    import json
    import tool_stats
    folder = Path(tempfile.mkdtemp())
    try:
        today = tool_stats.date.today().isoformat()
        rows = [{"ts": f"{today}T10:00:0{i}", "tool": tool, "args": {"path": 5}, "chars": chars, "ms": 3, "truncated": cut}
                for i, (tool, chars, cut) in enumerate([("describe_schema", 4000, True), ("describe_schema", 2000, False), ("get_recipe", 9000, False), ("env_sql", 100, False)])]
        (folder / f"{today}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
        text = tool_stats.summarise(tool_stats.read(1, folder))
        lines = text.splitlines()
        assert lines[0].split() == ["tool", "calls", "chars", "avg", "max"]
        assert lines[1].split() == ["get_recipe", "1", "9000", "9000", "9000"] and lines[2].split() == ["describe_schema", "2", "6000", "3000", "4000"]
        assert "largest answers:" in lines and lines[lines.index("largest answers:") + 1].split()[:2] == ["9000", "get_recipe(path)"]
        assert lines[-1] == "4 calls, 15100 chars, 1 truncated (25%)", lines[-1]
        assert tool_stats.summarise([]) == "(no tool calls logged)"
        with patch.dict(os.environ, {"CREATIO_KB_STATS_DIR": str(folder), "CREATIO_KB_GAPS_DIR": str(folder / "gaps")}):
            lines = server.tool_stats(1).splitlines()  # the tool reads the log, then logs itself
            assert lines[-2] == "4 calls, 15100 chars, 1 truncated (25%)" and lines[-1] == "gaps: 0", lines[-2:]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_report_gap_records_the_line_and_keeps_the_script():
    import json
    import tool_stats
    folder = Path(tempfile.mkdtemp())
    try:
        with patch.dict(os.environ, {"CREATIO_KB_STATS_DIR": str(folder / "stats"), "CREATIO_KB_GAPS_DIR": str(folder / "gaps")}):
            script = folder / "probe.sql"
            script.write_text("select 1", encoding="utf-8")
            first = server.report_gap("missing", "which lookup rows exist on the site", "env_sql over the lookup table", str(script), "012-labels")
            assert first.startswith(f"recorded: {folder / 'gaps' / 'gaps.jsonl'} line 1; script kept as "), first
            today = tool_stats.date.today().isoformat()
            kept = folder / "gaps" / "scripts" / f"{today}-probe.sql"
            assert kept.read_text(encoding="utf-8") == "select 1" and script.is_file(), "a copy, the original stays"
            line = json.loads((folder / "gaps" / "gaps.jsonl").read_text(encoding="utf-8").splitlines()[0])
            assert line["kind"] == "missing" and line["script"] == str(kept) and line["task"] == "012-labels" and set(line) == {"ts", "kind", "need", "instead", "script", "task"}
            # the same name again the same day gets a suffix; a file already under scripts/ is not copied twice
            script.write_text("select 2", encoding="utf-8")
            second = server.report_gap("misbehaved", "the rows with captions", "describe_table, then SQL", str(script))
            assert second.endswith(f"line 2; script kept as {folder / 'gaps' / 'scripts' / (today + '-2-probe.sql')}"), second
            third = server.report_gap("by-hand", "the caption of a status", "read it in the designer", str(kept))
            assert third.endswith(f"line 3; script kept as {kept}") and len(list((folder / "gaps" / "scripts").iterdir())) == 2, third
            assert server.report_gap("missing", "a value", "typed it").endswith("line 4"), "no script is fine"
            # refusals write nothing
            before = (folder / "gaps" / "gaps.jsonl").read_text(encoding="utf-8")
            assert server.report_gap("other", "x", "y") == "refused: kind must be one of missing, misbehaved, by-hand"
            assert server.report_gap("missing", " ", "y") == "refused: need and instead must both say something"
            assert server.report_gap("missing", "x", "y", str(folder / "none.py")).startswith("refused: script is not a file")
            assert server.report_gap("missing", "x", "y", str(folder)).startswith("refused: script is not a file"), "a directory"
            for secret in ("login with password=abc", "Authorization: Bearer abc", "token=zz", "api_key: k", "client_secret=1", "passwd 1"):
                assert server.report_gap("missing", secret, "y").startswith("refused: the log is read by other agents"), secret
            assert server.report_gap("missing", "x", "y", task="pwd=1").startswith("refused:"), "task is checked too"
            assert server.report_gap("missing", "the token column of UsrOrder", "y").startswith("refused:"), "a word alone is enough: better refused than leaked"
            assert (folder / "gaps" / "gaps.jsonl").read_text(encoding="utf-8") == before
            # a non-object JSON line in the file is skipped, not fatal
            with open(folder / "gaps" / "gaps.jsonl", "a", encoding="utf-8") as fh:
                fh.write("[1, 2]\n")
            # the summary ends with the count by kind and the last gap
            last = server.tool_stats(1).splitlines()[-1]
            assert last.startswith("gaps: 4 (missing 2, misbehaved 1, by-hand 1); last: ") and last.endswith(" missing a value"), last
            assert tool_stats.summarise([], []) == "(no tool calls logged)\ngaps: 0"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_offset_reaches_the_describe_tools():
    pages = str(TOOLS / "pages" / "tests" / "fixtures" / "UsrPkg")
    first = server.describe_item(pages, "UsrOrder", "columns", 5).splitlines()
    second = server.describe_item(pages, "UsrOrder", "columns", 5, 5).splitlines()
    assert second[0] != first[0] and second[-1].startswith("  ... ") and "next: offset=10" in second[-1], second[-1]
    assert "next: offset=" not in first[-1] and server.describe_item(pages, "UsrOrder", "columns offset=5", 5).splitlines() == second
    assert server.describe_package(pages, "", 2, 1).splitlines()[-1].startswith("  ... 2 more; next: offset=3")
    assert server.describe_schema(pages, "UsrOrder", 3, 2).splitlines()[-1].startswith("  ... ") and "next: offset=5" in server.describe_schema(pages, "UsrOrder", 3, 2)
    # the workspace lists: find_schema, list_lookups, merge_plan pass offset to their cut (S30-T03 leftovers)
    with patch("creatio_schemas.describe.find_schema", return_value="fs") as fs, \
            patch("creatio_schemas.describe.lookups", return_value="lk") as lk, \
            patch("creatio_schemas.describe.merge.merge_plan", return_value=("mp", 0)) as mp:
        assert server.find_schema(pages, "UsrOrder", 2, 4) == "fs" and fs.call_args.args == (pages, "UsrOrder", 2, 4)
        assert server.list_lookups(pages, 2, 4) == "lk" and lk.call_args.args == (pages, 2, 4)
        assert server.merge_plan(pages, "", "", 2, 4) == "mp\nexit code 0" and mp.call_args.args[-3:] == (2, 4, "up")


def test_get_recipe_takes_a_part():
    rid = "Frontend/FreedomUI/Data/HowToLoadDataWithSdkModel"
    traps, whole = server.get_recipe(rid, "traps"), server.get_recipe(rid)
    assert traps.startswith("# How to load records from an entity using sdk.Model") and "primaryColumnValue" in traps and len(traps) < len(whole) / 2
    assert server.get_recipe(rid, "all") == whole and "viewConfigDiff" in server.get_recipe(rid, "code")
    assert server.get_recipe(rid, "nope") == "error: part must be one of summary, code, traps, all"


class ProcessEnv(ScriptedEnv):
    """ScriptedEnv that also starts processes: `success` and `processId` as the engine would answer."""

    def __init__(self, answers, success=True, process_id="44444444-4444-4444-4444-444444444444"):
        super().__init__(answers)
        self.success, self.process_id, self.started = success, process_id, []

    def run_process(self, name, params=None, results=None):
        self.started.append((name, params, results))
        return {"process": name, "processId": self.process_id if self.success else "", "success": self.success,
                "error": None if self.success else "Schema not found", "results": {"Total": 42}}

    def process_log(self, process_id, zone=None):
        from creatio_schemas.runs import process_log
        return process_log(self, process_id, zone)


def test_process_tools_run_and_read_the_log():
    run = "44444444-4444-4444-4444-444444444444"
    row = {"Id": run, "Name": "Order", "Status": "Error", "ErrorDescription": "Expression expected\n   at Terrasoft.X()",
           "StartDate": "2026-11-11T08:00:05", "CompleteDate": None, "OwnerId": None, "Process": "UsrOrder_Process"}
    element = {"Caption": "Read order", "Status": "Error", "ErrorDescription": None, "StartDate": "2026-11-11T08:00:06", "CompleteDate": None}
    copy = {"id": "c1000000-0000-4000-8000-000000000001", "uid": "a1000000-0000-4000-8000-000000000001", "name": "UsrOrder_Process", "package": "UsrBase"}
    fake = ProcessEnv({'from "SysSchema" s left join "SysPackage" p': [copy], 'from "SysProcessLog" l': [row], 'from "SysProcessElementLog" e': [element], 'from "Contact" where "Id" in': []})
    with patch.object(env_module.Environment, "from_clio", staticmethod(lambda name, **kw: fake)):
        answer = server.run_process("dev", "UsrOrder_Process", '{"OrderId": "o-1", "Qty": 3}', "Total")
        assert fake.started[-1] == ("UsrOrder_Process", {"OrderId": "o-1", "Qty": 3}, ["Total"])
        assert answer.splitlines()[0] == f"UsrOrder_Process: ok  processId {run}" and "  Total = 42" in answer, answer
        assert "log: Error (failed)" in answer and "error: Expression expected" in answer and answer.endswith("exit code 1"), answer
        fake.answers['from "SysProcessLog" l'] = [dict(row, Status="Completed", ErrorDescription=None, CompleteDate="2026-11-11T08:00:09")]
        assert server.run_process("dev", "UsrOrder_Process").endswith("exit code 0")
        assert server.run_process("dev", "UsrOrder_Process", "[1]").startswith("error: params: params must be a JSON object")
        assert server.run_process("dev", "UsrOrder_Process", "{bad").startswith("error: params:")
        fake.answers['from "SysProcessLog" l'] = [row]
        listed = server.process_runs("dev", process="UsrOrder_Process", time_zone="+03:00")
        assert listed.splitlines()[0] == "1 copy: UsrBase" and "2026-11-11 08:00:05 UTC (11:00 +03:00)  UsrOrder_Process  Error (failed)  " + run in listed, listed
        assert server.process_runs("dev", record="UsrOrder:x").startswith("error: 'x' is not an Id")
        error = server.process_error("dev", run)
        assert "stopped on: Read order (Error" in error and error.splitlines()[-1] == "Expression expected", error
    tests = ProcessEnv({'from "SysPackage" p': [{"changed": "2026-11-11T09:00:00", "compiled": "2026-11-11T08:00:00"}]})
    tests.call_service = lambda path, body=None, method="POST": env_module.Response(200, '[{"Name": "T1", "Success": true}, {"Name": "T2", "Success": false, "Message": "expected 3"}]')
    with patch.object(env_module.Environment, "from_clio", staticmethod(lambda name, **kw: tests)):
        assert server.run_tests("dev", category="UsrOrders") == "error: no in-Creatio test runner configured: set project.json tests.runner or pass --runner\nexit code 2"
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project.json"
        project.write_text('{"environment": {"clioName": "dev", "url": "https://p.example"}, "tests": {"runner": "rest/UsrTests/Run", "package": "UsrTests"}}', encoding="utf-8")
        with patch.object(env_module.Environment, "from_project", classmethod(lambda cls, path, **kw: tests)):
            answer = server.run_tests(project=str(project), test="UsrOrderTest")
        assert answer.splitlines() == ["FAIL  T2  - expected 3", "ok    T1", "1 passed, 1 failed",
                                       "warning: the test package's dll is older than its last push (UsrTests changed 2026-11-11T09:00:00, compiled 2026-11-11T08:00:00)",
                                       "exit code 1"], answer
    assert server.run_tests("dev").startswith("error: give category or test")
    with tempfile.TemporaryDirectory() as tmp:  # the git tools answer an error line, never a traceback
        assert server.review_download(tmp).startswith("error: ") and "no descriptor.json" in server.review_download(tmp)
        assert server.precommit_check(str(Path(tmp) / "none")).startswith("error: ")
    refused = ProcessEnv({}, success=False)
    with patch.object(env_module.Environment, "from_clio", staticmethod(lambda name, **kw: refused)):
        assert server.run_process("dev", "UsrMissing") == "UsrMissing: FAILED Schema not found  processId -\nexit code 1"


def test_merge_run_is_a_registered_rehearsal_that_names_an_unknown_environment():
    import server

    assert "merge_run" in {t.name for t in server.mcp._tool_manager.list_tools()}
    out = server.merge_run(".", "UsrChild", "UsrBase", "nosuchenv", "evidence")
    assert out.startswith("error:") and "nosuchenv" in out, out


def test_resolve_caption_answers_from_a_package_and_names_a_bad_kind():
    import server

    pkg = str(TOOLS / "objects" / "tests" / "fixtures" / "UsrPkg")
    out = server.resolve_caption(pkg, "Status", limit=0)
    assert out.splitlines()[0].startswith("column    UsrOrder.UsrStatus 'Status'"), out
    assert server.resolve_caption(pkg, "x", kind="nonsense").startswith("error: unknown kind nonsense")


def test_page_audit_answers_with_the_last_line():
    import server

    pkg = str(TOOLS / "pages" / "tests" / "fixtures" / "UsrPkg")
    assert server.page_audit(pkg, "UsrOrder_FormPage") == "UsrOrder_FormPage: 0 finding(s)"
    assert server.page_audit(pkg, "UsrTests_FormPage").splitlines()[0].startswith("grid ")
    assert server.page_audit(pkg, "NoSuchPage").startswith("error:")


def test_process_text_tools_answer_and_refuse_a_bad_target():
    import server

    pkg = str(TOOLS / "process" / "tests" / "fixtures" / "UsrPkg")
    assert "DeleteDataUserTask1" in server.find_text(pkg, "macro", kind="process")
    assert server.find_text(pkg, "no such text", kind="process").startswith("no process text matches")
    assert not hasattr(server, "find_in_processes")  # folded into find_text(kind="process"), S41-T03
    help_text = server.describe_item(pkg, "UsrOrder", "help")
    assert help_text.startswith("One part of a schema") and 'classic: (a 7.x client schema)' in help_text and "callers onSaveClick" in help_text
    assert server.who_sets(pkg, "UsrOrder").startswith("error: give")
    assert server.who_reads_message(pkg, "Nobody").startswith("no publisher")


class _SqlEnv:
    """A scripted site: a select answers rows, an update answers an affected count."""

    clio_name, url = "dev", "https://site.example/"

    def __init__(self, rows):
        self.rows = rows
        self.ran = []

    def sql(self, text, counts=None):
        self.ran.append(text)
        if text.lower().startswith("update"):
            if counts is not None:
                counts.append(3)
            return []
        if counts is not None:
            counts.append(None)
        return self.rows


def test_env_sql_writes_a_whole_csv_answers_each_statement_and_guards_writes():
    import csv
    import tempfile

    rows = [{"Id": i, "Name": f"n{i};x" if i == 2 else f"n{i}", "Empty": None} for i in range(1, 9)]
    fake = _SqlEnv(rows)
    with tempfile.TemporaryDirectory() as tmp, patch.object(env_module.Environment, "from_clio", staticmethod(lambda name, **kw: fake)):
        target = Path(tmp) / "sub" / "rows.csv"
        answer = server.env_sql("dev", "select * from \"UsrOrder\"", limit=2, out=str(target))
        assert answer.splitlines()[0] == f"8 rows -> {target}" and len(answer.splitlines()) == 6 and "more" not in answer, answer
        raw = target.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 with BOM, as Excel wants it
        parsed = list(csv.reader(raw.decode("utf-8-sig").splitlines(), delimiter=";"))
        assert parsed[0] == ["Id", "Name", "Empty"] and len(parsed) == 9 and parsed[2] == ["2", "n2;x", ""]
        # a writing statement is refused, then runs with write=true and reports the count; each statement has its own answer
        before = len(fake.ran)
        assert server.env_sql("dev", 'update "UsrOrder" set "Name" = null') == "error: a writing statement needs write=true"
        assert server.env_sql("dev", "-- a comment\nselect 1;\nupdate x set y = 1") == "error: a writing statement needs write=true"
        assert len(fake.ran) == before, "a refused statement must not reach the site"
        two = server.env_sql("dev", 'update "UsrOrder" set "Name" = null;\nselect 1', write=True).splitlines()
        assert two[0] == "-- statement 1" and two[1] == "affected: 3" and two[2] == "-- statement 2" and two[-1] == "affected: 3", two
        assert server.env_sql("dev", "with a as (select 1) select * from a", limit=1).count("\n") == 1  # a with-select needs no flag


def test_describe_table_lists_columns_and_keys_and_refuses_a_bad_name():
    env = ScriptedEnv({
        "information_schema.columns": [{"column": "Id", "type": "uuid", "length": None, "nullable": "NO"},
                                       {"column": "Name", "type": "character varying", "length": "250", "nullable": "YES"}],
        "information_schema.table_constraints": [{"column": "Id", "kind": "PRIMARY KEY", "target": "UsrOrder", "target_column": "Id"},
                                                 {"column": "OwnerId", "kind": "FOREIGN KEY", "target": "Contact", "target_column": "Id"}]})
    with patch.object(env_module.Environment, "from_clio", staticmethod(lambda name, **kw: env)):
        assert server.describe_table("dev", "UsrOrder").splitlines() == [
            "Id uuid", "Name character varying(250) null", "primary key: Id", "foreign key: OwnerId -> Contact.Id"]
        assert server.describe_table("dev", "x; drop table y").startswith("error: give a table name")
    with patch.object(env_module.Environment, "from_clio", staticmethod(lambda name, **kw: ScriptedEnv({"information_schema.columns": []}))):
        assert server.describe_table("dev", "UsrNope").startswith("no table UsrNope")


def test_history_and_timer_tools_answer_refuse_and_write_only_on_a_dev_project():
    import tempfile

    rec, boss = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    ins, upd = "a852c33f-0bdd-e011-92c3-00155d04c01d", "a952c33f-0bdd-e011-92c3-00155d04c01d"
    snap = lambda at, kind, status: {"Id": "x", "ChangeTrackedOn": at, "ChangeTrackedById": boss, "ChangeTypeId": kind, "ChangeTrackedId": rec, "UsrStatus": status}  # noqa: E731
    run = "44444444-4444-4444-4444-444444444444"
    element = "99999999-9999-4999-8999-999999999999"
    timer = {"trigger": "t-1", "state": "WAITING", "next": 639308422800000000, "element_id": element, "caption": "1 d.", "element_start": "2026-11-20T07:18:00",
             "run_id": run, "run_start": "2026-11-20T07:18:00", "process": "UsrOrder_Process"}
    copy = {"id": "c1000000-0000-4000-8000-000000000001", "uid": "a1000000-0000-4000-8000-000000000001", "name": "UsrOrder_Process", "package": "UsrBase"}

    class Recording(ScriptedEnv):
        def __init__(self, answers):
            super().__init__(answers)
            self.statements = []

        def sql(self, text, counts=None):
            self.statements.append(text)
            if counts is not None:
                counts.append(1 if text.startswith("update") else None)
            return super().sql(text, counts)

    fake = Recording({"information_schema.tables where table_name = 'SysUsrOrderLog'": [{"table_name": "SysUsrOrderLog"}],
                      "information_schema.columns where table_name = 'SysUsrOrderLog'": [{"column_name": "UsrStatus"}],
                      'from "SysUsrOrderLog" where "ChangeTrackedId"': [snap("2026-11-11T08:00:00", ins, "Draft"), snap("2026-11-11T08:00:05", upd, "Closed")],
                      'from "SysUsrOrderLog" order by "ChangeTrackedId"': [{"ChangeTrackedId": rec, "ChangeTrackedOn": "2026-11-11T08:00:00", "ChangeTrackedById": boss,
                                                                           "ChangeTypeId": ins, "value": "Draft"},
                                                                          {"ChangeTrackedId": rec, "ChangeTrackedOn": "2026-11-11T08:00:05", "ChangeTrackedById": boss,
                                                                           "ChangeTypeId": upd, "value": "Closed"}],
                      'from "SysEntityChangeType"': [{"Id": ins, "Name": "Inserted"}, {"Id": upd, "Name": "Updated"}],
                      'from "Contact" where "Id" in': [{"Id": boss, "Name": "Ivan"}],
                      'from "SysSchema" s left join "SysPackage" p': [copy], "from qrtz_triggers t": [timer], "update qrtz_triggers": [],
                      'from "SysProcessLog" l': [], 'from "SysProcessLog" offset': []})
    with tempfile.TemporaryDirectory() as tmp, patch.object(env_module.Environment, "from_clio", staticmethod(lambda name, **kw: fake)):
        history = server.record_history("dev", f"UsrOrder:{rec}", time_zone="+02:00")
        assert history.splitlines()[0] == f"UsrOrder {rec}: 2 logged change(s)" and "    UsrStatus: Draft -> Closed" in history and "Updated by Ivan" in history, history
        assert "UsrStatus: -> Draft" not in server.record_history("dev", f"UsrOrder:{rec}", column="Nope"), "a column filter keeps only that column"
        assert server.record_history("dev", "UsrOrder:x").startswith("error: 'x' is not an Id")
        target = Path(tmp) / "t.csv"
        transitions = server.column_transitions("dev", "UsrOrder.UsrStatus", to="Closed", out=str(target))
        assert transitions.splitlines()[0] == "UsrOrder.UsrStatus: 1 transition(s)" and f"1 rows -> {target}" in transitions and target.is_file(), transitions
        assert server.column_transitions("dev", "UsrOrder").startswith("error: ")
        assert "no pending timers" not in server.process_timers("dev", "UsrOrder_Process", time_zone="+02:00") and "1 d." in server.process_timers("dev", "UsrOrder_Process")
        assert server.process_runs("dev", process="UsrOrder_Process").endswith("process logging is off (SysProcessLog empty); enable it in the process settings")
        # fire_timer: refused without a dev project, and a refusal touches nothing
        assert server.fire_timer("dev", "UsrOrder_Process", f"UsrOrder:{rec}", "") == "refused: dev is not a dev environment (project.json environment.kind must be \"dev\" for it)"
        project = Path(tmp) / "project.json"
        project.write_text('{"environment": {"clioName": "dev", "url": "https://p.example", "kind": "test"}}', encoding="utf-8")
        assert server.fire_timer("dev", "UsrOrder_Process", f"UsrOrder:{rec}", str(project)).startswith("refused: dev is not a dev environment")
        assert not any(s.startswith("update") for s in fake.statements)
        project.write_text('{"environment": {"clioName": "dev", "url": "https://p.example", "kind": "dev"}}', encoding="utf-8")
        fake.answers['select "ModifiedOn" from "UsrOrder" where'] = [{"ModifiedOn": "2026-11-20T07:18:00"}]
        fake.answers["ccu.table_name = 'UsrOrder'"] = []
        fired = server.fire_timer("dev", "UsrOrder_Process", f"UsrOrder:{rec}", str(project), delay=5, time_zone="+02:00")
        assert "was due 2026-11-21 07:18:00" in fired and "now due" in fired and "(in 5 s)" in fired, fired
        assert sum(s.startswith("update qrtz_triggers set next_fire_time = ") for s in fake.statements) == 1
    names = {t.name for t in server.mcp._tool_manager.list_tools()} if hasattr(server.mcp, "_tool_manager") else None
    assert names is None or {"record_history", "column_transitions", "process_timers", "fire_timer"} <= names


def test_ci_tools_run_the_pipeline_in_process_and_capture_its_output():
    import json
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "packages"
        for name, deps in (("UsrBase", []), ("UsrApp", ["UsrBase"])):
            schema = root / name / "Schemas" / f"{name}Page"
            schema.mkdir(parents=True)
            (root / name / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": name, "UId": f"uid-{name}",
                                                                                      "DependsOn": [{"Name": d} for d in deps]}}), encoding="utf-8")
            (schema / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": "same-uid"}}), encoding="utf-8")
            (schema / f"{name}Page.js").write_text("debugger;\n", encoding="utf-8")
        out = server.ci_check(str(root))
        assert "UsrApp" in out and "debugger" in out and "duplicate schema UId" in out and "metadata.json not found" in out, out
        assert out.endswith("exit code 1"), out
        assert server.ci_check(str(root), package="UsrNone").endswith("exit code 1")  # sys.exit("not under ...") captured
        out = server.ci_hierarchy(str(root))
        assert "--- level 1 (1) ---" in out and "UsrApp" in out and out.endswith("exit code 0"), out
        out = server.ci_lint(str(root))
        assert "missing localization" in out and "Read Data" in out and out.count("exit code") == 2, out
        with patch.object(server, "_ci", side_effect=lambda script, argv: " ".join(argv)):
            assert server.ci_deploy(str(root), "dev", package="UsrApp", restart=False) == f"deploy {root} -e dev --package UsrApp --no-restart"
            assert server.ci_build(str(root), "Build") == f"build {root} --out Build"
            assert server.ci_deploy(str(root), "dev", artifact="Build/Pkg.zip", redis=False) == "deploy --artifact Build/Pkg.zip -e dev --no-redis"
            assert server.ci_backup(str(root), "dev") == f"backup {root} -e dev --out Backup"
            assert server.ci_verify(str(root), "dev", package="UsrApp") == f"verify {root} -e dev --package UsrApp"
            assert server.ci_push_all(str(root), "dev", retry=True) == f"push-all -p {root} -e dev --list {root.parent / 'error-pkg.txt'}"


def test_test_data_tools_answer_from_the_database():
    status = "5d2a1c3e-0000-4000-8000-000000000001"
    order = "5d2a1c3e-0000-4000-8000-000000000002"
    cols = lambda *names: [{"column": n, "type": "character varying", "length": "250", "nullable": "YES", "default": "''"} for n in names]
    fake = ScriptedEnv({
        "table_name = 'UsrOrderStatus' order by ordinal_position": cols("Id", "Name"), "count(*)": [{"n": 1}],
        'from "UsrOrderStatus" order by "Name", "Id" offset': [{"Id": status, "Name": "Draft"}],
        "table_name = 'UsrOrder' order by ordinal_position": cols("Id", "UsrNumber") + [{"column": "UsrStatusId", "type": "uuid", "length": None, "nullable": "NO", "default": None}],
        "kcu.table_name = 'UsrOrder'": [{"table": "UsrOrder", "column": "UsrStatusId", "ref_table": "UsrOrderStatus"}],
        'select * from "UsrOrder"': [{"Id": order, "UsrNumber": "N-1", "UsrStatusId": status}],
        "column_name = 'Name' and table_name in": [{"table": "UsrOrderStatus"}], 'as "table", "Id", "Name" from': [{"table": "UsrOrderStatus", "Id": status, "Name": "Draft"}],
        "with recursive up": [{"table": "UsrOrderStatus"}], 'from "UsrOrderStatus" order by "Name", "Id" limit 1': [{"Id": status, "Name": "Draft"}],
        "information_schema.columns": []})
    with patch.object(env_module.Environment, "from_clio", staticmethod(lambda name, **kw: fake)):
        assert server.lookup_values("dev", "UsrOrderStatus") == f"UsrOrderStatus: 1 rows\n{status}  Draft"
        sample = server.sample_records("dev", "UsrOrder", n=1)
        assert f"  UsrStatusId (lookup UsrOrderStatus) = Draft ({status})" in sample and sample.endswith("columns: 2, lookups resolved: 1"), sample
        assert server.sample_records("dev", "UsrOrder", filter="1=1; drop table x") == "error: filter must be one where fragment: no ';'"
        fixture = server.make_fixture("dev", "UsrOrder")
        assert fixture == ("# UsrStatus = Draft (the first UsrOrderStatus by Name)\n"
                           f"insert UsrOrder as A set UsrStatus={status}\n# the end of the case: delete what the block inserted, newest first\ndelete UsrOrder $A\ncolumns: 1 required, 1 lookups resolved, 0 references inserted"), fixture
        assert server.lookup_values("dev", "OrderStatus").startswith('error: no table "OrderStatus" on the site; UsrOrderStatus exists')


def test_env_diff_and_set_feature_wrap_clio():
    calls = []

    def clio(args):
        calls.append(args)
        if args[0] == "save-state":
            Path(args[1]).write_text("features:\n- code: UsrFeatureA\n  users_values:\n    All employees: true\npackages:\n- name: UsrPkg\n  hash: 0A\n", encoding="utf-8")
        return 0, "[INF] - Loading packages\n[INF] - No differences found.\n"

    import json
    from creatio_schemas import environment as env_module_lib
    with tempfile.TemporaryDirectory() as tmp, patch.object(env_module_lib, "_run_clio", clio):
        before, after = Path(tmp) / "before.yaml", Path(tmp) / "after.yaml"
        assert server.env_diff("dev", save=str(before)) == f"saved {before.resolve()}: features 1, packages 1"
        after.write_text(before.read_text(encoding="utf-8").replace("hash: 0A", "hash: 0B"), encoding="utf-8")
        assert server.env_diff(before=str(before), after=str(after)) == "packages: 1 change(s)\n  ~ UsrPkg hash: 0A -> 0B"
        assert server.env_diff(before=str(before), after=str(before)) == "no differences"
        assert server.env_diff("dev", other="test") == "[INF] - No differences found."
        assert server.env_diff(save=str(before)) == "error: save needs env" and server.env_diff("dev").startswith("error: give env and save")
        project = Path(tmp) / "project.json"
        project.write_text(json.dumps({"environment": {"clioName": "dev", "kind": "dev"}}), encoding="utf-8")
        assert server.set_feature("dev", "UsrFeatureA", "on", str(project)) == "feature UsrFeatureA on for all users on dev"
        project.write_text(json.dumps({"environment": {"clioName": "dev", "kind": "client"}}), encoding="utf-8")
        assert server.set_feature("dev", "UsrFeatureA", "on", str(project)).startswith("refused: dev is not a dev environment")
        assert server.set_feature("dev", "UsrFeatureA", "soon", str(project)).startswith("error: state must be on or off")
    assert [c[0] for c in calls] == ["save-state", "show-diff", "set-feature"]  # the refused ones never reached clio


def _profile_run(role):
    """The server imported fresh under CREATIO_KB_ROLE=<role>: (registered tool names, the stderr, the tool_stats first line)."""
    import json
    import subprocess
    code = ("import asyncio, json, server; names = sorted(t.name for t in asyncio.run(server.mcp.list_tools())); "
            "print(json.dumps([names, server.tool_stats(1).splitlines()[0]]))")
    env = dict(os.environ, CREATIO_KB_STATS="0")
    env.pop("CREATIO_KB_ROLE", None)
    if role is not None:
        env["CREATIO_KB_ROLE"] = role
    run = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent, env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    names, first = json.loads(run.stdout.strip().splitlines()[-1])
    return set(names), run.stderr, first


def test_role_profiles_register_their_tools_only():
    everything, err, first = _profile_run(None)
    assert len(everything) > 60 and not err.strip() and first == f"profile: all ({len(everything)} tools)", first
    assert set().union(*server.PROFILES.values()) <= everything, "a profile names a tool the server does not define"
    for role in ("author", "tester"):
        names, err, first = _profile_run(role)
        assert names == server.PROFILES[role], (role, names ^ server.PROFILES[role])
        assert first == f"profile: {role} ({len(names)} of {len(everything)} tools)", first
        assert {"report_gap", "tool_stats", "get_recipe", "env_sql"} <= names and not {"ci_deploy", "merge_run"} & names, role
    assert "push_package" not in server.PROFILES["tester"] and "fire_timer" not in server.PROFILES["author"]
    assert "push_package" in server.PROFILES["author"] and "fire_timer" in server.PROFILES["tester"]
    names, err, first = _profile_run("Reviewer")
    assert names == everything and "unknown CREATIO_KB_ROLE 'reviewer'" in err and first.startswith("profile: all"), err
    names, _, first = _profile_run(" Tester ")
    assert names == server.PROFILES["tester"], "the value is read case- and space-blind"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
