"""A page over its layers (S24-T05): the fold of each layer's diff operations, the snapshot lines, the fold of a Classic method.

    fold(ops)                     name -> element after insert / merge / remove / move, applied in order
    disk_lines(workspace, page)   the snapshot lines of a page on disk (Freedom or Classic), over `layers_in_order`
    page_file_lines(path)         the site lines from the page file the UI test utility's `analyse` writes
    fold_method(lower, upper)     a Classic method overridden in two layers as one: the upper body with its
                                  `this.callParent(arguments)` statement replaced by the lower body

The fold is what the Shell (Freedom `viewConfigDiff`) and the SchemaBuilder (Classic `diff`) do with the layers of a page:
the operations of every layer, base first, applied one after another. A `merge` deep-merges its values; a `remove` with
`properties` drops those values, without them the element and every element under it; a `move` changes the parent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..text import mask

CLIENT = "ClientUnitSchemaManager"
LAYER_LINES = ("layers:", "siblings", "copy ", "layer ")  # what a merge changes by design; compare --ignore-layers drops them


def _deep(into: dict, values: dict) -> None:
    for k, v in values.items():
        if isinstance(v, dict) and isinstance(into.get(k), dict):
            _deep(into[k], v)
        else:
            into[k] = json.loads(json.dumps(v))


def fold(ops: list[dict]) -> dict[str, dict]:
    """name -> {"parent", "property", "index", "values", "base"} (`base`: first met in a merge, so it lives below the layers),
    or {"removed": True} for an element a layer removed."""
    out: dict[str, dict] = {}
    for op in ops:
        name, kind = op.get("name"), op.get("operation")
        if not name:
            continue
        values = op.get("values") if isinstance(op.get("values"), dict) else {}
        if kind == "insert":
            out[name] = {"parent": op.get("parentName"), "property": op.get("propertyName"), "index": op.get("index"),
                         "values": json.loads(json.dumps(values)), "base": False}
            continue
        el = out.get(name)
        if el is None or el.get("removed"):
            el = out[name] = {"parent": None, "property": None, "index": None, "values": {}, "base": True}
        if kind == "merge":
            _deep(el["values"], values)
        elif kind == "move":
            el["parent"] = op.get("parentName", el["parent"])
            el["property"] = op.get("propertyName", el["property"])
            el["index"] = op.get("index", el["index"])
        elif kind == "remove":
            props = op.get("properties")
            if props:
                for p in props:
                    el["values"].pop(p, None)
                continue
            gone = {name}
            while True:  # the children follow their parent
                more = {n for n, e in out.items() if not e.get("removed") and e.get("parent") in gone} - gone
                if not more:
                    break
                gone |= more
            for n in gone:
                out[n] = {"removed": True}
    return out


def _text(value) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def element_lines(folded: dict[str, dict], type_key: str, keys_only: bool = False) -> list[str]:
    """`element <name> <type> [parent <p>] [caption <c>]` (Freedom: the caption or the label), or with `keys_only` (Classic,
    whose values are JavaScript) `element <name> [parent <p>] values <key>, <key>`; `removed <name>`."""
    out = []
    for name, el in folded.items():
        if el.get("removed"):
            out.append(f"removed {name}")
            continue
        v = el["values"]
        if keys_only:
            line = f"element {name}" + (f" parent {el['parent']}" if el["parent"] else "") + (f" values {', '.join(sorted(v))}" if v else "")
            out.append(line)
            continue
        line = f"element {name} {_text(v.get(type_key)) or '?'}"
        if el["parent"]:
            line += f" parent {el['parent']}"
        caption = v.get("caption", v.get("label"))
        if caption is not None:
            line += f" caption {_text(caption)}"
        out.append(line)
    return out


_KEY_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'|([\w$.]+)')


def top_members(text: str) -> list[tuple[str, str]]:
    """(key, `key: value` source) of each member of a JavaScript object literal's first level."""
    masked = mask(text)
    start = masked.find("{")
    out, depth, i, cur = [], 0, start + 1, None
    while 0 <= start < i < len(masked):
        ch = masked[i]
        if depth == 0 and cur is None and not ch.isspace() and ch not in ",}":
            m = _KEY_RE.match(text, i)
            if m:
                cur = (next(g for g in m.groups() if g is not None), i)
                i = m.end()
                continue
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0 and cur:
            out.append((cur[0], text[cur[1]:i].rstrip()))
            cur = None
        i += 1
    if cur:
        out.append((cur[0], text[cur[1]:i].rstrip()))
    return out


def top_keys(text: str) -> list[str]:
    """The keys of a JavaScript object literal's first level (`{ "a": function() {...}, b: {...} }` -> a, b)."""
    return [k for k, _ in top_members(text)]


def _freedom_lines(pages) -> list[str]:
    ops = [op for page, _ in pages for op in page.view_config_diff]
    lines = element_lines(fold(ops), "type")
    i = 0
    for page, package in pages:
        for request, _ in page.handlers():
            i += 1
            lines.append(f"handler {request} #{i}")
            lines.append(f"layer handler {request} {package}")
    raw = [(page.raw_sections(), package) for page, package in pages]
    for sec, word in (("SCHEMA_CONVERTERS", "converter"), ("SCHEMA_VALIDATORS", "validator")):
        keys = {}
        for r, package in raw:
            for k in top_keys(r.get(sec, "{}")):
                keys.setdefault(k, []).append(package)
        lines += [f"{word} {k}" for k in keys]
    return lines


def _classic_lines(pages) -> list[str]:
    ops = [{"operation": op["operation"], "name": op["name"], "parentName": op["parentName"], "propertyName": op["propertyName"],
            "index": op["index"], "values": {k: True for k in op["values"]}} for page, _ in pages for op in page.diff_operations()]
    lines = element_lines(fold(ops), "itemType", keys_only=True)
    methods: dict[str, list[str]] = {}
    for page, package in pages:
        for m in page.methods():
            methods.setdefault(m["name"], []).append(package)
    lines += [f"method {name}" for name in methods] + [f"layer method {name} {' > '.join(ps)}" for name, ps in methods.items()]
    for sec, word in (("attributes", "attribute"), ("messages", "message"), ("details", "detail"), ("mixins", "mixin"), ("modules", "module")):
        keys = []
        for page, _ in pages:
            keys += [k for k in page.entries(sec) if k not in keys]
        lines += [f"{word} {k}" for k in keys]
    return lines


def is_freedom(folder: Path, page: str) -> bool:
    """A Freedom UI body has the view config marker; a Classic one is an AMD module without it (`ClassicSchema.is_classic`
    alone says yes to both)."""
    body = Path(folder) / f"{page}.js"
    return body.is_file() and "/**SCHEMA_VIEW_CONFIG_DIFF*/" in body.read_text(encoding="utf-8-sig", errors="replace")


def disk_lines(workspace, page: str, env=None) -> list[str]:
    """`layers: a > b`, then the folded elements and the handler / converter / validator lines (Freedom) or the method /
    attribute / message / detail / mixin / module lines (Classic) of the page over its copies in the workspace."""
    from ..classicui.schema import ClassicSchema
    from ..describe.merge import layers_in_order
    from .schema import PageSchema

    layers = [x for x in layers_in_order(workspace, page, env, CLIENT) if x.folder is not None]
    if not layers:
        raise KeyError(f"no page {page} in the workspace {workspace}")
    classic = not is_freedom(layers[0].folder, page)
    cls = ClassicSchema if classic else PageSchema
    pages = [(cls(x.folder.parent.parent, page), x.package) for x in layers]
    lines = ["layers: " + " > ".join(x.package for x in layers)]
    if any(x.siblings for x in layers):
        lines.append("siblings ordered by name: " + ", ".join(x.package for x in layers if x.siblings))
    return lines + (_classic_lines(pages) if classic else _freedom_lines(pages))


def page_file_lines(path: Path | str) -> list[str]:
    """`page <code> <type> <label> [columns a, b] [tabs x, y]` per element of a page file (`analyse` writes them)."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    out = []
    for e in data.get("elements", []):
        line = f"page {e.get('code')} {e.get('type')} {e.get('label', '')}".rstrip()
        for key in ("columns", "tabs"):
            if e.get(key):
                line += f" {key} " + ", ".join(c if isinstance(c, str) else _text(c) for c in e[key])
        out.append(line)
    return out


# --------------------------------------------------------------------------- #
# A Classic method in two layers
# --------------------------------------------------------------------------- #

_HEAD_RE = re.compile(r"\s*([\w$]+|\"[^\"]*\"|'[^']*')\s*:\s*function\s*\(([^)]*)\)\s*\{")
_CALL_RE = re.compile(r"(return\s+)?[\w$]+\s*\.\s*callParent\s*\(\s*arguments\s*\)\s*;?")
_DECL_RE = re.compile(r"\b(?:let|const)\s+([\w$]+)")


def _fn_depth(masked: str, start: int) -> list[int]:
    """For each offset from `start`, how many nested function bodies enclose it (0 = the method's own body)."""
    depth, stack, pending, out = 0, [], False, []
    for i in range(start, len(masked)):
        if masked.startswith("function", i) and not (masked[i - 1].isalnum() or masked[i - 1] in "_$") or masked.startswith("=>", i):
            pending = True
        ch = masked[i]
        if ch == "{":
            stack.append(pending)
            depth += pending
            pending = False
        elif ch == "}" and stack:
            depth -= stack.pop()
        elif ch == ";":
            pending = False
        out.append(depth)
    return out


def _parts(src: str):
    """(params, body inner text, masked inner, offset of the inner in src) of `name: function(params) { inner }`."""
    m = _HEAD_RE.match(mask(src)) and _HEAD_RE.match(src)
    if not m:
        return None
    end = src.rstrip().rfind("}")
    return [p.strip() for p in m.group(2).split(",") if p.strip()], src[m.end():end], mask(src)[m.end():end], m.end()


def fold_method(lower: str, upper: str) -> tuple[str | None, str]:
    """(the upper method with the lower body in place of its `this.callParent(arguments)`, "") or (None, why it cannot fold).
    Folds only what keeps the behaviour: the same parameters, one callParent in the upper method, not in a callback and its
    value not assigned, and an early `return` of the lower body only when the upper calls the parent last."""
    lo, up = _parts(lower), _parts(upper)
    if not lo or not up:
        return None, "not a `name: function(...) {...}` member"
    if lo[0] != up[0]:
        return None, f"parameters differ ({', '.join(lo[0])} / {', '.join(up[0])})"
    calls = [m for m in re.finditer(r"callParent\s*\(", up[2])]
    if len(calls) != 1:
        return None, f"{'no' if not calls else 'two or more'} callParent calls in the upper method"
    depth = _fn_depth(up[2], 0)
    if depth[calls[0].start()]:
        return None, "callParent inside a callback"
    stmt = next((m for m in _CALL_RE.finditer(up[1]) if m.start() <= calls[0].start() < m.end()), None)
    if not stmt or re.search(r"[=(,]\s*$", up[2][:stmt.start()]):
        return None, "callParent's value is used, or it is called with other arguments than `arguments`"
    after = up[2][stmt.end():].strip()
    lo_depth = _fn_depth(lo[2], 0)
    early = [m for m in re.finditer(r"\breturn\b", lo[2]) if not lo_depth[m.start()]]
    if early and after:
        return None, "the lower body may return early, and the upper one has code after callParent"
    clash = set(_DECL_RE.findall(lo[2])) & set(_DECL_RE.findall(up[2]))
    if clash:
        return None, f"both bodies declare {', '.join(sorted(clash))} with let / const"
    body = lo[1].strip("\r\n").rstrip()
    lines = body.replace("\r\n", "\n").split("\n")
    lo_indent = min((len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()), default=0)
    line_start = up[1].rfind("\n", 0, stmt.start()) + 1
    indent = re.match(r"[ \t]*", up[1][line_start:]).group(0)
    nl = "\r\n" if "\r\n" in upper else "\n"
    inlined = nl.join((indent + ln[lo_indent:]) if ln.strip() else "" for ln in lines).lstrip()
    if stmt.group(1) and not early:  # `return this.callParent(arguments)` above a body that returns nothing of its own
        inlined = re.sub(r"(?<!return )(?<!return\t)([\w$]+\s*\.\s*callParent\s*\(\s*arguments\s*\))", r"return \1", inlined, count=1)
    new_inner = up[1][:stmt.start()] + inlined + up[1][stmt.end():]
    return upper[:up[3]] + new_inner + upper[up[3] + len(up[1]):], ""
