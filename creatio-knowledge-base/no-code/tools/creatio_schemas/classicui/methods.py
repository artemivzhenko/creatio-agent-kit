"""A Classic page's method in every layer, its callers, its outline (S33-T07).

    layers_of(c, method, env)   the method's body in each copy of the schema, in the order the platform applies them (the
                                workspace's copies by DependsOn, `describe/merge.layers_in_order`; with `env` the site's copies,
                                each body read from `SysSchemaContent`, a copy only on the site marked `(site only)`)
    callers(c, method)          `this.<m>(` / `<module>.<m>(` in every client schema body of the workspace, file and line
    outline(c)                  methods, attributes and messages with their line numbers
"""

from __future__ import annotations

import re
from pathlib import Path

from ..text import mask

_CALL_PARENT = re.compile(r"\bcallParent\s*\(")


def view(body: str, name: str):
    """The Classic reader over a text that is not a package file (a site layer's body)."""
    from .schema import ClassicSchema

    v = ClassicSchema.__new__(ClassicSchema)
    v.body, v.masked, v.name = body, mask(body), name
    v.module_name, v.dependencies, v.sections, v._return_at, v._deps_at = None, [], {}, None, None
    v._parse()
    return v


def _method(c, method: str) -> tuple[int, str] | None:
    for k, a, b in c._method_spans():
        if k == method:
            return c._line(a), c.body[a:b]
    return None


def layers_of(c, method: str, env=None, env_name: str = "") -> list[dict]:
    """[{package, where: workspace|site|site only, line, body}] first to last; `body` None when that layer does not define it."""
    from ..describe.layers import layers_sql
    from ..describe.merge import layers_in_order
    from .schema import ClassicSchema

    workspace = Path(c.package).parent
    if env is None:
        layers = layers_in_order(workspace, c.name, manager="ClientUnitSchemaManager")
        bodies = {}
    else:
        layers = layers_in_order(workspace, c.name, env, manager="ClientUnitSchemaManager")
        bodies = {r["package"]: r.get("body") or "" for r in env.sql(layers_sql(c.name))}
    out = []
    for layer in layers:
        if env is not None and layer.source == "site":  # the site's body is what runs, in the workspace or not
            schema, where = view(bodies.get(layer.package, ""), c.name), "site" if layer.folder is not None else "site only"
        else:
            schema = ClassicSchema(layer.folder.parent.parent, c.name)
            where = "workspace" if env is None else "not on the site"
        hit = _method(schema, method)
        out.append({"package": layer.package, "where": where, "line": hit[0] if hit else None, "body": hit[1] if hit else None})
    return out


def method_lines(c, method: str, env=None, env_name: str = "") -> str | None:
    """The `method <name>` answer over the layers; None when the workspace holds one copy and no env is asked (today's answer)."""
    layers = layers_of(c, method, env, env_name)
    if env is None and len(layers) <= 1:
        return None
    having = [x for x in layers if x["body"] is not None]
    if not having:
        raise KeyError(f"no method {method} in any layer of {c.name} ({', '.join(x['package'] for x in layers)})")
    where = f" on {env_name}" if env is not None else ""
    lines = [f"{c.name}.{method}{where}: {len(having)} of {len(layers)} layers define it, applied first to last (the last one runs first)"]
    for x in layers:
        tag = f"  ({x['where']})" if x["where"] != "workspace" else ""
        if x["body"] is None:
            lines.append(f"  {x['package']}{tag}: -")
            continue
        parent = "callParent" if _CALL_PARENT.search(mask(x["body"])) else "no callParent: the layers below do not run"
        lines.append(f"  {x['package']}{tag}: line {x['line']}, {x['body'].count(chr(10)) + 1} lines, {parent}")
    for x in having:
        lines += ["", f"--- {x['package']} line {x['line']} ---", x["body"]]
    return "\n".join(lines)


def callers(c, method: str) -> list[str]:
    """`<package>/<Schema>.js:<line>  <text>` of every call of `method` in the workspace's client schema bodies."""
    call = re.compile(rf"(?:\bthis|\b[A-Za-z_$][\w$]*)\s*\.\s*{re.escape(method)}\s*\(")
    out = []
    for s in sorted(c.workspace.schemas, key=lambda s: (s["dir"].parent.parent.name, s["name"])):
        body = s["dir"] / f"{s['name']}.js"
        if s["manager"] != "ClientUnitSchemaManager" or not body.is_file():
            continue
        from ..files import read_text

        text = read_text(body)[0]
        if method not in text:
            continue
        masked = mask(text)
        for m in call.finditer(masked):
            line = masked.count("\n", 0, m.start()) + 1
            out.append(f"{s['dir'].parent.parent.name}/{s['name']}.js:{line}  {text.splitlines()[line - 1].strip()}")
    return out


def outline(c) -> list[str]:
    """`methods` / `attributes` / `messages` with the line each member starts on."""
    out = []
    for section in ("attributes", "messages", "methods"):
        span = c.sections.get(section)
        if not span or c.masked[span[0]] != "{":
            continue
        members = c._members(span[0])
        out.append(f"{section} ({len(members)}), line {c._line(span[0])}:")
        out += [f"  {k:<40} line {c._line(ka)}" for k, ka, _, _ in members]
    return out
