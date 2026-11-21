"""A pulled package reviewed: the working copy against git HEAD sorted into what matters and what does not.

    review_download(package)                         the classes below, as text
    review_download(package, keep=["UsrOrder"])      + the files that would be restored from HEAD (every change outside
                                                       the kept items); `apply=True` runs `git checkout HEAD -- <path>`

Classes: files that differ from HEAD only in line endings or a BOM (read over the bytes - what `git diff -w
--ignore-cr-at-eol` would call empty); the items changed in content (`schema_diff`'s lines, renames by UId included);
dependencies dropped or added (descriptor.json `DependsOn`, the csproj references); resource folders with no schema;
files git does not track. Git is only read, except `apply`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

BOM = b"\xef\xbb\xbf"


def _git(cwd: Path, args: list[str], binary: bool = False):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    except OSError as e:
        raise RuntimeError(f"could not run git: {e}") from e
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.decode(errors='replace').strip() or 'failed'}")
    return r.stdout if binary else r.stdout.decode("utf-8", errors="replace")


def _status(package: Path) -> list[tuple[str, str]]:
    """[(two-letter status, path relative to the package)] of every change under the package, renames as their new path."""
    parts = _git(package, ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "."]).split("\0")
    top = Path(_git(package, ["rev-parse", "--show-toplevel"]).strip()).resolve()
    prefix = package.resolve().relative_to(top).as_posix()
    out, i = [], 0
    while i < len(parts) and parts[i]:
        status, path = parts[i][:2], parts[i][3:]
        i += 2 if ("R" in status or "C" in status) else 1  # a rename carries its old path as the next record
        out.append((status, path[len(prefix) + 1:] if prefix and path.startswith(prefix + "/") else path))
    return out


def _normal(raw: bytes) -> bytes:
    raw = raw[len(BOM):] if raw.startswith(BOM) else raw
    return raw.replace(b"\r\n", b"\n")


def owner_of(rel: str) -> str | None:
    """The item a package file belongs to: Schemas/<S>/.., Resources/<S>.<kind>/.., SqlScripts/<S>/.., Data/<S>/.. -> S."""
    parts = rel.split("/")
    if len(parts) > 2 and parts[0] in ("Schemas", "SqlScripts", "Data"):
        return parts[1]
    if len(parts) > 2 and parts[0] == "Resources":
        return parts[1].split(".", 1)[0]
    return None


def review(package: Path | str, keep: list[str] | None = None, apply: bool = False) -> dict:
    """{package, eol_only, content, dependencies {dropped, added} | reason, orphans, untracked, restore, applied}."""
    from ..push import dependency_changes
    from .diff import schema_diff
    package = Path(package).resolve()
    if not (package / "descriptor.json").is_file():
        raise FileNotFoundError(f"{package} is not a package folder (no descriptor.json)")
    changes = _status(package)
    eol_only, untracked, tracked = [], [], []
    for status, rel in changes:
        if status == "??":
            untracked.append(rel)
            continue
        tracked.append((status, rel))
        if "M" in status and (package / rel).is_file():
            try:
                head = _git(package, ["show", f"HEAD:./{rel}"], binary=True)
            except RuntimeError:
                continue
            if _normal(head) == _normal((package / rel).read_bytes()):
                eol_only.append(rel)
    deps = dependency_changes(package)
    schemas = {p.name for p in (package / "Schemas").iterdir() if p.is_dir()} if (package / "Schemas").is_dir() else set()
    orphans = sorted(p.name for p in (package / "Resources").iterdir()
                     if p.is_dir() and p.name.split(".", 1)[0] not in schemas) if (package / "Resources").is_dir() else []
    answer = {"package": package.name, "changed": len(changes), "eol_only": eol_only, "untracked": untracked, "orphans": orphans,
              "dependencies": {"dropped": [d.split(":", 1)[1] for d in deps[0]], "added": [d.split(":", 1)[1] for d in deps[1]]}
              if not isinstance(deps, str) else deps,
              "content": schema_diff(package), "restore": [], "applied": False}
    if keep is not None:
        kept = {k.lower() for k in keep}
        answer["restore"] = [rel for status, rel in tracked if (owner_of(rel) or "").lower() not in kept]
        if apply:
            for rel in answer["restore"]:
                _git(package, ["checkout", "HEAD", "--", rel])
            answer["applied"] = True
    return answer


MAX_STAGED = 5 * 1024 * 1024
ARCHIVES = (".rar", ".zip", ".7z", ".gz", ".bak")
BINARIES = (".dll", ".exe", ".pdb")
# what a clio workspace keeps beside packages/ (the loop's files included); anything else at the root is refused
KNOWN_ROOTS = (".gitignore", ".gitattributes", ".editorconfig", "README.md", "project.json", ".clio", ".vscode", "tasks", "docs")


def _assembly_package(workspace: Path, name: str) -> bool:
    import json
    try:
        return json.loads((workspace / "packages" / name / "descriptor.json").read_text(encoding="utf-8-sig"))["Descriptor"].get("Type") == 1
    except (OSError, ValueError, KeyError):
        return False


def setting_bindings(workspace: Path, rel: str, allowed: set[str]) -> list[str]:
    """The lines for a staged `packages/<P>/Data/SysSettingsValue*/data.json`: one per row, `<path>: sets system setting <Code> = <value>
    on every environment it is installed on` (a binding overwrites the value everywhere the package goes, a test value included).
    The Code comes from a `SysSettings` binding of the workspace, else the setting's Id; a code in `allowed` passes."""
    from ..access import setting_value, _type_hint
    from ..data import DataBinding
    parts = rel.split("/")
    if not (len(parts) == 5 and parts[0] == "packages" and parts[2] == "Data" and parts[3].startswith("SysSettingsValue") and parts[4] == "data.json"):
        return []
    package = workspace / "packages" / parts[1]
    try:
        rows = DataBinding(package, parts[3]).rows()
    except (OSError, ValueError, KeyError):
        return [f"{rel}: a system setting value binding that could not be read"]
    codes = {}
    for pkg in sorted((workspace / "packages").glob("*")):
        for b in DataBinding.all(pkg) if (pkg / "Data").is_dir() else []:
            if b.schema_name == "SysSettings":
                codes.update({str(r.get("Id")).lower(): r.get("Code") for r in b.rows(culture="en-US")})
    out = []
    for r in rows:
        sid = str(r.get("SysSettings") or "").lower()
        code = codes.get(sid) or sid or "?"
        if code in allowed:
            continue
        out.append(f"{rel}: sets system setting {code} = {setting_value(r, _type_hint(r)) or 'null'} on every environment it is installed on")
    return out


def allowed_settings(workspace: Path) -> set[str]:
    """`allowedSettingBindings` of the workspace's project.json: the setting codes a package may carry a value for."""
    import json
    try:
        return set(json.loads((workspace / "project.json").read_text(encoding="utf-8-sig")).get("allowedSettingBindings") or [])
    except (OSError, ValueError):
        return set()


def _column_names(text: str) -> set[str]:
    """The column names an object's metadata.json defines (the JSON form or the diff form of a replacing copy)."""
    from ..workspace import parse_diff

    if not text.strip():
        return set()
    if text.lstrip("\ufeff").startswith("{"):
        return {c["A2"] for c in json.loads(text.lstrip("\ufeff"))["MetaData"]["Schema"].get("D2", []) if c.get("A2")}
    return {json.loads(v)["A2"] for op, path, v in parse_diff(text) if op in "+=" and path == "MetaData.Schema.D2" and v.startswith("{")}


def site_clashes(workspace: Path, rel: str, notes: list[str]) -> list[str]:
    """S31-T12: a staged object whose new columns (against HEAD) or whose new schema the last `index --env` pass found on the site."""
    from .site import NO_PASS, column_clash, schema_clash

    parts = rel.split("/")
    if len(parts) != 5 or parts[0] != "packages" or parts[2] != "Schemas" or parts[4] != "metadata.json":
        return []
    package, name = workspace / "packages" / parts[1], parts[3]
    try:
        desc = json.loads(_git(workspace, ["show", f":./packages/{parts[1]}/Schemas/{name}/descriptor.json"]).lstrip("\ufeff"))["Descriptor"]
    except (RuntimeError, ValueError, KeyError):
        return []
    if desc.get("ManagerName") != "EntitySchemaManager":
        return []
    try:
        head = _git(workspace, ["show", f"HEAD:./{rel}"])
    except RuntimeError:  # not in HEAD: a new schema
        head = None
    out = []
    staged = _column_names(_git(workspace, ["show", f":./{rel}"]))
    found = [schema_clash(package, name)] if head is None and not desc.get("ExtendParent") else []
    found += [column_clash(package, name, col) for col in sorted(staged - _column_names(head or ""))]
    for hit in found:
        if hit is None:
            continue
        level, line = hit
        if level == "stop":
            out.append(f"{rel}: {line.split('; --force')[0]}")
        elif line not in notes and (level == "note" and line == NO_PASS or level == "warn"):
            notes.append(line)
    return out


def precommit(workspace: Path | str, notes: list[str] | None = None) -> list[str]:
    """`<path>: <reason>` for each staged file (added, copied, modified, renamed) that must not be committed: over 5 MB,
    an archive, a binary outside `packages/<P>/Files/Bin` of an assembly package, a file outside `packages/` and the
    known roots, a system setting value binding (`setting_bindings`), an object whose new columns or new schema the site already has
    (`site_clashes`, S31-T12; `notes` collects what does not stop: `no site pass yet`, a physical column). Paths are relative to the
    workspace; files outside it are not looked at."""
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise FileNotFoundError(f"{workspace} is not a folder")
    staged = [p for p in _git(workspace, ["diff", "--cached", "--name-only", "-z", "--relative", "--diff-filter=ACMR"]).split("\0") if p]
    out = []
    allowed = allowed_settings(workspace)
    for rel in staged:
        parts, low = rel.split("/"), rel.lower()
        out += setting_bindings(workspace, rel, allowed)
        out += site_clashes(workspace, rel, notes if notes is not None else [])
        size = int(_git(workspace, ["cat-file", "-s", f":./{rel}"]).strip() or 0)
        if size > MAX_STAGED:
            out.append(f"{rel}: {size / 1024 / 1024:.1f} MB (over 5 MB)")
        if low.endswith(ARCHIVES):
            out.append(f"{rel}: an archive")
        elif low.endswith(BINARIES) and not (len(parts) > 4 and parts[0] == "packages" and parts[2:4] == ["Files", "Bin"]
                                            and _assembly_package(workspace, parts[1])):
            out.append(f"{rel}: a binary outside Files/Bin of an assembly package")
        if parts[0] != "packages" and parts[0] not in KNOWN_ROOTS:
            out.append(f"{rel}: outside packages/ (known roots: {', '.join(KNOWN_ROOTS)})")
    return out


def render(answer: dict, limit: int = 0) -> str:
    """`limit` cuts the content lines (0 = all)."""
    from .core import cut
    lines = [f"{answer['package']}: {answer['changed']} changed file(s) against HEAD"]
    if answer["eol_only"]:
        lines.append(f"line endings or BOM only ({len(answer['eol_only'])}) - nothing changed:")
        lines += [f"  {p}" for p in answer["eol_only"]]
    deps = answer["dependencies"]
    if isinstance(deps, str):
        lines.append(f"dependencies: {deps}")
    elif deps["dropped"] or deps["added"]:
        lines.append("dependencies: " + "; ".join(x for x in (("dropped " + ", ".join(deps["dropped"])) if deps["dropped"] else "",
                                                              ("added " + ", ".join(deps["added"])) if deps["added"] else "") if x))
    if answer["orphans"]:
        lines.append("resource folders with no schema: " + ", ".join(f"Resources/{o}" for o in answer["orphans"]))
    if answer["untracked"]:
        lines.append(f"not tracked by git ({len(answer['untracked'])}):")
        lines += [f"  {p}" for p in answer["untracked"]]
    lines.append("content:")
    lines += [f"  {l}" for l in cut(answer["content"].splitlines(), limit, "lines")]
    if answer["restore"] or answer["applied"]:
        verb = "restored" if answer["applied"] else "would restore (run with --apply)"
        lines.append(f"{verb} from HEAD ({len(answer['restore'])}):")
        lines += [f"  git checkout HEAD -- {p}" for p in answer["restore"]]
    return "\n".join(lines)
