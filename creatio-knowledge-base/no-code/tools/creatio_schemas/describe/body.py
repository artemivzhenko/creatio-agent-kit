"""The text of one copy of a schema as the site holds it, read in base64 chunks (S48-T04).

A client schema (`ClientUnitSchemaManager`) and a source code schema (`SourceCodeSchemaManager`): the largest
`SysSchemaContent.Content` row - the `.js` / the `.cs`; any other schema (an object, a process, a user task):
`SysSchema.MetaData` - a process's is JSON with a BOM, an object's the platform's diff-form text (P-2.12), not a pulled metadata.json.
The bytes come in chunks of 15000 (20 KB of base64 - the size clio carried stably in the field, D20), several chunks per clio call, and are checked against the md5 the site computes. PostgreSQL only.
"""

from __future__ import annotations

import base64
import hashlib

from ..records import quote as _quote

CHUNK = 15000  # bytes per chunk: 20 KB of base64
PER_CALL = 10  # chunks per clio call: 200 KB of base64 in one answer

_SOURCE = """(select case when s."ManagerName" in ('ClientUnitSchemaManager', 'SourceCodeSchemaManager')
  then (select sc."Content" from "SysSchemaContent" sc where sc."SysSchemaId" = s."Id" order by octet_length(sc."Content") desc limit 1)
  else s."MetaData" end "src") b"""

COPIES_SQL = """select s."Id"::text "id", p."Name"::text "package", s."ManagerName"::text "manager", s."ModifiedOn"::text "modifiedOn",
  coalesce(octet_length(b."src"), 0)::text "size", coalesce(md5(b."src"), '')::text "md5"
from "SysSchema" s join "SysPackage" p on p."Id" = s."SysPackageId" cross join lateral """ + _SOURCE + """
where s."Name" = {name} order by p."Name\""""

CHUNKS_SQL = """select i::text "i", encode(substring(b."src" from i * {chunk} + 1 for {chunk}), 'base64')::text "b64", md5(b."src")::text "md5"
from "SysSchema" s cross join lateral """ + _SOURCE + """ cross join generate_series({first}, {last}) i
where s."Id" = {id} and i * {chunk} < octet_length(b."src") order by i"""


def copies(env, schema: str) -> list[dict]:
    """Every SysSchema copy of the name: id, package, manager, modifiedOn, size and md5 of the body - no body."""
    return env.sql(COPIES_SQL.format(name=_quote(schema)))


def read(env, schema_id: str) -> str:
    """The body of one SysSchema row by its Id, decoded as UTF-8; "" when it has none. A body that does not match the site's md5 raises."""
    data, md5, first = b"", "", 0
    while True:
        rows = env.sql(CHUNKS_SQL.format(chunk=CHUNK, first=first, last=first + PER_CALL - 1, id=_quote(schema_id)))
        for r in rows:
            data += base64.b64decode("".join(r["b64"].split()))
            md5 = r["md5"]
        if len(rows) < PER_CALL:
            break
        first += PER_CALL
    if md5 and hashlib.md5(data).hexdigest() != md5:
        raise RuntimeError(f"the body of {schema_id} came back as {len(data)} bytes that do not match the site's md5 {md5}")
    return data.decode("utf-8")


def listing(rows: list[dict]) -> str:
    return "\n".join(f"  {r['package']}  {r['size']} bytes  md5 {r['md5'][:8]}  {r['modifiedOn'][:19]}" for r in rows)


def schema_body(env, schema: str, package: str | None = None) -> str:
    """The text of the copy of `schema` in `package`, or of its single copy. No copy raises KeyError; several copies and no
    package raise LookupError with one line per copy (package, size, md5, ModifiedOn)."""
    rows = copies(env, schema)
    if package:
        rows = [r for r in rows if r["package"].lower() == package.lower()]
    if not rows:
        raise KeyError(f"{schema} has no copy{' in package ' + package if package else ''} on the site")
    if len(rows) > 1:
        raise LookupError(f"{schema}: {len(rows)} copies on the site - name one with --package:\n{listing(rows)}")
    return read(env, rows[0]["id"])
