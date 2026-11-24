"""The platform's Freedom UI runtime code of a site - the shell's bundles and webpack chunks - cached per version and
searched by regex (S44-T02).

    shell_source(env, "QuickFilter", context=2)   -> text: `<file>:<line>: <text>` per hit, with context lines

The answer to "how does the platform do X on this version" for the client side (`find_api` answers it for C#). The
shell page `/0/Shell/` names its script bundles; `main.<hash>.js` holds the webpack chunk map
(`.u=o=>""+o+"<pre>"+{id:"hash",...}[o]+"<suf>"`); every bundle and chunk is downloaded ONCE per site version into
`~/.creatio-kit/shell/<host>/<hash>/` (outside every repository; a new hash is a new folder, the old ones of that host are
deleted). Read-only GETs as the logged-in user. The files are untrusted data: never executed, written nowhere else.
"""

from __future__ import annotations

import re
import shutil
import urllib.parse
from pathlib import Path

from .describe.core import DEFAULT_LIMIT, cut

CACHE = Path.home() / ".creatio-kit" / "shell"
SCRIPT_RE = re.compile(r'src="([^"]+?\.js)(?:\?[^"]*)?"')
MAIN_RE = re.compile(r"main\.([0-9a-f]{8,})\.js")
# webpack 5: `.u=e=>""+e+"<pre>"+{12:"ab12",...}[e]+"<suf>"` (the argument name varies with the minifier)
MAP_RE = re.compile(r'\.u=(\w+)=>""\+\1\+"([^"]*)"\+(\{[^}]*\})\[\1\]\+"([^"]*)"')
DONE = ".complete"
WIDTH = 200


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]", "_", name)[-120:]


def chunk_names(main: str) -> list[str]:
    """The file names of the chunks the main bundle's map lists; [] when the bundle has no map of that shape."""
    m = MAP_RE.search(main)
    if not m:
        return []
    pre, table, suf = m.group(2), m.group(3), m.group(4)
    pairs = re.findall(r'(\w+):"([^"]*)"', table)
    return [f"{cid}{pre}{h}{suf}" for cid, h in pairs]


def _get(env, path: str) -> str:
    r = env.fetch(path)
    if not r.ok:
        raise RuntimeError(f"GET {path}: HTTP {r.status}")
    return r.text


def ensure_cache(env, root: Path = CACHE) -> tuple[Path, str]:
    """(the version's folder, a note): downloads the shell's bundles and chunks when this version is not cached yet."""
    shell = _get(env, "0/Shell/")
    scripts = SCRIPT_RE.findall(shell)
    main = next((s for s in scripts if MAIN_RE.search(s)), None)
    if not main:
        raise RuntimeError("the shell page names no main.<hash>.js bundle: not a Freedom UI shell, or the login page came back")
    host = _safe(urllib.parse.urlsplit(env.url).netloc or "site")
    version = MAIN_RE.search(main).group(1)
    folder = Path(root) / host / version
    if (folder / DONE).is_file():
        return folder, ""
    for old in (Path(root) / host).glob("*") if (Path(root) / host).is_dir() else []:
        if old != folder and old.is_dir():
            shutil.rmtree(old, ignore_errors=True)  # a new site version replaces the old cache
    folder.mkdir(parents=True, exist_ok=True)
    size, files, skipped = 0, 0, []
    main_text = ""
    for src in dict.fromkeys(scripts):
        path = src.lstrip("/") if src.startswith("/") else "0/Shell/" + src
        try:
            text = _get(env, path)
        except RuntimeError as e:
            skipped.append(str(e))
            continue
        (folder / _safe(Path(src).name)).write_text(text, encoding="utf-8")
        size, files = size + len(text), files + 1
        if src == main:
            main_text = text
    for name in chunk_names(main_text):
        try:
            text = _get(env, "0/Shell/" + name)
        except RuntimeError as e:
            skipped.append(str(e))
            continue
        (folder / _safe(name)).write_text(text, encoding="utf-8")
        size, files = size + len(text), files + 1
    (folder / DONE).write_text(f"{files} files\n", encoding="utf-8")
    absent = sum(1 for s in skipped if s.endswith("HTTP 404"))  # the map lists chunks a site does not deploy (60 of 262 served on 8.2.3)
    note = (f"downloaded {files} files ({size / 1048576:.1f} MB) for {host} {version}"
            + (f"; {absent} chunks of the map not served by the site (404)" if absent else "")
            + (f"; {len(skipped) - absent} not fetched: {skipped[0] if len(skipped) > absent else ''}" if len(skipped) > absent else ""))
    return folder, note


def _clip(line: str, at: int | None = None, width: int = WIDTH) -> str:
    """A minified line cut to `width` characters around `at` (its start when no hit is on it)."""
    if len(line) <= width:
        return line
    start = 0 if at is None else max(0, min(at - width // 2, len(line) - width))
    return ("..." if start else "") + line[start:start + width] + ("..." if start + width < len(line) else "")


def search(folder: Path, pattern: str, context: int = 2) -> list[str]:
    """`<file>:<line>: <text>` per hit (the hit line cut around the match), `  <line>- <text>` for the context lines."""
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"pattern is not a regular expression: {e}") from None
    out = []
    for f in sorted(p for p in Path(folder).iterdir() if p.suffix == ".js"):
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            for m in regex.finditer(line):
                for j in range(max(0, i - context), i):
                    out.append(f"  {j + 1}- {_clip(lines[j])}")
                out.append(f"{f.name}:{i + 1}: {_clip(line, m.start())}")
                for j in range(i + 1, min(len(lines), i + 1 + context)):
                    out.append(f"  {j + 1}- {_clip(lines[j])}")
    return out


def shell_source(env, pattern: str, context: int = 2, limit: int = DEFAULT_LIMIT, offset: int = 0, root: Path = CACHE) -> str:
    """The hits of `pattern` in the site's shell code, the download note first when this call filled the cache."""
    if not pattern:
        raise ValueError("pattern must not be empty")
    folder, note = ensure_cache(env, root)
    hits = search(folder, pattern, max(0, int(context)))
    count = sum(1 for h in hits if not h.startswith("  "))
    head = ([note] if note else []) + [f"{count} hit(s) of /{pattern}/ in {folder.name}"]
    return "\n".join(head + cut(hits, limit, offset=offset, paged=True))
