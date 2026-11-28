"""Checks for S33-T06 and S49-T02: record_history, column_transitions, process_runs steps, process_timers, fire_timer.
python tests/test_env_history.py  (a scripted clio; no site)."""

import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

from test_env_forensics import BOSS, COPIES, COPIES_NEEDLE, ID, RUN, RUNS, env, raises, run_cli  # noqa: E402

from creatio_schemas import records, runs  # noqa: E402

CLERK = "77777777-7777-7777-7777-777777777777"
TYPES = [{"Id": "a852c33f-0bdd-e011-92c3-00155d04c01d", "Name": "Inserted"}, {"Id": "a952c33f-0bdd-e011-92c3-00155d04c01d", "Name": "Updated"}]
INS, UPD = TYPES[0]["Id"], TYPES[1]["Id"]
NAMES = [{"Id": BOSS, "Name": "Ivan"}, {"Id": CLERK, "Name": "Olga"}]
OTHER = "88888888-8888-8888-8888-888888888888"


def log(record, at, by, kind, status, amount):
    return {"Id": f"f{abs(hash((record, at))) % 10**7:07d}-0000-4000-8000-000000000000", "ChangeTrackedOn": at, "ChangeTrackedById": by, "ChangeTypeId": kind,
            "ChangeTrackedId": record, "ClientIP": "", "CreatedOn": "2026-11-01T00:00:00", "ModifiedOn": at, "ProcessListeners": 0,
            "Name": "Order 7" if record == ID else "Other", "UsrStatus": status, "UsrAmount": amount}


MINE = [log(ID, "2026-11-11T08:00:00.100000", BOSS, INS, "Draft", 10.0),
        log(ID, "2026-11-11T08:00:05.000000", BOSS, UPD, "Draft", 20.0),
        log(ID, "2026-11-11T08:00:09.000000", CLERK, UPD, "Closed", 20.0)]
THEIRS = [log(OTHER, "2026-11-11T08:00:05.200000", BOSS, UPD, "Closed", 5.0),       # same user, 200 ms after the second change
          log(OTHER, "2026-11-11T08:00:05.900000", BOSS, UPD, "Closed", 6.0),       # same user, too far for 500 ms
          log(OTHER, "2026-11-11T08:00:05.100000", CLERK, UPD, "Closed", 7.0)]      # another user
HAS_LOG = {"information_schema.tables where table_name = 'SysUsrOrderLog'": [{"table_name": "SysUsrOrderLog"}],
           'from "SysEntityChangeType"': TYPES, 'from "Contact" where "Id" in': NAMES}


def history_env(extra=None):
    return env({**HAS_LOG, 'from "SysUsrOrderLog" where "ChangeTrackedId" = ': MINE, 'where "ChangeTrackedId" <> ': THEIRS, **(extra or {})})


def test_record_history_shows_who_when_and_was_became_per_column():
    e, clio = history_env()
    answer = records.record_history(e, f"UsrOrder:{ID}", zone="+02:00")
    text = records.render_history(answer)
    lines = text.splitlines()
    assert lines[0] == f"UsrOrder {ID}: 3 logged change(s)", text
    assert lines[1] == "2026-11-11 08:00:00 UTC (10:00 +02:00)  Inserted by Ivan", text
    assert "    Name: -> Order 7" in lines and "    UsrStatus: -> Draft" in lines and "    UsrAmount: -> 10.0" in lines, text  # an insert lists what has a value
    assert "    UsrAmount: 10.0 -> 20.0" in lines and "    UsrStatus: Draft -> Closed" in lines and lines.count("    UsrAmount: 10.0 -> 20.0") == 1, text
    assert not any("ChangeTracked" in l or "ModifiedOn" in l or "ProcessListeners" in l for l in lines), text  # the log's own columns are not changes
    assert "Updated by Olga" in text
    assert "ChangeTrackedId\" = '" + ID in clio.statements[1] and "order by \"ChangeTrackedOn\"" in clio.statements[1]


def test_record_history_one_column_and_clusters_of_the_same_user():
    e, _ = history_env()
    answer = records.record_history(e, f"UsrOrder:{ID}", column="UsrStatus")
    assert [(c["type"], c["columns"]) for c in answer["changes"]] == [("Inserted", [("UsrStatus", None, "Draft")]), ("Updated", [("UsrStatus", "Draft", "Closed")])]
    e, clio = history_env()
    answer = records.record_history(e, f"UsrOrder:{ID}", clusters=500)
    second = answer["changes"][1]
    assert [(o["id"], o["ms"]) for o in second["cluster"]] == [(OTHER, 200)], second["cluster"]  # not the 900 ms one, not the other user's
    assert answer["changes"][0]["cluster"] == []
    text = records.render_history(answer)
    assert "same user within 500 ms: 1 other record(s)" in text and f"{OTHER}  Other  Updated  +200 ms" in text and "same user within 500 ms: none" in text, text
    between = next(s for s in clio.statements if '"ChangeTrackedId" <> ' in s)
    assert "between '2026-11-11 07:59:59.600000' and '2026-11-11 08:00:09.500000'" in between, between  # one read for all changes, the window widened by the ms


def test_record_history_without_a_log_table_says_so():
    e, _ = env({"information_schema.tables where table_name": []})
    raises(lambda: records.record_history(e, f"UsrOrder:{ID}"), ValueError, "change tracking is off for UsrOrder")
    raises(lambda: records.record_history(e, "Usr'; drop:" + ID), ValueError, "not a table or column name")
    raises(lambda: records.record_history(e, "UsrOrder:nope"), ValueError, "not an Id")
    code, out = run_cli("record", ["history", "-e", "dev", f"UsrOrder:{ID}"], {"information_schema.tables where table_name": []})
    assert code == 2 and "change tracking is off for UsrOrder" in out, out


def test_record_history_cli_and_the_empty_record():
    code, out = run_cli("record", ["history", "-e", "dev", f"UsrOrder:{ID}", "--clusters", "500"],
                        {**HAS_LOG, 'from "SysUsrOrderLog" where "ChangeTrackedId" = ': MINE, 'where "ChangeTrackedId" <> ': THEIRS})
    assert code == 0 and "UsrAmount: 10.0 -> 20.0" in out and "+200 ms" in out, out
    code, out = run_cli("record", ["history", "-e", "dev", f"UsrOrder:{ID}"], {**HAS_LOG, 'from "SysUsrOrderLog" where "ChangeTrackedId" = ': []})
    assert code == 1 and "the log holds no row for this record" in out, out


LOG_ROWS = [{"ChangeTrackedId": ID, "ChangeTrackedOn": "2026-11-11T08:00:00", "ChangeTrackedById": BOSS, "ChangeTypeId": INS, "value": "Draft"},
            {"ChangeTrackedId": ID, "ChangeTrackedOn": "2026-11-11T08:00:05", "ChangeTrackedById": BOSS, "ChangeTypeId": UPD, "value": "Draft"},
            {"ChangeTrackedId": ID, "ChangeTrackedOn": "2026-11-11T08:00:09", "ChangeTrackedById": CLERK, "ChangeTypeId": UPD, "value": "Closed"},
            {"ChangeTrackedId": OTHER, "ChangeTrackedOn": "2026-11-11T08:00:06", "ChangeTrackedById": BOSS, "ChangeTypeId": UPD, "value": "Draft"},  # the log starts after it
            {"ChangeTrackedId": OTHER, "ChangeTrackedOn": "2026-11-12T09:00:00", "ChangeTrackedById": BOSS, "ChangeTypeId": UPD, "value": "Closed"},
            {"ChangeTrackedId": OTHER, "ChangeTrackedOn": "2026-11-12T10:00:00", "ChangeTrackedById": CLERK, "ChangeTypeId": UPD, "value": "Draft"}]
COLUMN = {"information_schema.tables where table_name = 'SysUsrOrderLog'": [{"table_name": "SysUsrOrderLog"}],
          "information_schema.columns where table_name = 'SysUsrOrderLog' and column_name = 'UsrStatus'": [{"column_name": "UsrStatus"}],
          'from "SysUsrOrderLog" order by "ChangeTrackedId"': LOG_ROWS, 'from "SysEntityChangeType"': TYPES, 'from "Contact" where "Id" in': NAMES}


def test_column_transitions_every_change_oldest_first_with_filters():
    e, clio = env(COLUMN)
    answer = records.column_transitions(e, "UsrOrder.UsrStatus", zone="+02:00")
    rows = [(t["record"], t["from"], t["to"], t["by"]) for t in answer["rows"]]
    # the insert is a transition from empty; "Draft -> Draft" is no change; the first row of OTHER is a baseline, not a transition
    assert rows == [(ID, "", "Draft", "Ivan"), (ID, "Draft", "Closed", "Olga"), (OTHER, "Draft", "Closed", "Ivan"), (OTHER, "Closed", "Draft", "Olga")], rows
    assert 'select "ChangeTrackedId", "ChangeTrackedOn", "ChangeTrackedById", "ChangeTypeId", "UsrStatus" as "value" from "SysUsrOrderLog"' in clio.statements[-3]
    assert [t["to"] for t in records.column_transitions(e, "UsrOrder.UsrStatus", to_value="closed")["rows"]] == ["Closed", "Closed"]  # case-blind
    assert [t["record"] for t in records.column_transitions(e, "UsrOrder.UsrStatus", from_value="Closed")["rows"]] == [OTHER]
    assert [t["record"] for t in records.column_transitions(e, "UsrOrder.UsrStatus", from_value="")["rows"]] == [ID]  # "" is the empty value
    assert len(records.column_transitions(e, "UsrOrder.UsrStatus", since="2026-11-12")["rows"]) == 2
    text = records.render_transitions(answer, 3)
    assert text.splitlines()[0] == "UsrOrder.UsrStatus: 4 transition(s)" and "(empty) -> Draft  by Ivan" in text and text.endswith("1 more; add out=<file.csv> for all"), text
    raises(lambda: records.column_transitions(e, "UsrOrder.UsrStatus", since="yesterday"), ValueError, "not a date")


def test_column_transitions_csv_unknown_column_and_the_row_cap():
    e, _ = env(COLUMN)
    answer = records.column_transitions(e, "UsrOrder.UsrStatus")
    tmp = Path(tempfile.mkdtemp())
    try:
        out = records.transitions_csv(answer, str(tmp / "sub" / "t.csv"))
        raw = Path(out).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf") and raw.decode("utf-8-sig").splitlines()[0] == "at;record;from;to;by;type", raw[:80]
        assert len(raw.decode("utf-8-sig").splitlines()) == 5
        code, text = run_cli("record", ["transitions", "-e", "dev", "UsrOrder.UsrStatus", "--to", "Closed", "--out", str(tmp / "c.csv")], COLUMN)
        assert code == 0 and "2 rows ->" in text and (tmp / "c.csv").is_file(), text
        code, text = run_cli("record", ["transitions", "-e", "dev", "UsrOrder.UsrStatus", "--to", "Nope"], COLUMN)
        assert code == 1 and "0 transition(s)" in text, text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    e, _ = env({**COLUMN, "information_schema.columns where table_name = 'SysUsrOrderLog' and column_name = 'UsrNope'": [],
                "information_schema.columns where table_name = 'SysUsrOrderLog' order": [{"column_name": "Id"}, {"column_name": "UsrStatus"}]})
    raises(lambda: records.column_transitions(e, "UsrOrder.UsrNope"), ValueError, "has no column UsrNope; it has UsrStatus")
    saved, records.LOG_ROWS = records.LOG_ROWS, 6
    try:
        assert records.column_transitions(env(COLUMN)[0], "UsrOrder.UsrStatus")["truncated"] is True
        assert "narrow with since=" in records.render_transitions(records.column_transitions(env(COLUMN)[0], "UsrOrder.UsrStatus"))
    finally:
        records.LOG_ROWS = saved


STEPS = [{"SysProcessId": RUN, "Caption": "Start", "Status": "Completed", "ErrorDescription": None, "StartDate": "2026-11-11T08:00:05", "CompleteDate": "2026-11-11T08:00:05"},
         {"SysProcessId": RUN, "Caption": "Read order", "Status": "Error", "ErrorDescription": "Column UsrX not found\n   at X()", "StartDate": "2026-11-11T08:00:06", "CompleteDate": None},
         {"SysProcessId": ID, "Caption": "1 d.", "Status": "Running", "ErrorDescription": None, "StartDate": "2026-11-11T08:00:07", "CompleteDate": "2026-11-12T08:00:07"}]


def test_process_runs_with_steps_and_logging_off():
    e, clio = env({'from "SysProcessLog" l': RUNS, 'from "Contact" where "Id" in': [], 'from "SysProcessElementLog" e': STEPS, COPIES_NEEDLE: COPIES[:1]})
    answer = runs.process_runs(e, process="UsrOrder_Process", steps=True)
    first, second = answer["runs"]
    assert [s["caption"] for s in first["steps"]] == ["Start", "Read order"] and first["steps"][1]["state"] == "failed" and first["steps"][1]["error"] == "Column UsrX not found"
    assert first["steps"][0]["start"] == "2026-11-11 08:00:05" and first["steps"][0]["end"] == "08:00:05"  # the clock only on the same day
    assert second["steps"][0]["end"] == "2026-11-12 08:00:07"
    step_sql = next(s for s in clio.statements if "SysProcessElementLog" in s)
    assert f"'{RUN}'" in step_sql and f"'{ID}'" in step_sql and "order by e.\"StartDate\"" in step_sql, step_sql  # one read for every run
    text = runs.render_runs(answer)
    assert "      Read order  Error (failed)  2026-11-11 08:00:06 UTC  Column UsrX not found" in text and "      1 d.  Running (completed)  2026-11-11 08:00:07 .. 2026-11-12 08:00:07 UTC" in text, text
    e, clio = env({'from "SysProcessLog" l': RUNS, 'from "Contact" where "Id" in': [], COPIES_NEEDLE: COPIES[:1]})
    assert "steps" not in runs.process_runs(e, process="UsrOrder_Process")["runs"][0] and not any("SysProcessElementLog" in s for s in clio.statements)  # off by default
    # nothing found and the whole log is empty: logging is off; nothing found in a log that has rows: just no runs
    e, _ = env({'from "SysProcessLog" l': [], 'from "SysProcessLog" offset': [], COPIES_NEEDLE: COPIES[:1]})
    assert runs.render_runs(runs.process_runs(e, process="UsrOrder_Process")) .endswith("process logging is off (SysProcessLog empty); enable it in the process settings")
    e, _ = env({'from "SysProcessLog" l': [], 'from "SysProcessLog" offset': [{"Id": RUN}], COPIES_NEEDLE: COPIES[:1]})
    assert runs.render_runs(runs.process_runs(e, process="UsrOrder_Process")).endswith("(no runs)")
    code, out = run_cli("proc-runs", ["runs", "-e", "dev", "--process", "UsrOrder_Process", "--steps"],
                        {'from "SysProcessLog" l': RUNS, 'from "Contact" where "Id" in': [], 'from "SysProcessElementLog" e': STEPS, COPIES_NEEDLE: COPIES[:1]})
    assert code == 0 and "Read order  Error (failed)" in out, out


def test_ticks_are_dotnet_ticks_in_utc():
    assert runs.utc_to_ticks(datetime(1970, 1, 1)) == 621355968000000000
    moment = datetime(2026, 11, 21, 7, 18, 0)
    assert runs.ticks_to_utc(runs.utc_to_ticks(moment)) == moment
    assert runs.ticks_to_utc(639308422800000000) == datetime(2026, 11, 21, 7, 18, 0)  # a trigger of the test site, read by hand
    assert runs.utc_to_ticks(datetime(2026, 11, 21, 7, 18, 0)) == 639308422800000000


ELEMENT = "99999999-9999-4999-8999-999999999999"
TIMER = [{"trigger": "t-1", "state": "WAITING", "next": 639308422800000000, "element_id": ELEMENT, "caption": "1 d.", "element_start": "2026-11-20T07:18:00",
          "run_id": RUN, "run_start": "2026-11-20T07:18:00", "process": "UsrOrder_Process"}]
TIMER_NEEDLE = "from qrtz_triggers t"
START_NEEDLE = "union all select q.trigger_name"  # longer than TIMER_NEEDLE: answers the statement with both
START = [{"trigger": "5d2a1c3e-0000-4000-8000-000000000001", "group": "A1000000-0000-4000-8000-000000000001", "state": "WAITING",
          "next": 639308422800000000, "cron": "0 0 0 1 1 ? *", "cron_zone": "UTC"}]


def test_process_timers_show_the_fire_time_in_the_project_zone():
    e, clio = env({TIMER_NEEDLE: TIMER, COPIES_NEEDLE: COPIES[:1]})
    timers = runs.process_timers(e, "UsrOrder_Process", zone="+02:00")
    assert timers[0]["fires"] == "2026-11-21 07:18:00 UTC (09:18 +02:00)" and timers[0]["element"] == "1 d." and timers[0]["run"] == RUN, timers
    statement = clio.statements[-1]
    assert 'e."Id"::text = t.job_group' in statement and "l.\"SysSchemaId\" in ('c1000000-0000-4000-8000-000000000001')" in statement and 'order by "next"' in statement and START_NEEDLE in statement, statement
    assert runs.render_timers(timers) == f"2026-11-21 07:18:00 UTC (09:18 +02:00)  UsrOrder_Process  1 d.  (WAITING)  run {RUN} started 2026-11-20 07:18:00 UTC (09:18 +02:00)  element {ELEMENT}"
    assert runs.render_timers([]) == "(no pending timers)"
    e, _ = env({COPIES_NEEDLE: []})
    raises(lambda: runs.process_timers(e, "UsrNone"), KeyError, "no process UsrNone")
    code, out = run_cli("proc-runs", ["timers", "-e", "dev", "--process", "UsrOrder_Process"], {TIMER_NEEDLE: TIMER, COPIES_NEEDLE: COPIES[:1]})
    assert code == 0 and "1 d." in out, out
    code, out = run_cli("proc-runs", ["timers", "-e", "dev", "--process", "UsrOrder_Process"], {TIMER_NEEDLE: [], COPIES_NEEDLE: COPIES[:1]})
    assert code == 1 and "(no pending timers)" in out


def test_process_timers_list_the_cron_start_trigger_of_a_timer_started_process():
    e, clio = env({TIMER_NEEDLE: TIMER, COPIES_NEEDLE: COPIES, START_NEEDLE: TIMER + START})
    timers = runs.process_timers(e, "UsrOrder_Process", zone="+02:00")
    start = [t for t in timers if t["element"] == "(start timer)"]
    assert len(timers) == 2 and len(start) == 1, timers
    s = start[0]
    assert s["run"] == "" and s["cron"] == "0 0 0 1 1 ? *" and s["group"] == "a1000000-0000-4000-8000-000000000001" and s["process"] == "UsrOrder_Process", s
    assert "where q.trigger_group in ('a1000000-0000-4000-8000-000000000001') order by" in clio.statements[-1], clio.statements[-1]  # one UId for three copies
    assert runs.render_timers(start) == ("2026-11-21 07:18:00 UTC (09:18 +02:00)  UsrOrder_Process  (start timer)  (WAITING)  cron 0 0 0 1 1 ? * (UTC)  "
                                         "trigger 5d2a1c3e-0000-4000-8000-000000000001")
    e, clio = env({TIMER_NEEDLE: TIMER, COPIES_NEEDLE: COPIES[:1], START_NEEDLE: TIMER + START, 'select "ModifiedOn" from "UsrOrder" where': [{"ModifiedOn": "2026-11-20T07:18:00"}],
                   "ccu.table_name = 'UsrOrder'": []})
    assert [t["element"] for t in runs.process_timers(e, "UsrOrder_Process", f"UsrOrder:{ID}")] == ["1 d."]  # record: run timers only
    assert not any(START_NEEDLE in s for s in clio.statements)


def test_process_timers_name_the_start_element_from_the_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        schema = Path(tmp) / "packages" / "UsrPkg" / "Schemas" / "UsrOrder_Process"
        schema.mkdir(parents=True)
        (schema.parent.parent / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": "b1000000-0000-4000-8000-000000000001", "Name": "UsrPkg", "DependsOn": []}}), encoding="utf-8")
        uid = "A1000000-0000-4000-8000-000000000001"
        (schema / "descriptor.json").write_text(json.dumps({"Descriptor": {"UId": uid, "Name": "UsrOrder_Process", "ManagerName": "ProcessSchemaManager", "DependsOn": []}}), encoding="utf-8")
        meta = {"MetaData": {"Schema": {"ManagerName": "ProcessSchemaManager", "UId": uid, "Name": "UsrOrder_Process",
                                        "BK4": [{"UId": "5d2a1c3e-0000-4000-8000-000000000001", "A2": "UsrYearlyTimer"}]}}}
        (schema / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        answers = {TIMER_NEEDLE: [], COPIES_NEEDLE: COPIES[:1], START_NEEDLE: START}
        for workspace in (Path(tmp) / "packages", Path(tmp) / "packages" / "UsrPkg"):  # a packages folder or a package
            e, _ = env(answers)
            assert runs.process_timers(e, "UsrOrder_Process", workspace=str(workspace))[0]["element"] == "UsrYearlyTimer"
        meta["MetaData"]["Schema"]["BK4"][0]["UId"] = "5d2a1c3e-0000-4000-8000-0000000000ff"  # an element the workspace does not know
        (schema / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        e, _ = env(answers)
        assert runs.process_timers(e, "UsrOrder_Process", workspace=tmp)[0]["element"] == "(start timer)"
        assert runs.process_timers(env(answers)[0], "UsrOrder_Process")[0]["element"] == "(start timer)"  # no workspace: unchanged
        code, out = run_cli("proc-runs", ["timers", "-e", "dev", "--process", "UsrOrder_Process", "--workspace", str(Path(tmp) / "packages")], answers)
        assert code == 0 and "(start timer)" in out, out


def test_fire_timer_without_a_record_moves_the_start_trigger_and_reads_it_back():
    now = datetime(2026, 11, 21, 7, 0, 0)
    project = project_file("dev")
    try:
        back = [{"state": "WAITING", "next": runs.utc_to_ticks(datetime(2026, 11, 21, 7, 0, 20))}]
        answers = {TIMER_NEEDLE: [], COPIES_NEEDLE: COPIES[:1], START_NEEDLE: START, "update qrtz_triggers": 1, "from qrtz_triggers t where": back}
        e, clio = env(answers)
        answer = runs.fire_timer(e, "UsrOrder_Process", "", str(project), "dev", zone="+02:00", now=now)
        where = "where trigger_name = '5d2a1c3e-0000-4000-8000-000000000001' and trigger_group = 'a1000000-0000-4000-8000-000000000001'"
        assert clio.statements[-2] == f"update qrtz_triggers set next_fire_time = {runs.utc_to_ticks(datetime(2026, 11, 21, 7, 0, 20))} {where}", clio.statements[-2]
        assert clio.statements[-1].startswith("select trigger_state") and clio.statements[-1].endswith(where), clio.statements[-1]
        assert answer["after"] == {"fires": "2026-11-21 07:00:20 UTC (09:00 +02:00)", "state": "WAITING"}, answer
        text = runs.render_fire(answer)
        assert "(start timer)  trigger 5d2a1c3e-0000-4000-8000-000000000001" in text and "read back: due 2026-11-21 07:00:20" in text, text
        code, out = run_cli("proc-runs", ["fire", "--project", str(project), "--process", "UsrOrder_Process"], {**answers, "information_schema": []})
        assert code == 0 and "read back: due" in out, out
    finally:
        shutil.rmtree(project.parent, ignore_errors=True)


def project_file(kind, clio="dev"):
    folder = Path(tempfile.mkdtemp())
    path = folder / "project.json"
    path.write_text(json.dumps({"environment": {"clioName": clio, "url": "https://p.example", "timeZone": "+02:00", **({"kind": kind} if kind else {})}}), encoding="utf-8")
    return path


def test_fire_timer_is_refused_unless_the_project_marks_the_environment_dev():
    now = datetime(2026, 11, 21, 7, 0, 0)
    for kind, clio in ((None, "dev"), ("test", "dev"), ("prod", "dev"), ("dev", "other")):
        project = project_file(kind, clio)
        try:
            e, clio_calls = env({TIMER_NEEDLE: TIMER, COPIES_NEEDLE: COPIES[:1]})
            raises(lambda: runs.fire_timer(e, "UsrOrder_Process", f"UsrOrder:{ID}", str(project), "dev", now=now), PermissionError, "refused: dev is not a dev environment")
            assert clio_calls.statements == [], "a refusal reads nothing and writes nothing"
        finally:
            shutil.rmtree(project.parent, ignore_errors=True)
    e, clio_calls = env({})
    raises(lambda: runs.fire_timer(e, "UsrOrder_Process", f"UsrOrder:{ID}", None, "dev"), PermissionError, "refused: dev is not a dev environment")
    assert clio_calls.statements == []
    project = project_file("dev")
    try:
        code, out = run_cli("proc-runs", ["fire", "-e", "dev", "--process", "UsrOrder_Process", "--record", f"UsrOrder:{ID}"], {})
        assert code == 2 and "refused: dev is not a dev environment" in out, out
        project.write_text(json.dumps({"environment": {"clioName": "dev", "url": "https://p.example", "login": "u", "password": "p"}}), encoding="utf-8")
        code, out = run_cli("proc-runs", ["fire", "--project", str(project), "--process", "UsrOrder_Process", "--record", f"UsrOrder:{ID}"], {})
        assert code == 2 and "refused" in out, out
    finally:
        shutil.rmtree(project.parent, ignore_errors=True)


def test_fire_timer_on_a_dev_environment_sets_the_next_fire_time():
    now = datetime(2026, 11, 21, 7, 0, 0)
    project = project_file("dev")
    try:
        answers = {TIMER_NEEDLE: TIMER, COPIES_NEEDLE: COPIES[:1], 'select "ModifiedOn" from "UsrOrder" where': [{"ModifiedOn": "2026-11-20T07:18:00"}],
                   "ccu.table_name = 'UsrOrder'": [], "update qrtz_triggers": 1}
        e, clio = env(answers)
        answer = runs.fire_timer(e, "UsrOrder_Process", f"UsrOrder:{ID}", str(project), "dev", delay=20, zone="+02:00", now=now)
        update = clio.statements[-2]
        assert update == f"update qrtz_triggers set next_fire_time = {runs.utc_to_ticks(datetime(2026, 11, 21, 7, 0, 20))} where trigger_name = 't-1' and job_group = '{ELEMENT}'", update
        assert answer["was"] == "2026-11-21 07:18:00 UTC (09:18 +02:00)" and answer["now"] == "2026-11-21 07:00:20 UTC (09:00 +02:00)"
        assert "was due 2026-11-21 07:18:00" in runs.render_fire(answer) and "now due 2026-11-21 07:00:20" in runs.render_fire(answer)
        # the record picks the run: the timers are read for the runs around its changes
        assert any("l.\"StartDate\" between" in s for s in clio.statements)
        # an update that touches no row is an error, not a silent success
        e, _ = env({**answers, "update qrtz_triggers": 0})
        raises(lambda: runs.fire_timer(e, "UsrOrder_Process", f"UsrOrder:{ID}", str(project), "dev", now=now), RuntimeError, "was not updated")
        # two timers wait: name one
        second = dict(TIMER[0], trigger="t-2", element_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", caption="2 d.")
        e, clio = env({**answers, TIMER_NEEDLE: TIMER + [second]})
        raises(lambda: runs.fire_timer(e, "UsrOrder_Process", f"UsrOrder:{ID}", str(project), "dev", now=now), ValueError, "2 pending timers")
        assert not any(s.startswith("update") for s in clio.statements)
        runs.fire_timer(e, "UsrOrder_Process", f"UsrOrder:{ID}", str(project), "dev", timer="2 d", now=now)
        assert clio.statements[-1].endswith("job_group = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'")
        e, _ = env({**answers, TIMER_NEEDLE: []})
        raises(lambda: runs.fire_timer(e, "UsrOrder_Process", f"UsrOrder:{ID}", str(project), "dev", now=now), KeyError, "no pending timer")
        code, out = run_cli("proc-runs", ["fire", "--project", str(project), "--process", "UsrOrder_Process", "--record", f"UsrOrder:{ID}", "--delay", "5"],
                            {**answers, "information_schema": []})
        assert code == 0 and "now due" in out and "was due 2026-11-21 07:18:00" in out, out
    finally:
        shutil.rmtree(project.parent, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
