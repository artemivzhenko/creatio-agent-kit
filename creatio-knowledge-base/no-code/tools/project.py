#!/usr/bin/env python3
"""Synchronize the test framework's environment configuration from project.json."""

import argparse
import csv
import json
import re
import sys
from pathlib import Path


def read_json(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    # Framework configuration accepts comments; preserve strings while removing comments.
    result = []
    i = 0
    in_string = False
    escaped = False
    while i < len(text):
        ch = text[i]
        if in_string:
            result.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
        elif ch == '"':
            in_string = True
            result.append(ch)
            i += 1
        elif text[i:i + 2] == "//":
            end = text.find("\n", i + 2)
            i = len(text) if end < 0 else end
        elif text[i:i + 2] == "/*":
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError(f"{path}: unterminated comment")
            result.append(" ")
            i = end + 2
        else:
            result.append(ch)
            i += 1
    text = "".join(result)
    result = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            result.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            result.append(ch)
        elif ch == "," and text[i + 1:].lstrip().startswith(("}", "]")):
            continue
        else:
            result.append(ch)
    value = json.loads("".join(result))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def sync(project_file: Path, framework: Path | None = None) -> list[str]:
    project = read_json(project_file)
    env = project.get("environment")
    if not isinstance(env, dict) or any(not isinstance(env.get(k), str) or not env[k].strip()
                                        for k in ("url", "login", "password")):
        raise ValueError("project.json must contain environment.url, login and password")
    paths = project.get("paths")
    configured = paths.get("testFramework") if isinstance(paths, dict) else None
    if framework is None:
        if not isinstance(configured, str) or not configured.strip():
            raise ValueError("supply --framework or paths.testFramework in project.json")
        framework = Path(configured)
        if not framework.is_absolute():
            framework = project_file.resolve().parent / framework
    if not framework.is_dir() or not (framework / "Configuration").is_dir():
        raise ValueError(f"framework Configuration directory not found: {framework}")
    target = framework / "Configuration" / "creatio.env.config.json"
    config = read_json(target) if target.exists() else {}
    updates = {
        "BaseUrl": env["url"],
        "Users": [{"Username": env["login"], "Password": env["password"]}],
        "CasesFolders": config.get("CasesFolders", ["./Cases"]),
    }
    if not isinstance(updates["CasesFolders"], list) or not all(isinstance(p, str) for p in updates["CasesFolders"]):
        raise ValueError(f"{target}: CasesFolders must be a list of strings")
    changed = [key for key, value in updates.items() if config.get(key) != value]
    if not target.exists() or changed:
        config.update(updates)
        target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def tasks_from_csv(csv_file: Path, tasks: Path, key: str, title: str, text: str, status: str,
                   done: set[str], dry_run: bool = False) -> list[str]:
    """One <tasks>/<key>/task.md per CSV row; done rows and existing task.md are left alone."""
    with csv_file.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in (key, title, text, status) if c not in (reader.fieldnames or [])]
        if missing:
            raise KeyError(f"missing column {', '.join(missing)}; the file has: {', '.join(reader.fieldnames or [])}")
        rows = list(reader)
    lines, counts = [], {"wrote": 0, "kept": 0, "skipped (done)": 0}
    for row in rows:
        folder = re.sub(r"[^A-Za-z0-9_-]", "_", row[key].strip())
        if row[status].strip() in done:
            verdict = "skipped (done)"
        elif (tasks / folder / "task.md").is_file() and (tasks / folder / "task.md").stat().st_size:
            verdict = "kept"
        else:
            verdict = "wrote"
            if not dry_run:
                (tasks / folder).mkdir(parents=True, exist_ok=True)
                (tasks / folder / "task.md").write_text(
                    f"# {row[key].strip()} {row[title].strip()}\n\n{row[text].strip()}\n", encoding="utf-8")
        counts[verdict] += 1
        lines.append(f"{'would write' if dry_run and verdict == 'wrote' else verdict} {folder}")
    return lines + [", ".join(f"{k} {v}" for k, v in counts.items())]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("sync", help="write the framework environment from project.json")
    command.add_argument("project", type=Path)
    command.add_argument("--framework", type=Path)
    cmd = sub.add_parser("tasks-from-csv", help="one task folder per row of a tracker's CSV export")
    cmd.add_argument("csv_file", type=Path)
    cmd.add_argument("tasks", type=Path)
    cmd.add_argument("--key", default="Issue key")
    cmd.add_argument("--title", default="Summary")
    cmd.add_argument("--text", default="Description")
    cmd.add_argument("--status", default="Status")
    cmd.add_argument("--done", default="", help="comma-separated statuses to skip")
    cmd.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "tasks-from-csv":
        try:
            done = {d.strip() for d in args.done.split(",") if d.strip()}
            print("\n".join(tasks_from_csv(args.csv_file, args.tasks, args.key, args.title, args.text,
                                           args.status, done, args.dry_run)))
        except KeyError as exc:
            print(f"tasks-from-csv: {exc.args[0]}", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"tasks-from-csv failed: {exc}", file=sys.stderr)
            return 1
        return 0
    try:
        changed = sync(args.project, args.framework)
    except (OSError, ValueError) as exc:
        print(f"sync failed: {exc}", file=sys.stderr)
        return 1
    print("Updated: " + ", ".join(changed) if changed else "Already synchronized.")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic caption must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
