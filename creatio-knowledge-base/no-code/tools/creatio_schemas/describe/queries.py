"""Query topics per schema kind. Each handler is `(item, name, filters) -> str` and prints only what was asked."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..csharp import CSharpSource
from ..data import DataBinding
from ..dcm import DcmSchema
from ..entity import EntitySchema
from ..entity.catalog import column_flags
from ..files import ALL_DATA_VALUE_TYPES, DATA_VALUE_TYPES, read_text
from ..page import PageSchema
from ..process import ProcessSchema
from ..process.catalog import DIRECTION, USER_TASK_BY_UID, short_type
from ..process.schema import RECORD_VALUES
from ..rules import RuleSchema
from ..sqlscript import SqlScript
from ..usertask import UserTaskSchema
from .core import DEFAULT_LIMIT, GenericItem, QueryError, cut


def _match(value: str | None, wanted: str | None) -> bool:
    return wanted is None or (value or "").lower() == wanted.lower()


def _json(value) -> str:
    return json.dumps(value, indent=1, ensure_ascii=False)


BODY_TOPICS = {"handler", "member", "method", "script"}
LONG_BODY = 120  # lines: over this an unwindowed answer starts with the hint


def _body_window(text: str, f: dict) -> str:
    """A body topic's answer, or a window into it: `lines=a-b` (1-based, inclusive) or `around=<text>` (the first line that holds the
    text, `n=` lines on each side, default 8), every line numbered by its place in the body. A body over LONG_BODY lines
    asked without either starts with a line that names the keys."""
    lines = text.split("\n")
    width = len(str(len(lines)))
    if "lines" in f:
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", f["lines"].strip())
        if not m or int(m.group(1)) < 1 or (m.group(2) and int(m.group(2)) < int(m.group(1))):
            raise QueryError("lines must be a range 'a-b' (1-based, a <= b), e.g. lines=10-40")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a > len(lines):
            raise QueryError(f"the body has {len(lines)} lines; lines={f['lines']} starts after the end")
        lo, hi = a - 1, min(b, len(lines))
    elif "around" in f:
        try:
            n = int(f.get("n", 8))
        except ValueError as exc:
            raise QueryError("n must be a non-negative integer") from exc
        if n < 0:
            raise QueryError("n must be a non-negative integer")
        at = next((i for i, line in enumerate(lines) if f["around"] in line), None)
        if at is None:
            raise QueryError(f"no line of the body ({len(lines)} lines) holds {f['around']!r}")
        lo, hi = max(at - n, 0), min(at + n + 1, len(lines))
    else:
        return f"{len(lines)} lines; lines=a-b or around=<text> for a part\n{text}" if len(lines) > LONG_BODY else text
    return "\n".join([f"lines {lo + 1}-{hi} of {len(lines)}"] + [f"{i:>{width}}  {lines[i - 1]}" for i in range(lo + 1, hi + 1)])


def _need(name: str | None, what: str) -> str:
    if not name:
        raise QueryError(f"this topic needs a name: '{what} <name>'")
    return name


def _limited(lines, filters):
    """Limit a list of lines using the query's limit, from the query's offset (`columns offset=40`)."""
    try:
        limit, offset = int(filters.get("limit", DEFAULT_LIMIT)), int(filters.get("offset", 0))
    except ValueError as exc:
        raise QueryError("limit and offset must be non-negative integers") from exc
    if limit < 0 or offset < 0:
        raise QueryError("limit must be a non-negative integer")
    return "\n".join(cut(lines, limit, offset=offset))


# -- every kind --------------------------------------------------------------- #

def q_files(item, name, f):
    base = getattr(item, "dir", None) or getattr(item, "package")
    paths = sorted(p for p in base.rglob("*") if p.is_file()) if hasattr(item, "dir") else []
    if isinstance(item, SqlScript):
        paths = sorted(p for p in (item.package / "SqlScripts" / item.name).rglob("*") if p.is_file())
    return "\n".join(f"{p.relative_to(item.package).as_posix():<60} {p.stat().st_size:>8} bytes" for p in paths) or "(no files)"


def primary_culture_line(item) -> str:
    """`primary culture: uk-UA (410 keys; en-US 412, ru-RU 3, ...)` - the culture the index reads captions in, from the package index."""
    from .index import PackageIndex

    idx = PackageIndex(item.package)
    idx.refresh()
    counts, primary = idx.data.get("cultures", {}), idx.data.get("culture", "en-US")
    others = sorted(((c, n) for c, n in counts.items() if c != primary), key=lambda x: (-x[1], x[0]))
    shown = ", ".join(f"{c} {n}" for c, n in others[:4]) + (", ..." if len(others) > 4 else "")
    return f"primary culture: {primary} ({counts.get(primary, 0)} keys" + (f"; {shown}" if shown else "") + ")"


def q_resources(item, name, f):
    res = getattr(item, "resources", None)
    if res is None or not res.cultures:
        return "(no resources)"
    culture = f.get("culture")
    if culture:
        keys = res.ordered_keys(culture)
        return "\n".join(f"{k} = {res.get(k, culture)!r}" for k in keys) or f"(no {culture})"
    missing = res.missing()
    return "\n".join([primary_culture_line(item), f"cultures: {', '.join(sorted(res.cultures))}; {len(res.ordered_keys('en-US'))} keys in en-US"]
                     + [f"  missing in {c}: {len(ks)}" + (f" ({', '.join(ks[:8])}{', ...' if len(ks) > 8 else ''})" if ks else "") for c, ks in missing.items() if ks])


def q_resource(item, name, f):
    key = _need(name, "resource")
    res = item.resources
    return "\n".join(f"{c}: {res.get(key, c)!r}" for c in sorted(res.cultures) if res.get(key, c) is not None) or f"no key {key}"


def q_missing(item, name, f):
    """Keys a culture lacks against a source culture (en-US by default): `missing [culture=ru-RU] [from=en-US]`."""
    res = getattr(item, "resources", None)
    if res is None or not res.cultures:
        return "(no resources)"
    source = f.get("from", "en-US")
    if source not in res.cultures:
        return f"(no {source})"
    cultures = [f["culture"]] if f.get("culture") else [c for c in sorted(res.cultures) if c != source]
    lines = [f"{c}: {k}" for c in cultures for k in res.ordered_keys(source) if res.get(k, c) is None]
    return "\n".join(lines) or f"nothing missing against {source}"


def q_keys(item, name, f):
    """The top-level metadata keys of a schema with their platform names (process/assets/keymap.json names every kind's keys):
    for full metadata one line per key with a size hint, for a replacing schema's diff form one line per operation."""
    from ..process.catalog import KEYMAP
    from ..workspace import parse_diff

    folder = getattr(item, "dir", None)
    if folder is None and getattr(item, "descriptor", None) is not None and getattr(item, "path", None) is not None:
        folder = item.path.parent  # a source code schema: the CSharpSource points at its .cs file
    path = folder / "metadata.json" if folder else None
    if not path or not path.is_file():
        return "(no metadata.json)"
    text = read_text(path)[0]

    def hint(v):
        return f"[{len(v)} items]" if isinstance(v, list) else f"{{{len(v)} keys}}" if isinstance(v, dict) else json.dumps(v, ensure_ascii=False)[:60]

    if text.lstrip().startswith("{"):
        schema = json.loads(text).get("MetaData", {}).get("Schema", {})
        return "\n".join(f"{k:<12} {KEYMAP.get(k, '?'):<28} {hint(v)}" for k, v in schema.items()) or "(empty metadata)"
    lines = ["diff form against the parent's metadata: = set, + append, - remove, on MetaData.Schema.<key>[.<nested key>]"]
    for op, p, v in parse_diff(text):
        path = p.removeprefix("MetaData.Schema.") if p.startswith("MetaData.Schema.") else p
        last = path.split(".")[-1]
        lines.append(f"{op} {path:<22} {KEYMAP.get(last, '?'):<28} {(v or '')[:60]}")
    return "\n".join(lines)


def _index_name(item) -> str:
    name = getattr(item, "name", None)
    return name or Path(item.path).relative_to(item.package).as_posix()


def q_uses(item, name, f):
    """`uses [kind=object] [via=lookup]`: the typed edges from this item (describe/deps.py), from the workspace index."""
    from .deps import dependencies
    return dependencies(item.package, _index_name(item), "out", f.get("kind", ""), f.get("via", ""), int(f.get("limit", DEFAULT_LIMIT)))


def q_used_by(item, name, f):
    """`used-by [kind=process] [via=signal]`: every item of the workspace whose typed edges point here."""
    from .deps import dependencies
    return dependencies(item.package, _index_name(item), "in", f.get("kind", ""), f.get("via", ""), int(f.get("limit", DEFAULT_LIMIT)))


COMMON = {"files": q_files, "resources": q_resources, "resource": q_resource, "missing": q_missing, "keys": q_keys,
          "uses": q_uses, "used-by": q_used_by}

# -- objects ------------------------------------------------------------------ #

def q_columns(e: EntitySchema, name, f):
    # the caption follows the name, in the package's primary culture; `captions=end` is the old form (describe.py diff compares lines across revisions)
    culture = None if f.get("captions") == "end" else f.get("culture") or package_culture(e)
    if culture and e.resources.cultures and culture not in e.resources.cultures:
        raise QueryError(f"{e.name} has no culture {culture}; cultures: {', '.join(sorted(e.resources.cultures))}")
    out = []
    for c in e.columns():
        t = ALL_DATA_VALUE_TYPES.get(c.get("S2"), c.get("S2"))
        flags = column_flags(c)
        if not _match(t, f.get("type")):
            continue
        if f.get("flag") and f["flag"] not in flags:
            continue
        if f.get("own") and (f["own"].lower() == "true") != e.is_own(c):
            continue
        out.append(e.describe_column(c, culture).strip() + ("" if e.is_own(c) else "  base"))
    if culture and not any(f.get(k) for k in ("type", "flag", "own")):  # S31-T10: the site's columns the workspace does not define
        from .index import index_path
        from .site import column_lines

        out += column_lines(index_path(e.package), e.name)
    return "\n".join(out) or "(no matching column)"


def q_column(e: EntitySchema, name, f):
    c = e.column(_need(name, "column"))
    return e.describe_column(c).strip() + ("" if e.is_own(c) else "  base") + "\n" + _json(c)


def q_flags(e: EntitySchema, name, f):
    return "\n".join(line for line in e.describe().splitlines() if line.strip().startswith(("flags:", "display column:")))


def q_base(e: EntitySchema, name, f):
    info = e.base_info
    if not info:
        return f"{e.name} has no fetched base (own object with parent {e.parent_name})" if not e.replacing else "no base cached: run objects.py base"
    return "\n".join([f"base of {e.name}: {info.get('caption')!r} fetched {info.get('fetched')} from {info.get('env')}",
                      "chain: " + " <- ".join(f"{c.get('package')}" for c in info.get("chain", []))])


MAP_GROUPS = [("lookups", {"Lookup"}), ("text", {"ShortText", "MediumText", "LongText", "Text", "MaxSizeText", "RichText", "EmailText", "PhoneText", "WebText"}),
              ("dates", {"Date", "DateTime", "Time"}), ("numbers", {"Integer", "Float", "Float0", "Float1", "Float2", "Float3", "Float4", "Float8",
                                                                     "Money", "Money0", "Money1", "Money3"}), ("flags", {"Boolean"})]


def q_map(e: EntitySchema, name, f):
    """`map [culture=]`: the columns grouped by type (lookups, text, dates, numbers, flags, other), each with its caption, a lookup with its
    object; a column whose caption the workspace does not hold (a base column) says so."""
    culture = f.get("culture") or package_culture(e)
    if e.resources.cultures and culture not in e.resources.cultures:
        raise QueryError(f"{e.name} has no culture {culture}; cultures: {', '.join(sorted(e.resources.cultures))}")
    columns = e.columns()
    groups: dict[str, list[str]] = {label: [] for label, _ in MAP_GROUPS} | {"other": []}
    for c in columns:
        t = ALL_DATA_VALUE_TYPES.get(c.get("S2"), c.get("S2"))
        label = next((g for g, types in MAP_GROUPS if t in types), "other")
        caption = e.resources.get(f"Columns.{c['A2']}.Caption", culture)
        text = f"{c['A2']}{_quoted(caption, not e.is_own(c))}"
        if label == "lookups" and c.get("S4"):
            text += f" -> {e.ref_name(c['S4'])}"
        elif label in ("text", "numbers", "other"):
            text += f" ({t})"
        groups[label].append(text)
    own = len(e.own_columns())
    caption = e.resources.get("Caption", culture) or e.descriptor.data.get("Caption")
    lines = [f"{e.name}{_quoted(caption)} - {len(columns)} columns ({own} own)" + ("" if e.effective is not None else "; the base is not known here: own columns only")]
    lines += [f"{label + ':':<10} " + ", ".join(items) for label, items in groups.items() if items]
    from .index import index_path
    from .site import column_lines

    site = column_lines(index_path(e.package), e.name)  # S31-T10
    if site:
        lines.append(f"{'site:':<10} " + ", ".join(site))
    return "\n".join(lines)


OBJECT = {"columns": q_columns, "column": q_column, "flags": q_flags, "base": q_base, "map": q_map}

# -- processes ---------------------------------------------------------------- #

def _el_kind(e: dict) -> str:
    t = short_type(e).replace("ProcessSchema", "")
    return USER_TASK_BY_UID.get(e.get("J6"), e.get("J6", "?")) if t == "UserTask" else t


def q_p_elements(p: ProcessSchema, name, f):
    out = [f"{e['A2']:<30} {_el_kind(e):<24} {p.resources.get(f'BaseElements.{e['A2']}.Caption') or ''!r}"
           for e in p.nodes() if _match(_el_kind(e), f.get("kind"))]
    return "\n".join(out) or "(no matching element)"


def q_p_element(p: ProcessSchema, name, f):
    e = p.element(_need(name, "element"))
    lines = [f"{e['A2']} [{_el_kind(e)}] caption={p.resources.get(f'BaseElements.{e['A2']}.Caption')!r} at {e.get('BL3')}"]
    for par in p.element_params(e):
        if par.get("L8"):
            lines.append(f"    {par['A2']} = {p.describe_value(par['L8'])}")
    if f.get("env") and p.site is not None:  # S33-T10: with env= the filter and the set values are also read out, the site naming the lookup rows
        values_param = (RECORD_VALUES.get(e.get("J6")) or ("",))[0]
        for par in p.element_params(e):
            try:
                if par["A2"] == "DataSourceFilters" and (par.get("L8") or {}).get("GS2"):
                    lines.append(f"    filter: {p.describe_filter(e)}")
                elif par["A2"] == values_param and (par.get("L8") or {}).get("GS2"):
                    lines.append(f"    values: {p.describe_record_values(e)}")
            except (ValueError, KeyError):
                pass
    by_uid = {x["UId"]: x["A2"] for x in p.elements}
    for fl in p.flows():
        if fl.get("CI1") == e["UId"] or fl.get("CI2") == e["UId"]:
            cond = f" if {p.expressions.decode(fl['CI3'])}" if fl.get("CI3") not in (None, "null", "") else ""
            lines.append(f"    flow {fl['A2']}: {by_uid.get(fl.get('CI1'), '?')} -> {by_uid.get(fl.get('CI2'), '?')}{cond}")
    buttons = p.buttons(e)
    if buttons:
        lines.append("    buttons:")
        lines += [f"        {b['code']}  {b['caption']!r}  -> " + (", ".join(f"{fl} to {to}" for fl, to in b["flows"]) or "(no flow)") for b in buttons]
    if short_type(e) == "ProcessSchemaScriptTask":
        lines.append(f"    script: {len(e.get('CH1', ''))} chars (ask 'script {e['A2']}')")
    if p.describe_signal(e):
        lines.append(f"    {p.describe_signal(e)}")
    return "\n".join(lines)


def q_p_params(p: ProcessSchema, name, f):
    out = [f"{x['A2']:<28} {DATA_VALUE_TYPES.get(x.get('L1'), x.get('L1')):<12} {DIRECTION.get(x.get('L12', 0)):<9} default={p.describe_value(x.get('L8'))}"
           for x in p.params if _match(DIRECTION.get(x.get("L12", 0)), f.get("direction"))]
    return "\n".join(out) or "(no parameters)"


def q_p_flows(p: ProcessSchema, name, f):
    by_uid = {x["UId"]: x["A2"] for x in p.elements}
    out = []
    for fl in p.flows():
        src, dst = by_uid.get(fl.get("CI1"), "?"), by_uid.get(fl.get("CI2"), "?")
        if not _match(src, f.get("from")) or not _match(dst, f.get("to")):
            continue
        cond = f" if {p.expressions.decode(fl['CI3'])}" if fl.get("CI3") not in (None, "null", "") else ""
        cond += "".join(f" when button {c}" for c in p.flow_buttons(fl))
        out.append(f"{fl['A2']:<28} {src} -> {dst}{cond}")
    return "\n".join(out) or "(no flows)"


def q_p_script(p: ProcessSchema, name, f):
    return p.get_script(_need(name, "script"))


PROCESS = {"elements": q_p_elements, "element": q_p_element, "params": q_p_params, "flows": q_p_flows, "script": q_p_script}

# -- rules -------------------------------------------------------------------- #

def q_rules(r: RuleSchema, name, f):
    out = []
    for rule in r.rules:
        if f.get("enabled") and (f["enabled"].lower() == "true") != rule.get("BR4", True):
            continue
        out.append(r.describe_rule(rule)[0])
    return "\n".join(out) or "(no rules)"


def q_rule(r: RuleSchema, name, f):
    return "\n".join(r.describe_rule(r.rule(_need(name, "rule"))))


RULES = {"rules": q_rules, "rule": q_rule}

# -- SQL scripts -------------------------------------------------------------- #

def q_body(s: SqlScript, name, f):
    return s.body


def q_deps(s: SqlScript, name, f):
    return "\n".join(f"{d.get('Name')} ({d.get('UId')})" for d in s.depends_on) or "(no dependencies)"


SQL = {"body": q_body, "deps": q_deps}

# -- Freedom UI pages --------------------------------------------------------- #

def q_sections(pg: PageSchema, name, f):
    out = []
    for sec, inner in pg.raw_sections().items():
        label = sec.replace("SCHEMA_", "").lower().replace("_", "-")
        size = len(inner.strip())
        out.append(f"{label:<24} {size:>7} chars" + ("  (empty)" if size <= 2 else ""))
    return "\n".join(out)


def q_pg_elements(pg: PageSchema, name, f):
    out = []
    for op in pg.elements():
        v = op.get("values") or {}
        if not _match(v.get("type"), f.get("type")) or not _match(op.get("parentName"), f.get("parent")):
            continue
        lc = v.get("layoutConfig") or {}
        where = (op.get("parentName") or "") + (f" r{lc['row']}c{lc['column']}" if "row" in lc else "")
        bound = v.get("control") or (v.get("items") if v.get("type") == "crt.DataGrid" else "")
        out.append(f"{op['name']:<30} {v.get('type', op.get('operation')):<22} {where:<34} {bound}")
    return "\n".join(out) or "(no matching element)"


def q_pg_element(pg: PageSchema, name, f):
    return _json(pg.element(_need(name, "element")))


def q_pg_attributes(pg: PageSchema, name, f):
    out = []
    for k, v in pg.attributes.items():
        path = ((v or {}).get("modelConfig") or {}).get("path", "")
        bound = path.startswith(pg.primary + ".")
        if f.get("bound") and (f["bound"].lower() == "true") != bound:
            continue
        extra = "collection" if (v or {}).get("isCollection") else ""
        out.append(f"{k:<30} {path:<30} {extra}")
    return "\n".join(out) or "(no attributes)"


def q_pg_attribute(pg: PageSchema, name, f):
    key = _need(name, "attribute")
    if key not in pg.attributes:
        raise QueryError(f"no attribute {key}; attributes: {', '.join(pg.attributes) or '-'}")
    return _json(pg.attributes[key])


def q_pg_sources(pg: PageSchema, name, f):
    return "\n".join(f"{k:<24} {(v.get('config') or {}).get('entitySchemaName', '?'):<24} scope={v.get('scope')}  attributes={', '.join((v.get('config') or {}).get('attributes', {})) or '-'}"
                     for k, v in pg.data_sources.items()) or "(no data sources)"


def q_pg_handlers(pg: PageSchema, name, f):
    hs = pg.handlers()
    return "\n".join(f"{req:<44} {len(text):>6} chars" for req, text in hs) or "(no handlers)"


def q_pg_handler(pg: PageSchema, name, f):
    req = _need(name, "handler")
    for r, text in pg.handlers():
        if r == req:
            return text
    raise QueryError(f"no handler for {req}; handlers: {', '.join(r for r, _ in pg.handlers()) or '-'}")


def q_pg_raw(section: str):
    def q(pg: PageSchema, name, f):
        text = pg.raw_sections().get(section, "").strip()
        return text if len(text) > 2 else "(empty)"
    return q


def q_pg_containers(pg: PageSchema, name, f):
    parents: dict[str, list[str]] = {}
    for op in pg.elements():
        parents.setdefault(op.get("parentName") or "(root)", []).append(op["name"])
    return "\n".join(f"{parent}: {', '.join(children)}" for parent, children in parents.items()) or "(no elements)"


def q_pg_find(pg: PageSchema, name, f):
    needle = _need(name, "find").lower()
    hits = []
    for sec, inner in pg.raw_sections().items():
        for i, line in enumerate(inner.splitlines(), 1):
            if needle in line.lower():
                hits.append(f"{sec.replace('SCHEMA_', '').lower()}:{i}: {line.strip()[:120]}")
    return "\n".join(hits) if hits else f"'{needle}' not found"


def package_culture(item) -> str:
    """The primary culture of the item's package, from the package index."""
    from .index import PackageIndex

    idx = PackageIndex(item.package)
    idx.refresh()
    return idx.data.get("culture", "en-US")


def _page_view(pg: PageSchema, f: dict) -> tuple[str, dict[str, dict], bool]:
    """(culture asked for, {element name: index-style entry} in that culture, the culture is the primary one)."""
    from .index import captions_of

    primary = package_culture(pg)
    culture = f.get("culture") or primary
    if culture not in pg.resources.cultures and pg.resources.cultures:
        raise QueryError(f"{pg.name} has no culture {culture}; cultures: {', '.join(sorted(pg.resources.cultures))}")
    entries = captions_of("page", pg, culture)["elements"]
    return culture, {e["name"]: e for e in entries}, culture == primary


def _env(f):
    """The environment of an `env=<name>` filter (clio's settings), else None."""
    if not f.get("env"):
        return None
    from ..environment import open_environment

    return open_environment(f["env"], None)


def _quoted(caption: str | None, inherited: bool = False) -> str:
    return f" {caption!r}" if caption else (" (caption not in workspace)" if inherited else "")


def q_pg_where(pg: PageSchema, name, f):
    """`where <name> [culture=] [format=json]`: the element's caption, type and control, the attribute and column it binds with the
    column's caption, the parent chain with captions and the grid position, and the layer (added here / inherited)."""
    import difflib

    if not name:  # S31-T07: the page itself - the section, the object and the record type that open it
        from .sections import opens_from

        return "\n".join(opens_from(pg.package, pg.name, pg.descriptor.data.get("UId"), package_culture(pg), _env(f), f.get("env", "")))
    key = _need(name, "where")
    culture, by_name, is_primary = _page_view(pg, f)
    ops = [op for op in pg.elements() if op["name"] == key]
    if not ops and not any(o.get("parentName") == key for o in pg.elements()):
        close = difflib.get_close_matches(key, [op["name"] for op in pg.elements()], n=3, cutoff=0.4)
        raise QueryError(f"no element {key} in {pg.name}" + (f"; closest: {', '.join(close)}" if close else ""))
    ins = next((op for op in ops if op.get("operation", "insert") == "insert"), None)
    here = ins is not None
    op = ins or (ops[0] if ops else {})  # no operation of its own: a container of the parent page that this page only fills
    values = op.get("values") or {}
    el = by_name.get(key, {})
    etype = el.get("type") or values.get("type") or "?"
    control = el.get("control")
    attribute = column = column_caption = entity = path = None
    if control and control.startswith("$"):
        attribute = control[1:]
        path = pg._attr_path(attribute) or None
        if path:
            ds, _, col = path.partition(".")
            entity = ((pg.data_sources.get(ds) or {}).get("config") or {}).get("entitySchemaName")
            column = f"{entity}.{col}" if entity and col else None
            column_caption = pg._captions_of(entity).get(col) if entity and col else None
    chain, parent = [], op.get("parentName")
    while parent and parent not in [c["name"] for c in chain]:
        p = by_name.get(parent, {})
        chain.append({"name": parent, "caption": p.get("caption"), "inherited": parent not in by_name})
        parent = next((o.get("parentName") for o in pg.elements() if o["name"] == parent and o.get("parentName")), None)
    chain.reverse()
    lc = values.get("layoutConfig") if isinstance(values.get("layoutConfig"), dict) else {}
    position = f"row {lc['row']}, col {lc['column']}" if "row" in lc and "column" in lc else None
    parent_page = (getattr(pg.descriptor, "data", {}).get("Parent") or {}).get("Name")
    package = pg.package.name
    if here:
        layer = f"added in {package}"
    elif not ops:
        layer = f"inherited from {parent_page}" if parent_page else "not defined in this page"
    else:
        layer = f"{op.get('operation')} in {package}" + (f", inherited from {parent_page}" if parent_page else ", not defined in this page")
    if f.get("format") == "json":
        return json.dumps({"name": key, "caption": el.get("caption"), "culture": culture, "type": etype, "control": control, "attribute": attribute,
                           "path": path, "column": column, "column_caption": column_caption, "position": position, "layer": layer,
                           "parents": [{"name": c["name"], "caption": c["caption"]} for c in chain]}, ensure_ascii=False, indent=1)
    head = f"{key}{_quoted(el.get('caption'), not here)}" + ("" if is_primary else f" ({culture})") + (f"  {etype}" if etype != "?" else "")
    if control:
        head += f"  control {control}"
        if attribute:
            head += f" -> attribute {attribute}"
        if path and column:
            from .platform import column_caption as platform_caption  # S31-T09: a base column's caption from the platform install

            head += f" -> {path.split('.')[0]} {column}" + (_quoted(column_caption) if column_caption else
                                                            platform_caption(pg.package, entity, col, culture) or " (caption not in workspace)")
    lines = [head]
    if chain:
        lines.append("  in " + " > ".join(f"{c['name']}{_quoted(c['caption'])}" for c in chain) + (f" ({position})" if position else ""))
    elif position:
        lines.append(f"  ({position})")
    lines.append(f"  layer: {layer}")
    return "\n".join(lines)


def _short(etype: str) -> str:
    return etype[4:] if etype.startswith("crt.") else etype


def _target(pg: PageSchema, el: dict, values: dict) -> str:
    """` -> Contact` for a lookup control, ` (UsrOrderLine)` for a grid: the object the element reads, when the workspace knows it."""
    control = el.get("control")
    if el["type"] in ("crt.ComboBox", "crt.LookupSelect") and control and control.startswith("$"):
        path = pg._attr_path(control[1:])
        ds, _, column = path.partition(".")
        entity = ((pg.data_sources.get(ds) or {}).get("config") or {}).get("entitySchemaName")
        try:
            ref = pg.workspace.columns(entity).get(column, (None, None))[1] if entity and column else None
        except (KeyError, OSError):
            ref = None
        return f" -> {ref}" if ref else ""
    items = values.get("items")
    if el["type"] == "crt.DataGrid" and isinstance(items, str) and items.startswith("$"):
        model = ((pg.attributes.get(items[1:]) or {}).get("modelConfig")) or {}
        entity = model.get("entitySchemaName") or ((pg.data_sources.get(str(model.get("path", "")).split(".")[0]) or {}).get("config") or {}).get("entitySchemaName")
        return f" ({entity})" if entity else ""
    return ""


def q_pg_map(pg: PageSchema, name, f):
    """`map [tab=<container>] [culture=]`: the page as an indented tree, one line per element: name, caption, short type, the lookup target
    of a ComboBox or the object of a grid; a container carries the count of the elements under it."""
    import difflib

    culture, by_name, _ = _page_view(pg, f)
    ops = {op["name"]: op for op in pg.elements() if (op.get("values") or {}).get("type")}
    children: dict[str | None, list[str]] = {}
    for n, e in by_name.items():
        children.setdefault(e.get("parent") if e.get("parent") in by_name else None, []).append(n)

    def below(n: str) -> int:
        return sum(1 + below(c) for c in children.get(n, []))

    roots = children.get(None, [])
    tab = f.get("tab")
    if tab:
        if tab not in by_name:
            close = difflib.get_close_matches(tab, list(by_name), n=3, cutoff=0.4)
            raise QueryError(f"no element {tab} in {pg.name}" + (f"; closest: {', '.join(close)}" if close else ""))
        roots = [tab]
    caption = pg.resources.get("Caption", culture) or pg.descriptor.data.get("Caption")
    lines = [f"{pg.name}{_quoted(caption)} - {below(tab) + 1 if tab else len(by_name)} elements" + (f" under {tab}" if tab else "") + "; tab= narrows, offset= continues"]

    def walk(n: str, depth: int) -> None:
        e = by_name[n]
        kids = children.get(n, [])
        count = f" ({below(n)})" if kids else ""
        lines.append("  " * depth + f"{n}{_quoted(e.get('caption'))} {_short(e['type'])}{_target(pg, e, (ops.get(n) or {}).get('values') or {})}{count}")
        for c in kids:
            walk(c, depth + 1)

    if tab:
        walk(tab, 0)
        return "\n".join(lines)
    homes: dict[str | None, list[str]] = {}  # the roots under the container of the parent page they sit in
    for r in roots:
        homes.setdefault(by_name[r].get("parent"), []).append(r)
    for home, members in homes.items():
        if home:
            lines.append(f"{home} (inherited, {sum(1 + below(m) for m in members)})")
        for r in members:
            walk(r, 1 if home else 0)
    return "\n".join(lines)


def _rules_naming(pg: PageSchema, addon: str, needles: set[str]) -> tuple[str, list[tuple[str, str, bool]], int] | None:
    """(addon name, [(rule name, caption, enabled)] of the rules that name a needle, all rules) for `<addon>` of the workspace, or None."""
    from .core import open_item

    for hit in pg.workspace.find(addon, "AddonSchemaManager"):
        try:
            rs = open_item(hit["dir"].parent.parent, addon)
            found = []
            for rule in rs.rules:
                text = "\n".join(rs.describe_rule(rule))
                if any(re.search(rf"(?<![\w.]){re.escape(n)}(?!\w)", text) for n in needles):
                    found.append((rule["BR3"], rs.caption(rule) or "", rule.get("BR4", True)))
            return addon, found, len(rs.rules)
        except Exception:
            continue
    return None


def _handler_lines(src: str, needles: set[str]) -> tuple[list[int], list[int]]:
    """(read lines, write lines) of a handler body that name `$context.<needle>` or the needle as a word, counted from 1."""
    reads, writes = [], []
    pattern = re.compile(r"(?:\$context\.|(?<![\w.]))(?:" + "|".join(re.escape(n) for n in sorted(needles)) + r")\b(\s*=(?!=))?")
    for i, line in enumerate(src.splitlines(), 1):
        for m in pattern.finditer(line):
            (writes if m.group(1) else reads).append(i)
    return sorted(set(reads)), sorted(set(writes))


def _test_files(pg: PageSchema, words: list[str]) -> list[tuple[str, int, str]]:
    """(file, line, text) of the first line of each framework case that holds one of `words`; the folder is project.json paths.testFramework."""
    root = pg.package.parent.parent if pg.package.parent.name == "packages" else pg.package.parent
    try:
        folder = (json.loads((root / "project.json").read_text(encoding="utf-8-sig")).get("paths") or {}).get("testFramework")
    except (OSError, ValueError, AttributeError):
        folder = None
    if not folder:
        return []
    base = (root / folder).resolve()
    out = []
    for sub in ("Cases", "ProcessCases"):
        for path in sorted((base / sub).rglob("*.act")) if (base / sub).is_dir() else []:
            try:
                lines = read_text(path)[0].splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            hit = next(((i, t.strip()) for i, t in enumerate(lines, 1) for w in words if w and w.casefold() in t.casefold() and not t.lstrip().startswith("#")), None)
            if hit:
                out.append((f"{sub}/{path.relative_to(base / sub).as_posix()}", hit[0], hit[1][:70]))
    return out


def q_pg_about(pg: PageSchema, name, f):
    """`about <name> [culture=] [format=json]`: `where`, then what touches the element: the lookup target with its values, the page rules and the
    object rules that name it, the handlers that read or write it (line numbers of the handler body), the validators and converters on it, the
    framework's cases that hold its caption or name."""
    from .index import PackageIndex, packages_of

    key = _need(name, "about")
    where = json.loads(q_pg_where(pg, key, {**f, "format": "json"}))
    culture, by_name, _ = _page_view(pg, f)
    attribute, column, caption = where.get("attribute"), (where.get("column") or "").split(".")[-1] or None, where.get("caption")
    entity = (where.get("column") or "").split(".")[0] or None
    needles = {n for n in (key, attribute, column) if n}
    out: dict = {"lookup": None, "page_rules": None, "object_rules": None, "handlers": [], "validators": [], "converters": [], "tests": []}
    # the lookup target and its values
    if entity and column:
        try:
            ref = pg.workspace.columns(entity).get(column, (None, None))[1]
        except (KeyError, OSError):
            ref = None
        if ref:
            target = {"object": ref, "caption": None, "package": None, "values": []}
            for idx in (PackageIndex(p) for p in packages_of(pg.package.parent)):
                idx.refresh()
                if ref in idx.schemas:
                    target.update(caption=idx.schemas[ref].get("caption") or None, package=idx.data.get("package", idx.package.name))
                for dn, de in idx.data.get("data", {}).items():
                    if de.get("schema") == ref and "error" not in de:
                        target["values"] += [k.get("caption") or k.get("value") for k in de.get("keys", []) if isinstance(k, dict)]
                        target["rows"] = target.get("rows", 0) + de.get("rows", 0)
            out["lookup"] = target
    out["page_rules"] = _rules_naming(pg, pg.name + "BusinessRule", needles)
    if entity:
        out["object_rules"] = _rules_naming(pg, entity + "BusinessRule", needles)
    for req, src in pg.handlers():
        reads, writes = _handler_lines(src, needles)
        if reads or writes:
            out["handlers"].append({"request": req, "reads": reads, "writes": writes})
    attrs = pg.attributes.get(attribute) or {} if attribute else {}
    out["validators"] = sorted((attrs.get("validators") or {}).keys()) if isinstance(attrs.get("validators"), dict) else []
    values_text = json.dumps(pg.element(key).get("values") or {}, ensure_ascii=False) if pg.has(key) else ""
    out["converters"] = sorted(set(re.findall(r"\|\s*([A-Za-z_][\w.]*)", values_text)))
    out["tests"] = [{"file": p, "line": n, "text": t} for p, n, t in _test_files(pg, [caption or "", column or "", key])]
    if f.get("format") == "json":
        return json.dumps({**where, "lookup_target": out["lookup"],
                           "page_rules": out["page_rules"] and {"addon": out["page_rules"][0], "rules": [dict(zip(("name", "caption", "enabled"), r)) for r in out["page_rules"][1]]},
                           "object_rules": out["object_rules"] and {"addon": out["object_rules"][0], "rules": [dict(zip(("name", "caption", "enabled"), r)) for r in out["object_rules"][1]]},
                           "handlers": out["handlers"], "validators": out["validators"], "converters": out["converters"], "tests": out["tests"]},
                          ensure_ascii=False, indent=1)
    lines = q_pg_where(pg, key, f).splitlines()
    touched = False
    t = out["lookup"]
    if t:
        shown = ", ".join(str(v) for v in t["values"][:5]) + (", ..." if len(t["values"]) > 5 else "")
        lines.append(f"  lookup target: {t['object']}{_quoted(t['caption'])} ({t['package']}" + (f", {t.get('rows', len(t['values']))} values: {shown}" if t["values"] else "") + ")"
                     if t["package"] else f"  lookup target: {t['object']} (base)")
    for label, rules in (("page rules", out["page_rules"]), ("object rules", out["object_rules"])):
        if rules and rules[1]:
            touched = True
            if label == "page rules":
                lines.append(f"  page rules ({rules[0]}): " + ", ".join(f"{n} {c!r} ({'enabled' if on else 'disabled'})" for n, c, on in rules[1]))
            else:
                lines.append(f"  object rules ({rules[0]}): {len(rules[1])} of {rules[2]} - " + ", ".join(f"{n} {c!r}" for n, c, _ in rules[1])
                             + f"; `rule <name>` on {rules[0]} reads one")
    if out["handlers"]:
        touched = True
        for h in out["handlers"]:
            parts = ([f"reads line {', '.join(map(str, h['reads']))}"] if h["reads"] else []) + ([f"writes line {', '.join(map(str, h['writes']))}"] if h["writes"] else [])
            lines.append(f"  handler {h['request']} ({'; '.join(parts)}); `handler {h['request']} around={attribute or key}` reads it")
    if out["validators"]:
        touched = True
        lines.append("  validators: " + ", ".join(out["validators"]))
    if out["converters"]:
        touched = True
        lines.append("  converters: " + ", ".join(out["converters"]))
    for t_ in out["tests"]:
        touched = True
        lines.append(f"  test {t_['file']}:{t_['line']}  {t_['text']}")
    if not touched:
        lines.append(f"  nothing touches {key} beyond the page")
    return "\n".join(lines)


PAGE = {"sections": q_sections, "elements": q_pg_elements, "element": q_pg_element, "attributes": q_pg_attributes,
        "attribute": q_pg_attribute, "data-sources": q_pg_sources, "handlers": q_pg_handlers, "handler": q_pg_handler,
        "validators": q_pg_raw("SCHEMA_VALIDATORS"), "converters": q_pg_raw("SCHEMA_CONVERTERS"), "containers": q_pg_containers,
        "find": q_pg_find, "where": q_pg_where, "map": q_pg_map, "about": q_pg_about}

# -- dcm ---------------------------------------------------------------------- #

def _req(e: dict) -> str:
    return "required" if e.get("RequiredType") else "optional"


def q_d_stages(d: DcmSchema, name, f):
    out = []
    for s in d.stages:
        parent = d.stage_by_uid(s.get("ParentStageUId"))
        out.append(f"{s['A2']:<16} {d.stage_caption(s)!r:<34} {s.get('Color', ''):<8} record={s.get('StageRecordId')}"
                   + (f"  alternative of {parent['A2']}" if parent else "") + (f"  {len(s.get('Elements', []))} steps" if s.get("Elements") else ""))
    return "\n".join(out) or "(no stages)"


def q_d_stage(d: DcmSchema, name, f):
    s = d.stage(_need(name, "stage"))
    lines = [f"{s['A2']} {d.stage_caption(s)!r} {s.get('Color', '')} record={s.get('StageRecordId')} uid={s['UId']}"]
    for _, e in d.elements(s):
        lines.append(f"  step {e['A2']} {d.element_caption(s, e)!r} -> {d.calls(e)} [{_req(e)}]")
        lines += [f"      when {c['when']} -> {c['then']}" for c in d.conditions(e)]
    lines.append(f"  can move to: {', '.join(b for a, b in d.connections if a == s['A2']) or '(any)'}")
    lines.append(f"  reached from: {', '.join(a for a, b in d.connections if b == s['A2']) or '(any)'}")
    return "\n".join(lines)


def q_d_steps(d: DcmSchema, name, f):
    out = [f"{e['A2']:<18} in {s['A2']:<10} {d.element_caption(s, e)!r:<40} -> {d.calls(e)} [{_req(e)}]"
           for s, e in d.elements() if _match(s["A2"], f.get("stage"))]
    return "\n".join(out) or "(no steps)"


def q_d_step(d: DcmSchema, name, f):
    s, e = d.element(_need(name, "step"))
    lines = [f"{e['A2']} {d.element_caption(s, e)!r} in stage {s['A2']} -> {d.calls(e)} [{_req(e)}]"]
    prefix = f"Stages.{s['A2']}.Elements.{e['A2']}.ProcessFlowElement.Parameters."
    for p in (e.get("ProcessFlowElement") or {}).get("BP2", []):
        lines.append(f"  param {p['A2']}: {d.resources.get(prefix + p['A2'] + '.DisplayValue') or ''}")
    lines += [f"  when {c['when']} -> {c['then']}" for c in d.conditions(e)]
    return "\n".join(lines)


def q_d_moves(d: DcmSchema, name, f):
    out = [f"{a} -> {b}" for a, b in d.connections if _match(a, f.get("from")) and _match(b, f.get("to"))]
    return "\n".join(out) or "(no connections: any stage can follow any)"


def q_d_filter(d: DcmSchema, name, f):
    return d.describe_filter() + (("\n" + _json(d.filters)) if f.get("raw") == "true" and d.filters else "")


DCM = {"stages": q_d_stages, "stage": q_d_stage, "steps": q_d_steps, "step": q_d_step, "moves": q_d_moves, "filter": q_d_filter}


# -- user task ---------------------------------------------------------------- #

def q_u_params(u: UserTaskSchema, name, f):
    out = [u.describe_param(p) for p in u.params if _match(DIRECTION.get(p.get("L12", 0)), f.get("direction"))]
    return "\n".join(out) or "(no parameters)"


def q_u_param(u: UserTaskSchema, name, f):
    p = u.param(_need(name, "param"))
    return u.describe_param(p) + "\n" + _json(p)


def q_u_methods(u: UserTaskSchema, name, f):
    return "\n".join(u.methods()) or "(no .cs file)"


def q_u_method(u: UserTaskSchema, name, f):
    return u.method(_need(name, "method"))


def q_u_source(u: UserTaskSchema, name, f):
    return u.source or "(no .cs file)"


USERTASK = {"params": q_u_params, "param": q_u_param, "methods": q_u_methods, "method": q_u_method, "source": q_u_source}

# -- C# ------------------------------------------------------------------------ #


def q_c_classes(c: CSharpSource, name, f):
    types = [t for t in c.types if _match(t["role"], f.get("role")) and _match(t["kind"], f.get("kind")) and (f.get("generated", "").lower() == "true" or not t["generated"])]
    return "\n".join(c.type_line(t) for t in types) or "(no types" + ("" if f.get("generated") else "; generated ones hidden, add generated=true") + ")"


def q_c_members(c: CSharpSource, name, f):
    rows = [m for m in c.members(name) if _match(m["kind"], f.get("kind"))
            and (not f.get("visibility") or f["visibility"].lower() in m["modifiers"] or (f["visibility"].lower() == "private" and not {"public", "protected", "internal"} & set(m["modifiers"])))]
    return "\n".join(f"{m['type']}.{m['name']:<30} {m['kind']:<11} {m['signature']}  ({m['line']}-{m['end']})" for m in rows) or "(no members)"


def q_c_member(c: CSharpSource, name, f):
    try:
        return c.member(_need(name, "member"))
    except KeyError as exc:
        raise QueryError(str(exc)) from None


def q_c_usings(c: CSharpSource, name, f):
    return "\n".join(c.usings) or "(no usings)"


def q_c_regions(c: CSharpSource, name, f):
    return "\n".join(f"{line:>5}  {title}" for line, title in c.regions) or "(no regions)"


def q_c_operations(c: CSharpSource, name, f):
    rows = [(line, label, text) for line, label, text in c.operations() if _match(label, f.get("kind"))]
    return "\n".join(f"{line:>5}  {label:<20} {text}" for line, label, text in rows) or "(no platform operations found)"


def q_c_find(c: CSharpSource, name, f):
    hits = c.find(_need(name, "find"))
    return "\n".join(f"{line:>5}  {text}" for line, text in hits) if hits else f"no line contains {name!r}"


CSHARP = {"classes": q_c_classes, "members": q_c_members, "member": q_c_member, "method": q_c_member, "usings": q_c_usings,
          "regions": q_c_regions, "operations": q_c_operations, "find": q_c_find}


# -- data bindings --------------------------------------------------------------- #


def q_b_columns(b: DataBinding, name, f):
    return "\n".join(f"{n:<28} uid={c['uid']}  {'key ' if c.get('key') else ''}{'force ' if c.get('force_update') else ''}"
                     f"{ALL_DATA_VALUE_TYPES.get(c.get('type'), c.get('type'))}{' (loc)' if n in b.localized else ''}"
                     for n, c in b.columns.items()) or "(no columns)"


def q_b_rows(b: DataBinding, name, f):
    rows = b.rows(f.get("culture"))
    out = [f"{b.key_of(r)}  " + "  ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in r.items() if k not in b.key_columns) for r in rows]
    return "\n".join(out) or "(no rows)"


def q_b_row(b: DataBinding, name, f):
    key = _need(name, "row")
    try:
        row, display = b.row(key), b.display_values(key)
    except KeyError as exc:
        raise QueryError(str(exc)) from None
    return "\n".join(f"{k} = {json.dumps(v, ensure_ascii=False)}" + (f"  {display[k]!r}" if display.get(k) else "") for k, v in row.items())


DATA = {"columns": q_b_columns, "rows": q_b_rows, "row": q_b_row}

# -- Classic UI client schemas --------------------------------------------------- #


def _op_line(op: dict) -> str:
    where = f" in {op['parentName']}.{op['propertyName']}" if op["parentName"] else ""
    index = f"[{op['index']}]" if op["index"] is not None else ""
    return f"{op['operation'] or '?':<7} {op['name'] or '(no name)'}{where}{index}  line {op['line']}  values: {', '.join(op['values']) or '-'}"


def _entries(table: dict) -> str:
    def fmt(v):
        return "{...}" if isinstance(v, dict) else "[...]" if isinstance(v, list) else str(v)
    return "\n".join(f"{k}  " + (" ".join(f"{pk}={fmt(pv)}" for pk, pv in v.items()) if isinstance(v, dict) else fmt(v)) for k, v in table.items()) or "(none)"


def q_c_diff(c, name, f):
    ops = [op for op in c.diff_operations() if _match(op["operation"], f.get("op")) and _match(op["parentName"], f.get("parent"))]
    return "\n".join(_op_line(op) for op in ops) or "(no matching operation)"


def q_c_element(c, name, f):
    try:
        ops = c.element(_need(name, "element"))
    except KeyError as exc:
        raise QueryError(str(exc)) from None
    return "\n\n".join(_op_line(op) + "\n" + op["source"] for op in ops)


def q_c_methods_js(c, name, f):
    return "\n".join(f"{m['name']:<40} line {m['line']:<6} {m['size']} lines" for m in c.methods()) or "(no methods)"


def q_c_method_js(c, name, f):
    """`method <name> [env=]`: one copy - its body (as always); more copies or `env=` - the body in every layer, first to last,
    `callParent` marked (S33-T07)."""
    from ..classicui.methods import method_lines

    key = _need(name, "method")
    try:
        return method_lines(c, key, _env(f), f.get("env", "")) or c.method(key)
    except KeyError as exc:
        raise QueryError(exc.args[0]) from None


def q_c_callers(c, name, f):
    """`callers <method>`: `this.<m>(` / `<module>.<m>(` across the workspace's client schemas, file:line (S33-T07)."""
    from ..classicui.methods import callers

    key = _need(name, "callers")
    hits = callers(c, key)
    return "\n".join(cut(hits, int(f.get("limit", DEFAULT_LIMIT)), offset=int(f.get("offset", 0)))) if hits else f"nothing calls {key} in the workspace"


def q_c_outline(c, name, f):
    """`outline`: methods, attributes and messages with line numbers (S33-T07)."""
    from ..classicui.methods import outline

    return "\n".join(outline(c)) or "(no attributes, messages or methods)"


def q_c_find_js(c, name, f):
    hits = c.find(_need(name, "find"))
    return "\n".join(f"{line:>5}  {where:<30} {text}" for line, where, text in hits) if hits else f"no line contains {name!r}"


def q_c_where(c, name, f):
    """`where <name> [culture=]`: the insert's caption, control, column with its caption, the parentName chain, the layout cell, the layer
    (S31-T08). With no name: the page itself - `opens from` (T07), the pages that show a detail, the pages of a section's object."""
    from ..classicui.view import where
    from .sections import opens_from, pages_of, shown_on

    culture = f.get("culture") or package_culture(c)
    if name:
        try:
            return where(c, name, culture)
        except KeyError as exc:
            raise QueryError(exc.args[0]) from None
    if c.kind == "detail":
        lines = shown_on(c.package, c.name)
    elif c.kind == "section":
        lines = [f"section of {c.entity}" if c.entity else "section of no object"]
    else:
        lines = opens_from(c.package, c.name, c.descriptor.data.get("UId"), culture, _env(f), f.get("env", ""))
    pages = pages_of(c.package, c.entity) if c.entity and c.kind != "edit page" else None
    return "\n".join(lines + ([pages] if pages else []))


def q_c_map(c, name, f):
    """`map [tab=<name>] [culture=]`: the inserts as a captioned tree (S31-T08)."""
    from ..classicui.view import map_lines

    try:
        lines = map_lines(c, f.get("culture") or package_culture(c), f.get("tab"))
    except KeyError as exc:
        raise QueryError(exc.args[0]) from None
    return "\n".join(cut(lines, int(f.get("limit", DEFAULT_LIMIT)), offset=int(f.get("offset", 0)))) or "(no inserts)"


CLASSIC = {"where": q_c_where, "map": q_c_map, "callers": q_c_callers, "outline": q_c_outline, "diff": q_c_diff, "element": q_c_element, "methods": q_c_methods_js, "method": q_c_method_js, "find": q_c_find_js,
           "messages": lambda c, n, f: _entries(c.messages()), "attributes": lambda c, n, f: _entries(c.attributes()),
           "details": lambda c, n, f: _entries(c.details()), "mixins": lambda c, n, f: _entries(c.mixins())}


def topics_of(item) -> dict:
    """The topics of an item's kind (registry.KINDS) plus the ones every item answers."""
    from .registry import kind_for

    return {**kind_for(item).topics, **COMMON}


def answer(item, topic: str, name: str | None, filters: dict[str, str]) -> str:
    table = topics_of(item)
    if topic in ("topics", "help", "?"):
        return f"{type(item).__name__} topics: " + ", ".join(sorted(table))
    if topic not in table:
        raise QueryError(f"unknown topic '{topic}' for a {type(item).__name__}; topics: {', '.join(sorted(table))}")
    result = table[topic](item, name, filters)
    if topic in BODY_TOPICS:
        return _body_window(result, filters)
    list_topics = {"files", "resource", "columns", "elements", "params", "flows", "rules", "attributes",
                   "handlers", "containers", "stages", "steps", "moves", "members", "operations", "find",
                   "rows", "diff", "methods", "messages", "details", "mixins", "classes", "usings", "regions",
                   "deps", "sections", "data-sources", "uses", "used-by", "map", "about"}
    if filters.get("format") == "json":  # one JSON object is not a list to cut
        return result
    if topic in list_topics or (topic == "resources" and filters.get("culture")):
        return _limited(result.splitlines(), filters)
    return result
