#!/usr/bin/env python3
"""
Objects (entity schemas) stored in a package (library: ../creatio_schemas/entity).

    python objects.py inspect  <package> <Object>
    python objects.py new      <package> <Object> --caption "Order" [--parent BaseEntity|BaseLookup]
    python objects.py base     <package> <Object> --env dev                                fetch the base (replacing objects, other parents)
    python objects.py new      <package> <Object> --replace                                a replacing copy of a base object (after `base`)
    python objects.py column   <package> <Object> add <Name> --type ShortText [--ref Contact] [--caption ..] [--default ..] [--on required indexed ..] [--off ..]
                                                   [--refresh --env dev]                  fetch the base first
    python objects.py column   <package> <Object> ref <Name> Account [--env dev]           a lookup added here points at another object
    python objects.py column   <package> <Object> set <Name> [--on flag ..] [--off flag ..]
    python objects.py column   <package> <Object> default <Name> <value | ->
    python objects.py column   <package> <Object> type <Name> MediumText                  widen a text column only
    python objects.py column   <package> <Object> caption <Name> en-US=".." [uk-UA=".."]
    python objects.py column   <package> <Object> remove <Name>
    python objects.py set      <package> <Object> [--on flag ..] [--off flag ..]          object flags
    python objects.py caption  <package> <Object> en-US=".." [uk-UA=".."] | *=".."       (* = every culture)
    python objects.py display  <package> <Object> <Column>
    python objects.py validate <package> <Object>
    python objects.py probe    <package> <Object> --env dev                                metadata vs the table (PostgreSQL)

Column flags: required, indexed, simple-lookup, weak-reference, cascade, track-changes, sensitive, multiline,
localizable, masked, format-validated, copy-on-duplicate.  Object flags: virtual, db-view, track-changes,
admin-operations, admin-columns, admin-records, deny-rights, deactivation, ssp, live-editing.

Inherited columns of a replacing object (flags, default, caption, a wider text type) need its base:
`base` merges every copy in the packages below <package> the way the platform does and caches it in
<workspace>/.creatio-bases/; fetch again after the platform or those packages change.

After `clio push-pkg` the platform applies the changes to the table itself - unless the object is
virtual or a DB view. Every writing command accepts --dry-run: it prints the diff and writes nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from creatio_schemas import Clio, EntitySchema  # noqa: E402
from creatio_schemas.cli import CommandLine, parse_assignments  # noqa: E402
from creatio_schemas.entity import COLUMN_FLAGS, OBJECT_FLAGS  # noqa: E402
from creatio_schemas.entity.database import check  # noqa: E402
from creatio_schemas.entity.hierarchy import fetch_base, save_base  # noqa: E402
from creatio_schemas.platform_version import stamp  # noqa: E402
from creatio_schemas.workspace import Package  # noqa: E402
from creatio_schemas.files import ALL_DATA_VALUE_TYPES  # noqa: E402
from creatio_schemas.describe.site import site_says  # noqa: E402


def flags(a) -> dict:
    return {**{f: True for f in a.on or []}, **{f: False for f in a.off or []}}


def flag_options(p, choices) -> None:
    p.add_argument("--on", nargs="*", choices=sorted(choices), metavar="flag")
    p.add_argument("--off", nargs="*", choices=sorted(choices), metavar="flag")


def new(_, a):
    if a.replace:
        print(EntitySchema.create_replacing(Path(a.package), a.object, **stamp(a.version, a.project)).describe())
        return
    if not a.caption:
        raise ValueError("--caption is required for a new object")
    from creatio_schemas.describe.site import schema_clash

    if site_says(schema_clash(Path(a.package), a.object), a.force):
        return 1
    print(EntitySchema.create(Path(a.package), a.object, a.caption, a.parent, **stamp(a.version, a.project)).describe())


def base(_, a):
    pkg = Path(a.package)
    sdir = pkg / "Schemas" / a.object
    target = EntitySchema(pkg, a.object).parent_name if (sdir / "metadata.json").is_file() else a.object
    found = fetch_base(Clio(a.env), target, Package(pkg).name)
    path = save_base(pkg, found)
    print(f"{target}: {len(found['schema'].get('D2', []))} columns, merged from {' > '.join(found['chain'])} -> {path}")


def inspect(ent, a):
    print(ent.describe())


def validate(ent, a):
    problems = ent.validate()
    print("\n".join(problems) if problems else "ok")
    return 1 if ent.errors() else 0


def column_add(ent, a):
    from creatio_schemas.describe.site import column_clash

    found = column_clash(ent.package, ent.name, a.name)
    if a.refresh:
        if not a.env:
            raise ValueError("--refresh needs --env <env>")
        base(None, a)
        ent._parent = False  # read the base just fetched
        if found and found[0] == "stop" and not in_table(Clio(a.env), ent.name, a.name):
            print(f"note: the stored site pass says {found[1].split(': reuse it')[0]}; table {ent.name} on {a.env} has no such "
                  "column now, going on", file=sys.stderr)
            found = None
    if site_says(found, a.force):
        raise SystemExit(1)  # before `finish` saves anything
    col = ent.add_column(a.name, a.type, a.caption or "", a.ref, a.default, **flags(a))
    print(f"added {a.name} ({col['UId']})")


def in_table(clio, table: str, name: str) -> bool:
    """Whether the table on the site has the column (a lookup is stored as <Name>Id)."""
    from creatio_schemas.records import quote

    return bool(clio.sql("select column_name::text c from information_schema.columns where table_schema = 'public' "
                         f"and table_name = {quote(table)} and lower(column_name) in ({quote(name.lower())}, {quote(name.lower() + 'id')})"))


def column_ref(ent, a):
    print(f"{a.name} -> {a.schema} ({ent.set_ref(a.name, a.schema, a.env)})")


def column_default(ent, a):
    ent.set_default(a.name, None if a.value == "-" else a.value)


def captions(ent, target, values):
    pairs = parse_assignments(values)
    for culture, value in pairs.items():  # *=value: every culture of the schema
        ent.set_caption(target, value, None if culture == "*" else [culture])


def probe(ent, a):
    if ent.effective is None:  # the base is the author's step (`base`), not the probe's
        print(f"skipped: parent {ent.parent_name} not in the workspace (objects.py base {a.package} {a.object} --env {a.env} fetches it)")
        return 0
    results = check(ent, Clio(a.env))
    for status, message in results:
        if status != "ok" or a.all:
            print(f"{status:8} {message}")
    bad = [s for s, _ in results if s in ("missing", "differs")]
    print(f"{len(results) - len(bad)} ok, {len(bad)} not matching" + (" (use --all to list the ok ones)" if not a.all else ""))
    return 1 if bad else 0


def build() -> CommandLine:
    cli = CommandLine(__doc__, "object")
    c = cli.command
    p = c("new", new, "create an object (no columns yet) the way the 8.2.3 designer does", target=False)
    p.add_argument("package")
    p.add_argument("object")
    p.add_argument("--caption", help="required for a new object")
    p.add_argument("--parent", default="BaseEntity", choices=["BaseEntity", "BaseLookup"])
    p.add_argument("--replace", action="store_true", help="a replacing copy of the base object <Object> (run `base` first)")
    p.add_argument("--version", help="CreatedInVersion / B8 (default: the project's environment.platformVersion, else 8.2.3.1351)")
    p.add_argument("--project", help="project.json: its environment.platformVersion is the version written")
    p.add_argument("--force", action="store_true", help="create it although the last `index --env` pass found it on the site")
    p = c("base", base, "fetch the base of an object from an environment and cache it", target=False)
    p.add_argument("package")
    p.add_argument("object")
    p.add_argument("--env", required=True)
    c("inspect", inspect, "flags, columns and problems")
    c("validate", validate, "problems; exit code 1 on errors (warnings do not count)")

    g = cli.group("column", "columns")
    p = c("add", column_add, "add a column", True, g)
    p.add_argument("name")
    p.add_argument("--type", required=True, choices=sorted(set(ALL_DATA_VALUE_TYPES.values())))
    p.add_argument("--ref", help="Lookup: the referenced object (workspace or stock name, or UId)")
    p.add_argument("--caption")
    p.add_argument("--default", help="a constant default value")
    p.add_argument("--force", action="store_true", help="add it although the last `index --env` pass found it on the site in another package")
    p.add_argument("--refresh", action="store_true", help="fetch the base from --env first; a stored site pass is checked against the table")
    p.add_argument("--env", help="with --refresh: the environment")
    flag_options(p, COLUMN_FLAGS)
    p = c("ref", column_ref, "point a lookup column added here at another object (same column UId, caption kept)", True, g)
    p.add_argument("name")
    p.add_argument("schema", help="the referenced object: workspace or stock name, or UId")
    p.add_argument("--env", help="look the object up on this environment when it is neither in the workspace nor stock")
    p = c("set", lambda ent, a: ent.set_column(a.name, **flags(a)), "change column flags", True, g)
    p.add_argument("name")
    flag_options(p, COLUMN_FLAGS)
    p = c("default", column_default, "set ('-' removes) the constant default of a column added here", True, g)
    p.add_argument("name")
    p.add_argument("value")
    p = c("type", lambda ent, a: ent.set_type(a.name, a.type), "widen a text column (ShortText > MediumText > LongText > MaxSizeText)", True, g)
    p.add_argument("name")
    p.add_argument("type", choices=["MediumText", "LongText", "MaxSizeText"])
    p = c("caption", lambda ent, a: captions(ent, a.name, a.values), "set a column caption", True, g)
    p.add_argument("name")
    p.add_argument("values", nargs="+", metavar="culture=value")
    p = c("remove", lambda ent, a: print("removed", ent.remove_column(a.name)), "remove a column added here", True, g)
    p.add_argument("name")

    p = c("set", lambda ent, a: [ent.set_flag(f, on) for f, on in flags(a).items()], "change object flags", writes=True)
    flag_options(p, OBJECT_FLAGS)
    p = c("caption", lambda ent, a: captions(ent, "Object", a.values) if a.values else None, "set the object caption", writes=True)
    p.add_argument("values", nargs="+", metavar="culture=value")
    p = c("display", lambda ent, a: ent.set_display_column(a.column), "set the display (primary) column", writes=True)
    p.add_argument("column")
    p = c("probe", probe, "compare the metadata with the table on an environment (PostgreSQL)")
    p.add_argument("--env", required=True)
    p.add_argument("--all", action="store_true", help="list the matching items too")
    return cli


def main(argv: list[str]) -> int:
    return build().run(argv, lambda a: None if a.command in ("new", "base") else EntitySchema(Path(a.package), a.object))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
