"""
MCP server exposing the Creatio UI test utility to an agent: the DSL reference, the cases and
configuration on disk, and the runner itself (validate, run, analyse, schemas). Every tool
either reads the repository or runs the command line; none writes a case or a page file - that
is the tester's side of the author/tester loop.

Run directly for stdio:  python server.py
The repository root is the parent of this folder, or CREATIO_TESTS_ROOT.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from mcp.server.mcpserver import MCPServer as _Server  # mcp >= 2.0
except ImportError:  # pragma: no cover - older SDK
    from mcp.server.fastmcp import FastMCP as _Server  # mcp 1.x

ROOT = Path(os.environ.get("CREATIO_TESTS_ROOT") or Path(__file__).resolve().parent.parent)
CLI_PROJECT = ROOT / "src" / "CreatioAutoTests.Cli"
RUN_TIMEOUT = int(os.environ.get("CREATIO_TESTS_TIMEOUT", "1800"))

mcp = _Server(
    "creatio-tests",
    instructions=(
        "The Creatio UI test utility: .act cases in a small DSL, validated in full before a "
        "browser opens, run against a Creatio instance (Freedom UI pages) - and process cases, "
        "the backend tier that starts business processes and checks their results and records "
        "without a browser. Read dsl() before writing a case; cases() and page_config() show what "
        "exists; validate(filter) lints without the environment; run(filter) executes and returns "
        "the report; analyse(path, name) describes a live page into Configuration/pages. The tools "
        "read and run only: a case or a page file is written by the author, not through here."
    ),
)


def _exe() -> list[str]:
    for configuration in ("Debug", "Release"):
        exe = CLI_PROJECT / "bin" / configuration / "net8.0" / ("creatio-tests.exe" if os.name == "nt" else "creatio-tests")
        if exe.is_file():
            return [str(exe)]
    return ["dotnet", "run", "--project", str(CLI_PROJECT), "--"]


def _stale_note() -> str:
    """A built exe older than the newest source under src/ is rebuilt once (the last line of dotnet build is the note);
    CREATIO_TESTS_NO_BUILD=1 only warns. Empty when the exe is fresh or there is none (dotnet run builds by itself)."""
    exe = next((e for c in ("Debug", "Release") if (e := CLI_PROJECT / "bin" / c / "net8.0" / ("creatio-tests.exe" if os.name == "nt" else "creatio-tests")).is_file()), None)
    if exe is None:
        return ""
    newest = max((p.stat().st_mtime for ext in ("*.cs", "*.csproj") for p in (ROOT / "src").rglob(ext) if not {"obj", "bin"} & set(p.parts)), default=0.0)
    # the apphost is not rewritten by a rebuild; the dlls beside it are
    built = max([exe.stat().st_mtime] + [d.stat().st_mtime for d in exe.parent.glob("*.dll")])
    if built >= newest:
        return ""
    build = ["dotnet", "build", str(CLI_PROJECT), "-c", exe.parent.parent.name]
    if os.environ.get("CREATIO_TESTS_NO_BUILD") == "1":
        return f"warning: {exe} is older than the sources under src/ (CREATIO_TESTS_NO_BUILD=1, not rebuilt); build it: {' '.join(build)}\n\n"
    done = subprocess.run(build, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    lines = [l for l in (done.stdout or "").splitlines() if l.strip()]
    return f"rebuilt the stale {exe.name} ({' '.join(build)}, exit {done.returncode}): {lines[-1].strip() if lines else ''}\n\n"


def _cli(args: list[str], timeout: int = RUN_TIMEOUT) -> str:
    """Runs the command line from the repository root and returns its output, exit code included."""
    try:
        note = _stale_note()
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        run = subprocess.run(_exe() + args + ["--no-color"], cwd=ROOT, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace", env=env)
    except subprocess.TimeoutExpired:
        return f"timed out after {timeout} s: creatio-tests {' '.join(args)}"
    out = (run.stdout or "") + (("\n" + run.stderr) if run.stderr.strip() else "")
    return note + out.strip() + f"\n\nexit code {run.returncode}"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig") if path.is_file() else f"{path.relative_to(ROOT)} does not exist"


def _first_comment(path: Path) -> str:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("# ").strip()
        if line:
            break
    return ""


@mcp.tool()
def overview() -> str:
    """What this utility is, where its cases and configuration live, and the commands the other tools run."""
    pages = sorted(p.stem for p in (ROOT / "Configuration" / "pages").glob("*.json"))
    processes = sorted(p.stem for p in (ROOT / "Configuration" / "processes").glob("*.json"))
    return "\n".join([
        f"Creatio UI test utility at {ROOT}",
        "",
        "Cases: UI cases in Cases/ (open a page, set, check, check-value, click ...), process cases in",
        "ProcessCases/ (start, check-result, check-record; no browser), analysis scripts in Analysis/.",
        f"Pages described: {', '.join(pages) or '(none)'}",
        f"Processes described: {', '.join(processes) or '(none)'}",
        "",
        "Loop for a new case: dsl() for the syntax -> page_config(name) / process_config(name) for the",
        "codes -> write the .act file (author) -> validate(filter) -> run(filter) -> last_report().",
        "A page that is not described yet: schemas(text) to find its schema name, then",
        "analyse('/0/Shell/#Card/<Schema>/edit/<recordId>', name).",
        "",
        "The command line behind these tools: " + " ".join(_exe()),
    ])


@mcp.tool()
def dsl() -> str:
    """The DSL reference (docs/dsl.md): every command, the element types, values, process cases, configuration files."""
    return _read(ROOT / "docs" / "dsl.md")


@mcp.tool()
def cases(folder: str = "") -> str:
    """Lists the .act files with their first comment line, and the bundled .act.exp examples (not run, copy one to .act).
    folder: Cases, ProcessCases, Analysis or empty for all."""
    folders = [folder] if folder else ["Cases", "ProcessCases", "Analysis"]
    lines = []
    for name in folders:
        directory = ROOT / name
        if not directory.is_dir():
            continue
        lines.append(f"{name}/")
        for path in sorted(list(directory.glob("*.act")) + list(directory.glob("*.act.exp"))):
            lines.append(f"  {path.name:<34} {_first_comment(path)}" + ("  [example]" if path.name.endswith(".exp") else ""))
    return "\n".join(lines) or "no cases found"


@mcp.tool()
def case(name: str) -> str:
    """The text of one case or example: a file name with or without .act / .act.exp, searched in Cases, ProcessCases and Analysis."""
    stem = name.removesuffix(".exp").removesuffix(".act")
    for folder in ("Cases", "ProcessCases", "Analysis"):
        for suffix in (".act", ".act.exp"):
            path = ROOT / folder / f"{stem}{suffix}"
            if path.is_file():
                return _read(path)
    return f"no case named {name}"


def _config_folders(base: str, key: str, default: list[str]) -> list[Path]:
    """Configuration/<base>, then the env config's <key> folders (a project's tests/<Package>/...), relative to the root;
    `default` when the key is absent, as the framework reads it."""
    env = ROOT / "Configuration" / "creatio.env.config.json"
    try:
        extra = json.loads(env.read_text(encoding="utf-8-sig")).get(key, default) if env.is_file() else default
    except ValueError:  # a config with comments: the framework reads it, this lookup falls back to Configuration/<base>
        extra = default
    return [ROOT / "Configuration" / base, *(ROOT / f for f in extra or [])]


def _find_config(base: str, key: str, default: list[str], name: str) -> str:
    found = next((p for folder in _config_folders(base, key, default) if (p := folder / f"{name}.json").is_file()), None)
    return _read(found or ROOT / "Configuration" / base / f"{name}.json")


@mcp.tool()
def page_config(name: str) -> str:
    """A page file from Configuration/pages or a PagesFolders entry of the env config (tests/<Package>/pages): the codes,
    labels and element types a case may address on that page."""
    return _find_config("pages", "PagesFolders", [], name)


@mcp.tool()
def process_config(name: str) -> str:
    """A process file from Configuration/processes or a ProcessCasesFolders entry of the env config (tests/<Package>/integration,
    where a generated process case keeps its file): the parameters, their types and directions a process case may use."""
    return _find_config("processes", "ProcessCasesFolders", ["ProcessCases"], name)


def _package_args(package: str, project: str) -> list[str]:
    return (["--package", package] if package else []) + (["--project", project] if package and project else [])


@mcp.tool()
def validate(filter: str = "", package: str = "", project: str = "") -> str:
    """Validates the cases without a browser or an environment: unknown codes, wrong operators, bad values. filter: part of a case name.
    A case with a `# framework: <text>` header is listed as `gap   <case>: <text>` (not runnable, not a problem).
    package / project: only the cases of <workspace>/tests/<package>/{integration,e2e} (as for run)."""
    return _cli(["--validate-only"] + (["--filter", filter] if filter else []) + _package_args(package, project), timeout=300)


@mcp.tool()
def run(filter: str = "", verbose: bool = False, task_folder: str = "", task: str = "", package: str = "", project: str = "") -> str:
    """Runs the cases against the configured environment and returns the report, its first line the site (`site: <url> (clio <env>)`). filter: part of a case name; runs everything when empty.
    task_folder: the loop's task folder - every case writes <task_folder>/evidence/<AC>-report-N.txt (from its `# ac:` line) and a draft
    report row; task: the task id named in that evidence.
    package: re-test a package - `dotnet test` of <workspace>/tests/<package>/unit (when it holds a project), then the cases of its
    integration/ and e2e/ folders only; the report's head is `package:`, `unit: N passed, M failed` (or `no unit project`),
    `integration: ...`, `e2e: ...`, `not runnable: K (framework gaps)`. project: the project.json whose package.workspace holds
    tests/; empty: the env config's folders (written by project.py sync --project) name the package's folder.
    A `# framework:` case is never started; it is listed under `Not runnable (framework gaps):` and does not change the exit code."""
    args = (["--filter", filter] if filter else []) + (["--verbose"] if verbose else []) + _package_args(package, project)
    args += (["--task-folder", task_folder] if task_folder else []) + (["--task", task] if task else [])
    out = _cli(args)
    # the answer begins with the site the run hit, ahead of a rebuild note (the env config is shared, gap 70)
    site = next((line for line in out.splitlines() if line.startswith("site: ")), None)
    return site + "\n" + out.replace(site + "\n", "", 1) if site else out


@mcp.tool()
def analyse(page_path: str, name: str, include_hidden: bool = False, dry_run: bool = False) -> str:
    """Describes a live page into Configuration/pages/<name>.json. page_path: '/0/Shell/#Card/<Schema>/edit/<recordId>'."""
    args = ["analyse", page_path, "--name", name, "--list"]
    if include_hidden:
        args.append("--include-hidden")
    if dry_run:
        args.append("--dry-run")
    return _cli(args, timeout=600)


@mcp.tool()
def schemas(text: str = "", list_pages: bool = False) -> str:
    """Finds the Freedom UI page schemas of the instance whose name contains text, with the address that opens each."""
    return _cli(["schemas"] + ([text] if text else []) + (["--list-pages"] if list_pages else []), timeout=120)


@mcp.tool()
def last_report(console: bool = True, limit: int = 400) -> str:
    """The newest run report under Reports/, followed by the browser console logs of its cases
    (Reports/console/<stamp>-<case>.log: every message, page error, failed and 4xx / 5xx request) - the
    file to read when a page misbehaves. `console=False` gives the report alone; `limit` is the most lines
    of each log returned (0 = all), the tail kept since the failure is usually last."""
    reports = sorted((ROOT / "Reports").glob("run-*.txt")) if (ROOT / "Reports").is_dir() else []
    if not reports:
        return "no report yet"
    out = [_read(reports[-1])]
    stamp = reports[-1].stem.removeprefix("run-")
    for log in sorted((ROOT / "Reports" / "console").glob(f"{stamp}-*.log")) if console else []:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        shown = lines[-limit:] if limit and len(lines) > limit else lines
        head = f"--- {log.name} ({len(lines)} lines" + (f", last {len(shown)}" if len(shown) < len(lines) else "") + ")"
        out.append("\n".join([head, *shown]))
    return "\n\n".join(out)


def main() -> None:
    if not CLI_PROJECT.is_dir():
        print(f"not a creatio-tests repository: {ROOT}", file=sys.stderr)
        sys.exit(2)
    mcp.run()


if __name__ == "__main__":
    main()
