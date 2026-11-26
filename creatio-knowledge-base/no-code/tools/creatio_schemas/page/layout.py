"""A Freedom UI grid container over every layer of its page, site layers included (S48-T08).

    layout_lines(package, page, container, env)   the `viewConfigDiff` of every copy of the parent chain, then of the page, first to
                                                  last (`classicui.layout.chain_bodies`), folded (`fold.fold`: insert, merge, move, remove), and the container's cells by
                                                  `layoutConfig` (row, column, colSpan, rowSpan from 1) printed as a grid

Read-only. The container's column count is the length of its `columns` value, else the widest cell.
"""

from __future__ import annotations

from ..classicui.layout import chain_bodies, render_layout
from .fold import fold
from .schema import PageSchema


def layout_lines(package, page: str, container: str, env=None) -> list[str]:
    layers = chain_bodies(package, page, env)
    ops, last = [], {}
    for pkg, _, text, _ in layers:
        for op in PageSchema._ops_of(text):
            ops.append(op)
            if op.get("name") and (op.get("operation") in ("insert", "move") or "layoutConfig" in (op.get("values") or {})):
                last[op["name"]] = pkg
    folded = fold(ops)
    columns = ((folded.get(container) or {}).get("values") or {}).get("columns")
    return render_layout(page, container, layers, folded, last, "layoutConfig", len(columns) if isinstance(columns, list) else None, 1,
                         any(not x[3] for x in layers))
