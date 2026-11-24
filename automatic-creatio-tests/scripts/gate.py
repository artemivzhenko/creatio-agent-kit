#!/usr/bin/env python3
"""The gate every change to the test utility ends with (S11-T11): build, unit tests, `--validate-only` over the repo's cases, and
the live run of those cases on a test site. One command, exit 0 only when all four are green.

    py -3 scripts/gate.py [--live-root <dir>] [--rename Usr=ia] [--skip a,b] [--filter <text>]

Without `--live-root` the live part is skipped and said so. `--live-root` is a test root of its own (a `Configuration/` pointing at
the test site, the pages of the beds) that the gate OWNS: it deletes the `*.act` files of its `Cases/` and `ProcessCases/` and copies
the repo's active cases (`*.act`, not `*.act.exp`) in. `--rename Usr=ia` maps the repo's `Usr` names and `usr-` case names to the
prefix the site really holds (the repo keeps `Usr` only); a case whose leading comment lines hold `# bed bench` targets the
benchmark package, whose `Usr` names are real, and is copied as it is; `--skip` leaves out cases the site cannot pass.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
CLI = HERE / "src" / "CreatioAutoTests.Cli" / "bin" / "Debug" / "net8.0" / "creatio-tests.dll"


def run(label: str, cmd: list[str]) -> bool:
    print(f"== {label}: {' '.join(cmd)}", flush=True)
    code = subprocess.run(cmd, cwd=HERE).returncode
    print(f"== {label}: {'ok' if code == 0 else f'FAILED (exit {code})'}", flush=True)
    return code == 0


def mapped(text: str, prefix: str) -> str:
    """The repo's `Usr` names and `usr-` case names under the site's prefix."""
    return re.sub(r"\busr-", prefix.lower() + "-", re.sub(r"\bUsr([A-Z])", prefix + r"\1", text))


def bed_of(text: str) -> str:
    """`bench` when a leading `#` line says `# bed bench`, else `test-package`."""
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        if line.strip() == "# bed bench":
            return "bench"
    return "test-package"


def bed_counts(report: str, beds: dict[str, str]) -> str:
    """`test-package: N passed, bench: M passed` from the `PASS`/`FAIL` lines of a run report."""
    passed = {b: 0 for b in ("test-package", "bench")}
    for m in re.finditer(r"^PASS  (\S+)", report, re.M):
        passed[beds.get(m.group(1), "test-package")] += 1
    return ", ".join(f"{b}: {n} passed" for b, n in passed.items())


def copy_cases(live_root: Path, prefix: str | None, skip: set[str], beds: dict[str, str] | None = None) -> int:
    n = 0
    for folder in ("Cases", "ProcessCases"):
        target = live_root / folder
        target.mkdir(parents=True, exist_ok=True)
        for old in target.glob("*.act"):
            old.unlink()
        for src in sorted((HERE / folder).glob("*.act")):
            if src.stem in skip:
                continue
            text = src.read_text(encoding="utf-8")
            name = src.name
            bed = bed_of(text)
            if prefix and bed == "test-package":
                text, name = mapped(text, prefix), mapped(name, prefix)
            if beds is not None:
                beds[Path(name).stem] = bed
            (target / name).write_text(text, encoding="utf-8")
            n += 1
    # what the cases read besides themselves: the files they upload and the process configurations they start
    for folder, rename in (("TestData", False), ("Configuration/processes", True)):
        for src in sorted((HERE / folder).glob("*")) if (HERE / folder).is_dir() else []:
            (live_root / folder).mkdir(parents=True, exist_ok=True)
            if rename and prefix:
                (live_root / folder / mapped(src.name, prefix)).write_text(mapped(src.read_text(encoding="utf-8"), prefix), encoding="utf-8")
            else:
                (live_root / folder / src.name).write_bytes(src.read_bytes())
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live-root")
    ap.add_argument("--rename", help="Usr=<prefix> of the site")
    ap.add_argument("--skip", default="")
    ap.add_argument("--filter", default="")
    a = ap.parse_args(argv)

    ok = run("build", ["dotnet", "build", "src/CreatioAutoTests.Cli"]) \
        and run("unit tests", ["dotnet", "test", "tests/CreatioAutoTests.Tests"]) \
        and run("validate", ["dotnet", str(CLI), "--root", str(HERE), "--validate-only"])
    if not ok:
        return 1
    if not a.live_root:
        print("== live: skipped (no --live-root); the gate is not complete")
        return 0
    prefix = a.rename.split("=", 1)[1] if a.rename and a.rename.startswith("Usr=") else None
    live = Path(a.live_root).resolve()
    beds: dict[str, str] = {}
    print(f"== live: {copy_cases(live, prefix, {s for s in a.skip.split(',') if s}, beds)} cases copied into {live}")
    cmd = ["dotnet", str(CLI), "--root", str(live)] + (["--filter", a.filter] if a.filter else [])
    ok = run("live", cmd)
    reports = sorted((live / "Reports").glob("run-*.txt"))
    if reports:
        print(f"== live: {bed_counts(reports[-1].read_text(encoding='utf-8'), beds)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
