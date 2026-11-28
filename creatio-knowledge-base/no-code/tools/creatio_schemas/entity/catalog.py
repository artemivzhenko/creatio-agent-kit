"""What an entity (object) schema is made of: friendly names for its flags, the parents shipped as assets,
the stock entity UIds and the designer's templates for a new object.

Keys (Terrasoft.Core.Entities, 8.2.3):
    schema   D1 IsVirtual, D2 Columns, D4 PrimaryDisplayColumnUId, D6 Indexes, D8 ParentSchemaUId, D10 IsDBView,
             D15/D16/D17 AdministratedByOperations/Columns/Records, D24 IsTrackChangesInDB, D26 UseDenyRecordRights,
             D32 UseRecordDeactivation, D33 IsSSPAvailable, D38 UseLiveEditing, EG1 the embedded events process
    column   S2 DataValueTypeUId, S4 ReferenceSchemaUId, E2 RequirementType, E5 IsValueCloneable, E6 IsIndexed,
             E8 IsWeakReference, E9 IsCascade, E12 DefValue, E15 UsageType, E16 IsTrackChangesInDB, E17/E18 lookup
             value / display column names, E19 IsMultiLineText, E20 IsSimpleLookup, E21 IsLocalizable,
             E22 IsMasked, E23 IsSensitiveData, E25 IsFormatValidated
To add a flag, add a row to COLUMN_FLAGS or OBJECT_FLAGS.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

from ..diff import SchemaDiff
from ..files import read_text

ASSETS = Path(__file__).resolve().parent / "assets"
BASE_ENTITY_UID = "1bab9dcf-17d5-49f8-9536-8e0064f1dce0"
BASE_LOOKUP_UID = "11ab4bcb-9b23-4b6d-9c86-520fae925d75"
PARENT_NAMES = {BASE_ENTITY_UID: "BaseEntity", BASE_LOOKUP_UID: "BaseLookup"}


class Catalogue:
    """The stock objects, lookups and columns of one platform version (assets/<kind>_<major>.<minor>.<patch>.json)."""

    def __init__(self, entities: dict[str, str], lookups: set[str], columns: dict[str, dict[str, str]]):
        self.entities, self.lookups, self._columns = entities, lookups, columns

    def columns(self, entity: str) -> dict[str, str] | None:
        """name -> column UId of a stock object's effective columns; None when unknown."""
        return self._columns.get(entity)


def _asset(prefix: str, version: str) -> Path | None:
    """The file `<prefix>_<x.y.z>.json` for `version`: the same major.minor, else the nearest lower, else (a version older than
    every file) the oldest, else - an unknown version - the newest; None when no file has the prefix."""
    files = {tuple(int(n) for n in f.stem[len(prefix) + 1:].split(".")[:2]): f for f in ASSETS.glob(f"{prefix}_*.json")}
    if not files:
        return None
    try:
        want = tuple(int(n) for n in version.split(".")[:2])
    except ValueError:
        want = None
    if want is None or len(want) < 2:
        return files[max(files)]
    lower = [k for k in files if k <= want]
    return files[max(lower) if lower else min(files)]


def stock(version: str = "") -> Catalogue:
    """The catalogue for a platform version (platform_version.py); `""` or an unparsable one: the newest files."""
    return _stock(*(_asset(p, version) for p in ("entities", "stock_lookups", "stock_columns")))


@functools.lru_cache(maxsize=None)
def _stock(entities: Path | None, lookups: Path | None, columns: Path | None) -> Catalogue:
    read = lambda path, key: json.loads(path.read_text(encoding="utf-8"))[key] if path else None  # noqa: E731
    return Catalogue(read(entities, "entities") or {}, set(read(lookups, "names") or ()), read(columns, "columns") or {})


_NEWEST = stock("")
STOCK_VERSION = _asset("entities", "").stem.split("_", 1)[1]  # the version of the unknown-version view below
STOCK_ENTITIES: dict[str, str] = _NEWEST.entities
STOCK_LOOKUPS: set[str] = _NEWEST.lookups


def stock_columns(entity: str) -> dict[str, str] | None:
    """name -> column UId of a stock object's effective columns in the newest catalogue; None when unknown."""
    return _NEWEST.columns(entity)

# friendly name: (key, value when on, value when off); None = the key is absent (the platform default)
COLUMN_FLAGS = {
    "required": ("E2", 1, None),
    "indexed": ("E6", True, None),
    "simple-lookup": ("E20", True, None),
    "weak-reference": ("E8", True, None),   # no foreign key constraint in the database
    "cascade": ("E9", True, None),          # deleting the referenced record deletes this one
    "track-changes": ("E16", True, None),
    "sensitive": ("E23", True, None),
    "multiline": ("E19", True, None),
    "localizable": ("E21", True, None),
    "masked": ("E22", True, None),
    "format-validated": ("E25", True, None),
    "copy-on-duplicate": ("E5", None, False),  # IsValueCloneable is on unless the designer writes false
}
# friendly name: (metadata key, properties.json name or None); on = the key true, off = the key absent
OBJECT_FLAGS = {
    "virtual": ("D1", "IsVirtual"),
    "db-view": ("D10", None),
    "track-changes": ("D24", "IsTrackChangesInDB"),
    "admin-operations": ("D15", "AdministratedByOperations"),
    "admin-columns": ("D16", "AdministratedByColumns"),
    "admin-records": ("D17", "AdministratedByRecords"),
    "deny-rights": ("D26", None),
    "deactivation": ("D32", None),
    "ssp": ("D33", "IsSSPAvailable"),
    "live-editing": ("D38", "UseLiveEditing"),
}
# the designer's key order inside a column
COLUMN_KEY_ORDER = ["UId", "A2", "A3", "A4", "A5", "S2", "S4", "E2", "E5", "E6", "E20", "E8", "E9", "E12", "E15", "E16", "E19", "E21", "E22",
                    "E23", "E24", "E25", "E17", "E18"]


def column_flags(column: dict) -> list[str]:
    return [name for name, (key, on, off) in COLUMN_FLAGS.items() if (column.get(key) == on if on is not None else key not in column)
            and name != "copy-on-duplicate"] + (["no-copy-on-duplicate"] if column.get("E5") is False else [])


def ordered_column(column: dict) -> dict:
    rank = {k: i for i, k in enumerate(COLUMN_KEY_ORDER)}
    return dict(sorted(column.items(), key=lambda kv: rank.get(kv[0], len(rank))))


_PARENTS: dict[str, dict] = {}


def stock_parent(uid: str) -> dict | None:
    """The effective schema of BaseEntity / BaseLookup (exported from a 8.2.3 site), or None."""
    uid = (uid or "").lower()
    if uid not in PARENT_NAMES:
        return None
    if uid not in _PARENTS:
        base = json.loads(read_text(ASSETS / "BaseEntity.metadata.json")[0])["MetaData"]["Schema"]
        _PARENTS[BASE_ENTITY_UID] = base
        _PARENTS[BASE_LOOKUP_UID] = SchemaDiff(read_text(ASSETS / "BaseLookup.metadata.json")[0]).apply(base)
    return _PARENTS[uid]


def template(parent: str) -> str:
    """The metadata.json the 8.2.3 designer writes for a new object without columns; placeholders in braces."""
    path = ASSETS / f"new_{parent}.diff"
    if not path.is_file():
        raise ValueError(f"no template for parent {parent}; one of BaseEntity, BaseLookup")
    return read_text(path)[0]
