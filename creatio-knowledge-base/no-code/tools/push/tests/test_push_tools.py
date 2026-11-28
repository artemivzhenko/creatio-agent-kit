"""Checks for the push command, without an environment."""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from creatio_schemas import Clio, ProcessSchema  # noqa: E402
from creatio_schemas import push as push_module  # noqa: E402
from creatio_schemas.push import NO_RESULT, compile_script, creatio_bin, push  # noqa: E402

TABLES = ("SysSchema", "SysPackageSchemaData", "SysPackageSqlScript")
CLEARS = [f'update "{table}" set "IsChanged"=false' for table in TABLES] + [
    'update "SysLocalizableValue" set "IsChanged"=false where "SysSchemaId" in (select s."Id" from "SysSchema" s '
    "join \"SysPackage\" p on p.\"Id\" = s.\"SysPackageId\" where p.\"UId\" = '00000000-0000-0000-0000-000000000001')"]
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

    def version(self):
        return "8.1.0.158"

    def execute_sql_rows(self, sql):
        self.calls.append((["sql-rows", sql], None))
        if 's."Name" "Schema"' in sql:
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
            (["sql-rows", fake.calls[6][0][1]], None),
            (["last-compilation-log", "-e", "dev"], None),
            (["compile-configuration", "-e", "dev"], None),
        ]
        assert "publish: started" in logs
        assert '"SysSchemaSource"' in fake.calls[6][0][1] and "'UsrProcess.cs'" in fake.calls[6][0][1]
        assert "  process UsrProcess: script compile not checked (no binaries)" in logs
        assert "script compile: ok (0 compiled, 1 not checked)" in logs


def test_clear_isChanged_retries_once_on_a_web_timeout():
    class Busy(FakeClio):
        def __init__(self, failures):
            super().__init__()
            self.failures = failures

        def execute_sql(self, sql):
            if self.failures:
                self.failures -= 1
                raise RuntimeError("sql: The operation has timed out")
            super().execute_sql(sql)

    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        fake, logs = Busy(1), []
        with patch("creatio_schemas.push.time.sleep") as nap:
            assert push(pkg, "dev", fake, log=logs.append, skip_drift=True) == 0
        assert nap.call_args.args == (30,) and "  clear IsChanged: web timeout, retry in 30 s" in logs
        assert any(line.startswith("clear IsChanged: ok") for line in logs)
        fake, logs = Busy(2), []
        with patch("creatio_schemas.push.time.sleep"):
            assert push(pkg, "dev", fake, log=logs.append, skip_drift=True) == 1
        assert any(line.startswith("clear IsChanged: FAILED sql: The operation has timed out") for line in logs)
        assert logs[-1] == "push FAILED at clear IsChanged"


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
        assert [args[0] for args, _ in fake.calls] == ["sql-rows"] + ["execute-sql-script"] * 4 + ["push-pkg", "sql-rows", "last-compilation-log"]
        assert any("FAILED" in line and "Errors: 2" in line for line in logs)


def test_missing_summary_and_no_publish():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        fake, logs = FakeClio(), []
        assert push(pkg, "dev", fake, log=logs.append) == 0
        assert len(fake.calls) == 7 and "publish: not needed" in logs
        fake, logs = FakeClio(summary="unexpected"), []
        assert push(pkg, "dev", fake, log=logs.append) == 1
        assert any("summary not found" in line for line in logs)


def test_publish_reason_is_logged_and_objects_and_timer_starts_need_none():
    with tempfile.TemporaryDirectory() as tmp:  # P-2.26, P-2.27: a new object and a timer-only process are live without the compile
        pkg = package(Path(tmp))
        entity = pkg / "Schemas" / "UsrOrder"
        entity.mkdir(parents=True)
        (entity / "descriptor.json").write_text(json.dumps({"Descriptor": {"ManagerName": "EntitySchemaManager"}}))
        proc = ProcessSchema.create(pkg, "UsrTimer", "Timer")
        proc.add_element("startTimer", "Tick", "Tick", after="StartEvent1", before="TerminateEvent1")
        proc.remove_element("StartEvent1")
        proc.save()
        fake, logs = FakeClio(), []
        fake.site_schemas = []  # the object is new on the site
        assert push(pkg, "dev", fake, log=logs.append) == 0
        assert "publish: not needed" in logs and not any(line.startswith("publish: needed") for line in logs)
        add_process(pkg)
        fake, logs = FakeClio(), []
        assert push(pkg, "dev", fake, log=logs.append) == 0
        assert "publish: needed (script task UsrProcess)" in logs and "publish: started" in logs


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
        assert logs[-1] == "dry run of UsrPkg -> dev: 13 of 15 steps would run, nothing sent" and not any("pushed" in line for line in logs)  # foreign files and baseline are skipped, not counted


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


def test_probes_line_counts_the_skipped_objects():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        for name in ("UsrEntity", "UsrOther"):
            (pkg / "Schemas" / name).mkdir(parents=True)
            (pkg / "Schemas" / name / "descriptor.json").write_text(json.dumps({"Descriptor": {"ManagerName": "EntitySchemaManager"}}))
        logs = []
        skip = subprocess.CompletedProcess([], 0, "skipped: parent Base not in the workspace (objects.py base ...)\n", "")
        with patch("creatio_schemas.push.subprocess.run", return_value=skip), patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", FakeClio(), probe=True, log=logs.append, skip_drift=True, skip_sql_dates=True) == 0
        assert "probes: ok (2 skipped: UsrEntity, UsrOther)" in logs


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
            "Name": "UsrPkg", "UId": "00000000-0000-0000-0000-000000000001", "ModifiedOnUtc": "/Date(1)/",
            "DependsOn": [{"UId": "00000000-0000-4000-8000-0000000000b1", "PackageVersion": "7.8.0", "Name": "Base"}]}}).replace(
            "/Date(1)/", "\\/Date(1)\\/").encode())  # the form clio writes
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
        # D88: a changed DependsOn advances the package descriptor's date, or push-pkg skips the change
        assert "process dates: package (descriptor.json, DependsOn changed)" in logs, logs
        assert "Date(1)" not in (pkg / "descriptor.json").read_text(encoding="utf-8-sig")
        assert (pkg / "descriptor.json").read_bytes().startswith(b"\xef\xbb\xbf")
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
                assert str(e) == f"no package folder named UsrMissing: looked under {elsewhere / 'packages'}; give its path (packages/UsrMissing)"
            (root / "ws" / "packages" / "UsrWs").mkdir(parents=True)
            (root / "project.json").write_text(json.dumps({"package": {"workspace": "ws"}}))
            assert resolve_package("UsrWs", root / "project.json") == root / "ws" / "packages" / "UsrWs"  # relative workspace
            (root / "project.json").write_text(json.dumps({"package": {"workspace": str(root / "ws")}}))
            assert resolve_package("UsrWs", root / "project.json") == root / "ws" / "packages" / "UsrWs"  # absolute workspace
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
        assert logs[-1].startswith("push FAILED at compile-package; the package is on the site (push-pkg ok)")
        baseline = root / "baseline.txt"
        logs.clear()
        summary = "Finished building project: Succeeded: False. Errors: 2. Warnings: 0."
        assert push(pkg, "dev", FakeClio(summary=summary), baseline=baseline, skip_drift=True,
                    skip_sql_dates=True, log=logs.append) == 1
        assert not baseline.exists() and logs[-1].startswith("push FAILED at baseline; the package is on the site")


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
        assert any("push.py page" in line and "P-2.18" in line for line in logs), logs  # the way out of a stop it cannot lift
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
            assert any(l.startswith("push FAILED at script compile") for l in logs)
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
            assert any(l.startswith("push FAILED at script compile") for l in logs) and not probes.called
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



def test_a_renamed_schema_is_a_note_and_a_real_deletion_still_stops():
    """A site row whose UId is a folder here under another name is a rename (HEAD may still hold the old name); a UId
    absent from the folder is a deletion."""
    from creatio_schemas.push import missing_schemas
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = package(root)
        folder = pkg / "Schemas" / "UsrNewName"
        folder.mkdir(parents=True)
        (folder / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": "UsrNewName",
                                                                          "UId": "5d2a1c3e-0000-4000-8000-000000000001"}}), encoding="utf-8")
        head = {"Schemas/UsrOldName/descriptor.json": ""}
        fake, logs = FakeClio(), []
        fake.site_schemas = [{"Schema": "UsrOldName", "UId": "5D2A1C3E-0000-4000-8000-000000000001"}]
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, head=head)):
            assert push(pkg, "dev", fake, log=logs.append, skip_sql_dates=True) == 0, logs
        assert "package schemas: ok; renamed UsrOldName -> UsrNewName" in logs, logs
        assert logs[0] == "clio: 8.1.0.158"
        query = next(a[1] for a, _ in fake.calls if a[0] == "sql-rows" and '"Schema"' in a[1])
        assert 's."UId"::text "UId"' in query
        fake, logs = FakeClio(), []  # another UId: the old row goes, the stop as before
        fake.site_schemas = [{"Schema": "UsrOldName", "UId": "5d2a1c3e-0000-4000-8000-000000000002"}]
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, head=head)):
            assert push(pkg, "dev", fake, log=logs.append, skip_sql_dates=True) == 1
        assert "package schemas: FAILED package install deletes schemas absent from the package: UsrOldName" in logs, logs
        assert missing_schemas(pkg, {"UsrOldName"}, None) == (["UsrOldName"], [])  # no site answer: HEAD names decide
        assert missing_schemas(pkg, None, {"UsrNewName": "5d2a1c3e-0000-4000-8000-000000000001", "UsrGone": ""}) == (["UsrGone"], [])
        # D11: the site renamed first - the old name is in HEAD only; its committed UId is the folder's
        head = {"Schemas/UsrOldName/descriptor.json": json.dumps({"Descriptor": {"UId": "5d2a1c3e-0000-4000-8000-000000000001"}})}
        fake, logs = FakeClio(), []
        fake.site_schemas = [{"Schema": "UsrNewName", "UId": "5d2a1c3e-0000-4000-8000-000000000001"}]
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, head=head)):
            assert push(pkg, "dev", fake, log=logs.append, skip_sql_dates=True) == 0, logs
        assert "package schemas: ok; renamed UsrOldName -> UsrNewName" in logs, logs


def test_a_changed_client_schema_gets_a_new_date_and_its_strings_are_cleared():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = package(root)
        page = pkg / "Schemas" / "UsrOrderPage"
        page.mkdir(parents=True)
        (page / "descriptor.json").write_bytes(b'\xef\xbb\xbf{\r\n  "Descriptor": {"ManagerName": "ClientUnitSchemaManager", '
                                               b'"ModifiedOnUtc": "\\/Date(1)\\/"}\r\n}')
        (page / "UsrOrderPage.js").write_text("define('UsrOrderPage', [], function() {});", encoding="utf-8")
        status = " M UsrPkg/Schemas/UsrOrderPage/UsrOrderPage.js\0"
        fake, logs = FakeClio(), []
        with patch("creatio_schemas.push._git", side_effect=fake_git(root, status)):
            assert push(pkg, "dev", fake, log=logs.append) == 0, logs
        after = (page / "descriptor.json").read_bytes()  # D68: the install regenerates conf/content only for a moved date
        assert "process dates: client UsrOrderPage" in logs and b"Date(1)" not in after and after.startswith(b"\xef\xbb\xbf") and b"\r\n" in after
        assert ("clear IsChanged: ok (SysSchema, SysPackageSchemaData, SysPackageSqlScript, SysLocalizableValue of the package's "
                "schemas)") in logs, logs  # D82
        assert [a for a, _ in fake.calls if a[0] == "execute-sql-script"][-1][1] == CLEARS[-1]


def test_an_empty_select_is_an_empty_answer_and_a_silent_clio_is_no_result():
    clio = Clio("dev")
    done = "select 1 where false\n\nDone\n"  # an older clio: zero rows, no -d file, Done
    with patch("creatio_schemas.clio.subprocess.run", return_value=subprocess.CompletedProcess([], 0, done, "")):
        assert clio.execute_sql_rows("select 1 where false") == []
    with patch("creatio_schemas.clio.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "[INF] - Done\n", "")):
        assert clio.sql("select 1 where false") == []
    with patch("creatio_schemas.clio.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")):
        try:
            clio.sql("select 1")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert NO_RESULT in str(e)
    with patch("creatio_schemas.clio.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "[INF] - clio:   8.1.0.158\n", "")):
        assert clio.version() == "8.1.0.158"
    with patch("creatio_schemas.clio.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "")):
        assert clio.version() == "unknown"


def test_both_sql_clients_read_an_empty_file_as_zero_rows_and_a_missing_one_as_a_lost_answer():
    """8.3.2 test site, clio 8.1.0.158: `select 1 where false` writes `[]` and prints `Results saved to ...`; an update writes
    its count. No file after `Results saved to`, or no file and no `Done`, is a lost answer (S48-T03, T04's finding)."""
    from creatio_schemas.environment import Environment
    saved = "select 1 where false\n[INF] - Results saved to: out.json\n[]\n[INF] - Done\n"

    def clio_writing(text):
        def run(args, **kwargs):
            if text is not None:
                Path(args[args.index("-d") + 1]).write_text(text, encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, saved, "")
        return run
    clio = Clio("dev")
    with patch("creatio_schemas.clio.subprocess.run", side_effect=clio_writing("[]")):
        assert clio.sql("select 1 where false") == []
    with patch("creatio_schemas.clio.subprocess.run", side_effect=clio_writing("0")):
        assert clio.sql("update x") == []
    with patch("creatio_schemas.clio.subprocess.run", side_effect=clio_writing(None)):
        try:
            clio.sql("select 1")
            raise AssertionError("a lost answer read as zero rows")
        except RuntimeError as e:
            assert NO_RESULT in str(e) and "'dev'" in str(e)
    env = Environment("https://dev.example.com", "Supervisor", "", clio_name="dev",
                      clio_run=lambda args: (0, "[INF] - Results saved to: out.json\n[INF] - Done"))
    try:  # D12/D72: Environment.sql read a missing file as "no rows" and a lost answer became "no SysSchema copy"
        env.sql("select 1")
        raise AssertionError("a lost answer read as zero rows")
    except RuntimeError as e:
        assert NO_RESULT in str(e) and "'dev'" in str(e)
    assert Environment("https://dev.example.com", "Supervisor", "", clio_name="dev", clio_run=lambda args: (0, "Done")).sql("select 1 where false") == []


def test_compile_package_without_wait_polls_the_compile_history():
    class OldClio(FakeClio):
        """A clio that refuses --wait; the package's CompilationHistory row changes on the third poll."""

        def __init__(self, result=True, polls=2, project="UsrPkg.csproj"):
            super().__init__()
            self.answers = [[{"at": "2026-11-01 10:00:00"}]] + [[]] * polls + [
                [{"project": project, "at": "2026-11-24 10:00:00", "ok": result}]]

        def version(self):
            return "8.0.1.20"

        def run(self, args, cwd=None):
            if args[0] == "compile-package" and "--wait" in args:
                self.calls.append((args, cwd))
                raise RuntimeError("clio exited 1: ERROR(S):\n  Option 'wait' is unknown.\n")
            return super().run(args, cwd)

        def execute_sql_rows(self, sql):
            if '"CompilationHistory"' in sql:
                self.calls.append((["sql-rows", sql], None))
                return self.answers.pop(0)
            return super().execute_sql_rows(sql)

    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        desc = pkg / "descriptor.json"
        data = json.loads(desc.read_text())
        data["Descriptor"]["Type"] = 1
        desc.write_text(json.dumps(data))
        quiet = dict(skip_drift=True, skip_sql_dates=True)
        with patch("creatio_schemas.push._git", return_value=None), patch("creatio_schemas.push.time.sleep") as sleep:
            fake, logs = OldClio(), []
            assert push(pkg, "dev", fake, log=logs.append, **quiet) == 0, logs
            assert logs[0] == "clio: 8.0.1.20"
            assert any(line.startswith("compile-package: ok (clio 8.0.1.20: no --wait, polled ") for line in logs), logs
            assert ["compile-package", "UsrPkg", "-e", "dev"] in [a for a, _ in fake.calls] and sleep.call_count == 2
            assert "\"CreatedOn\" > '2026-11-01 10:00:00'" in [a[1] for a, _ in fake.calls if a[0] == "sql-rows" and "CompilationHistory" in a[1]][1]
            fake, logs = OldClio(result=False, polls=0), []
            assert push(pkg, "dev", fake, log=logs.append, **quiet) == 1
            assert logs[-2].startswith("compile-package: FAILED CompilationHistory: UsrPkg.csproj failed") and logs[-1].startswith("push FAILED at compile-package; the package is on the site (push-pkg ok)")
            fake, logs = OldClio(polls=0, project="Terrasoft.Configuration.ODataEntities.csproj"), []  # D55: no <Pkg>.csproj row
            assert push(pkg, "dev", fake, log=logs.append, **quiet) == 0, logs
            assert any(l.endswith("; no UsrPkg.csproj row, Terrasoft.Configuration.ODataEntities.csproj ok)") for l in logs), logs

            class Refusing(FakeClio):  # another failure of compile-package is not the fallback
                def run(self, args, cwd=None):
                    if args[0] == "compile-package":
                        raise RuntimeError("clio exited 1: build failed")
                    return super().run(args, cwd)
            logs = []
            assert push(pkg, "dev", Refusing(), log=logs.append, **quiet) == 1 and "compile-package: FAILED clio exited 1: build failed" in logs


def _assembly(root):
    pkg = package(root)
    data = json.loads((pkg / "descriptor.json").read_text())
    data["Descriptor"]["Type"] = 1
    (pkg / "descriptor.json").write_text(json.dumps(data))
    return pkg


def test_compile_package_retries_a_busy_compiler_and_reads_build_result_0_as_success():
    class Busy(FakeClio):
        def __init__(self, answers):
            super().__init__()
            self.answers = answers  # one per compile-package call: an exception text, or None for "done"

        def run(self, args, cwd=None):
            if args[0] == "compile-package":
                self.calls.append((args, cwd))
                text = self.answers.pop(0)
                if text:
                    raise RuntimeError(f"clio exited 1: {text}")
                return "done"
            return super().run(args, cwd)

    busy = "InvalidOperationException: Cannot run compilation because another compilation is in progress"
    zero = "Package compilation failed for 'UsrPkg' (build result 0). The new code was not loaded"
    quiet = dict(skip_drift=True, skip_sql_dates=True)
    with tempfile.TemporaryDirectory() as tmp, patch("creatio_schemas.push._git", return_value=None), \
            patch("creatio_schemas.push.time.sleep") as sleep:
        pkg = _assembly(Path(tmp))
        fake, logs = Busy([busy, busy, None]), []  # K37: busy twice, then the build
        assert push(pkg, "dev", fake, log=logs.append, **quiet) == 0, logs
        assert sleep.call_count == 2 and logs.count("  ... another compilation is in progress: retry in 15 s (0 s waited)") == 2, logs
        assert "compile-package: ok" in logs
        logs = []  # E9: clio says failed, the build result is BuildResultType.Success, no error line
        assert push(pkg, "dev", Busy([zero]), log=logs.append, **quiet) == 0, logs
        assert any(l.startswith("compile-package: ok (clio said failed, but the build result is BuildResultType") for l in logs), logs
        logs = []  # build result 1 or a compiler error is a failure
        assert push(pkg, "dev", Busy([zero.replace("result 0", "result 1")]), log=logs.append, **quiet) == 1
        logs = []
        assert push(pkg, "dev", Busy([zero + "\n(CS0103) in UsrClass.cs at (3,1): no UsrHelper"]), log=logs.append, **quiet) == 1
        assert logs[-1].startswith("push FAILED at compile-package; the package is on the site (push-pkg ok)")


def test_compilation_log_of_an_assembly_package_fails_on_its_own_error_only():
    own = ("Pkg/UsrPkg/Files/cs/UsrClass.cs(3,1): error CS0103: The name 'UsrHelper' does not exist\n"
           "Finished building project: Succeeded: False. Errors: 1. Warnings: 0.")
    foreign = own.replace("Pkg/UsrPkg/", "Pkg/UsrOther/")
    quiet = dict(skip_drift=True, skip_sql_dates=True)
    with tempfile.TemporaryDirectory() as tmp, patch("creatio_schemas.push._git", return_value=None):
        pkg = _assembly(Path(tmp))
        logs = []  # D55: the log said Succeeded: False and the step said ok
        assert push(pkg, "dev", FakeClio(summary=own), log=logs.append, **quiet) == 1
        assert ("compilation log: FAILED compile FAILED: Pkg/UsrPkg/Files/cs/UsrClass.cs(3,1): error CS0103: The name "
                "'UsrHelper' does not exist") in logs, logs
        logs = []
        assert push(pkg, "dev", FakeClio(summary=foreign), log=logs.append, **quiet) == 0
        assert ("compilation log: ok (Finished building project: Succeeded: False. Errors: 1. Warnings: 0. none in UsrPkg; "
                "compile-package decides)") in logs, logs
        logs = []  # Succeeded: False with no error count is a failure of a plain package
        (Path(tmp) / "plain").mkdir()
        plain = package(Path(tmp) / "plain")
        assert push(plain, "dev", FakeClio(summary="Finished building project: Succeeded: False. Errors: 0."), log=logs.append, **quiet) == 1


def test_a_long_clio_call_prints_a_heartbeat_on_the_summary():
    class Slow(FakeClio):
        def run(self, args, cwd=None):
            if args[0] == "push-pkg":
                time.sleep(0.25)
            return super().run(args, cwd)

    with tempfile.TemporaryDirectory() as tmp, patch("creatio_schemas.push._git", return_value=None), \
            patch.object(push_module, "HEARTBEAT_S", 0.1):
        pkg, logs = package(Path(tmp)), []
        assert push(pkg, "dev", Slow(), log=logs.append, details=Path(tmp) / "d.log", skip_drift=True) == 0
        assert any(re.fullmatch(r"  \.\.\. still running \(0 s\)", l) for l in logs), logs


def test_drift_lets_a_site_schema_equal_to_the_working_copy_pass_and_names_a_real_change():
    import hashlib
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = package(root)
        page = pkg / "Schemas" / "UsrOrderPage"
        page.mkdir(parents=True)
        (page / "metadata.json").write_bytes(b'{"MetaData": {}}\r\n')
        (page / "UsrOrderPage.js").write_bytes(b"define('UsrOrderPage', [], function() {});\r\n")
        md5 = lambda b: hashlib.md5(b).hexdigest()  # noqa: E731
        ours = {"Name": "UsrOrderPage", "modifiedOn": "2026-11-26 10:12:33.1", "modifiedBy": "Supervisor", "isChanged": "false",
                "meta": md5(b'{"MetaData": {}}\n'), "content": md5((page / "UsrOrderPage.js").read_bytes())}  # metadata with LF
        fake, logs = FakeClio(), []
        fake.rows = [ours]
        with patch("creatio_schemas.push._git", side_effect=fake_git(root)):
            assert push(pkg, "dev", fake, log=logs.append) == 0, logs
        assert "drift: ok (1 newer than the commit, dated before the folder or same as the working copy)" in logs, logs
        assert 'md5(s."MetaData")' in fake.calls[0][0][1] and '"IsChanged"' in fake.calls[0][0][1]
        fake.rows, logs = [dict(ours, isChanged="true")], []  # the same body, but a designer save since: not ours
        with patch("creatio_schemas.push._git", side_effect=fake_git(root)):
            assert push(pkg, "dev", fake, log=logs.append) == 1, logs
        fake.rows, logs = [dict(ours, content=md5(b"changed on the site"), isChanged="true")], []
        with patch("creatio_schemas.push._git", side_effect=fake_git(root)):
            assert push(pkg, "dev", fake, log=logs.append) == 1
        assert "drift: FAILED UsrOrderPage (changed on the site 2026-11-26 10:12 by Supervisor, IsChanged)" in logs, logs
        from datetime import datetime, timezone
        site_ms = int(datetime(2026, 11, 26, 10, 12, 33, tzinfo=timezone.utc).timestamp()) * 1000
        for ms, exit_code in ((site_ms, 0), (site_ms - 1000, 1)):  # downloaded from that state of the site, edited here: ours; a second older: foreign
            (page / "descriptor.json").write_bytes(b'{"Descriptor": {"ModifiedOnUtc": "\\/Date(%d)\\/"}}\r\n' % ms)
            fake.rows, logs = [dict(ours, content=md5(b"changed on the site"), isChanged="true")], []
            with patch("creatio_schemas.push._git", side_effect=fake_git(root)):
                assert push(pkg, "dev", fake, log=logs.append) == exit_code, (ms, logs)


def test_stale_bin_tolerates_one_checkout_and_a_clean_git_and_build_names_foreign_errors():
    from creatio_schemas.push import build_dll, stale_bin
    with tempfile.TemporaryDirectory() as tmp:
        pkg = _assembly(Path(tmp))
        cs, dll = pkg / "Files" / "cs", pkg / "Files" / "Bin" / "UsrPkg.dll"
        cs.mkdir(parents=True)
        dll.parent.mkdir(parents=True)
        (cs / "UsrOrderHelper.cs").write_text("class UsrOrderHelper { }", encoding="utf-8")
        dll.write_bytes(b"MZ")
        now = time.time()
        os.utime(dll, (now - 600, now - 600))
        for f in (cs, cs / "UsrOrderHelper.cs"):
            os.utime(f, (now - 599.96, now - 599.96))  # D61: one checkout, 40 ms apart
        assert stale_bin(pkg, "UsrPkg") is None
        os.utime(cs / "UsrOrderHelper.cs", (now, now))
        assert stale_bin(pkg, "UsrPkg") is not None
        logs = []  # git says Files/cs is as committed: the committed dll is current
        with patch("creatio_schemas.push._git", side_effect=lambda p, a, allow_not_repo=False: "" if a[0] == "status" else None):
            assert push(pkg, "dev", FakeClio(), log=logs.append, skip_drift=True, skip_sql_dates=True, skip_compile_package=True) == 0
        assert "stale bin: ok (Files/cs as committed: the committed dll is its build)" in logs, logs
        (pkg / "Files" / "UsrPkg.csproj").write_text("<Project />", encoding="utf-8")
        foreign = subprocess.CompletedProcess([], 1, r"C:\ws\packages\UsrOther\Files\cs\UsrX.cs(3,1): error CS0246: no UsrY" "\n", "")
        with patch("creatio_schemas.push.shutil.which", return_value="dotnet"):
            try:  # D97: the local build fails on another package's file
                build_dll(pkg, "UsrPkg", Path(tmp), "8.3.2.4199", detail=lambda l: None, run=lambda *a, **k: foreign)
                raise AssertionError("a failed build passed")
            except RuntimeError as exc:
                assert str(exc).endswith("all 1 foreign (not in UsrPkg's own files): --skip-stale-bin is right then, the server build decides"), exc
            own = subprocess.CompletedProcess([], 1, f"{cs / 'UsrOrderHelper.cs'}(3,1): error CS0246: no UsrY\n", "")
            try:
                build_dll(pkg, "UsrPkg", Path(tmp), "8.3.2.4199", detail=lambda l: None, run=lambda *a, **k: own)
                raise AssertionError("a failed build passed")
            except RuntimeError as exc:
                assert "foreign" not in str(exc), exc


def test_a_wrong_task_name_lists_the_task_folders():
    from creatio_schemas.push import _task_conflicts
    with tempfile.TemporaryDirectory() as tmp:
        tasks = Path(tmp) / "tasks"
        (tasks / "001-usr-order").mkdir(parents=True)
        (tasks / "002-usr-shipment").mkdir()
        try:
            _task_conflicts(tasks, tasks / "001", [])
            raise AssertionError("a wrong name passed")
        except RuntimeError as exc:  # E13: a bare name that is no folder there
            assert str(exc).endswith("no '001' there; pass one of: 001-usr-order, 002-usr-shipment"), exc
        assert _task_conflicts(tasks, tasks / "001-usr-order", []) == []


class SiteWithLayer(FakeClio):
    """The package's site rows hold `UsrGone` (an object layer a merge removed); `refs` is the count one key holds."""

    def __init__(self, refs=0, ref="SysEntitySchemaReference.SysSchemaId", **kw):
        super().__init__(**kw)
        self.refs, self.ref = refs, ref
        self.site_schemas = [{"Schema": "UsrProcess"}, {"Schema": "UsrGone"}]

    def execute_sql_rows(self, sql):
        self.calls.append((["sql-rows", sql], None))
        if '"ManagerName" from "SysSchema"' in sql:
            return [{"ManagerName": "EntitySchemaManager"}]
        if 's."Id"::text "id"' in sql:
            return [{"id": "5d2a1c3e-0000-4000-8000-000000000001", "package": "UsrPkg"}]
        if "information_schema" in sql:
            return [{"table": "SysEntitySchemaReference", "column": "SysSchemaId"}]
        if "union all" in sql or '"ref"' in sql:
            return [{"ref": self.ref, "id": "5d2a1c3e-0000-4000-8000-000000000001", "n": str(self.refs)}]
        return super().execute_sql_rows(sql)


def test_allow_removed_lets_a_merged_away_schema_go_only_when_absent_and_unreferenced():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        add_process(pkg)
        quiet = dict(skip_drift=True, skip_sql_dates=True)
        with patch("creatio_schemas.push._git", return_value=None):
            logs = []  # no flag: the stop as before
            assert push(pkg, "dev", SiteWithLayer(), log=logs.append, **quiet) == 1
            assert "package schemas: FAILED package install deletes schemas absent from the package: UsrGone" in logs
            logs = []  # the flag on a schema the folder still has: refused before the site is asked
            fake = SiteWithLayer()
            assert push(pkg, "dev", fake, log=logs.append, allow_removed=["UsrProcess"], **quiet) == 1
            assert "package schemas: FAILED --allow-removed names a schema still in the package folder: UsrProcess" in logs
            assert not any(a[0] == "push-pkg" for a, _ in fake.calls)
            logs = []  # still referenced on the site: refused with the count
            fake = SiteWithLayer(refs=3)
            assert push(pkg, "dev", fake, log=logs.append, allow_removed=["UsrGone"], **quiet) == 1
            assert "package schemas: FAILED UsrGone is still referenced: SysEntitySchemaReference.SysSchemaId 3 rows" in logs, logs
            assert not any(a[0] == "push-pkg" for a, _ in fake.calls)
            logs = []  # absent and unreferenced: pushed, the answer names it
            fake = SiteWithLayer(refs=0)
            assert push(pkg, "dev", fake, log=logs.append, allow_removed=[" UsrGone", ""], **quiet) == 0
            assert "package schemas: ok; removal allowed: UsrGone" in logs, logs
            logs = []  # D100: the schema's own strings are not a reference to it
            assert push(pkg, "dev", SiteWithLayer(refs=31, ref="SysLocalizableValue.SysSchemaId"), log=logs.append,
                        allow_removed=["UsrGone"], **quiet) == 0, logs
            assert any(a[0] == "push-pkg" for a, _ in fake.calls)


def test_a_failed_compile_says_whose_errors_they_are():
    from creatio_schemas.push import errors_by_package
    log = ("UsrProbeService.UsrOther.cs(15,3): Error CS0246 : The type or namespace name 'X' could not be found\n"
           "UsrProbeService.UsrOther.cs(15,3): Error CS0246 : The type or namespace name 'XAttribute' could not be found\n"
           r"C:\site\Terrasoft.Configuration\Pkg\UsrThird\Files\cs\A.cs(3,1): error CS1002: ; expected" "\n"
           "------- Finished building project: Succeeded: False. Errors: 3. Warnings: 0.\n")
    groups = errors_by_package(log)
    assert list(groups) == ["UsrOther", "UsrThird"] and len(groups["UsrOther"]) == 2
    assert errors_by_package("Finished building project: Succeeded: True. Errors: 0.") == {}
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        fake, logs = FakeClio(summary=log), []
        with patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", fake, log=logs.append, skip_drift=True, skip_sql_dates=True) == 1
        assert "compilation log: FAILED compile FAILED: 2 error(s) in UsrOther, 1 error(s) in UsrThird (none in UsrPkg)" in logs, logs
        assert "  UsrProbeService.UsrOther.cs(15,3): Error CS0246 : The type or namespace name 'X' could not be found" in logs



class PageClio:
    """get-page and update-page answers as clio prints them (`[INF] - {json}`); records each call."""

    def __init__(self, update=None, leaf="UsrPkg", checksum="cs-1", fail=None, design=""):
        self.calls, self.leaf, self.checksum, self.update, self.fail, self.design = [], leaf, checksum, update, fail, design

    def run(self, args, cwd=None):
        self.calls.append((args, cwd))
        if args[0] == "get-page":
            return "[INF] - " + json.dumps({"success": True, "page": {"currentLeafPackageName": self.leaf, "designPackageUId": self.design},
                                            "editable": {"checksum": self.checksum}})
        if self.fail:
            raise RuntimeError("clio exited 1: [INF] - " + json.dumps(self.fail))
        return "[INF] - " + json.dumps(self.update or {"success": True, "newChecksum": "cs-2", "warnings": ["resources unchanged"]})


def _page_package(root):
    pkg = package(root)
    folder = pkg / "Schemas" / "UsrOrder_FormPage"
    folder.mkdir(parents=True)
    (folder / "UsrOrder_FormPage.js").write_text('define("UsrOrder_FormPage", [], function() { return { viewConfigDiff: '
                                                  '/**SCHEMA_VIEW_CONFIG_DIFF*/[]/**SCHEMA_VIEW_CONFIG_DIFF*/ }; });\n', encoding="utf-8")
    return pkg


def test_push_page_sends_update_page_into_the_package_then_verifies():
    from creatio_schemas.push_page import push_page
    with tempfile.TemporaryDirectory() as tmp:
        pkg = _page_package(Path(tmp))
        clio, verified = PageClio(), []
        lines, code = push_page(pkg, "UsrOrder_FormPage", "dev", clio, lambda p, names: verified.append(names) or [("UsrOrder_FormPage", "same")])
        assert code == 0 and lines == ["update-page: saved (UsrPkg, replace, checksum cs-2)", "  warning: resources unchanged",
                                       "verify: UsrOrder_FormPage same"], lines
        get, update = clio.calls[0], clio.calls[1][0]
        assert get[0][:3] == ["get-page", "--schema-name", "UsrOrder_FormPage"] and get[1] is not None  # a scratch folder for .clio-pages
        assert update[:2] == ["update-page", "--schema-name"] and "--mode" in update and update[update.index("--mode") + 1] == "replace"
        assert update[update.index("--target-package-uid") + 1] == "00000000-0000-0000-0000-000000000001"
        assert update[update.index("--expected-checksum") + 1] == "cs-1" and "--dry-run" not in update and verified == [["UsrOrder_FormPage"]]
        # a dry run: update-page --dry-run, no verify
        clio, verified = PageClio(), []
        lines, code = push_page(pkg, "UsrOrder_FormPage", "dev", clio, lambda p, n: verified.append(n) or [], dry_run=True)
        assert code == 0 and lines[0].startswith("update-page: dry run ok") and "--dry-run" in clio.calls[1][0] and verified == []
        # the site's top copy in another package: said; a verify difference: exit 1
        lines, code = push_page(pkg, "UsrOrder_FormPage", "dev", PageClio(leaf="UsrOther"), lambda p, n: [("UsrOrder_FormPage", "differs: body")])
        assert code == 1 and lines[0].startswith("note: the site's top copy of UsrOrder_FormPage is in UsrOther") and lines[-1] == "verify: UsrOrder_FormPage differs: body"
        # a conflict (the site changed since get-page): refused, nothing verified; --force sends no checksum
        clio = PageClio(fail={"success": False, "conflict": True, "error": "modified outside this session"})
        lines, code = push_page(pkg, "UsrOrder_FormPage", "dev", clio, lambda p, n: 1 / 0)
        assert code == 1 and lines[-1].startswith("update-page: FAILED conflict"), lines
        clio = PageClio(fail={"success": False, "error": 'Unable to save changes for item "UsrOrder_FormPage". It is either created by '
                                                      'third-party publisher or installed from the file archive'})
        lines, code = push_page(pkg, "UsrOrder_FormPage", "dev", clio, lambda p, n: 1 / 0)
        assert code == 1 and "the site does not let the designer edit UsrPkg" in lines[-1] and "push.py UsrPkg -e dev" in lines[-1], lines
        clio = PageClio()
        push_page(pkg, "UsrOrder_FormPage", "dev", clio, lambda p, n: [("UsrOrder_FormPage", "same")], force=True)
        assert "--force" in clio.calls[1][0] and "--expected-checksum" not in clio.calls[1][0]
        # the package is not the page's default design package: clio refuses a replace there without --force, and the
        # working copy is that package's own layer - saved with --force, said (seen on the test site, S44-T03)
        clio = PageClio(design="5D2A1C3E-0000-4000-8000-000000000009")
        lines, code = push_page(pkg, "UsrOrder_FormPage", "dev", clio, lambda p, n: [("UsrOrder_FormPage", "same")])
        assert code == 0 and lines[0].startswith("note: UsrPkg is not the page's default design package"), lines
        assert "--force" in clio.calls[1][0] and "--expected-checksum" not in clio.calls[1][0]
        clio = PageClio(design="00000000-0000-0000-0000-000000000001")  # the package itself (case-blind): the checksum, no force
        push_page(pkg, "UsrOrder_FormPage", "dev", clio, lambda p, n: [("UsrOrder_FormPage", "same")])
        assert "--force" not in clio.calls[1][0] and clio.calls[1][0][clio.calls[1][0].index("--expected-checksum") + 1] == "cs-1"
        # not a page of this package, not a Freedom page
        for name, kind in (("UsrNope", FileNotFoundError), ("UsrClassic", ValueError)):
            if name == "UsrClassic":
                (pkg / "Schemas" / name).mkdir()
                (pkg / "Schemas" / name / f"{name}.js").write_text('define("UsrClassic", [], function() { return { diff: [] }; });', encoding="utf-8")
            try:
                push_page(pkg, name, "dev", PageClio(), lambda p, n: [])
                assert False, name
            except kind:
                pass



def test_a_stale_bin_dll_stops_an_assembly_package():
    """S44-T06: Files/Bin/<Pkg>.dll older than Files/cs (an edit, or a source deleted: the folder's time) stops the push;
    --skip-stale-bin passes and says so; no Files/cs or not an assembly package is n/a; a fresh dll is ok."""
    from creatio_schemas.push import stale_bin
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        (pkg / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": "UsrPkg", "UId": "00000000-0000-0000-0000-000000000001",
                                                                       "Type": 1}}), encoding="utf-8")
        assert stale_bin(pkg, "UsrPkg") is None  # no Files/cs at all
        cs = pkg / "Files" / "cs"
        cs.mkdir(parents=True)
        (cs / "UsrOrderHelper.cs").write_text("class UsrOrderHelper { }", encoding="utf-8")
        assert stale_bin(pkg, "UsrPkg") == "Files/Bin/UsrPkg.dll is missing while Files/cs holds sources"
        dll = pkg / "Files" / "Bin" / "UsrPkg.dll"
        dll.parent.mkdir(parents=True)
        dll.write_bytes(b"MZ")
        now = time.time()
        for f in (cs, cs / "UsrOrderHelper.cs"):
            os.utime(f, (now - 600, now - 600))
        os.utime(dll, (now - 300, now - 300))
        assert stale_bin(pkg, "UsrPkg") is None  # built after the last edit
        os.utime(cs / "UsrOrderHelper.cs", (now, now))
        assert stale_bin(pkg, "UsrPkg") == "Files/Bin/UsrPkg.dll is older than Files/cs (Files/cs/UsrOrderHelper.cs, 5 min newer)"
        os.utime(cs / "UsrOrderHelper.cs", (now - 600, now - 600))
        os.utime(cs, (now, now))  # a source deleted after the build: only the folder's time moves
        assert stale_bin(pkg, "UsrPkg").startswith("Files/Bin/UsrPkg.dll is older than Files/cs (Files/cs/ (a file deleted or added there)")
        logs = []
        with patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", FakeClio(), log=logs.append, skip_drift=True, skip_sql_dates=True) == 1
            assert any(l.startswith("stale bin: FAILED Files/Bin/UsrPkg.dll is older than Files/cs") and "--skip-stale-bin" in l for l in logs), logs
            logs = []
            fake = FakeClio()
            push(pkg, "dev", fake, log=logs.append, skip_drift=True, skip_sql_dates=True, skip_stale_bin=True, skip_compile_package=True)
            assert any(l.startswith("stale bin: skipped (--skip-stale-bin): Files/Bin/UsrPkg.dll is older") for l in logs), logs
            assert any(a[0] == "push-pkg" for a, _ in fake.calls)
        os.utime(dll, (now + 60, now + 60))
        assert stale_bin(pkg, "UsrPkg") is None
        logs = []
        with patch("creatio_schemas.push._git", return_value=None):
            (Path(tmp) / "plain").mkdir()
            push(package(Path(tmp) / "plain"), "dev", FakeClio(), log=logs.append, skip_drift=True, skip_sql_dates=True)
        assert "stale bin: n/a (not an assembly package)" in logs, logs


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
        assert "publish: pushed schemas among the failed: UsrProcess" in logs and logs[-1].startswith("push FAILED at publish; the package is on the site")


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
        # --project: paths.platformBin is the bin of the compile when there is no --bin
        (Path(tmp) / "project.json").write_text(json.dumps({"paths": {"platformBin": "site-bin"}}), encoding="utf-8")
        bins = []
        with patch.object(verify_module, "compile_script", lambda text, name, bin_dir, extra=(): bins.append(bin_dir) or ("ok", [])):
            verify(pkg, Site(fresh), ["UsrProcess"], project=Path(tmp) / "project.json")
            with patch("creatio_schemas.environment.open_environment", lambda name, project=None: Site(fresh)):
                assert cli.main(["verify", str(pkg), "-e", "dev", "UsrProcess", "--project", str(Path(tmp) / "project.json")]) == 0
        assert bins == [(Path(tmp) / "site-bin").resolve()] * 2, bins


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


def test_served_checks_the_layers_own_members_in_a_composed_body():
    """S48-T05: a composed body never holds a middle layer's whole text - its members (Freedom: operations, handler requests; Classic:
    diff inserts, methods, rule UIds) are looked for; a missing one is named; the `served` command saves and greps."""
    import hashlib
    import io
    import contextlib
    from creatio_schemas import verify as verify_module
    from creatio_schemas.verify import _served_status, members

    freedom = ('define("UsrP", [], function() { return { viewConfigDiff: /**SCHEMA_VIEW_CONFIG_DIFF*/[{"operation": "insert", "name": "UsrField", '
               '"values": {"type": "x"}, "parentName": "Main", "propertyName": "items", "index": 0}, {"operation": "remove", "name": "OldField"}]'
               '/**SCHEMA_VIEW_CONFIG_DIFF*/, handlers: /**SCHEMA_HANDLERS*/[{ request: "usr.Open", handler: async (r, next) => next?.handle(r) }]'
               '/**SCHEMA_HANDLERS*/ }; });')
    assert members(freedom, "UsrP") == ["UsrField", "usr.Open"]
    classic = ("define('UsrC', [], function() { return { diff: /**SCHEMA_DIFF*/[{operation: 'insert', name: 'UsrTerms', parentName: 'Header', "
               "propertyName: 'items', values: {}}]/**SCHEMA_DIFF*/, methods: { onUsrClick: function() { return 1; } }, "
               "rules: {UsrA: {UsrRule1: {uId: 'u-1', ruleType: 1}}} }; });")
    assert members(classic, "UsrC") == ["UsrTerms", "onUsrClick", "u-1"], members(classic, "UsrC")
    composed = "other layers...\n" + "".join(f'"{n}"\n' for n in ("UsrTerms", "onUsrClick", "u-1")) + "...more"
    assert _served_status("same", classic, "UsrC", composed) == "same, served (3 of 3 members)"
    assert _served_status("same", classic, "UsrC", composed.replace("onUsrClick", "x").replace("u-1", "y")) == \
        "not served: 2 of 3 members missing (onUsrClick, u-1)"
    assert _served_status("same", classic, "UsrC", None) == "not served: conf/content has no such file"
    bare = "define('UsrM', [], function() { return {}; });"  # no members: the whole text, as before
    assert _served_status("same", bare, "UsrM", 'define("UsrM", [], function() { return {}; });') == "same"
    assert _served_status("same", bare, "UsrM", "other").startswith("not served: conf/content holds another body")
    # the command: size, md5, saved text, matching lines; a missing file is exit 1
    sys.path.insert(0, str(HERE.parent))
    import push as cli
    text = "a\nb HandlerChain\nc\n"
    with tempfile.TemporaryDirectory() as tmp, patch("creatio_schemas.environment.open_environment", lambda name, project=None: object()), \
            patch.object(verify_module, "served", lambda env, name: None if name == "UsrGone" else text):
        out, saved = io.StringIO(), Path(tmp) / "s.js"
        with contextlib.redirect_stdout(out):
            code = cli.main(["served", "UsrP", "-e", "dev", "--out", str(saved), "--grep", "handlerchain"])
        assert code == 0 and "2: b HandlerChain" in out.getvalue() and hashlib.md5(text.encode()).hexdigest() in out.getvalue()
        assert saved.read_text(encoding="utf-8") == text
        with contextlib.redirect_stdout(io.StringIO()):
            assert cli.main(["served", "UsrGone", "-e", "dev"]) == 1


def test_resolve_task_meets_the_projects_tasks_folder():
    """A bare task name from an MCP call goes under the project's paths.tasks, not the server's cwd; an existing or absolute path stays."""
    import json
    from creatio_schemas.push import resolve_task
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "tasks" / "001-labels").mkdir(parents=True)
        (root / "project.json").write_text(json.dumps({"paths": {"tasks": "tasks"}}), encoding="utf-8")
        assert resolve_task("001-labels", None, root / "project.json") == root / "tasks" / "001-labels"
        assert resolve_task("001-labels", root / "tasks", None) == root / "tasks" / "001-labels"
        assert resolve_task(root / "elsewhere", root / "tasks", None) == root / "elsewhere"
        assert resolve_task("tasks/UsrTask", Path("tasks"), None) == Path("tasks") / "UsrTask"  # a path with the folder in it keeps its name only
        assert resolve_task("002-new", None, None) == Path("002-new") and resolve_task(None, None, None) is None
        (root / "project.json").write_text("{}", encoding="utf-8")
        assert resolve_task("003", None, root / "project.json") == Path("003")  # no paths.tasks: as given


def test_without_git_foreign_files_is_skipped_and_a_cs_in_a_plain_package_warns():
    """S46-T08 items 2 and 6: no git -> `skipped (no git; ...)` and the push goes on; Files/cs in a non-assembly package -> WARN."""
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        tasks = Path(tmp) / "tasks"
        (tasks / "001-a").mkdir(parents=True)
        (pkg / "Files" / "cs").mkdir(parents=True)
        (pkg / "Files" / "cs" / "UsrHelper.cs").write_text("class UsrHelper { }", encoding="utf-8")
        logs = []
        with patch("creatio_schemas.push._git", return_value=None):
            code = push(pkg, "dev", FakeClio(), log=logs.append, skip_drift=True, skip_sql_dates=True, tasks=tasks, task=tasks / "001-a")
        assert code == 0 and "foreign files: skipped (no git; schema_impact is the lock between tasks)" in logs, logs
        assert "stale bin: WARN Files/cs is never compiled - not an assembly package (Type 1, ProjectPath)" in logs, logs


def test_deps_fills_empty_entries_and_adds_from_the_site():
    from creatio_schemas.push import fill_dependencies
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        base_uid, ui_uid = "00000000-0000-4000-8000-0000000000b1", "00000000-0000-4000-8000-0000000000b2"
        (pkg / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": "UsrPkg", "DependsOn": [
            {"UId": "", "PackageVersion": "", "Name": "Base"},
            {"UId": ui_uid, "PackageVersion": "7.8.0", "Name": "Done"}]}}, indent=2), encoding="utf-8")
        queries = []
        rows = lambda sql: queries.append(sql) or [{"Name": "Base", "UId": base_uid, "Version": "7.8.0"},
                                                    {"Name": "UsrUi", "UId": ui_uid, "Version": "7.9.1"}]
        lines, found = fill_dependencies(pkg, rows, ["UsrUi", "Gone"], dry_run=True)
        assert len(queries) == 1 and "'Done'" not in queries[0] and "'Gone'" in queries[0]
        assert not found and json.loads((pkg / "descriptor.json").read_text())["Descriptor"]["DependsOn"][0]["UId"] == ""  # dry run
        assert [l.split(":")[0] for l in lines] == ["filled Base", "unchanged Done", "added UsrUi", "not on the site Gone"], lines
        lines, found = fill_dependencies(pkg, rows, ["UsrUi"])
        deps = json.loads((pkg / "descriptor.json").read_text())["Descriptor"]["DependsOn"]
        assert found and deps[0] == {"UId": base_uid, "PackageVersion": "7.8.0", "Name": "Base"}
        assert deps[2] == {"UId": ui_uid, "PackageVersion": "7.9.1", "Name": "UsrUi"} and len(deps) == 3
        assert fill_dependencies(pkg, rows)[0] == ["unchanged Base", "unchanged Done", "unchanged UsrUi"] and len(queries) == 3 - 1  # nothing to ask


def test_an_empty_dependency_entry_stops_the_push_and_no_git_says_so():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        desc = json.loads((pkg / "descriptor.json").read_text())
        desc["Descriptor"]["DependsOn"] = [{"UId": "", "PackageVersion": "", "Name": "Base"}]
        (pkg / "descriptor.json").write_text(json.dumps(desc), encoding="utf-8")
        fake, logs = FakeClio(), []
        with patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", fake, log=logs.append, skip_drift=True) == 1
        assert "dependencies: FAILED Base has no UId/version - run push.py deps UsrPkg -e dev" in logs
        assert not any(args[0] == "push-pkg" for args, _ in fake.calls)
        desc["Descriptor"]["DependsOn"][0].update(UId="00000000-0000-4000-8000-0000000000b1", PackageVersion="7.8.0")
        (pkg / "descriptor.json").write_text(json.dumps(desc), encoding="utf-8")
        logs.clear()
        with patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", FakeClio(), log=logs.append, skip_drift=True, skip_sql_dates=True) == 0
        assert "dependencies: ok (no git: not compared)" in logs, logs
        desc["Descriptor"]["DependsOn"][0]["PackageVersion"] = ""  # S45-T09: the site's package has no version, `deps` filled it so
        (pkg / "descriptor.json").write_text(json.dumps(desc), encoding="utf-8")
        logs.clear()
        with patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", FakeClio(), log=logs.append, skip_drift=True, skip_sql_dates=True) == 0, logs


def test_a_bare_task_name_resolves_under_tasks_even_when_the_cwd_holds_that_folder():
    """S46-T08 item 3: the push log must not land beside the workspaces because a folder of that name exists here."""
    from creatio_schemas.push import details_path, resolve_task
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "011-shipments").mkdir()
        (root / "tasks").mkdir()
        old = Path.cwd()
        os.chdir(root)
        try:
            task = resolve_task("011-shipments", root / "tasks")
            assert task == root / "tasks" / "011-shipments" and details_path(root, task).parent == task
        finally:
            os.chdir(old)


def test_the_cli_push_writes_the_whole_clio_failure_to_the_details_file():
    """S46-T08 item 5: the screen keeps the 200-character cut, the details file the whole clio output; the CLI asks for the file."""
    long = "clio exited 1: " + "bad metadata " * 60 + "THE-END"

    class Failing(FakeClio):
        def run(self, args, cwd=None):
            if args[0] == "push-pkg":
                raise RuntimeError(long)
            return super().run(args, cwd)

    with tempfile.TemporaryDirectory() as tmp:
        pkg, logs, details = package(Path(tmp)), [], Path(tmp) / "task" / "push.log"
        with patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", Failing(), log=logs.append, skip_drift=True, skip_sql_dates=True, details=details) == 1
        assert not any("THE-END" in line for line in logs) and "THE-END" in details.read_text(encoding="utf-8")
        sys.path.insert(0, str(HERE.parent))
        import push as cli
        seen = {}
        with patch.object(cli, "push", lambda *a, **k: seen.update(k) or 0), patch.object(cli, "Clio", lambda env: None):
            assert cli.main([str(pkg), "-e", "dev"]) == 0
        assert seen["details"].name.startswith("push-UsrPkg-"), seen


def _fake_bin(folder: Path, version: str) -> Path:
    folder.mkdir(parents=True)
    (folder / "Terrasoft.Core.dll").write_bytes(b"MZ..." + "FileVersion\0".encode("utf-16-le") + f"{version}\0".encode("utf-16-le"))
    return folder


def test_build_finds_the_site_version_binaries_or_stops_naming_both_places():
    """S46-T09: --bin, else paths.platformBin; the bin's Terrasoft.Core.dll version must start with environment.platformVersion."""
    from creatio_schemas.push import site_bin
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project.json"
        project.write_text(json.dumps({"environment": {"platformVersion": "8.2.3"}}), encoding="utf-8")
        for given, where in ((None, None), (None, project)):
            try:
                site_bin(given, where)
                raise AssertionError("no stop")
            except RuntimeError as exc:
                assert "--bin" in str(exc) and "paths.platformBin" in str(exc), exc
        old, new = _fake_bin(root / "b823", "8.2.3.1351"), _fake_bin(root / "b832", "8.3.2.4199")
        assert site_bin(old, project) == (old, "8.2.3.1351")
        project.write_text(json.dumps({"environment": {"platformVersion": "8.2.3"}, "paths": {"platformBin": "b823"}}), encoding="utf-8")
        assert site_bin(None, project) == (old, "8.2.3.1351")  # relative to project.json
        try:
            site_bin(new, project)
            raise AssertionError("a wrong version passed")
        except RuntimeError as exc:
            assert "is 8.3.2.4199, the site is 8.2.3" in str(exc), exc
        assert site_bin(new) == (new, "8.3.2.4199")  # no project: nothing to match


def test_build_runs_dotnet_with_the_site_bin_and_summarises_msb3245():
    from creatio_schemas.push import build_dll
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        try:
            build_dll(pkg, "UsrPkg", Path(tmp) / "bin", "8.2.3.1351", run=None)
            raise AssertionError("no csproj passed")
        except RuntimeError as exc:
            assert "Files/UsrPkg.csproj is missing" in str(exc) and "tests-init" in str(exc)
        (pkg / "Files").mkdir()
        (pkg / "Files" / "UsrPkg.csproj").write_text("<Project />", encoding="utf-8")
        calls, details = [], []
        warn = ('x.targets(2453,5): warning MSB3245: Could not resolve this reference. Could not locate the assembly "{0}". Check [UsrPkg.csproj]\n')

        def dotnet(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, (warn.format("ErrorOr") + warn.format("ATF.Repository")) * 2, "")
        with patch("creatio_schemas.push.shutil.which", return_value="dotnet"):
            line = build_dll(pkg, "UsrPkg", Path(tmp) / "bin", "8.2.3.1351", detail=details.append, run=dotnet)
        assert line == f"built against 8.2.3.1351 ({Path(tmp) / 'bin'}); 2 MSB3245 (unresolved: ATF.Repository, ErrorOr)", line
        args = calls[0]
        assert args[:5] == ["dotnet", "build", str(pkg / "Files" / "UsrPkg.csproj"), "-c", "Release"], args
        assert "-p:CoreTargetFramework=net472" in args and f"-p:CoreLibPath={Path(tmp) / 'bin'}" in args and "-p:DebugType=none" in args and "-p:DefaultItemExcludes=obj/**" in args
        assert any(a.startswith("-p:BaseIntermediateOutputPath=") and "creatio-build/UsrPkg/obj/" in a for a in args), args
        assert len(details) == 4

        def broken(args, **kwargs):
            return subprocess.CompletedProcess(args, 1, "a.cs(3,1): error CS0246: The type 'UsrX' could not be found\n" * 2, "")
        with patch("creatio_schemas.push.shutil.which", return_value="dotnet"):
            try:
                build_dll(pkg, "UsrPkg", Path(tmp) / "bin", "8.2.3.1351", detail=details.append, run=broken)
                raise AssertionError("a failed build passed")
            except RuntimeError as exc:
                assert str(exc).startswith("dotnet build exit 1: a.cs(3,1): error CS0246") and "more" not in str(exc), exc
        logs = []
        assert build_dll(pkg, "UsrPkg", Path(tmp) / "bin", "8.2.3.1351", dry_run=True, log=logs.append, run=None) == "dry run"
        assert logs[0].startswith("  dotnet build ")


def test_push_build_stops_before_the_install_without_binaries_and_builds_first_with_them():
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        (pkg / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": "UsrPkg", "UId": "00000000-0000-0000-0000-000000000001",
                                                                       "Type": 1}}), encoding="utf-8")
        logs, fake = [], FakeClio()
        with patch("creatio_schemas.push._git", return_value=None):
            assert push(pkg, "dev", fake, log=logs.append, skip_drift=True, skip_sql_dates=True, build=True) == 1
        assert any(l.startswith("build: FAILED no binaries for the site's version") for l in logs) and "push FAILED at build" in logs, logs
        assert not any(a[0] == "push-pkg" for a, _ in fake.calls)
        bin_dir = _fake_bin(Path(tmp) / "bin", "8.2.3.1351")
        project = Path(tmp) / "project.json"  # a tasks folder and no --task: without git the ownership check skips, not stops
        project.write_text(json.dumps({"environment": {"platformVersion": "8.2.3"}, "paths": {"tasks": "tasks", "platformBin": "bin"}}),
                           encoding="utf-8")
        logs, order = [], []
        with patch("creatio_schemas.push._git", return_value=None), \
             patch("creatio_schemas.push.build_dll", side_effect=lambda *a, **k: order.append(a[2]) or "built against 8.2.3.1351 (x)"):
            push(pkg, "dev", FakeClio(), log=logs.append, skip_drift=True, skip_sql_dates=True, build=True, project=project,
                 skip_compile_package=True)
        steps = [l.split(":")[0] for l in logs if not l.startswith(" ")]
        assert order == [bin_dir] and steps.index("build") < steps.index("stale bin") and "build: built against 8.2.3.1351 (x)" in logs, logs
        assert "foreign files: skipped (no git; schema_impact is the lock between tasks)" in logs, logs


def test_verify_retries_the_site_sql_once_after_a_timeout():
    """S46-T08 item 7: a first Timeout is retried and said; any other error and a second timeout still raise."""
    from creatio_schemas.verify import verify

    class Site:
        def __init__(self, errors, rows=()):
            self.errors, self.rows, self.calls = errors, list(rows), 0

        def sql(self, text):
            self.calls += 1
            if self.errors:
                raise RuntimeError(self.errors.pop(0))
            return self.rows

    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        (pkg / "Schemas" / "UsrLf").mkdir(parents=True)
        (pkg / "Schemas" / "UsrLf" / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": "UsrLf"}}), encoding="utf-8")
        site = Site(["sql: request Timeout"])
        assert verify(pkg, site) == [("UsrLf", "not on the site")] and site.calls == 2
        rows = [{"name": "UsrLf", "manager": "EntitySchemaManager", "meta": "", "content": ""}]
        (pkg / "Schemas" / "UsrLf" / "metadata.json").write_bytes(b"")
        import hashlib
        rows[0]["meta"] = hashlib.md5(b"").hexdigest()
        site = Site(["Timeout"], rows)
        assert verify(pkg, site) == [("UsrLf", "same (sql retried once)")]
        for errors in (["boom"], ["Timeout", "Timeout"]):
            try:
                verify(pkg, Site(errors))
                raise AssertionError("no error")
            except RuntimeError:
                pass


def test_script_compile_references_every_managed_bin_dll_and_the_flag_wins_over_the_environment():
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("Terrasoft.Core.dll", "Newtonsoft.Json.dll", "UsrOther.dll", "e_sqlite3.dll", "Microsoft.Data.SqlClient.SNI.x64.dll"):
            (Path(tmp) / name).write_bytes(b"")
        seen = []

        def fake_run(args, **kwargs):
            seen.append(Path(args[-1][1:]).read_text(encoding="utf-8"))
            return subprocess.CompletedProcess([], 0, "", "")
        with patch.object(push_module, "_csc", return_value=Path("csc.dll")), patch.object(push_module.subprocess, "run", fake_run):
            assert compile_script(CLEAN, "UsrProcess", Path(tmp))[0] == "ok"
        refs = [l for l in seen[0].splitlines() if l.startswith("-r:") and Path(tmp).name in l]
        assert [Path(l[4:-1]).name for l in refs] == ["Newtonsoft.Json.dll", "Terrasoft.Core.dll", "UsrOther.dll"], refs
        (Path(tmp) / "project.json").write_text(json.dumps({"paths": {"platformBin": "C:/proj/bin"}}), encoding="utf-8")
        project = Path(tmp) / "project.json"
        assert creatio_bin(Path(tmp), None, project) == Path("C:/proj/bin") and creatio_bin(Path(tmp), "D:/flag/bin", project) == Path("D:/flag/bin")
        os.environ["CREATIO_BIN"] = "C:/env/bin"
        assert creatio_bin(Path(tmp), None, project) == Path("C:/proj/bin")
        try:
            assert creatio_bin(Path(tmp), "D:/flag/bin") == Path("D:/flag/bin") and creatio_bin(Path(tmp)) == Path("C:/env/bin")
        finally:
            os.environ.pop("CREATIO_BIN", None)


def test_a_failure_after_push_pkg_says_the_package_is_on_the_site():
    def fail(source, name, bin_dir, extra=()):
        return "failed", ["CS0234: no Linq"]
    with tempfile.TemporaryDirectory() as tmp:
        pkg = package(Path(tmp))
        add_process(pkg)
        with patch.object(push_module, "compile_script", fail):
            logs = []
            assert push(pkg, "dev", FakeClio(), log=logs.append, bin_dir=Path("C:/bin")) == 1
            assert logs[-1] == ("push FAILED at script compile; the package is on the site (push-pkg ok): "
                                "run clio compile-configuration -e dev and push.py verify UsrPkg")
        logs = []
        assert push(pkg, "dev", FakeClio(summary="Done. Errors: 1\nfoo.cs(1,1): error CS0103: x"), log=logs.append) == 1
        assert logs[-1].startswith("push FAILED at") and logs[-1].endswith(": run the push again"), logs[-1]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
