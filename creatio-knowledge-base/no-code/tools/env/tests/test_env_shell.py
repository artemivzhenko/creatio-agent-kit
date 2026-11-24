"""Checks for creatio_schemas/shell.py (S44-T02):  python tests/test_env_shell.py  (a fake site; nothing downloaded for real)."""

import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))

from creatio_schemas import shell  # noqa: E402
from creatio_schemas.environment import Response  # noqa: E402

MAIN = 'var a=1;\n!function(){r.u=e=>""+e+"."+{12:"aa11",34:"bb22",56:"cc33"}[e]+".js"}();\n'
CHUNK_HIT = 'x=1;\nclass UsrQuickFilterPreprocessor{process(t){return t.lookupConfig}}\ny=2;\n'
CHUNK_MISS = "nothing here\n"


class FakeSite:
    """`fetch(path)` as Environment answers it; `main` is the hash the shell page names."""

    def __init__(self, main="abcdef12"):
        self.url, self.main, self.calls = "https://dev.example.com/", main, []

    def fetch(self, path, accept="*/*"):
        self.calls.append(path)
        files = {"0/Shell/": f'<html><script src="runtime.0001.js"></script><script src="main.{self.main}.js?v=1"></script></html>',
                 "0/Shell/runtime.0001.js": "runtime();", f"0/Shell/main.{self.main}.js": MAIN,
                 "0/Shell/12.aa11.js": CHUNK_HIT, "0/Shell/34.bb22.js": CHUNK_MISS}
        return Response(200, files[path]) if path in files else Response(404, "not found")


def test_the_chunk_map_and_the_search():
    assert shell.chunk_names(MAIN) == ["12.aa11.js", "34.bb22.js", "56.cc33.js"]
    assert shell.chunk_names("no map here") == []
    long = "a" * 500 + "QuickFilter" + "b" * 500
    clipped = shell._clip(long, 500)
    assert "QuickFilter" in clipped and clipped.startswith("...") and clipped.endswith("...") and len(clipped) == 206


def test_the_cache_is_filled_once_per_version_and_searched():
    root = Path(tempfile.mkdtemp())
    try:
        site = FakeSite()
        text = shell.shell_source(site, "QuickFilter", context=1, root=root)
        lines = text.splitlines()
        # the map's third chunk is not deployed (404): said, not counted as a failure
        assert lines[0] == "downloaded 4 files (0.0 MB) for dev.example.com abcdef12; 1 chunks of the map not served by the site (404)", lines[0]
        assert lines[1] == "1 hit(s) of /QuickFilter/ in abcdef12", lines
        assert lines[2:5] == ["  1- x=1;", "12.aa11.js:2: class UsrQuickFilterPreprocessor{process(t){return t.lookupConfig}}", "  3- y=2;"], lines
        folder = root / "dev.example.com" / "abcdef12"
        assert (folder / ".complete").is_file() and sorted(p.name for p in folder.glob("*.js")) == ["12.aa11.js", "34.bb22.js", "main.abcdef12.js", "runtime.0001.js"]
        # the second call reads the cache: only the shell page is fetched, no download line
        site.calls.clear()
        again = shell.shell_source(site, r"lookupConfig\b", context=0, root=root)
        assert site.calls == ["0/Shell/"] and again.splitlines()[0] == "1 hit(s) of /lookupConfig\\b/ in abcdef12", again
        # a new main hash is a new folder; the old one goes
        site.main = "99887766"
        newer = shell.shell_source(site, "nothing", root=root)
        assert "dev.example.com 99887766" in newer.splitlines()[0] and not folder.exists() and (root / "dev.example.com" / "99887766").is_dir()
        # errors say what went wrong
        for bad, kind, text in (("(", ValueError, "not a regular expression"), ("", ValueError, "must not be empty")):
            try:
                shell.shell_source(site, bad, root=root)
                raise AssertionError(bad)
            except kind as e:
                assert text in str(e), e

        class LoginPage(FakeSite):
            def fetch(self, path, accept="*/*"):
                return Response(200, "<html>login</html>")
        try:
            shell.shell_source(LoginPage(), "x", root=root)
            raise AssertionError("no main bundle")
        except RuntimeError as e:
            assert "no main.<hash>.js" in str(e)
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
