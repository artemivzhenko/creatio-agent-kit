"""Test data from a site without typing SQL (S38): what a lookup holds, what records of an object look like, and a synthetic
record of the object's shape as a DSL `insert` block.

    lookup_values(env, "UsrOrderStatus")                 `Id  Name  [Code]  [Description]` per row, ordered by Name
    sample_records(env, "UsrOrder", "\"UsrAmount\" > 10")  the newest records, every lookup named, system columns hidden
    make_fixture(env, "UsrOrder", alias="A")             `insert UsrOrder as A set ...` with synthetic values (writes nothing)

Read-only, PostgreSQL, through `Environment.sql`; a table or column name reaches a statement only from `information_schema`
or after `records.ident` accepted it. A lookup value in a fixture is platform data (the first row by Name); every other
value is made up, so no record of the site's content ends up in a case.
"""

from __future__ import annotations

import re
from datetime import date

from .describe.core import NEXT_TAIL
from .records import foreign_keys, guid, ident

SYSTEM = ("CreatedOn", "CreatedById", "ModifiedOn", "ModifiedById", "ProcessListeners")
MAX_RECORDS = 50
COLUMNS_SQL = ('select column_name::text as "column", data_type::text as "type", character_maximum_length::text as "length", '
               'is_nullable::text as "nullable", column_default::text as "default" from information_schema.columns '
               "where table_schema = current_schema() and table_name = '{table}' order by ordinal_position")
# the tables among {names} whose object inherits BaseLookup (SysSchema.ParentId up to 20 levels, every package layer)
LOOKUPS_SQL = ('with recursive up as (select s."Name"::text as "start", s."ParentId", s."Name"::text as "name", 0 as "depth" from "SysSchema" s '
               "where s.\"ManagerName\" = 'EntitySchemaManager' and s.\"Name\" in ({names}) "
               'union select up."start", p."ParentId", p."Name"::text, up."depth" + 1 from "SysSchema" p join up on p."Id" = up."ParentId" '
               'where up."depth" < 20) select distinct "start" as "table" from up where "name" = \'BaseLookup\'')
WRITING = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|merge|call|execute|vacuum|reindex|lock)\b", re.I)
SHORT_TYPES = {"character varying": "text", "timestamp without time zone": "datetime", "timestamp with time zone": "datetime",
               "uuid": "uuid", "double precision": "float"}


def columns_of(env, table: str) -> list[dict]:
    """[{column, type, length, nullable, default}] of a table on the site, in column order; [] when there is no such table."""
    return env.sql(COLUMNS_SQL.format(table=ident(table)))


def _columns_or_hint(env, table: str) -> list[dict]:
    cols = columns_of(env, table)
    if cols:
        return cols
    hint = ""
    if not table.lower().startswith("usr") and columns_of(env, "Usr" + table):
        hint = f"; Usr{table} exists - did you mean it?"
    raise KeyError(f'no table "{table}" on the site{hint}')


def _lookup_tables(env, tables: set[str]) -> set[str]:
    if not tables:
        return set()
    names = ", ".join(f"'{ident(t)}'" for t in sorted(tables))
    return {r["table"] for r in env.sql(LOOKUPS_SQL.format(names=names))}


def _short(text, width: int = 60) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width - 3] + "..."


# --- lookup_values ----------------------------------------------------------------------------------------------------

def lookup_values(env, lookup: str, limit: int = 50, offset: int = 0) -> str:
    """`<lookup>: N rows`, then `Id  Name  [Code]  [Description]` per row ordered by Name, a page of `limit` (0 = all) from `offset`."""
    cols = {c["column"] for c in _columns_or_hint(env, lookup)}
    if "Name" not in cols:
        raise KeyError(f'"{lookup}" has no Name column: not a lookup (sample_records reads it)')
    picked = ["Id", "Name"] + [c for c in ("Code", "Description") if c in cols]
    total = int(env.sql(f'select count(*) as "n" from "{ident(lookup)}"')[0]["n"])
    page = f" offset {max(offset, 0)}" + (f" limit {limit}" if limit else "")
    rows = env.sql(f'select {", ".join(chr(34) + c + chr(34) for c in picked)} from "{ident(lookup)}" order by "Name", "Id"{page}')
    lines = [f"{lookup}: {total} rows"]
    for r in rows:
        cells = [str(r.get("Id")), str(r.get("Name") or "")]
        if "Code" in picked:
            cells.append(str(r.get("Code") or ""))
        if "Description" in picked and r.get("Description"):
            cells.append(_short(r["Description"]))
        lines.append("  ".join(cells).rstrip())
    shown = max(offset, 0) + len(rows)
    if shown < total and rows:
        lines.append(NEXT_TAIL.format(more=total - shown, next=shown))
    return "\n".join(lines)


# --- sample_records ---------------------------------------------------------------------------------------------------

def _names_by_table(env, ids_of: dict[str, set[str]]) -> dict[str, dict[str, str]]:
    """{table: {id: Name}} for every table that has a Name column - two statements for all tables, not two per column
    (one clio call is seconds; Account has 20 foreign keys)."""
    if not ids_of:
        return {}
    tables = ", ".join(f"'{ident(t)}'" for t in sorted(ids_of))
    named = {r["table"] for r in env.sql("select table_name::text as \"table\" from information_schema.columns where table_schema = current_schema() "
                                       f"and column_name = 'Name' and table_name in ({tables})")}
    selects = [f"select '{t}' as \"table\", \"Id\", \"Name\" from \"{t}\" where \"Id\" in ({', '.join(repr(guid(i)) for i in sorted(ids_of[t]))})"
               for t in sorted(ids_of) if t in named]
    out: dict[str, dict[str, str]] = {t: {} for t in named}
    for r in env.sql(" union all ".join(selects)) if selects else []:
        out[r["table"]][str(r["Id"]).lower()] = r.get("Name")
    return out


def read_filter(text: str) -> str:
    """A `where` fragment that may go into a select: one fragment, no writing word."""
    text = (text or "").strip()
    bare = re.sub(r"'[^']*'", "''", text)  # a word or a ';' inside a string literal is a value, not a statement
    if ";" in bare:
        raise ValueError("filter must be one where fragment: no ';'")
    m = WRITING.search(bare)
    if m:
        raise ValueError(f"filter must only read: {m.group(1)!r} is a writing word")
    return text


def _wanted(columns: str) -> set[str]:
    return {c.strip().lower() for c in columns.split(",") if c.strip()}


def _named(column: str, wanted: set[str]) -> bool:
    low = column.lower()
    return low in wanted or (low.endswith("id") and low[:-2] in wanted)


def sample_records(env, entity: str, filter: str = "", n: int = 3, columns: str = "") -> str:
    """`n` records of an object (the newest by CreatedOn without a filter), one block each: `Column (type) = value`, a lookup
    as the referenced row's Name and its Id; the system columns only when `columns` names them."""
    where = read_filter(filter)
    n = min(max(int(n or 3), 1), MAX_RECORDS)
    cols = _columns_or_hint(env, entity)
    wanted = _wanted(columns)
    names = {c["column"] for c in cols}
    shown = [c for c in cols if c["column"] != "Id" and (c["column"] not in SYSTEM or _named(c["column"], wanted))]
    order = '"CreatedOn" desc nulls last, "Id"' if "CreatedOn" in names else '"Id"'
    rows = env.sql(f'select * from "{ident(entity)}"' + (f" where ({where})" if where else "") + f" order by {order} limit {n}")
    refs = {f["column"]: f["ref_table"] for f in foreign_keys(env, entity)}
    ids_of: dict[str, set[str]] = {}  # ref table -> the Ids the shown rows point at
    for col, ref in refs.items():
        if col in {c["column"] for c in shown}:
            ids_of.setdefault(ref, set()).update(str(r[col]) for r in rows if r.get(col))
    lookups = _names_by_table(env, {t: ids for t, ids in ids_of.items() if ids})
    resolved = 0
    lines = [f"{entity}: {len(rows)} record(s)" + (f" where {where}" if where else " (the newest by CreatedOn)" if "CreatedOn" in names else "")]
    for r in rows:
        lines.append(f"{entity} {r.get('Id')}")
        for c in shown:
            col, value = c["column"], r.get(c["column"])
            if col in refs:
                kind = f"lookup {refs[col]}"
                if value:
                    name = lookups.get(refs[col], {}).get(str(value).lower())
                    resolved += name is not None
                    value = f"{name} ({value})" if name is not None else f"{value} (no row)"
            else:
                kind = SHORT_TYPES.get(c["type"], c["type"])
            lines.append(f"  {col} ({kind}) = " + ("null" if value is None else '""' if value == "" else str(value)))
    if not rows:
        lines.append("(no rows)")
    lines.append(f"columns: {len(shown)}, lookups resolved: {resolved}")
    return "\n".join(lines)


# --- make_fixture -----------------------------------------------------------------------------------------------------

def _value(column: dict, alias: str) -> str | None:
    """A synthetic value of the column's type; None when the type has no sample (the column is set by hand)."""
    kind = column["type"]
    if kind in ("character varying", "text", "character"):
        text = f"{column['column']} {alias}"
        return text[:int(column["length"])] if column.get("length") not in (None, "") else text
    if kind in ("integer", "bigint", "smallint", "numeric", "double precision", "real"):
        return "1"
    if kind == "date":
        return date.today().isoformat()
    if kind.startswith("timestamp"):
        return date.today().isoformat() + "T12:00:00Z"  # the form cases-from-package writes and the OData body takes
    if kind.startswith("time"):
        return "12:00:00"
    if kind == "boolean":
        return "false"
    return None


def make_fixture(env, entity: str, alias: str = "A", columns: str = "") -> str:
    """A DSL block that inserts a synthetic record of the object: its required columns (NOT NULL without a default) and the
    ones `columns` names; a lookup takes the first row by Name; a reference to another object gets its own `insert` above,
    one level deep; then the `delete` lines for the case's end, newest first. Nothing is written to the site."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", alias or ""):
        raise ValueError(f"alias {alias!r} must be a name (letters, digits, underscore)")
    stats = {"required": 0, "lookups": 0, "refs": 0, "inserted": []}
    above: list[str] = []
    main = _insert(env, entity, alias, _wanted(columns), None, above, stats)
    # a `# writes` case must delete what it inserts (the validator refuses an insert without `delete` or `keep`): newest first
    ends = [f"delete {e} ${a}" for e, a in reversed(stats["inserted"])]
    return "\n".join(above + main + (["# the end of the case: delete what the block inserted, newest first"] + ends if ends else [])
                     + [f"columns: {stats['required']} required, {stats['lookups']} lookups resolved, {stats['refs']} references inserted"])


def _insert(env, entity: str, alias: str, wanted: set[str], parent: str | None, above: list[str], stats: dict) -> list[str]:
    cols = _columns_or_hint(env, entity)
    refs = {f["column"]: f["ref_table"] for f in foreign_keys(env, entity)}
    # shortcut: required = NOT NULL without a default in the database; the schema's RequirementType is not read (most SysSchema
    # layers keep MetaData in the old text form, not JSON), so a column the object marks required is named in `columns`
    required = [c for c in cols if c["column"] != "Id" and c["column"] not in SYSTEM and c["nullable"].upper() == "NO" and c.get("default") is None]
    if parent is None:
        stats["required"] = len(required)
    chosen = list(required)
    if not required:  # nothing required: the caption still makes the record readable - Name, else the first own text column
        texts = [c for c in cols if c["column"] not in SYSTEM and c["column"] not in refs and c["type"] in ("character varying", "text")]
        chosen = sorted(texts, key=lambda c: (c["column"] != "Name", not c["column"].startswith("Usr")))[:1]
    chosen += [c for c in cols if c not in chosen and c["column"] != "Id" and _named(c["column"], wanted)]
    lookups = _lookup_tables(env, {refs[c["column"]] for c in chosen if c["column"] in refs})
    pairs, notes = [], []
    for c in chosen:
        col = c["column"]
        short = col[:-2] if col.endswith("Id") and col in refs else col
        if col in refs:
            ref = refs[col]
            if ref in lookups:
                first = env.sql(f'select "Id", "Name" from "{ident(ref)}" order by "Name", "Id" limit 1')
                if not first:
                    notes.append(f"# {short}: {ref} has no row - add one or set by hand")
                    continue
                pairs.append(f"{short}={first[0]['Id']}")
                notes.append(f"# {short} = {first[0]['Name']} (the first {ref} by Name)")
                stats["lookups"] += 1
            elif parent is not None or ref == entity:
                notes.append(f"# {short}: set by hand, {entity} needs {ref}")
            else:
                above += _insert(env, ref, short, set(), entity, above, stats)
                pairs.append(f"{short}=${short}")
                stats["refs"] += 1
            continue
        value = _value(c, alias)
        if value is None:
            notes.append(f"# {col}: set by hand, no sample for type {c['type']}")
            continue
        pairs.append(f"{col}={value}")
    if not pairs:
        return notes + [f"# insert {entity} as {alias}: no column a sample can be written to - set by hand"]
    stats["inserted"].append((entity, alias))
    return notes + [f"insert {entity} as {alias} set " + ";".join(pairs)]
