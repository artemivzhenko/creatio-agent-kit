"""What changed on a site between two moments, and a feature switched on a dev site (S40-T04): thin wrappers over clio verbs
its MCP server does not reach (`clio-run` answers `cli-verb-not-mcp-tool`).

    save_state(env, "before.yaml")               clio save-state: the site's manifest (features, settings, webservices,
                                                 packages with their schemas' hashes) and the item count per section
    manifest_diff("before.yaml", "after.yaml")   two such files compared here, grouped by section, one line per change
    show_diff(env, other)                        clio show-diff --source <env> --target <other>: two environments now
    set_feature(env, "UsrFeature", "on", project)  clio set-feature <code> 1|0; refused unless project.json marks env `kind: dev`

clio's `show-diff` compares two environments, not two manifest files, so the "before / after a push" question is answered
by `manifest_diff` over two `save-state` files. `apply-manifest` is not wrapped: it writes to a site, and the push stays
the kit's one write path.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import environment
from .runs import environment_is_dev

ITEM = re.compile(r"^(\s*)- ([^:]+):\s?(.*)$")
KEY = re.compile(r"^(\s*)([^:#][^:]*):\s?(.*)$")
FEATURE_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_.]*")
STATES = {"on": "1", "true": "1", "1": "1", "off": "0", "false": "0", "0": "0"}


def _run(clio_run):
    return clio_run or environment._run_clio  # looked up at call time: a test patches the module's runner


def _scalar(text: str) -> str:
    text = text.strip()
    if len(text) > 1 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if len(text) > 1 and text[0] == text[-1] == '"':
        return text[1:-1].replace('\\"', '"')
    return text


def read_manifest(text: str) -> tuple[dict[tuple, str], set[tuple]]:
    """(values, items) of a save-state manifest: `values` maps a path (`("packages", "UsrPkg", "schemas", "UsrOrder", "hash")`) to
    its scalar, `items` holds the path of every list item (a `- <key>: <value>` line, named by that first value).

    shortcut: reads the block YAML clio writes (keys and `- key: value` items by indent, plain or quoted scalars, a line of
    neither kind continues the last value); a flow collection or a block scalar would need a YAML parser."""
    values: dict[tuple, str] = {}
    items: set[tuple] = set()
    owner: dict[int, tuple] = {0: ()}  # content indent -> the path a `key: value` at that indent belongs to
    lists: dict[int, tuple] = {}       # item indent -> the path a `- key: value` at that indent is an item of
    last = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = ITEM.match(raw)
        if m:
            i = len(m.group(1))
            owner = {k: v for k, v in owner.items() if k <= i}
            lists = {k: v for k, v in lists.items() if k <= i}
            path = lists.get(i, owner.get(i, ())) + (_scalar(m.group(3)),)
            items.add(path)
            owner[i + 2] = path
            last = path + (m.group(2).strip(),)
            values[last] = _scalar(m.group(3))
            continue
        m = KEY.match(raw)
        if m:
            i, key, rest = len(m.group(1)), m.group(2).strip(), m.group(3)
            owner = {k: v for k, v in owner.items() if k <= i}
            lists = {k: v for k, v in lists.items() if k <= i}
            path = owner.get(i, ()) + (key,)
            if rest.strip():
                values[path] = _scalar(rest)
                last = path
            else:
                owner[i + 2] = lists[i] = lists[i + 2] = path
            continue
        if last is not None:
            values[last] = (values[last] + " " + raw.strip()).strip()
    return values, items


def section_counts(values: dict[tuple, str], items: set[tuple]) -> dict[str, int]:
    """The number of top items per section, the sections in the file's order."""
    counts = dict.fromkeys((p[0] for p in values), 0)
    for path in items:
        if len(path) == 2:
            counts[path[0]] += 1
    return counts


def save_state(env: str, file: str, clio_run=None) -> str:
    """`clio save-state <file> -e <env>`, then `saved <file>: features N, settings N, webservices N, packages N`."""
    target = Path(file).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    code, output = _run(clio_run)(["save-state", str(target), "-e", env])
    if code or not target.is_file():
        raise RuntimeError(f"clio save-state exited {code}: {environment.err_line(output)}")
    values, items = read_manifest(target.read_text(encoding="utf-8-sig"))
    return f"saved {target}: " + ", ".join(f"{k} {v}" for k, v in section_counts(values, items).items())


def _enclosing(path: tuple, items: set[tuple]) -> tuple:
    for n in range(len(path) - 1, 0, -1):
        if path[:n] in items:
            return path[:n]
    return path[:1]


def manifest_diff(before: str, after: str) -> list[str]:
    """One line per change, grouped by section (`packages: 2 changes` then `  + UsrPkg`, `  - UsrOld`,
    `  ~ UsrPkg schemas/UsrOrder/hash: A -> B`); `[]` when the two files hold the same."""
    b_values, b_items = read_manifest(Path(before).read_text(encoding="utf-8-sig"))
    a_values, a_items = read_manifest(Path(after).read_text(encoding="utf-8-sig"))
    changes: dict[str, list[str]] = {}

    def add(path: tuple, line: str) -> None:
        changes.setdefault(path[0], []).append(line)

    def name(item: tuple) -> str:
        return " ".join([item[1]] + (["/".join(item[2:])] if len(item) > 2 else []))

    for item in sorted(b_items ^ a_items):
        parent = _enclosing(item, b_items | a_items)
        if len(item) == 2 or (parent in b_items and parent in a_items):  # an item under an added one is part of that one
            add(item, f"  {'+' if item in a_items else '-'} {name(item)}")
    for path in sorted(set(b_values) | set(a_values)):
        item = _enclosing(path, b_items | a_items)
        if b_values.get(path) == a_values.get(path) or item not in b_items or item not in a_items:
            continue
        where = " ".join(([name(item)] if len(item) > 1 else []) + ["/".join(path[len(item):])])
        add(path, f"  ~ {where}: {b_values.get(path, '(none)')} -> {a_values.get(path, '(none)')}")
    out = []
    order = dict.fromkeys([p[0] for p in b_values] + [p[0] for p in a_values])  # the sections in the files' order
    for section in [s for s in order if s in changes]:
        out.append(f"{section}: {len(changes[section])} change(s)")
        out += changes[section]
    return out


def show_diff(env: str, other: str, clio_run=None) -> list[str]:
    """`clio show-diff --source <env> --target <other>`: what clio prints, without its progress lines."""
    code, output = _run(clio_run)(["show-diff", "--source", env, "--target", other])
    if code:
        raise RuntimeError(f"clio show-diff exited {code}: {environment.err_line(output)}")
    noise = re.compile(r"^\s*(Loaded \d+ out of \d+|\[INF\] - (Creat|Delet|Load|Operating|Saving))")
    return [l.rstrip() for l in output.splitlines() if l.strip() and not noise.match(l)]


def set_feature(env: str, code: str, state: str, project: str | None, clio_run=None) -> str:
    """`clio set-feature <code> 1|0 -e <env>` for all users; PermissionError unless project.json marks `env` as `kind: dev`."""
    if not FEATURE_CODE.fullmatch(code or ""):
        raise ValueError(f"{code!r} is not a feature code")
    value = STATES.get(str(state).strip().lower())
    if value is None:
        raise ValueError(f"state must be on or off, not {state!r}")
    if not environment_is_dev(project, env):
        raise PermissionError(f"refused: {env} is not a dev environment (project.json environment.kind must be \"dev\" for it)")
    rc, output = _run(clio_run)(["set-feature", code, value, "-e", env])
    if rc:
        raise RuntimeError(f"clio set-feature exited {rc}: {environment.err_line(output)}")
    return f"feature {code} {'on' if value == '1' else 'off'} for all users on {env}"
