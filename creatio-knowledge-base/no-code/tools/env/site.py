#!/usr/bin/env python3
"""A site restart and a process switched off or on, the way the Process Library does it.

    python site.py -e <env> restart [--wait 120]       clio restart-web-app, then waits until the site answers
    python site.py -e <env> process-off <ProcessName>  ProcessEngineService.svc/DisableProcess, read back from SysProcessDisabled
    python site.py -e <env> process-on <ProcessName>   EnableProcess

`restart` prints `restarted in <n> s` or `not up after <wait> s` (exit 1). A restart is site-wide: tell whoever works on the site first.
`process-off` / `process-on` print `<Process> off|on (SysProcessDisabled rows: n)`, n counted from the table after the call (exit 1 when
the table disagrees with the verb). A name with several schema rows is an error naming the packages. Exit 2 on a usage error.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from creatio_schemas.clio import Clio  # noqa: E402
from creatio_schemas.environment import open_environment  # noqa: E402

SERVICE = "ServiceModel/ProcessEngineService.svc/"


def restart(env, wait: int = 120, clio_run=None, sleep=time.sleep, clock=time.monotonic) -> tuple[bool, str]:
    start, env.timeout = clock(), min(env.timeout, 15)  # a request to a starting site may hang
    (clio_run or Clio(env.clio_name or "").run)(["restart-web-app", "-e", env.clio_name])
    while True:
        try:
            if env.fetch("odata/Contact?$top=1").ok:
                return True, f"restarted in {round(clock() - start)} s"
        except (RuntimeError, OSError):  # login refused while the site comes up
            pass
        if clock() - start >= wait:
            return False, f"not up after {wait} s"
        sleep(3)


def switch(env, name: str, off: bool) -> tuple[bool, str]:
    if not re.fullmatch(r"\w+", name):
        raise ValueError(f"a process name is letters, digits and _: {name!r}")
    schemas = env.sql(f"""select s."Id", p."Name" as "Package" from "SysSchema" s left join "SysPackage" p on p."Id" = s."SysPackageId"
        where s."Name" = '{name}' and s."ManagerName" = 'ProcessSchemaManager'""")
    if not schemas:
        raise ValueError(f"no process schema named {name}")
    if len(schemas) > 1:
        raise ValueError(f"{name} has {len(schemas)} schema rows, in packages: " + ", ".join(sorted(str(r.get("Package")) for r in schemas)))
    schema_id = schemas[0]["Id"]
    r = env.post(f"{SERVICE}{'DisableProcess' if off else 'EnableProcess'}?sysSchemaId={schema_id}")
    if not r.ok:
        raise RuntimeError(f"{'DisableProcess' if off else 'EnableProcess'}: {r.error}")
    n = int(env.sql(f"""select count(*) as "n" from "SysProcessDisabled" where "SysSchemaId" = '{schema_id}'""")[0]["n"])
    return (n > 0) == off, f"{name} {'off' if off else 'on'} (SysProcessDisabled rows: {n})"


def main(argv=None, **env_kw) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-e", "--env", help="clio environment name")
    p.add_argument("--project", help="project.json")
    sub = p.add_subparsers(dest="verb", required=True)
    sub.add_parser("restart").add_argument("--wait", type=int, default=120, help="seconds to wait for the site (default 120)")
    for verb in ("process-off", "process-on"):
        sub.add_parser(verb).add_argument("process")
    a = p.parse_args(argv)
    try:
        env = open_environment(a.env, a.project, **{k: v for k, v in env_kw.items() if k in ("opener", "clio_run", "timeout")})
        if a.verb == "restart":
            ok, line = restart(env, a.wait, **{k: v for k, v in env_kw.items() if k in ("sleep", "clock")}, clio_run=env_kw.get("restart_run"))
        else:
            ok, line = switch(env, a.process, a.verb == "process-off")
    except (ValueError, KeyError, FileNotFoundError, RuntimeError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2
    print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
