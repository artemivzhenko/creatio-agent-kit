"""The site's platform version, once: `environment.platformVersion` of project.json (S52-T04)."""
from __future__ import annotations

import json
from pathlib import Path


def platform_version(project: str | Path | None) -> str:
    """`environment.platformVersion` (a short `8.3.2` becomes the full version of the `paths.platformBin` binaries when they
    are that version), else the binaries' version, else "". Never inferred from a schema's CreatedInVersion (it is per schema, mixed on one site)."""
    if not project:
        return ""
    path = Path(project)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    want = str((data.get("environment") or {}).get("platformVersion") or "")
    if len(want.split(".")) >= 4:
        return want
    bin_dir = (data.get("paths") or {}).get("platformBin")
    if not bin_dir:
        return want
    from .describe.platform import version_of
    bin_dir = Path(bin_dir)
    have = version_of(bin_dir if bin_dir.is_absolute() else path.resolve().parent / bin_dir) or ""
    # a short version takes the bin's full one only when the bin is that version
    return have if have and (not want or have == want or have.startswith(want + ".")) else want


def stamp(version: str | None, project: str | Path | None) -> dict:
    """The `version=` keyword for a writer: an explicit `--version`, else the project's (padded to four parts), else {} (the writer's default)."""
    v = version or platform_version(project)
    if not v:
        return {}
    return {"version": ".".join((v.split(".") + ["0"] * 4)[:4])}
