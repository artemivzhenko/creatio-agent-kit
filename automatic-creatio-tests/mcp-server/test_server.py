"""Checks for the MCP server's tools, called as plain functions:  python test_server.py"""

import sys
import shutil
import tempfile
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402


def test_reads():
    assert "## Backend cases" in server.dsl()
    listing = server.cases()
    assert "Cases/" in listing and ".act.exp" in listing and "[example]" in listing
    process_examples = server.cases("ProcessCases")
    assert "order-process.act.exp" in process_examples and "[example]" in process_examples
    first_case = next(p for p in sorted((server.ROOT / "Cases").glob("*.act.exp")))
    assert "use " in server.case(first_case.name.removesuffix(".act.exp")) and "use " in server.case(first_case.name)
    assert server.case("nope").startswith("no case")
    first_page = next(p for p in sorted((server.ROOT / "Configuration" / "pages").glob("*.json")))
    assert f'"name": "{first_page.stem}"' in server.page_config(first_page.stem)
    assert "does not exist" in server.page_config("Nope")
    assert "does not exist" in server.process_config("Nope")
    assert "Loop for a new case" in server.overview()


def test_validate_runs_the_command_line():
    root = server.ROOT
    with tempfile.TemporaryDirectory() as tmp:
        isolated = Path(tmp)
        (isolated / "Configuration" / "pages").mkdir(parents=True)
        (isolated / "Cases").mkdir()
        for name in ("creatio.site.config.json", "run.config.json", "objects.config.json", "static.values.json"):
            shutil.copyfile(root / "Configuration" / name, isolated / "Configuration" / name)
        shutil.copyfile(root / "Configuration" / "creatio.env.config.example.json",
                        isolated / "Configuration" / "creatio.env.config.json")
        shutil.copyfile(root / "Configuration" / "pages" / "OrderClassic.json",
                        isolated / "Configuration" / "pages" / "OrderClassic.json")
        shutil.copyfile(root / "Cases" / "classic-order-form.act.exp",
                        isolated / "Cases" / "classic-order-form.act")
        page = isolated / "Configuration" / "pages" / "OrderClassic.json"
        data = json.loads(page.read_text(encoding="utf-8-sig"))
        data["elements"].append({"code": "Код", "label": "Название", "type": "Text", "tab": "GeneralInfoTab"})
        page.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        (isolated / "Cases" / "unicode.act").write_text(
            'use Supervisor\nopen OrderClassic\nset Код "Тест"\n', encoding="utf-8")
        try:
            server.ROOT = isolated
            out = server.validate()
            page_out = server.page_config("OrderClassic")
        finally:
            server.ROOT = root
    assert "case(s) checked" in out and out.rstrip().endswith("exit code 0"), out
    assert "Название" in page_out


def test_run_forwards_the_task_folder_without_running():
    from unittest.mock import patch

    with patch.object(server, "_cli", side_effect=lambda args, timeout=0: " ".join(args)) as cli:
        out = server.run("contact", task_folder="C:/tasks/012", task="012")
    assert out == "--filter contact --task-folder C:/tasks/012 --task 012", out
    assert cli.call_count == 1
    with patch.object(server, "_cli", return_value="rebuilt the stale exe: ok\n\nsite: https://dev.example.com (clio dev)\nrunning\n\nexit code 0"):
        out = server.run()
    assert out.splitlines()[:3] == ["site: https://dev.example.com (clio dev)", "rebuilt the stale exe: ok", ""], out


def test_stale_exe_is_rebuilt_or_warned():
    import os
    import time
    from unittest.mock import patch

    saved = (server.ROOT, server.CLI_PROJECT)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cli = root / "src" / "CreatioAutoTests.Cli"
        exe = cli / "bin" / "Debug" / "net8.0" / ("creatio-tests.exe" if os.name == "nt" else "creatio-tests")
        exe.parent.mkdir(parents=True)
        exe.write_text("x")
        source = root / "src" / "A.cs"
        source.write_text("class A {}")
        generated = root / "src" / "obj" / "G.cs"  # build output is not a source
        generated.parent.mkdir()
        generated.write_text("class G {}")
        now = time.time()
        os.utime(exe, (now, now))
        os.utime(generated, (now + 100, now + 100))
        os.utime(source, (now - 100, now - 100))
        server.ROOT, server.CLI_PROJECT = root, cli
        try:
            assert server._stale_note() == ""  # fresh
            os.utime(source, (now + 100, now + 100))
            with patch.dict(os.environ, {"CREATIO_TESTS_NO_BUILD": "1"}), patch.object(server.subprocess, "run") as run:
                note = server._stale_note()
            assert "older than the sources" in note and "dotnet build" in note and "-c Debug" in note and run.call_count == 0, note
            done = type("R", (), {"stdout": "Build succeeded.\n\nTime Elapsed 00:00:05\n", "returncode": 0})()
            with patch.dict(os.environ, {"CREATIO_TESTS_NO_BUILD": ""}), patch.object(server.subprocess, "run", return_value=done) as run:
                note = server._stale_note()
            assert run.call_count == 1 and run.call_args.args[0][:2] == ["dotnet", "build"] and "Time Elapsed 00:00:05" in note, note
            os.utime(exe.parent / "a.dll", None) if (exe.parent / "a.dll").exists() else (exe.parent / "a.dll").write_text("d")
            os.utime(exe.parent / "a.dll", (now + 200, now + 200))  # a rebuilt dll beside the exe makes it fresh
            assert server._stale_note() == ""
        finally:
            server.ROOT, server.CLI_PROJECT = saved


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
