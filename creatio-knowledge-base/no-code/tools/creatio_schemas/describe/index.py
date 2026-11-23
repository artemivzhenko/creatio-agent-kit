"""The package index: the project's knowledge-base file, one SQLite store per workspace (store.py).

For every schema, SQL script and data binding it stores the kind, caption, summary line, the
parent or target, every file that belongs to it (with size and mtime) and the other schemas
of the workspace it refers to. `describe_package` and `find_schema` answer from it, so a
package of 500 schemas is listed in milliseconds instead of being parsed again, and an agent
gets the files of a schema without searching. The index checks itself on every use: a file
that changed, a schema that appeared (after `clio pull-pkg`) or disappeared is re-read before
the answer, so there is no refresh hook to forget.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import traceback
from pathlib import Path

from ..csharp import csharp_files
from ..files import LEGACY_ENCODED, read_text
from ..resources import Resources
from ..workspace import Workspace
from . import platform, store
from .core import DEFAULT_LIMIT, _caption, cut, kind_of, open_item, summary
from .deps import Edge, Resolver, deps_of

INDEX_DIR = ".creatio-index"
INDEX_FORMAT = 6  # 3: typed `deps` edges per item (describe/deps.py); 4: the text extractors (S20-T02); 5: parse_diff forms, located errors (S22-T03); 6: captions in the package's primary culture (S31-T01)
TYPE_NAME_RE = re.compile(r"\b(?:class|interface|struct|enum|record)\s+(\w+)")
# Identifiers and GUIDs: the two ways a file names another schema.
TOKEN_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[A-Za-z_][A-Za-z0-9_]{2,}")  # GUID first: one may start with a letter
SCAN_SUFFIXES = {".json", ".cs", ".js", ".sql", ".less", ".css"}  # resource XML is captions, not references
UNREADABLE = (OSError, UnicodeDecodeError, ValueError, KeyError, IndexError)  # one bad item costs one line, never the answer


def index_path(package: Path) -> Path:
    """<workspace>/.creatio-index/index.sqlite in a clio workspace (one store for every package); next to the package folder otherwise."""
    package = Path(package)
    root = package.parent.parent if package.parent.name == "packages" else package.parent
    return root / INDEX_DIR / store.STORE_NAME


def packages_of(path: Path | str) -> list[Path]:
    """The package folders a path means: a package, a clio workspace root, or a folder of packages."""
    path = Path(path)
    if (path / "descriptor.json").is_file():
        return [path]
    root = path / "packages" if (path / "packages").is_dir() else path
    pkgs = sorted(p for p in root.iterdir() if (p / "descriptor.json").is_file()) if root.is_dir() else []
    if not pkgs:
        raise FileNotFoundError(f"{path} is neither a package nor a folder with packages")
    return pkgs


def located(package: Path, files, e: Exception) -> str:
    """`<file>:<byte offset>: <Type>: <message>` for an item that cannot be read: a decoding error or a JSON error is found
    again in the item's files (a JSON value inside a diff file too); any other error names the reader line that raised."""
    reason = f"{type(e).__name__}: {e}"
    doc, pos = getattr(e, "doc", None), getattr(e, "pos", None)
    for rel in files:
        try:
            raw = (package / rel).read_bytes()
        except OSError:
            continue
        if isinstance(e, UnicodeDecodeError):
            try:
                read_text(package / rel)
            except UnicodeDecodeError as again:
                return f"{rel}:{again.start}: {reason}"
            continue
        if isinstance(doc, str) and doc and isinstance(pos, int):
            text = raw.decode("utf-8", errors="replace")
            at = text.find(doc)
            if at >= 0:
                return f"{rel}:{len(text[:at + pos].encode('utf-8'))}: {reason}"
    frame = traceback.extract_tb(e.__traceback__)[-1] if e.__traceback__ else None
    return reason + (f" (raised at {Path(frame.filename).name}:{frame.lineno})" if frame else "")


ITEM_NAME_RE = re.compile(r'<Item Name="')


def culture_counts(package: Path) -> dict[str, int]:
    """Resource keys per culture, summed over the package's `Resources/*/resource.<culture>.xml`."""
    counts: dict[str, int] = {}
    for path in (package / "Resources").glob("*/resource.*.xml") if (package / "Resources").is_dir() else []:
        try:
            n = len(ITEM_NAME_RE.findall(read_text(path)[0]))
        except (OSError, UnicodeDecodeError):
            continue
        culture = path.name[len("resource."):-len(".xml")]
        counts[culture] = counts.get(culture, 0) + n
    return counts


def project_culture(package: Path) -> str | None:
    """`culture` of the workspace's project.json (the tie-break of the primary culture)."""
    root = package.parent.parent if package.parent.name == "packages" else package.parent
    try:
        value = json.loads((root / "project.json").read_text(encoding="utf-8-sig")).get("culture")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


def primary_culture(counts: dict[str, int], package: Path) -> str:
    """The culture with the most keys; one culture is that one; a tie goes to project.json's `culture`, then en-US, then the first by name."""
    if not counts:
        return project_culture(package) or "en-US"
    top = max(counts.values())
    tied = sorted(c for c, n in counts.items() if n == top)
    if len(tied) == 1:
        return tied[0]
    for choice in (project_culture(package), "en-US"):
        if choice in tied:
            return choice
    return tied[0]


def _cap(res, key: str, culture: str):
    """The caption of `key` in `culture`, or None when the schema has no such key."""
    return res.get(key, culture) if res is not None else None


def captions_of(kind: str, item, culture: str) -> dict:
    """The index fields that carry captions: `columns` {name: caption} of an object, `elements` of a page (name, type, parent,
    control, caption), `parameters` / `elements` {name: caption} of a process, `parameters` of a user task, `rules` {name: caption}.
    A caption the culture lacks is None. Pure: an item in, a dict out."""
    res = getattr(item, "resources", None)
    if kind == "object":
        return {"columns": {c["A2"]: _cap(res, f"Columns.{c['A2']}.Caption", culture) for c in item.own_columns()}}
    if kind == "page":
        item.culture = culture
        seen: dict[str, dict] = {}
        for op in item.elements():
            values = op.get("values") or {}
            if op.get("operation") not in (None, "insert") or not isinstance(values.get("type"), str):
                continue
            raw = next((values[k] for k in ("label", "caption", "title") if isinstance(values.get(k), str)), None)
            el = {"name": op["name"], "type": values["type"], "parent": op.get("parentName"),
                  "control": values["control"] if isinstance(values.get("control"), str) else None, "caption": item._text(raw)}
            seen[op["name"]] = {k: v for k, v in el.items() if v is not None or k == "caption"}
        return {"elements": list(seen.values())}
    if kind == "process":
        return {"parameters": {p["A2"]: _cap(res, f"Parameters.{p['A2']}.Caption", culture) for p in item.params},
                "elements": {e["A2"]: _cap(res, f"BaseElements.{e['A2']}.Caption", culture) for e in item.elements if e.get("A2")}}
    if kind == "user-task":
        return {"parameters": {p["A2"]: _cap(res, f"Parameters.{p['A2']}.Caption", culture) for p in item.params}}
    if kind == "rules":
        return {"rules": {r["BR3"]: item.caption(r, culture) for r in item.rules if r.get("BR3")}}
    return {}


def _norm(name: str) -> str:
    """A file name as this system compares it (Windows: case-insensitive, as the `Resources/<name>.*` glob did)."""
    return os.path.normcase(name) if os.name == "nt" else name


def _path_key(rel: str) -> list[str]:
    """The key `sorted()` of Path objects compared by: the parts, case-folded on Windows."""
    return _norm(rel.replace("/", os.sep)).split(os.sep)


def _stat(path: Path) -> list[int]:
    st = path.stat()
    return [st.st_size, st.st_mtime_ns]


class PackageIndex:
    """One package's index: load, check against the disk, answer."""

    def __init__(self, package: Path | str, con: sqlite3.Connection | None = None):
        """`con`: a reader of the store the caller holds for the whole call (`Indexed`); None opens one per read."""
        self.package = Path(package)
        self.path = index_path(self.package)
        self._con = con
        self.reset = ""  # why the store file was deleted and is rebuilt (a corrupt or foreign file), for `index` to say
        self._data: dict | None = None  # the entries, read from the store on first use: an up-to-date package never is (S26-T04)
        self._head, self._unreadable_n = {}, 0
        if store.drop_json(self.path, self.package.name):  # the JSON index before S26: the store is built from disk instead
            print(f"index: {self.package.name}.json replaced by {store.STORE_NAME}", file=sys.stderr)
        try:
            self._head, self._unreadable_n = store.load_head(self.path, self.package.name, self._con) or ({}, 0)
        except sqlite3.DatabaseError as exc:  # a corrupt or foreign file: every package is rebuilt into a new one
            self.path.unlink(missing_ok=True)
            self.reset = f"{self.path}: not a store this toolkit reads ({exc}); rebuilt from disk"
        self._format_mismatch = self._head.get("format") != INDEX_FORMAT
        self._names: dict[str, str] = {}  # lower-case name and uid -> schema name, whole workspace
        self._culture = self._head.get("culture") or "en-US"

    @property
    def data(self) -> dict:
        """The package dict (`format`, `package`, ..., `schemas`, `data`), loaded from the store when first asked for."""
        if self._data is None:
            self._data = (store.load_package(self.path, self.package.name, self._con) if self._head else None) or {"schemas": {}, "data": {}}
        return self._data

    @data.setter
    def data(self, value: dict) -> None:
        self._data = value

    @property
    def head(self) -> dict:
        """The package's own fields (`package`, `version`, `culture`, `cultures`, ...) without loading the entries."""
        return self._data if self._data is not None else self._head

    # -- disk -------------------------------------------------------------- #

    def _scan(self) -> dict[str, dict[str, dict[str, list[int]]]]:
        """One `os.scandir` walk of Schemas, SqlScripts, Resources and Data: {top folder: {child folder: {package-relative
        path: [size, mtime_ns]}}}, the children in directory order, each child's files in the order `sorted(rglob)` gave
        them (the order the entries and their `files` rows always had)."""
        found = {}
        for top in ("Schemas", "SqlScripts", "Resources", "Data"):
            children = found[top] = {}
            try:
                tops = list(os.scandir(self.package / top))
            except (FileNotFoundError, NotADirectoryError):
                continue
            for child in tops:
                if not child.is_dir():
                    continue
                files, stack = [], [(child.path, f"{top}/{child.name}")]
                while stack:  # rglob does not follow a linked folder; is_file follows a linked file
                    folder, rel = stack.pop()
                    for e in os.scandir(folder):
                        if e.is_dir(follow_symlinks=False):
                            stack.append((e.path, f"{rel}/{e.name}"))
                        elif e.is_file():
                            st = e.stat()
                            files.append((f"{rel}/{e.name}", [st.st_size, st.st_mtime_ns]))
                files.sort(key=lambda f: _path_key(f[0]))
                children[child.name] = dict(files)
        return found

    def _on_disk(self) -> tuple[dict[str, str], dict[str, dict], list[str]]:
        """(items {name: "Schemas" | "SqlScripts" | "Files"}, files {name or `Data/<name>`: {path: [size, mtime]}}, the
        binding folders) - every item folder with a descriptor, plus every plain C# file under Files (named by its
        package-relative path: it has no descriptor, no resources, nothing but the one file). An item's files are its
        folder's, then those of each `Resources/<name>.*` folder."""
        scan = self._scan()
        found, files_now = {}, {}
        for folder in ("Schemas", "SqlScripts"):
            for name, files in scan[folder].items():
                if f"{folder}/{name}/descriptor.json" in files:
                    found[name], files_now[name] = folder, files
        resources: dict[str, list[dict]] = {}  # a name as compared -> the files of each Resources/<name>.* folder
        for child, files in scan["Resources"].items():
            for i, ch in enumerate(child):
                if ch == ".":
                    resources.setdefault(_norm(child[:i]), []).append(files)
        for name in found:
            for files in resources.get(_norm(name), []):
                files_now[name] = {**files_now[name], **files}
        for cs in csharp_files(self.package):
            name = cs.relative_to(self.package).as_posix()
            found[name], files_now[name] = "Files", {name: _stat(cs)}
        data_on_disk = sorted(scan["Data"])
        for name in data_on_disk:
            files_now[f"Data/{name}"] = scan["Data"][name]
        return found, files_now, data_on_disk

    def _stored_files(self) -> dict[str, dict[str, list[int]]]:
        """{node: files} as the index has them: from the loaded entries, else from the store's `files` rows."""
        if self._data is not None or not self._head:
            return {**{n: e.get("files") for n, e in self.schemas.items()},
                    **{f"Data/{n}": e.get("files") for n, e in self.data.get("data", {}).items()}}
        return store.load_files(self.path, self.package.name, self._con)

    # -- building ------------------------------------------------------------ #

    def _load_names(self) -> None:
        ws = Workspace(self.package)
        self._resolver = Resolver(ws)
        self._names = {}
        for s in ws.schemas:
            self._names[s["name"].lower()] = s["name"]
            self._names[s["uid"]] = s["name"]
            self._names[s["base"]] = s["name"]  # a lookup points at the base UId of a replacing schema
        for pkg in self.package.parent.iterdir():
            if (pkg / "SqlScripts").is_dir():
                for d in (pkg / "SqlScripts").iterdir():
                    if (d / "descriptor.json").is_file():
                        self._names[d.name.lower()] = d.name
            for cs in csharp_files(pkg):  # a plain C# file is referred to by the types it declares
                item = cs.relative_to(pkg).as_posix()
                try:
                    text = read_text(cs)[0]
                except (OSError, UnicodeDecodeError):
                    continue
                for type_name in TYPE_NAME_RE.findall(text):
                    self._names.setdefault(type_name.lower(), item)

    def _refs(self, files: dict[str, list[int]], own: str) -> list[str]:
        """Schemas of the workspace named (by identifier or UId) in the item's text files, itself excluded."""
        hits = set()
        for rel in files:
            if Path(rel).suffix.lower() not in SCAN_SUFFIXES:
                continue
            try:
                text = read_text(self.package / rel)[0]
            except (OSError, UnicodeDecodeError):
                continue
            for tok in TOKEN_RE.findall(text):
                name = self._names.get(tok.lower())
                if name and name != own:
                    hits.add(name)
        return sorted(hits)

    def _build_schema(self, name: str, files: dict[str, list[int]]) -> dict:
        entry = {"kind": "?", "caption": "", "summary": "", "parent": None, "files": files, "refs": self._refs(files, name)}
        try:
            item = open_item(self.package, name)
            entry["kind"] = kind_of(item)
            entry["caption"] = _caption(item)
            entry["summary"] = summary(item)
            if entry["summary"].startswith("unreadable: "):  # a reader that answers instead of raising (CSharpSource)
                entry["error"] = entry["summary"][len("unreadable: "):]
            if any((self.package / rel).resolve() in LEGACY_ENCODED for rel in files):
                entry["summary"] += " (cp1251)"
            entry["parent"] = _parent_of(item)
            from .registry import kind_for  # the registry name, not the renamed one: a GenericItem called "mobile" has no page body
            try:
                entry["deps"] = [e.as_dict() for e in deps_of(item, self._resolver, kind_for(item).name)]
            except Exception as e:  # the edges are an extra: a failing extractor costs them, not the item
                entry["deps"], entry["deps_error"] = [], f"{type(e).__name__}: {e}"
            try:
                entry.update(captions_of(entry["kind"], item, self._culture))
            except Exception as e:  # the captions are an extra: a failing reader costs them, not the item
                entry["captions_error"] = f"{type(e).__name__}: {e}"
            desc = getattr(item, "descriptor", None)
            data = desc.data if hasattr(desc, "data") else (desc or {})
            entry["manager"] = data.get("ManagerName") if isinstance(data, dict) else None
            entry["uid"] = str(data["UId"]).lower() if isinstance(data, dict) and data.get("UId") else None
            folders = sorted(p for p in (self.package / "Resources").glob(f"{name}.*") if p.is_dir())
            if folders:
                cultures = {}
                for folder in folders:
                    for culture, values in Resources(folder).cultures.items():
                        cultures.setdefault(culture, {}).update(values)
                base = cultures.get("en-US", {})
                entry["resources"] = {
                    "cultures": sorted(cultures),
                    "keys": len(base),
                    "missing": {culture: len(set(base) - set(values)) for culture, values in cultures.items() if culture != "en-US"},
                }
        except Exception as e:  # one broken schema must not stop the index
            entry["error"] = located(self.package, files, e)
        return entry

    def _json(self, path: Path):
        """A JSON file of a binding; the error names the file (an empty data.json, a missing descriptor)."""
        rel = path.relative_to(self.package).as_posix()
        if not path.is_file():
            raise ValueError(f"{rel}: missing")
        text = read_text(path)[0]
        if not text.strip():
            raise ValueError(f"{rel}: empty file")
        try:
            return json.loads(text)
        except ValueError as e:
            raise ValueError(f"{rel}: not JSON ({e})") from None

    def _build_data(self, name: str, files: dict[str, list[int]]) -> dict:
        desc = self._json(self.package / "Data" / name / "descriptor.json")["Descriptor"]
        columns = desc.get("Columns", [])
        by_uid = {str(c.get("ColumnUId", "")).lower(): c.get("ColumnName") for c in columns}
        key_name = next((candidate for candidate in ("Code", "Name") if any(c.get("ColumnName") == candidate for c in columns)), None)
        key_columns = [c["ColumnName"] for c in columns if c.get("IsKey")]

        def values(row):
            return {(cell.get("ColumnName") or by_uid.get(str(cell.get("SchemaColumnUId", "")).lower())): cell.get("Value")
                    for cell in row["Row"]}

        localized, captions = {}, {}
        loc_files = sorted((self.package / "Data" / name / "Localization").glob("data.*.json"),
                           key=lambda p: (p.name != "data.en-US.json", p.name))
        if key_columns and key_name:
            for path in loc_files:
                for row in self._json(path)["PackageData"]:
                    data = values(row)
                    if all(col in data for col in key_columns) and key_name in data:
                        k = tuple(str(data[col]).lower() for col in key_columns)
                        localized.setdefault(k, data[key_name])
                        if path.name == f"data.{self._culture}.json":
                            captions[k] = data.get("Name", data[key_name])
        rows, keys = 0, []
        for path in sorted((self.package / "Data" / name).rglob("data.json")):
            if "localization" in (part.lower() for part in path.relative_to(self.package / "Data" / name).parts):
                continue
            data_rows = self._json(path)["PackageData"]
            rows += len(data_rows)
            for row in data_rows:
                data = values(row)
                value = data.get(key_name)
                if value is None and key_columns and all(col in data for col in key_columns):
                    value = localized.get(tuple(str(data[col]).lower() for col in key_columns))
                if value is not None and len(keys) < DEFAULT_LIMIT:
                    own = tuple(str(data[col]).lower() for col in key_columns) if key_columns and all(col in data for col in key_columns) else None
                    keys.append({"value": value, "caption": captions.get(own) or data.get("Name") or value})
        schema = desc.get("Schema", {}).get("Name")
        deps = [Edge("object", *self._resolver.entity(schema), "binds", "name", [c["ColumnName"] for c in columns]).as_dict()] if schema else []
        return {"schema": schema, "columns": [c["ColumnName"] for c in columns],
                "rows": rows, "keys": keys, "files": files, "refs": self._refs(files, name), "deps": deps}

    def refresh(self, rebuild: bool = False) -> dict:
        """Bring the index in line with the disk; returns {"added": [...], "changed": [...], "removed": [...]}."""
        t0 = time.time()
        from .registry import KINDS  # the kinds and their order: a registry change must re-read every item (R01 finding 1)

        registry_fp = "|".join(k.name for k in KINDS)
        rebuild = rebuild or self._format_mismatch or self.head.get("registry") != registry_fp
        on_disk, files_now, data_on_disk = self._on_disk()
        stored = self._stored_files()  # the store's `files` rows: an up-to-date package is not loaded
        stored_data = {n[len("Data/"):] for n in stored if n.startswith("Data/")}
        changes = {"added": [], "changed": [], "removed": []}
        changes["removed"] = (sorted(n for n in stored if not n.startswith("Data/") and n not in on_disk)
                              + sorted(f"Data/{n}" for n in stored_data - set(data_on_disk)))
        todo_schemas, todo_data = [], []
        for name, folder in on_disk.items():
            if rebuild or name not in stored or stored[name] != files_now[name]:
                todo_schemas.append((name, folder))
                changes["added" if name not in stored else "changed"].append(name)
        for name in data_on_disk:
            label = f"Data/{name}"
            if rebuild or label not in stored or stored[label] != files_now[label]:
                todo_data.append(name)
                changes["added" if label not in stored else "changed"].append(label)
        if not any(changes.values()) and not self._format_mismatch:
            return changes
        schemas, data = self.data.get("schemas", {}), self.data.get("data", {})
        counts = culture_counts(self.package)
        self._culture = primary_culture(counts, self.package)
        if not rebuild and self._culture != self.head.get("culture"):  # every caption was read in another culture
            rebuild = True
            todo_schemas = [(n, f) for n, f in on_disk.items()]
            todo_data = list(data_on_disk)
            for label in [n for n, _ in todo_schemas] + [f"Data/{n}" for n in todo_data]:
                if label not in changes["added"] and label not in changes["changed"]:
                    changes["changed"].append(label)
        self._load_names()
        for name in changes["removed"]:
            (data if name.startswith("Data/") else schemas).pop(name.removeprefix("Data/"), None)
        for name, folder in todo_schemas:
            schemas[name] = self._build_schema(name, files_now[name])
        for name in todo_data:
            try:
                data[name] = self._build_data(name, files_now[f"Data/{name}"])
            except UNREADABLE as e:  # an empty data.json, a folder without its descriptor
                data[name] = {"error": f"{type(e).__name__}: {e}", "files": files_now[f"Data/{name}"], "refs": []}
        if rebuild or changes["added"] or changes["removed"]:
            # The set of names changed: every item may now refer to a new name, or to one that is gone.
            for name, entry in schemas.items():
                if name not in dict(todo_schemas):
                    entry["refs"] = self._refs(entry["files"], name)
            for name, entry in data.items():
                if name not in todo_data:
                    entry["refs"] = self._refs(entry["files"], name)
        desc = json.loads(read_text(self.package / "descriptor.json")[0])["Descriptor"]
        self.data = {"format": INDEX_FORMAT, "registry": registry_fp, "package": desc.get("Name", self.package.name), "version": desc.get("PackageVersion"),
                     "depends_on": [d["Name"] for d in desc.get("DependsOn", [])],
                     "culture": self._culture, "cultures": dict(sorted(counts.items())),
                     "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - t0, 2),
                     "schemas": dict(sorted(schemas.items())), "data": dict(sorted(data.items()))}
        store.save_package(self.path, self.package.name, self.data)
        self._format_mismatch = False
        return changes

    # -- answering ------------------------------------------------------------- #

    @property
    def schemas(self) -> dict:
        return self.data.get("schemas", {})

    def entries(self) -> list[tuple[str, dict]]:
        """(name, entry) of every schema and data binding (`Data/<name>`)."""
        return list(self.schemas.items()) + [(f"Data/{n}", e) for n, e in self.data.get("data", {}).items()]

    def dependents(self, name: str) -> list[tuple[str, str, Edge]]:
        """(kind, name, edge) of every item whose typed edges point at `name`."""
        key = name.lower()
        out = []
        for n, e in self.entries():
            for d in e.get("deps", []):
                if d["name"].lower() == key:
                    out.append((e.get("kind", "data"), n, Edge.from_dict(d)))
        return out

    def referrers(self, name: str) -> list[tuple[str, str]]:
        """(kind, name) of every schema or data binding in this package that refers to `name`."""
        hits = [(e["kind"], n) for n, e in self.schemas.items() if name in e.get("refs", [])]
        hits += [("data", n) for n, e in self.data.get("data", {}).items() if name in e.get("refs", []) or e.get("schema") == name]
        return hits

    def lines(self, kind: str = "") -> list[str]:
        """The describe_package lines, from the index; `kind="error"` lists only the unreadable items."""
        out = []
        for name, e in self.schemas.items():
            if "error" in e:
                if kind and kind not in ("schema", "error"):
                    continue
                out.append(f"  {'?':<9} {name:<36} {'':<34} cannot read: {e['error']}")
            elif not kind or e["kind"] == kind:
                out.append(f"  {e['kind']:<9} {name:<36} {e['caption']!r:<34} {e['summary']}")
        if kind in ("", "error"):
            out += [f"  {'?':<9} {'Data/' + name:<36} {'':<34} cannot read: {e['error']}" for name, e in self.data.get("data", {}).items() if "error" in e]
        return out


def _unreadable(idx) -> int:
    if idx._data is None:  # not loaded: the count saved with the package
        return idx._unreadable_n
    return sum("error" in e for e in idx.schemas.values()) + sum("error" in e for e in idx.data.get("data", {}).values())


def _unreadable_line(indexes: list[PackageIndex]) -> list[str]:
    """The one line find_schema and lookups end with when items were skipped."""
    broken = [idx for idx in indexes if _unreadable(idx)]
    if not broken:
        return []
    n = sum(_unreadable(idx) for idx in broken)
    where = ", ".join(f"describe.py package {idx.package} --kind error" for idx in broken[:3]) + (" ..." if len(broken) > 3 else "")
    return [f"{n} items unreadable ({where} lists them)"]


def _file_lines(package: Path, files: dict[str, list[int]]) -> list[str]:
    """One line per file, the per-culture files of a folder (resource.*.xml, data.*.json) folded into one."""
    cultures: dict[str, list[int]] = {}
    lines = []
    for rel, (size, _) in files.items():
        m = re.fullmatch(r"(.*/)(resource|data)\.[a-z]{2}-[A-Z]{2}\.(xml|json)", rel)
        if m:
            key = f"{m.group(1)}{m.group(2)}.*.{m.group(3)}"
            cultures.setdefault(key, [0, 0])
            cultures[key][0] += 1
            cultures[key][1] += size
        else:
            lines.append(f"    {(package / rel).as_posix()}  ({size} bytes)")
    for key, (n, size) in cultures.items():
        lines.append(f"    {(package / key).as_posix()}  ({n} cultures, {size} bytes)")
    return lines


def _parent_of(item) -> str | None:
    """What the schema builds on: the object's parent or replaced base, the page's entity or parent page, the rules' target."""
    for attr in ("parent_name", "target", "entity"):
        value = getattr(item, attr, None)
        if value:
            return value
    desc = getattr(item, "descriptor", None)
    data = desc.data if hasattr(desc, "data") else (desc or {})
    if isinstance(data, dict) and data.get("ExtendParent") and data.get("Parent"):
        return data["Parent"].get("Name")
    return None


class Indexed:
    """The packages a path means with every index refreshed; the workspace-wide lookups are statements over their rows
    in the store (S26-T02). `:pkgs` in a statement is the JSON list of the call's package folders."""

    PKGS = "package in (select value from json_each(:pkgs))"

    def __init__(self, path: Path | str):
        self.pkgs = packages_of(path)
        self.con = self._reader(index_path(self.pkgs[0])) if self.pkgs else None
        shared = self.con if len({index_path(p) for p in self.pkgs}) == 1 else None
        self.indexes = [PackageIndex(p, shared) for p in self.pkgs]
        self.stale: list[str] = []  # the first line of every answer when the store could not take the fresh rows
        for idx in self.indexes:
            try:
                idx.refresh()
            except (sqlite3.OperationalError, PermissionError) as exc:  # a read-only checkout: `idx.data` is fresh, unsaved
                self.stale = [f"(index stale: built from disk - the store cannot be written here: {exc})"]
        self.db, self._scratch = self.indexes[0].path if self.indexes else None, None
        if self.stale:  # the statements read a throwaway store of the fresh data
            if self.con is not None:
                self.con.close()
                self.con = None
            self._scratch = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.db = Path(self._scratch.name) / store.STORE_NAME
            for idx in self.indexes:
                store.save_package(self.db, idx.package.name, idx.data)
        self.rank = {p.name: i for i, p in enumerate(self.pkgs)}
        self.dir = {p.name: p for p in self.pkgs}
        self.name = {idx.package.name: idx.head.get("package", idx.package.name) for idx in self.indexes}  # folder -> package name

    @staticmethod
    def _reader(path: Path) -> sqlite3.Connection | None:
        """One reader for the whole call (S26-T03: an open per package cost ~0.3 s on 35 packages); None when there is no
        readable store yet, so each package opens, builds or replaces it as before."""
        if not path.is_file():
            return None
        con = store.connect(path, write=False)
        try:
            con.execute("select count(*) from sqlite_master").fetchone()
            return con
        except sqlite3.DatabaseError:  # corrupt: the package index deletes and rebuilds it, which an open handle would block
            con.close()
            return None

    def query(self, sql: str, **args) -> list[tuple]:
        """The rows of `sql` as the statement orders them; `{pkgs}` is the filter on the call's packages."""
        if self.con is None:  # one connection per call: an open costs ms in WAL mode, a statement here tens of µs
            self.con = store.connect(self.db, write=False)
        return self.con.execute(sql.replace("{pkgs}", self.PKGS), {"pkgs": json.dumps(list(self.rank)), **args}).fetchall()

    def __del__(self):
        if getattr(self, "con", None) is not None:
            self.con.close()
        if getattr(self, "_scratch", None) is not None:
            self._scratch.cleanup()

    def rows(self, sql: str, **args) -> list[tuple]:
        """`query` of a statement whose first column is the package: in package order (the order of `packages_of`), the
        statement's own order inside a package."""
        return sorted(self.query(sql, **args), key=lambda r: self.rank[r[0]])  # stable

    def referrer_counts(self) -> dict[str, int]:
        """{name: how many items refer to it} - the `referrers` of every name at once."""
        return dict(self.query("select to_name, count(*) from refs where {pkgs} group by to_name"))

    def referrers(self, name: str) -> list[tuple[str, str, str]]:
        """(package folder, kind, name) of every item that refers to `name` - its `refs`, or a binding of it."""
        rows = self.rows("select n.package, n.kind, n.name from refs r join nodes n on n.package = r.package and n.name = r.node "
                         "where r.{pkgs} and r.to_name = :n order by n.kind = 'data', n.name", n=name)
        return [(p, k, n.removeprefix(store.DATA_PREFIX)) for p, k, n in rows]

    def bindings(self, schema: str) -> list[tuple[str, str, int]]:
        """(package folder, binding, rows) of the readable data bindings of `schema`."""
        rows = self.rows("select package, name, json_extract(entry, '$.rows') from nodes where {pkgs} and kind = 'data' "
                         "and parent = :s and json_extract(entry, '$.error') is null order by name", s=schema)
        return [(p, n.removeprefix(store.DATA_PREFIX), r) for p, n, r in rows]

    def dependents(self, name: str) -> list[tuple[str, str, str, Edge]]:
        """(package folder, kind, name, edge) of every item whose typed edges point at `name`."""
        rows = self.rows("select e.package, n.kind, e.node, e.to_kind, e.to_name, e.to_uid, e.via, e.ref, e.detail from edges e "
                         "join nodes n on n.package = e.package and n.name = e.node where e.{pkgs} and e.to_name = :n collate nocase",
                         n=name)
        return [(p, k, n, Edge(tk, tn, tu, via, ref or "uid", json.loads(d) if d else [])) for p, k, n, tk, tn, tu, via, ref, d in rows]


def index_workspace(path: Path | str, rebuild: bool = False, stats: bool = False, env: str | None = None) -> str:
    """Refresh the index of every package under `path`; one line per package with what changed. A store file this
    toolkit cannot read (corrupt, foreign) or wrote in an older format is one line first: it is rebuilt, nothing else
    is tried. `stats` adds the store's rows per table, size, format and per package its build time (`store.stats`).
    `env` (a clio environment name): then the site's columns and schemas the workspace does not hold, read-only (site.py, S31-T10/T11)."""
    out = []
    pkgs = packages_of(path)
    paths = list(dict.fromkeys(index_path(p) for p in pkgs))
    for sp in paths:
        try:
            was = store.format_of(sp)
        except sqlite3.DatabaseError:
            continue  # the package index below says it and rebuilds
        if was and was != store.STORE_FORMAT:
            out.append(f"{sp}: store format {was}, this toolkit writes {store.STORE_FORMAT}; every package rebuilt")
    cultures, built = {"en-US"}, []
    for pkg in pkgs:
        idx = PackageIndex(pkg)
        built.append(idx)
        if idx.reset:
            out.append(idx.reset)
        ch = idx.refresh(rebuild)
        d = idx.data
        cultures.add(d.get("culture") or "en-US")
        out.append(f"{pkg.name}: {len(d.get('schemas', {}))} schemas, {len(d.get('data', {}))} data bindings"
                   + (f"; +{len(ch['added'])} added, ~{len(ch['changed'])} changed, -{len(ch['removed'])} removed in {d.get('seconds', 0)} s" if any(ch.values()) else "; up to date")
                   + f"  -> {idx.path}")
        for key in ("added", "changed", "removed"):
            if ch[key]:
                out.append(f"    {key}: {', '.join(ch[key][:20])}" + (f" ... +{len(ch[key]) - 20}" if len(ch[key]) > 20 else ""))
    platform_dir = platform.project_platform(pkgs[0]) if pkgs else None
    if platform_dir is not None:  # S31-T09: the install's captions, once per path, version and cultures
        try:
            out.append(platform.build(paths[0], platform_dir, cultures))
        except (OSError, ValueError, KeyError) as exc:
            out.append(f"platform: {exc}")
    if env and pkgs:
        out += _site_pass(pkgs, built, paths[0], env, path)
    if stats:
        for sp in paths:
            out += store.stats(sp)
    return "\n".join(out)


def _site_pass(pkgs: list[Path], built: list, db: Path, env_name: str, path) -> list[str]:
    """S31-T10/T11: every object of the index with the columns the workspace gives it, every schema name with its base UId."""
    from ..environment import open_environment
    from . import site

    ws = Workspace(pkgs[0])
    objects = {}
    for idx in built:
        for name, e in idx.data.get("schemas", {}).items():
            if e.get("kind") == "object" and name not in objects:
                objects[name] = (idx.package.name, set(ws.columns(name)))
    schemas = {s["name"]: s["base"] for s in ws.schemas}
    prefixes = site.prefixes_of(Path(path), [s["name"] for s in ws.schemas if s["uid"] == s["base"]])
    culture = next((idx.data.get("culture") for idx in built if idx.data.get("culture")), "en-US")
    try:
        return site.site_pass(db, open_environment(env_name, None), env_name, objects, schemas, prefixes, culture)
    except (RuntimeError, ValueError, KeyError, OSError) as exc:
        return [f"site {env_name}: {exc}"]


from ..entity.catalog import STOCK_LOOKUPS  # noqa: E402  (stock_lookups_<version>.json: 8.3.2 when present, else 8.2.3)


def lookups(path: Path | str, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """Every object of the workspace that is a lookup - its parent chain reaches BaseLookup, through the workspace's own
    objects or the stock ones (entity/assets/stock_lookups_<version>.json) - with package, caption, own columns, data bindings
    (rows bound) and how many items refer to it: the list a de-duplication or binding-check task starts from."""
    cut([], limit, offset=offset)
    ws = Indexed(path)
    pkgs, indexes = ws.pkgs, ws.indexes
    objects = ws.rows("select package, name, parent, caption, summary from nodes where {pkgs} and kind = 'object' order by name")
    parents = {n: parent for _, n, parent, _, _ in objects}
    users_of = ws.referrer_counts()
    binds: dict[tuple[str, str], list[str]] = {}
    for folder, schema, dn, count in ws.rows("select package, parent, name, json_extract(entry, '$.rows') from nodes "
                                             "where {pkgs} and kind = 'data' and json_extract(entry, '$.error') is null order by name"):
        binds.setdefault((folder, schema), []).append(f"{dn} ({count} rows)")

    def is_lookup(name: str, seen: frozenset = frozenset()) -> bool | None:
        """True / False, or None when the chain leaves the workspace into an object the stock list does not know."""
        if name == "BaseLookup" or name in STOCK_LOOKUPS:
            return True
        if name == "BaseEntity" or name in seen:
            return False
        parent = parents.get(name)
        if parent is None:
            return None if name in parents else (True if name in STOCK_LOOKUPS else None)
        return is_lookup(parent, seen | {name})

    rows, unknown = [], []
    for folder, n, _, caption, summ in objects:
        pkg, caption, summ = ws.name[folder], caption or "", summ or ""
        verdict = is_lookup(n)
        if verdict is None:
            unknown.append(f"{n} (parent {parents.get(n)}, {pkg})")
            continue
        if not verdict:
            continue
        chain, cur = [], parents.get(n)
        while cur and cur not in chain and cur != "BaseLookup":
            chain.append(cur)
            cur = parents.get(cur)
        own = re.search(r"\((\d+) own\)", summ)
        bindings = binds.get((folder, n), [])
        users = users_of.get(n, 0)
        rows.append(f"  {n:<34} {caption!r:<30} {pkg:<16} "
                    + ("replacing " if "replacing" in summ else "parent ") + " -> ".join(chain + ["BaseLookup"])
                    + (f"  {own.group(1)} own columns" if own else "") + f"  bindings: {', '.join(bindings) if bindings else 'none'}  used by {users}")
    out = [f"{len(rows)} lookups in {', '.join(p.name for p in pkgs)}"] + cut(rows, limit, offset=offset, paged=True)
    if unknown:
        out.append(f"  not decided ({len(unknown)}; parent outside the workspace and the stock list):")
        out.extend(cut([f"    {item}" for item in unknown], limit, offset=offset, paged=True))
    return "\n".join(ws.stale + out + _unreadable_line(indexes))


def find_schema(path: Path | str, name: str, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """Where a schema lives and what touches it: package, kind, files (absolute), what it refers to, who refers to it, its data bindings."""
    cut([], limit, offset=offset)
    ws = Indexed(path)
    pkgs, indexes = ws.pkgs, ws.indexes
    key = name.lower()
    out = []
    # a plain C# file answers to its path, its file name or its stem
    own = [(f, n, json.loads(e)) for f, n, e in ws.rows("select package, name, entry from nodes where {pkgs} and kind != 'data' "
                                                         "and (name = :n collate nocase or kind = 'csharp') order by name", n=name)]
    for folder, n, e in own:
        if n.lower() != key and key not in (Path(n).name.lower(), Path(n).stem.lower()):
            continue
        if "error" in e:  # the one asked for is broken: say so in one line, list nothing of it
            out.append(f"{n}  cannot read, in {ws.name[folder]}: {e['error']}")
            continue
        out.append(f"{n}  {e['kind']} in {ws.name[folder]}  ({ws.dir[folder]})")
        parent = e.get("parent")
        out.append(f"  {e['summary']}" + (f"; caption {e['caption']!r}" if e["caption"] else "") + (f"; builds on {parent}" if parent and parent not in e["summary"] else "") + (f"; {e['error']}" if "error" in e else ""))
        resources = e.get("resources")
        if resources is not None:
            out.append(f"  resources: {', '.join(resources['cultures'])}; {resources['keys']} keys; missing: "
                       + (", ".join(f"{c}={count}" for c, count in resources["missing"].items()) or "none"))
        bindings = [f"Data/{dn} ({rows} rows, {other})" for other, dn, rows in ws.bindings(n)]
        if bindings:
            shown = cut(bindings, limit, offset=offset, paged=True)
            tail = shown.pop() if limit and len(shown) > limit else None
            out.append("  bindings: " + ", ".join(shown))
            if tail:
                out.append(tail)
        out.append("  files:")
        out += _file_lines(ws.dir[folder], e["files"])
        typed = [Edge.from_dict(d).line() for d in e.get("deps", [])]
        if typed:
            shown = cut(typed, limit, offset=offset, paged=True)
            tail = shown.pop() if limit and len(shown) > limit else None
            out.append("  depends on: " + "; ".join(shown))
            if tail:
                out.append(tail)
        dependents = sorted(f"{fk} {fn}{'' if other == folder else ', ' + other} ({ed.via})" for other, fk, fn, ed in ws.dependents(n))
        if dependents:
            shown = cut(dependents, limit, offset=offset, paged=True)
            tail = shown.pop() if limit and len(shown) > limit else None
            out.append("  dependents: " + "; ".join(shown))
            if tail:
                out.append(tail)
        if e.get("refs"):
            refs = cut(e["refs"], limit, offset=offset, paged=True)
            tail = refs.pop() if len(refs) > limit and limit else None
            out.append(f"  refers to: {', '.join(refs)}")
            if tail:
                out.append(tail)
        users = [f"{un} ({uk}{'' if other == folder else ', ' + other})" for other, uk, un in ws.referrers(n)]
        limited_users = cut(users, limit, offset=offset, paged=True)
        tail = limited_users.pop() if len(limited_users) > limit and limit else None
        out.append(f"  used by: {', '.join(limited_users)}" if users else "  used by: nothing in the workspace")
        if tail:
            out.append(tail)
    from .site import schema_hits

    out += schema_hits(ws.query, name) if ws.db else []  # S31-T11: a schema the last `index --env` pass found on the site only
    if not out:
        out = [f"no schema named {name} in {', '.join(p.name for p in pkgs)}"]
    return "\n".join(ws.stale + out + _unreadable_line(indexes))


FIND_TEXT_WIDTH = 160


def find_text(path: Path | str, pattern: str, kind: str = "", context: int = 0, limit: int = DEFAULT_LIMIT) -> str:
    """A regex over the lines of every file the index knows: `<Package>/<Item> (<kind>) <line>: <text>`, `context` lines
    around each hit (`<line>- <text>`). Resource XML and binary files are skipped unless `kind="resource"`, which reads
    resource XML only; another `kind` keeps the items of that kind. The file list is the store's `files`, the text is
    read from disk. shortcut: every listed file is read, fine for 500 schemas; an FTS table of the lines when a
    workspace makes it slow."""
    from .core import QueryError
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise QueryError(f"not a regex: {pattern} ({exc})") from exc
    if context < 0:
        raise QueryError("context must be a non-negative integer")
    cut([], limit)
    ws = Indexed(path)
    pkgs, indexes = ws.pkgs, ws.indexes
    hits, items, matched = [], set(), 0
    files = ws.rows("select f.package, f.node, n.kind, f.path from files f join nodes n on n.package = f.package and n.name = f.node "
                    "where f.{pkgs} and (:kind in ('', 'resource') or n.kind = :kind) and (f.path like 'Resources/%') = (:kind = 'resource') "
                    "order by n.kind = 'data', f.node, f.rowid", kind=kind)
    for folder, name, item_kind, rel in files:
        pname, package = ws.name[folder], ws.dir[folder]
        try:
            raw = (package / rel).read_bytes()
            if b"\0" in raw[:8000]:
                continue  # binary
            lines = read_text(package / rel)[0].splitlines()
        except UNREADABLE:
            continue
        shown = -1
        for i, text in enumerate(lines):
            if not rx.search(text):
                continue
            items.add((pname, name))
            matched += 1
            for j in range(max(i - context, shown + 1), min(i + context, len(lines) - 1) + 1):
                mark = ":" if j == i or rx.search(lines[j]) else "-"
                hits.append(f"{pname}/{name} ({item_kind}) {j + 1}{mark} {lines[j].strip()[:FIND_TEXT_WIDTH]}")
                shown = j
    if not hits:
        return "\n".join(ws.stale + [f"no line matches /{pattern}/ in {', '.join(p.name for p in pkgs)}"] + _unreadable_line(indexes))
    head = f"{matched} lines match /{pattern}/ in {len(items)} items"
    return "\n".join(ws.stale + [head] + cut(hits, limit) + _unreadable_line(indexes))
