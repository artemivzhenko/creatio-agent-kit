"""Checks project synchronization and setup without real credentials or registration."""

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


project = load("project_tools", ROOT / "no-code" / "tools" / "project.py")
setup = load("agent_setup", ROOT.parent / "agent_setup.py")  # the kit root, above creatio-knowledge-base


def test_sync_example_and_preserves_unmanaged_settings():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "project.json"
        shutil.copyfile(ROOT / "skill" / "creatio-loop" / "templates" / "project.example.json", source)
        config_dir = root / "framework" / "Configuration"
        config_dir.mkdir(parents=True)
        target = config_dir / "creatio.env.config.json"
        target.write_text('{"BaseUrl":"old", // keep settings\n "CasesFolders":["custom",], "AnalysisFolders":["analysis"],}', encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert project.main(["sync", str(source), "--framework", str(config_dir.parent)]) == 0
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["BaseUrl"] == "https://dev.example.com"
        assert data["Users"] == [{"Username": "Supervisor", "Password": "change-me"}]
        assert data["CasesFolders"] == ["custom"] and data["AnalysisFolders"] == ["analysis"]
        assert "change-me" not in out.getvalue() and "Users" in out.getvalue()
        assert project.sync(source, config_dir.parent) == []


def test_new_config_and_missing_environment():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "framework" / "Configuration").mkdir(parents=True)
        source = root / "project.json"
        source.write_text(json.dumps({"environment": {"url": "https://example.test", "login": "x", "password": "y"},
                                      "paths": {"testFramework": "framework"}}), encoding="utf-8")
        assert project.sync(source) == ["BaseUrl", "Users", "CasesFolders", "AllowDevOnly"]
        target = root / "framework" / "Configuration" / "creatio.env.config.json"
        assert json.loads(target.read_text(encoding="utf-8"))["CasesFolders"] == ["./Cases"]
        before = target.read_bytes()
        source.write_text("{}", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            assert project.main(["sync", str(source)]) == 1
        assert target.read_bytes() == before


def test_sync_writes_the_dev_keys_both_ways_and_keeps_the_other_users():  # S49-T03
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "framework" / "Configuration").mkdir(parents=True)
        target = root / "framework" / "Configuration" / "creatio.env.config.json"
        target.write_text(json.dumps({"Users": [{"Username": "UsrTestOperator", "Password": "a"},
                                                {"Username": "supervisor", "Password": "old"}]}), encoding="utf-8")
        source = root / "project.json"
        env = {"url": "https://dev.example.com", "login": "Supervisor", "password": "p", "kind": "dev", "clioName": "dev"}
        source.write_text(json.dumps({"environment": env, "paths": {"testFramework": "framework"}}), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            assert project.main(["sync", "--project", str(source)]) == 0
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["Users"] == [{"Username": "Supervisor", "Password": "p"}, {"Username": "UsrTestOperator", "Password": "a"}]
        assert data["AllowDevOnly"] is True and data["ClioEnvironment"] == "dev"
        source.write_text(json.dumps({"environment": {**env, "kind": "client", "clioName": ""},
                                      "paths": {"testFramework": "framework"}}), encoding="utf-8")
        assert project.sync(source) == ["AllowDevOnly", "ClioEnvironment"]
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["AllowDevOnly"] is False and "ClioEnvironment" not in data and len(data["Users"]) == 2
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                project.main(["sync", str(source), "--project", str(source)])
                raise AssertionError("both forms accepted")
            except SystemExit as exc:
                assert exc.code == 2


def test_sync_writes_the_package_folders_of_the_tests_layout():  # S51-T01
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "framework" / "Configuration").mkdir(parents=True)
        target = root / "framework" / "Configuration" / "creatio.env.config.json"
        target.write_text(json.dumps({"CasesFolders": ["./Cases"], "AnalysisFolders": ["./Analysis"]}), encoding="utf-8")
        tests = root / "ws" / "tests"
        for folder in ("UsrOrder/e2e", "UsrOrder/integration", "UsrOrder/pages", "UsrShipment/integration"):
            (tests / folder).mkdir(parents=True)
        source = root / "project.json"
        source.write_text(json.dumps({"environment": {"url": "https://dev.example.com", "login": "Supervisor", "password": "p"},
                                      "package": {"name": "UsrOrder", "workspace": "ws"},
                                      "paths": {"testFramework": "framework"}}), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert project.main(["sync", "--project", str(source)]) == 0
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["CasesFolders"] == [str(tests / "UsrOrder" / "e2e")], data
        assert data["ProcessCasesFolders"] == [str(tests / "UsrOrder" / "integration"), str(tests / "UsrShipment" / "integration")]
        assert data["PagesFolders"] == [str(tests / "UsrOrder" / "pages")] and data["AnalysisFolders"] == ["./Analysis"]
        assert "skipped UsrShipment/e2e: no folder" in out.getvalue() and "skipped UsrShipment/pages: no folder" in out.getvalue()
        assert "Updated: " in out.getvalue() and "PagesFolders" in out.getvalue() and "ProcessCasesFolders" in out.getvalue()
        with contextlib.redirect_stdout(io.StringIO()):
            assert project.main(["sync", "--project", str(source), "--package", "UsrShipment"]) == 0
        data = json.loads(target.read_text(encoding="utf-8"))
        assert (data["CasesFolders"], data["PagesFolders"]) == ([], [])
        assert data["ProcessCasesFolders"] == [str(tests / "UsrShipment" / "integration")]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert project.main(["sync", "--project", str(source), "--package", "UsrNone"]) == 1
        assert "no tests folder" in err.getvalue()


def test_launcher_falls_back_to_py_and_check_is_read_only():
    def run(cmd, **kwargs):
        if cmd[0] == "python":
            return subprocess.CompletedProcess(cmd, 9009, "", "Install Python from the Microsoft Store")
        return subprocess.CompletedProcess(cmd, 0, "3.12.1\n", "")
    with patch.object(setup.subprocess, "run", side_effect=run), \
         patch.object(setup, "register", side_effect=AssertionError("check must not register")), \
         patch.object(setup, "ARGS", ["--check"]), \
         contextlib.redirect_stdout(io.StringIO()) as out:
        setup.main()
    assert "Selected Python launcher: py -3" in out.getvalue()
    assert "Servers: creatio-kb, creatio-tests" in out.getvalue() and "Skills: " in out.getvalue()


def test_the_launcher_order_is_py_3_on_windows_and_python3_elsewhere():  # S33-T09
    tried = []

    def run(cmd, **kwargs):
        tried.append(cmd[0] if cmd[0] != "py" else "py -3")
        return subprocess.CompletedProcess(cmd, 0, "3.12.1\n", "")
    for win, first, chosen in ((True, "py -3", ["py", "-3"]), (False, "python3", ["python3"])):
        tried.clear()
        with patch.object(setup.subprocess, "run", side_effect=run), patch.object(setup, "WIN", win), contextlib.redirect_stdout(io.StringIO()):
            assert setup.python_launcher() == chosen and tried[0] == first, (win, tried)


def test_no_working_launcher_stops_before_registration():
    with patch.object(setup.subprocess, "run", side_effect=FileNotFoundError("missing")), \
         patch.object(setup, "register", side_effect=AssertionError("must not register")), \
         contextlib.redirect_stdout(io.StringIO()):
        try:
            setup.main()
        except SystemExit as exc:
            assert "works; install Python" in str(exc) and "python" in str(exc) and ("py -3" in str(exc) or "python3" in str(exc))
        else:
            raise AssertionError("a working launcher is required")


CSV = ("Issue key,Summary,Description,Status\n"
       "USR-1,First,Do the first,Open\n"
       "USR-2,Second,Was done,Done\n"
       "USR-3,Third,Also done,Closed\n"
       "USR-4,Fourth,Already here,Open\n"
       "USR/5,Fifth,A slash key,Open\n"
       "USR-6,Sixth,,Open\n")


def run_csv(root, *extra):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = project.main(["tasks-from-csv", str(root / "in.csv"), str(root / "tasks"), "--done", "Done,Closed", *extra])
    return code, out.getvalue().splitlines()


def test_tasks_from_csv_writes_keeps_skips_and_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "in.csv").write_text(CSV, encoding="utf-8-sig")
        (root / "tasks" / "USR-4").mkdir(parents=True)
        (root / "tasks" / "USR-4" / "task.md").write_text("mine", encoding="utf-8")
        code, lines = run_csv(root, "--dry-run")
        assert code == 0 and not (root / "tasks" / "USR-1").exists() and "would write USR-1" in lines
        code, lines = run_csv(root)
        assert lines == ["wrote USR-1", "skipped (done) USR-2", "skipped (done) USR-3", "kept USR-4", "wrote USR_5",
                         "wrote USR-6", "wrote 3, kept 1, skipped (done) 2"], lines
        assert (root / "tasks" / "USR-1" / "task.md").read_text(encoding="utf-8") == "# USR-1 First\n\nDo the first\n"
        assert (root / "tasks" / "USR_5" / "task.md").is_file() and not (root / "tasks" / "USR-2").exists()
        assert (root / "tasks" / "USR-4" / "task.md").read_text(encoding="utf-8") == "mine"


def test_tasks_from_csv_missing_column_exits_2_with_the_columns():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "in.csv").write_text(CSV, encoding="utf-8-sig")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert project.main(["tasks-from-csv", str(root / "in.csv"), str(root / "tasks"), "--key", "Key"]) == 2
        assert "Key" in err.getvalue() and "Issue key, Summary, Description, Status" in err.getvalue()
        assert not (root / "tasks").exists()


# a clio test project's relative paths: two levels up from tests/<Pkg>/, one more from tests/<Pkg>/unit/ (b, f: the extra level)
CSPROJ = ('<Project><Import Project="{b}..\\..\\.build-props\\env.props" /><P>{f}../../.application/core-bin</P>'
          '<H>$(TestCoreLibPath)\\..\\bin</H></Project>')


def test_tests_init_bootstraps_a_bare_package_and_a_second_run_says_what_exists():
    """S46-T09: clio mocked - the workspace, the package project from add-package in a scratch workspace, new-test-project,
    the binaries copied into .application, app.config from the assembly identities, the paths and the command in project.json."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "ws" / "packages" / "UsrPkg" / "Files" / "cs").mkdir(parents=True)
        web = root / "platform" / "Terrasoft.WebApp"
        (web / "bin").mkdir(parents=True)
        (web / "bin" / "Terrasoft.Core.dll").write_bytes(b"MZ")
        (web / "conf" / "bin" / "1").mkdir(parents=True)
        (web / "conf" / "bin" / "1" / "Terrasoft.Configuration.dll").write_bytes(b"MZ")
        source = root / "project.json"
        source.write_text(json.dumps({"environment": {"platformVersion": "8.2.3"},
                                      "package": {"name": "UsrPkg", "workspace": "ws"},
                                      "paths": {"unitTestBin": str(web / "bin")}}), encoding="utf-8")
        calls = []

        def run(cmd, cwd=None, **kwargs):
            calls.append(cmd[:2])
            if cmd[:2] == ["clio", "create-workspace"]:
                ws = Path(cmd[cmd.index("--directory") + 1]) / cmd[2]
                (ws / ".clio").mkdir(parents=True, exist_ok=True)
                (ws / ".clio" / "workspaceSettings.json").write_text('{"Packages": [], "ApplicationVersion": "8.3.0"}', encoding="utf-8")
            elif cmd[:2] == ["clio", "add-package"]:
                files = Path(cwd) / "packages" / cmd[2] / "Files"
                files.mkdir(parents=True)
                for n in (f"{cmd[2]}.csproj", "Directory.Build.targets", "Libs.dll"):
                    (files / n).write_text("<Project />", encoding="utf-8")
            elif cmd[:2] == ["clio", "new-test-project"]:
                tests = Path(cwd) / "tests"
                (tests / cmd[3]).mkdir(parents=True)
                (tests / cmd[3] / f"{cmd[3]}.Tests.csproj").write_text(CSPROJ.format(b="", f=""), encoding="utf-8")
                (tests / cmd[3] / "UnitTest1.cs").write_text("class T {}", encoding="utf-8")
                (tests / "UnitTests.slnx").write_text(f'<Solution><Project Path="{cmd[3]}\\{cmd[3]}.Tests.csproj" /></Solution>', encoding="utf-8")
            elif cmd[0] == "powershell":
                return subprocess.CompletedProcess(cmd, 0, "Terrasoft.Core 8.3.2.4199 edaadfbc3b0bb879\nCreatio.FeatureToggling 1.0.5.0 edaadfbc3b0bb879\n", "")
            return subprocess.CompletedProcess(cmd, 0, "Done", "")
        lines, ok = project.tests_init(source, run)
        ws = root / "ws"
        assert ok and [c[1] for c in calls] == ["create-workspace", "create-workspace", "add-package", "new-test-project", "-NoProfile"], calls
        assert json.loads((ws / ".clio" / "workspaceSettings.json").read_text(encoding="utf-8")) == {"Packages": ["UsrPkg"], "ApplicationVersion": "8.2.3"}
        files = ws / "packages" / "UsrPkg" / "Files"
        assert (files / "UsrPkg.csproj").is_file() and (files / "Directory.Build.targets").is_file() and not (files / "Libs.dll").exists()
        assert (ws / ".application" / "net-framework" / "core-bin" / "Terrasoft.Core.dll").is_file()
        assert (ws / ".application" / "net-framework" / "bin" / "Terrasoft.Configuration.dll").is_file()
        unit = ws / "tests" / "UsrPkg" / "unit"  # S51-T01: the unit project lives in tests/<Pkg>/unit
        assert (unit / "UnitTest1.cs").is_file() and not (ws / "tests" / "UsrPkg" / "UsrPkg.Tests.csproj").exists()
        assert (unit / "UsrPkg.Tests.csproj").read_text(encoding="utf-8") == CSPROJ.format(b="..\\", f="../")
        assert 'Path="UsrPkg\\unit\\UsrPkg.Tests.csproj"' in (ws / "tests" / "UnitTests.slnx").read_text(encoding="utf-8")
        assert "test project: created tests/UsrPkg/unit" in lines, lines
        config = (unit / "app.config").read_text(encoding="utf-8")
        assert config.count("<bindingRedirect") == 2 and 'name="Terrasoft.Core" publicKeyToken="edaadfbc3b0bb879"' in config and 'newVersion="1.0.5.0"' in config
        data = json.loads(source.read_text(encoding="utf-8"))
        assert data["paths"]["unitTests"] == str(unit) and data["paths"]["solution"] == str(ws / "tests" / "UnitTests.slnx")
        assert data["commands"]["unitTests"] == f'dotnet test "{ws / "tests" / "UnitTests.slnx"}" -c dev-nf' and data["paths"]["unitTestBin"]
        assert lines[-1].startswith("run the unit tests: dotnet test ") and "push.py --build" in lines[-1]
        calls.clear()
        lines, ok = project.tests_init(source, run)
        assert ok and calls == [] and lines[:-1] == ["workspace: exists", "workspace settings: exist", "package project: exists",
                                                     "test project: exists", "test binaries: exist", "app.config: exists",
                                                     "project.json: up to date"], lines


def test_tests_init_uses_a_project_at_the_legacy_location_and_says_to_move_it():  # S51-T01
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ws = root / "ws"
        (ws / "packages" / "UsrPkg" / "Files").mkdir(parents=True)
        for name in ("UsrPkg.csproj", "Directory.Build.targets"):
            (ws / "packages" / "UsrPkg" / "Files" / name).write_text("<Project />", encoding="utf-8")
        (ws / ".clio").mkdir()
        (ws / ".clio" / "workspaceSettings.json").write_text('{"Packages": ["UsrPkg"], "ApplicationVersion": "8.3.2"}', encoding="utf-8")
        (ws / ".application" / "net-framework" / "core-bin").mkdir(parents=True)
        (ws / ".application" / "net-framework" / "core-bin" / "Terrasoft.Core.dll").write_bytes(b"MZ")
        legacy = ws / "tests" / "UsrPkg"
        legacy.mkdir(parents=True)
        (legacy / "UsrPkg.Tests.csproj").write_text("<Project />", encoding="utf-8")
        (legacy / "app.config").write_text("<configuration />", encoding="utf-8")
        source = root / "project.json"
        source.write_text(json.dumps({"environment": {"platformVersion": "8.3.2"},
                                      "package": {"name": "UsrPkg", "workspace": "ws"}}), encoding="utf-8")
        calls = []
        lines, ok = project.tests_init(source, lambda cmd, **kwargs: calls.append(cmd))
        assert ok and calls == [] and not (legacy / "unit").exists(), (lines, calls)
        assert "test project: exists at the legacy location tests/UsrPkg/ - move it to unit/" in lines, lines
        assert json.loads(source.read_text(encoding="utf-8"))["paths"]["unitTests"] == str(legacy)


def test_tests_init_without_test_binaries_says_so_and_exits_1():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "ws" / "packages" / "UsrPkg" / "Files").mkdir(parents=True)
        (root / "ws" / ".clio").mkdir(parents=True)
        (root / "ws" / ".clio" / "workspaceSettings.json").write_text('{"Packages": ["UsrPkg"]}', encoding="utf-8")
        for n in ("UsrPkg.csproj", "Directory.Build.targets"):
            (root / "ws" / "packages" / "UsrPkg" / "Files" / n).write_text("<Project />", encoding="utf-8")
        (root / "ws" / "tests" / "UsrPkg").mkdir(parents=True)
        (root / "ws" / "tests" / "UsrPkg" / "UsrPkg.Tests.csproj").write_text("<Project />", encoding="utf-8")
        source = root / "project.json"
        source.write_text(json.dumps({"package": {"name": "UsrPkg", "workspace": str(root / "ws")}}), encoding="utf-8")
        out = io.StringIO()
        with patch.object(project.subprocess, "run", side_effect=AssertionError("nothing to run")), contextlib.redirect_stdout(out):
            assert project.main(["tests-init", str(source)]) == 1
        assert "test binaries: missing - set paths.unitTestBin" in out.getvalue(), out.getvalue()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
