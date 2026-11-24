#!/usr/bin/env python3
"""Call a service on an environment with login and CSRF: status, then the JSON pretty-printed or the fault in one line.

    python call.py -e <env> POST ServiceModel/UsrOrderService.svc/Recalc '{"orderId": "..."}'
    python call.py -e <env> POST rest/UsrOrderService/Recalc --file body.json
    python call.py -e <env> GET odata/Contact?$top=1
    python call.py -e <env> POST rest/UsrParseService/Parse --upload invoice.pdf
    python call.py -e <env> POST rest/UsrParseService/Parse --upload invoice.pdf --field content '{"kind": "invoice"}'

`0/` is added on .NET Framework and dropped on .NET Core for odata/, ServiceModel/, rest/, DataService/.
`--upload <path>` sends the file as multipart form data (part `file`, the file's name kept); with `--field <name>` it goes
as base64 in that field of the JSON body instead (the body argument, if any, supplies the other fields).
Exit 1 on a non-2xx answer; 2 on a usage error.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import urllib.parse
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from creatio_schemas.environment import open_environment  # noqa: E402


def main(argv=None, **env_kw) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("method", type=str.upper, choices=["GET", "POST", "PATCH", "PUT", "DELETE"])
    p.add_argument("path")
    p.add_argument("body", nargs="?", help="JSON body")
    p.add_argument("-e", "--env", help="clio environment name")
    p.add_argument("--project", help="project.json")
    p.add_argument("--file", help="read the JSON body from a file")
    p.add_argument("--upload", help="send this file: multipart form data, or base64 in --field")
    p.add_argument("--field", help="with --upload: the JSON field that gets the file as base64")
    a = p.parse_args(argv)
    try:
        raw = Path(a.file).read_text(encoding="utf-8-sig") if a.file else a.body
        body, content_type = json.loads(raw) if raw else None, None
        if a.field and not a.upload:
            raise ValueError("--field needs --upload")
        if a.upload:
            data = Path(a.upload).read_bytes()
            if a.field:
                body = {**(body or {}), a.field: base64.b64encode(data).decode("ascii")}
            else:
                boundary = "----kit" + uuid.uuid4().hex
                head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{Path(a.upload).name}"\r\n'
                        f"Content-Type: {mimetypes.guess_type(a.upload)[0] or 'application/octet-stream'}\r\n\r\n").encode("utf-8")
                body, content_type = head + data + f"\r\n--{boundary}--\r\n".encode("ascii"), f"multipart/form-data; boundary={boundary}"
        env = open_environment(a.env, a.project, **env_kw)
        path, _, query = a.path.partition("?")
        params = dict(urllib.parse.parse_qsl(query, keep_blank_values=True)) or None
        r = env.request(a.method, path, body if a.method != "GET" else None, params, content_type)
    except (ValueError, KeyError, FileNotFoundError, RuntimeError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2
    print(f"status: {r.status}")
    if r.error:
        print(f"error: {r.error}")
        return 1
    data = r.json()
    print(json.dumps(data, ensure_ascii=False, indent=2) if data is not None else (r.text or "(empty body)"))
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
