"""The site's columns and schemas the workspace does not hold (S31-T10, T11): `index --env <name>`.

After the normal refresh, three read-only statements (the S23 way, through `env.sql`):

    columns   information_schema.columns of every object's table of the index, one statement for all of them
    owners    SysLocalizableValue keys `Columns.<Name>.Caption` of those objects' SysSchema copies: the package that captions a
              column is the layer that defines it (an own copy before a replacing one); the caption in the site's PrimaryCulture
    schemas   SysSchema rows whose name starts with a prefix of the workspace and that no workspace package defines

A column of the table that the workspace does not define (a lookup `XId` is the workspace's `X`) is a row of `site_columns`; one with
no caption key anywhere is `package` null (a physical column from a SQL script, a designer leftover), printed `package not found`. A
table the site does not have is one row with `missing` = 1. Every row carries the env and the time of the pass; a pass replaces its env.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..records import quote
from . import store

MANAGER_KINDS = {"EntitySchemaManager": "object", "ClientUnitSchemaManager": "client", "ProcessSchemaManager": "process",
                 "SourceCodeSchemaManager": "source", "ProcessUserTaskSchemaManager": "user-task", "DcmSchemaManager": "dcm",
                 "AddonSchemaManager": "addon", "CampaignSchemaManager": "campaign"}
_PREFIX_RE = re.compile(r"^([a-z][a-z0-9]*|[A-Z][a-z0-9]+)(?=[A-Z])")


def _in(names) -> str:
    return ", ".join(quote(n) for n in sorted(names)) or "''"


def columns_sql(objects) -> str:
    return ('select table_name::text "object", column_name::text "column", data_type::text "type", character_maximum_length::text "length" '
            f"from information_schema.columns where table_schema = current_schema() and table_name in ({_in(objects)}) order by 1, 2")


def owners_sql(objects) -> str:
    """The caption keys of every copy of the objects and of their parents (`ParentId` up: a lookup's `Name` is BaseLookup's), with
    the depth of that schema below the object."""
    return f"""with recursive chain (object, id, parent, depth) as (
  select s."Name", s."Id", s."ParentId", 0 from "SysSchema" s where s."ManagerName" = 'EntitySchemaManager' and s."Name" in ({_in(objects)})
  union
  select c.object, p."Id", p."ParentId", c.depth + 1 from chain c join "SysSchema" p on p."Id" = c.parent where c.depth < 30)
select c.object::text "object", l."Key"::text "key", p."Name"::text "package", s."ExtendParent"::text "replacing", max(c.depth)::text "depth",
  max(case when l."SysCultureId" = (select v."GuidValue" from "SysSettingsValue" v join "SysSettings" ss on ss."Id" = v."SysSettingsId"
    where ss."Code" = 'PrimaryCulture' limit 1) then l."Value" end)::text "caption"
from chain c
join "SysSchema" s on s."Id" = c.id
join "SysLocalizableValue" l on l."SysSchemaId" = s."Id"
join "SysPackage" p on p."Id" = l."SysPackageId"
where l."Key" like 'Columns.%.Caption'
group by 1, 2, 3, 4"""


def schemas_sql(prefixes) -> str:
    like = " or ".join(f's."Name" like {quote(p + "%")}' for p in sorted(prefixes)) or "false"
    return f"""select s."Name"::text "name", s."UId"::text "uid", s."ManagerName"::text "manager", p."Name"::text "package",
  coalesce(s."Caption", '')::text "caption"
from "SysSchema" s join "SysPackage" p on p."Id" = s."SysPackageId"
where not s."ExtendParent" and ({like})
order by 1"""


def prefixes_of(path: Path, own_names) -> set[str]:
    """project.json `prefixes`, else the prefixes two or more of the workspace's own schema names share (`Usr`, `ia`)."""
    root = path if (path / "packages").is_dir() else path.parent.parent if path.parent.name == "packages" else path.parent
    try:
        given = json.loads((root / "project.json").read_text(encoding="utf-8-sig")).get("prefixes")
        if given:
            return set(given)
    except (OSError, ValueError, AttributeError):
        pass
    counts: dict[str, int] = {}
    for n in own_names:
        m = _PREFIX_RE.match(n)
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return {p for p, c in counts.items() if c >= 2}


def _type(row: dict, lookup: bool) -> str:
    if lookup:
        return "Lookup"
    return row["type"] + (f"({row['length']})" if row.get("length") not in (None, "") else "")


def site_pass(db: Path, env, env_name: str, objects: dict[str, tuple[str, set[str]]], schemas: dict[str, str], prefixes: set[str],
              culture: str = "en-US") -> list[str]:
    """Fill `site_columns` and `site_schemas` of `env_name`. `objects` = {object: (package folder, the workspace's column names)},
    `schemas` = {name: uid} of every schema the workspace defines. The report lines for `index`."""
    from .platform import caption as platform_caption

    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    table: dict[str, list[dict]] = {}
    for r in env.sql(columns_sql(objects)) if objects else []:
        table.setdefault(r["object"], []).append(r)
    owners: dict[tuple[str, str], tuple[str, str | None]] = {}
    rows = env.sql(owners_sql(objects)) if objects else []
    # the column's definer: an own (not replacing) schema before a replacing copy, the deepest one first (the parent that adds it);
    # the caption: the shallowest one in the site's primary culture (the layer the user sees last)
    for r in sorted(rows, key=lambda r: (str(r["replacing"]).lower() == "true", -int(r["depth"] or 0), r["package"])):
        col = r["key"][len("Columns."):-len(".Caption")]
        owners.setdefault((r["object"].lower(), col), (r["package"], None))
    for r in sorted(rows, key=lambda r: int(r["depth"] or 0)):
        key = (r["object"].lower(), r["key"][len("Columns."):-len(".Caption")])
        if r.get("caption") and owners[key][1] is None:
            owners[key] = (owners[key][0], r["caption"])
    out_rows, missing = [], []
    for obj, (folder, known) in sorted(objects.items()):
        cols = table.get(obj)
        if not cols:
            missing.append(obj)
            out_rows.append((env_name, at, folder, obj, None, None, None, None, 1))
            continue
        for r in cols:
            c = r["column"]
            lookup = r["type"] == "uuid" and c.endswith("Id") and c != "Id"
            name = c[:-2] if lookup else c
            if name in known or c in known:
                continue
            package, caption = owners.get((obj.lower(), name), (None, None))
            if caption is None:
                hit = platform_caption(db, obj, f"Columns.{name}.Caption", culture)
                caption = hit[0] if hit else None
            out_rows.append((env_name, at, folder, obj, name, _type(r, lookup), package, caption, 0))
    site_only, clashes = [], []
    for r in env.sql(schemas_sql(prefixes)) if prefixes else []:
        uid = str(r["uid"]).lower()
        if r["name"] in schemas:
            if schemas[r["name"]] and schemas[r["name"]] != uid:
                clashes.append(f"  {r['name']} on the site has UId {uid}, the workspace {schemas[r['name']]}")
            continue
        site_only.append((env_name, at, r["name"], uid, MANAGER_KINDS.get(r["manager"], r["manager"]), r["package"], r["caption"] or None))
    con = store.connect(db)
    try:
        con.execute("delete from site_columns where env = ?", (env_name,))
        con.execute("delete from site_schemas where env = ?", (env_name,))
        con.executemany("insert into site_columns (env, at, package_of_object, object, name, type, package, caption, missing) "
                        "values (?, ?, ?, ?, ?, ?, ?, ?, ?)", out_rows)
        con.executemany("insert into site_schemas (env, at, name, uid, kind, package, caption) values (?, ?, ?, ?, ?, ?, ?)", site_only)
        con.commit()
    finally:
        con.close()
    extra = [r for r in out_rows if not r[8]]
    lost = sum(1 for r in extra if r[6] is None)
    lines = [f"site {env_name} ({at[:10]}): {len(extra)} columns beyond the workspace in {len({r[3] for r in extra})} objects"
             + (f", {lost} package not found" if lost else "") + (f"; no table on the site: {', '.join(missing)}" if missing else "")]
    lines.append(f"site {env_name} ({at[:10]}): {len(site_only)} schemas beyond the workspace in {len({r[5] for r in site_only})} packages"
                 + f" (prefixes {', '.join(sorted(prefixes)) or 'none'})")
    return lines + clashes


# -- readers ----------------------------------------------------------------------- #

def _query(db: Path, sql: str, **args) -> list[tuple]:
    if not db.is_file():
        return []
    con = store.connect(db, write=False)
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:  # an older store: no table
        return []
    finally:
        con.close()


def columns_of(db: Path, obj: str) -> list[tuple]:
    """(env, at, name, type, package, caption, missing) of an object's site rows, every env."""
    return _query(db, "select env, at, name, type, package, caption, missing from site_columns where object = :o collate nocase "
                      "order by env, missing desc, name", o=obj)


def column_lines(db: Path, obj: str) -> list[str]:
    """`UsrRegion  'Region'  Lookup  site: UsrOtherPkg` per site column; the missing table as one line."""
    out = []
    for env, at, name, typ, package, caption, missing in columns_of(db, obj):
        if missing:
            out.append(f"(no table {obj} on the site {env}, {at[:10]})")
            continue
        out.append(f"{name}" + (f"  {caption!r}" if caption else "") + f"  {typ}  site: {package or 'package not found'}")
    return out


def summary_line(db: Path, obj: str) -> list[str]:
    """`site (<env>, <date>): 4 columns beyond the workspace, 1 package not found` per env with a pass."""
    by_env: dict[tuple[str, str], list[tuple]] = {}
    for env, at, name, typ, package, caption, missing in columns_of(db, obj):
        by_env.setdefault((env, at[:10]), []).append((package, missing))
    out = []
    for (env, day), rows in sorted(by_env.items()):
        if any(m for _, m in rows):
            out.append(f"site ({env}, {day}): no table {obj} on the site")
            continue
        lost = sum(1 for p, _ in rows if p is None)
        out.append(f"site ({env}, {day}): {len(rows)} columns beyond the workspace" + (f", {lost} package not found" if lost else ""))
    return out


def schema_hits(query, name: str) -> list[str]:
    """`UsrRegion  object 'Region'  site: UsrOtherPkg (not in workspace)  (<env>, <date>)` per env whose pass found it; `query` is the
    call's reader (`Indexed.query`: one connection per call, S26-T03)."""
    return [f"{n}  {kind}" + (f" {caption!r}" if caption else "") + f"  site: {package} (not in workspace)  ({env}, {at[:10]})"
            for env, at, n, kind, package, caption in query("select env, at, name, kind, package, caption from site_schemas "
                                                            "where name = :n collate nocase order by env", n=name)]


# -- T12: the writers ask before they add -------------------------------------------- #

NO_PASS = "no site pass yet - run index --env <name>"


def _has_pass(db: Path) -> bool:
    return bool(_query(db, "select 1 from site_columns union all select 1 from site_schemas limit 1"))


def column_clash(package: Path, obj: str, name: str) -> tuple[str, str] | None:
    """("stop" | "warn" | "note", line) when adding `obj.name` would make a second column; None when the site pass knows none."""
    from .index import index_path

    db = index_path(Path(package))
    if not _has_pass(db):
        return "note", NO_PASS
    for env, at, n, typ, pkg, caption, missing in columns_of(db, obj):
        if missing or n is None or n.lower() != name.lower():
            continue
        if pkg is None:
            return "warn", (f"warning: {n} exists on the site ({env}, {at[:10]}) with no package (a physical column, it cannot be "
                            "referenced); adding it anyway")
        return "stop", (f"{n} exists on the site ({env}, {at[:10]}) in package {pkg}: reuse it (add that package to the workspace or "
                        "reference the column); --force adds it anyway")
    return None


def schema_clash(package: Path, name: str) -> tuple[str, str] | None:
    """("stop" | "note", line) when a new schema `name` is a site-only schema of the last pass."""
    from .index import index_path

    db = index_path(Path(package))
    if not _has_pass(db):
        return "note", NO_PASS
    hit = _query(db, "select env, at, kind, package from site_schemas where name = :n collate nocase limit 1", n=name)
    if hit:
        env, at, kind, pkg = hit[0]
        return "stop", f"{name} exists on the site ({env}, {at[:10]}) as {kind} in package {pkg}: reuse it (add that package to the workspace); --force creates it anyway"
    return None
