#!/usr/bin/env python3
"""
Push a package to an environment: clear IsChanged, push-pkg, check compilation, publish, probe.

    python push.py <package> -e <environment>          push and check
    python push.py <package> -e <environment> --probe  also run probes
    python push.py <package> -e <environment> --dry-run print commands only
    python push.py <package> -e <environment> --bin <Terrasoft.WebApp/bin>   compile script tasks against these assemblies
    python push.py <package> -e <environment> --build [--project <project.json>]  first build Files/Bin/<Pkg>.dll against the site version's bin
    python push.py verify <package> -e <environment> [<Schema> ...] [--bin ..]  is the site running this code: one line per schema; exit 1
    python push.py served <Schema> -e <environment> [--out <file>] [--grep <text>]  the served conf/content text: size, md5, matching lines
    python push.py page <package> <Page> -e <environment> [--dry-run] [--force]  one Freedom UI page over clio update-page, then verify
    python push.py deps <package> -e <environment> [--add <Package>[,<Package>]] [--dry-run]  fill DependsOn UId/version from the site's SysPackage
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from creatio_schemas import Clio  # noqa: E402
from creatio_schemas.cli import resolve_package  # noqa: E402
from creatio_schemas.push import details_path, fill_dependencies, push, resolve_task  # noqa: E402


def verify_main(argv: list[str]) -> int:
    from creatio_schemas.environment import open_environment
    from creatio_schemas.verify import render, verify

    p = argparse.ArgumentParser(prog="push.py verify", description="Is the site running the pushed code: per schema the site's metadata "
                                "and body against the working copy, a script process's generated source and its compile, a client "
                                "schema's served content. Read-only; exit 1 on any difference.")
    p.add_argument("package")
    p.add_argument("schemas", nargs="*", help="only these schemas (default: every schema of the package)")
    p.add_argument("-e", "--env", required=True, help="clio environment name")
    p.add_argument("--project", type=Path)
    p.add_argument("--bin", type=Path, help="Creatio assemblies for the script compile check (as for the push)")
    args = p.parse_args(argv)
    try:
        results = verify(resolve_package(args.package, args.project), open_environment(args.env), args.schemas or None, args.bin)
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2
    print(render(results))
    return 1 if any(not s.startswith("same") for _, s in results) else 0


def served_main(argv: list[str]) -> int:
    import hashlib

    from creatio_schemas.environment import open_environment
    from creatio_schemas.verify import served

    p = argparse.ArgumentParser(prog="push.py served", description="The text the site serves at conf/content/<Schema>.js (the composed "
                                "body of every layer): its size and md5, saved with --out, the lines holding --grep. Read-only; exit 1 when the site serves no such file.")
    p.add_argument("schema")
    p.add_argument("-e", "--env", required=True, help="clio environment name")
    p.add_argument("--project", type=Path)
    p.add_argument("--out", type=Path, help="save the served text here")
    p.add_argument("--grep", help="print the lines holding this text (case-insensitive), with their numbers")
    args = p.parse_args(argv)
    try:
        text = served(open_environment(args.env, args.project), args.schema)
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2
    if text is None:
        print(f"{args.schema}: not served: conf/content has no such file (a schema's `<Schema>Resources` module is not a file of its own: check SysLocalizableValue)")
        return 1
    print(f"{args.schema}: {len(text.encode('utf-8'))} bytes, md5 {hashlib.md5(text.encode('utf-8')).hexdigest()}")
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="")
        print(f"saved to {args.out}")
    for n, line in enumerate(text.splitlines(), 1):
        if args.grep and args.grep.lower() in line.lower():
            print(f"{n}: {line.strip()[:240]}")
    return 0


def deps_main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="push.py deps", description="Fill the package descriptor's DependsOn from the site: an entry with "
                                "an empty UId or PackageVersion, and every --add package not listed yet, get UId and version from "
                                "SysPackage. One line per entry; exit 1 when a name is not on the site.")
    p.add_argument("package")
    p.add_argument("-e", "--env", required=True, help="clio environment name")
    p.add_argument("--add", default="", help="package name(s) to add to DependsOn, comma separated")
    p.add_argument("--project", type=Path)
    p.add_argument("--dry-run", action="store_true", help="print the entries, write nothing")
    args = p.parse_args(argv)
    try:
        lines, found = fill_dependencies(resolve_package(args.package, args.project), Clio(args.env).execute_sql_rows,
                                         [n.strip() for n in args.add.split(",") if n.strip()], args.dry_run)
    except (FileNotFoundError, KeyError, ValueError, RuntimeError, OSError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0 if found else 1


def page_main(argv: list[str]) -> int:
    from creatio_schemas.environment import open_environment
    from creatio_schemas.push_page import push_page
    from creatio_schemas.verify import verify

    p = argparse.ArgumentParser(prog="push.py page", description="One Freedom UI page of a package to the site with clio update-page "
                                "(replace, into this package, against the checksum get-page reads first), then verify of that schema. "
                                "No package install: the package's bindings, processes and other schemas are not touched.")
    p.add_argument("package")
    p.add_argument("page", help="the page schema name (a folder Schemas/<Page>/ with <Page>.js)")
    p.add_argument("-e", "--env", required=True, help="clio environment name")
    p.add_argument("--project", type=Path)
    p.add_argument("--dry-run", action="store_true", help="update-page --dry-run: validate, save nothing, no verify")
    p.add_argument("--force", action="store_true", help="overwrite a site copy changed since get-page (no checksum)")
    args = p.parse_args(argv)
    try:
        package = resolve_package(args.package, args.project)
        env = None if args.dry_run else open_environment(args.env)
        lines, code = push_page(package, args.page, args.env, Clio(args.env), lambda pkg, names: verify(pkg, env, names),
                                dry_run=args.dry_run, force=args.force)
    except (FileNotFoundError, KeyError, ValueError, RuntimeError, OSError) as e:
        print(f"error: {type(e).__name__}: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2
    print("\n".join(lines + [f"exit code {code}"]))
    return code


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["verify"]:
        return verify_main(argv[1:])
    if argv[:1] == ["served"]:
        return served_main(argv[1:])
    if argv[:1] == ["deps"]:
        return deps_main(argv[1:])
    if argv[:1] == ["page"]:
        return page_main(argv[1:])
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("package", help="path to the package folder, or its name (packages/<name> here or next to --project)")
    p.add_argument("-e", "--env", required=True, help="clio environment name")
    p.add_argument("--probe", action="store_true", help="run probes for each schema")
    p.add_argument("--dry-run", action="store_true", help="print commands without executing")
    p.add_argument("--project", type=Path, help="project.json containing paths.tasks")
    p.add_argument("--tasks", type=Path, help="folder containing task folders")
    p.add_argument("--task", type=Path, help="current task folder")
    p.add_argument("--force", action="store_true", help="allow environment drift")
    p.add_argument("--baseline", type=Path, help="file of accepted compilation error lines")
    p.add_argument("--skip-drift", action="store_true", help="skip the environment drift check")
    p.add_argument("--skip-foreign-files", action="store_true", help="skip the task ownership check")
    p.add_argument("--skip-sql-dates", action="store_true", help="do not stamp changed SQL descriptors")
    p.add_argument("--skip-compile-package", action="store_true", help="skip the assembly package build")
    p.add_argument("--skip-stale-bin", action="store_true",
                   help="push an assembly package whose Files/Bin/<Pkg>.dll is older than Files/cs, on purpose")
    p.add_argument("--allow-removed", metavar="SCHEMA,...", default="",
                   help="schemas the package lost on purpose (a merge): pushed only when absent from the folder and no site "
                        "row references them")
    p.add_argument("--bin", type=Path, help="Creatio assemblies for the script compile check; default $CREATIO_BIN, then the "
                                            "TestCoreLibPath of the workspace's tests/Directory.Build.props")
    p.add_argument("--build", action="store_true", help="before the stale-bin step build Files/Bin/<Pkg>.dll (dotnet build, Release, "
                   "net472) against the site version's binaries: --bin, else paths.platformBin of --project; the bin's "
                   "Terrasoft.Core.dll version must match the project's environment.platformVersion")
    args = p.parse_args(argv)

    try:
        package, task = resolve_package(args.package, args.project), resolve_task(args.task, args.tasks, args.project)
        # the whole log (a cut clio failure in full) goes to a file; the screen keeps the summary and `details: <file>`
        details = {} if args.dry_run else {"details": details_path(package, task)}
        return push(package, args.env, Clio(args.env), args.probe, args.dry_run, **details,
                    project=args.project, tasks=args.tasks, task=task, force=args.force, baseline=args.baseline,
                    skip_drift=args.skip_drift, skip_foreign_files=args.skip_foreign_files,
                    skip_sql_dates=args.skip_sql_dates, skip_compile_package=args.skip_compile_package, bin_dir=args.bin,
                    allow_removed=args.allow_removed.split(","), skip_stale_bin=args.skip_stale_bin, build=args.build)
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
