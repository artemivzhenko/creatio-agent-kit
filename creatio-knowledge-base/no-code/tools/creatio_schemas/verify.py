"""Is the site running the pushed code (S33-T05): every schema of a package against its row on the site, read-only.

    same                                  the site's bytes are the working copy's
    same (line endings)                   equal once CRLF / LF are swapped (a git checkout converted them)
    differs (<part>: site <md5> repo <md5>)   metadata (SysSchema.MetaData) or body (the largest SysSchemaContent: the .js / .cs)
    not on the site                       no SysSchema row of that name in the package
    not published: <why>                  a script process whose generated source is missing or older than its schema
    compile error: CS0103: ...            that generated source does not compile (push.compile_script, when the binaries are here)
    not served: <why>                     a client schema whose body the site does not serve at conf/content/<Schema>.js

Measured on the test site (2026-11-21): `md5(MetaData)` is the md5 of `metadata.json` as the repository holds it, and the largest
`SysSchemaContent` the md5 of the `.js` / `.cs` file, for every schema of a 30-schema package; the served `conf/content` file wraps
the body and holds it unchanged.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .push import SOURCES_SQL, _source_text, compile_script, creatio_bin, script_processes
from .records import quote

_DEFINE_RE = re.compile(r"define\(\s*'([^']*)'")

SITE_SQL = """select s."Name"::text "name", s."ManagerName"::text "manager", coalesce(md5(s."MetaData"), '')::text "meta",
  coalesce((select md5(sc."Content") from "SysSchemaContent" sc where sc."SysSchemaId" = s."Id"
    order by octet_length(sc."Content") desc limit 1), '')::text "content"
from "SysSchema" s join "SysPackage" p on p."Id" = s."SysPackageId" where p."Name" = {package}"""


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _compare(site: str, data: bytes) -> str | None:
    """None when equal, 'line endings' when equal after a CRLF/LF swap, else the repo md5."""
    if site == _md5(data):
        return None
    lf = data.replace(b"\r\n", b"\n")
    if site in (_md5(lf), _md5(lf.replace(b"\n", b"\r\n"))):
        return "line endings"
    return _md5(data)


def _normal(text: str) -> str:
    """LF, and the module name in double quotes: the site serves `define('X'` as `define("X"`."""
    return _DEFINE_RE.sub(r'define("\1"', text.replace("\r\n", "\n"))


def _body_file(folder: Path, name: str) -> Path | None:
    return next((p for p in (folder / f"{name}.js", folder / f"{name}.cs") if p.is_file()), None)


def served(env, name: str) -> str | None:
    """The text the site serves for a client schema (conf/content/<Schema>.js), None when it does not serve it."""
    env.login()  # a refused login raises, it is not "not served"
    try:
        r = env.fetch(f"conf/content/{name}.js")  # fetch puts `0/` before it on .NET Framework
    except RuntimeError:  # the site cannot be reached
        return None
    return r.text if r.ok else None


def members(body: str, name: str) -> list[str]:
    """The names a client layer adds, read by the layout readers: a Freedom page's `viewConfigDiff` operations (not the removes) and
    handler requests; a Classic schema's diff inserts, methods and rule UIds."""
    # shortcut: a member is a substring of its name in the composed text, so a name present elsewhere hides a missing
    # member; upgrade to a per-kind `"name": "<n>"` match when a false `served` verdict shows up (S48-T05)
    if "/**SCHEMA_VIEW_CONFIG_DIFF*/" in body:
        from .page.schema import PageSchema

        page = PageSchema.__new__(PageSchema)  # the reader over a text, as `classicui.methods.view` is for Classic
        page.body = body
        names = [op["name"] for op in PageSchema._ops_of(body) if op.get("name") and op.get("operation") != "remove"]
        return list(dict.fromkeys(names + [req for req, _ in page.handlers()]))
    from .classicui.layout import _tree
    from .classicui.methods import view

    c = view(body, name)
    names = [op["name"] for op in c.diff_operations() if op["name"] and op["operation"] != "remove"] + [m["name"] for m in c.methods()]
    for section in ("businessRules", "rules"):
        span = c.sections.get(section)
        for by_key in (_tree(c, *span) if span else {}).values():
            names += [str(p.get("uId") or k) for k, p in by_key.items() if isinstance(p, dict)] if isinstance(by_key, dict) else []
    return list(dict.fromkeys(names))


def _served_status(status: str, body: str, name: str, text: str | None) -> str:
    """`status` plus the served verdict: a composed body never holds a middle layer's whole text, so its own members are looked for."""
    if text is None:
        return "not served: conf/content has no such file"
    names = members(body, name)
    if not names:  # nothing to name (a bare module): the whole text, as before the composed bodies
        return status if _normal(body) in _normal(text) else "not served: conf/content holds another body (the site's client cache is older)"
    missing = [n for n in names if n not in text]
    if missing:
        return f"not served: {len(missing)} of {len(names)} members missing ({', '.join(missing[:3])})"
    return f"{status}, served ({len(names)} of {len(names)} members)"


def verify(package: Path, env, names: list[str] | None = None, bin_dir: Path | None = None, fetch=None) -> list[tuple[str, str]]:
    """(schema, status) per schema folder of the package (or of `names`), in name order."""
    package = Path(package)
    folders = sorted(d for d in (package / "Schemas").iterdir() if (d / "descriptor.json").is_file()) if (package / "Schemas").is_dir() else []
    if names:
        wanted = {n.lower() for n in names}
        unknown = sorted(wanted - {d.name.lower() for d in folders})
        if unknown:
            raise KeyError(f"no schema {', '.join(unknown)} in {package.name}")
        folders = [d for d in folders if d.name.lower() in wanted]
    from .workspace import Package

    sql, retried = SITE_SQL.format(package=quote(Package(package).name)), ""
    try:
        rows = env.sql(sql)
    except (RuntimeError, OSError) as e:  # right after a long push the site's SQL answers a timeout once
        if "timeout" not in str(e).lower() and "timed out" not in str(e).lower():
            raise
        rows, retried = env.sql(sql), " (sql retried once)"
    site = {r["name"]: r for r in rows}
    scripts = set(script_processes(package))
    out = []
    for d in folders:
        name, row = d.name, site.get(d.name)
        if row is None:
            out.append((name, "not on the site"))
            continue
        status = "same"
        parts = [("metadata", row["meta"], d / "metadata.json")]
        body = _body_file(d, name)
        if body is not None and row["content"]:
            parts.append(("body", row["content"], body))
        for part, site_md5, path in parts:
            got = _compare(site_md5, path.read_bytes()) if path.is_file() else _md5(b"")
            if got == "line endings":
                status = "same (line endings)"
            elif got is not None:
                status = f"differs ({part}: site {site_md5[:8]} repo {got[:8]})"
                break
        if status.startswith("same") and name in scripts:
            status = _process(package, env, name, bin_dir) or status
        if status.startswith("same") and row["manager"] == "ClientUnitSchemaManager" and body is not None:
            text = (fetch or served)(env, name)
            status = _served_status(status, body.read_text(encoding="utf-8-sig", errors="replace"), name, text)
        out.append((name, status + retried if status.startswith("same") else status))
    return out


def _process(package: Path, env, name: str, bin_dir: Path | None) -> str | None:
    """`not published: ...` / `compile error: ...` of a script process; None when its generated source is fresh and compiles."""
    import json
    import uuid

    from .files import read_text

    uid = str(uuid.UUID(json.loads(read_text(package / "descriptor.json")[0])["Descriptor"]["UId"]))
    rows = env.sql(SOURCES_SQL.format(uid=uid, names=quote(f"{name}.cs")))
    if not rows:
        return "not published: no generated source"
    if str(rows[0].get("fresh")).lower() not in ("true", "1"):
        return "not published: generated source older than its schema"
    extra = sorted((package / "Files" / "cs").rglob("*.cs")) if (package / "Files" / "cs").is_dir() else []
    result, errors = compile_script(_source_text(rows[0].get("Source")), name, creatio_bin(package, bin_dir), extra)
    return f"compile error: {errors[0]}" + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else "") if result == "failed" else None


def render(results: list[tuple[str, str]]) -> str:
    width = max((len(n) for n, _ in results), default=0)
    bad = sum(1 for _, s in results if not s.startswith("same"))
    return "\n".join([f"{n:<{width}}  {s}" for n, s in results] + [f"{len(results) - bad} same, {bad} not"])
