#!/usr/bin/env python3
"""The CI/CD pipeline of a Creatio package repository, one stage per subcommand. Standard library and clio only.

    python pipeline.py check   <packages dir> [--package A,B] [--cyrillic]      the package rules, no site needed
    python pipeline.py build   <packages dir> --out Build [--package A,B]       clio compress -> Build/<pkg>.gz + Build/Pkg.zip
    python pipeline.py register <env> --url URL --login L --password P          clio reg-web-app on a runner (from secrets)
    python pipeline.py deploy  <packages dir> -e <env> [--package A,B] [--no-restart] [--no-redis] [--all]
                                        clear IsChanged -> push-pkg per package -> compile-configuration -> restart-web-app
                                        --wait-ready -> clear-redis-db -> healthcheck
    python pipeline.py unit    -e <env> --runner <process or service> [--category C] [--class K] [--evidence f.json]
                                        the unit tests inside Creatio (env/unit.py of the kit): exit 1 on a failed test
    python pipeline.py ui      --root <folder with Cases/ and Configuration/> [--filter F] [--validate-only]
                                        the .act cases (the kit's test framework); the site from CREATIO_URL / CREATIO_LOGIN /
                                        CREATIO_PASSWORD when Configuration/creatio.env.config.json is absent

Package order for deploy: `--package A,B,C` as given; else `.clio/workspaceSettings.json` ("Packages") next to the
packages dir; else the folders in dependency order from their descriptor.json DependsOn. Every stage exits non-zero on
a failure, so a pipeline step fails with it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
UNIT_PY = KIT / "creatio-knowledge-base" / "no-code" / "tools" / "env" / "unit.py"
TESTS_CLI = KIT / "automatic-creatio-tests" / "src" / "CreatioAutoTests.Cli"
ISCHANGED_TABLES = ("SysSchema", "SysPackageSchemaData", "SysPackageSqlScript")  # the kit's push does the same
CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def shown(cmd: list[str]) -> str:
    """The command line as the log shows it: the value after -p / --password masked (a CI log or an MCP answer is not a vault)."""
    return " ".join("***" if i and cmd[i - 1] in ("-p", "--password") else x for i, x in enumerate(cmd))


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> int:
    print("+ " + shown(cmd), flush=True)
    # captured, not inherited: the kit's MCP server runs these stages in-process and its stdout is the protocol channel
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    for text in (result.stdout, result.stderr):
        if text.strip():
            print(text.rstrip(), flush=True)
    code = result.returncode
    if check and code:
        sys.exit(f"failed ({code}): {shown(cmd)}")
    return code


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def package_dirs(root: Path, names: str | None) -> list[Path]:
    """The package folders to work on, in deploy order."""
    found = {p.name: p for p in root.iterdir() if p.is_dir() and (p / "descriptor.json").is_file()}
    if not found:
        sys.exit(f"no package folder with a descriptor.json under {root}")
    if names:
        missing = [n for n in names.split(",") if n not in found]
        if missing:
            sys.exit(f"not under {root}: {', '.join(missing)}")
        return [found[n] for n in names.split(",")]
    settings = root.parent / ".clio" / "workspaceSettings.json"
    if settings.is_file():
        listed = [n for n in read_json(settings).get("Packages", []) if n in found]
        if listed:
            return [found[n] for n in listed]
    return [found[n] for n in dependency_order(found)]


def dependency_order(found: dict[str, Path]) -> list[str]:
    """Dependencies first, by descriptor.json DependsOn (names outside the folder are ignored)."""
    deps = {}
    for name, folder in found.items():
        d = read_json(folder / "descriptor.json").get("Descriptor", {})
        deps[name] = {x.get("Name") for x in d.get("DependsOn", []) if x.get("Name") in found}
    order, seen = [], set()

    def visit(n, trail=()):
        if n in seen:
            return
        if n in trail:
            sys.exit(f"dependency cycle: {' -> '.join(trail + (n,))}")
        for m in sorted(deps[n]):
            visit(m, trail + (n,))
        seen.add(n)
        order.append(n)

    for n in sorted(found):
        visit(n)
    return order


# --- check: the package rules (ported from the PowerShell rules of the former repository) --------------------------

def check(packages: list[Path], cyrillic: bool) -> list[str]:
    errors = []
    uids: dict[str, list[str]] = {}
    for pkg in packages:
        schemas = pkg / "Schemas"
        for schema in sorted(p for p in schemas.iterdir() if p.is_dir()) if schemas.is_dir() else []:
            for required in ("metadata.json", "descriptor.json", "properties.json"):
                if not (schema / required).is_file():
                    errors.append(f"{schema}: {required} not found")
            descriptor = schema / "descriptor.json"
            if descriptor.is_file():
                try:
                    uid = read_json(descriptor).get("Descriptor", {}).get("UId", "")
                except ValueError as exc:
                    errors.append(f"{descriptor}: not JSON ({exc})")
                    uid = ""
                if uid:
                    uids.setdefault(uid.lower(), []).append(str(schema))
            for js in schema.glob("*.js"):
                text = js.read_text(encoding="utf-8", errors="replace")
                for n, line in enumerate(text.splitlines(), 1):
                    if re.search(r"\balert\s*\(", line):
                        errors.append(f"{js}:{n}: alert()")
                    if re.search(r"\bdebugger\b", line):
                        errors.append(f"{js}:{n}: debugger")
                    if cyrillic and CYRILLIC.search(re.sub(r"//.*|/\*.*?\*/", "", line)):
                        errors.append(f"{js}:{n}: Cyrillic outside a comment")
        for folder, ext in (("SqlScripts", ".sql"), ("Assemblies", ".dll")):
            base = pkg / folder
            for item in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
                files = [f for f in item.iterdir() if f.suffix.lower() == ext]
                if len(files) != 1:
                    errors.append(f"{item}: {len(files)} {ext} files, expected one")
                elif folder == "SqlScripts" and files[0].stem != item.name:
                    errors.append(f"{files[0]}: the file is not named after its folder")
    for uid, where in uids.items():
        if len(where) > 1:
            errors.append(f"duplicate schema UId {uid}: " + ", ".join(where))
    return errors


# --- build: clio compress per package, one zip of the .gz files (the artifact the deploy and the Upload step take) -----

def build(packages: list[Path], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    for gz in out.glob("*.gz"):
        gz.unlink()
    for pkg in packages:
        run(["clio", "compress", pkg.name], cwd=pkg.parent)
        gz = pkg.parent / f"{pkg.name}.gz"
        if not gz.is_file():
            sys.exit(f"clio compress produced no {gz.name}")
        shutil.move(str(gz), out / gz.name)
    archive = out / "Pkg.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for gz in sorted(out.glob("*.gz")):
            z.write(gz, gz.name)
    print(f"built {archive} ({len(packages)} packages)")
    return archive


# --- deploy --------------------------------------------------------------------------------------------------------

def clear_ischanged(env: str) -> None:
    """Designer-edited schemas count as modified locally and push-pkg skips them otherwise (the kit's push rule)."""
    for table in ISCHANGED_TABLES:
        run(["clio", "execute-sql-script", f'update "{table}" set "IsChanged"=false', "-e", env])


def deploy(packages: list[Path], env: str, restart: bool, redis: bool, compile_all: bool) -> None:
    clear_ischanged(env)
    for pkg in packages:
        run(["clio", "push-pkg", pkg.name, "-e", env], cwd=pkg.parent)
    run(["clio", "compile-configuration", "-e", env] + (["--all"] if compile_all else []))
    if restart:
        run(["clio", "restart-web-app", "-e", env, "--wait-ready"])
    if redis:
        run(["clio", "clear-redis-db", "-e", env])
    run(["clio", "healthcheck", "-e", env, "-a", "true", "-h", "true"])  # clio 8.1: a bare -a is "has no value"


# --- tests ---------------------------------------------------------------------------------------------------------

def unit(args: argparse.Namespace) -> int:
    cmd = [sys.executable, str(UNIT_PY), "run", "-e", args.env, "--runner", args.runner]
    for flag, value in (("--category", args.category), ("--class", args.cls), ("--evidence", args.evidence), ("--package", args.package)):
        if value:
            cmd += [flag, value]
    return run(cmd, check=False)


def ui(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    config = root / "Configuration" / "creatio.env.config.json"
    if not config.is_file():
        url, login, password = (os.environ.get(k) for k in ("CREATIO_URL", "CREATIO_LOGIN", "CREATIO_PASSWORD"))
        if not (url and login and password):
            sys.exit(f"{config} is absent and CREATIO_URL / CREATIO_LOGIN / CREATIO_PASSWORD are not all set")
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"BaseUrl": url, "Users": [{"Username": login, "Password": password}],
                                      "CasesFolders": ["./Cases"], "AnalysisFolders": ["./Analysis"]}, indent=2), encoding="utf-8")
        print(f"wrote {config} from the environment")
    # the framework's own service paths and defaults, for what the project did not bring (never the env config, never the pages)
    for name in ("creatio.site.config.json", "objects.config.json", "run.config.json"):
        target = root / "Configuration" / name
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(TESTS_CLI.parents[1] / "Configuration" / name, target)
    cmd = ["dotnet", "run", "--project", str(TESTS_CLI), "--", "--root", str(root)]
    if args.filter:
        cmd += ["--filter", args.filter]
    if args.validate_only:
        cmd.append("--validate-only")
    return run(cmd, check=False)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="stage", required=True)
    for name in ("check", "build", "deploy"):
        s = sub.add_parser(name)
        s.add_argument("packages", help="the folder that holds the package folders")
        s.add_argument("--package", help="comma-separated names, in this order (default: every package, dependencies first)")
        if name == "check":
            s.add_argument("--cyrillic", action="store_true", help="also refuse Cyrillic outside comments in .js schemas")
        if name == "build":
            s.add_argument("--out", default="Build")
        if name == "deploy":
            s.add_argument("-e", "--env", required=True)
            s.add_argument("--no-restart", action="store_true")
            s.add_argument("--no-redis", action="store_true")
            s.add_argument("--all", action="store_true", help="compile-configuration --all (full rebuild)")
    s = sub.add_parser("register")
    s.add_argument("env"); s.add_argument("--url", required=True); s.add_argument("--login", required=True); s.add_argument("--password", required=True)
    s = sub.add_parser("unit")
    s.add_argument("-e", "--env", required=True); s.add_argument("--runner", required=True)
    s.add_argument("--category"); s.add_argument("--class", dest="cls"); s.add_argument("--evidence"); s.add_argument("--package")
    s = sub.add_parser("ui")
    s.add_argument("--root", required=True); s.add_argument("--filter"); s.add_argument("--validate-only", action="store_true")
    a = p.parse_args(argv)

    if a.stage in ("check", "build", "deploy"):
        packages = package_dirs(Path(a.packages).resolve(), a.package)
        print("packages: " + ", ".join(x.name for x in packages))
    if a.stage == "check":
        errors = check(packages, a.cyrillic)
        print("\n".join(errors) if errors else "package rules: ok")
        return 1 if errors else 0
    if a.stage == "build":
        build(packages, Path(a.out).resolve())
        return 0
    if a.stage == "register":
        return run(["clio", "reg-web-app", a.env, "-u", a.url, "-l", a.login, "-p", a.password])
    if a.stage == "deploy":
        deploy(packages, a.env, not a.no_restart, not a.no_redis, a.all)
        return 0
    if a.stage == "unit":
        return unit(a)
    return ui(a)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
