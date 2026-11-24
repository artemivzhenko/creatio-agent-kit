"""Freedom UI pages (client unit schemas) as package files.

The page body `Schemas/<Page>/<Page>.js` holds JSON between marker comments
(`/**SCHEMA_VIEW_CONFIG_DIFF*/[...]/**SCHEMA_VIEW_CONFIG_DIFF*/`). Those sections are parsed,
edited as data and rendered back in the file's own indentation; everything else in the body
(handlers with JavaScript in them, the define() wrapper) is kept as text. A section that was not
changed is not re-rendered, so an untouched page saves to the bytes it was read from.

Two body forms exist on 8.2.3 and both are handled: a designer-saved page has `viewModelConfig`
and `modelConfig` objects; a page clio created from a template has `viewModelConfigDiff` and
`modelConfigDiff` arrays of merge operations.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from ..files import dump_json, new_uid, newline_of, read_text, write_text
from ..resources import Resources
from ..schema import WARNING, Schema

JSON_SECTIONS = ("SCHEMA_VIEW_CONFIG_DIFF", "SCHEMA_VIEW_MODEL_CONFIG", "SCHEMA_VIEW_MODEL_CONFIG_DIFF",
                 "SCHEMA_MODEL_CONFIG", "SCHEMA_MODEL_CONFIG_DIFF")

# keys of a mobile page body (plain JSON) -> the section they correspond to
MOBILE_KEYS = {"viewConfigDiff": "SCHEMA_VIEW_CONFIG_DIFF", "viewModelConfig": "SCHEMA_VIEW_MODEL_CONFIG",
               "viewModelConfigDiff": "SCHEMA_VIEW_MODEL_CONFIG_DIFF", "modelConfig": "SCHEMA_MODEL_CONFIG",
               "modelConfigDiff": "SCHEMA_MODEL_CONFIG_DIFF"}

# column type -> (component type, extra values), what the 8.2.3 designer emits for a bound field
CONTROL_OF = {
    "ShortText": ("crt.Input", {}), "MediumText": ("crt.Input", {}), "LongText": ("crt.Input", {}),
    "MaxSizeText": ("crt.Input", {}), "Text": ("crt.Input", {}),
    "Integer": ("crt.NumberInput", {}), "Float": ("crt.NumberInput", {}), "Float1": ("crt.NumberInput", {}),
    "Float2": ("crt.NumberInput", {}), "Float3": ("crt.NumberInput", {}), "Float4": ("crt.NumberInput", {}),
    "Float8": ("crt.NumberInput", {}), "Money": ("crt.NumberInput", {}),
    "Boolean": ("crt.Checkbox", {}),
    "Date": ("crt.DateTimePicker", {"pickerType": "date"}),
    "DateTime": ("crt.DateTimePicker", {"pickerType": "datetime"}),
    "Time": ("crt.DateTimePicker", {"pickerType": "time"}),
    "Lookup": ("crt.ComboBox", {}),
    "RichText": ("crt.RichTextEditor", {}),
    "PhoneText": ("crt.PhoneInput", {}), "EmailText": ("crt.EmailInput", {}), "WebText": ("crt.WebInput", {}),
}

# DataValueType codes a grid column carries; the ones not listed render as text (1)
DVT_CODE = {"Guid": 0, "Text": 1, "Integer": 4, "Float": 5, "Money": 6, "DateTime": 7, "Date": 8, "Time": 9,
            "Lookup": 10, "Boolean": 12, "ShortText": 28, "MediumText": 29, "MaxSizeText": 30, "LongText": 31}

# template -> (asset, parent UId, parent name) of the empty pages clio's create-page writes on 8.2.3
PAGE_TEMPLATES = {"form": ("FormPage", "3b2e117f-8c6b-4ca5-80a2-7ebb497cddf9", "PageWithTabsFreedomTemplate"),
                  "list": ("ListPage", "3334b6c0-c8ab-4b59-a367-0c9182102552", "ListPageV2Template")}

DEFAULT_FIELD_PARENT = "SideAreaProfileContainer"
DEFAULT_GRID_PARENT = "GeneralInfoTabContainer"


def strip_comments(text: str) -> str:
    """JavaScript comments removed from a JSON section - a commented-out block of elements is valid JS and the designer
    keeps it, json.loads does not; string contents are kept as they are."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


class _Section:
    def __init__(self, name: str, inner: str):
        self.name = name
        self.inner = inner
        # JavaScript tolerates comments and a trailing comma in an array or object; json.loads does not
        self.value = json.loads(re.sub(r",(\s*[\]}])", r"\1", strip_comments(inner)))
        self.original = copy.deepcopy(self.value)

    @property
    def changed(self) -> bool:
        return self.value != self.original

    def style(self) -> tuple[str, str] | None:
        """(base indent of the closing bracket, one indent step) of a multi-line section; None when it is one line."""
        lines = self.inner.split("\n")
        if len(lines) < 3:
            return None
        second, last = lines[1], lines[-1]
        base = last[: len(last) - len(last.lstrip())]
        step = second[: len(second) - len(second.lstrip())]
        return base, step[len(base):] or "\t"


class PageSchema(Schema):
    """One Freedom UI page: Schemas/<Page>/<Page>.js edited through its JSON sections."""

    RESOURCE_SUFFIX = "ClientUnit"

    def __init__(self, package: Path, name: str):
        super().__init__(package, name)
        self.culture = "en-US"  # the culture a caption is read in (the index sets the package's primary one)
        self._entity_captions: dict[str, dict[str, str]] = {}
        self.body_path = self.dir / f"{name}.js"
        if not self.body_path.is_file():
            raise FileNotFoundError(f"{self.body_path} is missing: {name} is not a client unit schema")
        self.body, self.body_bom = read_text(self.body_path)
        self.body_newline = newline_of(self.body)
        self.sections: dict[str, _Section] = {}
        for sec in JSON_SECTIONS:
            m = re.search(rf"/\*\*{sec}\*/(.*?)/\*\*{sec}\*/", self.body, re.S)
            if m:
                self.sections[sec] = _Section(sec, m.group(1))
        # A mobile page body is one JSON object with the same keys and no define() wrapper: readable
        # through the same sections, but not written back (its formatting is not reproduced).
        self.mobile = not self.sections and self.body.lstrip().startswith("{")
        if self.mobile:
            data = json.loads(self.body)
            for key, sec in MOBILE_KEYS.items():
                if key in data:
                    self.sections[sec] = _Section(sec, json.dumps(data[key], indent="\t", ensure_ascii=False))

    # metadata.json is kept as it is: the body is where a page lives
    def load_metadata(self, text: str) -> None:
        self._metadata = text

    def render_metadata(self) -> str:
        return self._metadata

    # -- the two body forms ---------------------------------------------------- #

    def section(self, name: str) -> _Section:
        if name not in self.sections:
            raise KeyError(f"{self.name} has no {name} section")
        return self.sections[name]

    @property
    def view_config_diff(self) -> list:
        return self.section("SCHEMA_VIEW_CONFIG_DIFF").value

    @staticmethod
    def _merge_values(ops: list, path: list, create: bool) -> dict:
        for op in ops:
            if op.get("operation") == "merge" and op.get("path") == path:
                return op.setdefault("values", {}) if create else op.get("values", {})
        if not create:
            return {}
        op = {"operation": "merge", "path": path, "values": {}}
        ops.append(op)
        return op["values"]

    @staticmethod
    def _merged_tree(ops: list, key: str) -> dict:
        """Read view of a *Diff array: every merge op whose path starts at `key`, folded into one dict.

        The designer writes `path: ["dataSources"]`, `["dataSources", "PDS", "config"]` or
        `["attributes", "X"]` as it pleases; a reader wants the resulting tree.
        """
        tree: dict = {}
        for op in ops:
            if op.get("operation") != "merge":
                continue
            path = op.get("path") or []
            values = op.get("values") or {}
            if not path:
                # a root merge may carry the whole subtree: {"dataSources": {...}}
                values = values.get(key) if isinstance(values.get(key), dict) else None
                if values is None:
                    continue
            elif path[0] != key:
                continue
            node = tree
            for seg in path[1:]:
                node = node.setdefault(seg, {})
            for k, v in values.items():
                if isinstance(v, dict) and isinstance(node.get(k), dict):
                    node[k] = {**node[k], **v}
                else:
                    node[k] = v
        return tree

    def _part(self, key: str, obj_section: str, diff_section: str, create: bool) -> dict:
        """attributes / dataSources in whichever form the body has; reading never creates anything."""
        if obj_section in self.sections:
            value = self.sections[obj_section].value
            return value.setdefault(key, {}) if create else value.get(key, {})
        ops = self.section(diff_section).value
        return self._merge_values(ops, [key], True) if create else self._merged_tree(ops, key)

    @property
    def attributes(self) -> dict:
        """The view model attributes (a copy-safe read: write through attributes_w())."""
        return self._part("attributes", "SCHEMA_VIEW_MODEL_CONFIG", "SCHEMA_VIEW_MODEL_CONFIG_DIFF", False)

    def _attr_path(self, key) -> str:
        """The `modelConfig.path` of an attribute, '' when it has none or is not a dict (a designer may store a list)."""
        attr = self.attributes.get(key) if isinstance(key, str) else None
        return ((attr.get("modelConfig") or {}).get("path") or "") if isinstance(attr, dict) else ""

    def attributes_w(self) -> dict:
        return self._part("attributes", "SCHEMA_VIEW_MODEL_CONFIG", "SCHEMA_VIEW_MODEL_CONFIG_DIFF", True)

    @property
    def data_sources(self) -> dict:
        return self._part("dataSources", "SCHEMA_MODEL_CONFIG", "SCHEMA_MODEL_CONFIG_DIFF", False)

    def data_sources_w(self) -> dict:
        return self._part("dataSources", "SCHEMA_MODEL_CONFIG", "SCHEMA_MODEL_CONFIG_DIFF", True)

    @property
    def primary(self) -> str:
        """Name of the primary data source: `primaryDataSourceName` where the body states it, else PDS,
        else the one data source of page scope (designer-made pages name it after the object)."""
        if "SCHEMA_MODEL_CONFIG" in self.sections:
            named = self.sections["SCHEMA_MODEL_CONFIG"].value.get("primaryDataSourceName")
        else:
            named = next((op.get("values", {}).get("primaryDataSourceName") for op in self.section("SCHEMA_MODEL_CONFIG_DIFF").value
                          if op.get("operation") == "merge" and not op.get("path") and "primaryDataSourceName" in (op.get("values") or {})), None)
        if named:
            return named
        sources = self.data_sources
        if "PDS" in sources:
            return "PDS"
        return next((k for k, v in sources.items() if v.get("scope") == "page"), "PDS")

    @property
    def entity(self) -> str | None:
        """The object of the page's primary data source."""
        return ((self.data_sources.get(self.primary) or {}).get("config") or {}).get("entitySchemaName")

    # -- reading ---------------------------------------------------------------- #

    RAW_SECTIONS = ("SCHEMA_DEPS", "SCHEMA_ARGS", "SCHEMA_VIEW_CONFIG_DIFF", "SCHEMA_VIEW_MODEL_CONFIG",
                    "SCHEMA_VIEW_MODEL_CONFIG_DIFF", "SCHEMA_MODEL_CONFIG", "SCHEMA_MODEL_CONFIG_DIFF",
                    "SCHEMA_HANDLERS", "SCHEMA_CONVERTERS", "SCHEMA_VALIDATORS")

    def raw_sections(self) -> dict[str, str]:
        """Every marker section's text, JSON or JavaScript alike, in the order the body has them."""
        out = {}
        for sec in self.RAW_SECTIONS:
            m = re.search(rf"/\*\*{sec}\*/(.*?)/\*\*{sec}\*/", self.body, re.S)
            if m:
                out[sec] = m.group(1)
        return out

    def handlers(self) -> list[tuple[str, str]]:
        """(request name, source) of each handler: the top-level objects of the handlers array, split by brace matching."""
        text = self.raw_sections().get("SCHEMA_HANDLERS", "")
        items, depth, start, in_str, quote, i = [], 0, None, False, "", 0
        while i < len(text):
            ch = text[i]
            if in_str:
                if ch == "\\":
                    i += 1
                elif ch == quote:
                    in_str = False
            elif text.startswith("//", i):  # a comment may hold an apostrophe or a brace; skip it whole
                i = text.find("\n", i)
                if i < 0:
                    break
            elif text.startswith("/*", i):
                i = text.find("*/", i + 2)
                if i < 0:
                    break
                i += 1
            elif ch in "\"'`":
                in_str, quote = True, ch
            elif ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    items.append(text[start:i + 1])
                    start = None
            i += 1
        out = []
        for src in items:
            m = re.search(r"request\s*:\s*[\"']([^\"']+)[\"']", src)
            out.append((m.group(1) if m else f"handler#{len(out) + 1}", src.strip()))
        return out

    def elements(self) -> list[dict]:
        return [op for op in self.view_config_diff if op.get("name")]

    def element(self, name: str) -> dict:
        for op in self.elements():
            if op["name"] == name:
                return op
        raise KeyError(f"{self.name} has no element {name}")

    def has(self, name: str) -> bool:
        return any(op["name"] == name for op in self.elements())

    def _siblings(self, parent: str) -> list[dict]:
        return [op for op in self.elements() if op.get("parentName") == parent]

    def _next_row(self, parent: str) -> int:
        rows = [op["values"]["layoutConfig"].get("row", 0) for op in self._siblings(parent)
                if isinstance(op.get("values", {}).get("layoutConfig"), dict)]
        return max(rows, default=0) + 1

    def column_type(self, column: str) -> tuple[str, str | None]:
        if not self.entity:
            raise KeyError(f"{self.name} has no PDS data source, so its columns are unknown")
        columns = self.workspace.columns(self.entity)
        if column not in columns:
            raise KeyError(f"{self.entity} has no column {column}; it has: {', '.join(sorted(columns))}")
        return columns[column]

    # -- writing ---------------------------------------------------------------- #

    def add_field(self, column: str, parent: str = DEFAULT_FIELD_PARENT, row: int | None = None,
                  col: int = 1, span: int = 1) -> dict:
        """A bound field of the primary object: the viewConfigDiff insert and the PDS attribute."""
        if self.has(column):
            raise KeyError(f"{self.name} already has an element {column}")
        kind, _ = self.column_type(column)
        if kind not in CONTROL_OF:
            raise ValueError(f"no Freedom UI control for a {kind} column ({column})")
        control, extra = CONTROL_OF[kind]
        op = {
            "operation": "insert",
            "name": column,
            "values": {
                "layoutConfig": {"column": col, "row": row or self._next_row(parent), "colSpan": span, "rowSpan": 1},
                "type": control,
                "label": f"$Resources.Strings.{column}",
                "control": f"${column}",
                "labelPosition": "auto",
                **extra,
            },
            "parentName": parent,
            "propertyName": "items",
            "index": len(self._siblings(parent)),
        }
        self.view_config_diff.append(op)
        self.attributes_w()[column] = {"modelConfig": {"path": f"{self.primary}.{column}"}}
        return op

    def add_grid(self, name: str, entity: str, columns: list[str], parent: str = DEFAULT_GRID_PARENT,
                 rows: int = 6, editable: bool = False) -> dict:
        """A list of another object's records: the grid, its collection attribute and its data source."""
        if self.has(name):
            raise KeyError(f"{self.name} already has an element {name}")
        known = self.workspace.columns(entity)
        missing = [c for c in columns if c not in known]
        if missing:
            raise KeyError(f"{entity} has no column {', '.join(missing)}")
        ds = f"{name}DS"
        captions = self._captions_of(entity)
        op = {
            "operation": "insert",
            "name": name,
            "values": {
                "type": "crt.DataGrid",
                "columns": [{"id": new_uid(), "code": f"{ds}_{c}", "caption": captions.get(c, c),
                             "dataValueType": DVT_CODE.get(known[c][0], 1), "width": 200} for c in columns],
                "items": f"${name}",
                "primaryColumnName": f"{ds}_Id",
                "layoutConfig": {"column": 1, "row": self._next_row(parent), "colSpan": 2, "rowSpan": rows},
                "features": {"editable": {"enable": editable}, "rows": {"selection": {"enable": True, "multiple": True}}},
                "visible": True,
            },
            "parentName": parent,
            "propertyName": "items",
            "index": len(self._siblings(parent)),
        }
        self.view_config_diff.append(op)
        self.attributes_w()[name] = {
            "isCollection": True,
            "modelConfig": {"path": ds, "sortingConfig": {"default": [{"columnName": columns[0], "direction": "asc"}]}},
            "viewModelConfig": {"attributes": {**{f"{ds}_{c}": {"modelConfig": {"path": f"{ds}.{c}"}} for c in columns},
                                               f"{ds}_Id": {"modelConfig": {"path": f"{ds}.Id"}}}},
        }
        self.data_sources_w()[ds] = {
            "type": "crt.EntityDataSource",
            "scope": "viewElement",
            "config": {"entitySchemaName": entity, "attributes": {c: {"path": c} for c in columns}},
        }
        return op

    # -- resource strings as element values (#ResourceString(Key)#) ---------------- #

    RESOURCE_REF = re.compile(r"#ResourceString\(([A-Za-z_][\w.]*)\)#")

    def own_string_keys(self) -> set[str]:
        """The `A2` names of the `+ MetaData.Schema.B2 {...}` entries this page adds (strings it owns; inherited ones are `=` lines)."""
        return set(re.findall(r'(?m)^\+ MetaData\.Schema\.B2 \{.*?"A2":\s*"([^"]+)"', self._metadata, re.S))

    def resource_refs(self) -> set[str]:
        """Every Key named by a `#ResourceString(Key)#` in the page body."""
        return set(self.RESOURCE_REF.findall(self.body))

    def ensure_resource_string(self, key: str, text: str | None = None, culture: str | None = None) -> bool:
        """Both halves of a page string: the `B2` entry (with its UId in the `~ B2` order line) and
        `LocalizableStrings.<Key>.Value` in one culture - `culture`, else en-US, else the first the page has. The page's other cultures
        get no key, so `resources missing` lists them. Returns False when the string was there already."""
        nl = "\r\n" if "\r\n" in self._metadata else "\n"
        resource_key = f"LocalizableStrings.{key}.Value"
        culture = culture or ("en-US" if "en-US" in self.resources.cultures or not self.resources.cultures else sorted(self.resources.cultures)[0])
        changed = False
        if key not in self.own_string_keys():
            uid_m = re.search(r'(?m)^= MetaData\.Schema\.UId "([^"]+)"', self._metadata)
            a5_m = re.search(r'(?m)^= MetaData\.Schema\.A5 "([^"]+)"', self._metadata)
            order_m = re.search(r"(?m)^~ MetaData\.Schema\.B2 (\[[^\]\r\n]*\])", self._metadata)
            if not (uid_m and a5_m and order_m):
                raise KeyError(f"{self.name} metadata has no UId, A5 or `~ MetaData.Schema.B2` order line to extend")
            uid = new_uid()
            entry = json.dumps({"UId": uid, "A2": key, "A3": uid_m.group(1), "A4": uid_m.group(1), "A5": a5_m.group(1)}, indent=2)
            block = "+ MetaData.Schema.B2 " + entry.replace("\n", nl) + nl
            order = json.loads(order_m.group(1))
            text_ = self._metadata[:order_m.start(1)] + json.dumps([uid] + order, separators=(",", ":")) + self._metadata[order_m.end(1):]
            anchor = re.search(r"(?m)^[=-] MetaData\.Schema\.B2\.\[", text_) or re.search(r"(?m)^~ MetaData\.Schema\.B2 \[", text_)
            self._metadata = text_[:anchor.start()] + block + text_[anchor.start():]
            changed = True
        if self.resources.get(resource_key, culture) is None:
            if text is None:
                raise ValueError(f"{key} has no text in {culture}: give one (--text)")
            self.resources.set(resource_key, text, [culture])
            changed = True
        return changed

    def set_value(self, element: str, prop: str, value, text: str | None = None, culture: str | None = None) -> None:
        """Set one property of an element's `values`; a `#ResourceString(Key)#` value gets its string written with it."""
        values = self.element(element).setdefault("values", {})
        values[prop] = value
        if isinstance(value, str):
            for key in self.RESOURCE_REF.findall(value):
                self.ensure_resource_string(key, text, culture)

    def remove(self, name: str) -> None:
        """Drop an element and what add_field / add_grid created for it."""
        op = self.element(name)
        self.view_config_diff.remove(op)
        attr = self.attributes_w().pop(name, None)
        if isinstance(attr, dict) and attr.get("isCollection"):
            self.data_sources_w().pop(attr["modelConfig"]["path"], None)

    def _captions_of(self, entity: str) -> dict[str, str]:
        if entity in self._entity_captions:
            return self._entity_captions[entity]
        out = {}
        for hit in self.workspace.find(entity, "EntitySchemaManager"):
            res = Resources(hit["dir"].parent.parent / "Resources" / f"{entity}.Entity")
            for key in res.ordered_keys(self.culture):
                if key.startswith("Columns.") and key.endswith(".Caption"):
                    out.setdefault(key[len("Columns."):-len(".Caption")], res.get(key, self.culture) or "")
        self._entity_captions[entity] = out
        return out

    # -- checks, text ----------------------------------------------------------- #

    def validate(self) -> list[str]:
        problems = []
        seen = set()
        columns = self.workspace.columns(self.entity) if self.entity else {}
        for op in self.elements():
            if op["name"] in seen:
                problems.append(f"element {op['name']} is defined twice")
            seen.add(op["name"])
            control = (op.get("values") or {}).get("control", "")
            if control.startswith("$") and control[1:] not in self.attributes:
                problems.append(f"{op['name']} is bound to {control} but the page has no such attribute")
        own = self.own_string_keys()  # a ref with neither half is the platform's or the parent's string (a grid column caption): not judged
        defined = {k for c in self.resources.cultures.values() for k in c}
        for key in sorted(self.resource_refs()):
            has_string = f"LocalizableStrings.{key}.Value" in defined
            if has_string and key not in own:
                problems.append(f"#ResourceString({key})# has a string but no B2 entry in the page metadata: the page shows the key (`pages.py set-value` writes both)")
            elif key in own and not has_string:
                problems.append(f"#ResourceString({key})# has a B2 entry but no LocalizableStrings.{key}.Value in any culture")
        prefix = self.primary + "."
        for name in self.attributes:
            path = self._attr_path(name)
            if path.startswith(prefix) and columns and path[len(prefix):] not in columns:
                problems.append(f"{WARNING}attribute {name} reads {path}, which {self.entity} does not have")
        return problems

    GROUPS = 8  # containers named in the summary; the rest is a count

    def _by_container(self) -> list[tuple[str, int, str]]:
        """[(container, elements in it, "46 ComboBox, 31 Input, ...")] biggest first: the elements counted per parent and per type."""
        groups: dict[str, dict[str, int]] = {}
        for op in self.elements():
            kinds = groups.setdefault(op.get("parentName") or "(no parent)", {})
            kind = str((op.get("values") or {}).get("type") or "?").removeprefix("crt.")
            kinds[kind] = kinds.get(kind, 0) + 1
        out = []
        for name, kinds in groups.items():
            top = sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))
            more = ", ..." if len(top) > 4 else ""
            out.append((name, sum(kinds.values()), ", ".join(f"{n} {k}" for k, n in top[:4]) + more))
        return sorted(out, key=lambda g: (-g[1], g[0]))

    def _rule_summary(self) -> str | None:
        """`10 in UsrPage_FormPageBusinessRule (2 disabled)` for the page's rule schema, None without one."""
        from ..rules import RuleSchema
        name = RuleSchema.name_for(self.package, self.name)
        if not (self.package / "Schemas" / name / "properties.json").is_file():
            return None
        rules = RuleSchema(self.package, name).rules
        off = sum(1 for r in rules if not r.get("BR4", True))
        return f"{len(rules)} in {name}" + (f" ({off} disabled)" if off else "")

    def _count_raw(self, section: str) -> int:
        return len(re.findall(r"(?m)^\s{0,6}[\"']?[\w.]+[\"']?\s*:\s*(?:function|\{|\()", self.raw_sections().get(section, "")))

    def describe(self) -> str:
        """The summary of a page: counts, never the element list (`elements` is the topic for that)."""
        form = "designer form (viewModelConfig)" if "SCHEMA_VIEW_MODEL_CONFIG" in self.sections else "template form (viewModelConfigDiff)"
        groups = self._by_container()
        tabs = sum(1 for g in groups if g[0].endswith("TabContainer"))
        lines = [f"{self.name}: page of {self.entity or '?'}, {form}, {len(self.elements())} elements" + (f", {tabs} tab{'' if tabs == 1 else 's'}" if tabs else "")]
        for name, count, kinds in groups[:self.GROUPS]:
            label = f"tab {name[:-len('TabContainer')]}" if name.endswith("TabContainer") and name != "TabContainer" else name
            lines.append(f"  {label}: {count} element{'' if count == 1 else 's'} ({kinds})")
        if len(groups) > self.GROUPS:
            lines.append(f"  ... {len(groups) - self.GROUPS} more containers ({sum(g[1] for g in groups[self.GROUPS:])} elements)")
        attrs = self.attributes
        sources = []
        for k, v in self.data_sources.items():
            entity = (v.get("config") or {}).get("entitySchemaName")
            n = sum(1 for a in attrs if self._attr_path(a).split(".")[0] == k)
            sources.append(f"{k} ({entity}" + (f", {n} attribute{'' if n == 1 else 's'}" if n else "") + ")")
        lines.append(f"  attributes: {len(attrs)}; data sources: " + (", ".join(sources) or "-"))
        handlers = self.handlers()
        lines.append("  handlers: " + (", ".join(f"{name} ({len(src)} chars)" for name, src in handlers[:8]) + (f", ... {len(handlers) - 8} more" if len(handlers) > 8 else "") if handlers else "none"))
        rules = self._rule_summary()
        lines.append(f"  rules: {rules or 'none'}; validators: {self._count_raw('SCHEMA_VALIDATORS')}, converters: {self._count_raw('SCHEMA_CONVERTERS')}")
        lines.append("  ask describe_item: elements [type= parent=], element <name>, attributes, attribute <name>, data-sources, handlers, handler <name>, validators, converters")
        for p in self.validate():
            lines.append(f"  ! {p}")
        return "\n".join(lines)

    # -- the UI test utility's page file ----------------------------------------- #

    def _text(self, value) -> str | None:
        """A caption or label as the page shows it: a literal, a page string, or the caption of the bound column; None when unknown."""
        if not isinstance(value, str):
            return None
        m = re.fullmatch(r"#ResourceString\((\w+)\)#", value) or re.fullmatch(r"\$Resources\.Strings\.(\w+)", value)
        if not m:
            return None if value.startswith("$") else value
        key = m.group(1)
        text = self.resources.get(f"LocalizableStrings.{key}.Value", self.culture)
        if text is not None:
            return text
        # not a page string: an attribute (PDS_Name -> PDS.Name) or <DataSource>_<Column>, shown with the column's caption
        path = self._attr_path(key) or key.replace("_", ".", 1)
        ds, _, column = path.partition(".")
        entity = ((self.data_sources.get(ds) or {}).get("config") or {}).get("entitySchemaName")
        return self._captions_of(entity).get(column) if entity and column else None

    def _bound_type(self, values: dict) -> str | None:
        """The type name of the column a control is bound to (`control: "$Attr"` -> PDS.Column), when the workspace knows it."""
        control = values.get("control")
        path = self._attr_path(control[1:]) if isinstance(control, str) and control.startswith("$") else ""
        ds, _, column = path.partition(".")
        entity = ((self.data_sources.get(ds) or {}).get("config") or {}).get("entitySchemaName")
        return self.workspace.columns(entity).get(column, (None,))[0] if entity and column else None

    def rule_toggled(self) -> set[str]:
        """Element names a business rule of this page shows or hides (the `show` / `hide` actions of `<Page>BusinessRule`)."""
        from ..rules import RuleSchema  # local: the rules kit reads page models, this module is read by it
        name = RuleSchema.name_for(self.package, self.name)
        if not (self.package / "Schemas" / name / "properties.json").is_file():
            return set()
        from ..rules.actions import ACTION_BY_CLASS
        names: set[str] = set()
        for rule in RuleSchema(self.package, name).rules:
            for case in rule["BR1"]:
                for action in case["BRC2"]:
                    if getattr(ACTION_BY_CLASS.get(action["JI0"]), "name", None) in ("show", "hide"):
                        names.update(n for n in action.get("BRA4", "").split(",") if n)
        return names

    def page_file(self, name: str | None = None, culture: str | None = None) -> tuple[dict, list[str]]:
        """The UI test utility's page file for this page (Configuration/pages/<name>.json) and notes on what was left out.
        An element a business rule shows or hides carries `"conditional": true` (it may be absent from the DOM). Labels are read in
        `culture` (default: the one set on the page, en-US)."""
        if culture:
            self.culture = culture
            self._entity_captions = {}
        from .catalog import FRAMEWORK_TYPE, PICKER_TYPE, TEMPLATE_ELEMENTS
        toggled = self.rule_toggled()
        parent = (self.descriptor.data.get("Parent") or {}).get("Name")
        entries = {e["code"]: copy.deepcopy(e) for e in TEMPLATE_ELEMENTS.get(parent, [])}
        unknown: dict[str, list[str]] = {}
        hidden, unlabelled = [], []
        for op in self.view_config_diff:
            code, values, operation = op.get("name"), op.get("values") or {}, op.get("operation")
            if not code or operation == "move":
                continue
            if operation == "remove":
                entries.pop(code, None)
                continue
            if values.get("visible") is False and code not in toggled:  # a rule may show it: the catalog lists what the page can show
                entries.pop(code, None)
                hidden.append(code)
                continue
            if operation == "merge" and code in entries:
                text = self._text(values.get("caption", values.get("label")))
                if text is not None:
                    entries[code]["label"] = text
                continue
            kind = values.get("type")
            if kind not in FRAMEWORK_TYPE:
                if kind:
                    unknown.setdefault(kind, []).append(code)
                continue
            ftype = FRAMEWORK_TYPE[kind]
            if kind == "crt.NumberInput":
                ftype = "Integer" if self._bound_type(values) == "Integer" else "Decimal"
            elif kind == "crt.DateTimePicker":
                column = self._bound_type(values)
                ftype = PICKER_TYPE.get(values.get("pickerType")) or (column if column in ("Date", "Time", "DateTime") else "DateTime")
            raw = values.get("caption", values.get("label"))
            label = "" if raw is None and kind == "crt.DataGrid" else self._text(raw)
            if label is None:
                unlabelled.append(code)
                label = ""
            entry = {"code": code, "label": label, "type": ftype}
            if kind == "crt.DataGrid":
                entry["columns"] = [self._text(c.get("caption")) or "" for c in values.get("columns", [])]
            entries[code] = entry
        for code in toggled & entries.keys():
            entries[code]["conditional"] = True
        page = {"name": name or (self.name[:-len("_FormPage")] + "Form" if self.name.endswith("_FormPage") else self.name),
                "url": f"/0/Shell/#Card/{self.name}", "type": "FreedomUI",
                "elements": sorted(entries.values(), key=lambda e: (e["type"], e["code"]))}
        notes = [f"not written ({kind}): {', '.join(codes)}" for kind, codes in sorted(unknown.items())]
        if hidden:
            notes.append(f"hidden by the page (visible: false): {', '.join(hidden)}")
        if unlabelled:
            notes.append(f"label unknown, written empty (a page string or a column outside the workspace): {', '.join(unlabelled)}")
        if parent not in TEMPLATE_ELEMENTS:
            notes.append(f"the elements of the parent {parent} are not known here: describe the page with analyse for its buttons and tabs")
        return page, notes

    # -- a new page -------------------------------------------------------------------- #

    @classmethod
    def create(cls, package: Path, name: str, entity: str, template: str = "form", caption: str = "",
               cultures: list[str] | None = None, version: str = "8.2.3.1351") -> "PageSchema":
        """An empty form page (PageWithTabsFreedomTemplate) or list page (ListPageV2Template) of `entity`, byte for byte what
        clio's create-page writes (assets/new_FormPage.*, new_ListPage.*); fields go on with add_field."""
        from ..schema import Descriptor
        from ..workspace import Package
        if template not in PAGE_TEMPLATES:
            raise ValueError(f"template must be one of {sorted(PAGE_TEMPLATES)}")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            raise ValueError(f"{name!r} is not a valid schema name")
        package = Path(package)
        sdir = package / "Schemas" / name
        if sdir.exists():
            raise FileExistsError(sdir)
        asset, parent_uid, parent = PAGE_TEMPLATES[template]
        pkg, uid = Package(package), new_uid()
        values = {"@NAME@": name, "@ENTITY@": entity, "@UID@": uid, "@CREATED_IN@": pkg.created_in_uid(), "@PACKAGE@": pkg.uid}

        def fill(text: str) -> str:
            for k, v in values.items():
                text = text.replace(k, v)
            return text
        assets = Path(__file__).resolve().parent / "assets"
        write_text(sdir / f"{name}.js", fill(read_text(assets / f"new_{asset}.js")[0]), False)
        write_text(sdir / "metadata.json", fill(read_text(assets / f"new_{asset}.metadata.json")[0]), False)
        desc = Descriptor.new(sdir / "descriptor.json", {"UId": uid, "Name": name, "ModifiedOnUtc": "", "Parent": {"UId": parent_uid, "Name": parent},
                                                          "ManagerName": "ClientUnitSchemaManager", "Caption": caption or name, "DependsOn": []})
        write_text(desc.path, desc.text, True)
        write_text(sdir / "properties.json", dump_json({"Properties": {"CreatedInVersion": version, "Group": "Page", "SchemaType": "AngularSchema"}}), True)
        page = cls(package, name)
        known = sorted({p.name[len("resource."):-len(".xml")] for p in package.glob("Resources/*/resource.*.xml")})
        page.resources = Resources.empty(page.resources.folder, cultures or known or ["en-US"])
        page.resources.set("Caption", caption or name)  # clio writes the caption to every culture
        page.save()
        return page

    def render_body(self) -> str:
        if getattr(self, "mobile", False):
            if any(s.changed for s in self.sections.values()):
                raise NotImplementedError(f"{self.name} is a mobile page: readable here, but its body is not written back")
            return self.body
        text = self.body
        fallback = next((s.style() for s in self.sections.values() if s.style()), ("\t\t", "\t"))
        for sec in self.sections.values():
            if not sec.changed:
                continue
            base, step = sec.style() or fallback
            rendered = json.dumps(sec.value, indent=step, ensure_ascii=False).replace("\n", self.body_newline + base)
            marker = f"/**{sec.name}*/"
            text = re.sub(re.escape(marker) + r".*?" + re.escape(marker), lambda m: marker + rendered + marker, text, count=1, flags=re.S)
        return text

    def files(self) -> dict[Path, tuple[str, bool]]:
        out = super().files()
        out[self.body_path] = (self.render_body(), self.body_bom)
        return out


def compare_page_files(expected: dict, actual: dict) -> list[str]:
    """What differs between two page files: elements only in one, and type, label or column differences of the shared ones."""
    a = {e["code"]: e for e in actual.get("elements", [])}
    b = {e["code"]: e for e in expected.get("elements", [])}
    lines = [f"only in the schema: {code} ({a[code]['type']})" for code in sorted(set(a) - set(b))]
    lines += [f"only in the file: {code} ({b[code]['type']})" for code in sorted(set(b) - set(a))]
    for code in sorted(set(a) & set(b)):
        for key in ("type", "label", "columns", "tabs"):
            if a[code].get(key) != b[code].get(key) and (key in a[code] or key in b[code]):
                lines.append(f"{key} of {code}: schema {a[code].get(key)!r}, file {b[code].get(key)!r}")
    return lines
