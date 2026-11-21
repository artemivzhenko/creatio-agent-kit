"""The package index on disk: one SQLite file per workspace (S26-T01), stdlib `sqlite3`.

    <workspace>/.creatio-index/index.sqlite        (next to the package when it is not in a clio workspace)

`PackageIndex` keeps its dict (`format`, `registry`, `package`, ..., `schemas`, `data`); this module only stores and
loads it: `save_package(path, folder, data)` writes one package in one transaction, `load_package(path, folder)`
gives the same dict back. The tables:

    meta      (key, value)                              format of the store
    packages  (name, uid, version, depends_on, culture, cultures, refreshed_at, unreadable, head)
    nodes     (package, kind, name, uid, caption, summary, parent, entry)   one per schema; a binding is `Data/<name>`,
                                                                           its object the parent
    files     (package, node, path, size, mtime)
    edges     (package, node, to_kind, to_name, to_uid, via, ref, detail)  the typed deps of an entry
    refs      (package, node, to_name)                  the names an entry's text refers to; a binding refers to its object
    captions  FTS5 (package, node, kind, key, culture, text)               what `resolve` searches: the schema's own
              caption, its columns', elements', parameters', rules' captions, a binding's lookup values (key = the value)

The tables the S31 passes fill (S26-T03; the rows are theirs, a package refresh never touches them):

    platform_captions (package, schema, key, culture, text)   the captions of the local platform install (S31-T09);
                                                              `meta.platform_version` is that install's version
    site_columns (env, at, package_of_object, object, name, type, package, caption, missing)
                                                              columns the site's table has and the workspace does not
                                                              define (S31-T10); a table missing on the site is one row
                                                              with `missing` = 1 and no name
    site_schemas (env, at, name, uid, kind, package, caption) schemas of the workspace's prefixes on the site that no
                                                              workspace package defines (S31-T11)

`at` is the ISO time of the pass: a pass replaces the rows of its env.

`entry` is the builders' dict as JSON, unchanged; `head` the package fields that are not entries; the other columns
are extracted from them at save time, for the workspace queries (S26-T02). It is a cache of the files: delete it and
the next call rebuilds it. WAL and a 5 s busy timeout let two sessions share a workspace: a second writer waits, a
reader sees the last committed package. Without FTS5 `captions` is a plain table and `fts` is False (MATCH falls
back to LIKE in the readers). Every connection has `fold(text)` (Python's casefold): `resolve` matches inside words and
in any script, which neither MATCH nor LIKE does.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

STORE_NAME = "index.sqlite"
STORE_FORMAT = "4"  # a new table or column bumps it (a fresh package never writes, so never creates it); 3: entries carry their uid, `captions` holds every row `resolve` searches, `refs`, a binding's object as its parent (S26-T02); 4: the S31 tables (S26-T03)
DDL = (
    "create table if not exists meta (key text primary key, value text)",
    "create table if not exists packages (name text primary key, uid text, version text, depends_on text, culture text, "
    "cultures text, refreshed_at text, unreadable integer, head text)",
    "create table if not exists nodes (package text, kind text, name text, uid text, caption text, summary text, "
    "parent text, entry text, primary key (package, name))",
    "create table if not exists files (package text, node text, path text, size integer, mtime integer, primary key (package, path))",
    "create table if not exists edges (package text, node text, to_kind text, to_name text, to_uid text, via text, ref text, detail text)",
    "create index if not exists edges_to_name on edges (to_name collate nocase)",
    "create index if not exists edges_to_uid on edges (to_uid)",
    "create index if not exists nodes_name on nodes (name collate nocase)",
    "create table if not exists refs (package text, node text, to_name text, primary key (package, node, to_name))",
    "create index if not exists refs_to_name on refs (to_name)",
    "create table if not exists platform_captions (package text, schema text, key text, culture text, text text)",
    "create index if not exists platform_captions_schema on platform_captions (schema collate nocase, key)",
    "create table if not exists site_columns (env text, at text, package_of_object text, object text, name text, type text, "
    "package text, caption text, missing integer)",
    "create index if not exists site_columns_object on site_columns (env, object collate nocase)",
    "create table if not exists site_schemas (env text, at text, name text, uid text, kind text, package text, caption text)",
    "create index if not exists site_schemas_name on site_schemas (env, name collate nocase)",
)
TABLES = ("packages", "nodes", "files", "edges", "refs", "captions", "platform_captions", "site_columns", "site_schemas")
CAPTIONS_FTS = "create virtual table if not exists captions using fts5(package, node, kind, key, culture, text, tokenize='unicode61')"
CAPTIONS_PLAIN = "create table if not exists captions (package text, node text, kind text, key text, culture text, text text)"
CAPTION_GROUPS = (("columns", "column"), ("elements", "element"), ("parameters", "parameter"), ("rules", "rule"))
CAPTION_KINDS = frozenset({"object", "page", "process", "dcm", "user-task", "rules", "classic"})  # the kinds `resolve` finds by their own caption
DATA_PREFIX = "Data/"


def has_fts5() -> bool:
    """Whether this Python's SQLite was compiled with FTS5."""
    con = sqlite3.connect(":memory:")
    try:
        con.execute("create virtual table t using fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


FTS5 = has_fts5()


def connect(path: Path, write: bool = True) -> sqlite3.Connection:
    """The store at `path`, a 5 s busy timeout; for a writer also WAL and the tables, created when missing (a reader
    writes nothing: a missing table is the caller's OperationalError)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=5.0)
    con.execute("pragma busy_timeout = 5000")
    con.create_function("fold", 1, lambda s: s.casefold() if isinstance(s, str) else s, deterministic=True)  # LIKE folds ASCII only
    if not write:
        return con
    con.execute("pragma journal_mode = wal")
    for statement in DDL + ((CAPTIONS_FTS if FTS5 else CAPTIONS_PLAIN),):
        con.execute(statement)
    con.execute("insert or replace into meta (key, value) values ('format', ?)", (STORE_FORMAT,))  # the last writer's format
    con.execute("insert or ignore into meta (key, value) values ('fts5', ?)", ("1" if FTS5 else "0",))
    con.commit()
    return con


def load_head(path: Path, folder: str, con: sqlite3.Connection | None = None) -> tuple[dict, int] | None:
    """(the package's fields without its entries, how many entries are unreadable), or None when the store has no such
    package (or no file, or the package was saved by an older store format): what a freshness check needs (S26-T04).
    `con`: a reader the caller holds for the whole call (one open per call, not three per package)."""
    if con is None and not path.is_file():
        return None
    own = con is None
    con = con or connect(path, write=False)
    try:
        return _head(con, folder)
    finally:
        if own:
            con.close()


def _head(con: sqlite3.Connection, folder: str) -> tuple[dict, int] | None:
    try:
        row = con.execute("select head, unreadable from packages where name = ?", (folder,)).fetchone()
    except sqlite3.OperationalError:  # a store with no tables yet (created by a writer that has not committed)
        return None
    if row is None:
        return None
    head = json.loads(row[0])
    if head.pop("store", None) != STORE_FORMAT:  # saved by an older store: the package is rebuilt from disk
        return None
    return head, row[1] or 0


def load_files(path: Path, folder: str, con: sqlite3.Connection | None = None) -> dict[str, dict[str, list[int]]]:
    """{node: {path: [size, mtime]}} of every node of the package, in the order it was saved; a node without files maps
    to {}. The entries themselves are not read."""
    own = con is None
    con = con or connect(path, write=False)
    try:
        nodes = {name: {} for (name,) in con.execute("select name from nodes where package = ? order by rowid", (folder,))}
        for node, rel, size, mtime in con.execute("select node, path, size, mtime from files where package = ? order by rowid", (folder,)):
            nodes.setdefault(node, {})[rel] = [size, mtime]
        return nodes
    finally:
        if own:
            con.close()


def load_package(path: Path, folder: str, con: sqlite3.Connection | None = None) -> dict | None:
    """The package dict as `PackageIndex` saved it, or None when the store has no such package (or no file)."""
    if con is None and not path.is_file():
        return None
    own = con is None
    con = con or connect(path, write=False)
    try:
        found = _head(con, folder)
        if found is None:
            return None
        data = found[0]
        schemas, bindings = {}, {}
        for name, entry in con.execute("select name, entry from nodes where package = ? order by name", (folder,)):
            if name.startswith(DATA_PREFIX):
                bindings[name[len(DATA_PREFIX):]] = json.loads(entry)
            else:
                schemas[name] = json.loads(entry)
        data["schemas"], data["data"] = schemas, bindings
        return data
    finally:
        if own:
            con.close()


def _rows(folder: str, data: dict):
    culture = data.get("culture") or ""
    nodes, files, edges, captions, refs = [], [], [], [], []
    items = [(n, e) for n, e in data.get("schemas", {}).items()] + [(DATA_PREFIX + n, e) for n, e in data.get("data", {}).items()]
    for name, e in items:
        kind = "data" if name.startswith(DATA_PREFIX) else e.get("kind", "?")
        parent = e.get("schema") if kind == "data" else e.get("parent")  # a binding builds on its object
        nodes.append((folder, kind, name, e.get("uid"), e.get("caption"), e.get("summary"), parent, json.dumps(e, ensure_ascii=False)))
        refs += [(folder, name, to) for to in sorted(set(e.get("refs") or []) | ({parent} if kind == "data" and parent else set()))]
        files += [(folder, name, rel, st[0], st[1]) for rel, st in (e.get("files") or {}).items()]
        edges += [(folder, name, d.get("kind"), d.get("name"), d.get("uid"), d.get("via"), d.get("ref"),
                   json.dumps(d["detail"], ensure_ascii=False) if d.get("detail") else None) for d in e.get("deps") or []]
        if "error" in e:
            continue
        if kind in CAPTION_KINDS:  # the rows `resolve` searches, in its order; a row without a caption is found by its name
            captions.append((folder, name, kind, "", culture, e.get("caption") or ""))
        for group, ckind in CAPTION_GROUPS:
            values = e.get(group)
            if isinstance(values, dict):
                captions += [(folder, name, ckind, key, culture, text if isinstance(text, str) else "") for key, text in values.items()]
            elif isinstance(values, list):  # a page's elements: [{"name", "caption"}]
                captions += [(folder, name, ckind, el["name"], culture, el.get("caption") or "") for el in values if isinstance(el, dict)]
        if kind == "data":
            captions += [(folder, name, "lookup", str(k.get("value")), culture, k.get("caption") or "") for k in e.get("keys") or [] if isinstance(k, dict)]
    return nodes, files, edges, captions, refs


def save_package(path: Path, folder: str, data: dict) -> None:
    """Replace one package's rows in one transaction."""
    head = {k: v for k, v in data.items() if k not in ("schemas", "data")} | {"store": STORE_FORMAT}
    nodes, files, edges, captions, refs = _rows(folder, data)
    unreadable = sum(1 for e in list(data.get("schemas", {}).values()) + list(data.get("data", {}).values()) if "error" in e)
    con = connect(path)
    try:
        with con:  # one transaction: a reader sees the old package or the new one, never half
            for table in ("nodes", "files", "edges", "captions", "refs"):
                con.execute(f"delete from {table} where package = ?", (folder,))
            con.execute("insert or replace into packages values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (folder, data.get("uid"), data.get("version"), json.dumps(data.get("depends_on") or []),
                         data.get("culture"), json.dumps(data.get("cultures") or {}), data.get("built"), unreadable,
                         json.dumps(head, ensure_ascii=False)))
            con.executemany("insert into nodes values (?, ?, ?, ?, ?, ?, ?, ?)", nodes)
            con.executemany("insert into files values (?, ?, ?, ?, ?)", files)
            con.executemany("insert into edges values (?, ?, ?, ?, ?, ?, ?, ?)", edges)
            con.executemany("insert into captions values (?, ?, ?, ?, ?, ?)", captions)
            con.executemany("insert into refs values (?, ?, ?)", refs)
    finally:
        con.close()


def format_of(path: Path) -> str | None:
    """The `meta` format of the store at `path`; None when there is no file or no table yet. A corrupt file raises
    `sqlite3.DatabaseError`."""
    if not path.is_file():
        return None
    con = connect(path, write=False)
    try:
        row = con.execute("select value from meta where key = 'format'").fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:  # no meta table: an empty file
        return None
    finally:
        con.close()


def stats(path: Path) -> list[str]:
    """`index --stats`: the file and its size, the format and FTS5 state, rows per table, per package its refresh time
    and unreadable count."""
    if not path.is_file():
        return [f"{path}: no store yet (the first describe call or `index` builds it)"]
    con = connect(path, write=False)
    try:
        meta = dict(con.execute("select key, value from meta"))
        size = path.stat().st_size + sum(f.stat().st_size for f in path.parent.glob(path.name + "-wal"))
        lines = [f"{path}: {size / 1024:.0f} KB, format {meta.get('format', '?')}"
                 + ("" if meta.get("format") == STORE_FORMAT else f" (this toolkit writes {STORE_FORMAT}: the next refresh rebuilds every package)")
                 + f", FTS5 {'on' if meta.get('fts5') == '1' else 'off (captions is a plain table)'}"
                 + (f", platform {meta['platform_version']}" if meta.get("platform_version") else "")]
        have = {n for (n,) in con.execute("select name from sqlite_master where type in ('table', 'view')")}
        lines.append("  rows: " + ", ".join(f"{t} {con.execute(f'select count(*) from {t}').fetchone()[0]}" if t in have else f"{t} -"
                                             for t in TABLES))
        for name, at, unreadable in con.execute("select name, refreshed_at, unreadable from packages order by name"):
            lines.append(f"  {name}: built {at}" + (f", {unreadable} unreadable" if unreadable else ""))
        return lines
    finally:
        con.close()


def drop_json(path: Path, folder: str) -> bool:
    """Delete the JSON index of one package the store replaces (`<dir>/<Package>.json` next to the store)."""
    old = path.parent / f"{folder}.json"
    if old.is_file():
        old.unlink()
        return True
    return False
