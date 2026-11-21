"""S33-T10: the lookup rows a workspace's data bindings do not hold, named from the site.

`describe_schema <Process> env=<name>` and `describe_item ... env=<name>` print `UsrStatus = Done (0042909f-...)` also for a
row of a base package (`OpportunityStage`, `CaseStatus`) or one filled by hand on the site. The lookup table of each GUID is
known from the process itself - the column the filter or the Modify / Add data element sets - and each table is read once per
call, `select "Id", "Name" from "<Table>" where "Id" in (...)`, through `Environment.sql`. Read-only. A GUID the site does not
know either, or a table without a `Name`, stays bare.
"""

from __future__ import annotations

import re

from ..filters import load
from ..records import CHUNK, ident

GUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")


class SiteNames:
    """Row names read from a site: {row Id (lower case): Name}, asked once per (table, Id)."""

    def __init__(self, env):
        self.env, self.names, self.errors = env, {}, []
        self._asked: set[tuple[str, str]] = set()

    def fetch(self, wanted: dict[str, set[str]]) -> None:
        """`wanted` = {table: {row Ids}}; one statement per table (more past 50 Ids)."""
        for table, ids in sorted(wanted.items()):
            todo = sorted(i.lower() for i in ids if (table, i.lower()) not in self._asked)
            for i in range(0, len(todo), CHUNK):
                chunk = todo[i:i + CHUNK]
                self._asked.update((table, c) for c in chunk)
                try:
                    rows = self.env.sql(f'select "Id", "Name" from "{ident(table)}" where "Id" in (' + ", ".join(f"'{c}'" for c in chunk) + ")")
                except (RuntimeError, ValueError) as exc:  # a table without Name, an Id that is not a uuid: those GUIDs stay bare
                    self.errors.append(f"{table}: {exc.args[0] if exc.args else exc}")
                    continue
                self.names.update({str(r["Id"]).lower(): str(r["Name"]) for r in rows if r.get("Name")})

    def note(self) -> str:
        """One line when the site could not name anything it was asked about (so a bare GUID is not mistaken for an unknown row)."""
        return f"(site names not read: {self.errors[0]})" if self.errors and not self.names else ""


def filter_ids(ps, element: dict) -> dict[str, set[str]]:
    """{lookup table: {row Ids}} the element's record filter compares lookup columns with."""
    param = next((p for p in ps.element_params(element) if p["A2"] == "DataSourceFilters"), None)
    group = load(((param or {}).get("L8") or {}).get("GS2"))
    if not group or "rootSchemaName" not in group:
        return {}
    wanted: dict[str, set[str]] = {}

    def walk(g: dict) -> None:
        for item in (g.get("items") or {}).values():
            if "items" in item:
                walk(item)
                continue
            table = _reference(ps, group["rootSchemaName"], (item.get("leftExpression") or {}).get("columnPath", ""))
            if not table:
                continue
            for r in item.get("rightExpressions") or ([item["rightExpression"]] if item.get("rightExpression") else []):
                v = (r.get("parameter") or {}).get("value")
                v = v.get("value") if isinstance(v, dict) else v
                if isinstance(v, str) and GUID.fullmatch(v):
                    wanted.setdefault(table, set()).add(v.lower())

    walk(group)
    return wanted


def _reference(ps, entity: str, path: str) -> str | None:
    """The lookup table a column path ends in (`UsrStatus`, `Owner.Account`), through the workspace's own objects."""
    table = entity
    for part in path.split(".") if path else []:
        kind, ref = ps.workspace.columns(table).get(part, (None, None))
        if not ref:
            return None
        table = ref
    return table if table != entity else None


def values_ids(ps, element: dict) -> dict[str, set[str]]:
    """{lookup table: {row Ids}} a Modify / Add data element writes into lookup columns."""
    _, entity, _ = ps._record_target(element)
    columns = ps.workspace.columns(entity)
    wanted: dict[str, set[str]] = {}
    for column, value in ps.record_values(element):
        kind, ref = columns.get(column, (None, None))
        if kind == "Lookup" and ref and GUID.fullmatch(value.strip()):
            wanted.setdefault(ref, set()).add(value.strip().lower())
    return wanted


def process_ids(ps) -> dict[str, set[str]]:
    """Every lookup row Id the process shows, by table, minus the rows the workspace already names."""
    from .schema import RECORD_VALUES, short_type

    known = ps.workspace.lookup_captions()
    wanted: dict[str, set[str]] = {}
    for e in ps.nodes():
        if short_type(e) != "ProcessSchemaUserTask":
            continue
        for found in (_safe(filter_ids, ps, e), _safe(values_ids, ps, e) if e.get("J6") in RECORD_VALUES else {}):
            for table, ids in found.items():
                wanted.setdefault(table, set()).update(i for i in ids if i not in known)
    return {t: ids for t, ids in wanted.items() if ids}


def _safe(fn, ps, element) -> dict[str, set[str]]:
    try:
        return fn(ps, element)
    except (ValueError, KeyError, TypeError, AttributeError):  # an element the toolkit cannot read costs its own lines
        return {}
