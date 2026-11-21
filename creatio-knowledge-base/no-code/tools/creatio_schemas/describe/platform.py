"""The captions of the local platform install (S31-T09): base columns and base client schemas' strings the workspace does not hold.

`project.json` `paths.platform` names the install: its root, its `Packages` folder (one `<Package>.gz` archive per package, the
delivery form) or a folder of package folders with `Resources/` (`Terrasoft.Configuration/Pkg` of a file-system install).
`index_workspace` reads it once into the store's `platform_captions` table: per package, the `Resources/<Schema>.Entity` and
`<Schema>.ClientUnit` strings (`Caption`, `Columns.<Name>.Caption`, `LocalizableStrings.<Name>.Value`) in the workspace's primary
cultures and `en-US`. `meta.platform_version` is the install's version (`Terrasoft.Core.dll`'s file version, else `CrtCore`'s
`PackageVersion`); `meta.platform_path` and the cultures say what was read, so the next call skips the work.

An archive is gzip of records: an int32 count of UTF-16 characters, the name (`Resources\\X.Entity\\resource.en-US.xml`), an
int32 byte length, the bytes.
"""

from __future__ import annotations

import gzip
import json
import re
import sqlite3
import struct
import time
from pathlib import Path
from xml.sax.saxutils import unescape

from ..files import read_text
from . import store

_ITEM_RE = re.compile(r'<Item Name="([^"]*)"(?: [A-Za-z]+="[^"]*")*? Value="([^"]*)" />')
_UNESCAPE = {"&quot;": '"', "&apos;": "'", "&#xA;": "\n", "&#xD;": "\r", "&#x9;": "\t"}
_RES_RE = re.compile(r"^Resources[\\/]([^\\/]+)\.(Entity|ClientUnit)[\\/]resource\.([A-Za-z-]+)\.xml$")
_VERSION_RE = re.compile(rb"F\x00i\x00l\x00e\x00V\x00e\x00r\x00s\x00i\x00o\x00n\x00\x00\x00(?:\x00\x00)?((?:[0-9.]\x00)+)")


def _wanted(key: str, kind: str) -> bool:
    if kind == "Entity":
        return key == "Caption" or (key.startswith("Columns.") and key.endswith(".Caption"))
    return key == "Caption" or (key.startswith("LocalizableStrings.") and key.endswith(".Value"))


def archive(path: Path):
    """(name, bytes) of every record of a package archive."""
    with gzip.open(path) as f:
        while True:
            head = f.read(4)
            if len(head) < 4:
                return
            name = f.read(struct.unpack("<i", head)[0] * 2).decode("utf-16-le")
            yield name, f.read(struct.unpack("<i", f.read(4))[0])


def _source(platform: Path) -> tuple[str, list[Path]]:
    """("gz", archives) or ("folders", package folders) of the install path."""
    for p in (platform, platform / "Packages"):
        gz = sorted(p.glob("*.gz")) if p.is_dir() else []
        if gz:
            return "gz", gz
    folders = sorted(d for d in platform.iterdir() if (d / "Resources").is_dir()) if platform.is_dir() else []
    if not folders:
        raise FileNotFoundError(f"{platform}: no <Package>.gz archives and no package folders with Resources/ (paths.platform in project.json)")
    return "folders", folders


def version_of(platform: Path) -> str | None:
    """The install's version: `Terrasoft.Core.dll`'s FileVersion found at or above `platform`, else CrtCore's PackageVersion."""
    for d in [platform, *platform.parents][:4]:
        for dll in (d / "Terrasoft.WebApp" / "bin" / "Terrasoft.Core.dll", d / "bin" / "Terrasoft.Core.dll"):
            if dll.is_file():
                m = _VERSION_RE.search(dll.read_bytes())
                if m:
                    return m.group(1).decode("utf-16-le")
    kind, items = _source(platform)
    for item in items:
        if item.name in ("CrtCore", "CrtCore.gz"):
            text = next((b.decode("utf-8-sig") for n, b in archive(item) if n == "descriptor.json"), None) if kind == "gz" \
                else read_text(item / "descriptor.json")[0]
            return json.loads(text)["Descriptor"].get("PackageVersion") if text else None
    return None


def rows(platform: Path, cultures: set[str]):
    """(package, schema, key, culture, text) of the install's object and client schema strings in `cultures`."""
    kind, items = _source(platform)
    for item in items:
        package = item.name[:-3] if kind == "gz" else item.name
        if kind == "gz":
            entries = ((n, b) for n, b in archive(item))
        else:
            entries = ((p.relative_to(item).as_posix(), p) for p in sorted((item / "Resources").glob("*/resource.*.xml")))
        for name, content in entries:
            m = _RES_RE.match(name)
            if not m or m.group(3) not in cultures:
                continue
            text = content.decode("utf-8-sig", "replace") if isinstance(content, bytes) else read_text(content)[0]
            for key, value in _ITEM_RE.findall(text):
                if _wanted(key, m.group(2)):
                    yield package, m.group(1), key, m.group(3), unescape(value, _UNESCAPE)


def build(db: Path, platform: Path, cultures: set[str], force: bool = False) -> str:
    """Fill `platform_captions` from the install, once: the same path, version and cultures as the last build skip it. One line."""
    platform = Path(platform)
    version = version_of(platform)
    want = {"platform_path": str(platform.resolve()), "platform_version": version or "", "platform_cultures": ",".join(sorted(cultures))}
    con = store.connect(db)
    try:
        meta = dict(con.execute("select key, value from meta where key like 'platform%'"))
        count = con.execute("select count(*) from platform_captions").fetchone()[0]
        if not force and count and all(meta.get(k) == v for k, v in want.items()):
            return f"platform {version}: {count} captions, up to date"
        start = time.perf_counter()
        con.execute("delete from platform_captions")
        con.executemany("insert into platform_captions (package, schema, key, culture, text) values (?, ?, ?, ?, ?)", rows(platform, cultures))
        con.executemany("insert or replace into meta (key, value) values (?, ?)", want.items())
        con.commit()
        count = con.execute("select count(*) from platform_captions").fetchone()[0]
        packages = con.execute("select count(distinct package) from platform_captions").fetchone()[0]
        return f"platform {version}: {count} captions of {packages} packages ({', '.join(sorted(cultures))}) in {time.perf_counter() - start:.1f} s"
    finally:
        con.close()


def caption(db: Path, schema: str, key: str, culture: str) -> tuple[str, str] | None:
    """(text, package) of a platform string in `culture`, else en-US; None without a platform pass (or no store)."""
    if not db.is_file():
        return None
    con = store.connect(db, write=False)
    try:
        row = con.execute("select text, package from platform_captions where schema = :s collate nocase and key = :k and culture in (:c, 'en-US') "
                          "and text != '' order by culture = :c desc, package limit 1", {"s": schema, "k": key, "c": culture}).fetchone()
        return (row[0], row[1]) if row else None
    except sqlite3.OperationalError:  # a store of an older format: no table yet
        return None
    finally:
        con.close()


def column_caption(package: Path, entity: str, column: str, culture: str) -> str | None:
    """` 'Created on' (CrtBase)` for a column the platform captions; None when it has none."""
    from .index import index_path

    db = index_path(Path(package))
    # a system column (Id, CreatedOn, ModifiedBy ...) is captioned in BaseEntity only, not in the object that inherits it
    hit = caption(db, entity, f"Columns.{column}.Caption", culture) or caption(db, "BaseEntity", f"Columns.{column}.Caption", culture)
    return f" {hit[0]!r} ({hit[1]})" if hit else None


def project_platform(package: Path) -> Path | None:
    """`paths.platform` of the workspace's project.json, else None."""
    root = package.parent.parent if package.parent.name == "packages" else package.parent
    try:
        value = (json.loads((root / "project.json").read_text(encoding="utf-8-sig")).get("paths") or {}).get("platform")
    except (OSError, ValueError, AttributeError):
        return None
    return (root / value if not Path(value).is_absolute() else Path(value)) if isinstance(value, str) and value else None
