"""The layers of one schema across a workspace, in the order the platform applies them (S24: the layer merge).

`layers_in_order(workspace, schema, env=None)` is the one place that order comes from; the merge plan (T03) and the
object snapshot (T02) both read it.

- With `env`: the site's order (`schema_layers`: every SysSchema copy of the name, applied first to last). A copy
  on the site only (the vendor base, a package not in the workspace) has no folder. A workspace copy the site
  does not have yet comes after them, in dependency order, with `source = "workspace"`.
- Without `env`: the workspace's copies only (a vendor base is not on disk). The own (not replacing) copy first,
  then the replacing ones so that a package comes after every package it depends on, directly or through other
  packages of the workspace (descriptor.json `DependsOn`). Two layers with no dependency path either way are
  siblings: the platform's order between them is not known from the files, so they are put by package name and
  each names the other in `siblings`.

`merge_plan(workspace, schemas=None, env=None)` (T03) is what collapsing those layers into one would do, from the
describe layer's own answers (an object's added columns, a client schema's diff and methods, a page's viewConfigDiff
and handlers): the target package, what each layer adds, the conflicts that stop a merge, the dependencies the
target must take over. It opens the layer files and writes nothing either.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..files import read_text
from ..text import mask
from .core import DEFAULT_LIMIT, cut
from .index import packages_of
from .layers import schema_layers


@dataclass(frozen=True)
class Layer:
    package: str
    folder: Path | None  # <package>/Schemas/<schema>; None when the copy is on the site only
    replacing: bool
    uid: str = ""  # the schema UId from the local descriptor ("" for a site-only copy)
    manager: str = ""
    source: str = "workspace"  # "site": the position is the site's; "workspace": derived from DependsOn
    siblings: tuple[str, ...] = ()  # packages of the layers whose order against this one is guessed


def _descriptor(path: Path) -> dict:
    return json.loads(read_text(path)[0].lstrip("﻿"))["Descriptor"]


def _workspace(workspace: Path | str) -> tuple[dict[str, Path], dict[str, set[str]]]:
    """{package name: folder}, {package name: every package it depends on, transitively, as far as the workspace knows}."""
    folders, reach, _ = _graph(workspace)
    return folders, reach


def _graph(workspace: Path | str) -> tuple[dict[str, Path], dict[str, set[str]], dict[str, set[str]]]:
    """folders, transitive dependencies, direct dependencies (descriptor.json `DependsOn`) of every workspace package."""
    folders, direct = {}, {}
    for pkg in packages_of(workspace):
        d = _descriptor(pkg / "descriptor.json")
        name = d.get("Name") or pkg.name
        folders[name] = pkg
        direct[name] = {x["Name"] for x in d.get("DependsOn") or []}
    reach: dict[str, set[str]] = {}

    def closure(name: str, path: frozenset = frozenset()) -> set[str]:
        if name in reach:
            return reach[name]
        out = set()
        for dep in direct.get(name, ()):
            if dep not in path:  # a dependency cycle: stop on it rather than recurse forever
                out |= {dep} | closure(dep, path | {name})
        reach[name] = out
        return out

    for name in direct:
        closure(name)
    return folders, reach, direct


def _local(folders: dict[str, Path], schema: str, manager: str | None) -> dict[str, Layer]:
    out = {}
    for name, pkg in folders.items():
        path = pkg / "Schemas" / schema / "descriptor.json"
        if not path.is_file():
            continue
        d = _descriptor(path)
        if manager and d.get("ManagerName") != manager:
            continue
        out[name] = Layer(name, path.parent, bool(d.get("ExtendParent")), d.get("UId", ""), d.get("ManagerName", ""))
    return out


def _depth(direct: dict[str, set[str]]):
    """The longest DependsOn chain below a package, over the workspace packages (a vendor package counts as 0)."""
    memo: dict[str, int] = {}

    def depth(name: str, path: frozenset = frozenset()) -> int:
        if name not in memo:
            below = [depth(d, path | {name}) for d in direct.get(name, ()) if d in direct and d not in path]
            memo[name] = 1 + max(below) if below else 0
        return memo[name]
    return depth


def _dependency_order(layers: list[Layer], reach: dict[str, set[str]], direct: dict[str, set[str]]) -> list[Layer]:
    """Own copies first, then the replacing ones as the platform numbers packages (SysPackage.HierarchyLevel: the
    dependency depth, then the name in ordinal order) - as far as the workspace shows the depth; siblings named."""
    depth = _depth(direct)
    own = sorted((x for x in layers if not x.replacing), key=lambda x: x.package)
    ordered = sorted((x for x in layers if x.replacing), key=lambda x: (depth(x.package), x.package))
    out = list(own)
    for x in ordered:
        loose = tuple(y.package for y in ordered if y is not x and y.package not in reach.get(x.package, set())
                      and x.package not in reach.get(y.package, set()))
        out.append(Layer(x.package, x.folder, x.replacing, x.uid, x.manager, "workspace", loose))
    return out


def layers_in_order(workspace: Path | str, schema: str, env=None, manager: str | None = None) -> list[Layer]:
    """The base and every replacing layer of `schema`, applied first to last (see the module text)."""
    folders, reach, direct = _graph(workspace)
    local = _local(folders, schema, manager)
    if env is None:
        return _dependency_order(list(local.values()), reach, direct)
    out = []
    for row in schema_layers(env, schema)["layers"]:
        if manager and row.get("manager") != manager:
            continue
        mine = local.pop(row["package"], None)
        out.append(Layer(row["package"], mine.folder if mine else None, str(row.get("extendParent")).lower() == "true",
                         mine.uid if mine else "", row.get("manager") or (mine.manager if mine else ""), "site"))
    out = _by_hierarchy_level(env, out)
    # shortcut: a copy not pushed yet goes after the site's copies; place it among them by DependsOn when T04 pushes new layers
    return out + _dependency_order(list(local.values()), reach, direct)


LEVELS_SQL = 'select "Name"::text "package", "HierarchyLevel"::text "level" from "SysPackage" where "Name" in ({names})'


def _by_hierarchy_level(env, layers: list[Layer]) -> list[Layer]:
    """The replacing copies re-sorted the way the runtime folds them (story README fact 1: SysPackage.HierarchyLevel, then
    the name in ordinal order); `schema_layers`' design-time function has no tiebreak for siblings. Unchanged when the
    site gives no level for one of them."""
    replacing = [x for x in layers if x.replacing]
    if len(replacing) < 2:
        return layers
    names = ", ".join("'" + x.package.replace("'", "''") + "'" for x in replacing)
    levels = {r["package"]: r["level"] for r in env.sql(LEVELS_SQL.format(names=names)) if r.get("level") not in (None, "")}
    if any(x.package not in levels for x in replacing):
        return layers
    ordered = iter(sorted(replacing, key=lambda x: (int(levels[x.package]), x.package)))
    return [next(ordered) if x.replacing else x for x in layers]


# --------------------------------------------------------------------------- #
# The merge plan (T03)
# --------------------------------------------------------------------------- #

CHANGING_OPS = {"merge", "remove", "move"}  # two layers changing one element: which wins is the layer order
_USED_RE = re.compile(r"(?<![=!<>])=\s*[\w.$]*\bcallParent\s*\(")  # `var x = this.callParent(...)`


@dataclass
class _Ctx:
    folders: dict[str, Path]
    reach: dict[str, set[str]]
    direct: dict[str, set[str]]
    own: dict[str, str]  # object name -> the workspace package holding its own (not replacing) copy
    keys: dict[tuple[str, str], int]  # (schema folder name, manager) -> replacing copies in the workspace


def _context(workspace: Path | str) -> _Ctx:
    folders, reach, direct = _graph(workspace)
    own, keys = {}, {}
    for pkg_name, pkg in folders.items():
        for path in (pkg / "Schemas").glob("*/descriptor.json"):
            try:
                d = _descriptor(path)
            except (OSError, ValueError, KeyError):
                continue  # an unreadable descriptor: the plan of that schema says so when it opens the layer
            key = (path.parent.name, d.get("ManagerName", ""))
            if d.get("ExtendParent"):
                keys[key] = keys.get(key, 0) + 1
            else:
                keys.setdefault(key, 0)
                if key[1] == "EntitySchemaManager":
                    own[key[0]] = pkg_name
    return _Ctx(folders, reach, direct, own, keys)


def _call_parent(src: str) -> tuple[bool, bool]:
    """(a callParent inside a nested function, its return value assigned) in a method's source `name: function() {...}`."""
    masked = mask(src)
    stack, pending, callback = [], False, False
    for i in range(masked.find("{") + 1, len(masked)):
        if masked.startswith("function", i) and not (masked[i - 1].isalnum() or masked[i - 1] in "_$") or masked.startswith("=>", i):
            pending = True
        ch = masked[i]
        if ch == "{":
            stack.append(pending)
            pending = False
        elif ch == "}" and stack:
            stack.pop()
        elif ch == ";":
            pending = False
        elif masked.startswith("callParent", i) and any(stack):
            callback = True
    return callback, bool(_USED_RE.search(masked))


_RULE_EDIT_RE = re.compile(r'^([=+~-]) MetaData\.Schema\.AD4\.BRS1\.\["([^"]+)"\](\S*)')


def _contents(layer: Layer, schema: str) -> dict:
    """What one layer adds, from the toolkit object describe opens: columns, elements, methods, handlers."""
    from ..classicui.schema import ClassicSchema
    from ..dcm.schema import DcmSchema
    from ..entity.schema import EntitySchema
    from ..page.schema import PageSchema
    from ..process.schema import ProcessSchema
    from ..rules.schema import RuleSchema
    from .core import kind_of, open_item

    item = open_item(layer.folder.parent.parent, schema)
    out = {"kind": kind_of(item), "columns": [], "elements": [], "methods": {}, "handlers": [], "nodes": [], "parameters": [], "stages": [],
           "rules": [], "rule_edits": {}, "rule_removed": []}
    if isinstance(item, EntitySchema):
        out["columns"] = [(c.get("A2"), (c.get("UId") or "").lower(), c.get("S2"), item.ref_name(c["S4"]) if c.get("S4") else None)
                          for c in item.own_columns()]
    elif isinstance(item, ClassicSchema):
        out["elements"] = [(op["name"], op["operation"]) for op in item.diff_operations() if op["name"]]
        out["methods"] = {m["name"]: item.method(m["name"]) for m in item.methods()}
    elif isinstance(item, PageSchema):
        out["elements"] = [(op.get("name"), op.get("operation")) for op in item.elements()]
        out["handlers"] = [name for name, _ in item.handlers()]
    elif isinstance(item, ProcessSchema):  # kept apart from `elements`: a process is never merged, so it has no element conflicts
        out["nodes"] = [e["A2"] for e in item.nodes() if "A2" in e]
        out["parameters"] = [p["A2"] for p in item.params if "A2" in p]
    elif isinstance(item, DcmSchema):
        out["stages"] = [st["A2"] for st in item.stages]
    elif isinstance(item, RuleSchema):
        out["rules"] = [r["UId"].lower() for r in item.rules]
        # a replacing addon edits the rules of the base addon by UId: `= / + / - MetaData.Schema.AD4.BRS1.["<uid>"]...`
        for line in item.base_edits() if item.replacing else []:
            m = _RULE_EDIT_RE.match(line)
            if m:
                uid = m.group(2).lower()
                out["rule_edits"].setdefault(uid, []).append(line)
                if m.group(1) == "-" and not m.group(3):
                    out["rule_removed"].append(uid)
    return out


def _and(names) -> str:
    names = list(names)
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


def _counts(c: dict) -> str:
    def n(count, word):
        return f"+{count} {word}{'' if count == 1 else 's'}"
    parts = [n(len(c[k]), w) for k, w in (("columns", "column"), ("elements", "element"), ("nodes", "element"), ("parameters", "parameter"),
                                                     ("stages", "stage"), ("rules", "rule"), ("methods", "method"), ("handlers", "handler")) if c[k]]
    if c.get("rule_edits"):
        n_edited = len(c["rule_edits"])
        parts.append(f"~{n_edited} base rule{'' if n_edited == 1 else 's'} edited")
    return ", ".join(parts) or "nothing added"


def _conflicts(order: list[str], contents: dict[str, dict], ctx: _Ctx, target: str) -> list[str]:
    from ..files import ALL_DATA_VALUE_TYPES

    out = []
    by_name, by_uid = {}, {}
    for p in order:
        for name, uid, typ, ref in contents[p]["columns"]:
            by_name.setdefault(name, {}).setdefault(uid, []).append(p)
            by_uid.setdefault(uid, {}).setdefault(typ, []).append(p)
            owner = ctx.own.get(ref or "")
            if owner and owner != target and target in ctx.reach.get(owner, set()):
                out.append(f"conflict lookup {name} -> {ref} (its package {owner} depends on the target): {p}")
    for name, uids in by_name.items():
        if len(uids) > 1:
            out.append(f"conflict column {name} (two UIds): {_and(p for ps in uids.values() for p in ps)}")
    for uid, types in by_uid.items():
        if len(types) > 1:
            out.append(f"conflict column {uid} (types {', '.join(ALL_DATA_VALUE_TYPES.get(t, str(t)) for t in types)}): "
                       f"{_and(p for ps in types.values() for p in ps)}")
    changing = {}
    for p in order:
        for name, op in contents[p]["elements"]:
            if op in CHANGING_OPS:
                changing.setdefault(name, {}).setdefault(p, op)
    for name, layers in changing.items():
        if len(layers) > 1:
            out.append(f"conflict element {name} ({', '.join(sorted(set(layers.values())))}): {_and(layers)}")
    methods = {}
    for p in order:
        for name in contents[p]["methods"]:
            methods.setdefault(name, []).append(p)
    for name, layers in methods.items():
        if len(layers) < 2:
            continue  # a method in one layer moves as it is
        out.append(f"conflict method {name}{' (three-deep override)' if len(layers) > 2 else ''}: {_and(layers)}")
        for p in layers:
            callback, used = _call_parent(contents[p]["methods"][name])
            if callback:
                out.append(f"conflict callParent in a callback, method {name}: {p}")
            if used:
                out.append(f"conflict callParent return value used, method {name}: {p}")
    return out


def _rule_conflicts(order: list[str], contents: dict[str, dict]) -> list[str]:
    """The same own rule UId in two layers; a base rule removed in one layer and edited (or removed) in another. Edits of one base
    rule by several layers are not conflicts: the diffs concatenate in fold order, which is how the platform folds them."""
    out = []
    owners: dict[str, list[str]] = {}
    for p in order:
        for uid in contents[p]["rules"]:
            owners.setdefault(uid, []).append(p)
    out += [f"conflict rule {uid}: {_and(ps)}" for uid, ps in sorted(owners.items()) if len(ps) > 1]
    for p in order:
        for uid in sorted(set(contents[p]["rule_removed"])):
            others = [q for q in order if q != p and uid in contents[q]["rule_edits"]]
            if others:
                out.append(f"conflict rule {uid} (removed in {p}, edited in {_and(others)}): {_and([p] + others)}")
    return out


def plan_schema(ctx: _Ctx, workspace: Path | str, schema: str, manager: str = "", env=None, target: str | None = None,
                only: set[str] | None = None) -> dict:
    """{schema, kind, layers, target, remove, conflicts, skipped, lines, order} for one schema (see merge_plan). `target`
    names the package instead of the lowest layer: one every layer's package depends on (it need not hold a layer)."""
    layers = layers_in_order(workspace, schema, env, manager or None)
    if only:  # merge-package: the layers of these packages only; another package's layer is like one on the site only
        layers = [Layer(x.package, x.folder, x.replacing, x.uid, x.manager, x.source, tuple(p for p in x.siblings if p in only))
                  if x.package in only else Layer(x.package, None, x.replacing, x.uid, x.manager, x.source) for x in layers]
    disk = [x for x in layers if x.replacing and x.folder is not None]
    res = {"schema": schema, "kind": "?", "layers": len(disk), "target": None, "remove": 0, "conflicts": [], "skipped": False, "lines": []}
    if len(disk) < 2:
        res["lines"] = [f"{schema}: {len(disk)} replacing layer{'' if len(disk) == 1 else 's'} in the workspace, nothing to merge"]
        return res
    contents = {}
    for x in disk:
        try:
            contents[x.package] = _contents(x, schema)
        except Exception as e:  # one unreadable layer stops this schema's merge, not the plan
            contents[x.package] = {"error": f"{type(e).__name__}: {e}"}
    res["kind"] = next((c["kind"] for c in contents.values() if "kind" in c), "?")
    names = [x.package for x in disk]
    res["order"] = disk
    if target:
        if target not in ctx.folders or any(q != target and target not in ctx.reach.get(q, set()) for q in names):
            res.update(skipped=True, lines=[f"{schema} {res['kind']}: {len(disk)} layers, target {target} is not below every layer: "
                                            + ", ".join(q for q in names if q != target and target not in ctx.reach.get(q, set()))])
            return res
        lowest = [target]
    else:
        lowest = [p for p in names if all(p in ctx.reach.get(q, set()) for q in names if q != p)]
    if len(lowest) != 1:
        bottom = sorted(p for p in names if not ctx.reach.get(p, set()) & set(names))
        res.update(skipped=True, lines=[f"{schema} {res['kind']}: {len(disk)} layers, no common lowest package: {', '.join(bottom)}"])
        return res
    target = res["target"] = lowest[0]
    res["remove"] = len(disk) - (1 if target in names else 0)
    lines = [f"{schema} {res['kind']}: {len(disk)} layers, target {target}"]
    # a site-only layer folded after the first merged one: the merge would move the removed layers' lines before it
    res["between"] = [x.package for x in layers[layers.index(disk[0]):] if x.replacing and x.folder is None
                      and (not only or layers.index(x) < layers.index(disk[-1]))]  # above every merged layer it keeps its place
    for x in layers:
        if not x.replacing:
            continue
        if x.folder is None:
            lines.append(f"  layer {x.package}: on the site only, not merged")
            continue
        c = contents[x.package]
        if "error" in c:
            lines.append(f"  layer {x.package}: unreadable: {c['error']}")
            res["conflicts"].append(f"conflict unreadable layer: {x.package}")
        else:
            lines.append(f"  layer {x.package}: {_counts(c)}")
    guessed = [x.package for x in disk if x.siblings]
    if guessed:
        lines.append(f"  siblings: {', '.join(guessed)} (order guessed)")
    readable = [p for p in names if "error" not in contents[p]]
    res["conflicts"] += _conflicts(readable, contents, ctx, target)
    if res["kind"] == "rules":
        res["conflicts"] += _rule_conflicts(readable, contents)
    if res["kind"] in NOT_MERGED:
        # the layers of a process hold whole schemas and running instances point at them (S24-T06): listed, never merged
        res["conflicts"].append(f"conflict {res['kind']}: not merged by this toolkit (T06)")
    gains = set()
    for p in names:
        if p == target:
            continue
        for g in ctx.direct.get(p, ()):
            # a package above the target is not gained (a cycle); content that needs one is a `conflict lookup`
            if g != target and g not in names and g not in ctx.reach.get(target, set()) and target not in ctx.reach.get(g, set()):
                gains.add(g)
    lines += [f"  {c}" for c in res["conflicts"]]
    res["gains"] = sorted(gains)
    if gains:
        lines.append(f"  depends: {target} gains {', '.join(res['gains'])}")
    res["lines"] = lines
    return res


def merge_plan(workspace: Path | str, schemas: list[str] | None = None, env=None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> tuple[str, int]:
    """(text, conflicts): the plan of every schema replaced by more than one package (or of `schemas`), then
    `<M> schemas, <L> layers to remove, <C> conflicts`. `env` takes the layer order from the site."""
    ctx = _context(workspace)
    if schemas:
        wanted = {s.lower() for s in schemas}
        keys = sorted(k for k in ctx.keys if k[0].lower() in wanted)
        missing = [s for s in schemas if s.lower() not in {k[0].lower() for k in keys}]
    else:
        keys, missing = sorted(k for k, n in ctx.keys.items() if n > 1), []
    plans = [plan_schema(ctx, workspace, name, manager, env) for name, manager in keys]
    body = [f"{name}: no copy in the workspace" for name in missing] + [line for plan in plans for line in plan["lines"]]
    merged = [p for p in plans if p["layers"] > 1]
    skipped = sum(1 for p in merged if p["skipped"])
    conflicts = sum(len(p["conflicts"]) for p in merged)
    last = (f"{len(merged)} schemas, {sum(p['remove'] for p in merged)} layers to remove, {conflicts} conflicts"
            + (f", {skipped} without a common lowest package" if skipped else ""))
    return "\n".join(cut(body, limit, offset=offset, paged=True) + [last]), conflicts


# --------------------------------------------------------------------------- #
# The merge of an object (T04)
# --------------------------------------------------------------------------- #

# The lines that say whose layer this is: the schema UId, its package, the events process; from one layer only.
IDENTITY = {"MetaData.Schema.UId", "MetaData.Schema.A5", "MetaData.Schema.B6", "MetaData.Schema.B8", "MetaData.Schema.D36.A3",
            "MetaData.Schema.EG1.UId", "MetaData.Schema.EG1.A2", "MetaData.Schema.EG1.A5", "MetaData.Schema.EG1.B8", "MetaData.Schema.EG1.BK8"}
PACKAGE_UID = "MetaData.Schema.B6"
OBJECT = "EntitySchemaManager"
NOT_MERGED = {"process", "dcm"}  # kinds the plan counts and refuses
REFERENCES_FK_SQL = """select tc.table_name::text "table", kcu.column_name::text "column"
from information_schema.table_constraints tc
join information_schema.key_column_usage kcu on kcu.constraint_name = tc.constraint_name
join information_schema.referential_constraints rc on rc.constraint_name = tc.constraint_name
join information_schema.constraint_column_usage ccu on ccu.constraint_name = tc.constraint_name
where tc.constraint_type = 'FOREIGN KEY' and ccu.table_name = 'SysSchema' and ccu.column_name = 'Id' and rc.delete_rule = 'NO ACTION'
order by 1, 2"""
LAYER_IDS_SQL = """select s."Id"::text "id", p."Name"::text "package" from "SysSchema" s join "SysPackage" p on p."Id" = s."SysPackageId"
where s."Name" = {schema} and s."ManagerName" = {manager} and p."Name" in ({packages})"""


def _q(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def platform_drops(op: str, path: str) -> bool:
    """What EntitySchemaManager.ActualizeSchemaDifferencePackage ignores in every layer but the last (story README fact 3)."""
    return op == "+" and "EG1" in path and "C2" in path or op == "-" and "D20.FA" in path


def merged_diff(layers: list[Layer], source: Layer, package_uid: str, renames: dict[str, str] | None = None, drops=platform_drops) -> str:
    """One diff from the layers' diffs in fold order (fact 2): the identity lines of `source` only, B6 = the target package,
    the lines the platform drops left out of every layer but the top. `renames` maps the UIds of the removed layers and of
    their packages to the merged layer's and the target's: a column keeps CreatedInSchemaUId / ModifiedInSchemaUId /
    CreatedInPackageId (A3 / A4 / A5) of a layer that no longer exists otherwise."""
    from ..workspace import parse_diff

    swap = re.compile("|".join(map(re.escape, renames)), re.I) if renames else None
    out = []
    for x in layers:
        for op, path, value in parse_diff(read_text(x.folder / "metadata.json")[0]):
            if path in IDENTITY and x is not source or drops and x is not layers[-1] and drops(op, path):
                continue
            if path == PACKAGE_UID:
                value = json.dumps(package_uid)
            elif swap:
                value = swap.sub(lambda m: renames[m.group(0).lower()], value)
            out.append(f"{op} {path}" + (f" {value}" if value else ""))
    if not any(line.startswith(f"= {PACKAGE_UID} ") for line in out):  # every designer layer has it; a hand-made one may not
        out.insert(1 if out else 0, f"= {PACKAGE_UID} {json.dumps(package_uid)}")
    return "\r\n".join(out)


def references(env, schema: str, packages: list[str], manager: str = OBJECT) -> list[str]:
    """`references: <table>.<column> <n> rows point at <package>'s <Schema>` for every NO ACTION foreign key to SysSchema.Id
    that holds a layer's row (T01: such a row makes the install of the removal fail whole)."""
    ids = {r["id"]: r["package"] for r in env.sql(LAYER_IDS_SQL.format(schema=_q(schema), manager=_q(manager),
                                                                        packages=", ".join(_q(p) for p in packages)))}
    if not ids:
        return []
    keys = ", ".join(_q(i) for i in ids)
    parts = [f'select \'{r["table"]}.{r["column"]}\' "ref", "{r["column"]}"::text "id", count(*)::text "n" from "{r["table"]}" '
             f'where "{r["column"]}" in ({keys}) group by "{r["column"]}"' for r in env.sql(REFERENCES_FK_SQL)]
    hits = env.sql("\nunion all ".join(parts)) if parts else []
    return [f"references: {h['ref']} {h['n']} rows point at {ids.get(h['id'], h['id'])}'s {schema}" for h in hits if int(h.get("n") or 0)]


def _resources(layers: list[Layer], schema: str, folder: Path, suffix: str = "Entity"):
    """The layers' resource files merged key by key, the upper layer winning; None when no layer has any."""
    from ..resources import Resources

    merged, found = Resources(folder), folder.is_dir()
    for x in layers:
        own = x.folder.parent.parent / "Resources" / f"{schema}.{suffix}"
        if not own.is_dir():
            continue
        found = True
        r = Resources(own)
        for culture, items in r.cultures.items():
            for key, value in items.items():
                merged.set(key, value, [culture])
                if r.attrs.get(culture, {}).get(key):
                    merged.attrs.setdefault(culture, {})[key] = r.attrs[culture][key]
    return merged if found else None


def _object_files(order: list[Layer], source: Layer, schema: str, folder: Path, package_uid: str, renames: dict, notes: list) -> tuple[dict, list]:
    """The merged object's files: one diff, descriptor and .cs of the UId source, properties of the top layer."""
    writes: dict[Path, tuple[str, bool]] = {}
    meta, bom = read_text(source.folder / "metadata.json")
    writes[folder / "metadata.json"] = (merged_diff(order, source, package_uid, renames) + ("\r\n" if meta.endswith(("\n", "\r\n")) else ""), bom)
    for name, frm in (("descriptor.json", source), ("properties.json", order[-1]), (f"{schema}.cs", source)):
        if (frm.folder / name).is_file():
            writes[folder / name] = read_text(frm.folder / name)
    return writes, []


def _merge(workspace: Path | str, schema: str, target: str | None, env, apply: bool, manager: str, kinds: set[str], build, suffix: str,
           stop_filter=None, only: set[str] | None = None) -> tuple[str, int]:
    """The shared run of a merge: the plan, the stops, `references`, the UId rule, `DependsOn`, resources merged key by key, the
    deletes of the other layers, `--apply`. `build(order, source, schema, folder, package_uid, renames, notes)` gives the kind's
    files and its own stops; `stop_filter(conflict line)` says which plan conflicts stop this kind (default: all)."""
    import shutil

    from ..files import write_text
    from ..schema import Descriptor

    ctx = _context(workspace)
    plan = plan_schema(ctx, workspace, schema, manager, env, target, only)
    lines, stops, notes = list(plan["lines"]), [], []
    if plan["layers"] < 2:
        other = plan_schema(ctx, workspace, schema, "", env, target)  # another manager: say what it is instead of "nothing to merge"
        if other["layers"] > 1 and other["kind"] not in kinds:
            return "\n".join(other["lines"] + [f"{schema} is a {other['kind']}: merge writes objects and pages only"]), 1
        return "\n".join(lines), 0
    if plan["kind"] not in kinds and not plan["skipped"]:
        stops.append(f"{schema} is a {plan['kind']}: merge writes objects and pages only")
    if plan["skipped"]:
        stops.append("no target; name one with --target")
    blocking = [c for c in plan["conflicts"] if stop_filter is None or stop_filter(c)]
    stops += [f"{len(blocking)} conflicts"] if blocking else []
    order = plan.get("order", [])
    if env is None and any(x.siblings for x in order):
        stops.append("siblings: their order is a guess without the site; run with -e")
    if plan.get("between"):
        stops.append(f"a layer on the site only folds after the target: {', '.join(plan['between'])}; "
                     "the merge would put the removed layers' lines before it")
    if env is not None and not stops:
        files = [x.package for x in layers_in_order(workspace, schema, None, manager) if x.replacing]
        if files != [x.package for x in order]:
            lines.append(f"  order: the site folds {' > '.join(x.package for x in order)}; the files say {' > '.join(files)}; the site's is used")
    whole = [x.package for x in order if read_text(x.folder / "metadata.json")[0].lstrip().startswith("{")]
    if whole:
        stops.append(f"a layer stores the whole schema, not a diff: {', '.join(whole)}")
    target = plan["target"]
    removed = [x for x in order if x.package != target]
    if env is not None and not stops:
        refs = references(env, schema, [x.package for x in removed], manager)
        lines += [f"  {r}" for r in refs]
        stops += [f"{len(refs)} references"] if refs else []
        if not refs:
            lines.append(f"  references: none to the {len(removed)} layers removed")
    if stops:
        return "\n".join(lines + [f"stopped: {'; '.join(stops)} - nothing written"]), 1

    root = Path(workspace)
    pkg = ctx.folders[target]
    source = next((x for x in order if x.package == target), order[-1])  # the UId rule
    package_uid = _descriptor(pkg / "descriptor.json").get("UId")
    if not package_uid:
        return "\n".join(lines + [f"stopped: {target}/descriptor.json has no UId - nothing written"]), 1
    folder = pkg / "Schemas" / schema
    renames = {}
    for x in order:
        if x is not source:
            renames[x.uid.lower()] = source.uid
        if x.package != target:
            renames[(_descriptor(ctx.folders[x.package] / "descriptor.json").get("UId") or "").lower()] = package_uid
    renames.pop("", None)
    writes, kind_stops = build(order, source, schema, folder, package_uid, renames, notes)
    lines += [f"  {n}" for n in notes]
    if kind_stops:
        return "\n".join(lines + [f"  conflict {s}" for s in kind_stops] + [f"stopped: {len(kind_stops)} conflicts - nothing written"]), 1
    res = _resources(order, schema, pkg / "Resources" / f"{schema}.{suffix}", suffix)
    if res is not None:
        writes.update(res.files())
    gains = plan["gains"]
    if gains:
        entries = {}
        for x in removed:
            for d in _descriptor(ctx.folders[x.package] / "descriptor.json").get("DependsOn") or []:
                entries.setdefault(d["Name"], d)
        desc = Descriptor(pkg / "descriptor.json")
        data = desc.data
        desc.set("DependsOn", (data.get("DependsOn") or []) + [entries[g] for g in gains])
        writes[pkg / "descriptor.json"] = (desc.text, read_text(pkg / "descriptor.json")[1])
    deletes = [p for x in removed for p in (x.folder, x.folder.parent.parent / "Resources" / f"{schema}.{suffix}") if p.exists()]

    def rel(p: Path) -> str:
        try:
            return p.relative_to(root).as_posix()
        except ValueError:
            return p.as_posix()
    lines += [f"write {rel(p)}" for p in writes] + [f"delete {rel(p)}" for p in deletes]
    if apply:
        for p in deletes:
            shutil.rmtree(p)
        for p, (text, b) in writes.items():
            write_text(p, text, b)
    lines.append(f"{'merged' if apply else 'would merge'} {schema} into {target}: {len(order)} layers -> 1"
                 + ("" if apply else " (dry run; --apply writes)"))
    return "\n".join(lines), 0


def merge_object(workspace: Path | str, schema: str, target: str | None = None, env=None, apply: bool = False,
                 only: set[str] | None = None) -> tuple[str, int]:
    """(text, exit code): the replacing layers of one object collapsed into one layer of the target package. Prints the plan,
    then the files it writes and deletes; writes them only with `apply`. Exit 1 (nothing written) on a conflict, siblings
    without `env`, a layer that stores a whole schema, or a site row that still points at a layer to remove."""
    return _merge(workspace, schema, target, env, apply, OBJECT, {"object"}, _object_files, "Entity", only=only)


# --------------------------------------------------------------------------- #
# The merge of a page (T05)
# --------------------------------------------------------------------------- #

CLIENT = "ClientUnitSchemaManager"
DIFF_SECTIONS = ("SCHEMA_VIEW_CONFIG_DIFF", "SCHEMA_VIEW_MODEL_CONFIG_DIFF", "SCHEMA_MODEL_CONFIG_DIFF")
CLASSIC_KEYED = ("attributes", "messages", "details", "mixins", "modules", "rules", "businessRules")


def _merge_deps(layers: list[tuple[str, list[str], list[str]]]) -> tuple[list[str], list[str], str]:
    """define()'s modules and the function's parameter names over the layers, bottom first: (modules, names, "") or
    ([], [], why) when a module would need a name the merged list cannot give it at its position."""
    deps, names = list(layers[0][1]), list(layers[0][2])
    for package, ds, ns in layers[1:]:
        for i, dep in enumerate(ds):
            name = ns[i] if i < len(ns) else None
            if dep in deps:
                have = names[deps.index(dep)] if deps.index(dep) < len(names) else None
                if name and have and name != have:
                    return [], [], f"module {dep} is `{have}` below and `{name}` in {package}"
                if name and not have:
                    return [], [], f"module {dep} has no parameter below and `{name}` in {package}"
                continue
            if name and name in names:
                return [], [], f"parameter `{name}` names two modules ({deps[names.index(name)]}, {dep} in {package})"
            if name and len(names) != len(deps):
                return [], [], f"module {dep} of {package} needs the parameter `{name}`, after a module without one"
            deps.append(dep)
            if name:
                names.append(name)
    return deps, names, ""


def _render_list(items: list[str], close_indent: str, nl: str, open_: str, close: str) -> str:
    if not items:
        return open_ + close
    return open_ + nl + ("," + nl).join(close_indent + "\t" + it.strip() for it in items) + nl + close_indent + close


def _closing_indent(raw: str, default: str = "\t\t") -> str:
    tail = raw.rstrip()
    line = tail[tail.rfind("\n") + 1:]
    return re.match(r"[ \t]*", line).group(0) if "\n" in tail else default


def absorb(ops: list[dict]) -> list[dict]:
    """The operations of several layers as one array the Shell folds the same way: a `merge`, `move` or `remove` of an element
    an earlier operation of the array inserted is folded into that `insert` (merge: its values deep-merged; move: its parent,
    property and index; remove: the insert and its own children's inserts dropped, or the properties removed). Verified on the
    test site: in one viewConfigDiff the Shell does not apply a merge to an element the same array inserts - the label of the
    earlier insert stayed - while the designer never writes such a pair."""
    from ..page.fold import _deep

    out: list[dict] = []
    for op in ops:
        name, kind = op.get("name"), op.get("operation")
        hit = next((o for o in out if o.get("operation") == "insert" and o.get("name") == name), None) if name else None
        if hit is None or kind not in ("merge", "move", "remove"):
            out.append(json.loads(json.dumps(op)))
            continue
        if kind == "merge":
            _deep(hit.setdefault("values", {}), op.get("values") or {})
        elif kind == "move":
            for key in ("parentName", "propertyName", "index"):
                if key in op:
                    hit[key] = op[key]
        elif op.get("properties"):
            for prop in op["properties"]:
                (hit.get("values") or {}).pop(prop, None)
        else:
            gone = {name}
            while True:
                more = {o.get("name") for o in out if o.get("operation") == "insert" and o.get("parentName") in gone} - gone
                if not more:
                    break
                gone |= more
            out = [o for o in out if o.get("name") not in gone]
    return out


def _freedom_files(order: list[Layer], source: Layer, schema: str, folder: Path, package_uid: str, renames: dict, notes: list):
    from ..page.fold import top_members
    from ..page.schema import PageSchema

    pages = [PageSchema(x.folder.parent.parent, schema) for x in order]
    stops = []
    if any(p.mobile for p in pages):
        stops.append("a mobile page: its body is not written back")
    objform = [x.package for x, p in zip(order, pages) if {"SCHEMA_VIEW_MODEL_CONFIG", "SCHEMA_MODEL_CONFIG"} & set(p.sections)]
    if objform:
        stops.append(f"viewModelConfig / modelConfig as objects, not diffs: {', '.join(objform)}")
    base = pages[0]
    for sec in DIFF_SECTIONS:
        ops = [op for p in pages for op in (p.sections[sec].value if sec in p.sections else [])]
        if sec == "SCHEMA_VIEW_CONFIG_DIFF":
            ops = absorb(ops)
        if sec in base.sections:
            base.sections[sec].value = ops
        elif ops:
            stops.append(f"{order[0].package} has no {sec} section to hold the upper layers' operations")
    raws = [p.raw_sections() for p in pages]
    layer_deps = []
    for x, r in zip(order, raws):
        args = r.get("SCHEMA_ARGS", "()").strip()
        layer_deps.append((x.package, json.loads(r.get("SCHEMA_DEPS", "[]")), [a.strip() for a in args[1:-1].split(",") if a.strip()]))
    deps, names, why = _merge_deps(layer_deps)
    if why:
        stops.append(why)
    if stops:
        return {}, stops
    text = base.render_body()
    nl = base.body_newline
    handlers = [src for p in pages for _, src in p.handlers()]
    keyed = {}
    for sec in ("SCHEMA_CONVERTERS", "SCHEMA_VALIDATORS"):
        members: dict[str, tuple[str, str]] = {}
        for x, r in zip(order, raws):
            for key, src in top_members(r.get(sec, "{}")):
                if key in members:
                    notes.append(f"{sec[7:-1].lower()} {key}: {x.package}'s kept, {members[key][0]}'s dropped")
                members[key] = (x.package, src)
        keyed[sec] = [src for _, src in members.values()]
    rendered = {"SCHEMA_DEPS": json.dumps(deps), "SCHEMA_ARGS": "(" + ", ".join(names) + ")",
                "SCHEMA_HANDLERS": _render_list(handlers, _closing_indent(raws[0].get("SCHEMA_HANDLERS", "")), nl, "[", "]")}
    for sec, items in keyed.items():
        rendered[sec] = _render_list(items, _closing_indent(raws[0].get(sec, "")), nl, "{", "}")
    for sec, value in rendered.items():
        marker = f"/**{sec}*/"
        if marker in text:
            text = re.sub(re.escape(marker) + r".*?" + re.escape(marker), lambda m, v=value, k=marker: k + v + k, text, count=1, flags=re.S)
    writes = {folder / f"{schema}.js": (text, base.body_bom)}
    writes.update(_page_common(order, source, schema, folder, package_uid, renames))
    return writes, []


def _page_common(order: list[Layer], source: Layer, schema: str, folder: Path, package_uid: str, renames: dict) -> dict:
    """metadata.json (the layers' diffs concatenated, the source's identity), descriptor of the source, properties of the
    top, the .less files of every layer one after another (the cascade keeps the layer order)."""
    writes = {}
    meta, bom = read_text(source.folder / "metadata.json")
    writes[folder / "metadata.json"] = (merged_diff(order, source, package_uid, renames, drops=None) + ("\r\n" if meta.endswith(("\n", "\r\n")) else ""), bom)
    for name, frm in (("descriptor.json", source), ("properties.json", order[-1])):
        if (frm.folder / name).is_file():
            writes[folder / name] = read_text(frm.folder / name)
    less = [read_text(x.folder / f"{schema}.less") for x in order if (x.folder / f"{schema}.less").is_file()]
    if less:
        writes[folder / f"{schema}.less"] = ("\r\n".join(t.rstrip() for t, _ in less) + "\r\n", less[0][1])
    return writes


def _classic_params(cs) -> tuple[int, int] | None:
    m = re.search(r"\bdefine\s*\(", cs.masked)
    fn = re.compile(r"\bfunction\b").search(cs.masked, m.end()) if m else None
    if not fn:
        return None
    a = cs.masked.find("(", fn.end())
    return (a + 1, cs.masked.find(")", a)) if a >= 0 else None


def _relative(src: str) -> str:
    """A member's source as the writer takes it: the lines after the first relative to the closing line's indent."""
    lines = src.replace("\r\n", "\n").split("\n")
    base = re.match(r"[ \t]*", lines[-1]).group(0) if len(lines) > 1 else ""
    return "\n".join([lines[0]] + [ln[len(base):] if ln.startswith(base) else ln.lstrip() for ln in lines[1:]])


def _classic_files(order: list[Layer], source: Layer, schema: str, folder: Path, package_uid: str, renames: dict, notes: list):
    from ..classicui.schema import ClassicSchema, _close
    from ..page.fold import fold_method

    pages = [ClassicSchema(x.folder.parent.parent, schema) for x in order]
    stops = []

    def params(p):
        span = _classic_params(p)
        return [a.strip() for a in p.body[span[0]:span[1]].split(",") if a.strip()] if span else []
    deps, names, why = _merge_deps([(x.package, list(p.dependencies), params(p)) for x, p in zip(order, pages)])
    if why:
        return {}, [why]
    cs = pages[0]
    for dep in deps:
        cs.add_dependency(dep)
    span = _classic_params(cs)
    if span and names != params(cs):
        cs._splice(span[0], span[1], ", ".join(names))
    owner = {m["name"]: order[0].package for m in cs.methods()}
    for x, up in zip(order[1:], pages[1:]):
        items = [op["source"] for op in up.diff_operations()]
        if items:
            a = cs._section("diff")
            close = _close(cs.masked, a) - 1
            inner = cs.body[a + 1:close]
            indent = cs._indent_at(close) + cs._unit
            nl = cs._nl
            if inner.strip():
                end = a + 1 + len(inner.rstrip())
                cs._splice(end, end, "".join("," + nl + indent + it for it in items))
            else:
                cs._splice(a + 1, close, nl + ("," + nl).join(indent + it for it in items) + nl + cs._indent_at(close))
        for sec in CLASSIC_KEYED:
            at = up.sections.get(sec)
            if not at or up.masked[at[0]] != "{":
                continue
            for key, ka, va, vb in up._members(at[0]):
                had = key in cs.entries(sec)
                cs._set_member(cs._section(sec), key, up.body[va:vb], quoted=up.body[ka] in "\"'")
                if had:
                    notes.append(f"{sec} {key}: {x.package}'s kept")
        for m in up.methods():
            name = m["name"]
            if name not in owner:
                cs.add_method(name, _relative(up.method(name)))
                owner[name] = x.package
                continue
            merged, why = fold_method(cs.method(name), up.method(name))
            if merged is None:
                stops.append(f"method {name} ({owner[name]} > {x.package}): {why}")
                continue
            cs.replace_method(name, _relative(merged))
            owner[name] += f" > {x.package}"
            notes.append(f"method {name}: folded {owner[name]}")
    if stops:
        return {}, stops
    writes = {folder / f"{schema}.js": (cs.body, cs.body_bom)}
    writes.update(_page_common(order, source, schema, folder, package_uid, renames))
    return writes, []


def _page_stops(conflict: str, env) -> bool:
    """Which plan conflicts stop a page merge: an element changed in two layers only without the site's order; a method in two
    layers and its callParent lines never (the fold decides, and says why it cannot); anything else always."""
    if conflict.startswith("conflict element "):
        return env is None
    return not conflict.startswith(("conflict method ", "conflict callParent "))


def merge_page(workspace: Path | str, schema: str, target: str | None = None, env=None, apply: bool = False,
               only: set[str] | None = None) -> tuple[str, int]:
    """(text, exit code): the replacing layers of one page (Freedom or Classic) as one layer of the target package, the same run
    as merge_object. Freedom: the three diff arrays concatenated in fold order, the handlers one after another, converters and
    validators by key (the upper wins). Classic: the diff arrays concatenated, the keyed sections by key, a method in two layers
    folded pairwise bottom up (the upper body with the lower body in place of its callParent)."""
    from ..page.fold import is_freedom

    order = [x for x in layers_in_order(workspace, schema, env, CLIENT) if x.replacing and x.folder is not None and (not only or x.package in only)]
    classic = bool(order) and not is_freedom(order[0].folder, schema)
    return _merge(workspace, schema, target, env, apply, CLIENT, {"page", "classic"}, _classic_files if classic else _freedom_files,
                  "ClientUnit", stop_filter=lambda c: _page_stops(c, env), only=only)


def merge_schema(workspace: Path | str, schema: str, target: str | None = None, env=None, apply: bool = False,
                 only: set[str] | None = None) -> tuple[str, int]:
    """merge_object or merge_page, by the manager of the schema's copies in the workspace."""
    ctx = _context(workspace)
    managers = {m for (name, m), n in ctx.keys.items() if name.lower() == schema.lower() and n}
    if CLIENT in managers and OBJECT not in managers:
        return merge_page(workspace, schema, target, env, apply, only)
    return merge_object(workspace, schema, target, env, apply, only)
