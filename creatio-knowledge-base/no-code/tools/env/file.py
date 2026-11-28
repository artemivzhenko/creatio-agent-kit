#!/usr/bin/env python3
"""A file record's bytes from the site, written to a local file.

    python file.py get <FileSchema> <Id> -e <env> --out <path>

`<FileSchema>` is the file table of an object (`SysFile`, `UsrOrderFile`, ...); the bytes are read through SQL
(`encode("Data", 'base64')`, decoded here) - the platform names no download route the kit could rely on.
Answers `<path>: N bytes, <content type>` (the type from the file name). Exit 1 when no such record; 2 on a usage error.
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from creatio_schemas.environment import open_environment  # noqa: E402

GUID = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def file_bytes(env, schema: str, id: str) -> tuple[str, bytes] | None:
    """(name, bytes) of one file record, or None."""
    if not re.fullmatch(r"[A-Za-z_]\w*", schema) or not GUID.fullmatch(id):
        raise ValueError("a file schema is a table name and an Id is a guid")
    rows = env.sql(f"select \"Name\", encode(\"Data\", 'base64') as \"B64\" from \"{schema}\" where \"Id\" = '{id}'")
    return (rows[0]["Name"], base64.b64decode(rows[0]["B64"] or "")) if rows else None


def main(argv=None, **env_kw) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("verb", choices=["get"])
    p.add_argument("schema")
    p.add_argument("id")
    p.add_argument("-e", "--env", help="clio environment name")
    p.add_argument("--project", help="project.json")
    p.add_argument("--out", required=True, help="the local file to write")
    a = p.parse_args(argv)
    try:
        found = file_bytes(open_environment(a.env, a.project, **env_kw), a.schema, a.id)
    except (ValueError, KeyError, FileNotFoundError, RuntimeError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2
    if not found:
        print(f"no record {a.id} in {a.schema}")
        return 1
    name, data = found
    Path(a.out).write_bytes(data)
    print(f"{a.out}: {len(data)} bytes, {mimetypes.guess_type(name)[0] or 'application/octet-stream'}")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
