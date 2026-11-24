"""Install a package with drift, task ownership, compilation and probe checks."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from .clio import Clio
from .files import read_text, write_text
from .schema import Descriptor


def _schemas(package: Path, manager: str):
    """Yield schema directories belonging to the requested manager."""
    for descriptor in sorted(package.glob("Schemas/*/descriptor.json")):
        data = json.loads(descriptor.read_text(encoding="utf-8-sig"))["Descriptor"]
        if data.get("ManagerName") == manager:
            yield descriptor.parent


def _needs_publish(package: Path) -> bool:
    """Identify processes containing script or user tasks."""
    for schema in _schemas(package, "ProcessSchemaManager"):
        text = (schema / "metadata.json").read_text(encoding="utf-8-sig")
        if "ProcessSchemaScriptTask" in text or "ProcessSchemaUserTask" in text:
            return True
    return False


def _git(package: Path, args: list[str], allow_not_repo: bool = False) -> str | None:
    """Run a read-only git command in the package's repository."""
    try:
        result = subprocess.run(["git", *args], cwd=package, capture_output=True, text=True, encoding="utf-8", check=False)
    except OSError as exc:
        raise RuntimeError(f"could not run git: {exc}") from exc
    if result.returncode:
        if allow_not_repo and "not a git repository" in result.stderr.lower():
            return None
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def _changed_files(package: Path) -> list[str]:
    """Return all changed package paths, including both sides of renames."""
    output = _git(package, ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--", str(package)])
    parts = output.split("\0")
    paths = []
    i = 0
    while i < len(parts) and parts[i]:
        record = parts[i]
        status, name = record[:2], record[3:]
        paths.append(name.replace("\\", "/"))
        i += 1
        if "R" in status or "C" in status:
            if i >= len(parts) or not parts[i]:
                raise RuntimeError("git status returned an incomplete rename")
            paths.append(parts[i].replace("\\", "/"))
            i += 1
    root = Path(_git(package, ["rev-parse", "--show-toplevel"]).strip()).resolve()
    result = []
    for name in paths:
        try:
            result.append((root / name).resolve().relative_to(package).as_posix())
        except ValueError as exc:
            raise RuntimeError(f"git status returned a path outside the package: {name}") from exc
    return result


def _task_conflicts(tasks: Path, current: Path, paths: list[str]) -> list[str]:
    """Find changed files owned by other unfinished tasks."""
    tasks, current = tasks.resolve(), current.resolve()
    if not tasks.is_dir() or not current.is_dir() or current.parent != tasks:
        raise RuntimeError("the current task must be a folder directly under the tasks folder")
    conflicts = []
    for task in sorted(tasks.iterdir()):
        if not task.is_dir() or task.resolve() == current or (task / "success-report.md").exists():
            continue
        lock = task / "schemas.json"
        if not lock.is_file():
            continue
        data = json.loads(lock.read_text(encoding="utf-8-sig"))
        schemas = {str(n).casefold() for n in data["schemas"]}
        files = {str(n).replace("\\", "/").casefold() for n in data.get("files", [])}
        hits = []
        for path in paths:
            parts = path.split("/")
            schema = parts[1].split(".")[0].casefold() if len(parts) > 1 and parts[0] in ("Schemas", "Resources", "SqlScripts", "Data") else ""
            if schema in schemas or path.casefold() in files:
                hits.append(path)
        if hits:
            conflicts.append(f"{task.name}: {', '.join(hits)}")
    return conflicts


def _touch_dates(descriptors: dict[str, Path], root: str, what: str) -> list[str]:
    """Advance `ModifiedOnUtc` of each descriptor ({name: path}); every other byte (BOM, CRLF) stays as it was."""
    updates = []
    for name, path in sorted(descriptors.items()):
        if not path.is_file():
            raise RuntimeError(f"changed {what} {name} has no descriptor")
        text, bom = read_text(path)
        descriptor = Descriptor(path, text, root=root)
        previous = descriptor.data.get("ModifiedOnUtc")
        descriptor.touch()
        updated = descriptor.data.get("ModifiedOnUtc")
        old_match = re.fullmatch(r"/Date\((\d+)\)/", str(previous))
        new_match = re.fullmatch(r"/Date\((\d+)\)/", str(updated))
        if not old_match or not new_match or int(new_match.group(1)) <= int(old_match.group(1)):
            raise RuntimeError(f"could not advance ModifiedOnUtc for {what} {name}; check its timestamp")
        updates.append((path, descriptor.text, bom))
    for path, text, bom in updates:
        write_text(path, text, bom)
    return [name for name, _ in sorted(descriptors.items())]


def _touch_sql_dates(package: Path, paths: list[str]) -> list[str]:
    """Stamp descriptors of changed SQL scripts without changing other bytes."""
    names = {parts[1] for path in paths if len(parts := path.split("/")) >= 3 and parts[0] == "SqlScripts"}
    return _touch_dates({n: package / "SqlScripts" / n / "descriptor.json" for n in names}, "SqlScript", "SQL script")


def _changed_beside(folders, name: str, top: str, paths: list[str] | None) -> list[str]:
    """Folders whose `name` file changed: in `paths` (git status against HEAD), or without git (`paths` None) the file
    written more than 2 s after its descriptor (a save writes both in one go; a later hand edit is what the date misses)."""
    names = []
    for folder in folders:
        file = folder / name
        if not file.is_file():
            continue
        if paths is None:
            if file.stat().st_mtime > (folder / "descriptor.json").stat().st_mtime + 2:
                names.append(folder.name)
        elif f"{top}/{folder.name}/{name}" in paths:
            names.append(folder.name)
    return names


def changed_processes(package: Path, paths: list[str] | None) -> list[str]:
    """Processes whose `metadata.json` changed. The install regenerates a process only when its `ModifiedOnUtc` moved."""
    return _changed_beside(_schemas(package, "ProcessSchemaManager"), "metadata.json", "Schemas", paths)


def changed_bindings(package: Path, paths: list[str] | None) -> list[str]:
    """Bindings whose `data.json` changed. The install applies a binding only when its `ModifiedOnUtc` differs from the
    site's (a changed data.json alone is not installed)."""
    return _changed_beside(sorted(d for d in package.glob("Data/*") if d.is_dir()), "data.json", "Data", paths)


def _touch_process_dates(package: Path, paths: list[str] | None) -> list[str]:
    processes = _touch_dates({n: package / "Schemas" / n / "descriptor.json" for n in changed_processes(package, paths)}, "Descriptor", "process")
    bindings = _touch_dates({n: package / "Data" / n / "descriptor.json" for n in changed_bindings(package, paths)}, "Descriptor", "binding")
    return processes + [f"binding {n}" for n in bindings]


SITE_MANAGER_SQL = ('select s."ManagerName" from "SysSchema" s join "SysPackage" p on p."Id" = s."SysPackageId" '
                    "where p.\"UId\" = '{uid}' and s.\"Name\" = '{schema}'")
SITE_SCHEMAS_SQL = ('select s."Name" "Schema", s."UId"::text "UId" from "SysSchema" s join "SysPackage" p on p."Id" = s."SysPackageId" '
                    "where p.\"UId\" = '{uid}'")


def _folder_uids(package: Path) -> dict[str, str]:
    """UId -> folder name of the schema folders here (a folder without a readable UId is left out)."""
    uids = {}
    for d in package.glob("Schemas/*/descriptor.json"):
        try:
            uids[str(uuid.UUID(json.loads(d.read_text(encoding="utf-8-sig"))["Descriptor"]["UId"]))] = d.parent.name
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return uids


def missing_schemas(package: Path, head: set[str] | None, site: dict[str, str] | None) -> tuple[list[str], list[str]]:
    """The schemas the install would delete, and the renames it does: a site row (name -> UId) of this package whose UId
    is a folder here under another name is `renamed <old> -> <new>`; any other name in git HEAD or on the site without a
    folder here is a deletion."""
    here, uids = {d.parent.name for d in package.glob("Schemas/*/descriptor.json")}, _folder_uids(package)
    renamed = {}
    for name, uid in (site or {}).items():
        try:
            new = uids.get(str(uuid.UUID(uid))) if name not in here else None
        except (ValueError, TypeError, AttributeError):
            new = None
        if new and new != name:
            renamed[name] = new
    gone = ((head or set()) | set(site or {})) - here - set(renamed)
    return sorted(gone), [f"renamed {old} -> {new}" for old, new in sorted(renamed.items())]


COMPILE_ERROR = re.compile(r"\berror\s+CS\d+", re.IGNORECASE)
PKG_IN_PATH = re.compile(r"Pkg[\\/]([^\\/]+)[\\/]")
PKG_IN_FILE = re.compile(r"([^\\/\s(]+?)\.([^.\\/\s(]+)\.cs\(")  # <Schema>.<Package>.cs(15,3): the generated source


def errors_by_package(log_text: str) -> dict[str, list[str]]:
    """The compiler error lines of a compilation log grouped by the package their file belongs to (`Pkg/<Pkg>/...` in the path,
    else the `<Schema>.<Package>.cs` name the configuration build gives a schema's source; `?` when neither), in log order."""
    groups: dict[str, list[str]] = {}
    for line in log_text.splitlines():
        if not COMPILE_ERROR.search(line):
            continue
        path, file = PKG_IN_PATH.search(line), PKG_IN_FILE.search(line)
        groups.setdefault(path.group(1) if path else file.group(2) if file else "?", []).append(line.strip())
    return groups


def stale_bin(package: Path, name: str) -> str | None:
    """Why `Files/Bin/<name>.dll` is older than the sources it should hold, or None. `push-pkg` installs that dll as it is: a
    class edited or deleted in `Files/cs` after the last build keeps running on the site (S44-T06). A deletion shows in the
    folder's own time, so a removed source counts whether git knows it or not."""
    sources = [p for root in ("Files/cs", "Files/src/cs") for p in (package / root).rglob("*.cs") if (package / root).is_dir()]
    folders = [d for root in ("Files/cs", "Files/src/cs") if (package / root).is_dir()
               for d in [package / root, *(x for x in (package / root).rglob("*") if x.is_dir())]]
    if not sources and not folders:
        return None
    dll = package / "Files" / "Bin" / f"{name}.dll"
    if not dll.is_file():
        return f"Files/Bin/{name}.dll is missing while Files/cs holds sources"
    built = dll.stat().st_mtime
    newest = max(sources + folders, key=lambda p: p.stat().st_mtime)
    if newest.stat().st_mtime <= built:
        return None
    minutes = int((newest.stat().st_mtime - built) // 60)
    what = newest.relative_to(package).as_posix() + ("/ (a file deleted or added there)" if newest.is_dir() else "")
    return f"Files/Bin/{name}.dll is older than Files/cs ({what}, {minutes} min newer)"


def _head_schemas(package: Path) -> set[str] | None:
    """The schema folders of the package at git HEAD; None outside git or before the first commit."""
    if _git(package, ["rev-parse", "--show-toplevel"], allow_not_repo=True) is None:
        return None
    try:
        out = _git(package, ["ls-tree", "--name-only", "HEAD", "Schemas/"])
    except RuntimeError:  # no HEAD yet, or the package is not in it
        return None
    return {Path(line).name for line in out.splitlines() if line.strip()}


def _csproj_references(text: str) -> set[str]:
    """Names of the <Reference>/<ProjectReference> items of a project file (the version part is dropped)."""
    return {m.split(",")[0].strip() for m in re.findall(r'<(?:Reference|ProjectReference)\s+Include="([^"]+)"', text)}


def _depends_on(text: str) -> set[str]:
    """`package:<Name>` of every DependsOn entry of a package descriptor."""
    return {"package:" + d["Name"] for d in json.loads(text.lstrip("\ufeff"))["Descriptor"].get("DependsOn") or []}


def dependency_changes(package: Path) -> tuple[list[str], list[str]] | str:
    """(dropped, added) against git HEAD: `package:<Name>` of descriptor.json DependsOn and `Files/<x>.csproj:<Reference>`
    of the project files; a reason string when there is nothing to compare with."""
    if _git(package, ["rev-parse", "--show-toplevel"], allow_not_repo=True) is None:
        return "skipped (no git)"
    try:
        _git(package, ["rev-parse", "--verify", "HEAD"])
        before = _depends_on(_git(package, ["show", "HEAD:./descriptor.json"]))
        listed = [n for n in _git(package, ["ls-tree", "--name-only", "HEAD", "Files/"]).splitlines() if n.endswith(".csproj")]
        for name in listed:
            before |= {f"{name}:{ref}" for ref in _csproj_references(_git(package, ["show", f"HEAD:./{name}"]))}
    except RuntimeError:
        return "skipped (the package is not committed)"
    now = _depends_on((package / "descriptor.json").read_text(encoding="utf-8-sig"))
    for csproj in package.glob("Files/*.csproj"):
        now |= {f"Files/{csproj.name}:{ref}" for ref in _csproj_references(csproj.read_text(encoding="utf-8-sig"))}
    return sorted(before - now), sorted(now - before)


FRAMEWORK = ("mscorlib", "System", "System.Core", "System.Drawing", "System.Data", "System.Xml", "System.Runtime.Serialization",
             "System.ServiceModel", "System.Web", "Facades/netstandard")
REFERENCE_ROOT = Path(r"C:\Program Files (x86)\Reference Assemblies\Microsoft\Framework\.NETFramework")
SOURCES_SQL = ('select ss."Name", ss."Source", (ss."ModifiedOn" >= s."ModifiedOn") "fresh" from "SysSchemaSource" ss '
               'join "SysSchema" s on s."Id" = ss."SysSchemaId" join "SysPackage" p on p."Id" = s."SysPackageId" '
               'where p."UId" = \'{uid}\' and ss."Name" in ({names})')


def script_processes(package: Path) -> list[str]:
    """Processes of the package with a script task: each has a generated `<Name>.cs` in SysSchemaSource after the install."""
    return [s.name for s in _schemas(package, "ProcessSchemaManager")
            if "ProcessSchemaScriptTask" in (s / "metadata.json").read_text(encoding="utf-8-sig")]


def creatio_bin(package: Path, given=None) -> Path | None:
    """The Creatio assemblies to compile against: `--bin`, then $CREATIO_BIN, then the TestCoreLibPath of the workspace's
    `tests/Directory.Build.props` (S15)."""
    if given or os.environ.get("CREATIO_BIN"):
        return Path(given or os.environ["CREATIO_BIN"])
    for root in Path(package).resolve().parents:
        props = root / "tests" / "Directory.Build.props"
        if props.is_file():
            m = re.search(r"<TestCoreLibPath>([^<]+)</TestCoreLibPath>", props.read_text(encoding="utf-8-sig"))
            return Path(m.group(1).strip()) if m else None
    return None


def _csc() -> Path | None:
    """csc.dll of the newest .NET SDK."""
    dotnet = shutil.which("dotnet")
    found = Path(dotnet).resolve().parent.glob("sdk/*/Roslyn/bincore/csc.dll") if dotnet else []
    versions = [(tuple(int(x) for x in re.findall(r"\d+", p.parents[2].name)), p) for p in found]
    return max(versions)[1] if versions else None


def compile_script(source: str, name: str, bin_dir: Path | None, extra=()) -> tuple[str, list[str]]:
    """Compile a generated process source as a net4.x library: ('ok' | 'failed' | 'not checked (<why>)', [`CS0103: ...`]).
    `extra` (the package's Files/cs) is compiled along so a script may call the package's own classes; only errors inside
    the process source count."""
    refs = next((REFERENCE_ROOT / v for v in ("v4.8", "v4.7.2") if (REFERENCE_ROOT / v / "mscorlib.dll").is_file()), None)
    csc = _csc()
    if bin_dir is None or not (Path(bin_dir) / "Terrasoft.Core.dll").is_file() or csc is None or refs is None:
        return "not checked (no binaries)", []
    bin_dir = Path(bin_dir)
    confs = sorted(bin_dir.parent.glob("conf/bin/*/Terrasoft.Configuration.dll"),
                   key=lambda p: int(p.parent.name) if p.parent.name.isdigit() else -1)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"{name}.cs"
        src.write_text(source, encoding="utf-8")
        args = ["-nologo", "-noconfig", "-nostdlib", "-target:library", "-nowarn:1701,1702", f'-out:"{Path(tmp) / "out.dll"}"']
        args += [f'-r:"{refs / f}.dll"' for f in FRAMEWORK if (refs / f"{f}.dll").is_file()]
        args += [f'-r:"{p}"' for p in sorted(bin_dir.glob("Terrasoft.*.dll")) + confs[-1:]]
        args += [f'"{p}"' for p in [src, *extra]]
        rsp = Path(tmp) / "args.rsp"  # the reference list is longer than a Windows command line
        rsp.write_text("\n".join(args), encoding="utf-8")
        try:
            run = subprocess.run(["dotnet", str(csc), f"@{rsp}"], capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", check=False)
        except OSError as exc:
            return f"not checked ({exc})", []
    out = run.stdout + run.stderr
    errors = [f"{m.group(2)}: {m.group(3).strip()}" for m in re.finditer(r"^(.*?)\(\d+,\d+\): error (CS\d+): (.*)$", out, re.M)
              if Path(m.group(1).strip()).name == src.name]
    if errors:
        return "failed", errors
    if run.returncode and " error CS" not in out:
        return f"not checked (csc: {(out.strip().splitlines() or ['exit ' + str(run.returncode)])[-1][:120]})", []
    return "ok", []


def _source_text(value) -> str:
    """SysSchemaSource.Source as text: clio returns the bytea as base64."""
    try:
        return base64.b64decode(str(value), validate=True).decode("utf-8-sig")
    except ValueError:
        return str(value or "")

ISCHANGED_TABLES = ("SysSchema", "SysPackageSchemaData", "SysPackageSqlScript")
BINDING_CHUNK = 50  # rows per `or` of keys


def _same(site, package) -> bool:
    """A site value and a binding value mean the same: empty = empty, numbers by value, the rest case-blind as text."""
    a, b = (("" if v is None or str(v).strip().lower() == "null" else str(v).strip()) for v in (site, package))
    try:
        return float(a) == float(b)
    except ValueError:
        return a.lower() == b.lower() or {a.lower(), b.lower()} <= {"true", "1"} or {a.lower(), b.lower()} <= {"false", "0", ""}


def binding_overwrites(package: Path, rows_of) -> tuple[list[str], list[str]]:
    """([`<object> <key>: <Column> site <v> -> package <v>`], [notes]) for the rows of every `Data/<Name>` binding whose
    key exists on the site with another value in a column the binding writes. `rows_of(sql)` runs a select."""
    from .data.binding import LOOKUP_TYPES, DataBinding
    from .files import DVT_OF
    from .records import ident
    lines, notes = [], []
    for b in DataBinding.all(package):
        keys = b.key_columns or (["Id"] if "Id" in b.columns else [])
        if not keys:
            notes.append(f"{b.name}: no key column, not compared")
            continue
        db = {n: n + "Id" if c["type"] in LOOKUP_TYPES else n for n, c in b.columns.items()}
        compared = [n for n in b.columns if n not in keys and n not in b.localized and b.columns[n]["type"] != DVT_OF["Binary"]
                    and db[n] not in ("CreatedOn", "ModifiedOn", "CreatedById", "ModifiedById")]
        rows = [r for r in b.rows() if all(r.get(k) not in (None, "") for k in keys)]
        if not rows or not compared:
            continue
        table, site = ident(b.schema_name), {}
        try:
            for i in range(0, len(rows), BINDING_CHUNK):
                where = " or ".join("(" + " and ".join(f"\"{ident(db[k])}\" = '{str(r[k]).replace(chr(39), chr(39) * 2)}'" for k in keys) + ")"
                                    for r in rows[i:i + BINDING_CHUNK])
                cols = ", ".join(f'"{ident(db[n])}"' for n in dict.fromkeys(keys + compared))
                for s in rows_of(f'select {cols} from "{table}" where {where}'):
                    site["|".join(str(s.get(db[k], "")).lower() for k in keys)] = s
        except RuntimeError as exc:  # an object the site does not have yet: nothing there to overwrite
            notes.append(f"{b.name}: not compared ({str(exc)[:120]})")
            continue
        for r in rows:
            s = site.get(b.key_of(r))
            if s is None:
                continue
            for n in compared:
                if n in r and not _same(s.get(db[n]), r[n]):
                    lines.append(f"{b.schema_name} {b.key_of(r)}: {n} site {s.get(db[n])!r} -> package {r[n]!r}"
                                 + (" (force update)" if b.columns[n]["force_update"] else ""))
    return lines, notes


NO_RESULT = "wrote no result"  # clio's own failure (environment, network), not an answer of the site
COMPILE_POLL_S, COMPILE_WAIT_S = 15, 600  # a clio without compile-package --wait: poll CompilationHistory, clio's own --wait-timeout
COMPILE_HISTORY_SQL = ('select "CreatedOn"::text "at", "Result" "ok" from "CompilationHistory" '
                       "where \"ProjectName\" = '{name}.csproj' order by \"CreatedOn\" desc limit 1")


class PublishError(RuntimeError):
    """A failed compile-configuration: the whole message chain, and whether a schema of the package is named in it."""

    def __init__(self, text: str, verdict: str):
        super().__init__(text)
        self.text, self.verdict = text, verdict


def resolve_task(task: Path | str | None, tasks: Path | str | None = None, project: Path | str | None = None) -> Path | None:
    """The task folder: an absolute `task`, or a relative one that exists from here, as it is; otherwise its name under
    `tasks`, else under the project's `paths.tasks` (relative to project.json) - so the push log and the ownership check
    meet the folder the project means, not the server's cwd (a `task=001-...` from an MCP call landed in the cwd)."""
    if task is None:
        return None
    task = Path(task)
    if task.is_absolute() or task.is_dir():
        return task
    base = Path(tasks) if tasks else None
    if base is None and project:
        project_path = Path(project).resolve()
        try:
            value = json.loads(project_path.read_text(encoding="utf-8-sig"))["paths"]["tasks"]
        except (OSError, ValueError, KeyError, TypeError):
            value = None
        if value:
            base = Path(value) if Path(value).is_absolute() else project_path.parent / value
    return (base / task.name) if base is not None else task


def details_path(package: Path, task: Path | None = None) -> Path:
    """Where the whole push log goes when the answer is the summary: the task folder (next to its evidence), else temp."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = Path(task) if task else Path(tempfile.gettempdir()) / "creatio-push"
    return folder / f"push-{Path(package).name}-{stamp}.log"


def push(package: Path, env: str, clio: Clio, probe: bool = False, dry_run: bool = False, log=print, *,
         details: Path | None = None, **options) -> int:
    """Push a package, stopping on the first failed step. With `details` the whole log is written there and `log` gets
    the summary only (the step lines, no indented detail) and `details: <file>`."""
    if details is None:
        return _push(package, env, clio, probe, dry_run, log, lambda line: None, **options)
    lines: list[str] = []

    def summary(line: str) -> None:
        lines.append(line)
        if not line.startswith("  "):
            log(line)

    try:
        return _push(package, env, clio, probe, dry_run, summary, lines.append, **options)
    finally:
        path = Path(details)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log(f"details: {path}")


def _push(package: Path, env: str, clio: Clio, probe: bool, dry_run: bool, log, detail, *,
          project: Path | None = None, tasks: Path | None = None, task: Path | None = None,
          force: bool = False, baseline: Path | None = None, skip_drift: bool = False,
          skip_foreign_files: bool = False, skip_sql_dates: bool = False,
          skip_compile_package: bool = False, bin_dir: Path | None = None, allow_removed: list[str] | None = None,
          skip_stale_bin: bool = False) -> int:
    package = Path(package).resolve()
    allowed = sorted({s.strip() for s in allow_removed or [] if s.strip()})
    try:
        descriptor = json.loads((package / "descriptor.json").read_text(encoding="utf-8-sig"))["Descriptor"]
        pkg_name, assembly = descriptor["Name"], descriptor.get("Type") == 1
    except (OSError, ValueError, KeyError) as exc:
        log(f"package: FAILED {str(exc)[:200]}")
        log("push FAILED at package")
        return 1
    start = time.monotonic()
    version = clio.version()
    log(f"clio: {version}")
    statements = [f'update "{table}" set "IsChanged"=false' for table in ISCHANGED_TABLES]
    commit, changed, compilation_log = None, None, ""

    def command(args, cwd=None):
        if dry_run:
            log("  " + subprocess.list2cmdline(["clio", *args]))
            return ""
        return clio.run(args, cwd=cwd)

    def git_context():
        nonlocal commit, changed
        if changed is not None:
            return
        root = _git(package, ["rev-parse", "--show-toplevel"], allow_not_repo=True)
        if root is None:
            changed = []
            return
        commit = _git(package, ["log", "-1", "--format=%cI", "--", str(package)]).strip()
        if not commit:
            raise RuntimeError("package has no git commit; drift cannot be checked")
        try:
            datetime.fromisoformat(commit.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError(f"invalid git commit timestamp: {commit}") from exc
        changed = _changed_files(package)

    def drift():
        if skip_drift:
            return "skipped"
        if dry_run:
            log(f"  git log -1 --format=%cI -- {package}")
            log(f'  clio execute-sql-script -f <drift.sql> -v json -d <result.json> -e {env}')
            return "dry run"
        git_context()
        if commit is None:
            return "skipped (no git)"
        try:
            uid = str(uuid.UUID(descriptor["UId"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise RuntimeError("package descriptor has no valid UId") from exc
        # SysSchema has no PackageUId on 8.x: the package is SysPackageId -> SysPackage.Id, whose UId the descriptor holds.
        query = ('select s."Name", s."ModifiedOn" from "SysSchema" s join "SysPackage" p on p."Id" = s."SysPackageId" '
                 f'where p."UId" = \'{uid}\' and s."ModifiedOn" > \'{commit}\'')
        try:
            rows = clio.execute_sql_rows(query)
        except RuntimeError as exc:
            if NO_RESULT not in str(exc):
                raise
            detail(f"  {exc}")
            return "not checked (clio returned no result)"
        if rows and not force:
            raise RuntimeError(", ".join(str(row["Name"]) for row in rows))
        return f"forced ({len(rows)} changed)" if rows else "ok"

    def package_schemas():
        if dry_run:
            log("  git ls-tree --name-only HEAD Schemas/")
            log(f'  select s."Name" from "SysSchema" ... where p."UId" = <package UId> -e {env}')
            return "dry run"
        head, site, note = _head_schemas(package), None, ""
        try:
            site = {str(r["Schema"]): str(r.get("UId") or "") for r in clio.execute_sql_rows(SITE_SCHEMAS_SQL.format(uid=uuid.UUID(descriptor["UId"])))}
        except (RuntimeError, KeyError, ValueError, TypeError) as exc:  # no site answer: HEAD alone decides
            detail(f"  site schemas: {exc}")
            note = " (site not checked)"
        here = {d.parent.name for d in package.glob("Schemas/*/descriptor.json")}
        still = [s for s in allowed if s in here]
        if still:
            raise RuntimeError("--allow-removed names a schema still in the package folder: " + ", ".join(still))
        for schema in allowed:  # the merge's check: a NO ACTION key to the removed row rolls the whole install back
            managers = [str(r["ManagerName"]) for r in clio.execute_sql_rows(SITE_MANAGER_SQL.format(
                uid=uuid.UUID(descriptor["UId"]), schema=schema.replace("'", "''")))]
            from .describe.merge import references
            reader = SimpleNamespace(sql=clio.execute_sql_rows)  # references() reads through env.sql
            refs = [r for m in managers for r in references(reader, schema, [pkg_name], m)]
            if refs:
                raise RuntimeError(f"{schema} is still referenced: " + "; ".join(
                    re.sub(r"^references: (\S+ \d+ rows).*$", r"\1", r) for r in refs))
        gone, renamed = missing_schemas(package, head, site)
        missing = [s for s in gone if s not in allowed]
        if missing:  # no --force: the installer deletes them, and a foreign key rolls the whole install back
            raise RuntimeError("package install deletes schemas absent from the package: " + ", ".join(missing))
        done = ("ok" if head is not None or site is not None else "not checked (no git, no site)") + note
        done += "".join(f"; {r}" for r in renamed)  # same UId under a new name: the install renames the row
        return done + (f"; removal allowed: {', '.join(allowed)}" if allowed else "")

    def bindings():
        if not (package / "Data").is_dir():
            return "not needed"
        if dry_run:
            log(f'  select <key and bound columns> from "<object>" where <binding keys> -e {env}  (each Data/<Name>)')
            return "dry run"
        lines, notes = binding_overwrites(package, clio.execute_sql_rows)
        # The install writes only the force-update columns of a row that exists (verified on the test site, S33-T01).
        forced = [line for line in lines if line.endswith("(force update)")]
        kept = [line for line in lines if not line.endswith("(force update)")]
        for line in notes + forced:
            log(f"  {line}")
        for line in kept:
            detail(f"  {line}")
        if kept:
            log(f"  {len(kept)} value(s) on the site differ and are not overwritten")
        if forced and not force:
            raise RuntimeError(f"{len(forced)} force-update value(s) on the site would be overwritten (listed above); --force pushes anyway; "
                               "a push cannot skip a binding (P-2.18): one page goes by push.py page")
        counts = f"{len(kept)} differ, not overwritten" if kept else ""
        if forced:
            return f"forced ({len(forced)} overwritten" + (f", {counts})" if counts else ")")
        return f"ok ({counts})" if counts else "ok"

    def dependencies():
        if dry_run:
            return "dry run"
        changes = dependency_changes(package)
        if isinstance(changes, str):
            return changes
        dropped = changes[0]
        if dropped and not force:
            raise RuntimeError("dropped " + ", ".join(sorted(d.split(":", 1)[1] for d in dropped)))
        return f"forced (dropped {len(dropped)})" if dropped else "ok"

    def foreign_files():
        if skip_foreign_files:
            return "skipped"
        folder = Path(tasks) if tasks else None
        if folder is None and project:
            project_path = Path(project).resolve()
            config = json.loads(project_path.read_text(encoding="utf-8-sig"))
            value = config["paths"]["tasks"]
            folder = Path(value)
            if not folder.is_absolute():
                folder = project_path.parent / folder
        if folder is None:
            return "skipped (no tasks folder)"
        if task is None:
            raise RuntimeError("--task is required when a tasks folder is configured")
        if dry_run:
            log(f"  git status --porcelain -- {package}")
            return "dry run"
        git_context()
        if commit is None:
            raise RuntimeError("cannot check uncommitted task files without git")
        conflicts = _task_conflicts(folder, resolve_task(task, tasks, project), changed)
        if conflicts:
            raise RuntimeError("; ".join(conflicts))
        return "ok"

    def sql_dates():
        if skip_sql_dates:
            return "skipped"
        if dry_run:
            log(f"  git status --porcelain -- {package}")
            log("  update ModifiedOnUtc for changed SQL scripts")
            return "dry run"
        git_context()
        if commit is None:
            return "skipped (no git)"
        names = _touch_sql_dates(package, changed)
        return ", ".join(names) if names else "not needed"

    def process_dates():
        if skip_sql_dates:
            return "skipped"
        if dry_run:
            log("  update ModifiedOnUtc for changed processes")
            log("  update ModifiedOnUtc for changed bindings")
            return "dry run"
        git_context()
        names = _touch_process_dates(package, changed if commit is not None else None)
        return ", ".join(names) if names else "not needed"

    def clear():
        for statement in statements:
            if dry_run:
                command(["execute-sql-script", statement, "-e", env])
            else:
                clio.execute_sql(statement)
        return "dry run" if dry_run else "ok (" + ", ".join(ISCHANGED_TABLES) + ")"

    def install():
        command(["push-pkg", pkg_name, "-e", env], cwd=package.parent)
        return "dry run" if dry_run else "ok"

    def compilation():
        nonlocal compilation_log
        compilation_log = command(["last-compilation-log", "-e", env])
        if dry_run:
            return "dry run"
        summaries = [line for line in compilation_log.splitlines() if "Finished building project:" in line]
        if not summaries:
            raise RuntimeError("compilation summary not found")
        summary = summaries[-1]
        log(f"  {summary}")
        match = re.search(r"\bErrors:\s*(\d+)\b", summary)
        if not match:
            raise RuntimeError(summary)
        if int(match.group(1)) and baseline is None and not (assembly and not skip_compile_package):
            groups = errors_by_package(compilation_log)
            for lines in groups.values():
                log(f"  {lines[0]}")
            if groups:
                raise RuntimeError("compile FAILED: " + ", ".join(f"{len(v)} error(s) in {k}" for k, v in groups.items())
                                   + ("" if pkg_name in groups else f" (none in {pkg_name})"))
            raise RuntimeError(summary)
        return "ok"

    def compile_package():
        if skip_compile_package:
            return "skipped"
        if not assembly:
            return "not needed"
        try:
            output = command(["compile-package", pkg_name, "-e", env, "--wait"])
        except RuntimeError as exc:
            if not re.search(r"Option 'wait' is unknown", str(exc)):
                raise
            return compile_and_poll()
        if output.strip():
            log(f"  {output.strip().splitlines()[-1]}")
        return "dry run" if dry_run else "ok"

    def compile_and_poll():
        """compile-package without --wait, then the package's CompilationHistory row polled until a new one is written."""
        sql = COMPILE_HISTORY_SQL.format(name=pkg_name.replace("'", "''"))
        before = next((str(r.get("at")) for r in clio.execute_sql_rows(sql)), "")
        output = command(["compile-package", pkg_name, "-e", env])
        if output.strip():
            log(f"  {output.strip().splitlines()[-1]}")
        began = time.monotonic()
        while True:
            row = next(iter(clio.execute_sql_rows(sql)), None)
            waited = int(time.monotonic() - began)
            if row is not None and str(row.get("at")) != before:
                if str(row.get("ok")).lower() not in ("true", "1"):
                    raise RuntimeError(f"CompilationHistory: {pkg_name}.csproj failed (clio {version}: no --wait, polled {waited} s)")
                return f"ok (clio {version}: no --wait, polled {waited} s)"
            if waited >= COMPILE_WAIT_S:
                raise RuntimeError(f"no new CompilationHistory row for {pkg_name}.csproj in {waited} s (clio {version}: no --wait)")
            time.sleep(COMPILE_POLL_S)

    def check_baseline():
        if baseline is None:
            return "skipped"
        if dry_run:
            log(f"  compare compilation errors with {baseline}")
            return "dry run"
        errors = [line.strip() for line in compilation_log.splitlines()
                  if re.search(r"\berror\b", line, re.IGNORECASE) and not re.search(r"\bErrors:\s*\d+", line)]
        summary = next(line for line in reversed(compilation_log.splitlines()) if "Finished building project:" in line)
        count = int(re.search(r"\bErrors:\s*(\d+)\b", summary).group(1))
        if count and not errors:
            raise RuntimeError("compilation reported errors but no error lines were found")
        path = Path(baseline)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8", newline="\n") as out:
                out.write("\n".join(errors) + ("\n" if errors else ""))
            return f"created ({len(errors)} errors)"
        previous = set(path.read_text(encoding="utf-8-sig").splitlines())
        new = [line for line in errors if line not in previous]
        if new:
            raise RuntimeError("; ".join(new))
        return "ok"

    def publish():
        if not _needs_publish(package):
            return "not needed"
        if not dry_run:
            log("publish: started")
        try:
            output = command(["compile-configuration", "-e", env])
        except RuntimeError as exc:
            from .runs import trim_error
            text = trim_error(str(exc))
            ours = sorted(d.parent.name for d in package.glob("Schemas/*/descriptor.json")
                          if re.search(rf"(?<!\w){re.escape(d.parent.name)}(?!\w)", text))
            raise PublishError(text, "pushed schemas among the failed: " + ", ".join(ours) if ours
                               else "no schema of this package is named in the error") from exc
        if output.strip():
            log(f"  {output.strip().splitlines()[-1]}")
        return "dry run" if dry_run else "ok"

    def scripts():
        names = script_processes(package)
        if not names:
            return "not needed"
        if dry_run:
            log(f'  select "Source" from "SysSchemaSource" where "Name" in (<{len(names)} process>.cs) -e {env}; csc each')
            return "dry run"
        uid = str(uuid.UUID(descriptor["UId"]))
        rows = clio.execute_sql_rows(SOURCES_SQL.format(uid=uid, names=", ".join(f"'{n}.cs'" for n in names)))
        by_name = {r["Name"]: r for r in rows}
        extra = sorted((package / "Files" / "cs").rglob("*.cs")) if (package / "Files" / "cs").is_dir() else []
        bad, unchecked = [], []
        for name in names:
            row = by_name.get(f"{name}.cs")
            if row is None:
                bad.append(f"process {name}: no generated source after the install")
                continue
            if str(row.get("fresh")).lower() not in ("true", "1"):  # a changed process is regenerated by the install, after its row
                bad.append(f"process {name}: generated source older than its schema (not regenerated by the install)")
                continue
            status, errors = compile_script(_source_text(row.get("Source")), name, creatio_bin(package, bin_dir), extra)
            if status == "failed":
                bad += [f"process {name}: script does not compile: {e}" for e in errors]
            elif status != "ok":
                unchecked.append(f"process {name}: script compile {status}")
        for line in unchecked + bad:
            log(f"  {line}")
        if bad:
            raise RuntimeError(bad[0] + (f" (+{len(bad) - 1} more)" if len(bad) > 1 else ""))
        checked = len(names) - len(unchecked)
        return f"ok ({checked} compiled, {len(unchecked)} not checked)" if unchecked else f"ok ({checked} compiled)"

    def bin_age():
        if not assembly:
            return "n/a (not an assembly package)"
        why = stale_bin(package, pkg_name)
        if why is None:
            return "ok" if (package / "Files" / "Bin" / f"{pkg_name}.dll").is_file() else "n/a (no Files/cs)"
        if skip_stale_bin:
            return f"skipped (--skip-stale-bin): {why}"
        raise RuntimeError(f"{why}: build the package (dotnet build, or the pipeline's build) and push again; --skip-stale-bin passes")

    steps = (("drift", drift), ("package schemas", package_schemas), ("stale bin", bin_age), ("bindings", bindings), ("dependencies", dependencies),
             ("foreign files", foreign_files), ("sql dates", sql_dates), ("process dates", process_dates),
             ("clear IsChanged", clear), ("push-pkg", install), ("script compile", scripts), ("compilation log", compilation),
             ("compile-package", compile_package), ("baseline", check_baseline), ("publish", publish))
    ran = 0
    for name, step in steps:
        try:
            result = step()
        except PublishError as exc:  # the whole error: the cut one hid which schema failed
            log(f"{name}: FAILED {exc.text}")
            log(f"{name}: {exc.verdict}")
            log(f"push FAILED at {name}")
            return 1
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            log(f"{name}: FAILED {str(exc)[:200]}")
            if len(str(exc)) > 200:
                detail(f"  {exc}")
            log(f"push FAILED at {name}")
            return 1
        log(f"{name}: {result}")
        ran += not str(result).startswith("skipped")

    if probe:
        try:
            skipped = _run_probes(package, env, dry_run, log)
            if not dry_run:
                caption_probe(package, descriptor.get("UId"), clio.execute_sql_rows, log)
        except RuntimeError as exc:
            log(f"probes: FAILED {str(exc)[:200]}")
            log("push FAILED at probes")
            return 1
        log("probes: ok" + (f" ({len(skipped)} skipped: {', '.join(skipped)})" if skipped else ""))

    if dry_run:
        log(f"dry run of {pkg_name} -> {env}: {ran} of {len(steps)} steps would run, nothing sent")
        return 0
    log(f"pushed {pkg_name} to {env} in {int(time.monotonic() - start)} s")
    return 0


def caption_probe(package: Path, package_uid, rows_of, log) -> list[str]:
    """For every schema of the package that has a default-culture `Caption` in its resources: the site's `SysSchema.Caption` against it.
    A difference is the line `caption of <X> not updated: site '<a>', package '<b>'` (logged, not a failure): after a push the
    caption of a process stayed old although the resource file carried the new one."""
    from .resources import Resources
    captions = {}
    for folder in sorted((package / "Schemas").glob("*")):
        for res in sorted((package / "Resources").glob(folder.name + ".*")):
            text = Resources(res).get("Caption") if res.is_dir() else None
            if text:
                captions[folder.name] = text
                break
    if not captions:
        return []
    try:
        uid = str(uuid.UUID(str(package_uid)))
    except ValueError:
        return []
    names = ", ".join("'" + n.replace("'", "''") + "'" for n in captions)
    rows = rows_of('select s."Name", s."Caption" from "SysSchema" s join "SysPackage" p on p."Id" = s."SysPackageId" '
                   f"where p.\"UId\" = '{uid}' and s.\"Name\" in ({names})")
    out = [f"caption of {r['Name']} not updated: site '{r.get('Caption') or ''}', package '{captions[r['Name']]}'"
           for r in rows if r.get("Name") in captions and (r.get("Caption") or "") != captions[r["Name"]]]
    for line in out:
        log(f"  {line}")
    return out


def _run_probes(package: Path, env: str, dry_run: bool, log) -> list[str]:
    """Run object and SQL script probes for package items; the names of the items a probe skipped."""
    skipped: list[str] = []
    tools = Path(__file__).resolve().parent.parent
    items = [(tools / "objects" / "objects.py", p.name) for p in _schemas(package, "EntitySchemaManager")]
    items += [(tools / "sqlscripts" / "sqlscripts.py", p.parent.name)
              for p in sorted(package.glob("SqlScripts/*/descriptor.json"))]
    for script, name in items:
        args = [sys.executable, str(script), "probe", str(package), name, "--env", env]
        if dry_run:
            log("  " + subprocess.list2cmdline(args))
            continue
        try:
            result = subprocess.run(args, capture_output=True, text=True, check=False)
        except OSError as exc:
            raise RuntimeError(f"probe {name}: {exc}") from exc
        output = result.stdout + result.stderr
        for line in output.splitlines():
            log(f"  probe {name}: {line}")
        if result.returncode:
            raise RuntimeError(f"probe {name} exited {result.returncode}: {output[-500:]}")
        if any(line.startswith("skipped:") for line in output.splitlines()):
            skipped.append(name)
    return skipped
