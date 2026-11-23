"""Checks for the push command, without an environment."""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from creatio_schemas import Clio, ProcessSchema  # noqa: E402
from creatio_schemas import push as push_module  # noqa: E402
from creatio_schemas.push import compile_script, creatio_bin, push  # noqa: E402

TABLES = ("SysSchema", "SysPackageSchemaData", "SysPackageSqlScript")
CLEARS = [f'update "{table}" set "IsChanged"=false' for table in TABLES]
SQL = CLEARS[0]
SUMMARY = "Finished building project: Succeeded: True. Errors: 0. Warnings: 0."
# a generated process source as the site writes it (S29-T02): namespace Terrasoft.Core.Process, a ProcessModel wrapper
CLEAN = """namespace Terrasoft.Core.Process
{
	using System;
	using Terrasoft.Core;
	using Terrasoft.Core.Process;

	public class UsrProcessMethodsWrapper : ProcessModel
	{
		public UsrProcessMethodsWrapper(Process process) : base(process) {
			AddScriptTaskMethod("ScriptExecute", ScriptExecute);
		}

		private bool ScriptExecute(ProcessExecutingContext context) {
			return true;
		}
	}
}
"""
BROKEN = CLEAN.replace("return true;", "UsrMissingHelper.Run(); return true;")
os.environ.pop("CREATIO_BIN", None)  # the push tests compile nothing unless a test names the binaries


class FakeClio:
    def __init__(self, env="dev", summary=SUMMARY):
        self.env = env
        self.summary = summary
        self.calls = []
        self.rows = []
        self.site_schemas = []  # the package's schemas on the site (the partial-package check)
        self.sources = [{"Name": "UsrProcess.cs", "Source": base64.b64encode(CLEAN.encode()).decode(), "fresh": True}]

    def execute_sql(self, sql):
        self.run(["execute-sql-script", sql, "-e", self.env])

    def execute_sql_rows(self, sql):
        self.calls.append((["sql-rows", sql], None))
        if '"Schema" from "SysSchema"' in sql:
            return self.site_schemas
        return self.sources if '"SysSchemaSource"' in sql else self.rows

    def run(self, args, cwd=None):
        self.calls.append((args, cwd))
        return self.summary if args[0] == "last-compilation-log" else "done"


def package(root):
    pkg = root / "UsrPkg"
    pkg.mkdir()
    (pkg / "descriptor.json").write_text(json.dumps({"Descriptor": {
        "Name": "UsrPkg", "UId": "00000000-0000-0000-0000-000000000001"
    }}), encoding="utf-8")
    return pkg


def add_process(pkg):
    proc = ProcessSchema.create(pkg, "UsrProcess", "Process")
    proc.add_element("script", "Script", "Script", after="StartEvent1", before="TerminateEvent1")
    proc.save()


def test_sequence_and_publish():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        add_process(pkg)
        fake, logs = FakeClio(), []
        assert push(pkg, "dev", fake, log=logs.append) == 0
        assert fake.calls == [
            (["sql-rows", fake.calls[0][0][1]], None),
            *[(["execute-sql-script", sql, "-e", "dev"], None) for sql in CLEARS],
            (["push-pkg", "UsrPkg", "-e", "dev"], pkg.parent),
            (["sql-rows", fake.calls[5][0][1]], None),
            (["last-compilation-log", "-e", "dev"], None),
            (["compile-configuration", "-e", "dev"], None),
        ]
        assert "publish: started" in logs
        assert '"SysSchemaSource"' in fake.calls[5][0][1] and "'UsrProcess.cs'" in fake.calls[5][0][1]
        assert "  process UsrProcess: script compile not checked (no binaries)" in logs
        assert "script compile: ok (0 compiled, 1 not checked)" in logs


def test_publish_on_process_fixture_copy():
    fixtures = HERE.parent.parent / "process" / "tests" / "fixtures"
    source = next(p for p in fixtures.iterdir() if (p / "descriptor.json").is_file())
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "UsrPkg"
        shutil.copytree(source, pkg)
        add_process(pkg)
        fake = FakeClio()
        assert push(pkg, "dev", fake, log=lambda line: None) == 0
        assert fake.calls[-1][0] == ["compile-configuration", "-e", "dev"]


def test_compilation_failure_stops():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        add_process(pkg)
        fake, logs = FakeClio(summary="Finished building project: Succeeded: False. Errors: 2. Warnings: 0."), []
        assert push(pkg, "dev", fake, log=logs.append) == 1
        assert [args[0] for args, _ in fake.calls] == ["sql-rows"] + ["execute-sql-script"] * 3 + ["push-pkg", "sql-rows", "last-compilation-log"]
        assert any("FAILED" in line and "Errors: 2" in line for line in logs)


def test_missing_summary_and_no_publish():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        fake, logs = FakeClio(), []
        assert push(pkg, "dev", fake, log=logs.append) == 0
        assert len(fake.calls) == 6 and "publish: not needed" in logs
        fake, logs = FakeClio(summary="unexpected"), []
        assert push(pkg, "dev", fake, log=logs.append) == 1
        assert any("summary not found" in line for line in logs)


def test_dry_run_and_non_process_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        entity = pkg / "Schemas" / "UsrEntity"
        entity.mkdir(parents=True)
        (entity / "descriptor.json").write_text(json.dumps({"Descriptor": {"ManagerName": "EntitySchemaManager"}}))
        (entity / "metadata.json").write_text("ProcessSchemaScriptTask")
        fake, logs = FakeClio(), []
        assert push(pkg, "dev", fake, dry_run=True, log=logs.append) == 0
        assert "publish: not needed" in logs
        add_process(pkg)
        logs.clear()
        assert push(pkg, "dev", fake, dry_run=True, log=logs.append) == 0
        assert not fake.calls
        for cmd in ("execute-sql-script", "push-pkg", "last-compilation-log", "compile-configuration"):
            assert any("clio " + cmd in line and "-e dev" in line for line in logs)
        for table in TABLES:
            assert any(table in line for line in logs)
        sent = ("drift", "dependencies", "clear IsChanged", "push-pkg", "compilation log", "publish")
        steps = [line for line in logs if line.split(":")[0] in sent]
        assert len(steps) == len(sent) and all(line.endswith("dry run") for line in steps if not line.startswith("publish"))
        assert logs[-1] == "dry run of UsrPkg -> dev: 12 of 14 steps would run, nothing sent" and not any("pushed" in line for line in logs)  # foreign files and baseline are skipped, not counted


def test_clio_run_and_sql_errors():
    clio = Clio("dev")
    with patch("creatio_schemas.clio.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "ok", "")) as run:
        clio.execute_sql(SQL)
        assert run.call_args.args[0] == ["clio", "execute-sql-script", SQL, "-e", "dev"]
    for code, output in ((1, "failed"), (0, "[ERR] failed")):
        with patch("creatio_schemas.clio.subprocess.run", return_value=subprocess.CompletedProcess([], code, output, "")):
            try:
                clio.execute_sql(SQL)
                assert False, "expected RuntimeError"
            except RuntimeError as e:
                assert "failed" in str(e)
    long = "x" * 300 + "y" * 300  # a failure longer than the old 500-character tail comes back whole
    with patch("creatio_schemas.clio.subprocess.run", return_value=subprocess.CompletedProcess([], 1, long, "")):
        try:
            clio.run(["compile-configuration", "-e", "dev"])
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert str(e) == f"clio exited 1: {long}"


def test_probes_select_items_and_surface_failures():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        for name, manager in (("UsrEntity", "EntitySchemaManager"), ("UsrOther", "ClientUnitSchemaManager")):
            path = pkg / "Schemas" / name
            path.mkdir(parents=True)
            (path / "descriptor.json").write_text(json.dumps({"Descriptor": {"ManagerName": manager}}))
        script = pkg / "SqlScripts" / "UsrScript"
        script.mkdir(parents=True)
        (script / "descriptor.json").write_text("{}")
        fake, logs = FakeClio(), []
        with patch("creatio_schemas.push.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "probe result\n", "")) as run, \
                patch("creatio_schemas.push._git", return_value=None):  # not a repository: the dependency check skips
            assert push(pkg, "dev", fake, probe=True, log=logs.append, skip_drift=True, skip_sql_dates=True) == 0
            calls = [call.args[0] for call in run.call_args_list]
            assert len(calls) == 2
            assert [c[4] for c in calls] == ["UsrEntity", "UsrScript"]
            assert all(c[2:4] == ["probe", str(pkg)] and c[5:] == ["--env", "dev"] for c in calls)
            assert sum("probe result" in line for line in logs) == 2
        with patch("creatio_schemas.push.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "bad probe")):
            logs.clear()
            assert push(pkg, "dev", FakeClio(), probe=True, log=logs.append, skip_drift=True, skip_sql_dates=True) == 1
            assert any("FAILED" in line and "bad probe" in line for line in logs)
        with patch("creatio_schemas.push.subprocess.run") as run:
            logs.clear()
            assert push(pkg, "dev", FakeClio(), probe=True, dry_run=True, log=logs.append) == 0
            assert not run.called and any("UsrEntity" in line for line in logs)


def test_caption_probe_names_a_schema_whose_site_caption_stayed_old():
    from creatio_schemas.push import caption_probe
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        add_process(pkg)  # UsrProcess, caption "Process" in resource.en-US.xml
        fake, logs = FakeClio(), []
        fake.rows = [{"Name": "UsrProcess", "Caption": "Old caption"}]
        lines = caption_probe(pkg, "00000000-0000-0000-0000-000000000001", fake.execute_sql_rows, logs.append)
        assert lines == ["caption of UsrProcess not updated: site 'Old caption', package 'Process'"] and logs == ["  " + lines[0]]
        query = fake.calls[0][0][1]
        assert "'UsrProcess'" in query and "p.\"UId\" = '00000000-0000-0000-0000-000000000001'" in query, query
        fake.rows = [{"Name": "UsrProcess", "Caption": "Process"}]
        assert caption_probe(pkg, "00000000-0000-0000-0000-000000000001", fake.execute_sql_rows, logs.append) == []  # equal: nothing to say
        # a probing push logs it and still succeeds: a stale caption is a note, not a failure
        fake, logs = FakeClio(), []
        fake.rows = [{"Name": "UsrProcess", "Caption": "Old caption"}]
        with patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", fake, probe=True, log=logs.append, skip_drift=True, skip_sql_dates=True) == 0
        assert any("caption of UsrProcess not updated" in line for line in logs), logs


def fake_git(root, status="", head=None):
    head = {} if head is None else head
    def run(package_path, args, allow_not_repo=False):
        if args[:2] == ["rev-parse", "--show-toplevel"]:
            return str(root)
        if args[0] == "log":
            return "2026-01-02T03:04:05+00:00\n"
        if args[0] == "status":
            return status
        if args[:2] == ["rev-parse", "--verify"]:
            return "abc\n"
        if args[0] == "show":  # HEAD:./<file>: what the test says was committed, otherwise nothing
            name = args[1][len("HEAD:./"):]
            if name in head:
                return head[name]
            raise RuntimeError("path does not exist in HEAD")
        if args[0] == "ls-tree":
            folder = args[-1]  # "Files/" or "Schemas/": the committed entries directly under it
            return "".join(f"{folder}{name[len(folder):].split('/')[0]}\n" for name in head if name.startswith(folder))
        raise AssertionError(args)
    return run


def test_drift_and_foreign_task_stop_before_push():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = package(root)
        tasks = root / "tasks"
        current, other = tasks / "UsrCurrent", tasks / "UsrOther"
        current.mkdir(parents=True)
        other.mkdir()
        (current / "schemas.json").write_text(json.dumps({"schemas": ["UsrMine"]}))
        (other / "schemas.json").write_text(json.dumps({"schemas": ["UsrOther"], "files": ["Files/cs/UsrOther.cs"]}))
        project = root / "project.json"
        project.write_text(json.dumps({"paths": {"tasks": "tasks"}}))
        fake, logs = FakeClio(), []
        fake.rows = [{"Name": "UsrDrift"}]
        with patch("creatio_schemas.push._git", side_effect=fake_git(root)):
            assert push(pkg, "dev", fake, log=logs.append) == 1
        assert fake.calls[0][0][0] == "sql-rows" and "2026-01-02T03:04:05+00:00" in fake.calls[0][0][1]
        query = fake.calls[0][0][1]
        assert 'join "SysPackage" p on p."Id" = s."SysPackageId"' in query and "PackageUId" not in query
        assert "p.\"UId\" = '00000000-0000-0000-0000-000000000001'" in query and any("UsrDrift" in line for line in logs)
        status = " M UsrPkg/Schemas/UsrOther/metadata.json\0"
        logs.clear()
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, status)):
            assert push(pkg, "dev", fake, log=logs.append, force=True, project=project, task=current) == 1
        assert any("foreign files: FAILED UsrOther:" in line for line in logs)
        assert not any(args[0] == "push-pkg" for args, _ in fake.calls)
        logs.clear()
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, status)):
            assert push(pkg, "dev", FakeClio(), log=logs.append, project=project) == 1
        assert any("--task is required" in line for line in logs)


def test_sql_date_and_assembly_compile():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = package(root)
        desc = pkg / "descriptor.json"
        package_data = json.loads(desc.read_text())
        package_data["Descriptor"]["Type"] = 1
        desc.write_text(json.dumps(package_data))
        script = pkg / "SqlScripts" / "UsrScript"
        script.mkdir(parents=True)
        descriptor = script / "descriptor.json"
        descriptor.write_bytes(b'\xef\xbb\xbf' + b'{\r\n  "SqlScript": {"ModifiedOnUtc": "\\/Date(1)\\/"}\r\n}')
        before = descriptor.read_bytes()
        status = " M UsrPkg/SqlScripts/UsrScript/UsrScript.sql\0"
        fake, logs = FakeClio(), []
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, status)):
            assert push(pkg, "dev", fake, log=logs.append) == 0
        after = descriptor.read_bytes()
        assert after.startswith(b'\xef\xbb\xbf') and b'\r\n' in after and after != before
        assert "UsrScript" in next(line for line in logs if line.startswith("sql dates:"))
        assert any(args == ["compile-package", "UsrPkg", "-e", "dev", "--wait"] for args, _ in fake.calls)


def test_baseline_accepts_old_errors_and_rejects_new():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = package(root)
        desc = pkg / "descriptor.json"
        data = json.loads(desc.read_text())
        data["Descriptor"]["Type"] = 1
        desc.write_text(json.dumps(data))
        baseline = root / "evidence" / "baseline.txt"
        summary = "Finished building project: Succeeded: False. Errors: 1. Warnings: 0."
        old = "UsrOther.cs(1,1): error CS1000: old error"
        fake = FakeClio(summary=f"{old}\n{summary}")
        assert push(pkg, "dev", fake, baseline=baseline, skip_drift=True, skip_sql_dates=True, log=lambda _: None) == 0
        assert baseline.read_text().splitlines() == [old]
        assert push(pkg, "dev", FakeClio(summary=f"{old}\n{summary}"), baseline=baseline, skip_drift=True,
                    skip_sql_dates=True, log=lambda _: None) == 0
        logs = []
        result = push(pkg, "dev", FakeClio(summary=f"UsrNew.cs: error CS1001: new error\n{summary}"),
                      baseline=baseline, skip_drift=True, skip_sql_dates=True, log=logs.append)
        assert result == 1 and any("new error" in line for line in logs)
        assert baseline.read_text().splitlines() == [old]


def test_a_failed_drift_query_stops_the_push():
    class Broken(FakeClio):
        def execute_sql_rows(self, sql):
            raise RuntimeError('sql: 42703: column s."PackageUId" does not exist')

    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        fake, logs = Broken(), []
        with patch("creatio_schemas.push._git", side_effect=fake_git(Path(tmp))):
            assert push(pkg, "dev", fake, log=logs.append) == 1
        assert any(line.startswith("drift: FAILED sql: 42703") for line in logs) and logs[-1] == "push FAILED at drift"
        assert not fake.calls


def test_clio_sql_reads_a_sqlstate_line_as_an_error():
    clio = Clio("dev")
    answer = subprocess.CompletedProcess([], 0, "42703: column does not exist\nDone\n", "")
    with patch("creatio_schemas.clio.subprocess.run", return_value=answer):
        for call in (lambda: clio.sql("select 1"), lambda: clio.execute_sql("select 1")):
            try:
                call()
                assert False, "expected RuntimeError"
            except RuntimeError as e:
                assert "42703" in str(e)


def test_dropped_dependencies_stop_the_push_unless_forced():
    def descriptor(*names):
        return json.dumps({"Descriptor": {"Name": "UsrPkg", "DependsOn": [{"Name": n} for n in names]}})

    csproj = lambda *refs: "".join(f'<Reference Include="{r}, Version=1.0" />' for r in refs)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = package(root)
        (pkg / "descriptor.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"Descriptor": {
            "Name": "UsrPkg", "UId": "00000000-0000-0000-0000-000000000001", "DependsOn": [{"Name": "Base"}]}}).encode())
        (pkg / "Files").mkdir()
        (pkg / "Files" / "UsrPkg.csproj").write_text(csproj("Terrasoft.Core"), encoding="utf-8")
        head = {"descriptor.json": "\ufeff" + descriptor("Base", "Custom"),
                "Files/UsrPkg.csproj": csproj("Terrasoft.Core", "Newtonsoft.Json")}
        fake, logs = FakeClio(), []
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, head=head)):
            assert push(pkg, "dev", fake, log=logs.append) == 1
        assert "dependencies: FAILED dropped Custom, Newtonsoft.Json" in logs and not any(args[0] == "push-pkg" for args, _ in fake.calls)
        logs.clear()
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, head=head)):
            assert push(pkg, "dev", fake, log=logs.append, force=True) == 0
        assert "dependencies: forced (dropped 2)" in logs
        logs.clear()
        with patch("creatio_schemas.push._git", side_effect=fake_git(root)):  # not committed: nothing to compare with
            assert push(pkg, "dev", FakeClio(), log=logs.append) == 0
        assert any(line.startswith("dependencies: skipped") for line in logs)


def test_a_package_is_found_by_name_or_refused_with_the_hint():
    import os
    from creatio_schemas.cli import resolve_package
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        (root / "packages" / "UsrPkg").mkdir(parents=True)
        (root / "project.json").write_text("{}")
        elsewhere = root / "elsewhere"
        elsewhere.mkdir()
        before = Path.cwd()
        try:
            os.chdir(root)
            assert resolve_package("UsrPkg") == root / "packages" / "UsrPkg"
            os.chdir(elsewhere)
            assert resolve_package("UsrPkg", root / "project.json") == root / "packages" / "UsrPkg"
            try:
                resolve_package("UsrMissing")
                assert False, "expected FileNotFoundError"
            except FileNotFoundError as e:
                assert str(e) == "no package folder named UsrMissing; give its path (packages/UsrMissing)"
        finally:
            os.chdir(before)


def test_dry_run_never_executes_git_or_clio():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        logs, fake = [], FakeClio()
        with patch("creatio_schemas.push.subprocess.run", side_effect=AssertionError("unexpected process")):
            assert push(pkg, "dev", fake, dry_run=True, log=logs.append, baseline=Path(tmp) / "baseline") == 0
        assert not fake.calls and any("git log" in line for line in logs)
        assert any("git status" in line for line in logs) and not (Path(tmp) / "baseline").exists()


def test_task_ownership_includes_files_and_ignores_completed_tasks():
    from creatio_schemas.push import _task_conflicts
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        current, other = root / "UsrCurrent", root / "UsrOther"
        current.mkdir()
        other.mkdir()
        (current / "schemas.json").write_text(json.dumps({"schemas": ["UsrMine"]}))
        (other / "schemas.json").write_text(json.dumps({"schemas": ["UsrForeign"], "files": ["Files/cs/UsrOther.cs"]}))
        changed = ["Schemas/UsrMine/metadata.json", "Resources/UsrForeign.Entity/resource.en-US.xml", "Files/cs/UsrOther.cs"]
        conflicts = _task_conflicts(root, current, changed)
        assert len(conflicts) == 1 and "UsrForeign.Entity" in conflicts[0] and "UsrOther.cs" in conflicts[0]
        assert "UsrMine" not in conflicts[0]
        (other / "success-report.md").write_text("done")
        assert _task_conflicts(root, current, changed) == []


def test_git_status_renames_and_git_failures():
    from creatio_schemas.push import _changed_files, _git
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = package(root)
        status = "R  UsrPkg/Schemas/UsrNew/metadata.json\0UsrPkg/Schemas/UsrOld/metadata.json\0"
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, status)):
            assert _changed_files(pkg) == ["Schemas/UsrNew/metadata.json", "Schemas/UsrOld/metadata.json"]
        with patch("creatio_schemas.push.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 128, "", "fatal: permission denied")):
            try:
                _git(pkg, ["rev-parse", "--show-toplevel"], allow_not_repo=True)
                assert False, "expected git failure"
            except RuntimeError as exc:
                assert "permission denied" in str(exc)


def test_compile_failure_and_unreadable_baseline_errors_stop():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = package(root)
        desc = pkg / "descriptor.json"
        data = json.loads(desc.read_text())
        data["Descriptor"]["Type"] = 1
        desc.write_text(json.dumps(data))

        class BadCompile(FakeClio):
            def run(self, args, cwd=None):
                if args[0] == "compile-package":
                    raise RuntimeError("package compiler failed")
                return super().run(args, cwd)

        logs = []
        assert push(pkg, "dev", BadCompile(), skip_drift=True, skip_sql_dates=True, log=logs.append) == 1
        assert logs[-1] == "push FAILED at compile-package"
        baseline = root / "baseline.txt"
        logs.clear()
        summary = "Finished building project: Succeeded: False. Errors: 2. Warnings: 0."
        assert push(pkg, "dev", FakeClio(summary=summary), baseline=baseline, skip_drift=True,
                    skip_sql_dates=True, log=logs.append) == 1
        assert not baseline.exists() and logs[-1] == "push FAILED at baseline"


def test_future_sql_date_is_not_moved_backwards():
    from creatio_schemas.push import _touch_sql_dates
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        script = pkg / "SqlScripts" / "UsrScript"
        script.mkdir(parents=True)
        descriptor = script / "descriptor.json"
        descriptor.write_bytes(b'{"SqlScript":{"ModifiedOnUtc":"\\/Date(9999999999999)\\/"}}')
        before = descriptor.read_bytes()
        try:
            _touch_sql_dates(pkg, ["SqlScripts/UsrScript/UsrScript.sql"])
            assert False, "expected timestamp failure"
        except RuntimeError as exc:
            assert "could not advance" in str(exc)
        assert descriptor.read_bytes() == before


def test_bindings_that_would_overwrite_the_site_stop_the_push():
    data = HERE.parent.parent / "data" / "tests" / "fixtures" / "UsrPkg"

    class SiteClio(FakeClio):
        def __init__(self, tables):
            super().__init__()
            self.tables, self.selects = tables, []

        def execute_sql_rows(self, sql):
            self.selects.append(sql)
            table = sql.split(' from "', 1)[1].split('"', 1)[0]
            if table not in self.tables:
                raise RuntimeError(f'sql: 42P01: relation "{table}" does not exist')
            return self.tables[table]

    setting = "e0daf018-43e6-49ea-b5e9-db5bf96372ad"
    value = {"Id": "df1c9dc6-328f-4b8b-89f6-f82effb2fa05", "SysAdminUnitId": "a29a3ba5-4b0d-de11-9a51-005056c00008", "IntegerValue": 500,
             "BooleanValue": False, "FloatValue": 0, "SysSettingsId": setting, "GuidValue": None, "DateTimeValue": None, "TextValue": None,
             "IsDef": False, "Position": 2147483647}
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "UsrPkg"
        shutil.copytree(data, pkg)
        site = SiteClio({"SysSettingsValue": [value]})
        logs = []
        # IntegerValue without force update: the install keeps the site's value - one counted line, the push goes on
        assert push(pkg, "dev", site, log=logs.append, skip_drift=True, skip_sql_dates=True, details=Path(tmp) / "d.log") == 0
        assert "bindings: ok (1 differ, not overwritten)" in logs and not any("IntegerValue site 500" in line for line in logs), logs
        assert "  SysSettingsValue df1c9dc6-328f-4b8b-89f6-f82effb2fa05: IntegerValue site 500 -> package 10000" in (Path(tmp) / "d.log").read_text(encoding="utf-8")
        desc = pkg / "Data" / "SysSettingsValue_UsrMaxRows" / "descriptor.json"
        text = desc.read_text(encoding="utf-8-sig")
        i = text.index('"ColumnName": "IntegerValue"')
        desc.write_text(text[:i].rsplit('"IsForceUpdate": false', 1)[0] + '"IsForceUpdate": true' + text[:i].rsplit('"IsForceUpdate": false', 1)[1] + text[i:], encoding="utf-8")
        logs.clear()
        site.calls.clear()
        assert push(pkg, "dev", site, log=logs.append, skip_drift=True, skip_sql_dates=True) == 1
        assert "  SysSettingsValue df1c9dc6-328f-4b8b-89f6-f82effb2fa05: IntegerValue site 500 -> package 10000 (force update)" in logs, logs
        assert '  SysSettings_UsrMaxRows: not compared (sql: 42P01: relation "SysSettings" does not exist)' in logs  # nothing there to overwrite
        assert not any('"UsrOrderStatus"' in s for s in site.selects)  # only localized columns besides the key: nothing to compare
        assert logs[-1] == "push FAILED at bindings" and not any(args[0] == "push-pkg" for args, _ in site.calls)
        select = next(s for s in site.selects if '"SysSettingsValue"' in s)
        assert '"SysAdminUnitId"' in select and '"BinaryValue"' not in select and "\"Id\" = 'df1c9dc6-328f-4b8b-89f6-f82effb2fa05'" in select, select
        assert not any('"Name"' in s for s in site.selects if '"SysSchema"' not in s)  # localized columns are not compared
        logs.clear()
        assert push(pkg, "dev", site, log=logs.append, skip_drift=True, skip_sql_dates=True, force=True) == 0
        assert "bindings: forced (1 overwritten)" in logs
        value["IntegerValue"] = 10000
        logs.clear()
        assert push(pkg, "dev", site, log=logs.append, skip_drift=True, skip_sql_dates=True) == 0 and "bindings: ok" in logs
        logs.clear()
        assert push(pkg, "dev", SiteClio({}), log=logs.append, skip_drift=True, skip_sql_dates=True, dry_run=True) == 0
        assert "bindings: dry run" in logs
    with tempfile.TemporaryDirectory() as tmp:
        logs = []
        assert push(package(Path(tmp)), "dev", FakeClio(), log=logs.append, skip_drift=True, skip_sql_dates=True) == 0
        assert "bindings: not needed" in logs


def test_a_script_process_without_a_fresh_generated_source_stops_the_push():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        add_process(pkg)
        for sources, line in (([], "no generated source after the install"),
                              ([{"Name": "UsrProcess.cs", "Source": "", "fresh": False}],
                               "generated source older than its schema (not regenerated by the install)")):
            fake, logs = FakeClio(), []
            fake.sources = sources
            assert push(pkg, "dev", fake, log=logs.append) == 1
            assert f"  process UsrProcess: {line}" in logs
            assert "push FAILED at script compile" in logs
        fake, logs = FakeClio(), []
        assert push(pkg, "dev", fake, log=logs.append, dry_run=True) == 0 and "script compile: dry run" in logs
        assert not any(args[0] == "sql-rows" for args, _ in fake.calls)
    with tempfile.TemporaryDirectory() as tmp:  # no script task: no query, no compile
        fake, logs = FakeClio(), []
        assert push(package(Path(tmp)), "dev", fake, log=logs.append) == 0 and "script compile: not needed" in logs
        assert not any(args[0] == "sql-rows" and '"SysSchemaSource"' in args[1] for args, _ in fake.calls)


def test_a_compiler_error_in_the_generated_source_stops_the_push_before_the_probes():
    def fake_compile(source, name, bin_dir, extra=()):
        assert bin_dir == Path("C:/bin") and source in (CLEAN, BROKEN)
        if "UsrMissingHelper" in source:
            return "failed", ["CS0103: The name 'UsrMissingHelper' does not exist in the current context"]
        return "ok", []
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        add_process(pkg)
        with patch.object(push_module, "compile_script", fake_compile), patch.object(push_module, "_run_probes") as probes:
            fake, logs = FakeClio(), []
            assert push(pkg, "dev", fake, log=logs.append, bin_dir=Path("C:/bin"), probe=True) == 0
            assert "script compile: ok (1 compiled)" in logs and probes.called
            fake, logs = FakeClio(), []
            fake.sources = [{"Name": "UsrProcess.cs", "Source": BROKEN, "fresh": "true"}]  # plain text is read as it is
            probes.reset_mock()
            assert push(pkg, "dev", fake, log=logs.append, bin_dir=Path("C:/bin"), probe=True) == 1
            assert ("  process UsrProcess: script does not compile: CS0103: The name 'UsrMissingHelper' does not exist "
                    "in the current context") in logs
            assert "push FAILED at script compile" in logs and not probes.called
            assert not any(args[0] == "last-compilation-log" for args, _ in fake.calls)  # right after the install


def test_compile_script_reads_csc_errors_of_the_process_source_only():
    with tempfile.TemporaryDirectory() as tmp:
        assert compile_script(CLEAN, "UsrProcess", None) == ("not checked (no binaries)", [])
        assert compile_script(CLEAN, "UsrProcess", Path(tmp)) == ("not checked (no binaries)", [])
        (Path(tmp) / "tests").mkdir()
        (Path(tmp) / "tests" / "Directory.Build.props").write_text(
            "<Project><PropertyGroup><TestCoreLibPath>C:\\x\\bin</TestCoreLibPath></PropertyGroup></Project>", encoding="utf-8")
        (Path(tmp) / "packages" / "UsrPkg").mkdir(parents=True)
        assert creatio_bin(Path(tmp) / "packages" / "UsrPkg") == Path("C:\\x\\bin")
        assert creatio_bin(Path(tmp) / "packages" / "UsrPkg", "D:/bin") == Path("D:/bin")
        (Path(tmp) / "Terrasoft.Core.dll").write_bytes(b"")
        out = ("C:\\t\\UsrProcess.cs(9,4): error CS0103: The name 'UsrMissingHelper' does not exist in the current context\n"
               "C:\\t\\UsrHelper.cs(3,1): error CS0246: The type or namespace name 'Other' could not be found\n")
        done = subprocess.CompletedProcess([], 1, out, "")
        with patch.object(push_module, "_csc", return_value=Path("csc.dll")), \
                patch.object(push_module.subprocess, "run", return_value=done):
            assert compile_script(BROKEN, "UsrProcess", Path(tmp)) == (
                "failed", ["CS0103: The name 'UsrMissingHelper' does not exist in the current context"])
            done.stdout = out.splitlines()[1]  # an error in the package's Files/cs only: the script itself compiled
            assert compile_script(CLEAN, "UsrProcess", Path(tmp)) == ("ok", [])
            done.stdout = "Unhandled exception"
            assert compile_script(CLEAN, "UsrProcess", Path(tmp))[0] == "not checked (csc: Unhandled exception)"
    local = creatio_bin(HERE)  # the real compiler when this machine has the binaries (S15's tests/Directory.Build.props or CREATIO_BIN)
    if local and (local / "Terrasoft.Core.dll").is_file():
        assert compile_script(CLEAN, "UsrProcess", local) == ("ok", [])
        assert compile_script(BROKEN, "UsrProcess", local) == (
            "failed", ["CS0103: The name 'UsrMissingHelper' does not exist in the current context"])


def test_drift_on_a_clio_failure_is_not_checked_and_the_push_goes_on():
    class NoResult(FakeClio):
        def execute_sql_rows(self, sql):
            if '"ModifiedOn" >' in sql:
                self.calls.append((["sql-rows", sql], None))
                raise RuntimeError("clio execute-sql-script wrote no result (environment 'dev'?): ")
            return super().execute_sql_rows(sql)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = package(root)
        fake, logs = NoResult(), []
        with patch("creatio_schemas.push._git", side_effect=fake_git(root)):
            assert push(pkg, "dev", fake, log=logs.append) == 0
        assert "drift: not checked (clio returned no result)" in logs and any(a[0] == "push-pkg" for a, _ in fake.calls)
        stop, logs = FakeClio(), []  # a real difference still stops
        stop.rows = [{"Name": "UsrDrift"}]
        with patch("creatio_schemas.push._git", side_effect=fake_git(root)):
            assert push(pkg, "dev", stop, log=logs.append) == 1 and logs[-1] == "push FAILED at drift"


def test_a_changed_process_gets_a_new_modified_on_with_its_bytes_kept():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = package(root)
        add_process(pkg)
        desc = pkg / "Schemas" / "UsrProcess" / "descriptor.json"
        text = desc.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\n", "\r\n")
        text = re.sub(r'"\\/Date\(\d+\)\\/"', r'"\\/Date(1000)\\/"', text, count=1)  # an old date: the push must advance it
        desc.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        before = desc.read_bytes()
        status = " M UsrPkg/Schemas/UsrProcess/metadata.json\0"
        fake, logs = FakeClio(), []
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, status)):
            assert push(pkg, "dev", fake, log=logs.append) == 0
        after = desc.read_bytes()
        assert "process dates: UsrProcess" in logs, logs
        assert after.startswith(b"\xef\xbb\xbf") and after.count(b"\r\n") == before.count(b"\r\n") and b"\n" not in after.replace(b"\r\n", b"")
        old, new = (re.search(rb"Date\((\d+)\)", b).group(1) for b in (before, after))
        assert int(new) > int(old) and re.sub(rb"Date\(\d+\)", b"", after) == re.sub(rb"Date\(\d+\)", b"", before)
        logs.clear()  # unchanged: nothing touched; without git, a metadata.json edited after its descriptor is
        with patch("creatio_schemas.push._git", side_effect=fake_git(root)):
            assert push(pkg, "dev", FakeClio(), log=logs.append) == 0 and "process dates: not needed" in logs
        meta = pkg / "Schemas" / "UsrProcess" / "metadata.json"
        os.utime(meta, (desc.stat().st_mtime + 10, desc.stat().st_mtime + 10))
        from creatio_schemas.push import changed_processes
        assert changed_processes(pkg, None) == ["UsrProcess"] and changed_processes(pkg, []) == []
        logs.clear()
        assert push(pkg, "dev", FakeClio(), log=logs.append, dry_run=True) == 0 and "  update ModifiedOnUtc for changed processes" in logs


def test_a_changed_binding_gets_a_new_modified_on_with_its_bytes_kept():
    data = HERE.parent.parent / "data" / "tests" / "fixtures" / "UsrPkg"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = root / "UsrPkg"
        shutil.copytree(data, pkg)
        name = "SysSettingsValue_UsrMaxRows"
        desc, other = pkg / "Data" / name / "descriptor.json", pkg / "Data" / "SysSettings_UsrMaxRows" / "descriptor.json"
        text = desc.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\n", "\r\n")
        text = re.sub(r'"\\/Date\(\d+\)\\/"', r'"\\/Date(1000)\\/"', text, count=1)  # an old date: the push must advance it
        desc.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        before, other_before = desc.read_bytes(), other.read_bytes()
        status = f" M UsrPkg/Data/{name}/data.json\0"
        logs = []
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, status)):
            assert push(pkg, "dev", FakeClio(), log=logs.append, skip_drift=True) == 0
        after = desc.read_bytes()
        assert f"process dates: binding {name}" in logs, logs
        assert after.startswith(b"\xef\xbb\xbf") and after.count(b"\r\n") == before.count(b"\r\n")
        old, new = (re.search(rb"Date\((\d+)\)", b).group(1) for b in (before, after))
        assert int(new) > int(old) and re.sub(rb"Date\(\d+\)", b"", after) == re.sub(rb"Date\(\d+\)", b"", before)
        assert other.read_bytes() == other_before  # an unchanged binding is not touched
        from creatio_schemas.push import changed_bindings
        assert changed_bindings(pkg, []) == []
        os.utime(pkg / "Data" / name / "data.json", (desc.stat().st_mtime + 10, desc.stat().st_mtime + 10))
        assert changed_bindings(pkg, None) == [name]  # without git: data.json written after its descriptor
        logs.clear()
        assert push(pkg, "dev", FakeClio(), log=logs.append, skip_drift=True, skip_sql_dates=True) == 0 and "process dates: skipped" in logs
        logs.clear()
        assert push(pkg, "dev", FakeClio(), log=logs.append, dry_run=True) == 0 and "  update ModifiedOnUtc for changed bindings" in logs


def test_a_package_with_fewer_schemas_than_head_or_the_site_stops_even_forced():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = package(root)
        add_process(pkg)
        head = {"Schemas/UsrProcess/descriptor.json": "", "Schemas/UsrGone/descriptor.json": ""}
        fake, logs = FakeClio(), []
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, head=head)):
            assert push(pkg, "dev", fake, log=logs.append, force=True) == 1
        assert "package schemas: FAILED package install deletes schemas absent from the package: UsrGone" in logs
        assert not any(a[0] == "push-pkg" for a, _ in fake.calls)
        fake, logs = FakeClio(), []  # no git: the site's schemas of the package decide
        fake.site_schemas = [{"Schema": "UsrProcess"}, {"Schema": "UsrOnSite"}]
        with patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", fake, log=logs.append, skip_drift=True, skip_sql_dates=True) == 1
        assert "package schemas: FAILED package install deletes schemas absent from the package: UsrOnSite" in logs
        query = next(a[1] for a, _ in fake.calls if a[0] == "sql-rows")
        assert '"SysSchema"' in query and "p.\"UId\" = '00000000-0000-0000-0000-000000000001'" in query
        fake.site_schemas = [{"Schema": "UsrProcess"}]
        logs.clear()
        with patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", fake, log=logs.append, skip_drift=True, skip_sql_dates=True) == 0 and "package schemas: ok" in logs


def test_a_publish_error_is_printed_whole_and_names_the_pushed_schema():
    long = ("Terrasoft.Common.InvalidObjectStateException: compilation failed\n   at Terrasoft.Core.Configuration.Build()\n"
            "---> System.Exception: " + "x" * 300 + " in UsrProcess\n   at Terrasoft.Core.Process.Compile()\n")

    class Failing(FakeClio):
        def run(self, args, cwd=None):
            if args[0] == "compile-configuration":
                self.calls.append((args, cwd))
                raise RuntimeError(f"clio exited 1: {long}")
            return super().run(args, cwd)

    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        add_process(pkg)
        logs = []
        with patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", Failing(), log=logs.append, skip_drift=True, skip_sql_dates=True) == 1
        failed = next(line for line in logs if line.startswith("publish: FAILED"))
        assert "x" * 300 + " in UsrProcess" in failed and "   at " not in failed, failed
        assert "publish: pushed schemas among the failed: UsrProcess" in logs and logs[-1] == "push FAILED at publish"


def test_with_details_the_answer_is_the_summary_and_the_file_has_everything():
    from creatio_schemas.push import details_path
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        add_process(pkg)
        logs, details = [], Path(tmp) / "task" / "push.log"
        with patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", FakeClio(), log=logs.append, skip_drift=True, skip_sql_dates=True, details=details) == 0
        assert not any(line.startswith("  ") for line in logs) and logs[-1] == f"details: {details}"
        assert {"script compile: ok (0 compiled, 1 not checked)", "publish: ok", "package schemas: ok"} <= set(logs), logs
        text = details.read_text(encoding="utf-8")
        assert "  process UsrProcess: script compile not checked (no binaries)" in text and "publish: ok" in text
        assert details_path(pkg, Path(tmp) / "task").parent == Path(tmp) / "task" and details_path(pkg).name.startswith("push-UsrPkg-")


def test_verify_says_per_schema_whether_the_site_runs_the_working_copy():
    import hashlib
    from creatio_schemas import verify as verify_module
    from creatio_schemas.verify import render, verify

    def md5(path):
        return hashlib.md5(path.read_bytes()).hexdigest()

    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        add_process(pkg)
        page = pkg / "Schemas" / "UsrOrderPage"
        page.mkdir(parents=True)
        (page / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": "UsrOrderPage", "ManagerName": "ClientUnitSchemaManager"}}), encoding="utf-8")
        (page / "metadata.json").write_bytes(b"{}\r\n")
        (page / "UsrOrderPage.js").write_bytes(b"define('UsrOrderPage', [], function() {\r\n\treturn {};\r\n});\r\n")
        for name in ("UsrGone", "UsrLf"):
            (pkg / "Schemas" / name).mkdir()
            (pkg / "Schemas" / name / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": name}}), encoding="utf-8")
            (pkg / "Schemas" / name / "metadata.json").write_bytes(b'{"a": 1}\r\n')
        proc = pkg / "Schemas" / "UsrProcess" / "metadata.json"

        class Site:
            def __init__(self, sources):  # the site holds what the working copy holds now
                self.sources, self.asked = sources, []
                self.rows = [{"name": "UsrProcess", "manager": "ProcessSchemaManager", "meta": md5(proc), "content": ""},
                             {"name": "UsrOrderPage", "manager": "ClientUnitSchemaManager", "meta": md5(page / "metadata.json"),
                              "content": md5(page / "UsrOrderPage.js")},
                             {"name": "UsrLf", "manager": "EntitySchemaManager", "meta": hashlib.md5(b'{"a": 1}\n').hexdigest(), "content": ""}]

            def sql(self, text):
                self.asked.append(text)
                return self.sources if '"SysSchemaSource"' in text else self.rows

        fresh = [{"Name": "UsrProcess.cs", "Source": base64.b64encode(CLEAN.encode()).decode(), "fresh": "true"}]
        served = lambda env, name: 'Terrasoft.configuration.Structures["UsrOrderPage"] = {};\r\ndefine("UsrOrderPage", [], function() {\n\treturn {};\n});\n'
        site = Site(fresh)
        results = verify(pkg, site, fetch=served)
        assert results == [("UsrGone", "not on the site"), ("UsrLf", "same (line endings)"), ("UsrOrderPage", "same"),
                           ("UsrProcess", "same")], results  # served: the body with its define quoted the site's way
        assert "p.\"Name\" = 'UsrPkg'" in site.asked[0] and "md5(s.\"MetaData\")" in site.asked[0]
        assert render(results).splitlines()[-1] == "3 same, 1 not"
        # a changed body, an old served copy, an unpublished and a broken process
        before = Site(fresh)
        (page / "UsrOrderPage.js").write_bytes(b"define('UsrOrderPage', [], function() { return {x: 1}; });\r\n")
        changed = dict(verify(pkg, before, ["UsrOrderPage"], fetch=served))
        assert changed["UsrOrderPage"].startswith("differs (body: site ") and " repo " in changed["UsrOrderPage"], changed
        site = Site(fresh)  # pushed, but the site still serves the old body
        assert dict(verify(pkg, site, ["UsrOrderPage"], fetch=served))["UsrOrderPage"].startswith("not served: conf/content holds another body")
        assert dict(verify(pkg, site, ["UsrOrderPage"], fetch=lambda e, n: None))["UsrOrderPage"] == "not served: conf/content has no such file"
        assert dict(verify(pkg, Site([]), ["UsrProcess"]))["UsrProcess"] == "not published: no generated source"
        old = [dict(fresh[0], fresh="false")]
        assert dict(verify(pkg, Site(old), ["UsrProcess"]))["UsrProcess"] == "not published: generated source older than its schema"
        with patch.object(verify_module, "compile_script", lambda *a, **k: ("failed", ["CS0103: no UsrMissingHelper", "CS0246: x"])):
            assert dict(verify(pkg, Site(fresh), ["usrprocess"]))["UsrProcess"] == "compile error: CS0103: no UsrMissingHelper (+1 more)"
        try:
            verify(pkg, Site(fresh), ["UsrNope"])
            raise AssertionError("no error")
        except KeyError as e:
            assert "no schema usrnope in UsrPkg" in str(e)
        # the CLI: exit 1 on a difference
        sys.path.insert(0, str(HERE.parent))
        import push as cli
        with patch("creatio_schemas.environment.open_environment", lambda name, project=None: Site(fresh)), \
                patch.object(verify_module, "served", served):
            assert cli.main(["verify", str(pkg), "-e", "dev", "UsrLf"]) == 0
            assert cli.main(["verify", str(pkg), "-e", "dev"]) == 1


def test_served_goes_through_environment_fetch():
    """`served` asks `Environment.fetch` with `Accept: */*` under /0/ (.NET Framework); a 404 is None (S33-T05 4g)."""
    import io
    import urllib.error
    from email.message import Message
    from creatio_schemas.environment import Environment
    from creatio_schemas.verify import served
    seen = []

    class Opener:
        def open(self, req, timeout=None):
            seen.append((req.full_url, req.get_header("Accept")))
            headers = Message()
            if req.full_url.endswith("Login"):
                return type("R", (), {"status": 200, "headers": headers, "read": lambda self: b'{"Code": 0}'})()
            if "Missing" in req.full_url:
                raise urllib.error.HTTPError(req.full_url, 404, "nf", headers, io.BytesIO(b""))
            return type("R", (), {"status": 200, "headers": headers, "read": lambda self: b"define(1)"})()

    env = Environment("https://site.example/", "u", "p", opener=Opener())
    assert served(env, "UsrPage") == "define(1)" and served(env, "UsrMissing") is None
    assert seen[1] == ("https://site.example/0/conf/content/UsrPage.js", "*/*"), seen


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
