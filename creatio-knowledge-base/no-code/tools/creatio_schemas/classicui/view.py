"""`where` and `map` of a Classic UI schema, from its diff operations (S31-T08).

The same answers the Freedom page topics give: an element's caption (a `Resources.Strings` key, a literal, else the caption of the
column it binds), its control, the `parentName` chain up to the page root with captions, the `layout` cell, and the layer; the page
as a tree of its inserts. A detail is named with its schema, object and the column it filters by.
"""

from __future__ import annotations

import difflib

from ..resources import Resources

_TYPE_PREFIXES = ("Terrasoft.ViewItemType.", "Terrasoft.ContentType.", "Terrasoft.DataValueType.")


# Terrasoft.ViewItemType / Terrasoft.ContentType of the 8.3.2 core (Resources/ui/Terrasoft/core/enums/sysenums.js): a diff may hold the number
ITEM_TYPES = dict(enumerate("GRID_LAYOUT TAB_PANEL DETAIL MODEL_ITEM MODULE BUTTON LABEL CONTAINER MENU MENU_ITEM MENU_SEPARATOR SECTION_VIEWS "
                            "SECTION_VIEW GRID SCHEDULE_EDIT CONTROL_GROUP RADIO_GROUP DESIGN_VIEW COLOR_BUTTON IMAGE_TAB_PANEL HYPERLINK "
                            "INFORMATION_BUTTON TIP COMPONENT TIP_LABEL".split())) | {30: "PROGRESS_BAR", 31: "GRID_LAYOUT_EDIT", 32: "IFRAMECONTROL",
                                                                                     33: "EXTERNAL_WIDGET"}
CONTENT_TYPES = dict(enumerate("LONG_TEXT SHORT_TEXT DATE_TIME ENUM RICH_TEXT LOOKUP SEARCHABLE_TEXT".split()))


def _short(value: str | None, numbers: dict | None = None) -> str | None:
    if value and value.isdigit() and numbers is not None:
        return numbers.get(int(value), value)
    for p in _TYPE_PREFIXES:
        if value and value.startswith(p):
            return value[len(p):]
    return value


class View:
    """The diff of one Classic schema read for captions; `culture` is the one the captions are printed in."""

    def __init__(self, c, culture: str):
        self.c, self.culture = c, culture
        self.ops = c.diff_operations()
        self._entity_captions: dict[str, dict[str, str]] = {}

    def values(self, op: dict) -> dict[str, tuple[int, int]]:
        members = self.c._object(op["at"])
        return self.c._object(members["values"][0]) if "values" in members else {}

    def literal(self, vals: dict, key: str) -> str | None:
        return self.c._literal(*vals[key]) if key in vals else None

    def bind(self, vals: dict, key: str) -> str | None:
        """The `bindTo` of `{bindTo: "..."}` under `key`, else None."""
        inner = self.c._object(vals[key][0]) if key in vals else {}
        return self.c._literal(*inner["bindTo"]) if "bindTo" in inner else None

    def string(self, ref: str | None) -> str | None:
        if ref and ref.startswith("Resources.Strings."):
            return self.c.resources.get(f"LocalizableStrings.{ref[len('Resources.Strings.'):]}.Value", self.culture)
        return None

    def column_caption(self, entity: str | None, column: str | None) -> str | None:
        if not entity or not column:
            return None
        if entity not in self._entity_captions:
            out = {}
            for hit in self.c.workspace.find(entity, "EntitySchemaManager"):
                res = Resources(hit["dir"].parent.parent / "Resources" / f"{entity}.Entity")
                for key in res.ordered_keys(self.culture):
                    if key.startswith("Columns.") and key.endswith(".Caption"):
                        out.setdefault(key[len("Columns."):-len(".Caption")], res.get(key, self.culture) or "")
            self._entity_captions[entity] = out
        return self._entity_captions[entity].get(column) or None

    def element(self, name: str) -> dict:
        """{name, caption, type, column, column_caption, position, parent} of the insert of `name` (empty when not inserted here)."""
        op = next((o for o in self.ops if o["name"] == name and o["operation"] == "insert"), None)
        if op is None:
            return {}
        vals = self.values(op)
        caption = self.bind(vals, "caption")
        text = self.string(caption) if caption else self.literal(vals, "caption")
        column = self.bind(vals, "bindTo") or (self.literal(vals, "bindTo") if "bindTo" in vals else None)
        etype = _short(self.literal(vals, "itemType"), ITEM_TYPES) or _short(self.literal(vals, "contentType"), CONTENT_TYPES)
        etype = etype or ("field" if column else None)
        column_caption = self.column_caption(self.c.entity, column)
        lay = self.c._object(vals["layout"][0]) if "layout" in vals else {}
        position = (f"row {self.c._literal(*lay['row'])}, col {self.c._literal(*lay['column'])}" if "row" in lay and "column" in lay else None)
        return {"name": name, "caption": text or (column_caption if column else None), "type": etype, "column": column,
                "column_caption": column_caption, "position": position, "parent": self.parent(name)}

    def parent(self, name: str) -> str | None:
        """The parent the page leaves the element in: a `move` wins over the `insert`."""
        ops = [o for o in self.ops if o["name"] == name and o["parentName"]]
        move = next((o for o in reversed(ops) if o["operation"] == "move"), None)
        return (move or (ops[0] if ops else {})).get("parentName")

    def chain(self, name: str) -> list[dict]:
        out, parent = [], self.parent(name)
        while parent and parent not in [c["name"] for c in out]:
            el = self.element(parent)
            out.append({"name": parent, "caption": el.get("caption")})
            parent = self.parent(parent)
        return out[::-1]


def _q(caption: str | None) -> str:
    return f" {caption!r}" if caption else ""


def _detail_text(d: dict) -> str:
    f = d.get("filter") if isinstance(d.get("filter"), dict) else {}
    flt = f.get("detailColumn")
    return (f"detail {d.get('schemaName', '?')}" + (f" of {d['entitySchemaName']}" if d.get("entitySchemaName") else "")
            + (f" filtered by {d.get('entitySchemaName') or '?'}.{flt} = {f.get('masterColumn', 'Id')}" if flt else ""))


def _details(c) -> dict:
    """details with the filter object read one level deeper (entries() stops at the first level)."""
    span = c.sections.get("details")
    out = {}
    for k, (a, _) in (c._object(span[0]).items() if span else []):
        props = c._object(a)
        d = {pk: c._literal(pa, pb) for pk, (pa, pb) in props.items()}
        if "filter" in props:
            d["filter"] = {fk: c._literal(fa, fb) for fk, (fa, fb) in c._object(props["filter"][0]).items()}
        out[k] = d
    return out


def where(c, name: str, culture: str) -> str:
    view = View(c, culture)
    ops = [o for o in view.ops if o["name"] == name]
    if not ops:
        close = difflib.get_close_matches(name, list(dict.fromkeys(o["name"] for o in view.ops if o["name"])), n=3, cutoff=0.4)
        raise KeyError(f"no element {name} in the diff of {c.name}" + (f"; closest: {', '.join(close)}" if close else ""))
    el = view.element(name)
    package = c.package.name
    if el:
        head = f"{name}{_q(el['caption'])}" + (f"  {el['type']}" if el["type"] else "")
        if el["column"]:
            from ..describe.platform import column_caption as platform_caption  # S31-T09

            fallback = platform_caption(c.package, c.entity, el["column"], culture) if c.entity and not el["column_caption"] else None
            head += f"  bindTo {el['column']}" + (f" -> {c.entity}.{el['column']}{_q(el['column_caption']) or fallback or ' (caption not in workspace)'}"
                                                  if c.entity else "")
        detail = _details(c).get(name)
        lines = [head] + ([f"  {_detail_text(detail)}"] if detail else [])
        layer = f"added in {package}"
    else:
        lines = [f"{name} (caption not in workspace)"]
        layer = ", ".join(sorted({o["operation"] or "?" for o in ops})) + f" in {package}" + (f", inherited from {c.parent}" if c.parent else "")
    chain = view.chain(name)
    if chain:
        lines.append("  in " + " > ".join(f"{p['name']}{_q(p['caption'])}" for p in chain) + (f" ({el['position']})" if el.get("position") else ""))
    elif el.get("position"):
        lines.append(f"  ({el['position']})")
    lines.append(f"  layer: {layer}")
    return "\n".join(lines)


def map_lines(c, culture: str, tab: str | None = None) -> list[str]:
    """The inserts as a tree by parentName, in `index` order; the roots are the containers of the parent page they fill."""
    view = View(c, culture)
    details = _details(c)
    inserted = [o["name"] for o in view.ops if o["operation"] == "insert" and o["name"]]
    children: dict[str, list[str]] = {}
    for n in dict.fromkeys(inserted):
        children.setdefault(view.parent(n) or "", []).append(n)

    def order(n):  # a grid's cells by their layout row and column, other children by `index`, else the diff order
        pos, op = next((i, o) for i, o in enumerate(view.ops) if o["name"] == n and o["operation"] == "insert")
        lay = view.c._object(view.values(op)["layout"][0]) if "layout" in view.values(op) else {}
        try:
            return (int(view.c._literal(*lay["row"])), int(view.c._literal(*lay["column"]))) if "row" in lay and "column" in lay else (int(op["index"]), 0)
        except (TypeError, ValueError):
            return (pos, 0)

    for kids in children.values():
        kids.sort(key=order)
    out = []

    def walk(n, depth):
        el = view.element(n)
        line = "  " * depth + n + _q(el.get("caption")) + (f"  {el['type']}" if el.get("type") else "")
        if n in details:
            line += f"  {_detail_text(details[n])}"
        elif el.get("column") and el["column"] != n:
            line += f"  bindTo {el['column']}"
        out.append(line)
        for k in children.get(n, []):
            walk(k, depth + 1)

    if tab:
        if tab not in inserted:
            raise KeyError(f"no element {tab} inserted in {c.name}; inserted: {', '.join(inserted[:10])}")
        walk(tab, 0)
        return out
    roots = [p for p in children if p not in inserted]
    for r in roots:
        out.append(f"{r or '(no parent)'} (parent page)")
        for k in children[r]:
            walk(k, 1)
    return out
