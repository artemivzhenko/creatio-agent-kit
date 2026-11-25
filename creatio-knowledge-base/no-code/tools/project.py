#!/usr/bin/env python3
"""Synchronize the test framework's environment configuration from project.json; bootstrap the unit-test project."""

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def read_json(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    # Framework configuration accepts comments; preserve strings while removing comments.
    result = []
    i = 0
    in_string = False
    escaped = False
    while i < len(text):
        ch = text[i]
        if in_string:
            result.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
        elif ch == '"':
            in_string = True
            result.append(ch)
            i += 1
        elif text[i:i + 2] == "//":
            end = text.find("\n", i + 2)
            i = len(text) if end < 0 else end
        elif text[i:i + 2] == "/*":
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError(f"{path}: unterminated comment")
            result.append(" ")
            i = end + 2
        else:
            result.append(ch)
            i += 1
    text = "".join(result)
    result = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            result.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            result.append(ch)
        elif ch == "," and text[i + 1:].lstrip().startswith(("}", "]")):
            continue
        else:
            result.append(ch)
    value = json.loads("".join(result))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def sync(project_file: Path, framework: Path | None = None) -> list[str]:
    project = read_json(project_file)
    env = project.get("environment")
    if not isinstance(env, dict) or any(not isinstance(env.get(k), str) or not env[k].strip()
                                        for k in ("url", "login", "password")):
        raise ValueError("project.json must contain environment.url, login and password")
    paths = project.get("paths")
    configured = paths.get("testFramework") if isinstance(paths, dict) else None
    if framework is None:
        if not isinstance(configured, str) or not configured.strip():
            raise ValueError("supply --framework or paths.testFramework in project.json")
        framework = Path(configured)
        if not framework.is_absolute():
            framework = project_file.resolve().parent / framework
    if not framework.is_dir() or not (framework / "Configuration").is_dir():
        raise ValueError(f"framework Configuration directory not found: {framework}")
    target = framework / "Configuration" / "creatio.env.config.json"
    config = read_json(target) if target.exists() else {}
    updates = {
        "BaseUrl": env["url"],
        "Users": [{"Username": env["login"], "Password": env["password"]}],
        "CasesFolders": config.get("CasesFolders", ["./Cases"]),
    }
    if not isinstance(updates["CasesFolders"], list) or not all(isinstance(p, str) for p in updates["CasesFolders"]):
        raise ValueError(f"{target}: CasesFolders must be a list of strings")
    changed = [key for key, value in updates.items() if config.get(key) != value]
    if not target.exists() or changed:
        config.update(updates)
        target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def tasks_from_csv(csv_file: Path, tasks: Path, key: str, title: str, text: str, status: str,
                   done: set[str], dry_run: bool = False) -> list[str]:
    """One <tasks>/<key>/task.md per CSV row; done rows and existing task.md are left alone."""
    with csv_file.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in (key, title, text, status) if c not in (reader.fieldnames or [])]
        if missing:
            raise KeyError(f"missing column {', '.join(missing)}; the file has: {', '.join(reader.fieldnames or [])}")
        rows = list(reader)
    lines, counts = [], {"wrote": 0, "kept": 0, "skipped (done)": 0}
    for row in rows:
        folder = re.sub(r"[^A-Za-z0-9_-]", "_", row[key].strip())
        if row[status].strip() in done:
            verdict = "skipped (done)"
        elif (tasks / folder / "task.md").is_file() and (tasks / folder / "task.md").stat().st_size:
            verdict = "kept"
        else:
            verdict = "wrote"
            if not dry_run:
                (tasks / folder).mkdir(parents=True, exist_ok=True)
                (tasks / folder / "task.md").write_text(
                    f"# {row[key].strip()} {row[title].strip()}\n\n{row[text].strip()}\n", encoding="utf-8")
        counts[verdict] += 1
        lines.append(f"{'would write' if dry_run and verdict == 'wrote' else verdict} {folder}")
    return lines + [", ".join(f"{k} {v}" for k, v in counts.items())]


REDIRECTS_PS = ("Get-ChildItem -LiteralPath '{bin}' -Filter *.dll | Where-Object {{ $_.Name -like 'Terrasoft.*' -or $_.Name -like "
                "'Creatio.*' }} | ForEach-Object {{ try {{ $n = [Reflection.AssemblyName]::GetAssemblyName($_.FullName); "
                "$t = ($n.GetPublicKeyToken() | ForEach-Object {{ $_.ToString('x2') }}) -join ''; "
                "if ($t) {{ \"$($n.Name) $($n.Version) $t\" }} }} catch {{ }} }}")


def _app_config(identities: str) -> str:
    """app.config redirecting every listed assembly (`name version token` lines) to that version: the clio test kit is
    built on other platform builds than the local binaries the tests run against (gap 13: FileLoadException in SetUp)."""
    entries = "".join(
        f'\t\t\t<dependentAssembly>\n\t\t\t\t<assemblyIdentity name="{n}" publicKeyToken="{t}" culture="neutral" />\n'
        f'\t\t\t\t<bindingRedirect oldVersion="0.0.0.0-99.0.0.0" newVersion="{v}" />\n\t\t\t</dependentAssembly>\n'
        for n, v, t in sorted(tuple(line.split()) for line in identities.splitlines() if len(line.split()) == 3))
    return ('<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n\t<runtime>\n'
            '\t\t<assemblyBinding xmlns="urn:schemas-microsoft-com:asm.v1">\n' + entries +
            '\t\t</assemblyBinding>\n\t</runtime>\n</configuration>\n')


def tests_init(project_file: Path, run=None) -> tuple[list[str], bool]:
    """Make the package's workspace run `dotnet test` (S46-T09, gaps 12/13): a clio workspace, the package project
    Files/<Pkg>.csproj, `clio new-test-project`, the binaries under .application/net-framework, an app.config of binding
    redirects; then paths.unitTests, paths.solution and commands.unitTests into project.json. Each step that finds its
    result says `exists`. (lines, ok): not ok when the test binaries are missing."""
    run = run or subprocess.run
    project = read_json(project_file)
    base = project_file.resolve().parent
    pkg = (project.get("package") or {}).get("name")
    ws = (project.get("package") or {}).get("workspace")
    if not pkg or not ws:
        raise ValueError("project.json must contain package.name and package.workspace")
    ws = Path(ws) if Path(ws).is_absolute() else base / ws
    if not (ws / "packages" / pkg).is_dir():
        raise ValueError(f"no package folder {ws / 'packages' / pkg}")
    paths = project.get("paths") or {}
    lines = []

    def clio(args, cwd):
        done = run(["clio", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
        if done.returncode:
            raise RuntimeError(f"clio {args[0]} exit {done.returncode}: {((done.stdout or '') + (done.stderr or '')).strip()[-300:]}")

    settings = ws / ".clio" / "workspaceSettings.json"
    if settings.is_file():
        lines.append("workspace: exists")
    else:
        clio(["create-workspace", ws.name, "--empty", "--directory", str(ws.parent), "--force"], ws.parent)
        lines.append("workspace: created (clio create-workspace --empty)")
    data = read_json(settings)
    wanted = {"Packages": list(dict.fromkeys([*(data.get("Packages") or []), pkg])),
              "ApplicationVersion": (project.get("environment") or {}).get("platformVersion") or data.get("ApplicationVersion")}
    changed = [k for k, v in wanted.items() if data.get(k) != v]
    if changed:
        data.update(wanted)
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    lines.append("workspace settings: " + (f"set {', '.join(changed)}" if changed else "exist"))

    files = ws / "packages" / pkg / "Files"
    names = (f"{pkg}.csproj", "Directory.Build.targets")
    missing = [n for n in names if not (files / n).is_file()]
    if missing:
        with tempfile.TemporaryDirectory() as tmp:  # clio's own template: add-package in a scratch workspace
            clio(["create-workspace", "tmpws", "--empty", "--directory", tmp], tmp)
            clio(["add-package", pkg], Path(tmp) / "tmpws")
            files.mkdir(parents=True, exist_ok=True)
            for n in missing:  # not Libs/*.dll: binaries do not belong in the package (two MSB3245 warnings at build)
                shutil.copyfile(Path(tmp) / "tmpws" / "packages" / pkg / "Files" / n, files / n)
    lines.append("package project: " + (f"wrote {', '.join('Files/' + n for n in missing)}" if missing else "exists"))

    tests = ws / "tests" / pkg
    if (tests / f"{pkg}.Tests.csproj").is_file():
        lines.append("test project: exists")
    else:
        clio(["new-test-project", "--package", pkg], ws)
        if not (tests / f"{pkg}.Tests.csproj").is_file():
            raise RuntimeError(f"clio new-test-project wrote no {tests / (pkg + '.Tests.csproj')}")
        lines.append(f"test project: created tests/{pkg}")
    solution = next(iter(sorted((ws / "tests").glob("*.sln*"))), tests / f"{pkg}.Tests.csproj")

    # the test csproj and .build-props/env.dev-nf.props read the binaries from clio's layout; a copy, not a link: a clio
    # command that refreshes .application must never delete inside a platform install
    app = ws / ".application" / "net-framework"
    ok = True
    if (app / "core-bin" / "Terrasoft.Core.dll").is_file():
        lines.append("test binaries: exist")
    elif paths.get("unitTestBin"):
        source = Path(paths["unitTestBin"]) if Path(paths["unitTestBin"]).is_absolute() else base / paths["unitTestBin"]
        confs = sorted(source.parent.glob("conf/bin/*/Terrasoft.Configuration.dll"), key=lambda p: p.stat().st_mtime)
        if not (source / "Terrasoft.Core.dll").is_file() or not confs:
            raise ValueError(f"{source}: no Terrasoft.Core.dll, or no conf/bin/*/Terrasoft.Configuration.dll beside it (paths.unitTestBin)")
        shutil.copytree(source, app / "core-bin", dirs_exist_ok=True)
        (app / "bin").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(confs[-1], app / "bin" / "Terrasoft.Configuration.dll")
        lines.append(f"test binaries: copied from {source}")
    else:
        ok = False
        lines.append("test binaries: missing - set paths.unitTestBin in project.json (a local Terrasoft.WebApp/bin the "
                     "clio test kit accepts: 8.3.2 or newer) and run again")
    config = tests / "app.config"
    if config.is_file():
        lines.append("app.config: exists")
    elif ok:
        done = run(["powershell", "-NoProfile", "-Command", REDIRECTS_PS.format(bin=str(app / "core-bin").replace("'", "''"))],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
        if done.returncode or not done.stdout.strip():
            raise RuntimeError(f"no assembly identities read from {app / 'core-bin'}: {(done.stderr or '').strip()[-300:]}")
        config.write_text(_app_config(done.stdout), encoding="utf-8")
        lines.append(f"app.config: wrote {config.read_text(encoding='utf-8').count('<bindingRedirect')} binding redirects")

    command = f'dotnet test "{solution}" -c dev-nf'
    raw = json.loads(project_file.read_text(encoding="utf-8-sig"))  # the file as it is, not read_json's comment-free copy
    updates = {("paths", "unitTests"): str(tests), ("paths", "solution"): str(solution), ("commands", "unitTests"): command}
    changed = [f"{a}.{b}" for (a, b), v in updates.items() if (raw.get(a) or {}).get(b) != v]
    if changed:
        for (a, b), v in updates.items():
            raw.setdefault(a, {})[b] = v
        project_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines.append("project.json: " + (f"set {', '.join(changed)}" if changed else "up to date"))
    lines.append(f"run the unit tests: {command}  (it rebuilds Files/Bin/{pkg}.dll against these binaries: "
                 "push with `push.py --build`)")
    return lines, ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("sync", help="write the framework environment from project.json")
    command.add_argument("project", type=Path)
    command.add_argument("--framework", type=Path)
    cmd = sub.add_parser("tasks-from-csv", help="one task folder per row of a tracker's CSV export")
    cmd.add_argument("csv_file", type=Path)
    cmd.add_argument("tasks", type=Path)
    cmd.add_argument("--key", default="Issue key")
    cmd.add_argument("--title", default="Summary")
    cmd.add_argument("--text", default="Description")
    cmd.add_argument("--status", default="Status")
    cmd.add_argument("--done", default="", help="comma-separated statuses to skip")
    cmd.add_argument("--dry-run", action="store_true")
    cmd = sub.add_parser("tests-init", help="make the workspace run the package's unit tests; write the run command into project.json")
    cmd.add_argument("project", type=Path)
    args = parser.parse_args(argv)
    if args.command == "tests-init":
        try:
            lines, ok = tests_init(args.project)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"tests-init failed: {exc}", file=sys.stderr)
            return 1
        print("\n".join(lines))
        return 0 if ok else 1
    if args.command == "tasks-from-csv":
        try:
            done = {d.strip() for d in args.done.split(",") if d.strip()}
            print("\n".join(tasks_from_csv(args.csv_file, args.tasks, args.key, args.title, args.text,
                                           args.status, done, args.dry_run)))
        except KeyError as exc:
            print(f"tasks-from-csv: {exc.args[0]}", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"tasks-from-csv failed: {exc}", file=sys.stderr)
            return 1
        return 0
    try:
        changed = sync(args.project, args.framework)
    except (OSError, ValueError) as exc:
        print(f"sync failed: {exc}", file=sys.stderr)
        return 1
    print("Updated: " + ", ".join(changed) if changed else "Already synchronized.")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
