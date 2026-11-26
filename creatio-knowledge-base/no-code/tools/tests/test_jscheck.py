"""Checks for the JS check of client bodies:  python tests/test_jscheck.py  (skipped when node is not on PATH)."""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from creatio_schemas.jscheck import lines  # noqa: E402

BODY = 'define("UsrX", [], function() { return { diff: [1, 2], methods: { a: function() {}, b: function() {} }, handlers: [{request: "r1"}] }; });'


def _run(text: str) -> list[str]:
    folder = Path(tempfile.mkdtemp())
    try:
        (folder / "x.js").write_text(text, encoding="utf-8")
        return lines(folder / "x.js")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_syntax_error_load_counts_and_a_body_that_throws():
    if not shutil.which("node"):
        assert lines("x.js") == ["node not found: JS syntax not checked"]
        return
    assert _run(BODY) == ["js syntax: ok", "js load: diff 2, methods 2 (a, b), handlers 1 (r1)"]
    assert _run(BODY.replace("function() {", "function() { var x = ;", 1))[0].startswith("js syntax: ERROR")
    assert _run('define("UsrX", [], function() { Nope.go(); return {}; });')[1] == "js load: not loaded (ReferenceError: Nope is not defined)"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
