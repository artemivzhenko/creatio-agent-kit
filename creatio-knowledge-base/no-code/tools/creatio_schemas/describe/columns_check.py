"""`describe.py columns-check <package> -e <env>`: the column references of a package that the site does not have (S48-T16).

References read from the files: Freedom page attributes (`DS.Column.Sub` through the data source's object) and the data
sources' own attribute paths, process filters and Add / Modify data columns, C# `AddColumn("a.b")` after the nearest
preceding `new EntitySchemaQuery(..., "Root")`. Not read: Classic rules and `bindTo`. Each root object is asked of the site once
(its table's columns and foreign keys, read-only); a lookup column `X` is the table column `XId`; a path is followed through the
foreign keys and left unchecked where the site has none.
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import filters
from ..csharp.source import csharp_files
from ..files import is_uid, read_text
from ..records import quote
from .core import kind_of, open_item
from .site import columns_sql

FK_SQL = ('select a.attname::text "column", t.relname::text "ref" from pg_constraint c join pg_class s on s.oid = c.conrelid '
          'join pg_class t on t.oid = c.confrelid join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1] '
          "where c.contype = 'f' and s.relnamespace = current_schema()::regnamespace and s.relname = {name}")
_QUERY_RE = re.compile(r'new\s+EntitySchemaQuery\([^;"]*?,\s*"(\w+)"\s*\)|\.AddColumn\(\s*"([\w.]+)"')


class SiteColumns:
    def __init__(self, env):
        self.env, self.cache = env, {}

    def of(self, obj: str) -> tuple[set[str], dict[str, str]]:
        if obj not in self.cache:
            cols = {r["column"] for r in self.env.sql(columns_sql([obj]))}
            refs = {r["column"]: r["ref"] for r in self.env.sql(FK_SQL.format(name=quote(obj)))} if cols else {}
            self.cache[obj] = cols, refs
        return self.cache[obj]

    def missing(self, root: str, path: str) -> str | None:
        """What is absent on the site (`Obj.Column`, `Obj (object)`), None when every segment exists or cannot be followed."""
        obj, parts = root, path.split(".")
        for i, part in enumerate(parts):
            cols, refs = self.of(obj)
            if not cols:
                return f"{obj} (object)"
            if part != "Id" and part not in cols and part + "Id" not in cols:
                return f"{obj}.{part}"
            if i < len(parts) - 1:
                obj = refs.get(part + "Id") or refs.get(part)
                if not obj:
                    return None
        return None


def _filter_paths(group: dict) -> list[str]:
    out = []
    for item in (group.get("items") or {}).values():
        if "items" in item:
            out += _filter_paths(item)
        elif (item.get("leftExpression") or {}).get("columnPath"):
            out.append(item["leftExpression"]["columnPath"])
    return out


def _page(item) -> list[tuple[str, str, str]]:
    def entity(ds):
        return ((item.data_sources.get(ds) or {}).get("config") or {}).get("entitySchemaName")

    out = []
    for key in item.attributes:
        ds, _, path = item._attr_path(key).partition(".")
        if entity(ds) and path:
            out.append((f"attribute {key}", entity(ds), path))
    for ds, cfg in item.data_sources.items():
        for key, attr in ((cfg.get("config") or {}).get("attributes") or {}).items() if isinstance(((cfg.get("config") or {}).get("attributes")), dict) else []:
            if entity(ds) and isinstance(attr, dict):
                out.append((f"data source {ds} attribute {key}", entity(ds), attr.get("path") or key))
    return out


def _process(item) -> list[tuple[str, str, str]]:
    out = []
    for el in item.elements:
        for p in item.element_params(el):
            f = filters.load((p.get("L8") or {}).get("GS2")) if p.get("A2") == "DataSourceFilters" else None
            for path in _filter_paths(f) if f and f.get("rootSchemaName") else []:
                out.append((f"{el['A2']} filter", f["rootSchemaName"], path))
        try:
            entity = item._record_target(el)[1]
            values = item.record_values(el)
        except (ValueError, KeyError):
            continue
        out += [(f"{el['A2']} value", entity, col) for col, _ in values if not is_uid(entity) and not is_uid(col)]
    return out


def _csharp(path: Path) -> list[tuple[str, str, str]]:
    root, out = None, []
    for m in _QUERY_RE.finditer(read_text(path)[0]):
        if m.group(1):
            root = m.group(1)
        elif root:
            out.append(("AddColumn", root, m.group(2)))
    return out


def references(package: Path, schema: str | None = None) -> list[tuple[str, str, str, str]]:
    """(schema, where, root object, path) of everything the package refers to."""
    package, out = Path(package), []
    for folder in sorted((package / "Schemas").glob("*")) if (package / "Schemas").is_dir() else []:
        if schema and folder.name != schema:
            continue
        try:
            item = open_item(package, folder.name)
        except FileNotFoundError:
            continue
        kind = kind_of(item)
        found = _page(item) if kind == "page" else _process(item) if kind == "process" else []
        out += [(folder.name, *r) for r in found]
    for path in csharp_files(package):
        if not schema or path.stem == schema:
            out += [(path.stem, *r) for r in _csharp(path)]
    return out


def columns_check(package: Path | str, env, schema: str | None = None) -> tuple[str, int]:
    """One line per reference to a column the site lacks, and 1 when there is one."""
    site, lines = SiteColumns(env), []
    for name, where, root, path in references(Path(package), schema):
        gone = site.missing(root, path)
        line = f"{name}: {where}: {gone} is missing on the site (path {root}.{path})" if gone else None
        if line and line not in lines:
            lines.append(line)
    return "\n".join(lines) or "every column reference exists on the site", 1 if lines else 0
