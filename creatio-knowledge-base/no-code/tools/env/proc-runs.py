#!/usr/bin/env python3
"""What ran on a site: business-process runs from SysProcessLog, and one run's error in full.

    python proc-runs.py runs  -e <env> --process UsrOrder_Process [--limit 20] [--since 2026-11-11] [--until ...]
    python proc-runs.py runs  -e <env> --record UsrOrder:<id> [--window 30] [--steps]
    python proc-runs.py runs  -e <env> --process UsrOrder_Process --element "<caption or element UId>" [--status running]
    python proc-runs.py timers -e <env> --process UsrOrder_Process [--record UsrOrder:<id>]
    python proc-runs.py fire  --project project.json --process UsrOrder_Process --record UsrOrder:<id> [--timer "1 d."] [--delay 20]
    python proc-runs.py error -e <env> <log id>
    python proc-runs.py cancel --project project.json <run id> [<run id> ..] [--wait 10]

`runs --record` lists every run that started within --window seconds of a change of the record or of a row pointing at
it (its details), oldest first. The processes `environment.noiseProcesses` of --project names (names or prefixes) are
hidden from `--record` and the unfiltered list, with a line saying how many. Times are UTC and `environment.timeZone`.
`--element` lists instead the tasks of that element (a page task, say) still open in `SysProcessElementLog`, newest first, the count in the first
line, then per task its start, run id, the record the run holds and the owner.
`--steps` prints under each run the elements it went through (`SysProcessElementLog`: caption, status, start .. end, UTC). `timers` lists the
pending timers of a process (a `qrtz_triggers` row whose `job_group` is the run's element id) with the fire time in the project's zone. `fire`
moves one pending timer to now + `--delay` seconds (default 20); it is refused (exit 2, `refused: <env> is not a dev environment`) unless the
`--project` marks the environment `"kind": "dev"`. `cancel` (dev environments only, refused the same way) posts the Process Log's
cancel (`ProcessEngineService.svc/CancelExecution`) for the runs - the run ids `--element` lists - and prints each `SysProcessLog` row read
back (polled up to `--wait` seconds). With no run on a site whose `SysProcessLog` is empty `runs` says `process logging is off`.
Exit 1 when no run is found (`runs`, `timers`) or the run failed (`error`); 2 on a usage error or a refusal.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from creatio_schemas.environment import open_environment  # noqa: E402
from creatio_schemas.records import zone_of  # noqa: E402
from creatio_schemas.runs import (cancel_runs, fire_timer, process_error, process_runs, process_timers, render_cancel,  # noqa: E402
                                  render_error, render_fire, render_runs, render_timers)


def noise_of(project: str | None) -> list[str]:
    if not project:
        return []
    with open(project, encoding="utf-8-sig") as f:
        return list((json.load(f).get("environment") or {}).get("noiseProcesses") or [])


def main(argv=None, **env_kw) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = p.add_subparsers(dest="command", required=True, metavar="command")
    runs = commands.add_parser("runs", help="the runs of a process, or the runs around the changes of a record")
    runs.add_argument("--process", help="process name or UId (every copy of that schema)")
    runs.add_argument("--record", help="<Entity>:<Id>")
    runs.add_argument("--since", help="start at or after (2026-11-11T08:00, UTC unless a zone is written)")
    runs.add_argument("--until", help="start at or before")
    runs.add_argument("--limit", type=int, default=20)
    runs.add_argument("--window", type=int, default=30, help="--record: seconds around each change (default 30)")
    runs.add_argument("--steps", action="store_true", help="the elements each run went through")
    runs.add_argument("--element", help="a caption or an element UId: its open tasks, counted")
    runs.add_argument("--status", help="with --element: running (the default) or waiting")
    timers = commands.add_parser("timers", help="the pending timers of a process")
    timers.add_argument("--process", required=True)
    timers.add_argument("--record", help="<Entity>:<Id>: only runs that started around its changes")
    timers.add_argument("--window", type=int, default=30)
    fire = commands.add_parser("fire", help="move a pending timer to now + --delay seconds (dev environments only)")
    fire.add_argument("--process", required=True)
    fire.add_argument("--record", required=True, help="<Entity>:<Id>")
    fire.add_argument("--timer", default="", help="part of the element's caption (or its id) when several timers wait")
    fire.add_argument("--delay", type=int, default=20, help="seconds from now (default 20)")
    error = commands.add_parser("error", help="one run's error without stack frames, and the element it stopped on")
    error.add_argument("log_id")
    cancel = commands.add_parser("cancel", help="cancel runs (a stuck page task's run; dev environments only)")
    cancel.add_argument("run_ids", nargs="+", metavar="run_id")
    cancel.add_argument("--wait", type=int, default=10, help="seconds to wait for the SysProcessLog rows to leave running (default 10)")
    for sub in (runs, error, timers, fire, cancel):
        sub.add_argument("-e", "--env", help="clio environment name")
        sub.add_argument("--project", help="project.json (environment, timeZone, noiseProcesses)")
    a = p.parse_args(argv)
    try:
        sleep = env_kw.pop("sleep", None)  # tests: the cancel's poll without waiting
        env, zone = open_environment(a.env, a.project, **env_kw), zone_of(a.project)
        if a.command == "runs":
            answer = process_runs(env, a.process, a.record, a.since, a.until, a.limit, a.window, noise_of(a.project), zone, a.steps, a.element, a.status)
            print(render_runs(answer))
            return 0 if answer.get("runs", answer.get("tasks")) else 1
        if a.command == "timers":
            timers = process_timers(env, a.process, a.record, a.window, zone)
            print(render_timers(timers))
            return 0 if timers else 1
        if a.command == "fire":
            print(render_fire(fire_timer(env, a.process, a.record, a.project, a.env, a.timer, a.delay, zone)))
            return 0
        if a.command == "cancel":
            logs = cancel_runs(env, a.run_ids, a.project, a.env, zone, a.wait, sleep)
            print(render_cancel(logs))
            return 1 if any(x["state"] == "running" for x in logs) else 0
        answer = process_error(env, a.log_id, zone)
        print(render_error(answer))
        return 1 if answer["run"]["state"] == "failed" else 0
    except PermissionError as e:  # a refusal reads `refused: ...`, not `error: ...`
        print(e.args[0], file=sys.stderr)
        return 2
    except (ValueError, KeyError, FileNotFoundError, RuntimeError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
