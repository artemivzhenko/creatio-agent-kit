"""`merge-package` (S27-T03): one child package folded into its parent.

    merge_package(workspace, child, parent, env=None, apply=False) -> (text, exit code)

A schema the child replaces and the parent replaces too is a layer merge through the S24 engines (`merge_schema` with
`only={child, parent}`), in the story's order: objects, then pages (rule layers stop: their merge is not built, S24-T07).
Everything else the child holds is moved as it is, the UId kept: its own schemas (objects, pages, processes, DCM, user tasks,
source code), a replacing layer the parent does not have, SQL scripts, data bindings, `Files/cs`. Every other package of the
workspace that depends on the child is redirected to the parent; the parent gains what the child depended on and it does not
reach. The child keeps its descriptor.json and nothing else.

Verified on the test site (S27-T03): installing the parent with a schema the child holds moves that SysSchema row to the parent -
the same `Id` and UId, the table and its rows untouched - and the child installed without it afterwards leaves it there. Pushing
the child first would delete the schema (S24-T01), so the parent goes first. `push-pkg` does not change an installed package's
dependencies (S24-T05): the `depends` lines are written into the descriptors, the site needs them applied on its own.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..files import read_text, write_text
from .merge import CLIENT, OBJECT, _context, _descriptor, merge_schema

ORDER = {"object": 0, "page": 1, "classic": 1}  # the story's order of layer merges; rules are a stop for now
STOP_RE = re.compile(r"^stopped: (.*) - nothing written$", re.M)


def _kind(package: Path, name: str) -> str:
    from .core import kind_of, open_item
    try:
        return kind_of(open_item(package, name))
    except Exception:  # an unreadable schema still moves; its kind is only a label here
        return "schema"


def _schemas(package: Path) -> dict[str, dict]:
    out = {}
    for path in sorted((package / "Schemas").glob("*/descriptor.json")):
        try:
            d = _descriptor(path)
        except (OSError, ValueError, KeyError):
            d = {}
        out[path.parent.name] = d
    return out


def _row(word: str, kind: str, name: str, rest: str) -> str:
    return f"{word:<8}{kind:<8}{name:<28} {rest}".rstrip()


def _entry(desc: dict) -> dict:
    """A DependsOn entry naming a package, from its own descriptor."""
    e = {"UId": desc.get("UId", ""), "PackageVersion": desc.get("PackageVersion", ""), "Name": desc.get("Name", "")}
    if desc.get("Type") is not None:
        e["Type"] = desc["Type"]
    return e


def merge_package(workspace: Path | str, child: str, parent: str, env=None, apply: bool = False) -> tuple[str, int]:
    from ..schema import Descriptor
    from .layers import schema_layers

    ctx = _context(workspace)
    if child not in ctx.folders or parent not in ctx.folders:
        missing = [p for p in (child, parent) if p not in ctx.folders]
        return f"no package {', '.join(missing)} in the workspace", 2
    cpkg, ppkg = ctx.folders[child], ctx.folders[parent]
    if parent not in ctx.reach.get(child, set()):
        return f"stop    {child} does not depend on {parent}: it is not its parent", 1
    cdesc, pdesc = _descriptor(cpkg / "descriptor.json"), _descriptor(ppkg / "descriptor.json")
    mine, theirs = _schemas(cpkg), _schemas(ppkg)
    lines, stops, notes, layers, moves = [], [], [], [], []

    for name, d in mine.items():
        kind, manager = _kind(cpkg, name), d.get("ManagerName", "")
        other = theirs.get(name)
        same_manager = other is not None and other.get("ManagerName", "") == manager
        if d.get("ExtendParent") and same_manager and other.get("ExtendParent"):
            if kind not in ORDER:
                stops.append(_row("stop", kind, name, f"a {kind} layer in both: its merge is not built (S24-T07 / T06)"))
                continue
            layers.append((ORDER[kind], kind, name))
            continue
        if other is not None and (same_manager or other.get("UId", "").lower() != d.get("UId", "").lower()):
            stops.append(_row("stop", kind, name, f"the parent has its own {name} (name clash, "
                                                  f"{'different UId' if other.get('UId', '').lower() != d.get('UId', '').lower() else 'the same UId'})"))
            continue
        moves.append((kind, name, d))
        uid = d.get("UId", "").lower()
        if not d.get("ExtendParent"):
            third = sorted(p for p, folder in ctx.folders.items() if p not in (child, parent) and any(
                (x.get("Parent") or {}).get("UId", "").lower() == uid and x.get("ExtendParent") for x in _schemas(folder).values()))
            if third:
                notes.append(_row("note", kind, name, f"replaced by {', '.join(third)}: its ParentUId keeps pointing at the moved schema "
                                                      "(the UId does not change)"))
        if env is not None:
            custom = schema_layers(env, name)["custom"]
            if custom:
                stops.append(_row("stop", kind, name, f"a Custom layer on the site ({', '.join(custom)}) for a moved schema"))
            if kind == "process":
                runs = env.sql(f'select count(*)::text "n" from "SysProcessLog" where "SysSchemaId" in '
                               f'(select "Id" from "SysSchema" where "UId" = \'{uid}\')')
                n = int((runs or [{"n": "0"}])[0].get("n") or 0)
                if n:
                    notes.append(_row("note", kind, name, f"{n} runs logged: the schema row keeps its Id when the parent is pushed "
                                                          "first, so they stay valid"))

    def items(folder: str, word: str):
        base = cpkg / folder
        for path in sorted(base.iterdir()) if base.is_dir() else []:
            if (ppkg / folder / path.name).exists():
                stops.append(_row("stop", word, path.name, f"the parent has {folder}/{path.name} too"))
            else:
                yield path
    scripts = list(items("SqlScripts", "sql"))
    data = list(items("Data", "data"))
    cs_dir = cpkg / "Files" / "cs"
    cs = sorted(p for p in cs_dir.rglob("*") if p.is_file()) if cs_dir.is_dir() else []
    if cs and pdesc.get("Type") != 1:
        stops.append(_row("stop", "source", "Files/cs", f"{len(cs)} files, and {parent} is not an assembly package"))
    clashes = [p for p in cs if (ppkg / "Files" / "cs" / p.relative_to(cs_dir)).exists()]
    stops += [_row("stop", "source", f"Files/cs/{p.relative_to(cs_dir).as_posix()}", "the parent has it too") for p in clashes]
    for proj in (cpkg / "Files").glob("*.csproj") if cs else []:
        if re.search(r'<Compile\s+Include="[^"*]*cs[\\/][^"*]+\.cs"', read_text(proj)[0]):
            stops.append(_row("stop", "source", proj.name, "lists Files/cs files one by one: move them by hand"))

    # the layer merges, as a dry run first: a stop of any of them stops the whole package
    layer_text = {}
    for _, kind, name in sorted(layers):
        text, code = merge_schema(workspace, name, parent, env, False, {child, parent})
        layer_text[name] = text
        n = text.splitlines()[0] if text else ""
        m = re.search(r": (\d+) layers?", n)
        lines.append(_row("layer", kind, name, f"-> {parent}   ({m.group(1) if m else '2'} layers: {child}, {parent})   merge"))
        if code:
            why = STOP_RE.search(text)
            stops.append(_row("stop", kind, name, why.group(1) if why else text.splitlines()[-1]))
    for kind, name, d in moves:
        lines.append(_row("move", kind, name, f"-> {parent}   uid kept"))
    lines += [_row("move", "sql", p.name, f"-> {parent}") for p in scripts]
    lines += [_row("move", "data", f"Data/{p.name}", f"-> {parent}") for p in data]
    if cs:
        lines.append(_row("move", "source", "Files/cs", f"-> {parent}   {len(cs)} files"))

    depends = []
    for p, folder in sorted(ctx.folders.items()):
        if p in (child, parent):
            continue
        names = [x["Name"] for x in _descriptor(folder / "descriptor.json").get("DependsOn") or []]
        if child in names:
            depends.append(p)
            lines.append(f"depends {p}: DependsOn {child} -> {parent}")
    gains = [e for e in cdesc.get("DependsOn") or []
             if e["Name"] != parent and e["Name"] not in ctx.reach.get(parent, set()) and parent not in ctx.reach.get(e["Name"], set())]
    if gains:
        lines.append(f"depends {parent}: gains {', '.join(e['Name'] for e in gains)}")
    if depends or gains:
        notes.append("note    dependencies: push-pkg keeps an installed package's own (S24-T05) - apply the depends lines on the site too")
    lines += notes
    if stops:
        return "\n".join(lines + stops + [f"stopped: {len(stops)} stops - nothing written"]), 1
    if not apply:
        return "\n".join(lines + [f"would merge {child} into {parent} (dry run; --apply writes)"]), 0

    # --apply: the layers in the fixed order, then the moves, the descriptors, the child emptied
    written = []
    for _, kind, name in sorted(layers):
        text, code = merge_schema(workspace, name, parent, env, True, {child, parent})
        if code:
            return "\n".join(lines + [f"stopped at the layer {name}: {text.splitlines()[-1]}"] + [f"written before: {w}" for w in written]), 1
        written.append(f"layer {name}")
    for kind, name, d in moves:
        shutil.move(str(cpkg / "Schemas" / name), str(ppkg / "Schemas" / name))
        for res in sorted((cpkg / "Resources").glob(f"{name}.*")) if (cpkg / "Resources").is_dir() else []:
            (ppkg / "Resources").mkdir(parents=True, exist_ok=True)
            shutil.move(str(res), str(ppkg / "Resources" / res.name))
    for folder, paths in (("SqlScripts", scripts), ("Data", data)):
        for p in paths:
            (ppkg / folder).mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(ppkg / folder / p.name))
    for p in cs:
        dst = ppkg / "Files" / "cs" / p.relative_to(cs_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dst))
    pe = _entry(pdesc)
    for p in depends:
        path = ctx.folders[p] / "descriptor.json"
        desc = Descriptor(path)
        new, seen = [], False
        for x in desc.data.get("DependsOn") or []:
            x = pe if x["Name"] == child else x
            if x["Name"] == parent:
                if seen:  # it named both the child and the parent: one entry stays
                    continue
                seen = True
            new.append(x)
        desc.set("DependsOn", new)
        write_text(path, desc.text, read_text(path)[1])
    if gains:
        path = ppkg / "descriptor.json"
        desc = Descriptor(path)
        have = desc.data.get("DependsOn") or []
        names = {x["Name"] for x in have}  # a layer merge may have added some already
        desc.set("DependsOn", have + [e for e in gains if e["Name"] not in names])
        write_text(path, desc.text, read_text(path)[1])
    for entry in sorted(cpkg.iterdir()):
        if entry.name == "descriptor.json":
            continue
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    lines.append(f"merged {child} into {parent}: push {parent} first, then the packages that depended on {child}")
    lines.append(f"{child}: empty - remove the application on the site, then delete the folder")
    return "\n".join(lines), 0
