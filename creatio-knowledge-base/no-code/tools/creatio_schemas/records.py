"""Where a record lives on a site and what surrounds it, read from the database (`Environment.sql`).

    find_record(env, "<id>")                       which table holds an Id, with its caption, dates and authors
    record_context(env, "Contact", "<id>")         the record with its lookups named, then the rows that point at it
    record_history(env, "UsrOrder:<id>")           the change log of a record (`Sys<Entity>Log`): when, who, was -> became per column
    column_transitions(env, "UsrOrder.UsrStatus")  every transition of one column over all records, from the same log
    merge_plan / merge_apply(env, "UsrCity", keep, drops)  duplicate rows of a lookup folded into one: every foreign key moved, a backup, the delete

Every query is a plain `information_schema` / `select` the README lists, so a human can run it by hand. A table name
reaches a statement only from `information_schema` or after `ident` accepted it.
"""

from __future__ import annotations

import fnmatch
import re
from datetime import datetime, timedelta, timezone

from .files import GUID_RE

CHUNK = 50  # tables per `union all`
DETAIL_ROWS = 20
TABLES_SQL = ('select c.table_schema as "schema", c.table_name as "table" from information_schema.columns c '
              'join information_schema.tables t on t.table_name = c.table_name and t.table_schema = c.table_schema '
              "where c.column_name = 'Id' and c.data_type in ('uuid', 'uniqueidentifier') and t.table_type = 'BASE TABLE' "
              "and c.table_schema not in ('pg_catalog', 'information_schema', 'sys') order by 1")
FK_SQL = ('select kcu.table_name as "table", kcu.column_name as "column", ccu.table_name as "ref_table" '
          "from information_schema.referential_constraints rc "
          "join information_schema.key_column_usage kcu on kcu.constraint_name = rc.constraint_name "
          "join information_schema.constraint_column_usage ccu on ccu.constraint_name = rc.unique_constraint_name where ")
CAPTION_COLUMNS = ("Name", "Caption", "Title", "Subject", "Number")  # the first the row has stands for the record
AUDIT = ("CreatedOn", "CreatedById", "ModifiedOn", "ModifiedById")


def ident(name: str) -> str:
    """A table or column name that may go into a statement."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise ValueError(f"{name!r} is not a table or column name")
    return name


def guid(value: str) -> str:
    if not GUID_RE.fullmatch(value or ""):
        raise ValueError(f"{value!r} is not an Id (a guid)")
    return value.lower()


def quote(text) -> str:
    """A text as a SQL string literal."""
    return "'" + str(text).replace("'", "''") + "'"


def _zone(name: str | None):
    """(tzinfo, label): a fixed offset (`+03:00`, `UTC-5`), an IANA name when the machine has the tz database, else the machine's zone."""
    from datetime import timedelta
    if name:
        m = re.fullmatch(r"(?:UTC)?([+-])(\d{1,2})(?::?(\d\d))?", name.strip())
        if m:
            minutes = (int(m.group(2)) * 60 + int(m.group(3) or 0)) * (1 if m.group(1) == "+" else -1)
            return timezone(timedelta(minutes=minutes)), name.strip()
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name), name
        except Exception:  # no tz database (Windows without tzdata) or an unknown name
            return None, f"local, zone {name!r} unknown here (Windows needs `pip install tzdata` for IANA names; an offset like +02:00 always works)"
    return None, "local"


def local_time(value, zone: str | None = None) -> str:
    """`2026-11-10 12:30:00 UTC (14:30 +02:00)`; a value without a zone is UTC; `zone` is an offset or an IANA name, None the machine's."""
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    moment = moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)
    tz, label = _zone(zone)
    there = moment.astimezone(tz)
    return f"{moment:%Y-%m-%d %H:%M:%S} UTC ({there:%H:%M} {label})" + ("" if there.date() == moment.date() else f" {there:%d.%m}")


def zone_of(project: str | None) -> str | None:
    """`environment.timeZone` of a project.json (an IANA name), or None for the machine's zone."""
    if not project:
        return None
    import json
    with open(project, encoding="utf-8-sig") as f:
        return (json.load(f).get("environment") or {}).get("timeZone")


def _first(row: dict, names=CAPTION_COLUMNS):
    """(column, value) that stands for the record: a caption column, else the first `...Name` / `...Number` ... column with a value."""
    for n in names:
        if row.get(n) not in (None, ""):
            return n, row[n]
    return next(((k, v) for k, v in row.items() if k.endswith(names) and v not in (None, "")), (None, None))


def names_of(env, table: str, ids: list[str]) -> dict[str, str]:
    """Id -> Name of the rows of `table` (an object without a Name column answers with nothing)."""
    ids = sorted({guid(i) for i in ids if i})
    if not ids:
        return {}
    rows = env.sql(f'select "Id", "Name" from "{ident(table)}" where "Id" in ({", ".join(repr(i) for i in ids)})')
    return {str(r["Id"]).lower(): r.get("Name") for r in rows}


def find_record(env, record_id: str, priority=(), everywhere: bool = False, zone: str | None = None) -> list[dict]:
    """The tables whose `Id` is `record_id`: [{table, caption, createdOn, createdBy, modifiedOn, modifiedBy}].

    Tables come from `information_schema` (base tables with a uuid `Id`), the ones named in `priority` first (the objects of
    the workspace); chunks of 50 are one `union all` each, and the scan stops after the first chunk that finds the Id unless
    `everywhere`."""
    record_id = guid(record_id)
    tables = [(ident(r["schema"]), ident(r["table"])) for r in env.sql(TABLES_SQL)]  # schema-qualified: a table outside search_path still answers
    first = {t.lower() for t in priority}
    tables = [t for t in tables if t[1].lower() in first] + [t for t in tables if t[1].lower() not in first]
    hits: list[tuple[str, str]] = []
    for i in range(0, len(tables), CHUNK):
        union = " union all ".join(f"select '{s}' as \"schema\", '{t}' as \"table\" from \"{s}\".\"{t}\" where \"Id\" = '{record_id}'" for s, t in tables[i:i + CHUNK])
        hits += [(r.get("schema") or "public", r["table"]) for r in env.sql(union)]
        if hits and not everywhere:
            break
    out = []
    for schema, table in hits:
        row = (env.sql(f'select * from "{ident(schema)}"."{ident(table)}" where "Id" = \'{record_id}\'') or [{}])[0]
        who = names_of(env, "Contact", [row.get("CreatedById"), row.get("ModifiedById")])
        out.append({"table": table, "caption": dict([_first(row)]) if _first(row)[0] else {},
                    "createdOn": local_time(row.get("CreatedOn"), zone), "createdBy": who.get(str(row.get("CreatedById")).lower()),
                    "modifiedOn": local_time(row.get("ModifiedOn"), zone), "modifiedBy": who.get(str(row.get("ModifiedById")).lower())})
    return out


def foreign_keys(env, table: str, incoming: bool = False) -> list[dict]:
    """[{table, column, ref_table}] of the foreign keys a table has (`incoming`: the ones that point at it)."""
    return env.sql(FK_SQL + ("ccu" if incoming else "kcu") + f".table_name = '{ident(table)}'")


def record_context(env, entity: str, record_id: str, columns: str = "", depth: int = 1, zone: str | None = None) -> dict:
    """{entity, id, columns {name: value | {"id", "name"}}, details [{table, column, count, rows}]}.

    `columns` is a comma list with `*` wildcards (default: every column that has a value); a lookup shows the referenced
    row's Name next to its Id, found through the table's foreign keys; the details are the tables with a foreign key to
    this entity and a row for this Id, with the first 20 rows (`depth` 2 names the lookups of those rows too)."""
    record_id = guid(record_id)
    rows = env.sql(f'select * from "{ident(entity)}" where "Id" = \'{record_id}\'')
    if not rows:
        raise KeyError(f"no row {record_id} in {entity}")
    row = rows[0]
    wanted = [c.strip() for c in columns.split(",") if c.strip()]
    # a lookup may be named without its Id suffix (`UsrService` for `UsrServiceId`)
    shown = {k: v for k, v in row.items() if (any(fnmatch.fnmatchcase(k.lower(), w.lower()) or fnmatch.fnmatchcase(k.lower(), w.lower() + "id")
                                                 for w in wanted) if wanted else v not in (None, ""))}
    out = {"entity": entity, "id": record_id, "columns": _named(env, entity, [shown], zone)[0], "details": [], "depth": depth}
    if depth < 1:
        return out
    pointing = foreign_keys(env, entity, incoming=True)
    counts = []
    for i in range(0, len(pointing), CHUNK):
        union = " union all ".join(f"select '{ident(f['table'])}' as \"table\", '{ident(f['column'])}' as \"column\", count(*) as \"n\" "
                                   f"from \"{f['table']}\" where \"{f['column']}\" = '{record_id}'" for f in pointing[i:i + CHUNK])
        counts += [r for r in env.sql(union) if int(r["n"])]
    for c in sorted(counts, key=lambda r: (r["table"], r["column"])):
        sample = env.sql(f'select * from "{c["table"]}" where "{c["column"]}" = \'{record_id}\' order by "Id" offset 0 rows fetch first {DETAIL_ROWS} rows only')
        # depth 1: the Id, the column that points here and a caption; depth 2: every column, so `_named` can name its lookups
        keep = [r if depth > 1 else {k: v for k, v in r.items() if k in ("Id", c["column"]) or k in CAPTION_COLUMNS} for r in sample]
        out["details"].append({"table": c["table"], "column": c["column"], "count": int(c["n"]),
                               "rows": _named(env, c["table"], keep, zone) if depth > 1 else keep})
    return out


# -- merge duplicate rows: move every pointer to the kept row, delete the rest ---------------------- #
UNIQUE_SQL = ('select tablename as "table", indexdef from pg_indexes where indexdef like \'CREATE UNIQUE INDEX%\' and tablename in (')
UNIQUE_COLUMNS = re.compile(r'\(((?:"?[A-Za-z_]\w*"?(?:, )?)+)\)$')  # a plain column list; a partial (`where`) or expression index does not match


def require_dev(project: str | None) -> None:
    """A write that cannot be undone runs on a site whose project.json `environment` says `kind: dev` and `mayBreak: true`; nothing else lifts this."""
    import json
    rule = "merge --apply writes: it runs only on a dev site, --project <project.json> with environment.kind = dev and environment.mayBreak = true (there is no override)"
    if not project:
        raise ValueError(rule + "; no --project was given")
    with open(project, encoding="utf-8-sig") as f:
        e = json.load(f).get("environment") or {}
    if e.get("kind") != "dev" or e.get("mayBreak") is not True:
        raise ValueError(rule + f"; this project has kind = {e.get('kind')!r}, mayBreak = {e.get('mayBreak')!r}")


def _ids(ids) -> str:
    return ", ".join(quote(i) for i in ids)


def merge_plan(env, entity: str, keep: str, drops: list[str]) -> dict:
    """What folding the rows `drops` of `entity` into `keep` would do, read only: {entity, keep, drops, rows (the dropped rows), targets [{table, column,
    constraint, count, pointing [{Id, value}], collide [full rows], unique [column lists]}], statements [{sql, table, kind}]}.

    A target is a foreign key to the table (`foreign_keys`, incoming) or an unconstrained uuid column called `<Entity>Id` / `Usr<Entity>Id` (`constraint` False).
    A row whose move would break a unique index of its table that holds the column (the kept row has a sibling with the same other columns, or a dropped
    row of a lower Id has) is `collide`: it is deleted instead of moved. The statements are the exact text `merge_apply` runs: deletes of colliding rows,
    updates, the final delete."""
    entity, keep, drops = ident(entity), guid(keep), [guid(d) for d in drops]
    if not drops or keep in drops:
        raise ValueError("give --keep <Id> and --drop <Id>[,<Id>..], the kept row not among the dropped ones")
    rows = env.sql(f'select * from "{entity}" where "Id" in ({_ids([keep] + drops)})')
    missing = sorted(set([keep] + drops) - {str(r["Id"]).lower() for r in rows})
    if missing:
        raise KeyError(f"no row {', '.join(missing)} in {entity}")
    pairs = {(ident(f["table"]), ident(f["column"])): True for f in foreign_keys(env, entity, incoming=True)}
    loose = ('select c.table_name as "table", c.column_name as "column" from information_schema.columns c join information_schema.tables t '
             "on t.table_name = c.table_name and t.table_schema = c.table_schema where t.table_type = 'BASE TABLE' and c.data_type in ('uuid', 'uniqueidentifier') "
             f"and c.column_name in ('{entity}Id', 'Usr{entity}Id') and c.table_schema not in ('pg_catalog', 'information_schema', 'sys')")
    for r in env.sql(loose):
        pairs.setdefault((ident(r["table"]), ident(r["column"])), False)
    pairs = dict(sorted(pairs.items()))
    counts = []
    for i in range(0, len(pairs), CHUNK):
        union = " union all ".join(f"select '{t}' as \"table\", '{c}' as \"column\", count(*) as \"n\" from \"{t}\" where \"{c}\" in ({_ids(drops)})"
                                   for t, c in list(pairs)[i:i + CHUNK])
        counts += [r for r in env.sql(union) if int(r["n"])]
    tables = sorted({r["table"] for r in counts})
    unique: dict[str, list[list[str]]] = {}
    if tables:
        try:
            for r in env.sql(UNIQUE_SQL + ", ".join(quote(t) for t in tables) + ")"):
                m = UNIQUE_COLUMNS.search(r["indexdef"].strip())
                if m:
                    unique.setdefault(r["table"], []).append([c.strip('"') for c in m.group(1).split(", ")])
        except RuntimeError:  # no pg_indexes (MS SQL): a collision then fails the update, which stops the apply before the final delete
            pass
    targets, statements = [], []
    for c in sorted(counts, key=lambda r: (r["table"], r["column"])):
        t, col = c["table"], c["column"]
        pointing = [{"Id": r["Id"], "value": r["value"]} for r in env.sql(f'select "Id", "{col}" as "value" from "{t}" where "{col}" in ({_ids(drops)})')]
        collide, indexes = {}, [u for u in unique.get(t, []) if col in u]
        for u in indexes:
            same = "".join(f' and s."{ident(x)}" = r."{x}"' for x in u if x != col)
            for r in env.sql(f'select r.* from "{t}" r where r."{col}" in ({_ids(drops)}) and exists (select 1 from "{t}" s where s."Id" <> r."Id"{same} '
                             f'and (s."{col}" = {quote(keep)} or (s."{col}" in ({_ids(drops)}) and s."Id" < r."Id")))'):
                collide[str(r["Id"]).lower()] = r
        targets.append({"table": t, "column": col, "constraint": pairs[(t, col)], "count": int(c["n"]), "pointing": pointing,
                        "collide": list(collide.values()), "unique": indexes})
        if collide:
            statements.append({"sql": f'delete from "{t}" where "Id" in ({_ids(collide)})', "table": t, "kind": "delete colliding"})
    statements += [{"sql": f'update "{t["table"]}" set "{t["column"]}" = {quote(keep)} where "{t["column"]}" in ({_ids(drops)})', "table": t["table"], "kind": "move"}
                   for t in targets]
    statements.append({"sql": f'delete from "{entity}" where "Id" in ({_ids(drops)})', "table": entity, "kind": "delete dropped"})
    return {"entity": entity, "keep": keep, "drops": drops, "rows": [r for r in rows if str(r["Id"]).lower() != keep], "targets": targets, "statements": statements}


def render_plan(plan: dict) -> str:
    lines = [f"merge {plan['entity']}: keep {plan['keep']}, drop {len(plan['drops'])}: {', '.join(plan['drops'])}"]
    for t in plan["targets"]:
        lines.append(f"  {t['table']}.{t['column']}: {t['count']} row(s)" + ("" if t["constraint"] else " (no constraint)")
                     + (f", {len(t['collide'])} would collide with a unique index and are deleted instead" if t["collide"] else ""))
    if not plan["targets"]:
        lines.append("  (no row points at the dropped ones)")
    lines.append("plan:")
    lines += [f"  {s['sql']}" for s in plan["statements"]]
    return "\n".join(lines)


def merge_apply(env, plan: dict, backup_dir: str, log=print) -> str:
    """Write the backup (`<backup_dir>/<Entity>-<UTC time>.json`: the dropped rows, every pointing row's Id / table / column / old value, the colliding
    rows whole), then run the plan's statements one clio call each, `log`ging `affected: N` per statement. A failed statement stops and names the
    backup. Returns the backup path."""
    import json
    from pathlib import Path
    path = Path(backup_dir) / f"{plan['entity']}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entity": plan["entity"], "keep": plan["keep"], "dropped": plan["rows"],
                                "pointing": [{"table": t["table"], "column": t["column"], **p} for t in plan["targets"] for p in t["pointing"]],
                                "collidingRows": [{"table": t["table"], "row": r} for t in plan["targets"] for r in t["collide"]]},
                               indent=2, default=str), encoding="utf-8")
    log(f"backup: {path}")
    for s in plan["statements"]:
        counts: list = []
        try:
            env.sql(s["sql"], counts=counts)
        except RuntimeError as e:
            raise RuntimeError(f"{e} (statement: {s['sql']}; the backup is {path})") from None
        log(f"{s['sql']}\n  affected: {counts[0] if counts else '?'}")
    return str(path)


def _named(env, table: str, rows: list[dict], zone: str | None) -> list[dict]:
    """The rows with each lookup value as {id, name} (through the table's foreign keys) and times in UTC and the zone."""
    refs = {f["column"]: f["ref_table"] for f in foreign_keys(env, table)}
    names = {col: names_of(env, ref, [str(r[col]) for r in rows if r.get(col)]) for col, ref in refs.items() if any(r.get(col) for r in rows)}
    out = []
    for r in rows:
        shown = {}
        for k, v in r.items():
            if k in names and v:
                shown[k] = {"id": v, "name": names[k].get(str(v).lower())}
            elif k.endswith("On") and v:
                shown[k] = local_time(v, zone)
            else:
                shown[k] = v
        out.append(shown)
    return out


def _cell(value) -> str:
    if isinstance(value, dict):
        return f"{value['name']} ({value['id']})" if value.get("name") else str(value["id"])
    return str(value)


def render_hits(hits: list[dict]) -> str:
    if not hits:
        return "(no table holds this Id)"
    lines = []
    for h in hits:
        caption = ", ".join(f"{k} = {v}" for k, v in h["caption"].items())
        lines.append(f"{h['table']}" + (f"  {caption}" if caption else ""))
        lines.append(f"  created  {h['createdOn']}" + (f" by {h['createdBy']}" if h["createdBy"] else ""))
        lines.append(f"  modified {h['modifiedOn']}" + (f" by {h['modifiedBy']}" if h["modifiedBy"] else ""))
    return "\n".join(lines)


def render_context(context: dict) -> str:
    lines = [f"{context['entity']} {context['id']}"] + [f"  {k} = {_cell(v)}" for k, v in context["columns"].items()]
    for d in context["details"]:
        lines.append(f"{d['table']}.{d['column']}: {d['count']} row(s)" + (f", first {len(d['rows'])}" if d["count"] > len(d["rows"]) else ""))
        lines += ["  " + "  ".join(f"{k}={_cell(v)}" for k, v in r.items()) for r in d["rows"]]
    if not context["details"] and context.get("depth", 1):  # depth 0 did not look
        lines.append("(no other table has a row pointing at this record)")
    return "\n".join(lines)


# -- the change log: Sys<Entity>Log ----------------------------------------------------------------- #
# One row per change, a snapshot of the whole record after it: `ChangeTrackedId` is the record, `ChangeTrackedOn` / `ChangeTrackedById` when and
# who, `ChangeTypeId` -> `SysEntityChangeType` (Inserted, Updated, Deleted), the other columns the record's own (a lookup is logged by its text).
LOG_META = {"id", "changetrackedon", "changetrackedbyid", "changetypeid", "clientip", "changetrackedid", "createdon", "createdby",
            "modifiedon", "modifiedby", "processlisteners"}
LOG_ROWS = 50000  # the most rows `column_transitions` reads


def log_table(env, entity: str) -> str:
    """`Sys<Entity>Log`, the table the change log of an object writes to; ValueError `change tracking is off for <Entity>` when the site has none."""
    table = f"Sys{ident(entity)}Log"
    if not env.sql(f"select table_name from information_schema.tables where table_name = '{table}'"):
        raise ValueError(f"change tracking is off for {entity} (the site has no table {table}; switch the log on in the object designer)")
    return table


def _change_types(env) -> dict[str, str]:
    return {str(r["Id"]).lower(): r.get("Name") for r in env.sql('select "Id", "Name" from "SysEntityChangeType"')}


def _moment(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _shown(value) -> str:
    return "(empty)" if value in (None, "") else str(value)


def _wants(column: str, wanted: str) -> bool:
    return not wanted or column.lower() in (wanted.lower(), wanted.lower() + "id") or (wanted.lower().endswith("id") and column.lower() == wanted.lower()[:-2])


def record_history(env, record: str, column: str = "", clusters: int = 0, zone: str | None = None) -> dict:
    """{entity, id, changes [{at, by, type, columns [(name, was, became)], cluster [{id, caption, at, type, ms}]}]}: the change-log rows of one record
    (`record` = `<Entity>:<Id>`), oldest first. A row is the whole record after a change, so `was` is the column in the row before; an insert shows
    every column that has a value. `column` keeps one column (the rows that changed it). `clusters` (milliseconds) lists, for each change, the other
    records of the entity logged by the same user within that many milliseconds of it."""
    entity, _, record_id = record.partition(":")
    entity, record_id = ident(entity.strip()), guid(record_id.strip())
    table = log_table(env, entity)
    rows = env.sql(f'select * from "{table}" where "ChangeTrackedId" = \'{record_id}\' order by "ChangeTrackedOn"')
    types, who = _change_types(env), names_of(env, "Contact", [str(r.get("ChangeTrackedById")) for r in rows if r.get("ChangeTrackedById")])
    changes, previous = [], None
    for r in rows:
        kind = types.get(str(r.get("ChangeTypeId")).lower()) or "?"
        cols = [(k, None if previous is None else previous.get(k), v) for k, v in r.items()
                if k.lower() not in LOG_META and _wants(k, column) and (previous is None and v not in (None, "") or previous is not None and previous.get(k) != v)]
        changes.append({"at": local_time(r.get("ChangeTrackedOn"), zone), "moment": _moment(r.get("ChangeTrackedOn")),
                        "by": who.get(str(r.get("ChangeTrackedById")).lower()) or r.get("ChangeTrackedById"), "by_id": str(r.get("ChangeTrackedById")).lower(),
                        "type": kind, "columns": cols, "cluster": []})
        previous = r
    if column:
        changes = [c for c in changes if c["columns"]]
    if clusters and changes:
        _clusters(env, table, record_id, changes, clusters, types, zone)
    return {"entity": entity, "id": record_id, "changes": changes, "clusters_ms": clusters}


def _clusters(env, table: str, record_id: str, changes: list[dict], ms: int, types: dict, zone: str | None) -> None:
    moments = [c["moment"] for c in changes if c["moment"]]
    if not moments:
        return
    lo, hi = min(moments) - timedelta(milliseconds=ms), max(moments) + timedelta(milliseconds=ms)
    others = env.sql(f'select * from "{table}" where "ChangeTrackedId" <> \'{record_id}\' and "ChangeTrackedOn" between '
                     f"'{lo:%Y-%m-%d %H:%M:%S.%f}' and '{hi:%Y-%m-%d %H:%M:%S.%f}' order by \"ChangeTrackedOn\" offset 0 rows fetch first 1000 rows only")
    for c in changes:
        for o in others:
            at = _moment(o.get("ChangeTrackedOn"))
            if at and c["moment"] and str(o.get("ChangeTrackedById")).lower() == c["by_id"] and abs((at - c["moment"]) / timedelta(milliseconds=1)) <= ms:
                caption = _first(o)[1]
                c["cluster"].append({"id": str(o["ChangeTrackedId"]).lower(), "caption": caption, "at": local_time(o.get("ChangeTrackedOn"), zone),
                                     "type": types.get(str(o.get("ChangeTypeId")).lower()) or "?", "ms": round((at - c["moment"]) / timedelta(milliseconds=1))})


def render_history(answer: dict) -> str:
    changes = answer["changes"]
    lines = [f"{answer['entity']} {answer['id']}: {len(changes)} logged change(s)"]
    for c in changes:
        lines.append(f"{c['at']}  {c['type']} by {c['by'] or '?'}")
        lines += [f"    {name}: " + ("" if was is None else _shown(was) + " ") + f"-> {_shown(became)}" for name, was, became in c["columns"]]
        if answer["clusters_ms"]:
            lines.append(f"    same user within {answer['clusters_ms']} ms: " + (f"{len(c['cluster'])} other record(s)" if c["cluster"] else "none"))
            lines += [f"      {o['id']}  {o['caption'] or ''}  {o['type']}  {o['ms']:+d} ms" for o in c["cluster"][:20]]
            if len(c["cluster"]) > 20:
                lines.append(f"      ... {len(c['cluster']) - 20} more")
    if not changes:
        lines.append("(the log holds no row for this record" + (" that changed that column)" if answer.get("column") else ")"))
    return "\n".join(lines)


def column_transitions(env, target: str, from_value: str | None = None, to_value: str | None = None, since: str | None = None,
                       zone: str | None = None) -> dict:
    """{entity, column, rows [{record, at, by, type, from, to}]}: every change of one column (`target` = `<Entity>.<Column>`) in the entity's change
    log, over all records, oldest first. `from_value` / `to_value` (case-blind, `` = empty) keep matching transitions; `since` (2026-11-01 or
    2026-11-01T08:00, UTC) keeps the later ones. The first row of a record is a transition from empty when it is an insert. A lookup is logged by its
    text, so it reads as the log has it. Reads at most `LOG_ROWS` rows (`truncated` says so)."""
    entity, _, column = target.partition(".")
    entity, column = ident(entity.strip()), ident(column.strip())
    table = log_table(env, entity)
    if not env.sql(f"select column_name from information_schema.columns where table_name = '{table}' and column_name = '{column}'"):
        have = [r["column_name"] for r in env.sql(f"select column_name from information_schema.columns where table_name = '{table}' order by ordinal_position")]
        raise ValueError(f"{table} has no column {column}; it has {', '.join(c for c in have if c.lower() not in LOG_META)}")
    rows = env.sql(f'select "ChangeTrackedId", "ChangeTrackedOn", "ChangeTrackedById", "ChangeTypeId", "{column}" as "value" from "{table}" '
                   f'order by "ChangeTrackedId", "ChangeTrackedOn" offset 0 rows fetch first {LOG_ROWS} rows only')
    types = _change_types(env)
    floor = _moment(since.strip().replace("Z", "")) if since else None
    if since and floor is None:
        raise ValueError(f"{since!r} is not a date (2026-11-01 or 2026-11-01T08:00)")
    found, previous = [], {}
    for r in rows:
        record, value, at = str(r["ChangeTrackedId"]).lower(), r.get("value"), _moment(r.get("ChangeTrackedOn"))
        kind = types.get(str(r.get("ChangeTypeId")).lower()) or "?"
        if record in previous:
            old = previous[record]
        elif kind == "Inserted":
            old = None
        else:
            previous[record] = value  # a log that starts after the record: this row is the baseline
            continue
        previous[record] = value
        if old == value or (old in (None, "") and value in (None, "")):
            continue
        found.append({"record": record, "moment": at, "at": local_time(r.get("ChangeTrackedOn"), zone), "by_id": str(r.get("ChangeTrackedById")).lower(),
                      "type": kind, "from": "" if old is None else str(old), "to": "" if value is None else str(value)})
    keep = [t for t in found if (from_value is None or t["from"].lower() == from_value.lower()) and (to_value is None or t["to"].lower() == to_value.lower())
            and (floor is None or (t["moment"] and t["moment"] >= floor))]
    keep.sort(key=lambda t: t["moment"] or datetime.min)
    who = {}
    ids = sorted({t["by_id"] for t in keep if t["by_id"] not in ("", "none")})
    for i in range(0, len(ids), 200):
        who.update(names_of(env, "Contact", ids[i:i + 200]))
    for t in keep:
        t["by"] = who.get(t["by_id"]) or t["by_id"]
    return {"entity": entity, "column": column, "rows": keep, "truncated": len(rows) >= LOG_ROWS}


def write_csv(path: str, header: list[str], rows: list[list]) -> str:
    """A UTF-8 CSV with a BOM and `;` (what a spreadsheet opens as is); returns the path."""
    import csv
    from pathlib import Path
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)
    return str(target)


def transitions_csv(answer: dict, path: str) -> str:
    return write_csv(path, ["at", "record", "from", "to", "by", "type"],
                     [[t["at"], t["record"], t["from"], t["to"], t["by"], t["type"]] for t in answer["rows"]])


def render_transitions(answer: dict, limit: int = 40) -> str:
    rows = answer["rows"]
    lines = [f"{answer['entity']}.{answer['column']}: {len(rows)} transition(s)" + (" (the log has more rows than were read: narrow with since=)" if answer["truncated"] else "")]
    lines += [f"{t['at']}  {t['record']}  {_shown(t['from'])} -> {_shown(t['to'])}  by {t['by']}" for t in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"  ... {len(rows) - limit} more; add out=<file.csv> for all")
    return "\n".join(lines)
