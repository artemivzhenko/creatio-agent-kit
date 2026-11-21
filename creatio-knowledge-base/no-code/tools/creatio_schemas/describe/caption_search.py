"""`resolve` (S31-T04): the workspace by what the users call things - a caption (or a `Usr` name) in, the schemas, columns, page elements,
process parameters and lookup values that carry it out, ranked.

Answered from the store's `captions` (S26-T02; the primary culture). `culture=<c>` or `all` re-reads the items in another culture
(their resource XML is read once per call); lookup values are searched in the primary culture only (a binding's index keeps its first
40 values).
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from .core import DEFAULT_LIMIT, QueryError, cut, open_item
from .index import Indexed, PackageIndex, captions_of
from .store import CAPTION_KINDS as SCHEMA_KINDS

# the order of the story: object > column > page element > process parameter > lookup value > section; a page or another schema's own
# caption stands next to the object, a rule's caption next to the elements
RANK = {"object": 0, "page": 1, "process": 1, "dcm": 1, "user-task": 1, "rules": 1, "classic": 1, "column": 2, "element": 3, "rule": 3,
        "parameter": 4, "lookup": 5, "section": 6}
KINDS = ("object", "page", "column", "element", "parameter", "lookup", "section", "process", "rule")


def _score(text: str | None, needle: str) -> int | None:
    """0 = the whole text, 1 = a whole word (or run of words), 2 = a part of a word; None = no hit."""
    if not text:
        return None
    low = text.casefold()
    if low == needle:
        return 0
    if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", low):
        return 1
    return 2 if needle in low else None


def _from_xml(idx: PackageIndex, culture: str):
    """The same for another culture, read from each item's resources."""
    pkg = idx.data.get("package", idx.package.name)
    for name, e in idx.schemas.items():
        kind = e.get("kind")
        if "error" in e or kind not in ("object", "page", "process", "user-task", "rules"):
            continue
        try:
            item = open_item(idx.package, name)
            res = getattr(item, "resources", None)
            if res is None or culture not in res.cultures:
                continue
            if kind in SCHEMA_KINDS:
                yield kind, name, res.get("Caption", culture), name, pkg, ""
            fields = captions_of(kind, item, culture)
        except Exception:  # one unreadable item costs its own hits
            continue
        for col, cap in (fields.get("columns") or {}).items():
            yield "column", f"{name}.{col}", cap, col, pkg, ""
        for el in fields.get("elements") or []:
            if isinstance(el, dict):
                yield "element", f"{name}.{el['name']}", el.get("caption"), el["name"], pkg, ""
        for key, label in (("elements", "element"), ("parameters", "parameter"), ("rules", "rule")):
            if isinstance(fields.get(key), dict):
                for n, cap in fields[key].items():
                    yield label, f"{name}.{n}", cap, n, pkg, ""


def resolve_caption(path: Path | str, text: str, kind: str = "", culture: str = "", limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    needle = (text or "").strip().casefold()
    if not needle:
        raise QueryError("give the text to look for")
    if kind and kind not in KINDS:
        raise QueryError(f"unknown kind {kind}; kinds: {', '.join(KINDS)}")
    ws = Indexed(path)
    primary_rows: dict[str, list] = {}
    for folder, node, k, key, caption, schema in ws.rows(
            "select c.package, c.node, c.kind, c.key, c.text, json_extract(n.entry, '$.schema') from captions c join nodes n "
            "on n.package = c.package and n.name = c.node where c.{pkgs} and (instr(fold(c.text), :needle) "
            "or instr(fold(case c.key when '' then c.node else c.key end), :needle)) order by c.rowid", needle=needle):
        pkg = ws.name[folder]
        if k == "lookup":
            row = ("lookup", schema or node.removeprefix("Data/"), caption or None, key, pkg, f"= {key}  {node}")
        elif key:
            row = (k, f"{node}.{key}", caption or None, key, pkg, "")
        else:
            row = (k, node, caption or None, node, pkg, "")
        primary_rows.setdefault(folder, []).append(row)
    hits, seen, pool = [], set(), []
    for idx in ws.indexes:
        primary = idx.data.get("culture", "en-US")
        rows = [(c, primary, True) for c in primary_rows.get(idx.package.name, [])]
        extra = [c for c in idx.data.get("cultures", {}) if c != primary] if culture == "all" else [culture] if culture and culture != primary else []
        for other in extra:
            rows += [(c, other, False) for c in _from_xml(idx, other)]
        if culture and culture != "all" and culture != primary:
            rows = [r for r in rows if not r[2]]  # only that culture; lookup values (primary culture only) drop out with it
        pool += rows
    for (k, ref, caption, name, pkg, tail), lang, is_primary in pool:
        label = {"classic": "page"}.get(k, k)
        if kind and kind != label and not (kind == "process" and label in ("dcm", "user-task")):
            continue
        best = min((s for s in (_score(caption, needle), _score(name, needle)) if s is not None), default=None)
        if best is None:
            continue
        shown = (f" ({lang})" if not is_primary else "") if caption else ""
        line = f"{label:<9} {ref}" + (f" {caption!r}{shown}" if caption else "") + (f" {tail}" if tail else "") + f"  {pkg}"
        if line not in seen:
            seen.add(line)
            hits.append((best, RANK.get(k, 6), ref, line))
    for env, k, name, caption, pkg in ws.query("select env, kind, name, caption, package from site_schemas"):  # S31-T11: the last --env pass
        label = {"client": "page"}.get(k, k)
        best = min((s for s in (_score(caption, needle), _score(name, needle)) if s is not None), default=None)
        if best is not None and (not kind or kind == label):
            hits.append((best, RANK.get(k, 6), name, f"{label:<9} {name}" + (f" {caption!r}" if caption else "") + f"  site {env}: {pkg} (not in workspace)"))
    if not hits:
        pool_texts = {c for (_, _, c, _, _, _), _, is_primary in pool if c and not is_primary}  # every caption, not only the hits
        primary = [f for f, idx in zip(ws.rank, ws.indexes) if not culture or culture == "all" or culture == idx.data.get("culture", "en-US")]
        pool_texts |= {t for f, t in ws.rows("select distinct package, text from captions where {pkgs} and text != ''") if f in primary}
        pool_texts = sorted(pool_texts)
        close = difflib.get_close_matches(text.strip(), pool_texts, n=3, cutoff=0.5)
        return "\n".join(ws.stale + [f'no caption holds "{text.strip()}"' + (f"; closest: {', '.join(repr(c) for c in close)}" if close else "")])
    hits.sort(key=lambda h: h[:3])
    return "\n".join(ws.stale + cut([h[3] for h in hits], limit, offset=offset))
