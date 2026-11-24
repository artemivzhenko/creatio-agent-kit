#!/usr/bin/env python3
"""The platform's Freedom UI runtime code of a site (the shell's bundles and webpack chunks), cached per version, searched by regex.

    python shell.py <pattern> -e <env> [--context 2] [--limit 40] [--offset 0]
    python shell.py <pattern> --project project.json

The first call for a site version downloads every bundle and chunk once into ~/.creatio-kit/shell/<host>/<hash>/ (outside
the repositories; a new hash replaces the old folder) and says so; then `<file>:<line>: <text>` per hit, the minified line
cut to 200 characters around the match, with context lines. Read-only GETs; the files are never executed. Exit 1 when
nothing matches, 2 on an error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from creatio_schemas.environment import open_environment  # noqa: E402
from creatio_schemas.shell import shell_source  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pattern", help="a regular expression over the shell's code")
    p.add_argument("-e", "--env", help="clio environment name")
    p.add_argument("--project", help="project.json holding the environment")
    p.add_argument("--context", type=int, default=2, help="lines around each hit (default 2)")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--offset", type=int, default=0)
    args = p.parse_args(argv)
    if not args.env and not args.project:
        p.error("name the site: -e <env> or --project project.json")
    try:
        text = shell_source(open_environment(args.env, args.project), args.pattern, args.context, args.limit, args.offset)
    except (ValueError, KeyError, OSError, RuntimeError) as e:
        print(f"error: {type(e).__name__}: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2
    print(text)
    return 1 if any(line.startswith("0 hit(s)") for line in text.splitlines()[:2]) else 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a minified chunk may hold any character
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
