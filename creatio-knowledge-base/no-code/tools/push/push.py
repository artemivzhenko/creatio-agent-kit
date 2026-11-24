#!/usr/bin/env python3
"""
Push a package to an environment: clear IsChanged, push-pkg, check compilation, publish, probe.

    python push.py <package> -e <environment>          push and check
    python push.py <package> -e <environment> --probe  also run probes
    python push.py <package> -e <environment> --dry-run print commands only
    python push.py <package> -e <environment> --bin <Terrasoft.WebApp/bin>   compile script tasks against these assemblies
    python push.py verify <package> -e <environment> [<Schema> ...] [--bin ..]  is the site running this code: one line per schema; exit 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from creatio_schemas import Clio  # noqa: E402
from creatio_schemas.cli import resolve_package  # noqa: E402
from creatio_schemas.push import push  # noqa: E402


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


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["verify"]:
        return verify_main(argv[1:])
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
    p.add_argument("--allow-removed", metavar="SCHEMA,...", default="",
                   help="schemas the package lost on purpose (a merge): pushed only when absent from the folder and no site "
                        "row references them")
    p.add_argument("--bin", type=Path, help="Creatio assemblies for the script compile check; default $CREATIO_BIN, then the "
                                            "TestCoreLibPath of the workspace's tests/Directory.Build.props")
    args = p.parse_args(argv)

    try:
        return push(resolve_package(args.package, args.project), args.env, Clio(args.env), args.probe, args.dry_run,
                    project=args.project, tasks=args.tasks, task=args.task, force=args.force, baseline=args.baseline,
                    skip_drift=args.skip_drift, skip_foreign_files=args.skip_foreign_files,
                    skip_sql_dates=args.skip_sql_dates, skip_compile_package=args.skip_compile_package, bin_dir=args.bin,
                    allow_removed=args.allow_removed.split(","))
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
