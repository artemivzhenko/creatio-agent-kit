"""A Classic page over every layer, site layers included (S48-T08): the grid of one container and the business rules.

    layer_bodies(package, name, env)    (package, workspace|site, body, replacing) of each copy, first to last (`describe/merge.layers_in_order`):
                                        a copy in the workspace is read from its file, a copy only on the site through `describe/body`
    chain_bodies(package, name, env)    the same for the parent chain first (`<Parent>:<package>`), then the schema's own layers
    layout_lines(package, name, container, env)   the container's grid after every layer's diff (insert, merge of `layout`, move, remove),
                                        the parent chain's layers included
    rule_lines(package, name, env, rule)          every rule of `businessRules` and `rules` over the layers, merged by column and key
    grid_lines(cells, columns, first)   one line per grid row: the column ranges with the element in them, `free` where nothing is

Read-only. The fold is `page/fold.fold`, the reader the Classic parser over a text (`methods.view`).
"""

from __future__ import annotations

from pathlib import Path

from ..files import read_text
from ..page.fold import _deep, fold
from .methods import view
from .schema import _close

CLIENT = "ClientUnitSchemaManager"
CLASSIC_COLUMNS = 24  # a Classic GRID_LAYOUT is 24 columns wide


def layer_bodies(package, name: str, env=None) -> list[tuple[str, str, str, bool]]:
    from ..describe.body import copies, read
    from ..describe.merge import layers_in_order

    layers = layers_in_order(Path(package).parent, name, env, CLIENT)
    ids = {r["package"]: r["id"] for r in copies(env, name)} if env is not None and any(x.folder is None for x in layers) else {}
    out = []
    for x in layers:
        if x.folder is not None and (x.folder / f"{name}.js").is_file():
            out.append((x.package, "workspace", read_text(x.folder / f"{name}.js")[0], x.replacing))
        elif x.package in ids:
            out.append((x.package, "site", read(env, ids[x.package]), x.replacing))
    if not out:
        raise KeyError(f"no copy of {name} in the workspace" + ("" if env is not None else " - pass --env to read the site's copies"))
    return out



PARENT_SQL = """select ps."Name"::text "parent" from "SysSchema" s join "SysSchema" ps on ps."Id" = s."ParentId"
where s."Name" = {name} and not s."ExtendParent" and s."ManagerName" = 'ClientUnitSchemaManager' limit 1"""


def _parent(package, name: str, env=None) -> str | None:
    """The parent schema of `name`'s own copy: the site's `SysSchema.ParentId`, else the workspace descriptor's `Parent`."""
    import json

    from ..describe.merge import layers_in_order
    from ..records import quote

    if env is not None:
        rows = env.sql(PARENT_SQL.format(name=quote(name)))
        return rows[0]["parent"] if rows else None
    own = [x for x in layers_in_order(Path(package).parent, name, None, CLIENT) if not x.replacing and x.folder is not None]
    return (json.loads(read_text(own[0].folder / "descriptor.json")[0].lstrip("﻿"))["Descriptor"].get("Parent") or {}).get("Name") if own else None


def chain_bodies(package, name: str, env=None) -> list[tuple[str, str, str, bool]]:
    """`layer_bodies` of the parent chain, the farthest parent first, then of `name`: a parent's diff is applied before the child's
    (a Classic `Header` is filled by the parent page). A parent's layers are named `<Parent>:<package>`; a parent with no copy read is skipped."""
    names, parent = [name], _parent(package, name, env)
    while parent and parent not in names and len(names) < 12:
        names.append(parent)
        parent = _parent(package, parent, env)
    out = []
    for n in reversed(names):
        try:
            bodies = layer_bodies(package, n, env)
        except KeyError:
            if n == name:
                raise
            continue
        out += [(p if n == name else f"{n}:{p}", w, t, r) for p, w, t, r in bodies]
    return out

def _int(text: str):
    try:
        return int(text)
    except (TypeError, ValueError):
        return text


def _ops(c) -> list[dict]:
    """The diff operations of one layer with `values` reduced to the `layout` cell (numbers), what the grid needs."""
    out = []
    for op in c.diff_operations():
        members = c._object(op["at"])
        values = c._object(members["values"][0]) if "values" in members else {}
        lay = c._object(values["layout"][0]) if "layout" in values else {}
        out.append({**{k: op[k] for k in ("operation", "name", "parentName", "propertyName", "index")},
                    "values": {"layout": {k: _int(c._literal(*v)) for k, v in lay.items()}} if lay else {}})
    return out


def grid_lines(cells: list[tuple], columns: int, first: int) -> list[str]:
    """cells: (name, row, column, colSpan, rowSpan), counted from `first` (Classic 0, Freedom 1)."""
    grid: dict[tuple[int, int], list[str]] = {}
    for name, r, c, cs, rs in cells:
        for y in range(r, r + rs):
            for x in range(c, c + cs):
                grid.setdefault((y, x), []).append(name)
    last_col = max([first + columns - 1] + [x for _, x in grid])
    out: list[tuple[int, str, int]] = []  # (first row, cells, last row)
    for y in range(first, max((r + rs for _, r, _, _, rs in cells), default=first)):
        parts, x = [], first
        while x <= last_col:
            who, end = grid.get((y, x), []), x
            while end < last_col and grid.get((y, end + 1), []) == who:
                end += 1
            label = ("+".join(who) + (" (overlap)" if len(who) > 1 else "")) if who else "free"
            parts.append(f"{x}-{end} {label}" if end > x else f"{x} {label}")
            x = end + 1
        empty = f"{first}-{last_col} free"
        if parts == [empty] and out and out[-1][1] == empty:
            out[-1] = (out[-1][0], empty, y)  # empty rows in a run print as one line
        else:
            out.append((y, " | ".join(parts), y))
    return [f"  row {a}: {text}" if a == b else f"  rows {a}-{b}: {text}" for a, text, b in out]


def _layers(layers: list) -> str:
    return f"{len(layers)} layer{'' if len(layers) == 1 else 's'}"


def render_layout(name: str, container: str, layers: list, folded: dict, last: dict, key: str, columns: int | None, first: int,
                  base_read: bool) -> list[str]:
    """The head, the grid and one line per element of `container` with the layer that placed it last."""
    cells, loose = [], []
    for n, e in folded.items():
        if e.get("removed") or e.get("parent") != container:
            continue
        lay = e["values"].get(key)
        if isinstance(lay, dict) and isinstance(lay.get("row"), int) and isinstance(lay.get("column"), int):
            cells.append((n, lay["row"], lay["column"], lay.get("colSpan") if isinstance(lay.get("colSpan"), int) else 1,
                          lay.get("rowSpan") if isinstance(lay.get("rowSpan"), int) else 1))
        else:
            loose.append(n)
    if not cells and not loose:
        raise KeyError(f"nothing is placed in {container} in the layers read ({', '.join(p for p, *_ in layers)})"
                       + ("" if base_read else " - the base copy is on the site: pass --env"))
    columns = columns or max((c + cs - first for _, _, c, cs, _ in cells), default=0)
    chain = " > ".join(p + (" (site)" if w == "site" else "") for p, w, *_ in layers)
    lines = [f"{name}.{container} over {_layers(layers)} ({chain}), {columns} columns, the last layer wins"
             + ("" if base_read else "; the base copy was not read (pass --env)")]
    lines += grid_lines(cells, columns, first)
    for n, r, c, cs, rs in sorted(cells, key=lambda x: (x[1], x[2])):
        lines.append(f"  {n}  row {r} col {c} span {cs}x{rs}  (placed last in {last.get(n, '?')})")
    if loose:
        lines.append(f"  in {container} without a {key} cell: {', '.join(loose)}")
    return lines


def layout_lines(package, name: str, container: str = "Header", env=None) -> list[str]:
    layers = chain_bodies(package, name, env)
    ops, last = [], {}
    for pkg, _, text, _ in layers:
        for op in _ops(view(text, name)):
            ops.append(op)
            if op["name"] and (op["operation"] in ("insert", "move") or op["values"]):
                last[op["name"]] = pkg
    return render_layout(name, container, layers, fold(ops), last, "layout", CLASSIC_COLUMNS, 0, any(not x[3] for x in layers))


# -- rules ------------------------------------------------------------------------------------------------------------- #

RULE_TYPES = {"0": "BINDPARAMETER", "1": "FILTRATION"}
PROPERTIES = {"0": "VISIBLE", "1": "ENABLED", "2": "REQUIRED", "3": "READONLY"}
COMPARISONS = {str(i): n for i, n in enumerate("BETWEEN IS_NULL IS_NOT_NULL EQUAL NOT_EQUAL LESS LESS_OR_EQUAL GREATER GREATER_OR_EQUAL START_WITH "
                             "NOT_START_WITH CONTAIN NOT_CONTAIN END_WITH NOT_END_WITH EXISTS NOT_EXISTS".split())}
_SYMBOL = {"EQUAL": "=", "NOT_EQUAL": "!=", "LESS": "<", "LESS_OR_EQUAL": "<=", "GREATER": ">", "GREATER_OR_EQUAL": ">="}


def _tree(c, a: int, b: int):
    """A literal as data: objects as dicts, arrays of objects as lists, anything else as `_literal` text."""
    if c.masked[a:a + 1] == "{":
        return {k: _tree(c, va, vb) for k, _, va, vb in c._members(a)}
    if c.masked[a:a + 1] == "[":
        items, i, end = [], a + 1, _close(c.masked, a) - 1
        while i < end:
            if c.masked[i] == "{":
                j = _close(c.masked, i)
                items.append(_tree(c, i, j))
                i = j
            elif c.masked[i] == "[":
                i = _close(c.masked, i)
            else:
                i += 1
        return items
    return c._literal(a, b)


def _name(value, numbers: dict) -> str:
    """`3` -> EQUAL, `Terrasoft.ComparisonType.EQUAL` -> EQUAL."""
    text = str(value)
    return numbers.get(text, text.rsplit(".", 1)[-1])


def _expr(e) -> str:
    if not isinstance(e, dict):
        return "?"
    if "attribute" in e:
        return e["attribute"] + (f".{e['attributePath']}" if e.get("attributePath") else "")
    return repr(e["value"]) if "value" in e else "?"


def _condition(cond: dict) -> str:
    cmp = _name(cond.get("comparisonType", "?"), COMPARISONS)
    right = cond.get("rightExpression")
    return f"{_expr(cond.get('leftExpression'))} {_SYMBOL.get(cmp, cmp)}" + (f" {_expr(right)}" if right else "")


def _state(p: dict) -> str:
    """The same reading as `describe/layers.rule_state`, over props already parsed."""
    return "removed" if p.get("removed") == "true" else "disabled" if p.get("enabled") == "false" else "enabled"


def rules_over(package, name: str, env=None) -> tuple[list, dict]:
    """(layers, {(section, column, key): {"props": merged, "layers": [(package, state after it)]}}) in first-met order."""
    layers = layer_bodies(package, name, env)
    rules: dict[tuple, dict] = {}
    for pkg, _, text, _ in layers:
        c = view(text, name)
        for section in ("businessRules", "rules"):
            span = c.sections.get(section)
            columns = _tree(c, *span) if span else {}
            for column, by_key in (columns.items() if isinstance(columns, dict) else []):
                for key, props in (by_key.items() if isinstance(by_key, dict) else []):
                    if not isinstance(props, dict):
                        continue
                    r = rules.setdefault((section, column, key), {"props": {}, "layers": []})
                    _deep(r["props"], props)
                    r["layers"].append((pkg, _state(r["props"])))
    return layers, rules


def rule_lines(package, name: str, env=None, rule: str | None = None) -> list[str]:
    layers, rules = rules_over(package, name, env)
    if rule:
        rules = {k: v for k, v in rules.items() if rule.lower() in (k[2].lower(), str(v["props"].get("uId", "")).lower())}
        if not rules:
            raise KeyError(f"no rule {rule} in the layers of {name} ({', '.join(p for p, *_ in layers)})")
    chain = " > ".join(p + (" (site)" if w == "site" else "") for p, w, *_ in layers)
    lines = [f"{name}: {len(rules)} rule(s) over {_layers(layers)} ({chain}); column, UId, kind, state, conditions, filter, layers"]
    for (section, column, key), r in rules.items():
        p = r["props"]
        kind = _name(p.get("ruleType", "?"), RULE_TYPES)
        if kind == "BINDPARAMETER" and "property" in p:
            kind += " " + _name(p["property"], PROPERTIES)
        line = f"  {column}  {p.get('uId') or key}  {kind}  {_state(p)}" + ("  (rules section)" if section == "rules" else "")
        conds = p.get("conditions")
        if isinstance(conds, list) and conds:
            logical = " OR " if str(p.get("logical", "")).rsplit(".", 1)[-1] in ("1", "OR") else " AND "
            line += "  when " + logical.join(_condition(x) for x in conds if isinstance(x, dict))
        if kind == "FILTRATION":
            cmp = _name(p.get("comparisonType", "3"), COMPARISONS)
            line += (f"  filter {column}.{p.get('baseAttributePatch', '?')} {_SYMBOL.get(cmp, cmp)} {_expr(p)}"
                     + "".join(f", {f}" for f in ("autoClean", "autocomplete") if p.get(f) == "true"))
        defined = changed = r["layers"][0][0]
        before = None
        for pkg, st in r["layers"]:
            changed, before = (pkg if st != before else changed), st
        lines.append(line + f"  defined in {defined}, state last changed in {changed}  layers: " + " > ".join(f"{pkg} {st}" for pkg, st in r["layers"]))
    return lines
