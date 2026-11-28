#!/usr/bin/env python3
"""What the MCP server returned to the agents: one JSONL line per tool call, and the summary of the lines.

    python tool_stats.py [days]            calls and characters per tool, the ten largest answers, the truncated share, the gap count

`server.py` wraps every tool at its registration point and appends `{"ts", "tool", "args", "chars", "ms", "truncated"}` to
`.stats/<date>.jsonl` next to it. `args` holds the argument NAMES and the length of each value, never a value (a path, a query or a
password must not land in a log). `truncated` is true when the answer ends in a `... N more` tail. Off with `CREATIO_KB_STATS=0`.

The gaps (`report_gap`): one line per thing an agent did outside the tools, `{"ts", "kind", "need", "instead", "script", "task"}` in
`<kit>/dev/gaps/gaps.jsonl`, the script it wrote copied under `dev/gaps/scripts/` (`CREATIO_KB_GAPS_DIR` moves the folder). The
feedback round reads them whole; the summary ends with their count.
"""

from __future__ import annotations

import functools
import inspect
import json
from collections import Counter
import os
import re
import shutil
import traceback
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

def stats_folder() -> Path:
    """`.stats/` next to this file; `CREATIO_KB_STATS_DIR` names another (the tests)."""
    return Path(os.environ.get("CREATIO_KB_STATS_DIR") or Path(__file__).resolve().parent / ".stats")


TAIL_RE = re.compile(r"^\.\.\. \d+ more", re.M)


def enabled() -> bool:
    return os.environ.get("CREATIO_KB_STATS", "1") != "0"


def record(folder: Path, tool: str, args: dict, chars: int, ms: int, truncated: bool) -> None:
    """Append one line to <folder>/<today>.jsonl; a log that cannot be written never fails a tool call."""
    line = {"ts": datetime.now().isoformat(timespec="seconds"), "tool": tool, "args": args, "chars": chars, "ms": ms, "truncated": truncated}
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / f"{date.today().isoformat()}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


def lengths(fn, args, kwargs) -> dict:
    """{argument name: len(str(value))} of a call - names and sizes only."""
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        return {k: len(str(v)) for k, v in bound.arguments.items()}
    except (TypeError, ValueError):
        return {}


def instrument(fn, folder: Path | None = None):
    """`fn` with its call logged (`functools.wraps` keeps the signature, so the SDK still builds the tool's schema from it)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not enabled():
            return fn(*args, **kwargs)
        start = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except Exception as e:  # a tool that raises is an answer the agent cannot read: say it, keep it, never drop the call
            path = record_error(folder or stats_folder(), fn.__name__, lengths(fn, args, kwargs), e)
            return f"error: {type(e).__name__}: {e} - the parser or the tool failed; the call is logged in {path} (tool_stats lists it)"
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        record(folder or stats_folder(), fn.__name__, lengths(fn, args, kwargs), len(text), int((time.perf_counter() - start) * 1000), bool(TAIL_RE.search(text)))
        return result

    return wrapper


def record_error(folder: Path, tool: str, args: dict, e: BaseException) -> Path:
    """One JSON line in `<folder>/errors.jsonl`: when, the tool, the argument names and lengths, the error, the last three frames
    (`file:line in function`) - never a value. The path, for the answer."""
    folder.mkdir(parents=True, exist_ok=True)
    frames = [f"{Path(f.filename).name}:{f.lineno} in {f.name}" for f in traceback.extract_tb(e.__traceback__)[-3:]]
    line = {"ts": datetime.now().isoformat(timespec="seconds"), "tool": tool, "args": args, "error": f"{type(e).__name__}: {e}"[:500], "where": frames}
    path = folder / "errors.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def read_errors(days: int = 1, folder: Path | None = None) -> list[dict]:
    """The `errors.jsonl` lines of the last `days` days (today included)."""
    path = (folder or stats_folder()) / "errors.jsonl"
    if not path.is_file():
        return []
    since = (date.today() - timedelta(days=max(int(days), 1) - 1)).isoformat()
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict) and str(line.get("ts", ""))[:10] >= since:
            out.append(line)
    return out


def errors_line(errors: list[dict]) -> str:
    """`errors: N (<tool> x k, ...); last: <tool> <error>` or `errors: 0` - the tool calls that raised."""
    if not errors:
        return "errors: 0"
    per_tool = Counter(e.get("tool", "?") for e in errors)
    last = errors[-1]
    return (f"errors: {len(errors)} (" + ", ".join(f"{t} x {n}" for t, n in per_tool.most_common(5)) + f"); last: {last.get('tool', '?')} "
            + str(last.get("error", ""))[:120])


def read(days: int = 1, folder: Path | None = None) -> list[dict]:
    """The lines of the last `days` days (today included) from <folder>."""
    folder = folder or stats_folder()
    out = []
    for i in range(max(int(days), 1)):
        path = folder / f"{(date.today() - timedelta(days=i)).isoformat()}.jsonl"
        if path.is_file():
            for raw in path.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(raw))
                except ValueError:
                    continue
    return out


# -- gaps: what the agent did outside the tools, recorded when it happened (S37-T01) ---------------------------------- #

GAP_KINDS = ("missing", "misbehaved", "by-hand", "framework")
_SECRET_RE = re.compile(r"\b(password|passwd|pwd|token|secret|client_secret|api[_-]?key|bearer)\b\s*[=:]?\s*\S", re.I)


def gaps_folder() -> Path:
    """`<kit>/dev/gaps` (the kit root is two levels above `creatio-knowledge-base/mcp-server/`); `CREATIO_KB_GAPS_DIR` names another (the tests)."""
    return Path(os.environ.get("CREATIO_KB_GAPS_DIR") or Path(__file__).resolve().parents[2] / "dev" / "gaps")


def record_gap(folder: Path, kind: str, need: str, instead: str, script: str = "", task: str = "") -> dict:
    """Append one line to <folder>/gaps.jsonl and keep a copy of `script` under <folder>/scripts/; ValueError says why a call is refused.
    The secret check covers `need`, `instead` and `task` (the text other agents read); the script is copied as it is - the caller keeps
    credentials out of it."""
    if kind not in GAP_KINDS:
        raise ValueError(f"kind must be one of {', '.join(GAP_KINDS)}")
    if not need.strip() or not instead.strip():
        raise ValueError("need and instead must both say something")
    if _SECRET_RE.search(" ".join((need, instead, task))):
        raise ValueError("the log is read by other agents: no password, token or key in the text")
    kept = ""
    if script:
        src = Path(script)
        if not src.is_file():
            raise ValueError(f"script is not a file: {script}")
        scripts = folder / "scripts"
        if src.resolve().parent == scripts.resolve():
            kept = str(src)
        else:
            scripts.mkdir(parents=True, exist_ok=True)
            today = date.today().isoformat()
            dest, n = scripts / f"{today}-{src.name}", 2
            while dest.exists():  # the counter goes before the name: `a.tar.gz` stays whole
                dest, n = scripts / f"{today}-{n}-{src.name}", n + 1
            shutil.copy2(src, dest)
            kept = str(dest)
    line = {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind, "need": need.strip(), "instead": instead.strip(), "script": kept, "task": task}
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "gaps.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return line


def read_gaps(folder: Path | None = None) -> list[dict]:
    """Every line of <folder>/gaps.jsonl (a line that is not a JSON object is skipped)."""
    path = (folder or gaps_folder()) / "gaps.jsonl"
    out = []
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if isinstance(line, dict):
                out.append(line)
    return out


def gaps_line(gaps: list[dict]) -> str:
    """`gaps: N (missing a, misbehaved b, by-hand c, framework d); last: <ts> <kind> <need>`, or `gaps: 0`."""
    if not gaps:
        return "gaps: 0"
    counts = ", ".join(f"{k} {sum(1 for g in gaps if g.get('kind') == k)}" for k in GAP_KINDS)
    last = gaps[-1]
    return f"gaps: {len(gaps)} ({counts}); last: {last.get('ts')} {last.get('kind')} {str(last.get('need', ''))[:80]}"


def summarise(rows: list[dict], gaps: list[dict] | None = None, errors: list[dict] | None = None) -> str:
    """calls and characters per tool (the most characters first), the ten largest answers, the truncated share, the total; with `gaps` the gap line last."""
    text = _summarise_calls(rows)
    return text if gaps is None else text + "\n" + gaps_line(gaps) + ("\n" + errors_line(errors) if errors is not None else "")


def _summarise_calls(rows: list[dict]) -> str:
    if not rows:
        return "(no tool calls logged)"
    per: dict[str, list[int]] = {}
    for r in rows:
        per.setdefault(r["tool"], []).append(int(r["chars"]))
    width = max(len(t) for t in per)
    lines = [f"{'tool':<{width}}  {'calls':>6}  {'chars':>9}  {'avg':>7}  {'max':>8}"]
    for tool, chars in sorted(per.items(), key=lambda kv: -sum(kv[1])):
        lines.append(f"{tool:<{width}}  {len(chars):>6}  {sum(chars):>9}  {sum(chars) // len(chars):>7}  {max(chars):>8}")
    lines.append("")
    lines.append("largest answers:")
    for r in sorted(rows, key=lambda r: -int(r["chars"]))[:10]:
        lines.append(f"  {int(r['chars']):>8}  {r['tool']}({', '.join(sorted(r.get('args') or {}))})  {r['ts']}")
    total = sum(int(r["chars"]) for r in rows)
    cut = sum(1 for r in rows if r.get("truncated"))
    lines.append("")
    lines.append(f"{len(rows)} calls, {total} chars, {cut} truncated ({100 * cut // len(rows)}%)")
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        days = int(argv[0]) if argv else 1
    except ValueError:
        print("usage: tool_stats.py [days]", file=sys.stderr)
        return 2
    print(summarise(read(days), read_gaps(gaps_folder())))
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
