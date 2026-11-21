"""S33-T02: three questions over the workspace's text, answered without grep over `metadata.json`.

    find_in_processes(path, pattern)  - the decoded text of every process: script lines, flow conditions, element filters (a lookup
                                        GUID shown with its caption when the index has it), set values, parameters
    who_sets(path, "Entity.Column [= value]") - the places that write a column: process steps and scripts, C# (Files/cs, source
                                        schemas), client pages, SQL scripts
    who_reads_message(path, "sender") - the publishers (`PostMessage*` naming the sender) and subscribers (`ServerChannel` handlers
                                        with a `Header.Sender` check naming it)

`<Package> / <Process> / <Element> [<type>] / <where>: <text>`; case-blind, a regex when the pattern parses as one. Read-only.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..files import read_text
from ..process import ProcessSchema, short_type
from ..process.schema import RECORD_VALUES, USER_TASK_BY_UID
from .core import DEFAULT_LIMIT, QueryError, cut
from .index import packages_of

UNREADABLE = (OSError, ValueError, KeyError)


def _processes(package: Path):
    for sdir in sorted((package / "Schemas").glob("*")) if (package / "Schemas").is_dir() else []:
        try:
            desc = json.loads(read_text(sdir / "descriptor.json")[0])["Descriptor"]
        except UNREADABLE:
            continue
        if desc.get("ManagerName") == "ProcessSchemaManager":
            yield sdir.name


def process_units(ps: ProcessSchema):
    """(element, type, where, text) for every piece of text a process holds."""
    for p in ps.params:
        if p.get("L8"):
            yield "(parameter)", "Parameter", p["A2"], ps.workspace.captioned(ps.describe_value(p["L8"]))
    by_uid = {e["UId"]: e["A2"] for e in ps.elements}
    for e in ps.nodes():
        cls = short_type(e)
        kind = USER_TASK_BY_UID.get(e.get("J6"), e.get("J6", "?")) if cls == "ProcessSchemaUserTask" else cls.replace("ProcessSchema", "")
        values_param = (RECORD_VALUES.get(e.get("J6")) or ("",))[0]
        for p in ps.element_params(e) if cls != "ProcessSchemaSubProcess" else []:
            if not p.get("L8"):
                continue
            if p["A2"] == values_param and (p["L8"] or {}).get("GS2"):
                try:
                    for col, val in ps.record_values(e):
                        yield e["A2"], kind, "set value", f"{col} = {ps.workspace.captioned(val)}"
                    continue
                except (ValueError, KeyError):
                    pass
            if p["A2"] == "DataSourceFilters":
                try:
                    yield e["A2"], kind, "filter", ps.describe_filter(e) or ""
                except (ValueError, KeyError, TypeError):
                    pass
                continue
            yield e["A2"], kind, f"parameter {p['A2']}", ps.workspace.captioned(ps.describe_value(p["L8"]))
        if cls == "ProcessSchemaScriptTask":
            for n, line in enumerate((e.get("CH1") or "").splitlines(), 1):
                yield e["A2"], kind, f"script line {n}", line.strip()
        if cls == "ProcessSchemaFormulaTask" and e.get("CH1"):
            yield e["A2"], kind, "formula", ps.expressions.decode(e["CH1"])
    for f in ps.flows():
        if f.get("CI3") not in (None, "null", ""):
            yield f["A2"], "Flow", f"condition {by_uid.get(f.get('CI1'), '?')} -> {by_uid.get(f.get('CI2'), '?')}", ps.expressions.decode(f["CI3"])


_ROW_NAMES: dict = {}  # per call: the lookup row names of the workspace, read once and shared by every process opened in it


def _open(package: Path, name: str) -> ProcessSchema:
    ps = ProcessSchema(package, name)
    ps.workspace._rows = _ROW_NAMES.setdefault(str(package.parent), ps.workspace.lookup_rows())
    return ps


def _regex(pattern: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.I)
    except re.error:
        return re.compile(re.escape(pattern), re.I)


def find_in_processes(path: Path | str, pattern: str, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    _ROW_NAMES.clear()
    if not pattern.strip():
        raise QueryError("give the text or regex to look for")
    rx, hits = _regex(pattern), []
    for package in packages_of(path):
        for name in _processes(package):
            try:
                ps = _open(package, name)
                for element, kind, where, text in process_units(ps):
                    if rx.search(text) or rx.search(element):
                        hits.append(f"{package.name} / {name} / {element} [{kind}] / {where}: {text[:200]}")
            except Exception as exc:  # one unreadable process costs its own lines
                if rx.search(name):
                    hits.append(f"{package.name} / {name} (unreadable: {exc})")
    return "\n".join(cut(hits, limit, offset=offset)) if hits else f"no process text matches /{pattern}/"


# -- who sets a column ----------------------------------------------------------------- #

def _files(package: Path, kinds: tuple[str, ...]):
    for sub, exts in (("Files", (".cs",)), ("Schemas", (".cs", ".js")), ("SqlScripts", (".sql",)), ("Data", ())):
        base = package / sub
        for root, _, names in os.walk(base) if base.is_dir() else []:
            for n in sorted(names):
                ext = Path(n).suffix.lower()
                if ext in exts and (ext, sub) in kinds:
                    yield Path(root) / n


def _lines(path: Path) -> list[str]:
    try:
        return read_text(path)[0].splitlines()
    except UNREADABLE:
        return []


def who_sets(path: Path | str, target: str, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    _ROW_NAMES.clear()
    m = re.fullmatch(r"\s*(\w+)\.(\w+)\s*(?:=\s*(.+?))?\s*", target or "")
    if not m:
        raise QueryError('give "<Entity>.<Column>" or "<Entity>.<Column> = <value>"')
    entity, column, value = m.groups()
    word_col, word_ent = re.compile(rf"\b{re.escape(column)}\b"), re.compile(rf"\b{re.escape(entity)}\b")
    setter = re.compile(rf"(?:SetColumnValue|\.Set)\(\s*\"{re.escape(column)}\"|\[\"{re.escape(column)}\"\]\s*=(?!=)")
    hits = []
    for package in packages_of(path):
        for name in _processes(package):
            try:
                ps = _open(package, name)
                for e in ps.nodes():
                    cls = short_type(e)
                    if cls == "ProcessSchemaUserTask" and e.get("J6") in RECORD_VALUES:
                        try:
                            _, ent, _ = ps._record_target(e)
                            if ent == entity:
                                for col, val in ps.record_values(e):
                                    if col == column and (value is None or value.lower() in val.lower()):
                                        hits.append(f"process  {package.name} / {name} / {e['A2']} [{USER_TASK_BY_UID.get(e.get('J6'), '?')}]: {col} = {ps.workspace.captioned(val)}")
                        except (ValueError, KeyError):
                            pass
                    elif cls == "ProcessSchemaScriptTask":
                        for n, line in enumerate((e.get("CH1") or "").splitlines(), 1):
                            if setter.search(line) and (value is None or value.lower() in line.lower()):
                                hits.append(f"script   {package.name} / {name} / {e['A2']} line {n}: {line.strip()[:160]}")
            except Exception:
                continue
        for kind, label, pattern, entity_needed in (((".cs", "Files"), "C#", setter, True), ((".cs", "Schemas"), "C#", setter, True),
                                                    ((".js", "Schemas"), "client", re.compile(rf"this\.set\(\s*[\"']{re.escape(column)}[\"']|\$context\.{re.escape(column)}\s*=(?!=)|\[[\"']{re.escape(column)}[\"']\]\s*=(?!=)"), False),
                                                    ((".sql", "SqlScripts"), "sql", word_col, True)):
            for f in _files(package, (kind,)):
                lines = _lines(f)
                text = "\n".join(lines)
                if entity_needed and not word_ent.search(text):
                    continue
                if label == "sql" and not re.search(r"\b(update|insert)\b", text, re.I):
                    continue
                for n, line in enumerate(lines, 1):
                    if pattern.search(line) and (value is None or value.lower() in line.lower()):
                        hits.append(f"{label:<8} {package.name} / {f.relative_to(package).as_posix()}:{n}: {line.strip()[:160]}")
    return "\n".join(cut(hits, limit, offset=offset)) if hits else f"nothing sets {entity}.{column}" + (f" = {value}" if value else "") + " (processes, C#, pages, SQL scripts)"


# -- who reads a message ----------------------------------------------------------------- #

def who_reads_message(path: Path | str, sender: str, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    sender = (sender or "").strip().strip("\"'")
    if not sender:
        raise QueryError("give the message sender, as the code writes it")
    quoted = re.compile(rf"[\"']{re.escape(sender)}[\"']")
    publish = re.compile(r"PostMessage\w*\s*\(")
    subscribe = re.compile(r"ServerChannel\.on|Header\.Sender|\.Header\b.*Sender", re.I)
    hits = []
    for package in packages_of(path):
        for f in _files(package, ((".cs", "Files"), (".cs", "Schemas"), (".js", "Schemas"))):
            lines = _lines(f)
            rel = f"{package.name} / {f.relative_to(package).as_posix()}"
            has_sub = any(subscribe.search(x) for x in lines)
            for n, line in enumerate(lines, 1):
                if f.suffix == ".cs" and publish.search(line) and quoted.search(" ".join(lines[n - 1:n + 3])):
                    hits.append(f"publish   {rel}:{n}: {line.strip()[:160]}")
                elif has_sub and quoted.search(line) and not publish.search(line):
                    hits.append(f"subscribe {rel}:{n}: {line.strip()[:160]}")
    return "\n".join(cut(hits, limit, offset=offset)) if hits else f'no publisher or subscriber of the sender "{sender}"'
