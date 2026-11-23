"""S33-T09: every command line writes UTF-8 by itself.  python tests/test_utf8_cli.py

A Cyrillic caption must come out of a CLI as UTF-8 with PYTHONIOENCODING and PYTHONUTF8 unset (on Windows a pipe defaults to the
ANSI code page), and every entry script carries the guard."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
KB = TOOLS.parent.parent
KIT = KB.parent  # agent_setup.py is at the kit root
FIXTURE = TOOLS / "pages" / "tests" / "fixtures" / "UsrPkg"


def test_a_cyrillic_caption_survives_a_pipe_without_pythonioencoding():
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    with tempfile.TemporaryDirectory() as tmp:
        package = Path(tmp) / "UsrPkg"
        shutil.copytree(FIXTURE, package, ignore=shutil.ignore_patterns(".creatio-*"))
        done = subprocess.run([sys.executable, str(TOOLS / "describe" / "describe.py"), "resolve", str(package), "Заказ"],
                              capture_output=True, env=env, cwd=tmp)
        out = done.stdout.decode("utf-8")  # raises when the bytes are not UTF-8
        assert 'no caption holds "Заказ"' in out, (out, done.stderr[-300:])
        failing = subprocess.run([sys.executable, str(TOOLS / "env" / "record.py"), "history", "-e", "none", "Заказ"], capture_output=True, env=env, cwd=tmp)
        assert failing.returncode == 2 and failing.stderr.decode("utf-8"), failing.stderr  # stderr too: an error line naming the Cyrillic input is readable


def test_every_entry_script_carries_the_guard():
    candidates = list(TOOLS.rglob("*.py")) + [KIT / "agent_setup.py"] + list((KB / "mcp-server").glob("*.py"))
    entries, missing = [], []
    for p in candidates:
        rel = p.relative_to(KIT).as_posix()
        if any(part in rel.split("/") for part in ("tests", "fixtures", "__pycache__", ".venv")) or p.name.startswith("test_") or p.name == "server.py":
            continue
        text = p.read_text(encoding="utf-8")
        if 'if __name__ == "__main__":' not in text:
            continue
        entries.append(rel)
        if "S33-T09" not in text:
            missing.append(rel)
    assert len(entries) >= 25 and not missing, missing


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
