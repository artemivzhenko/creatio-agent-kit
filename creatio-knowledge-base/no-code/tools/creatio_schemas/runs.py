"""Business-process runs as the site logs them (`SysProcessLog`, `SysProcessElementLog`), read through `Environment.sql`.

    process_log(env, "<process id>")                       the run RunProcess started: status, error, start, end
    process_runs(env, process="UsrOrder_Process")         the newest runs of a process (own and replacing copies)
    process_runs(env, record="UsrOrder:<id>")             the runs started around the changes of a record and its details
    process_error(env, "<log id>")                        the whole error without stack frames, and the element it stopped on
    process_runs(..., steps=True)                         the steps of each run (`SysProcessElementLog`: caption, status, dates)
    process_timers(env, "<process>", "Entity:<id>")       the pending timers (`qrtz_triggers` of the run's elements), fire time in the zone
    fire_timer(env, "<process>", "Entity:<id>", project)  move a pending timer to now + 20 s; only for an environment `kind: dev`
    cancel_runs(env, ["<run id>"], project)                cancel runs (`ProcessEngineService.svc/CancelExecution`); only for `kind: dev`

The process id RunProcess answers is the `SysProcessLog.Id` of the run. Every query is in `env/README.md`.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .files import GUID_RE
from .records import CHUNK, foreign_keys, guid, ident, local_time, names_of, quote

LOG_SELECT = ('select l."Id", l."Name", st."Name" as "Status", l."ErrorDescription", l."StartDate", l."CompleteDate", '
              'l."OwnerId", s."Name" as "Process" from "SysProcessLog" l '
              'left join "SysProcessStatus" st on st."Id" = l."StatusId" left join "SysSchema" s on s."Id" = l."SysSchemaId" ')
ELEMENT_SELECT = ('select e."Caption", st."Name" as "Status", e."ErrorDescription", e."StartDate", e."CompleteDate" '
                  'from "SysProcessElementLog" e left join "SysProcessStatus" st on st."Id" = e."StatusId" ')
STEP_SELECT = ('select e."SysProcessId", e."Caption", st."Name" as "Status", e."ErrorDescription", e."StartDate", e."CompleteDate" '
               'from "SysProcessElementLog" e left join "SysProcessStatus" st on st."Id" = e."StatusId" ')
TIMERS_SQL = ('select t.trigger_name as "trigger", t.trigger_state as "state", t.next_fire_time as "next", e."Id"::text as "element_id", '
              'e."Caption" as "caption", e."StartDate" as "element_start", l."Id"::text as "run_id", l."StartDate" as "run_start", '
              's."Name" as "process", null::text as "cron", null::text as "cron_zone", null::text as "group" '
              'from qrtz_triggers t join "SysProcessElementLog" e on e."Id"::text = t.job_group '
              'join "SysProcessLog" l on l."Id" = e."SysProcessId" left join "SysSchema" s on s."Id" = l."SysSchemaId" where ')
# the start trigger of a timer-started process: a CRON trigger whose trigger_group is the process schema UId (8.3.2)
START_TIMERS_SQL = (' union all select q.trigger_name, q.trigger_state, q.next_fire_time, null, null, null, null, null, null, '
                    'c.cron_expression, c.time_zone_id, q.trigger_group from qrtz_triggers q left join qrtz_cron_triggers c '
                    'on c.sched_name = q.sched_name and c.trigger_name = q.trigger_name and c.trigger_group = q.trigger_group where q.trigger_group in ')
_TICKS_AT_EPOCH = 621355968000000000  # .NET ticks (100 ns since 0001-01-01) at 1970-01-01 UTC
_FRAME_RE = re.compile(r"^\s*(at |--- End of )")


def _when(value: str) -> str:
    """A date the caller typed (`2026-11-11`, `2026-11-11T08:00`, with or without a zone) as a UTC literal for SQL."""
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{value!r} is not a date (2026-11-11 or 2026-11-11T08:00)") from None
    moment = moment if moment.tzinfo is None else moment.astimezone(timezone.utc).replace(tzinfo=None)
    return f"{moment:%Y-%m-%d %H:%M:%S}"


def _moment(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.replace(tzinfo=None) if moment.tzinfo is None else moment.astimezone(timezone.utc).replace(tzinfo=None)


def state(row: dict) -> str:
    """`completed`, `running`, `failed` or `cancelled`, from the dates and the error (the status name is the site's language)."""
    if row.get("ErrorDescription"):
        return "failed"
    name = str(row.get("Status") or "").lower()
    if "cancel" in name:
        return "cancelled"
    if "error" in name:
        return "failed"
    return "completed" if row.get("CompleteDate") else "running"


def _first_line(text) -> str:
    return next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")


def _run(row: dict, zone: str | None, owners: dict | None = None) -> dict:
    return {"id": str(row.get("Id", "")).lower(), "process": row.get("Process") or row.get("Name"), "status": row.get("Status"),
            "state": state(row), "error": _first_line(row.get("ErrorDescription")), "start": local_time(row.get("StartDate"), zone),
            "end": local_time(row.get("CompleteDate"), zone), "owner": (owners or {}).get(str(row.get("OwnerId") or "").lower())}


def process_log(env, process_id: str, zone: str | None = None) -> dict | None:
    """The `SysProcessLog` row of a run as {id, process, status, state, error, start, end, owner}, or None (no row yet)."""
    rows = env.sql(LOG_SELECT + f"where l.\"Id\" = '{guid(process_id)}'")
    return _run(rows[0], zone) if rows else None


def _is_noise(name: str | None, noise) -> bool:
    return bool(name) and any(str(name).startswith(n) for n in noise)


def _record_moments(env, record: str) -> list[datetime]:
    """`ModifiedOn` of the record and of every row that points at it (the tables with a foreign key to its table)."""
    entity, _, record_id = record.partition(":")
    record_id = guid(record_id.strip())
    entity = ident(entity.strip())
    rows = env.sql(f'select "ModifiedOn" from "{entity}" where "Id" = \'{record_id}\'')
    if not rows:
        raise KeyError(f"no row {record_id} in {entity}")
    moments = [rows[0].get("ModifiedOn")]
    pointing = foreign_keys(env, entity, incoming=True)
    for i in range(0, len(pointing), CHUNK):
        union = " union all ".join(f"select \"ModifiedOn\" from \"{ident(f['table'])}\" where \"{ident(f['column'])}\" = '{record_id}'"
                                   for f in pointing[i:i + CHUNK])
        try:
            moments += [r.get("ModifiedOn") for r in env.sql(union)]
        except RuntimeError:  # a table without ModifiedOn in this chunk: ask each one alone
            for f in pointing[i:i + CHUNK]:
                try:
                    moments += [r.get("ModifiedOn") for r in env.sql(f"select \"ModifiedOn\" from \"{f['table']}\" where \"{f['column']}\" = '{record_id}'")]
                except RuntimeError:
                    continue
    return sorted({m for m in (_moment(v) for v in moments if v) if m})


def _windows(moments: list[datetime], seconds: int) -> list[tuple[datetime, datetime]]:
    """[moment - window, moment + window] for each moment, overlapping ones merged."""
    out: list[list[datetime]] = []
    for m in moments:
        lo, hi = m - timedelta(seconds=seconds), m + timedelta(seconds=seconds)
        if out and lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return [(lo, hi) for lo, hi in out]


COPIES_SQL = ('select s."Id"::text as "id", s."UId"::text as "uid", s."Name"::text as "name", s."ExtendParent"::text as "extendParent", '
              "coalesce(p.\"Name\", '')::text as \"package\" "
              'from "SysSchema" s left join "SysPackage" p on p."Id" = s."SysPackageId" '
              'where s."UId" in (select "UId" from "SysSchema" where {cond}) order by 5, 1')


def schema_copies(env, process: str) -> list[dict]:
    """Every `SysSchema` row of a process: [{id, uid, name, package}]. `SysProcessLog.SysSchemaId` points at one row, and a process has
    one row per package layer, so the runs are read for the Id of every layer of the UIds the name (or the UId) leads to. A copy the
    site renamed keeps its UId: give the UId (`schema_layers`, `describe.py uid`) when the name found nothing or only some copies."""
    p = process.strip()
    cond = f"\"UId\" = '{guid(p)}'" if GUID_RE.fullmatch(p) else f"\"Name\" = '{ident(p)}'"
    return env.sql(COPIES_SQL.format(cond=cond))


def element_tasks(env, element: str, process: str | None = None, zone: str | None = None) -> dict:
    """{tasks [task], copies}: the elements of `element` (its caption, or its `SchemaElementUId`) still open in `SysProcessElementLog`
    (no end date, no error), newest first, of a process (every copy of that schema) when `process` is given. A task is {run, start,
    record, owner, task}: the run id, its start, the record the run holds in `SysProcessEntity` (its display value, else the id), if
    any, the owner (`OwnerId`, a contact, by name) and the task's own `SysProcessElementLog.Id`."""
    where = ['e."CompleteDate" is null', "coalesce(e.\"ErrorDescription\", '') = ''",
             f"e.\"SchemaElementUId\" = '{guid(element)}'" if GUID_RE.fullmatch(element.strip()) else f'e."Caption" = {quote(element)}']
    copies = []
    if process:
        copies = schema_copies(env, process)
        if not copies:
            return {"tasks": [], "copies": []}
        where.append('l."SysSchemaId" in (' + ", ".join(f"'{guid(c['id'])}'" for c in copies) + ")")
    rows = env.sql('select e."SysProcessId"::text as "run", e."Id"::text as "task", e."StartDate", c."Name" as "owner", '
                   '(select coalesce(n."EntityDisplayValue", n."EntityId"::text) '
                   'from "SysProcessEntity" n where n."SysProcessId" = e."SysProcessId" offset 0 rows fetch first 1 rows only) as "record" '
                   'from "SysProcessElementLog" e join "SysProcessLog" l on l."Id" = e."SysProcessId" '
                   'left join "Contact" c on c."Id" = e."OwnerId" where ' + " and ".join(where) + ' order by e."StartDate" desc')
    return {"tasks": [{"run": str(r["run"]).lower(), "start": local_time(r.get("StartDate"), zone), "record": r.get("record") or "",
                       "owner": r.get("owner") or "", "task": str(r.get("task") or "").lower()} for r in rows],
            "copies": copies}


def process_runs(env, process: str | None = None, record: str | None = None, since: str | None = None, until: str | None = None,
                 limit: int = 20, window: int = 30, noise=(), zone: str | None = None, steps: bool = False,
                 element: str | None = None, status: str | None = None) -> dict:
    """{runs [run], hidden, windows}: the newest `limit` runs of a process (`process` = its name or UId - every copy of
    that schema), or every run that started within `window` seconds of a change of `record` (`<Entity>:<Id>`, its
    details included), oldest first. `noise` (names or prefixes, `project.json` `environment.noiseProcesses`) hides
    runs of those processes unless `process` names one; `hidden` counts them. `steps` adds to each run its elements (`steps`: caption,
    status, start, end, error); `loggingOff` is true when no run is found and `SysProcessLog` holds no row at all.
    `element` (a caption or an element UId) with `status="running"` (or "waiting") answers {tasks, copies} instead: see `element_tasks`."""
    if element:
        if (status or "running").lower() not in ("running", "waiting"):
            raise ValueError(f"status {status!r}: only running (waiting) tasks are listed")
        return element_tasks(env, element, process, zone)
    where, copies = [], []
    if process:
        copies = schema_copies(env, process)
        if not copies:
            return {"runs": [], "hidden": 0, "windows": [], "copies": []}
        where.append("l.\"SysSchemaId\" in (" + ", ".join(f"'{guid(c['id'])}'" for c in copies) + ")")
    if since:
        where.append(f"l.\"StartDate\" >= '{_when(since)}'")
    if until:
        where.append(f"l.\"StartDate\" <= '{_when(until)}'")
    windows = []
    if record:
        windows = _windows(_record_moments(env, record), window)
        if not windows:
            return {"runs": [], "hidden": 0, "windows": []}
        where.append("(" + " or ".join(f"l.\"StartDate\" between '{lo:%Y-%m-%d %H:%M:%S}' and '{hi:%Y-%m-%d %H:%M:%S}'" for lo, hi in windows) + ")")
    order = "asc" if record else "desc"
    # noise is dropped after the query, so the page is over-fetched by what the limit could lose to it
    fetch = limit if process or not noise else limit * 5
    rows = env.sql(LOG_SELECT + ("where " + " and ".join(where) + " " if where else "")
                   + f'order by l."StartDate" {order} offset 0 rows fetch first {int(fetch)} rows only')
    hidden = 0
    if not process and noise:
        kept = [r for r in rows if not _is_noise(r.get("Process") or r.get("Name"), noise)]
        hidden, rows = len(rows) - len(kept), kept
    rows = rows[:limit]
    owners = names_of(env, "Contact", [str(r["OwnerId"]) for r in rows if r.get("OwnerId")])
    runs = [_run(r, zone, owners) for r in rows]
    if steps and runs:
        by_run = process_steps(env, [r["id"] for r in runs], zone)
        for r in runs:
            r["steps"] = by_run.get(r["id"], [])
    answer = {"runs": runs, "hidden": hidden, "copies": copies,
              "windows": [(local_time(lo.isoformat(), zone), local_time(hi.isoformat(), zone)) for lo, hi in windows]}
    if not runs and (process or record):
        try:
            answer["loggingOff"] = not env.sql('select "Id" from "SysProcessLog" offset 0 rows fetch first 1 rows only')
        except RuntimeError:  # the hint is a bonus: a site that cannot answer it still gets "(no runs)"
            answer["loggingOff"] = False
    return answer


def process_steps(env, run_ids: list[str], zone: str | None = None) -> dict[str, list[dict]]:
    """{run id: [{caption, status, state, start, end, error}]} in start order: the elements each run went through
    (`SysProcessElementLog`)."""
    out: dict[str, list[dict]] = {}
    ids = [guid(i) for i in run_ids]
    for i in range(0, len(ids), CHUNK):
        rows = env.sql(STEP_SELECT + 'where e."SysProcessId" in (' + ", ".join(f"'{r}'" for r in ids[i:i + CHUNK]) + ') order by e."StartDate"')
        for r in rows:
            out.setdefault(str(r["SysProcessId"]).lower(), []).append(
                {"caption": r.get("Caption"), "status": r.get("Status"), "state": state(r), "start": _stamp(r.get("StartDate")),
                 "end": _stamp(r.get("CompleteDate"), r.get("StartDate")), "error": _first_line(r.get("ErrorDescription"))})
    return out


def _stamp(value, after=None) -> str:
    """A step's time as UTC `2026-11-11 08:00:06`; with `after` (its start) only the clock when the day is the same."""
    moment = _moment(value) if value else None
    if moment is None:
        return ""
    base = _moment(after) if after else None
    return f"{moment:%H:%M:%S}" if base and base.date() == moment.date() else f"{moment:%Y-%m-%d %H:%M:%S}"


def ticks_to_utc(ticks) -> datetime:
    """A Quartz `next_fire_time` (.NET ticks, UTC) as a naive UTC datetime."""
    return datetime(1970, 1, 1) + timedelta(microseconds=(int(ticks) - _TICKS_AT_EPOCH) // 10)


def utc_to_ticks(moment: datetime) -> int:
    """A UTC datetime (naive = UTC) as .NET ticks, the unit of `qrtz_triggers.next_fire_time`."""
    moment = moment if moment.tzinfo is None else moment.astimezone(timezone.utc).replace(tzinfo=None)
    return (moment - datetime(1970, 1, 1)) // timedelta(microseconds=1) * 10 + _TICKS_AT_EPOCH


def _start_element(workspace: str | None, group: str, trigger: str) -> str | None:
    """The name of the element of the process (schema UId `group`) whose UId is the start trigger's name; None when unknown."""
    if not workspace:
        return None
    from pathlib import Path

    from .process import ProcessSchema
    from .workspace import Workspace

    root = Path(workspace)
    package = root if (root / "descriptor.json").is_file() else next((d for d in sorted(root.iterdir()) if (d / "descriptor.json").is_file()), None)
    if package is None:
        return None
    for copy in Workspace(package).find(group):
        element = ProcessSchema(copy["dir"].parent.parent, copy["name"]).element_by_uid(trigger.lower())
        if element:
            return element["A2"]
    return None


def process_timers(env, process: str, record: str | None = None, window: int = 30, zone: str | None = None, workspace: str | None = None) -> list[dict]:
    """The pending timers of a process (every copy of its schema): [{trigger, state, fires, fires_utc, element, element_id, run, run_start,
    process, cron, group}] soonest first. A run timer is a `qrtz_triggers` row whose `job_group` is the id of the run's element in
    `SysProcessElementLog`; a start trigger (a timer-started process, no run yet) is one whose `trigger_group` is the schema UId: element
    `(start timer)`, run empty, its CRON in `cron`. `record` (`<Entity>:<Id>`) keeps the run timers of the runs that started within
    `window` seconds of a change of that record or of a row pointing at it. `workspace` (a packages folder or a package) names a start trigger's
    element (`YearlyTimer`) in place of `(start timer)`; an element the workspace does not know keeps `(start timer)`."""
    copies = schema_copies(env, process)
    if not copies:
        raise KeyError(f"no process {process} on this site")
    where = ['l."SysSchemaId" in (' + ", ".join(f"'{guid(c['id'])}'" for c in copies) + ")"]
    if record:
        windows = _windows(_record_moments(env, record), window)
        if not windows:
            return []
        where.append("(" + " or ".join(f"l.\"StartDate\" between '{lo:%Y-%m-%d %H:%M:%S}' and '{hi:%Y-%m-%d %H:%M:%S}'" for lo, hi in windows) + ")")
    names: dict = {}
    for c in copies:  # the name of the first copy (the base package) when a layer renamed it
        names.setdefault(c["uid"].lower(), c["name"])
    starts = "" if record else START_TIMERS_SQL + "(" + ", ".join(f"'{guid(u)}'" for u in names) + ")"
    rows = env.sql(TIMERS_SQL + " and ".join(where) + starts + ' order by "next"')
    out = []
    for r in rows:
        at, group = ticks_to_utc(r["next"]), str(r.get("group") or "").lower()
        t = {"trigger": r["trigger"], "state": r["state"], "fires": local_time(at.isoformat(), zone), "fires_utc": at, "cron": "", "group": ""}
        if group:
            t.update(element=_start_element(workspace, group, r["trigger"]) or "(start timer)", element_id="", run="", run_start="", process=names.get(group), cron=r.get("cron") or "",
                     cron_zone=r.get("cron_zone") or "", group=group)
        else:
            t.update(element=r.get("caption"), element_id=str(r["element_id"]).lower(), run=str(r["run_id"]).lower(),
                     run_start=local_time(r.get("run_start"), zone), process=r.get("process"))
        out.append(t)
    return out


def environment_is_dev(project: str | None, env_name: str | None) -> bool:
    """`environment.kind` of the project.json is `dev` and, when `env_name` is given, `environment.clioName` is that name."""
    if not project:
        return False
    import json
    with open(project, encoding="utf-8-sig") as f:
        e = json.load(f).get("environment") or {}
    return str(e.get("kind", "")).lower() == "dev" and (not env_name or str(e.get("clioName", "")).lower() == env_name.lower())


def fire_timer(env, process: str, record: str, project: str | None, env_name: str | None = None, timer: str = "", delay: int = 20,
               zone: str | None = None, now: datetime | None = None) -> dict:
    """Moves one pending timer of the run around `record` to now + `delay` seconds: `update qrtz_triggers set next_fire_time = <ticks>
    where trigger_name = ... and job_group = <element id>` - the statement S34-T08's `fire-timer` reuses. An empty `record` also reaches the
    start trigger of a timer-started process (`and trigger_group = <schema UId>`). The row is read back after (`after`: fires, state).
    Refused (PermissionError) unless the project.json marks the environment `kind: dev`; `timer` (a part of the element's caption,
    `start` for the start trigger, or the element id) picks one when several wait."""
    name = env_name or getattr(env, "clio_name", None) or "this environment"
    if not environment_is_dev(project, env_name or getattr(env, "clio_name", None)):
        raise PermissionError(f"refused: {name} is not a dev environment (project.json environment.kind must be \"dev\" for it)")
    timers = [t for t in process_timers(env, process, record or None, zone=zone) if t["state"] in ("WAITING", "ACQUIRED", "PAUSED")]
    if timer:
        timers = [t for t in timers if timer.lower() in str(t["element"] or "").lower() or timer.lower() == t["element_id"]]
    of = f"{process} for {record}" if record else process
    if not timers:
        raise KeyError(f"no pending timer of {of}" + (f" matching {timer!r}" if timer else ""))
    if len(timers) > 1:
        raise ValueError(f"{len(timers)} pending timers of {of}: name one with timer=<part of the caption, start, or the element id>: "
                         + "; ".join(f"{t['element']} ({t['element_id'] or t['trigger']}, fires {t['fires']})" for t in timers))
    t = timers[0]
    moment = (now or datetime.now(timezone.utc).replace(tzinfo=None)) + timedelta(seconds=max(0, delay))
    where = f"trigger_name = {quote(t['trigger'])} and " + (f"trigger_group = '{guid(t['group'])}'" if t.get("group") else f"job_group = '{guid(t['element_id'])}'")
    counts: list = []
    env.sql(f"update qrtz_triggers set next_fire_time = {utc_to_ticks(moment)} where {where}", counts)
    if counts and counts[-1] is not None and int(counts[-1]) != 1:
        raise RuntimeError(f"the trigger {t['trigger']} was not updated ({counts[-1]} rows)")
    back = env.sql(f"select trigger_state as \"state\", next_fire_time as \"next\" from qrtz_triggers t where {where}")
    after = {"fires": local_time(ticks_to_utc(back[0]["next"]).isoformat(), zone), "state": back[0]["state"]} if back else None
    return {"timer": t, "was": t["fires"], "now": local_time(moment.isoformat(), zone), "delay": delay, "after": after}


CANCEL = "ServiceModel/ProcessEngineService.svc/CancelExecution"


def cancel_runs(env, run_ids: list[str], project: str | None, env_name: str | None = None, zone: str | None = None,
                wait: int = 10, sleep=None) -> list[dict]:
    """Cancels runs (a stuck page task's run, say): `POST ProcessEngineService.svc/CancelExecution {"processDataIds": "<id>;<id>"}`,
    the Process Log's cancel (8.3.2 binaries: each id goes to `CancelExecutionAsync`), then each `SysProcessLog` row read back,
    polled up to `wait` seconds until no run is still running. Refused (PermissionError) unless the project.json marks the
    environment `kind: dev`, like `fire_timer`."""
    import time
    name = env_name or getattr(env, "clio_name", None) or "this environment"
    if not environment_is_dev(project, env_name or getattr(env, "clio_name", None)):
        raise PermissionError(f"refused: {name} is not a dev environment (project.json environment.kind must be \"dev\" for it)")
    ids = [guid(i) for i in run_ids]
    if not ids:
        raise ValueError("give the run id(s) to cancel (`runs --element ...` lists them)")
    r = env.call_service(CANCEL, {"processDataIds": ";".join(ids)})
    if not r.ok:
        raise RuntimeError(f"CancelExecution: {r.error}")
    sleep = sleep or time.sleep
    for _ in range(max(1, wait)):
        logs = [process_log(env, i, zone) or {"id": i, "process": None, "status": None, "state": "no SysProcessLog row", "start": "", "end": ""}
                for i in ids]
        if all(log["state"] != "running" for log in logs):
            break
        sleep(1)
    return logs


def render_cancel(logs: list[dict]) -> str:
    return "\n".join(f"{x['id']}  {x['process'] or '?'}  {x['status'] or '?'} ({x['state']})" + (f", ended {x['end']}" if x.get("end") else "")
                     for x in logs)


def trim_error(text: str | None) -> str:
    """The message chain of a .NET error without its stack frames (`   at ...`, `--- End of inner exception ...`)."""
    return "\n".join(line.rstrip() for line in str(text or "").splitlines() if line.strip() and not _FRAME_RE.match(line))


def process_error(env, log_id: str, zone: str | None = None) -> dict:
    """{run, error, element}: the run's whole error without stack frames and the element it stopped on
    (`SysProcessElementLog`: the newest with an error, else the newest that never completed), or None."""
    rows = env.sql(LOG_SELECT + f"where l.\"Id\" = '{guid(log_id)}'")
    if not rows:
        raise KeyError(f"no SysProcessLog row {log_id}")
    elements = env.sql(ELEMENT_SELECT + f"where e.\"SysProcessId\" = '{guid(log_id)}' order by e.\"StartDate\" desc")
    stopped = next((e for e in elements if e.get("ErrorDescription") or state(e) in ("failed", "cancelled")), None) \
        or next((e for e in elements if not e.get("CompleteDate")), None)
    element = None
    if stopped:
        element = {"caption": stopped.get("Caption"), "status": stopped.get("Status"), "start": local_time(stopped.get("StartDate"), zone),
                   "error": trim_error(stopped.get("ErrorDescription"))}
    return {"run": _run(rows[0], zone), "error": trim_error(rows[0].get("ErrorDescription")), "element": element}


def render_log(log: dict | None, process_id: str = "") -> str:
    if not log:
        return f"log: no SysProcessLog row for {process_id or 'the run'} (the engine did not log it)"
    line = f"log: {log['status'] or '?'} ({log['state']})  started {log['start']}" + (f", ended {log['end']}" if log["end"] else "")
    return line + (f"\n  error: {log['error']}" if log["error"] else "")


def render_runs(answer: dict) -> str:
    lines = []
    if "tasks" in answer:
        tasks = answer["tasks"]
        return "\n".join([f"{len(tasks)} running task{'' if len(tasks) == 1 else 's'}"]
                          + [f"{k['start']}  run {k['run']}" + (f"  waits on {k['record']}" if k["record"] else "")
                             + (f"  owner {k['owner']}" if k.get("owner") else "") for k in tasks])
    copies = answer.get("copies") or []
    if copies:
        asked = {c["name"] for c in copies}
        lines.append(f"{len(copies)} cop{'y' if len(copies) == 1 else 'ies'}: " + ", ".join(f"{c['package'] or '?'}" for c in copies)
                     + (f" (named {', '.join(sorted(asked))} on this site)" if len(asked) > 1 else ""))
    if answer["windows"]:
        lines.append("changes of the record: " + "; ".join(f"{lo} .. {hi}" for lo, hi in answer["windows"]))
    for r in answer["runs"]:
        lines.append(f"{r['start']}  {r['process']}  {r['status'] or '?'} ({r['state']})  {r['id']}"
                     + (f"  by {r['owner']}" if r["owner"] else "") + (f"\n    {r['error']}" if r["error"] else ""))
        for st in r.get("steps", []):
            lines.append(f"      {st['caption'] or '?'}  {st['status'] or '?'} ({st['state']})  {st['start']}"
                         + (f" .. {st['end']}" if st["end"] else "") + " UTC" + (f"  {st['error']}" if st["error"] else ""))
    if not answer["runs"]:
        lines.append("process logging is off (SysProcessLog empty); enable it in the process settings" if answer.get("loggingOff") else "(no runs)")
    if answer["hidden"]:
        lines.append(f"{answer['hidden']} runs of noise processes hidden")
    return "\n".join(lines)


def render_error(answer: dict) -> str:
    r = answer["run"]
    lines = [f"{r['process']}  {r['status'] or '?'} ({r['state']})  started {r['start']}" + (f", ended {r['end']}" if r["end"] else "")]
    e = answer["element"]
    if e:
        lines.append(f"stopped on: {e['caption']} ({e['status'] or '?'}, started {e['start']})")
    lines.append(answer["error"] or (e or {}).get("error") or "(no error text)")
    if e and e["error"] and e["error"] != answer["error"]:
        lines.append(f"element error: {e['error']}")
    return "\n".join(lines)


def render_timers(timers: list[dict]) -> str:
    if not timers:
        return "(no pending timers)"
    return "\n".join(f"{t['fires']}  {t['process']}  {t['element'] or '?'}  ({t['state']})  "
                     + (f"cron {t['cron'] or '?'} ({t.get('cron_zone') or '?'})  trigger {t['trigger']}" if t.get("group") else f"run {t['run']} started {t['run_start']}  element {t['element_id']}")
                     for t in timers)


def render_fire(answer: dict) -> str:
    t, after = answer["timer"], answer.get("after")
    return (f"{t['process']}  {t['element'] or '?'}  " + (f"trigger {t['trigger']}" if t.get("group") else f"run {t['run']}")
            + f"\n  was due {answer['was']}\n  now due {answer['now']} (in {answer['delay']} s)"
            + (f"\n  read back: due {after['fires']} ({after['state']})" if after else "\n  read back: no row"))
