"""Writers of a Classic UI client schema (mixed into ClassicSchema).

Body edits splice one span the reader found - a section of the returned object, a member of it, the
define() dependency list - and re-parse; every byte outside the span stays, and new text takes the body's
own newline and indent. Localizable strings go into the diff metadata (`+ MetaData.Schema.B2 {...}`) and
the resources. New schemas follow the shapes surveyed in real packages: a replacing schema in the diff
form, a module (and a mixin module) in the full form.
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
from pathlib import Path

from ..diff import SchemaDiff
from ..files import CRLF, dump_json, new_uid, read_text, write_text
from ..resources import Resources
from ..schema import Descriptor
from ..text import mask
from ..workspace import Package, Workspace

MANAGER = "ClientUnitSchemaManager"
MODULE_BASE_UID = "50e3acc0-26fc-4237-a095-849a1d534bd3"  # HD1 of every module and source code schema surveyed
MESSAGE_MODES = ("PTP", "BROADCAST")
MESSAGE_DIRECTIONS = ("SUBSCRIBE", "PUBLISH", "BIDIRECTIONAL")
_EMPTY = {"businessRules": "/**SCHEMA_BUSINESS_RULES*/{}/**SCHEMA_BUSINESS_RULES*/", "details": "/**SCHEMA_DETAILS*/{}/**SCHEMA_DETAILS*/",
          "diff": "/**SCHEMA_DIFF*/[]/**SCHEMA_DIFF*/"}
_QUOTED = {"businessRules", "messages", "details", "attributes"}  # sections whose member names the designer quotes
DIFF_OPS = ("insert", "merge", "remove", "move")
# UIds of the platform's base client schemas: the same row on every site (SysSchema, ExtendParent false; read on 8.3.2)
PLATFORM_PARENTS = {"BaseGridDetailV2": "01eb38ee-668a-42f0-999d-c2534f979089", "BasePageV2": "d3cc497c-f286-4f13-99c1-751c468733c0",
                    "BaseModulePageV2": "d62293c0-7f14-44b1-b547-735fb40499cd"}
_TYPES = ((("DetailV2", "Detail"), "GridDetailViewModelSchema"), (("SectionV2", "Section"), "ModuleViewModelSchema"),
          (("PageV2", "Page"), "EditViewModelSchema"))
# the B2 item of a string named {key} in the parent chain on the site (a replacing copy of a parent included)
_PARENT_STRING_SQL = """with recursive c as (
  select s."Id", s."ParentId" from "SysSchema" s where s."UId" = {uid} and s."ExtendParent" = false
  union all select p."Id", p."ParentId" from "SysSchema" p join c on p."Id" = c."ParentId")
select s."Name"::text "name", substring(convert_from(s."MetaData", 'UTF8') from {pattern}) "uid"
from c join "SysSchema" s on s."Id" = c."Id" or (s."ParentId" = c."Id" and s."ExtendParent")"""

REPLACING_BODY = """define("@NAME@", [], function() {
\treturn {
@ENTITY_LINE@\t\tattributes: {},
\t\tmessages: {},
\t\tmixins: {},
\t\tdetails: /**SCHEMA_DETAILS*/{}/**SCHEMA_DETAILS*/,
\t\tbusinessRules: /**SCHEMA_BUSINESS_RULES*/{}/**SCHEMA_BUSINESS_RULES*/,
\t\tmethods: {},
\t\tdiff: /**SCHEMA_DIFF*/[]/**SCHEMA_DIFF*/
\t};
});
"""

MODULE_BODY = """define("@NAME@", [], function() {
\treturn {};
});
"""

MIXIN_BODY = """define("@NAME@", ["@NAME@Resources"], function(resources) {
\t/**
\t * @class Terrasoft.configuration.mixins.@NAME@
\t * A page lists it in `mixins: {@NAME@: "Terrasoft.@NAME@"}` and adds "@NAME@" to its define() dependencies;
\t * the mixin's methods then run as the page's own (`this` is the page's view model).
\t */
\tExt.define("Terrasoft.configuration.mixins.@NAME@", {
\t\talternateClassName: "Terrasoft.@NAME@",

\t\t/**
\t\t * Called by the page as this.init@NAME@().
\t\t */
\t\tinit@NAME@: function() {
\t\t}
\t});
\treturn Ext.create("Terrasoft.@NAME@");
});
"""


def _pairs_close(masked: str, at: int) -> int:
    from .schema import _close
    return _close(masked, at)


def _members_of(schema, at):
    return {k: (ka, va, vb) for k, ka, va, vb in schema._members(at)}


def _key(name: str, quoted: bool) -> str:
    return json.dumps(name) if quoted or not re.fullmatch(r"[A-Za-z_$][\w$]*", name) else name


def _name_ok(name: str) -> None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
        raise ValueError(f"{name!r} is not a valid schema name")


def _sql_hint(name: str) -> str:
    return (f"python env/sql.py -e <env> \"select \\\"UId\\\" from \\\"SysSchema\\\" where \\\"Name\\\" = '{name}' "
            f"and \\\"ExtendParent\\\" = false\"")


def _parent_uid(package: Path, parent: str, parent_uid: str | None = None, env=None) -> str:
    """The parent's UId: given, a workspace copy in another package, the platform's base schemas, else the site's row."""
    if parent_uid:
        return parent_uid
    own = [s for s in Workspace(package).find(parent, MANAGER) if s["dir"].parent.parent != Path(package)]
    if own:
        return own[0]["base"]
    if parent in PLATFORM_PARENTS:
        return PLATFORM_PARENTS[parent]
    if env is None:
        raise ValueError(f"{parent} is not in the workspace: pass its UId (parent_uid / --parent-uid) or --env; {_sql_hint(parent)}")
    from ..records import quote
    rows = env.sql(f'select "UId"::text "uid" from "SysSchema" where "Name" = {quote(parent)} and "ExtendParent" = false '
                   f'and "ManagerName" = {quote(MANAGER)}')
    if not rows:
        raise ValueError(f"{parent} is not a client schema on the site")
    return rows[0]["uid"]


def _insert_b2_line(diff: SchemaDiff, line: list) -> None:
    """Before the `~ B2` order line when there is one, else after the UId/A2/A5/B2 lines (the designer's place)."""
    at = next((i for i, ln in enumerate(diff.lines) if ln[0] == "~" and ln[1] == "MetaData.Schema.B2"), None)
    if at is None:
        tops = [i for i, ln in enumerate(diff.lines) if ln[1].split(".")[2] in ("UId", "A2", "A5", "B2")]
        at = tops[-1] + 1 if tops else 0
    diff.lines.insert(at, line)


class ClassicWriter:
    """The writing half of ClassicSchema; relies on its body, masked, sections, _members, _parse."""

    # -- splicing ---------------------------------------------------------------- #

    @property
    def _nl(self) -> str:
        return "\r\n" if "\r\n" in self.body else "\n"

    @property
    def _unit(self) -> str:
        return "    " if re.search(r"^ {2,}\S", self.body, re.M) and not re.search(r"^\t", self.body, re.M) else "\t"

    def _indent_at(self, offset: int) -> str:
        start = self.body.rfind("\n", 0, offset) + 1
        return re.match(r"[ \t]*", self.body[start:]).group(0)

    def _reindent(self, text: str, indent: str) -> str:
        lines = text.replace("\r\n", "\n").split("\n")
        return (self._nl).join([lines[0]] + [(indent + ln) if ln.strip() else "" for ln in lines[1:]])

    def _splice(self, a: int, b: int, text: str) -> None:
        self.body = self.body[:a] + text + self.body[b:]
        self.masked = mask(self.body)
        self.sections, self._return_at, self._deps_at, self.dependencies = {}, None, None, []
        self._parse()

    def _put_member(self, obj_at: int, key: str, value: str) -> None:
        """Add `key: value` as the last member of the object literal whose "{" is at obj_at."""
        members = self._members(obj_at)
        if members:
            last = members[-1]
            indent = self._indent_at(last[1])
            self._splice(last[3], last[3], f",{self._nl}{indent}{key}: {self._reindent(value, indent)}")
            return
        close = _pairs_close(self.masked, obj_at) - 1
        outer = self._indent_at(obj_at)
        indent = outer + self._unit
        self._splice(obj_at + 1, close, f"{self._nl}{indent}{key}: {self._reindent(value, indent)}{self._nl}{outer}")

    def _set_member(self, obj_at: int, name: str, value: str, quoted: bool) -> None:
        """Replace the value of member `name` or add it."""
        hit = _members_of(self, obj_at).get(name)
        if hit:
            self._splice(hit[1], hit[2], self._reindent(value, self._indent_at(hit[0])))
        else:
            self._put_member(obj_at, _key(name, quoted), value)

    def _section(self, key: str) -> int:
        """The offset of a section's value, the section added empty when the schema lacks it."""
        if self._return_at is None:
            raise ValueError(f"{self.name}: no returned object literal to write into")
        if key not in self.sections:
            self._put_member(self._return_at, key, _EMPTY.get(key, "{}"))
        a = self.sections[key][0]
        if self.masked[a] not in "{[":
            raise ValueError(f"{self.name}: section {key} is not a literal")
        return a

    def _block(self, lines: list[str]) -> str:
        """{ <lines> } with the body's indent unit, relative to column 0 (the caller re-indents it)."""
        return "{\n" + "".join(f"{self._unit}{ln}{',' if i < len(lines) - 1 else ''}\n" for i, ln in enumerate(lines)) + "}"

    # -- body writers ------------------------------------------------------------------ #

    def _rule_at(self, uid: str):
        span = self.sections.get("businessRules")
        if not span or self.masked[span[0]] != "{":
            return None
        for column, (_, ca, _) in _members_of(self, span[0]).items():
            if self.masked[ca] != "{":
                continue
            for rule, (_, ra, _) in _members_of(self, ca).items():
                if rule.lower() == uid.lower() and self.masked[ra] == "{":
                    return column, ra
        return None

    def _inherited_rule(self, uid: str):
        """(column, rule source) of the rule in a workspace parent of this schema."""
        for anc in self._ancestors():
            hit = anc._rule_at(uid)
            if hit:
                return hit[0], anc.body[hit[1]:_pairs_close(anc.masked, hit[1])]
        return None

    def set_rule(self, uid: str, enabled: bool | None = None, removed: bool | None = None, column: str | None = None) -> None:
        """Override a business rule by UId in `businessRules`: `enabled` / `removed`. A rule only a parent has is
        copied in first (whole, from the workspace parent) or, when no parent here has it, written as {uId} under `column`."""
        if enabled is None and removed is None:
            raise ValueError("set_rule needs enabled and/or removed")
        if not self._rule_at(uid):
            inherited = self._inherited_rule(uid)
            col = column or (inherited[0] if inherited else None)
            if not col:
                raise ValueError(f"rule {uid} is neither in {self.name} nor in its workspace parents: name its column")
            br = self._section("businessRules")
            if col not in _members_of(self, br):
                self._put_member(br, json.dumps(col), "{}")
            col_at = _members_of(self, self._section("businessRules"))[col][1]
            source = inherited[1] if inherited else self._block([f'"uId": {json.dumps(uid)}'])
            if inherited:  # back to column 0: the parent's lines carry its indent, the closing brace's is the base
                first, *rest = source.replace("\r\n", "\n").split("\n")
                base = len(re.match(r"[ \t]*", rest[-1]).group(0)) if rest else 0
                source = "\n".join([first] + [ln[base:] for ln in rest])
            self._put_member(col_at, json.dumps(uid), source)
        for prop, value in (("enabled", enabled), ("removed", removed)):
            if value is not None:
                self._set_member(self._rule_at(uid)[1], prop, json.dumps(value), quoted=True)

    def add_mixin(self, name: str, cls: str | None = None, module: str | None = None) -> None:
        """`mixins: {name: "cls"}` (default Terrasoft.<name>) and the module (default <name>) in define()'s dependencies."""
        self._set_member(self._section("mixins"), name, json.dumps(cls or f"Terrasoft.{name}"), quoted=False)
        self.add_dependency(module or name)

    def add_dependency(self, module: str) -> None:
        if module in self.dependencies:
            return
        if self._deps_at is None:
            raise ValueError(f"{self.name}: define() has no dependency list")
        close = _pairs_close(self.masked, self._deps_at) - 1
        inner = self.body[self._deps_at + 1:close]
        self._splice(close, close, (", " if inner.strip() else "") + json.dumps(module))

    def _source_of(self, name: str, source: str) -> str:
        src = source.strip()
        m = re.match(rf"{re.escape(name)}\s*:\s*", src)
        return src[m.end():] if m else src

    def add_method(self, name: str, source: str) -> None:
        """A new member of `methods`: `function(...) {...}` (or `name: function...`)."""
        if any(m["name"] == name for m in self.methods()):
            raise KeyError(f"method {name} exists in {self.name}: use replace_method")
        self._put_member(self._section("methods"), name, self._source_of(name, source))

    def replace_method(self, name: str, source: str) -> None:
        for k, ka, vb in self._method_spans():
            if k == name:
                value_at = _members_of(self, self.sections["methods"][0])[name][1]
                self._splice(value_at, vb, self._reindent(self._source_of(name, source), self._indent_at(ka)))
                return
        raise KeyError(f"no method {name} in {self.name}; have {[k for k, _, _ in self._method_spans()]}")

    def set_message(self, name: str, mode: str, direction: str) -> None:
        mode, direction = mode.upper(), direction.upper()
        if mode not in MESSAGE_MODES or direction not in MESSAGE_DIRECTIONS:
            raise ValueError(f"mode is one of {MESSAGE_MODES}, direction one of {MESSAGE_DIRECTIONS}")
        self._set_member(self._section("messages"), name, self._block([f"mode: Terrasoft.MessageMode.{mode}",
                                                                       f"direction: Terrasoft.MessageDirectionType.{direction}"]), quoted=True)

    def add_diff(self, op: str, name: str, parent: str | None = None, prop: str = "items", index: int | None = None,
                 values: dict | None = None) -> str:
        """Append an operation to `diff` in the designer's key order (operation, name, values, parentName, propertyName,
        index); a `layout` value gets `layoutName` = parent. Returns the item as written."""
        if op not in DIFF_OPS:
            raise ValueError(f"op is one of {DIFF_OPS}")
        if not re.fullmatch(r"[A-Za-z_$][\w$]*", name):
            raise ValueError(f"{name!r} is not a valid element name")
        if op in ("insert", "move") and not parent:
            raise ValueError(f"{op} needs a parent (--parent Header)")
        if op == "remove" and (parent or values or index is not None):
            raise ValueError("remove takes only the name")
        if op == "insert" and any(o["operation"] == "insert" and o["name"] == name for o in self.diff_operations()):
            raise ValueError(f"{name} is inserted in {self.name} already: merge or move it")
        item: dict = {"operation": op, "name": name}
        values = dict(values or {})
        if isinstance(values.get("layout"), dict) and parent:
            values["layout"].setdefault("layoutName", parent)
        if values or op == "insert":
            item["values"] = values
        if parent:
            item.update(parentName=parent, propertyName=prop)
        if index is not None:
            item["index"] = index
        text = json.dumps(item, indent=self._unit, ensure_ascii=False)
        at = self._section("diff")
        if self.masked[at] != "[":
            raise ValueError(f"{self.name}: diff is not an array")
        ops = self.diff_operations()
        if ops:
            last = ops[-1]
            end, indent = last["at"] + len(last["source"]), self._indent_at(last["at"])
            self._splice(end, end, f",{self._nl}{indent}{self._reindent(text, indent)}")
        else:
            close, outer = _pairs_close(self.masked, at) - 1, self._indent_at(at)
            indent = outer + self._unit
            self._splice(at + 1, close, f"{self._nl}{indent}{self._reindent(text, indent)}{self._nl}{outer}")
        return text

    # -- metadata and resources -------------------------------------------------------- #

    def _diff(self) -> SchemaDiff:
        if not self.metadata_text.lstrip("﻿").startswith(("=", "+", "-", "~")):
            raise ValueError(f"{self.name}: metadata is not in the diff form; strings of a full-form schema are not written here")
        return SchemaDiff(self.metadata_text, CRLF)

    def _parent_string(self, key: str, env=None) -> tuple[str, str] | None:
        """(UId, where) of the string `key` in the parent chain: the workspace copies first, then the site's SysSchema.MetaData."""
        item = re.compile(r'\{[^{}]*"A2"\s*:\s*' + re.escape(json.dumps(key)) + r'\s*[,}][^{}]*')
        for anc in self._ancestors():
            for m in item.finditer(anc.metadata_text):
                uid = re.search(r'"UId"\s*:\s*"([0-9a-fA-F-]{36})"', m.group(0))
                if uid:
                    return uid.group(1), f"{anc.package.name}/{anc.name}"
        parent_uid = (self.descriptor.data.get("Parent") or {}).get("UId")
        if env is None or not parent_uid:
            return None
        from ..records import quote
        pattern = quote(r'"UId"\s*:\s*"([0-9a-fA-F-]{36})"\s*,\s*"A2"\s*:\s*' + json.dumps(key) + r'\s*[,}]')
        hit = next((r for r in env.sql(_PARENT_STRING_SQL.format(uid=quote(parent_uid), pattern=pattern)) if r.get("uid")), None)
        return (hit["uid"], f"{hit['name']} on the site") if hit else None

    def add_string(self, key: str, values: dict[str, str], env=None) -> str:
        """A localizable string: the B2 item in the diff metadata (once) and `LocalizableStrings.<key>.Value` per culture. A key
        the parent chain has (workspace copies, else `env`'s SysSchema.MetaData) is overridden: `= B2.["<its UId>"].A4 / .A5`."""
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"{key!r} is not a valid string name")
        if not values:
            raise ValueError("add_string needs at least one culture=value")
        diff = self._diff()
        uid = self.descriptor.data["UId"]
        a5 = diff.value("MetaData.Schema.A5") or Package(self.package).created_in_uid()
        if any(i.get("A2") == key for i in diff.added_items("MetaData.Schema.B2")):
            said = f"{key}: a string of {self.name} already"
        elif (inherited := self._parent_string(key, env)):
            path = f'MetaData.Schema.B2.["{inherited[0]}"]'
            for k, v in (("A4", uid), ("A5", a5)):
                if not diff.find(f"{path}.{k}"):
                    _insert_b2_line(diff, ["=", f"{path}.{k}", None, v])
            said = f"{key}: overrides the string {inherited[0]} of {inherited[1]} (= {path}.A4 / .A5)"
        else:
            item = {"UId": new_uid(), "A2": key, "A3": uid, "A4": uid, "A5": a5}
            if diff.find("MetaData.Schema.B2", "~"):
                diff.add_item("MetaData.Schema.B2", item)
            else:
                _insert_b2_line(diff, ["+", "MetaData.Schema.B2", None, item])
            said = f"{key}: a new string of {self.name} (+ MetaData.Schema.B2 {item['UId']})"
        if not said.endswith("already"):
            self.metadata_text = diff.render()
        for culture, value in values.items():
            self.resources.set(f"LocalizableStrings.{key}.Value", value, [culture])
        return said

    # -- new schemas ------------------------------------------------------------------- #

    @classmethod
    def create_replacing(cls, package: Path, parent_name: str, cultures: list[str] | None = None, parent_uid: str | None = None,
                         caption: str | None = None, entity: str = "", version: str = "8.2.3.1351", env=None):
        """A replacing schema of `parent_name` in `package`: descriptor (Parent, ExtendParent), the diff metadata, the
        designer's empty replacing body, resources with the caption. The parent's UId: see _parent_uid."""
        _name_ok(parent_name)
        package = Path(package)
        sdir = package / "Schemas" / parent_name
        if sdir.exists():
            raise FileExistsError(f"{sdir} exists")
        ws = Workspace(package)
        own = [s for s in ws.find(parent_name, MANAGER) if s["dir"].parent.parent != package]
        parent_uid = _parent_uid(package, parent_name, parent_uid, env)
        caption = caption or (own[0]["caption"] if own else parent_name)
        pkg, uid = Package(package), new_uid()
        meta = CRLF.join([f'= MetaData.Schema.UId "{uid}"', f'= MetaData.Schema.A5 "{pkg.created_in_uid()}"', f'= MetaData.Schema.B6 "{pkg.uid}"',
                          f'= MetaData.Schema.B8 "{version}"', "+ MetaData.Schema.B7 true", f'= MetaData.Schema.HD1 "{parent_uid}"'])
        write_text(sdir / "metadata.json", meta, False)
        entity_line = f"\t\tentitySchemaName: {json.dumps(entity)},\n" if entity else ""  # none named: the parent's object
        write_text(sdir / f"{parent_name}.js", REPLACING_BODY.replace("@NAME@", parent_name).replace("@ENTITY_LINE@", entity_line), False)
        desc = Descriptor.new(sdir / "descriptor.json", {"UId": uid, "Name": parent_name, "ModifiedOnUtc": "",
                                                         "Parent": {"UId": parent_uid, "Name": parent_name}, "ExtendParent": True,
                                                         "ManagerName": MANAGER, "Caption": caption, "DependsOn": []})
        write_text(desc.path, desc.text, True)
        write_text(sdir / "properties.json", dump_json({"Properties": {"CreatedInVersion": version}}), True)
        return cls._with_caption(package, parent_name, caption, cultures)

    @classmethod
    def create_new(cls, package: Path, name: str, parent: str, entity: str = "", caption: str | None = None, cultures: list[str] | None = None,
                   parent_uid: str | None = None, env=None, version: str = "8.2.3.1351"):
        """A new client schema with a parent (a grid detail, an edit page): descriptor `Parent`, the designer's diff metadata
        (UId, A2, A5, B6, B8, `- B7` / `+ B7 false`, HD1), SchemaType by the parent, the empty body, resources with the caption."""
        _name_ok(name)
        _name_ok(parent)
        package = Path(package)
        sdir = package / "Schemas" / name
        ws = Workspace(package)
        if sdir.exists() or ws.find(name, MANAGER):
            raise FileExistsError(f"client schema {name} exists in the workspace")
        parent_uid = _parent_uid(package, parent, parent_uid, env)
        props = next((s["dir"] / "properties.json" for s in ws.find(parent, MANAGER) if (s["dir"] / "properties.json").is_file()), None)
        schema_type = (json.loads(read_text(props)[0]).get("Properties", {}).get("SchemaType") if props else None) or \
            next((t for ends, t in _TYPES if parent.endswith(ends)), None)
        pkg, uid = Package(package), new_uid()
        meta = CRLF.join([f'= MetaData.Schema.UId "{uid}"', f'= MetaData.Schema.A2 "{name}"', f'= MetaData.Schema.A5 "{pkg.created_in_uid()}"',
                          f'= MetaData.Schema.B6 "{pkg.uid}"', f'= MetaData.Schema.B8 "{version}"', "- MetaData.Schema.B7",
                          "+ MetaData.Schema.B7 false", f'= MetaData.Schema.HD1 "{parent_uid}"'])
        write_text(sdir / "metadata.json", meta, False)
        entity_line = f"\t\tentitySchemaName: {json.dumps(entity)},\n" if entity else ""
        write_text(sdir / f"{name}.js", REPLACING_BODY.replace("@NAME@", name).replace("@ENTITY_LINE@", entity_line), False)
        desc = Descriptor.new(sdir / "descriptor.json", {"UId": uid, "Name": name, "ModifiedOnUtc": "", "Parent": {"UId": parent_uid, "Name": parent},
                                                         "ManagerName": MANAGER, "Caption": caption or name, "DependsOn": []})
        write_text(desc.path, desc.text, True)
        write_text(sdir / "properties.json", dump_json({"Properties": {"CreatedInVersion": version, **({"SchemaType": schema_type} if schema_type else {})}}), True)
        return cls._with_caption(package, name, caption or name, cultures)

    @classmethod
    def create_module(cls, package: Path, name: str, caption: str | None = None, mixin: bool = False, cultures: list[str] | None = None,
                      version: str = "8.2.3.1351"):
        """A client module (SchemaType Module, full metadata, the one-space .less the designer adds); with `mixin` the
        Ext.define mixin that a page lists in `mixins`."""
        _name_ok(name)
        package = Path(package)
        sdir = package / "Schemas" / name
        if sdir.exists() or Workspace(package).find(name, MANAGER):
            raise FileExistsError(f"client schema {name} exists in the workspace")
        pkg, uid = Package(package), new_uid()
        schema = {"ManagerName": MANAGER, "UId": uid, "A2": name, "A5": pkg.created_in_uid(), "B1": [], "B2": [], "B3": [], "B6": pkg.uid,
                  "B8": version, "HD1": MODULE_BASE_UID, "HD4": 1, "HD6": "null", "HD5": [], "HD7": [], "HD8": [], "HD11": []}
        write_text(sdir / "metadata.json", dump_json({"MetaData": {"Schema": schema}}), True)
        write_text(sdir / f"{name}.js", (MIXIN_BODY if mixin else MODULE_BODY).replace("@NAME@", name), False)
        write_text(sdir / f"{name}.less", " ", False)
        desc = Descriptor.new(sdir / "descriptor.json", {"UId": uid, "Name": name, "ModifiedOnUtc": "", "ManagerName": MANAGER,
                                                         "Caption": caption or name, "DependsOn": []})
        write_text(desc.path, desc.text, True)
        write_text(sdir / "properties.json", dump_json({"Properties": {"CreatedInVersion": version, "SchemaType": "Module"}}), True)
        return cls._with_caption(package, name, caption or name, cultures)

    @classmethod
    def _with_caption(cls, package: Path, name: str, caption: str, cultures: list[str] | None):
        s = cls(package, name)
        known = sorted({p.name[len("resource."):-len(".xml")] for p in package.glob("Resources/*/resource.*.xml")})
        s.resources = Resources.empty(s.resources.folder, cultures or known or ["en-US"])
        s.resources.set("Caption", caption)
        for path, (text, bom) in s.files().items():
            write_text(path, text, bom)
        return cls(package, name)

    @classmethod
    def adopt(cls, package: Path, name: str, source: Path):
        """A client schema pulled from another package (its folder, or that package's folder), moved into `package`:
        a new UId, `A5` and `B6` of the target in its metadata, descriptor and strings; resources copied."""
        package, source = Path(package), Path(source)
        src = source if (source / "descriptor.json").is_file() and (source / "metadata.json").is_file() else source / "Schemas" / name
        if not (src / "descriptor.json").is_file():
            raise FileNotFoundError(f"no schema {name} in {source}")
        target = package / "Schemas" / name
        if target.exists():
            raise FileExistsError(f"{target} exists")
        desc = json.loads(read_text(src / "descriptor.json")[0])["Descriptor"]
        if desc.get("ManagerName") != MANAGER:
            raise ValueError(f"{name} is a {desc.get('ManagerName')} schema; adopt takes client schemas")
        meta = read_text(src / "metadata.json")[0]
        diff = SchemaDiff(meta) if meta.lstrip("﻿").startswith(("=", "+", "-", "~")) else None
        full = None if diff else json.loads(meta)["MetaData"]["Schema"]
        old_a5 = diff.value("MetaData.Schema.A5") if diff else full.get("A5")
        old_b6 = diff.value("MetaData.Schema.B6") if diff else full.get("B6")
        pkg = Package(package)
        swap = {desc["UId"]: new_uid(), **({old_a5: pkg.created_in_uid()} if old_a5 else {}), **({old_b6: pkg.uid} if old_b6 else {})}
        shutil.copytree(src, target)
        for f in (target / "descriptor.json", target / "metadata.json"):
            text, bom = read_text(f)
            for old, new in swap.items():
                text = re.sub(re.escape(old), new, text, flags=re.I)
            write_text(f, text, bom)
        res = (src.parent.parent / "Resources" / f"{name}.ClientUnit")
        if res.is_dir():
            shutil.copytree(res, package / "Resources" / f"{name}.ClientUnit", dirs_exist_ok=True)
        s = cls(package, name)
        s.descriptor.touch()
        write_text(s.descriptor.path, s.descriptor.text, True)
        return cls(package, name)

    def diff_against_parent(self) -> str | None:
        """Unified diff of this body against the parent's body when a workspace package holds the parent; None otherwise."""
        for anc in self._ancestors():
            if anc.body:
                return "".join(difflib.unified_diff(anc.body.splitlines(True), self.body.splitlines(True),
                                                    f"{anc.package.name}/{anc.name}.js", f"{self.package.name}/{self.name}.js"))
        return None
