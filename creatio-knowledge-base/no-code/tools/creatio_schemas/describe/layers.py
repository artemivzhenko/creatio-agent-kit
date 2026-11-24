"""The layers of a schema on an environment: every SysSchema copy of the name, in the order the platform applies them.

One SQL call (through Environment.sql, so clio's file form) returns each copy with its package, ExtendParent,
ModifiedOn and ModifiedBy, IsChanged, the size and md5 of its body (SysSchemaContent, else the MetaData column)
and its level in the package hierarchy of the customisation package (the platform function the object
toolkit's base fetch uses). The copy applied last wins - and when it lives in the customisation package
(`Custom`, or project.json environment.customLayer), it overrides every package the task pushes. With a rule
UId, each layer's body says whether that business rule is absent, enabled, disabled or removed there.
PostgreSQL only, like the other probes.
"""

from __future__ import annotations

import json

from ..entity.hierarchy import merge_order

CUSTOM_LAYER = "Custom"


from ..records import quote as _quote  # noqa: E402


def layers_sql(schema: str, custom_layer: str = CUSTOM_LAYER) -> str:
    name, custom = _quote(schema), _quote(custom_layer)
    return f"""select p."Name"::text "package", s."ExtendParent"::text "extendParent", s."ModifiedOn"::text "modifiedOn",
  coalesce(c."Name", '')::text "modifiedBy", s."IsChanged"::text "isChanged", s."ManagerName"::text "manager",
  coalesce(octet_length(b."Content"), octet_length(s."MetaData"), 0)::text "size",
  coalesce(md5(b."Content"), md5(s."MetaData"), '')::text "md5",
  coalesce(convert_from(b."Content", 'UTF8'), '')::text "body",
  coalesce(h."SchemaLevel"::text, '-1') "sl", coalesce(h."PackageLevel"::text, '-1') "pl", p."HierarchyLevel"::text "hl"
from "SysSchema" s
join "SysPackage" p on p."Id" = s."SysPackageId"
left join "Contact" c on c."Id" = s."ModifiedById"
left join lateral (select sc."Content" from "SysSchemaContent" sc where sc."SysSchemaId" = s."Id"
  order by octet_length(sc."Content") desc limit 1) b on true
left join "tsp_GetSysSchemaParentsInPackageHierarchyByPackage"(
  (select "UId" from "SysSchema" where "Name" = {name} and not "ExtendParent" limit 1),
  (select "UId" from "SysSchema" where "Name" = {name} and not "ExtendParent" limit 1),
  (select "SysWorkspaceId" from "SysPackage" where "Name" = {custom}),
  (select "Id" from "SysPackage" where "Name" = {custom})) h on h."Id" = s."Id"
where s."Name" = {name}"""


def rule_state(body: str, uid: str) -> str:
    """absent / enabled / disabled / removed of a business rule (by UId) in a Classic UI body; `no body` when empty."""
    if not body.strip():
        return "no body"
    from ..classicui.schema import ClassicSchema
    from ..text import mask

    view = ClassicSchema.__new__(ClassicSchema)  # the reader's parse over a text, without package files
    view.body, view.masked, view.name = body, mask(body), "layer"
    view.module_name, view.dependencies, view.sections, view._return_at, view._deps_at = None, [], {}, None, None
    view._parse()
    hit = view._rule_at(uid)
    if not hit:
        return "absent"
    props = {k: view._literal(va, vb) for k, _, va, vb in view._members(hit[1])}
    if props.get("removed") == "true":
        return "removed"
    return "disabled" if props.get("enabled") == "false" else "enabled"


def site_name_of(env, workspace, schema: str) -> str | None:
    """The name the site gives the schema when it differs from the workspace's: the `SysSchema.Name` of the UIds the workspace's copies
    of `schema` carry. A schema renamed in the designer keeps its UId, a push from git brings the old name back."""
    import json

    from ..files import read_text
    from .index import packages_of
    uids = set()
    for pkg in packages_of(workspace):
        path = pkg / "Schemas" / schema / "descriptor.json"
        if path.is_file():
            uid = json.loads(read_text(path)[0].lstrip("﻿"))["Descriptor"].get("UId")
            if uid:
                uids.add(str(uid).lower())
    if not uids:
        return None
    names = sorted({r["name"] for r in env.sql('select distinct "Name"::text "name" from "SysSchema" where "UId" in ('
                                               + ", ".join(_quote(u) for u in sorted(uids)) + ")")})
    return next((n for n in names if n != schema), None) if schema not in names else None


def _runtime_order(rows: list[dict]) -> list[dict]:
    """The replacing copies re-sorted the way the runtime folds them - `SysPackage.HierarchyLevel`, then the package name -
    in the places the design-time function gave them; that function has no tiebreak for siblings and printed a chain's
    upper package before the lower one (S27-T09). The same rule as `merge.layers_in_order`. Unchanged when a copy has no level."""
    replacing = [r for r in rows if str(r.get("extendParent", "")).lower() == "true"]
    if len(replacing) < 2 or any(not str(r.get("hl") or "").lstrip("-").isdigit() for r in replacing):
        return rows
    ordered, ids = iter(sorted(replacing, key=lambda r: (int(r["hl"]), r["package"]))), {id(r) for r in replacing}
    return [next(ordered) if id(r) in ids else r for r in rows]


def _is_postgres(env) -> bool:
    """`select version()` names PostgreSQL; on MS SQL the query itself fails."""
    try:
        return any("postgresql" in str(r.get("v", "")).lower() for r in env.sql('select version()::text "v"'))
    except RuntimeError:
        return False


def schema_layers(env, schema: str, rule: str | None = None, custom_layer: str = CUSTOM_LAYER, workspace=None) -> dict:
    """{schema, rule, customLayer, layers: [...] applied first to last, custom: [packages of the customisation layer]}.
    With `workspace`, a schema the site renamed is read under the site's name (`siteName`). A failed query raises, never "no copy"."""
    site_name = site_name_of(env, workspace, schema) if workspace else None
    try:
        rows = env.sql(layers_sql(site_name or schema, custom_layer))
    except RuntimeError as e:  # an empty answer would read as "no copy" (S45-T02)
        where = env.clio_name or env.url
        line = str(e.args[0] if e.args else e).removeprefix("sql: ")
        raise RuntimeError(("" if _is_postgres(env) else f"{where} is not PostgreSQL - the kit's site SQL is PostgreSQL\n")
                           + f"the layers query failed on {where}: {line}") from e
    outside = [r for r in rows if r.get("sl") in (None, "", "-1")]  # not in the customisation package's hierarchy: listed first, applied nowhere above it
    out = []
    for r in outside + _runtime_order(merge_order([r for r in rows if r not in outside])):
        layer = {k: r.get(k, "") for k in ("package", "extendParent", "modifiedOn", "modifiedBy", "isChanged", "manager", "size", "md5")}
        layer["level"] = None if r.get("pl") in (None, "", "-1") else int(r["pl"])
        if rule:
            layer["rule"] = rule_state(r.get("body") or "", rule)
        out.append(layer)
    custom = [x["package"] for x in out if x["package"].lower() == custom_layer.lower()]
    return {"schema": schema, "rule": rule, "customLayer": custom_layer, "layers": out, "custom": custom, "siteName": site_name}


def render(result: dict, env_name: str = "") -> str:
    layers = result["layers"]
    where = f" on {env_name}" if env_name else ""
    if not layers:
        return f"{result['schema']}{where}: no SysSchema copy of that name"
    renamed = [f"  name on site: {result['siteName']} (workspace: {result['schema']})"] if result.get("siteName") else []
    head = f"{result['schema']}{where}: {len(layers)} cop{'y' if len(layers) == 1 else 'ies'}, applied first to last (the last one wins)"
    cols = ["package", "extendParent", "modifiedOn", "modifiedBy", "isChanged", "size", "md5"] + (["rule"] if result["rule"] else [])
    titles = {"extendParent": "replacing", "modifiedOn": "modified on", "modifiedBy": "by", "isChanged": "changed", "size": "bytes"}
    cells = [[titles.get(c, c) for c in cols]] + [[str(x.get(c, ""))[:8] if c == "md5" else str(x.get(c, ""))[:19] if c == "modifiedOn" else str(x.get(c, ""))
                                                   for c in cols] for x in layers]
    widths = [max(len(row[i]) for row in cells) for i in range(len(cols))]
    lines = [head] + renamed + ["  " + "  ".join(v.ljust(w) for v, w in zip(row, widths)).rstrip() for row in cells]
    if result["rule"]:
        lines.append(f"  rule {result['rule']}: {layers[-1]['rule']} in the layer applied last ({layers[-1]['package']})")
    if result["custom"]:
        lines.append(f"Custom layer present: {', '.join(result['custom'])} - it cannot be deleted by the tools; the human removes it on the site")
    return "\n".join(lines)


def to_json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


# -- S22-T04: the site's copy of a schema as package files ------------------------------------- #

COPY_SQL = """select s."Id"::text "id", encode(s."MetaData", 'base64')::text "meta",
  coalesce((select encode(sc."Content", 'base64') from "SysSchemaContent" sc where sc."SysSchemaId" = s."Id"
    order by octet_length(sc."Content") desc limit 1), '')::text "content"
from "SysSchema" s join "SysPackage" p on p."Id" = s."SysPackageId" where s."Name" = {name} and p."Name" = {package}"""
STRINGS_SQL = """select l."Key"::text "key", c."Name"::text "culture", coalesce(l."Value", '')::text "value"
from "SysLocalizableValue" l join "SysCulture" c on c."Id" = l."SysCultureId"
where l."SysSchemaId" = {id} and l."Value" is not null order by 2, 1"""


def _bytes(b64: str) -> bytes:
    import base64

    return base64.b64decode("".join((b64 or "").split()))


def site_copy(env, package, names: list[str], target) -> None:
    """Write the site's copy of each schema (in the package of that name on the site) into the package folder `target`, the
    way `clio pull-pkg` lays it out: `metadata.json` is `SysSchema.MetaData` and the body (`<Name>.js` / `.cs`) the largest
    `SysSchemaContent`, byte for byte; the resource strings are the copy's `SysLocalizableValue` rows. The descriptor and the
    files the site does not keep apart (properties.json) are the working copy's. A schema the site does not have raises KeyError."""
    import shutil
    from pathlib import Path

    from ..files import write_text
    from ..resources import Resources
    from ..workspace import Package

    package, target = Path(package), Path(target)
    pkg_name = Package(package).name
    shutil.copy2(package / "descriptor.json", target / "descriptor.json")
    for name in names:
        rows = env.sql(COPY_SQL.format(name=_quote(name), package=_quote(pkg_name)))
        if not rows:
            raise KeyError(f"{name} is not on the site in package {pkg_name}")
        local, folder = package / "Schemas" / name, target / "Schemas" / name
        folder.mkdir(parents=True)
        for f in local.glob("*") if local.is_dir() else []:
            if f.is_file() and f.name not in ("metadata.json", f"{name}.js", f"{name}.cs"):
                shutil.copy2(f, folder / f.name)
        (folder / "metadata.json").write_bytes(_bytes(rows[0]["meta"]))
        if rows[0]["content"]:
            suffix = ".cs" if (local / f"{name}.cs").is_file() else ".js"
            (folder / f"{name}{suffix}").write_bytes(_bytes(rows[0]["content"]))
        res_dirs = sorted((package / "Resources").glob(f"{name}.*")) if (package / "Resources").is_dir() else []
        strings = env.sql(STRINGS_SQL.format(id=_quote(rows[0]["id"])))
        if res_dirs and strings:
            res = Resources.empty(target / "Resources" / res_dirs[0].name, [])
            for r in strings:
                res.set(r["key"], r["value"], [r["culture"]])
            for path, (text, bom) in res.files().items():
                write_text(path, text, bom)
