"""`pages.py audit` (S27-T06): what makes a Freedom page slow, as counts with thresholds. Read-only."""

from __future__ import annotations

import re

from .schema import PageSchema

# one place for the numbers; a finding is printed when its count is OVER the threshold (disabled / duplicated / timers: any)
THRESHOLDS = {"tab_elements": 80, "joins": 3, "comboboxes": 25, "page_rules": 20, "object_rules": 20, "object_columns": 100}

CONTAINERS = ("crt.TabContainer",)  # an element is counted under its nearest tab
TIMER = re.compile(r"\b(setTimeout|setInterval)\b")
FILTER_KEYS = ("filter", "filters", "PredefinedFilter", "predefinedFilter")


def _tab_of(pg: PageSchema, name: str, by_name: dict[str, dict]) -> str | None:
    """The nearest ancestor that is a tab (type crt.TabContainer / crt.Tab...), or None."""
    seen = set()
    while name and name not in seen:
        seen.add(name)
        op = by_name.get(name) or {}
        if (op.get("values") or {}).get("type") in CONTAINERS:
            return name
        name = op.get("parentName")
    return None


def _joins(pg: PageSchema, path: str) -> int:
    """Tables a `DS.A.B.Column` path walks through: the segments between the data source and the column."""
    parts = path.split(".")
    if parts and parts[0] in pg.data_sources:
        parts = parts[1:]
    return max(len(parts) - 1, 0)


def _has_filter(pg: PageSchema, attr: dict) -> bool:
    mc = attr.get("modelConfig") or {}
    if any(mc.get(k) for k in FILTER_KEYS) or mc.get("filterAttributes"):
        return True
    ds_name = (mc.get("path") or "").split(".")[0]
    if pg.dependencies.get(ds_name):
        return True
    ds = pg.data_sources.get(ds_name) or {}
    return any((ds.get("config") or {}).get(k) for k in FILTER_KEYS)


def _rule_counts(pg: PageSchema, addon: str):
    """(rules, disabled, filter rules, duplicates) of `<addon>` in the workspace, or None when it is not there."""
    from ..describe.core import open_item
    from ..rules.model import T_FILTER_LOOKUP, T_SET_FILTER, walk

    for hit in pg.workspace.find(addon, "AddonSchemaManager"):
        try:
            rs = open_item(hit["dir"].parent.parent, addon)
            filters = sum(1 for r in rs.rules if any(i.get("JI0") in (T_FILTER_LOOKUP, T_SET_FILTER) for i in walk(r)))
            dups = sum(1 for p in rs.duplicates() if "duplicate rule name" in p or "times" in p)
            return len(rs.rules), sum(1 for r in rs.rules if not r.get("BR4", True)), filters, dups
        except Exception:  # an unreadable addon costs its own line
            continue
    return None


def audit(pg: PageSchema, show_all: bool = False, t: dict | None = None) -> list[str]:
    """The finding lines (every count with `show_all`); the caller prints the last line and picks the exit code."""
    t = {**THRESHOLDS, **(t or {})}
    out: list[str] = []

    def put(over: bool, line: str) -> None:
        if over or show_all:
            out.append(line)

    ops = pg.elements()
    by_name = {op["name"]: op for op in ops}
    per_tab: dict[str, int] = {}
    for op in ops:
        tab = _tab_of(pg, op.get("parentName") or "", by_name) or "(no tab)"
        per_tab[tab] = per_tab.get(tab, 0) + 1
    for tab, n in sorted(per_tab.items(), key=lambda kv: -kv[1]):
        put(n > t["tab_elements"], f"elements {n} on tab {tab}")

    for op in ops:
        v = op.get("values") or {}
        if v.get("type") != "crt.DataGrid":
            continue
        key = str(v.get("items") or "").lstrip("$")
        attr = pg.attributes.get(key) or {}
        ds_name = ((attr.get("modelConfig") or {}).get("path") or "").split(".")[0]
        ds = pg.data_sources.get(ds_name) or {}
        if ds_name == pg.primary or ds.get("scope") == "page":  # the page's own list, not a detail of a record
            continue
        entity = (ds.get("config") or {}).get("entitySchemaName", "?")
        put(not _has_filter(pg, attr), f"grid {op['name']} ({entity}): no master filter (accepted: a `dependencies` entry of its data source in modelConfigDiff, `filterAttributes` or a filter on its attribute, a `filter` / `PredefinedFilter` on its data source)")

    deep = 0
    for k, a in pg.attributes.items():
        path = pg._attr_path(k)
        n = _joins(pg, path) if path else 0
        deep += n >= 2
        put(n >= t["joins"], f"attribute {k}: path {path} ({n} joins)")
    put(deep > 0, f"attributes through 2+ joins: {deep}")

    combos = sum(1 for op in ops if (op.get("values") or {}).get("type") == "crt.ComboBox")
    put(combos > t["comboboxes"], f"comboboxes {combos}")

    page_rules = _rule_counts(pg, pg.name + "BusinessRule")
    if page_rules:
        n, off, _, _ = page_rules
        put(n > t["page_rules"] or off, f"page rules {n} ({off} disabled)")
    entity = pg.entity
    obj_rules = _rule_counts(pg, entity + "BusinessRule") if entity else None
    if obj_rules:
        n, off, fil, dup = obj_rules
        put(n > t["object_rules"] or off or dup, f"object rules {n} ({off} disabled, {fil} filter rules, {dup} duplicates)")
    if entity:
        try:
            cols = len(pg.workspace.columns(entity))
        except Exception:
            cols = 0
        put(cols > t["object_columns"], f"object columns {cols} (workspace layers)")

    handlers = pg.handlers()
    size = sum(len(src.encode("utf-8")) for _, src in handlers)
    timers = sum(len(TIMER.findall(src)) for _, src in handlers)
    put(timers > 0, f"handlers {len(handlers)}, {size} bytes; setTimeout/setInterval {timers}")
    return out
