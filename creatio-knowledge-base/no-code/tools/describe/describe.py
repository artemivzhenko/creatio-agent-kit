#!/usr/bin/env python3
"""What a package holds, what a schema is, one part of it - without reading the files (library: ../creatio_schemas/describe).

    python describe.py package <package> [--kind object|process|rules|page|sql|client|addon|source|csharp|dcm|user-task]
    python describe.py schema  <package> <Schema>
    python describe.py item    <package> <Schema> "<topic> [<name>] [key=value ...]"
    python describe.py item    <package> <Schema> topics                 # what this schema can answer
    python describe.py index   <workspace|package> [--rebuild] [--stats] [-e <env>]  # build/refresh the index (.creatio-index/index.sqlite); -e: the site's extra columns and schemas
    python describe.py find    <workspace|package> <Schema>              # package, files, refers to, used by
    python describe.py find-text <workspace|package> <regex> [--kind page|object|...|resource] [--context 1] [--limit N]  # a regex over the indexed files

Topics: every schema - files, resources [culture=], resource <key>, missing [culture=] [from=];
  object  - columns [type= flag= own=true], column <name>, flags, base
  process - elements [kind=], element <name>, params [direction=], flows [from= to=], script <element>
  rules   - rules [enabled=], rule <name>
  sql     - body, deps
  dcm     - stages, stage <name>, steps [stage=], step <name>, moves [from= to=], filter [raw=true]
  user-task - params [direction=], param <name>, methods, method <name>, source
  data (a Data/<Name> binding) - columns, rows [limit=] [culture=], row <key>; `package <pkg> --kind data` lists them
  classic (7.x client schema) - diff [op=] [parent=], element <name>, methods, method <name>, messages, attributes, details, mixins, find <text>,
            where [<name>], map [tab=], method <name> [env=] (every layer), callers <method>, outline
  C# (a source code schema, or Files/cs/X.cs by path, file name or stem) - classes [role=] [kind=] [generated=true],
            members [<Type>] [kind=method|property|field|const] [visibility=public], member <Type.Name>, usings, regions,
            operations [kind=], find <text>
  page    - sections, elements [type= parent=], element <name>, attributes [bound=true], attribute <name>,
            data-sources, handlers, handler <request>, validators, converters, containers, find <text>
    python describe.py lookups <workspace|package>                      # every lookup object: parent chain, bindings, users
    python describe.py deps    <workspace|package> <Schema> [--in|--out] [--kind object] [--via lookup]  # typed graph
    python describe.py impact  <workspace|package> <Schema>... [--tasks <folder>] [--current <task>] [--md]  # dependents + locks
    python describe.py layers  <Schema> -e <env> [--rule <UId>] [--json]  # the SysSchema copies on an environment, Custom detected
    python describe.py snapshot <Schema> [--workspace <ws>] [-e <env>] [--columns a,b] [--out <file>]  # an object as lines: effective columns on disk; table, rows, checksums, copies on a site
    python describe.py compare <before> <after>                    # two snapshot files: + - ~ lines; exit 1 on a difference
    python describe.py merge-plan <workspace> [<Schema>...] [-e <env>]  # collapsing replacing layers into one: target, conflicts; exit 1 on a conflict
    python describe.py merge   <workspace> <Object> [--target <pkg>] [-e <env>] [--apply]  # the object's layers as one layer of the target; exit 1 when it stops
    python describe.py merge-package <workspace> <child> --into <parent> [-e <env>] [--apply]  # a child package folded into its parent
    python describe.py resolve <workspace|package> "<text>" [--kind object|column|element|parameter|lookup] [--culture all|<c>]  # the workspace by caption or name
    python describe.py who-sets <workspace|package> "<Entity>.<Column> [= <value>]"  # every place that writes the column: processes, C#, pages, SQL scripts
    python describe.py who-reads-message <workspace|package> "<sender>"  # the publishers and subscribers of a message
    python describe.py merge-run <workspace> <child> --into <parent> -e <env> --evidence <folder> [--apply] [--continue]  # the whole procedure, tests before and after
    python describe.py export  <workspace|package> [--out <folder>]    # a text file per schema and per package (default <workspace>/.creatio-export)
    python describe.py diff    <package> [<Schema>...] [--against HEAD|<rev>|<folder>|env:<env>]  # what changed, in schema terms: + - ~ lines
    python describe.py review  <package> [--keep <Schema>...] [--apply]   # a pulled package sorted: line endings only, content, deps, orphans
    python describe.py precommit <workspace>                       # staged files that must not be committed (size, archives, binaries); exit 1
    python describe.py uid     <workspace|package> <uid | Schema.Column | Process.Element[.Param] | "<text with UIds>">  # what a UId names, and back

The same calls are MCP tools of the creatio-kb server (describe_package, describe_schema, describe_item, index_workspace, find_schema, list_lookups).
The index checks itself against the disk on every call: after `clio pull-pkg` the next call sees the new schemas.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from creatio_schemas.describe import DEFAULT_LIMIT, QueryError, describe_item, describe_package, describe_schema, find_schema, index_workspace, lookups  # noqa: E402


def layers_command(args) -> int:
    import json

    from creatio_schemas.describe.layers import CUSTOM_LAYER, render, schema_layers, to_json
    from creatio_schemas.environment import open_environment
    try:
        custom = args.custom_layer
        if not custom and args.project:
            custom = json.loads(Path(args.project).read_text(encoding="utf-8-sig")).get("environment", {}).get("customLayer")
        env = open_environment(args.env, args.project)
        result = schema_layers(env, args.schema, args.rule, custom or CUSTOM_LAYER, args.workspace)
    except (ValueError, KeyError, FileNotFoundError, RuntimeError) as e:
        print(f"error: {_message(e)}", file=sys.stderr)
        return 2
    print(to_json(result) if args.json else render(result, env.clio_name or env.url))
    return 1 if result["custom"] else 0


def snapshot_command(args) -> int:
    from creatio_schemas.environment import open_environment
    from creatio_schemas.integrity import compare, snapshot
    try:
        if args.command == "compare":
            diff = compare(Path(args.before).read_text(encoding="utf-8").splitlines(), Path(args.after).read_text(encoding="utf-8").splitlines(),
                           args.ignore_layers)
            print("\n".join(diff) if diff else "same")
            return 1 if diff else 0
        if not args.workspace and not (args.env or args.project) and not args.page_file:
            raise ValueError("give --workspace (the disk lines), -e / --project (the site lines), or both")
        env = open_environment(args.env, args.project) if args.env or args.project else None
        lines = snapshot(args.workspace, args.schema, env, [c.strip() for c in args.columns.split(",") if c.strip()] or None,
                         page_file=args.page_file)
    except (ValueError, KeyError, OSError, RuntimeError) as e:
        print(f"error: {_message(e)}", file=sys.stderr)
        return 2
    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


def _message(e: Exception) -> str:
    """The error's text; a bare key or index (`KeyError(2)`) names its type, so `error: 2` never happens."""
    if e.args and isinstance(e.args[0], str) and e.args[0]:
        return e.args[0]
    return f"{type(e).__name__}: {e}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("package", help="one line per schema")
    a.add_argument("package")
    a.add_argument("--kind", default="")
    a.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    a.add_argument("--offset", type=int, default=0, help="skip this many lines first (the tail of a cut answer says what to pass)")
    b = sub.add_parser("schema", help="the summary of one schema")
    b.add_argument("package")
    b.add_argument("schema")
    b.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="lines to show (0 = all); the rest is one '... N more' line")
    b.add_argument("--offset", type=int, default=0, help="skip this many lines first")
    b.add_argument("--env", "-e", default=None, help="a process: name the lookup rows of its filters and set values that no data binding holds, from this clio environment (read-only)")
    c = sub.add_parser("item", help="one part of a schema")
    c.add_argument("package")
    c.add_argument("schema")
    c.add_argument("query", nargs="?", default="topics")
    d = sub.add_parser("index", help="build or refresh the package index")
    d.add_argument("path")
    d.add_argument("--rebuild", action="store_true")
    d.add_argument("--stats", action="store_true", help="also the store: size, format, rows per table, per package its build time")
    d.add_argument("--env", "-e", default=None, help="a clio environment: also the site's columns and schemas the workspace does not hold (read-only)")
    rs = sub.add_parser("resolve", help="the workspace by what users call things: a caption (or a Usr name) -> objects, pages, columns, elements, parameters, lookup values, ranked")
    rs.add_argument("path")
    rs.add_argument("text")
    rs.add_argument("--kind", default="", help="object, page, column, element, parameter, lookup, section, process or rule")
    rs.add_argument("--culture", default="", help="another culture, or all (default: each package's primary culture)")
    rs.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    rs.add_argument("--offset", type=int, default=0)
    for cmd, helptext in (("who-sets", "every place that writes <Entity>.<Column> [= value]: process steps and scripts, C#, pages, SQL scripts"),
                          ("who-reads-message", "the publishers and subscribers of a message sender")):
        w = sub.add_parser(cmd, help=helptext)
        w.add_argument("path")
        w.add_argument("target")
        w.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
        w.add_argument("--offset", type=int, default=0)
    e = sub.add_parser("find", help="where a schema lives and what touches it")
    e.add_argument("path")
    e.add_argument("schema")
    e.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    e.add_argument("--offset", type=int, default=0, help="skip this many lines of each list first")
    ft = sub.add_parser("find-text", help="a regex over every file the index knows: <Package>/<Item> (<kind>) <line>: <text>; resource XML only with --kind resource")
    ft.add_argument("path")
    ft.add_argument("pattern")
    ft.add_argument("--kind", default="", help="items of one kind (object, page, process, ...); resource reads resource XML only")
    ft.add_argument("--context", type=int, default=0, help="lines before and after each hit")
    ft.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    f = sub.add_parser("lookups", help="every lookup object (parent chain reaches BaseLookup) with bindings and users")
    f.add_argument("path")
    f.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    f.add_argument("--offset", type=int, default=0)
    h = sub.add_parser("deps", help="typed dependencies of a schema over the workspace: what it builds on and who builds on it")
    h.add_argument("path")
    h.add_argument("schema")
    h.add_argument("--in", dest="direction", action="store_const", const="in", default="both", help="dependents only")
    h.add_argument("--out", dest="direction", action="store_const", const="out", help="what it depends on only")
    h.add_argument("--kind", default="", help="only edges to / from this kind (object, process, page, ...)")
    h.add_argument("--via", default="", help="only this relation (lookup, signal, data-source, ...)")
    h.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    h.add_argument("--offset", type=int, default=0, help="skip this many lines of each list first")
    i = sub.add_parser("impact", help="the dependents of the schemas a task changes, and the other active tasks that change or affect them; exit 1 on a conflict")
    i.add_argument("path")
    i.add_argument("schemas", nargs="+", metavar="Schema")
    i.add_argument("--tasks", help="the loop's tasks folder (project.json paths.tasks): locks of the other active tasks are checked")
    i.add_argument("--current", help="this task's folder name, left out of the lock check")
    i.add_argument("--md", action="store_true", help="the `## Impact` table for plan.md and the `affects:` line for schemas.json")
    i.add_argument("--kind", default="", help="only dependents of this kind (page, process, rules, dcm, data, csharp ...)")
    i.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    g = sub.add_parser("layers", help="the copies of a schema on an environment, applied first to last; exit 1 when the Custom layer has one")
    g.add_argument("schema")
    g.add_argument("-e", "--env", help="clio environment name")
    g.add_argument("--project", help="project.json: the environment and environment.customLayer")
    g.add_argument("--rule", help="a business rule UId: its state in every layer")
    g.add_argument("--workspace", help="the workspace: a schema the site renamed is found by its UId and `name on site: X (workspace: Y)` is printed")
    g.add_argument("--custom-layer", help="the customisation package (default: project.json environment.customLayer, else Custom)")
    g.add_argument("--json", action="store_true", help="the result as JSON, for evidence")
    sn = sub.add_parser("snapshot", help="an object as lines: effective columns over the workspace layers (disk), table columns / rows / checksums / copies (site)")
    sn.add_argument("schema")
    sn.add_argument("--workspace", help="the workspace: the effective columns over its layers (in the site's order with -e)")
    sn.add_argument("-e", "--env", help="clio environment name")
    sn.add_argument("--project", help="project.json holding the environment")
    sn.add_argument("--columns", default="", help="comma list of columns to checksum (default: all but Id)")
    sn.add_argument("--out", help="also write the lines to this file (the evidence)")
    sn.add_argument("--page-file", help="a page: the file the UI test utility's analyse wrote from the live page (one `page` line per element)")
    mp = sub.add_parser("merge-plan", help="the plan of collapsing each schema's replacing layers into one: target, additions, conflicts, dependencies; read-only, exit 1 on a conflict")
    mp.add_argument("path")
    mp.add_argument("schemas", nargs="*", metavar="Schema", help="only these (default: every schema replaced by more than one package)")
    mp.add_argument("-e", "--env", help="clio environment name: the layer order of the site")
    mp.add_argument("--project", help="project.json holding the environment")
    mp.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    mp.add_argument("--offset", type=int, default=0)
    mp.add_argument("--direction", choices=("up", "down"), default="up", help='"up" (default): into the top package, the one that depends on every layer\'s package, dependencies unchanged; "down": into the lowest package, which gains the removed packages\' dependencies')
    mg = sub.add_parser("merge", help="the replacing layers of one object or page collapsed into one layer of the target package; prints the files, --apply writes them; exit 1 when it stops")
    mg.add_argument("path")
    mg.add_argument("schema")
    mg.add_argument("--target", help="the package to merge into (default: the single top package with --direction up, the lowest with down)")
    mg.add_argument("--direction", choices=("up", "down"), default="up", help='"up" (default): into the top package, the one that depends on every layer\'s package, dependencies unchanged; "down": into the lowest package, which gains the removed packages\' dependencies')
    mg.add_argument("-e", "--env", help="clio environment name: the site's layer order and the references check")
    mg.add_argument("--project", help="project.json holding the environment")
    mg.add_argument("--apply", action="store_true", help="write and delete the files (without it: print only)")
    mk = sub.add_parser("merge-package", help="one child package folded into its parent: layers merged, the rest moved with the UId kept, DependsOn redirected; --apply writes; exit 1 on a stop")
    mk.add_argument("path")
    mk.add_argument("child")
    mk.add_argument("--into", required=True, help="the parent package (the child must depend on it)")
    mk.add_argument("-e", "--env", help="clio environment name: the site's layer order, Custom layers, logged process runs")
    mk.add_argument("--project", help="project.json holding the environment")
    mk.add_argument("--apply", action="store_true", help="write, move and delete the files (without it: print only)")
    mr = sub.add_parser("merge-run", help="merge-package with tests, snapshots and push around it, evidence in a folder; without --apply a rehearsal; exit 1 on a stop, red case or difference, 3 when paused")
    mr.add_argument("path")
    mr.add_argument("child")
    mr.add_argument("--into", required=True, help="the parent package")
    mr.add_argument("-e", "--env", required=True, help="clio environment name (the test site)")
    mr.add_argument("--evidence", required=True, help="the folder for plan.txt, cases/, before/, after/, merge.txt, push.log, compare.txt")
    mr.add_argument("--apply", action="store_true", help="merge and push (without it: the run ends after the snapshots)")
    mr.add_argument("--continue", dest="resume", action="store_true", help="after the pause: the child's application is removed; compare and test again")
    mr.add_argument("--tests-root", help="the UI test utility's folder (default CREATIO_TESTS_ROOT or ../automatic-creatio-tests)")
    cp = sub.add_parser("compare", help="two snapshot files: + - ~ lines; exit 1 on a difference")
    cp.add_argument("before")
    cp.add_argument("after")
    cp.add_argument("--ignore-layers", action="store_true", help="leave out the lines a merge changes by design (layers:, siblings, copy, layer ...)")
    x = sub.add_parser("export", help="a snapshot for reading without the tools: one text file per schema, one per package")
    x.add_argument("path")
    x.add_argument("--out", help="the folder (default <workspace>/.creatio-export; elsewhere for a client workspace)")
    y = sub.add_parser("diff", help="the working copy against git HEAD, a revision or a folder, in schema terms: + added, - removed, ~ changed lines")
    y.add_argument("package")
    y.add_argument("schemas", nargs="*", metavar="Schema", help="only these items (default: the whole package)")
    y.add_argument("--against", help="a git revision (default HEAD), a folder holding the package (a pulled copy), or env:<clio env> (the site's copy of the named schemas)")
    z = sub.add_parser("uid", help="what a UId names in the workspace (a schema, a column, a process element or parameter), a dotted name's UId, or a text with every UId named")
    z.add_argument("path")
    z.add_argument("text", help="a UId, Schema.Column, Process.Element[.Parameter], or a text holding UIds (a meta path, a filter)")
    r = sub.add_parser("review", help="a pulled package against git HEAD: line endings / BOM only, content changes, dependencies, orphan resources; --keep restores the rest")
    r.add_argument("package")
    r.add_argument("--keep", nargs="*", metavar="Schema", help="the items to keep; every other changed file is restored from HEAD (printed; run with --apply)")
    r.add_argument("--apply", action="store_true", help="with --keep: run the git checkout lines")
    q = sub.add_parser("precommit", help="the staged files that must not be committed: over 5 MB, archives, binaries outside Files/Bin, files outside packages/; exit 1")
    q.add_argument("workspace")
    args = p.parse_args(argv)
    if args.command == "review":
        from creatio_schemas.describe.review import render, review
        try:
            print(render(review(args.package, args.keep, args.apply and args.keep is not None)))
        except (FileNotFoundError, RuntimeError, QueryError) as e:
            print(f"error: {_message(e)}", file=sys.stderr)
            return 2
        return 0
    if args.command == "precommit":
        from creatio_schemas.describe.review import precommit
        try:
            notes: list[str] = []
            problems = precommit(args.workspace, notes)
        except (FileNotFoundError, RuntimeError) as e:
            print(f"error: {_message(e)}", file=sys.stderr)
            return 2
        for note in notes:
            print(note, file=sys.stderr)
        print("\n".join(problems) if problems else "ok")
        return 1 if problems else 0
    if args.command == "layers":
        return layers_command(args)
    if args.command in ("snapshot", "compare"):
        return snapshot_command(args)
    if args.command == "merge-run":
        from creatio_schemas.describe.merge_run import Engines, merge_run
        try:
            text, code = merge_run(args.path, args.child, args.into, args.evidence, args.env, args.apply, args.resume,
                                   Engines(Path(args.path), args.env, args.tests_root))
        except (ValueError, KeyError, OSError, RuntimeError, QueryError) as e:
            print(f"error: {_message(e)}", file=sys.stderr)
            return 2
        print(text)
        return code
    if args.command == "merge-package":
        from creatio_schemas.describe.package_merge import merge_package
        from creatio_schemas.environment import open_environment
        try:
            env = open_environment(args.env, args.project) if args.env or args.project else None
            text, code = merge_package(args.path, args.child, args.into, env, args.apply)
        except (ValueError, KeyError, OSError, RuntimeError, QueryError) as e:
            print(f"error: {_message(e)}", file=sys.stderr)
            return 2
        print(text)
        return code
    if args.command in ("merge-plan", "merge"):
        from creatio_schemas.describe.merge import merge_plan, merge_schema
        from creatio_schemas.environment import open_environment
        try:
            env = open_environment(args.env, args.project) if args.env or args.project else None
            if args.command == "merge":
                text, code = merge_schema(args.path, args.schema, args.target, env, args.apply, direction=args.direction)
            else:
                text, conflicts = merge_plan(args.path, args.schemas, env, args.limit, args.offset, args.direction)
                code = 1 if conflicts else 0
        except (ValueError, KeyError, OSError, RuntimeError, QueryError) as e:
            print(f"error: {_message(e)}", file=sys.stderr)
            return 2
        print(text)
        return code
    try:
        if args.command == "package":
            print(describe_package(args.package, args.kind, args.limit, args.offset))
        elif args.command == "lookups":
            print(lookups(args.path, args.limit, args.offset))
        elif args.command == "deps":
            from creatio_schemas.describe.deps import dependencies
            print(dependencies(args.path, args.schema, args.direction, args.kind, args.via, args.limit, args.offset))
        elif args.command == "impact":
            from creatio_schemas.describe.deps import impact
            text, conflicts = impact(args.path, args.schemas, args.tasks, args.current, args.md, args.limit, args.kind)
            print(text)
            return 1 if conflicts else 0
        elif args.command == "schema":
            print(describe_schema(args.package, args.schema, args.limit, args.offset, args.env))
        elif args.command == "export":
            from creatio_schemas.describe.export import export
            print(export(args.path, args.out))
        elif args.command == "diff":
            from creatio_schemas.describe.diff import schema_diff
            print(schema_diff(args.package, args.schemas, args.against))
        elif args.command == "uid":
            from creatio_schemas.describe.uids import resolve
            print(resolve(args.path, args.text))
        elif args.command == "index":
            print(index_workspace(args.path, args.rebuild, args.stats, args.env))
        elif args.command == "find":
            print(find_schema(args.path, args.schema, args.limit, args.offset))
        elif args.command == "find-text":
            from creatio_schemas.describe.index import find_text
            print(find_text(args.path, args.pattern, args.kind, args.context, args.limit))
        elif args.command in ("who-sets", "who-reads-message"):
            from creatio_schemas.describe import writes
            fn = writes.who_sets if args.command == "who-sets" else writes.who_reads_message
            print(fn(args.path, args.target, args.limit, args.offset))
        elif args.command == "resolve":
            from creatio_schemas.describe.caption_search import resolve_caption
            print(resolve_caption(args.path, args.text, args.kind, args.culture, args.limit, args.offset))
        else:
            print(describe_item(args.package, args.schema, args.query))
    except (OSError, KeyError, ValueError, QueryError) as e:
        print(f"error: {_message(e)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
