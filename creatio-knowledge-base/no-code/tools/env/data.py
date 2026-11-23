#!/usr/bin/env python3
"""Test data from a site without typing SQL: a lookup's rows, sample records with their lookups named, a synthetic fixture.

    python data.py lookup-values -e <env> <Lookup> [--limit 50] [--offset 0]
    python data.py sample  -e <env> <Entity> [--filter "\\"UsrAmount\\" > 10"] [--n 3] [--columns "CreatedOn,ModifiedBy"]
    python data.py fixture -e <env> <Entity> [--alias A] [--columns "UsrNotes,UsrStatus"]

`sample` reads records to look at; `fixture` prints a DSL `insert` block of the object's shape with made-up values (a lookup
takes its first row by Name) for a backend case to paste - it writes nothing. Read-only.
Exit 2 on a usage error, a missing table or a refused filter; 1 when the database answers an error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from creatio_schemas.environment import open_environment  # noqa: E402
from creatio_schemas.testdata import lookup_values, make_fixture, sample_records  # noqa: E402


def main(argv=None, **env_kw) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = p.add_subparsers(dest="command", required=True, metavar="command")
    values = commands.add_parser("lookup-values", help="the rows of a lookup ordered by Name")
    values.add_argument("lookup")
    values.add_argument("--limit", type=int, default=50, help="rows shown (0 = all)")
    values.add_argument("--offset", type=int, default=0)
    sample = commands.add_parser("sample", help="records of an object with their lookups named")
    sample.add_argument("entity")
    sample.add_argument("--filter", default="", help="a SQL where fragment (no ';', nothing that writes)")
    sample.add_argument("--n", type=int, default=3, help="records (at most 50)")
    sample.add_argument("--columns", default="", help="system columns to show too (comma list)")
    fixture = commands.add_parser("fixture", help="a synthetic DSL insert block of the object's shape")
    fixture.add_argument("entity")
    fixture.add_argument("--alias", default="A")
    fixture.add_argument("--columns", default="", help="optional columns to set too (comma list)")
    for sub in (values, sample, fixture):
        sub.add_argument("-e", "--env", help="clio environment name")
        sub.add_argument("--project", help="project.json")
    a = p.parse_args(argv)
    try:
        env = open_environment(a.env, a.project, **env_kw)
        if a.command == "lookup-values":
            print(lookup_values(env, a.lookup, max(a.limit, 0), max(a.offset, 0)))
        elif a.command == "sample":
            print(sample_records(env, a.entity, a.filter, a.n, a.columns))
        else:
            print(make_fixture(env, a.entity, a.alias, a.columns))
        return 0
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
