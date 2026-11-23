#!/usr/bin/env python3
"""clio-ext: the developer's commands around clio, in one Python script (no PowerShell).

    python clio-ext.py init -d <dir> [-e <env>] [-b <branch>]            repo/, backup/, logs/ with a clio workspace each
    python clio-ext.py deploy -d <dir>                                    restorew -> compress -> archive -> pushw (env from clio-ext.config.json)
    python clio-ext.py pull <package|all> -e <env> [-p <packages dir>]    clio pull-pkg one package, or restorew for all
    python clio-ext.py push <package|all> -e <env> [-p <packages dir>]    IsChanged cleared, then push-pkg one package or pushw for all
    python clio-ext.py push-all -e <env> [-p <packages dir>] [--package A,B | --list hierarchy.txt] [--continue-on-error]
                                                                          one package at a time, dependencies first; the failed ones
                                                                          in error-pkg.txt (pass it back with --list to retry them)
    python clio-ext.py hierarchy [-p <packages dir>] [--out hierarchy.txt] [--report package-hierarchy.txt]
                                                                          the install order and a dependency report from descriptor.json
    python clio-ext.py find-missing-loc -p <packages dir> [-l uk-UA]      schemas without resource.<locale>.xml
    python clio-ext.py validate-processes -p <packages dir> [-k <pkg>]    Read Data elements that read every column
    python clio-ext.py deploy-oauth --creatio-root <dir> --identity-service-zip <zip> [...]   the OAuth 2.0 Identity Service

<packages dir> defaults to ./packages. IsChanged is cleared in SysSchema, SysPackageSchemaData and SysPackageSqlScript
before every push (designer-edited schemas otherwise count as modified locally and push-pkg skips them); --keep-ischanged
leaves it. Every command exits non-zero on a failure.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from importlib import import_module
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))            # clio-ext-lib
sys.path.insert(0, str(HERE.parent))     # pipeline.py: the package order, the IsChanged rule
import pipeline  # noqa: E402


# --- logging (logs/<date>.log next to the work, one line per step) -----------------------------------------------

def _log(logs_dir: Path | None, line: str) -> None:
    print(line, flush=True)
    if logs_dir:
        logs_dir.mkdir(parents=True, exist_ok=True)
        with (logs_dir / f"{datetime.now():%Y-%m-%d}.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def run(logs_dir: Path | None, operation: str, cmd: list[str], cwd: Path | None = None, stop: bool = True) -> int:
    """One step: `[!] started`, `[+] ok` or `[-] failed <tail>`; exits on a failure unless stop is False."""
    _log(logs_dir, f"[!] {operation}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        tail = (result.stderr or result.stdout).strip().splitlines()[-5:]
        _log(logs_dir, f"[-] {operation}: exit {result.returncode}\n    " + "\n    ".join(tail))
        if stop:
            sys.exit(1)
        return result.returncode
    _log(logs_dir, f"[+] {operation}")
    return 0


def read_config(dir_path: Path) -> dict:
    path = dir_path / "clio-ext.config.json"
    if not path.is_file():
        sys.exit(f"config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def packages_dir(given: str | None) -> Path:
    root = Path(given or "packages").resolve()
    if not root.is_dir():
        sys.exit(f"packages folder not found: {root}")
    return root


# --- init / deploy (a working directory with a backup workspace and the repository workspace) ---------------------

def cmd_init(a) -> int:
    dir_path = Path(a.dir).resolve()
    if not dir_path.is_dir():
        sys.exit(f"directory does not exist: {dir_path}")
    logs = dir_path / "logs"
    _log(logs, f"=== init {datetime.now().isoformat()} ===")
    for name in ("repo", "backup"):
        folder = dir_path / name
        if not folder.exists():
            folder.mkdir()
            run(logs, f"clio createw in {name}", ["clio", "createw"], cwd=folder)
    config = dir_path / "clio-ext.config.json"
    data = json.loads(config.read_text(encoding="utf-8-sig")) if config.is_file() else {"environment": "", "branch": ""}
    data["environment"] = a.env or data.get("environment", "")
    data["branch"] = a.branch or data.get("branch", "")
    config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _log(logs, f"[+] {config.name}: environment={data['environment']!r} branch={data['branch']!r}")
    return 0


def cmd_deploy(a) -> int:
    dir_path = Path(a.dir).resolve()
    logs = dir_path / "logs"
    env = read_config(dir_path).get("environment", "").strip()
    if not env:
        sys.exit("'environment' is empty in clio-ext.config.json")
    _log(logs, f"=== deploy {datetime.now().isoformat()} ===")
    backup, repo = dir_path / "backup", dir_path / "repo"
    run(logs, f"clio restorew -e {env} (backup of the site's packages)", ["clio", "restorew", "-e", env], cwd=backup)
    pkgs = backup / "packages"
    folders = [p for p in pkgs.iterdir() if p.is_dir()] if pkgs.is_dir() else []
    if not folders:
        sys.exit("no package folders in backup/packages after restorew")
    for p in folders:
        run(logs, f"clio compress {p.name}", ["clio", "compress", p.name], cwd=pkgs)
    archive = backup / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    archive.mkdir()
    for gz in pkgs.glob("*.gz"):
        shutil.move(str(gz), archive / gz.name)
    _log(logs, f"[+] backup archived to {archive}")
    if not a.keep_ischanged:
        pipeline.clear_ischanged(env)
    run(logs, f"clio pushw -e {env}", ["clio", "pushw", "-e", env], cwd=repo)
    return 0


# --- pull / push / push-all --------------------------------------------------------------------------------------

def cmd_pull(a) -> int:
    root = packages_dir(a.packages)
    if a.package == "all":
        return run(None, f"clio restorew -e {a.env}", ["clio", "restorew", "-e", a.env], cwd=root.parent)
    before = pipeline.archives(root)
    run(None, f"clio pull-pkg {a.package}", ["clio", "pull-pkg", a.package, "-e", a.env], cwd=root)
    gz = pipeline.pulled_gz(root, a.package, before)
    if gz is None:
        sys.exit(f"clio pull-pkg {a.package} wrote no package archive into {root}")
    # into an empty folder: over an existing one extract-pkg-zip asks on the console, which a runner does not have
    scratch = Path(tempfile.mkdtemp(prefix=".pull-", dir=root))
    try:
        run(None, f"clio extract-pkg-zip {gz.name}", ["clio", "extract-pkg-zip", str(gz), "-d", str(scratch)], cwd=root)
        # the site's files over the working copy's; a file the site no longer has stays (git shows it)
        shutil.copytree(scratch / a.package, root / a.package, dirs_exist_ok=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        gz.unlink(missing_ok=True)
    return 0


def cmd_push(a) -> int:
    root = packages_dir(a.packages)
    if not a.keep_ischanged:
        pipeline.clear_ischanged(a.env)
    if a.package == "all":
        return run(None, f"clio pushw -e {a.env}", ["clio", "pushw", "-e", a.env], cwd=root.parent)
    if not (root / a.package).is_dir():
        sys.exit(f"no folder {a.package} under {root}")
    return run(None, f"clio push-pkg {a.package}", ["clio", "push-pkg", a.package, "-e", a.env], cwd=root)


def read_list(path: Path) -> list[str]:
    """One package name per line; blank lines and # comments skipped; a duplicate kept once."""
    if not path.is_file():
        sys.exit(f"package list not found: {path} (clio-ext.py hierarchy writes one)")
    names = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in names:
            names.append(line)
    if not names:
        sys.exit(f"no package names in {path}")
    return names


def cmd_push_all(a) -> int:
    root = packages_dir(a.packages)
    logs = root.parent / "logs"
    if a.list:
        names = read_list(Path(a.list))
    else:
        names = [p.name for p in pipeline.package_dirs(root, a.package)]
    _log(logs, f"=== push-all -e {a.env}: {len(names)} packages {'(continue on error)' if a.continue_on_error else '(stop at the first failure)'} ===")
    if not a.keep_ischanged:
        pipeline.clear_ischanged(a.env)
    pushed, failed, skipped = [], [], []
    for i, name in enumerate(names, 1):
        if not (root / name).is_dir():
            _log(logs, f"[{i}/{len(names)}] {name}: no folder, skipped")
            skipped.append(name)
            continue
        code = run(logs, f"[{i}/{len(names)}] clio push-pkg {name}", ["clio", "push-pkg", name, "-e", a.env], cwd=root, stop=False)
        (failed if code else pushed).append(name)
        if code and not a.continue_on_error:
            break
    errors = root.parent / "error-pkg.txt"
    if failed:
        errors.write_text("# packages that failed to push; pass this file back with --list to retry them\n" + "\n".join(failed) + "\n", encoding="utf-8")
    elif errors.is_file():
        errors.unlink()
    rest = names[len(pushed) + len(failed) + len(skipped):]
    _log(logs, f"pushed {len(pushed)}, failed {len(failed)}, skipped {len(skipped)}, not reached {len(rest)}"
         + (f"; the failed ones are in {errors}" if failed else ""))
    return 1 if failed else 0


# --- hierarchy -----------------------------------------------------------------------------------------------------

def graph(root: Path) -> dict:
    """deps, external, level (longest chain below), dependents and descriptor problems of every package folder."""
    found = {p.name: p for p in root.iterdir() if p.is_dir() and (p / "descriptor.json").is_file()}
    order = pipeline.dependency_order(found)  # exits on a cycle or a descriptor that is not JSON, one line each
    deps, external, problems = {}, {}, []
    for name, folder in found.items():
        d = pipeline.read_json(folder / "descriptor.json").get("Descriptor", {})
        if d.get("Name") != name:
            problems.append(f"{name}: descriptor Name is {d.get('Name')!r}")
        if d.get("ProjectPath") not in (None, f"Files/{name}.csproj"):
            problems.append(f"{name}: ProjectPath is {d.get('ProjectPath')!r}")
        elif d.get("Type") == 1 and not d.get("ProjectPath"):
            # seen on 8.2.3: compile --all writes the package's csproj to Pkg/<Name> as a file, then cannot create the folder
            problems.append(f"{name}: Type 1 without ProjectPath (expected Files/{name}.csproj)")
        names = [x.get("Name") for x in d.get("DependsOn", [])]
        deps[name] = sorted(n for n in names if n in found)
        external[name] = sorted(n for n in names if n not in found)
    level = {}
    for name in order:
        level[name] = 1 + max((level[d] for d in deps[name]), default=-1)
    dependents = {n: sorted(m for m in found if n in deps[m]) for n in found}
    return {"order": order, "deps": deps, "external": external, "level": level, "dependents": dependents, "problems": problems}


def cmd_hierarchy(a) -> int:
    root = packages_dir(a.packages)
    g = graph(root)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = Path(a.out or root.parent / "hierarchy.txt")
    lines = [f"# Generated by clio-ext.py hierarchy on {stamp}: the packages of {root}, ordered by their descriptor.json",
             "# dependencies - every package comes after everything it depends on. One name per line; # lines are ignored."]
    current = -1
    for name in g["order"]:
        if g["level"][name] != current:
            current = g["level"][name]
            lines += ["", f"# --- level {current} ---"]
        lines.append(name)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(g['order'])} packages (levels 0..{max(g['level'].values())}) to {out}")
    if a.report:
        rep = Path(a.report)
        text = [f"PACKAGE HIERARCHY ({len(g['order'])} packages in {root}), generated {stamp}", "",
                "level 0 depends on nothing inside the folder; each next level only on levels above it.", ""]
        for lv in range(max(g["level"].values()) + 1):
            at = [n for n in g["order"] if g["level"][n] == lv]
            text.append(f"--- level {lv} ({len(at)}) ---")
            for n in at:
                text.append(f"  {n:<46} <- {', '.join(g['deps'][n]) or '-'}"
                            + (f"   [outside: {', '.join(g['external'][n])}]" if g["external"][n] else "")
                            + (f"   [used by: {', '.join(g['dependents'][n])}]" if g["dependents"][n] else ""))
            text.append("")
        if g["problems"]:
            text += ["PROBLEMS"] + [f"  {p}" for p in g["problems"]]
        rep.write_text("\n".join(text) + "\n", encoding="utf-8")
        print(f"report: {rep}" + (f" ({len(g['problems'])} problems)" if g["problems"] else ""))
    return 0


# --- the lib commands (clio-ext-lib/) ---------------------------------------------------------------------------------

def cmd_find_missing_loc(a) -> int:
    return import_module("clio-ext-lib.find_missing_loc").run(packages_path=a.packages, locale=a.locale)


def cmd_validate_processes(a) -> int:
    return import_module("clio-ext-lib.validate_processes").run(packages_path=a.packages, package=a.package)


OAUTH_OVERRIDES = ["identity_service_dir", "identity_service_port", "identity_service_https_port", "service_name", "app_pool_name",
                   "site_name", "db_connection_string", "client_id", "client_name", "client_secret", "cert_password", "cert_valid_days",
                   "cert_output_path", "cert_subject_name", "cert_file_name", "cert_legacy_name", "creatio_base_url", "enable_logging",
                   "creatio_https_port", "creatio_host_header", "skip_creatio_https", "normalize_conn_string", "log_path", "rebind_ports"]


def cmd_deploy_oauth(a) -> int:
    overrides = {k: getattr(a, k) for k in OAUTH_OVERRIDES if getattr(a, k, None) is not None}
    return import_module("clio-ext-lib.deploy_oauth").run(
        creatio_root=a.creatio_root, identity_service_zip=a.identity_service_zip, what_if=a.what_if, force=a.force,
        rollback=a.rollback, reset_client=a.reset_client, enable_https=a.enable_https, config_path=a.config_path or "", **overrides)


# --- entry point ---------------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def packages_arg(s):
        s.add_argument("-p", "--packages", help="the packages folder (default ./packages)")

    s = sub.add_parser("init"); s.add_argument("-d", "--dir", required=True); s.add_argument("-e", "--env", default=""); s.add_argument("-b", "--branch", default=""); s.set_defaults(func=cmd_init)
    s = sub.add_parser("deploy"); s.add_argument("-d", "--dir", required=True); s.add_argument("--keep-ischanged", action="store_true"); s.set_defaults(func=cmd_deploy)
    s = sub.add_parser("pull"); s.add_argument("package", help="a package name or all"); s.add_argument("-e", "--env", required=True); packages_arg(s); s.set_defaults(func=cmd_pull)
    s = sub.add_parser("push"); s.add_argument("package", help="a package name or all"); s.add_argument("-e", "--env", required=True); packages_arg(s); s.add_argument("--keep-ischanged", action="store_true"); s.set_defaults(func=cmd_push)
    s = sub.add_parser("push-all"); s.add_argument("-e", "--env", required=True); packages_arg(s)
    s.add_argument("--package", help="comma-separated names in this order"); s.add_argument("--list", help="a file with one package name per line (hierarchy.txt, error-pkg.txt)")
    s.add_argument("--continue-on-error", action="store_true"); s.add_argument("--keep-ischanged", action="store_true"); s.set_defaults(func=cmd_push_all)
    s = sub.add_parser("hierarchy"); packages_arg(s); s.add_argument("--out", help="the list file (default <packages>/../hierarchy.txt)"); s.add_argument("--report", help="also write the dependency report here"); s.set_defaults(func=cmd_hierarchy)
    s = sub.add_parser("find-missing-loc"); s.add_argument("-p", "--packages", required=True); s.add_argument("-l", "--locale", default="uk-UA"); s.set_defaults(func=cmd_find_missing_loc)
    s = sub.add_parser("validate-processes"); s.add_argument("-p", "--packages", required=True); s.add_argument("-k", "--package"); s.set_defaults(func=cmd_validate_processes)
    s = sub.add_parser("deploy-oauth")
    s.add_argument("--creatio-root", required=True); s.add_argument("--identity-service-zip", required=True)
    bools = {"enable_logging", "skip_creatio_https", "normalize_conn_string", "rebind_ports"}
    for key in OAUTH_OVERRIDES:
        kind = int if key.endswith(("_port", "_days")) else (lambda v: v.lower() != "false") if key in bools else str
        s.add_argument("--" + key.replace("_", "-"), default=None, type=kind)
    s.add_argument("--enable-https", type=lambda v: v.lower() != "false", default=True); s.add_argument("--config-path", default=None)
    for flag in ("what-if", "force", "rollback", "reset-client"):
        s.add_argument("--" + flag, action="store_true")
    s.set_defaults(func=cmd_deploy_oauth)

    a = p.parse_args(argv)
    return a.func(a) or 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
