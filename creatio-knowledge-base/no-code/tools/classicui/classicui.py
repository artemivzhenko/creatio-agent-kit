#!/usr/bin/env python3
"""Classic UI (7.x) client schemas stored in a package: read and write (library: ../creatio_schemas/classicui).

    python classicui.py inspect  <package> <Schema>
    python classicui.py validate <package> <Schema>
    python classicui.py methods  <package> <Schema>
    python classicui.py method   <package> <Schema> <name>
    python classicui.py diff     <package> <Schema> [--op insert] [--parent Header]
    python classicui.py layout   <package> <Schema> [--container Header] [-e env]
    python classicui.py rules    <package> <Schema> [--rule <UId>] [-e env]
    python classicui.py diff add <package> <Schema> --op insert|merge|remove|move --name X [--parent Header] [--bind-to X]
                                 [--row 1 --col 0 --col-span 12] [--index N] [--values key=value ..]   [--dry-run]

    python classicui.py new         <package> <Schema> --parent BaseGridDetailV2|BasePageV2|<Name> [--entity UsrOrder] [--caption ..] [-e env]

    python classicui.py replace     <package> <Schema> [--parent-uid U | -e env] [--entity Contact] [--caption ..] [--cultures en-US,ru-RU]
    python classicui.py adopt       <package> <Schema> --from <pulled package or schema folder>
    python classicui.py add-string  <package> <Schema> <Key> en-US="Text" [ru-RU="..."] [-e env] [--dry-run]
    python classicui.py set-rule    <package> <Schema> <RuleUId> [--enabled false] [--removed true] [--column Owner]
    python classicui.py add-mixin   <package> <Schema> <Name> [--class Terrasoft.<Name>] [--module <Name>]
    python classicui.py add-method  <package> <Schema> <name> --file method.js [--replace]
    python classicui.py set-message <package> <Schema> <Name> --mode PTP|BROADCAST --direction SUBSCRIBE|PUBLISH|BIDIRECTIONAL

An edit page, section or detail of the 7.x designer: `define("Name", [deps], function(...) { return {...} })`
with entitySchemaName, attributes, messages, mixins, details, diff (insert / merge / remove / move), methods,
rules. `inspect` gives the header, the sections with their sizes and the diff's elements; `validate` warns about
parentNames and handler methods this file cannot prove (they usually come from the platform's parent schema).
Freedom UI pages are read by ../pages.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from creatio_schemas.classicui import ClassicSchema  # noqa: E402
from creatio_schemas.classicui.write import DIFF_OPS  # noqa: E402
from creatio_schemas.cli import CommandLine, parse_assignments  # noqa: E402
from creatio_schemas.environment import open_environment  # noqa: E402
from creatio_schemas import jscheck  # noqa: E402
from creatio_schemas.platform_version import stamp  # noqa: E402
from creatio_schemas.files import read_text  # noqa: E402

CREATE = {"replace", "adopt", "new"}
OVER_LAYERS = {"layout", "rules"}  # read every copy in the workspace (and the site's): the package names the workspace only


def env_of(a):
    return open_environment(a.env) if a.env else None


def validate(s, a):
    problems = s.validate()
    print("\n".join(problems) if problems else "ok")
    js = jscheck.lines(s.body_path)
    print("\n".join(js))
    return 1 if s.errors() or any(x.startswith("js syntax: ERROR") for x in js) else 0


def methods(s, a):
    for m in s.methods():
        print(f"{m['name']:<40} line {m['line']:<6} {m['size']} lines")


def diff(s, a):
    for op in s.diff_operations():
        if (a.op and op["operation"] != a.op) or (a.parent and op["parentName"] != a.parent):
            continue
        where = f" in {op['parentName']}.{op['propertyName']}" if op["parentName"] else ""
        index = f"[{op['index']}]" if op["index"] is not None else ""
        print(f"{op['operation'] or '?':<7} {op['name'] or '(no name)'}{where}{index}  line {op['line']}  values: {', '.join(op['values']) or '-'}")


def layout(_, a):
    from creatio_schemas.classicui.layout import layout_lines
    print("\n".join(layout_lines(Path(a.package), a.schema, a.container, env_of(a))))


def rules(_, a):
    from creatio_schemas.classicui.layout import rule_lines
    print("\n".join(rule_lines(Path(a.package), a.schema, env_of(a), a.rule)))


def diff_add(s, a):
    values = {}
    for k, v in parse_assignments(a.values or []).items():
        try:
            values[k] = json.loads(v)
        except ValueError:
            values[k] = v  # plain text
    if a.bind_to:
        values["bindTo"] = a.bind_to
    if a.row is not None or a.col is not None:
        values["layout"] = {"colSpan": a.col_span, "rowSpan": a.row_span, "column": a.col or 0, "row": a.row or 0}
    print(s.add_diff(a.op, a.name, a.parent, a.property, a.index, values))


def files_of(s) -> None:
    for path in sorted(s.files()):
        print(f"  {path.relative_to(s.package).as_posix()}")


def replace(_, a):
    s = ClassicSchema.create_replacing(Path(a.package), a.schema, a.cultures.split(",") if a.cultures else None, a.parent_uid,
                                       a.caption, a.entity or "", env=env_of(a), **stamp(a.version, a.project))
    print(f"created {s.name} replacing {s.parent} ({s.descriptor.data['Parent']['UId']}):")
    files_of(s)


def new(_, a):
    s = ClassicSchema.create_new(Path(a.package), a.schema, a.parent, a.entity or "", a.caption, a.cultures.split(",") if a.cultures else None,
                                 a.parent_uid, env_of(a), **stamp(a.version, a.project))
    print(f"created {s.name} ({s.kind}) with parent {s.parent} ({s.descriptor.data['Parent']['UId']}):")
    files_of(s)


def adopt(_, a):
    s = ClassicSchema.adopt(Path(a.package), a.schema, Path(a.source))
    print(f"adopted {s.name} into {s.package.name} as {s.descriptor.data['UId']}:")
    files_of(s)
    diff = s.diff_against_parent()
    print(diff if diff else f"(the body of {s.parent} is not in the workspace: no diff against the parent)")


def add_string(s, a):
    values = parse_assignments(a.values) if all("=" in v for v in a.values) else None
    if not values:
        raise ValueError("expected culture=value, e.g. en-US=\"Print\"")
    print(s.add_string(a.key, values, env_of(a)))


def flag(text: str | None) -> bool | None:
    if text is None:
        return None
    if text.lower() not in ("true", "false"):
        raise ValueError(f"expected true or false, got {text!r}")
    return text.lower() == "true"


def add_method(s, a):
    source = read_text(Path(a.file))[0]
    (s.replace_method if a.replace else s.add_method)(a.name, source)


def build() -> CommandLine:
    c = CommandLine(__doc__, "schema")
    c.command("inspect", lambda s, a: print(s.describe()), "kind, object, parent, sections with sizes, diff elements, warnings")
    c.command("validate", validate, "warnings; exit code 1 on a JavaScript syntax error")
    c.command("methods", methods, "one line per method: name, line, size")
    p = c.command("method", lambda s, a: print(s.method(a.name)), "one method's source")
    p.add_argument("name")
    p = c.command("diff", diff, "one line per diff operation")
    p.add_argument("--op", choices=["insert", "merge", "remove", "move"])
    p.add_argument("--parent", help="only operations under this parentName")
    p = c.command("layout", layout, "a container's grid over every layer (site copies with -e): the element in each cell, free cells")
    p.add_argument("--container", default="Header")
    p.add_argument("-e", "--env", help="clio environment: the site's copies too, each body read from the site")
    p = c.command("rules", rules, "every business rule over the layers: column, UId, kind, state, conditions, filter, layers")
    p.add_argument("--rule", help="one rule by its UId or key")
    p.add_argument("-e", "--env", help="clio environment: the site's copies too, each body read from the site")
    p = c.command("diff-add", diff_add, "`diff add`: append an operation to diff (CRLF, BOM and indent kept); prints it", writes=True)
    p.add_argument("--op", required=True, choices=DIFF_OPS)
    p.add_argument("--name", required=True)
    p.add_argument("--parent", help="parentName (insert, move, merge)")
    p.add_argument("--property", default="items", help="propertyName (default items)")
    p.add_argument("--bind-to")
    p.add_argument("--row", type=int)
    p.add_argument("--col", type=int)
    p.add_argument("--col-span", type=int, default=12)
    p.add_argument("--row-span", type=int, default=1)
    p.add_argument("--index", type=int)
    p.add_argument("--values", nargs="*", metavar="key=value", help="more values; a JSON value is parsed (false, 3, {...}), else text")

    p = c.command("new", new, "a new client schema with a parent: descriptor, diff metadata, properties, empty body, resources")
    p.add_argument("--parent", required=True, help="BaseGridDetailV2, BasePageV2, BaseModulePageV2 or any client schema")
    p.add_argument("--parent-uid", help="the parent's UId when neither the workspace nor the built-in list has it")
    p.add_argument("-e", "--env", help="clio environment: the parent's UId from its SysSchema row")
    p.add_argument("--entity", help="entitySchemaName of the body")
    p.add_argument("--caption")
    p.add_argument("--cultures", help="comma-separated; default the package's")
    p.add_argument("--version", help="CreatedInVersion / B8 (default: the project's platformVersion, else 8.2.3.1351)")
    p.add_argument("--project", help="project.json: its environment.platformVersion is the version written")

    p = c.command("replace", replace, "a replacing schema of a client schema: descriptor, diff metadata, empty body, resources")
    p.add_argument("--parent-uid", help="the parent's UId when the workspace does not hold it")
    p.add_argument("-e", "--env", help="clio environment: the parent's UId from its SysSchema row")
    p.add_argument("--entity", help="entitySchemaName of the new body (default: the parent's)")
    p.add_argument("--caption")
    p.add_argument("--cultures", help="comma-separated; default the package's")
    p.add_argument("--version", help="CreatedInVersion / B8 (default: the project's platformVersion, else 8.2.3.1351)")
    p.add_argument("--project", help="project.json: its environment.platformVersion is the version written")
    p = c.command("adopt", adopt, "move a client schema pulled from another package into this one (new UId, A5, B6)")
    p.add_argument("--from", dest="source", required=True, help="the pulled package folder or the schema folder")
    p = c.command("add-string", add_string, "a localizable string: B2 metadata + resources; a key of the parent chain is overridden", writes=True)
    p.add_argument("key")
    p.add_argument("values", nargs="+", metavar="culture=value")
    p.add_argument("-e", "--env", help="clio environment: look for the key in the parent chain's SysSchema.MetaData too")
    p = c.command("set-rule", lambda s, a: s.set_rule(a.uid, flag(a.enabled), flag(a.removed), a.column),
                  "override a business rule by UId in businessRules (enabled / removed)", writes=True)
    p.add_argument("uid")
    p.add_argument("--enabled", metavar="true|false")
    p.add_argument("--removed", metavar="true|false")
    p.add_argument("--column", help="the rule's column when no workspace parent has the rule")
    p = c.command("add-mixin", lambda s, a: s.add_mixin(a.name, a.cls, a.module), "a mixin in mixins + its module in define()", writes=True)
    p.add_argument("name")
    p.add_argument("--class", dest="cls", help="default Terrasoft.<name>")
    p.add_argument("--module", help="the module schema to depend on; default <name>")
    p = c.command("add-method", add_method, "a method from a file (`function(...) {...}`); --replace for an existing one", writes=True)
    p.add_argument("name")
    p.add_argument("--file", required=True)
    p.add_argument("--replace", action="store_true")
    p = c.command("set-message", lambda s, a: s.set_message(a.name, a.mode, a.direction), "a message: mode and direction", writes=True)
    p.add_argument("name")
    p.add_argument("--mode", required=True)
    p.add_argument("--direction", required=True)
    return c


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:2] == ["diff", "add"]:
        argv = ["diff-add", *argv[2:]]
    return build().run(argv,
                       lambda a: None if a.command in CREATE | OVER_LAYERS else ClassicSchema(Path(a.package), a.schema))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
