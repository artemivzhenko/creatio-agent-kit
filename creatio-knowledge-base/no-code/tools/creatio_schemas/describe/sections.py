"""Which section opens a page, for which object and record type (S31-T07).

The workspace's `SysModuleEdit` bindings name the page (`CardSchemaUId`) and the `SysModuleEntity` (the object, and the
type column by UId) with the type value (`TypeColumnValue`; none = the default page); `SysModule` gives the section and
its caption. With an environment the same rows come from the site's tables (read-only SQL), so a page registered by a
package the workspace does not hold is answered too.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..files import read_text
from ..records import quote
from ..workspace import Workspace

NOT_REGISTERED = "not registered in this workspace (a parent package may register it)"


def _value(v):
    return None if v in (None, "", "null") else str(v).lower() if isinstance(v, str) else v


def _rows(root: Path, schema: str) -> list[dict]:
    """Every row of every readable binding of `schema` in the workspace, localised columns as {culture: text}."""
    from ..data import DataBinding

    out = []
    for ddir in sorted(root.glob("*/Data/*")):
        try:
            if json.loads(read_text(ddir / "descriptor.json")[0])["Descriptor"]["Schema"]["Name"] != schema:
                continue
            out += DataBinding(ddir.parent.parent, ddir.name).rows()
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def _text(value, culture: str | None) -> str | None:
    if isinstance(value, dict):
        return value.get(culture) or value.get("en-US") or next((v for v in value.values() if v), None)
    return None if value in (None, "", "null") else str(value)


def _type_text(ws: Workspace, entity: str | None, type_column: str | None, value: str) -> str:
    """`ActivityType = 'Meeting' (<id>)`: the type column's name and the lookup value's Name the bindings hold, else the Id."""
    column = ref = None
    if entity and type_column:
        column = next((n for n, u in ws.column_uids(entity).items() if u == type_column), None)
        ref = ws.columns(entity).get(column, (None, None))[1] if column else None
    rows = ws.lookup_rows()
    name = (rows.get(ref) or {}).get(value) if ref else None
    name = name or ws.lookup_captions().get(value)
    return f"record type {column or 'type'} = " + (f"{name!r} ({value})" if name else value)


def _line(ws: Workspace, r: dict, site: str = "") -> str:
    section = f"section {r['code']}" + (f" {r['caption']!r}" if r.get("caption") else "") if r.get("code") else "section not in workspace"
    if r.get("section_schema"):
        section += f" (SysModule {r['section_schema']})"
    obj = r.get("object") or r.get("entity_uid")
    parts = [section] + ([f"object {obj}"] if obj else [])
    parts.append(_type_text(ws, r.get("object"), r.get("type_column"), r["type"]) if r.get("type") else "default page (no type)")
    return ", ".join(parts) + (f" (site {site})" if site else "")


def registrations(package: Path, page_uid: str, culture: str | None = None) -> list[dict]:
    """The workspace's registrations of a page: {code, caption, section_schema, object, entity_uid, type_column, type} per SysModuleEdit row."""
    root = Path(package).parent
    ws = Workspace(package)
    entities = {_value(r.get("Id")): r for r in _rows(root, "SysModuleEntity")}
    modules = {}
    for m in _rows(root, "SysModule"):
        modules.setdefault(_value(m.get("SysModuleEntity")), m)
    out = []
    for e in _rows(root, "SysModuleEdit"):
        if _value(e.get("CardSchemaUId")) != page_uid.lower():
            continue
        me = entities.get(_value(e.get("SysModuleEntity"))) or {}
        m = modules.get(_value(e.get("SysModuleEntity"))) or {}
        entity_uid = _value(me.get("SysEntitySchemaUId"))
        out.append({"code": _text(m.get("Code"), culture), "caption": _text(m.get("Caption"), culture),
                    "section_schema": ws.name_of(_value(m.get("SectionSchemaUId"))), "object": ws.name_of(entity_uid), "entity_uid": entity_uid,
                    "type_column": _value(me.get("TypeColumnUId")), "type": _value(e.get("TypeColumnValue"))})
    return out


def site_sql(page_uid: str) -> str:
    return f"""select coalesce(m."Code", '')::text "code", coalesce(m."Caption", '')::text "caption", coalesce(ss."Name", '')::text "section_schema",
  coalesce(es."Name", '')::text "object", coalesce(me."SysEntitySchemaUId"::text, '') "entity_uid",
  coalesce(me."TypeColumnUId"::text, '') "type_column", coalesce(e."TypeColumnValue"::text, '') "type"
from "SysModuleEdit" e
join "SysModuleEntity" me on me."Id" = e."SysModuleEntityId"
left join "SysModule" m on m."SysModuleEntityId" = me."Id"
left join lateral (select s."Name" from "SysSchema" s where s."UId" = m."SectionSchemaUId" limit 1) ss on true
left join lateral (select s."Name" from "SysSchema" s where s."UId" = me."SysEntitySchemaUId" and not s."ExtendParent" limit 1) es on true
where e."CardSchemaUId" = {quote(page_uid.lower())}
order by e."TypeColumnValue" nulls first"""


def opens_from(package: Path, name: str, page_uid: str | None, culture: str | None = None, env=None, env_name: str = "") -> list[str]:
    """`opens from:` lines of a page: one per registration; the workspace's, or the site's with `env`."""
    if not page_uid:
        return [f"opens from: {NOT_REGISTERED}"]
    ws = Workspace(package)
    if env is not None:
        rows = [{k: (_value(v) if k in ("entity_uid", "type_column", "type") else (v or None)) for k, v in r.items()} for r in env.sql(site_sql(page_uid))]
        if not rows:
            return [f"opens from: not registered on the site (site {env_name})"]
        return [f"opens from: {_line(ws, r, env_name)}" for r in rows]
    rows = registrations(package, page_uid, culture)
    return [f"opens from: {_line(ws, r)}" for r in rows] or [f"opens from: {NOT_REGISTERED}"]


def pages_of(package: Path, entity: str, culture: str | None = None) -> str | None:
    """`pages: UsrOrder_FormPage (default), UsrOrderVip_FormPage (type 'VIP')` of an object, None when no binding registers one."""
    root = Path(package).parent
    ws = Workspace(package)
    uids = {s["uid"] for s in ws.find(entity, "EntitySchemaManager")} | {s["base"] for s in ws.find(entity, "EntitySchemaManager")}
    ids = {_value(r.get("Id")): r for r in _rows(root, "SysModuleEntity") if _value(r.get("SysEntitySchemaUId")) in uids}
    if not ids:
        return None
    out = []
    for e in _rows(root, "SysModuleEdit"):
        me = ids.get(_value(e.get("SysModuleEntity")))
        if me is None:
            continue
        page = ws.name_of(_value(e.get("CardSchemaUId"))) or _value(e.get("CardSchemaUId"))
        t = _value(e.get("TypeColumnValue"))
        if t:
            text = _type_text(ws, entity, _value(me.get("TypeColumnUId")), t).split(" = ", 1)[1]
            out.append(f"{page} (type {text})")
        else:
            out.append(f"{page} (default)")
    return "pages: " + ", ".join(out) if out else None


def schema_lines(item) -> list[str]:
    """What `describe_schema` adds after its first line: a Freedom page's `opens from`, a Classic schema's when a binding registers it,
    an object's `pages`."""
    from ..classicui import ClassicSchema
    from ..entity import EntitySchema
    from ..page import PageSchema

    from .queries import package_culture

    data = getattr(getattr(item, "descriptor", None), "data", None) or {}
    if isinstance(item, PageSchema) and not getattr(item, "mobile", False):
        return opens_from(item.package, item.name, data.get("UId"), package_culture(item))
    if isinstance(item, ClassicSchema):
        culture = package_culture(item)
        return opens_from(item.package, item.name, data["UId"], culture) if data.get("UId") and registrations(item.package, data["UId"], culture) else []
    if isinstance(item, EntitySchema):
        from .index import index_path
        from .site import summary_line

        line = pages_of(item.package, item.name)
        return ([line] if line else []) + summary_line(index_path(item.package), item.name)  # S31-T10: the site's extra columns
    return []


def shown_on(package: Path, detail: str) -> list[str]:
    """`shown on <Page> as <name>, filtered by <Object>.<Column> = <master>` for every Classic page of the workspace whose details name `detail`."""
    from ..classicui import ClassicSchema
    from ..classicui.view import _detail_text, _details

    out = []
    for s in Workspace(package).schemas:
        body = s["dir"] / f"{s['name']}.js"
        if s["manager"] != "ClientUnitSchemaManager" or s["name"] == detail or not body.is_file() or detail not in read_text(body)[0]:
            continue
        try:
            page = ClassicSchema(s["dir"].parent.parent, s["name"])
        except (OSError, ValueError, KeyError):
            continue
        for key, d in _details(page).items():
            if d.get("schemaName") == detail:
                rest = _detail_text(d).removeprefix(f"detail {d.get('schemaName', '?')}").strip()  # "of <Object> filtered by ..."
                out.append(f"shown on {page.name} as {key}" + (f", {rest}" if rest else ""))
    return out or ["shown on no page of this workspace"]
