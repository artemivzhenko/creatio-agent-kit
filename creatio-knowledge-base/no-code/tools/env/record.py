#!/usr/bin/env python3
"""Find which table holds an Id, and show a record with its lookups named and the rows that point at it.

    python record.py find    -e <env> <id> [--workspace <folder>] [--everywhere]
    python record.py context -e <env> <Entity> <id> [--columns "Name,*Id"] [--depth 1|2]
    python record.py history -e <env> <Entity>:<id> [--column UsrStatus] [--clusters 500]
    python record.py transitions -e <env> <Entity>.<Column> [--from "A"] [--to "B"] [--since 2026-11-01] [--out file.csv]
    python record.py merge   -e <env> <Object> --keep <Id> --drop <Id>[,<Id>..] [--apply --project project.json] [--backup <folder>]

`find` scans the base tables that have a uuid `Id` (the workspace's objects first) in unions of 50 and stops at the first
batch that holds the Id; `--everywhere` goes on. Times are UTC and the zone `environment.timeZone` of --project names.
`history` reads the change log of the object (`Sys<Entity>Log`, one snapshot row per change): when, who, `was -> became` per
column; `--clusters <ms>` adds the other records the same user changed within that many milliseconds of each change.
`transitions` lists every change of one column over all records, oldest first; `--out` writes a CSV (UTF-8 with a BOM, `;`).
`merge` folds duplicate rows of a lookup into one: the plan (read only, the default) lists every table and column that points at the dropped
ids with counts and the SQL; `--apply` (a dev site only: `--project` with `kind: dev`, `mayBreak: true`) writes a backup first, then runs it.
Without the log table: `change tracking is off for <Entity>` (exit 2).
Exit 1 when nothing is found; 2 on a usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from creatio_schemas.environment import open_environment  # noqa: E402
from creatio_schemas.records import (column_transitions, find_record, merge_apply, merge_plan, record_context, record_history, render_context,  # noqa: E402
                                     render_hits, render_history, render_plan, render_transitions, require_dev, transitions_csv, zone_of)


def objects_of(workspace: str | None) -> list[str]:
    """The entity names of a workspace's packages (a table is named like its object)."""
    if not workspace:
        return []
    from creatio_schemas.workspace import Workspace
    root = Path(workspace)
    anchor = next(iter(sorted((root / "packages").glob("*") if (root / "packages").is_dir() else root.glob("*"))), None)
    return [s["name"] for s in Workspace(anchor).schemas if s["manager"] == "EntitySchemaManager"] if anchor else []


def workspace_of(project: str | None) -> str | None:
    """`paths.workspace` of a project.json, relative to the file's folder."""
    if not project:
        return None
    import json
    with open(project, encoding="utf-8-sig") as f:
        path = (json.load(f).get("paths") or {}).get("workspace")
    return str((Path(project).resolve().parent / path)) if path else None


def main(argv=None, **env_kw) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = p.add_subparsers(dest="command", required=True, metavar="command")
    find = commands.add_parser("find", help="the table(s) that hold an Id, with caption, dates and authors")
    find.add_argument("id")
    find.add_argument("--workspace", help="a workspace folder: its objects are scanned first (default: project.json paths.workspace)")
    find.add_argument("--everywhere", action="store_true", help="scan every batch, not only up to the first hit")
    context = commands.add_parser("context", help="a record with its lookups named and the rows that point at it")
    context.add_argument("entity")
    context.add_argument("id")
    context.add_argument("--columns", default="", help="comma list, * wildcards (default: every column with a value)")
    context.add_argument("--depth", type=int, default=1, choices=(0, 1, 2), help="0 the record only, 1 + the rows pointing at it, 2 + their lookups named")
    history = commands.add_parser("history", help="the change log of a record: when, who, was -> became")
    history.add_argument("record", help="<Entity>:<Id>")
    history.add_argument("--column", default="", help="only the changes of this column")
    history.add_argument("--clusters", type=int, default=0, metavar="MS", help="the other records the same user changed within MS ms of each change")
    transitions = commands.add_parser("transitions", help="every change of one column of an object, from its change log")
    transitions.add_argument("target", help="<Entity>.<Column>")
    transitions.add_argument("--from", dest="from_value", help="only transitions from this value")
    transitions.add_argument("--to", dest="to_value", help="only transitions to this value")
    transitions.add_argument("--since", help="only changes at or after (2026-11-01, 2026-11-01T08:00, UTC)")
    transitions.add_argument("--out", help="write every transition to this CSV file")
    transitions.add_argument("--limit", type=int, default=40, help="lines shown (0 = all)")
    merge = commands.add_parser("merge", help="duplicate rows of a lookup folded into one: foreign keys moved, backup, delete (a plan unless --apply)")
    merge.add_argument("entity")
    merge.add_argument("--keep", required=True, help="the Id that stays")
    merge.add_argument("--drop", required=True, help="the Ids that go, comma separated")
    merge.add_argument("--apply", action="store_true", help="write (dev site only: needs --project with kind dev and mayBreak)")
    merge.add_argument("--backup", default="merge-backups", help="folder of the backup file written before the first write")
    for sub in (find, context, history, transitions, merge):
        sub.add_argument("-e", "--env", help="clio environment name")
        sub.add_argument("--project", help="project.json")
    a = p.parse_args(argv)
    try:
        env, zone = open_environment(a.env, a.project, **env_kw), zone_of(a.project)
        if a.command == "merge":
            if a.apply:
                require_dev(a.project)
            plan = merge_plan(env, a.entity, a.keep, [d.strip() for d in a.drop.split(",") if d.strip()])
            print(render_plan(plan))
            if a.apply:
                merge_apply(env, plan, a.backup)
            return 0
        if a.command == "find":
            workspace = a.workspace or workspace_of(a.project)
            hits = find_record(env, a.id, objects_of(workspace), a.everywhere, zone)
            print(render_hits(hits))
            return 0 if hits else 1
        if a.command == "history":
            answer = record_history(env, a.record, a.column, a.clusters, zone)
            answer["column"] = a.column
            print(render_history(answer))
            return 0 if answer["changes"] else 1
        if a.command == "transitions":
            answer = column_transitions(env, a.target, a.from_value, a.to_value, a.since, zone)
            print(render_transitions(answer, a.limit or len(answer["rows"]) or 1))
            if a.out:
                print(f"{len(answer['rows'])} rows -> {transitions_csv(answer, a.out)}")
            return 0 if answer["rows"] else 1
        print(render_context(record_context(env, a.entity, a.id, a.columns, a.depth, zone)))
        return 0
    except (ValueError, KeyError, FileNotFoundError, RuntimeError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
