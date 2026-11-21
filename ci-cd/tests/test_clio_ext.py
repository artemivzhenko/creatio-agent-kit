"""Checks for clio-ext's site-free logic:  python ci-cd/tests/test_clio_ext.py"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("clio_ext", HERE.parent / "clio-ext" / "clio-ext.py")
ext = importlib.util.module_from_spec(spec)
sys.modules["clio_ext"] = ext
spec.loader.exec_module(ext)


def package(root: Path, name: str, depends=(), descriptor_name=None, project_path=None):
    pkg = root / name
    pkg.mkdir(parents=True)
    d = {"Name": descriptor_name or name, "UId": f"uid-{name}", "DependsOn": [{"Name": x} for x in depends]}
    if project_path:
        d["ProjectPath"] = project_path
    (pkg / "descriptor.json").write_text(json.dumps({"Descriptor": d}), encoding="utf-8")
    return pkg


def test_the_hierarchy_has_levels_external_dependencies_dependents_and_problems():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "packages"
        package(root, "UsrBase", depends=["CrtBase"])
        package(root, "UsrApp", depends=["UsrBase", "CrtBase"], project_path="Files/Other.csproj")
        package(root, "UsrTests", depends=["UsrApp"], descriptor_name="UsrTest")
        g = ext.graph(root)
        assert g["order"] == ["UsrBase", "UsrApp", "UsrTests"]
        assert g["level"] == {"UsrBase": 0, "UsrApp": 1, "UsrTests": 2}
        assert g["external"]["UsrApp"] == ["CrtBase"] and g["dependents"]["UsrBase"] == ["UsrApp"]
        assert any("ProjectPath" in p for p in g["problems"]) and any("descriptor Name" in p for p in g["problems"])
        out, rep = Path(tmp) / "h.txt", Path(tmp) / "r.txt"
        ext.cmd_hierarchy(type("A", (), {"packages": str(root), "out": str(out), "report": str(rep)}))
        assert ext.read_list(out) == ["UsrBase", "UsrApp", "UsrTests"]
        assert "--- level 2 (1) ---" in rep.read_text(encoding="utf-8") and "PROBLEMS" in rep.read_text(encoding="utf-8")
        typed = package(root, "UsrTyped")
        text = (typed / "descriptor.json").read_text(encoding="utf-8").replace('"Name"', '"Type": 1, "Name"', 1)
        (typed / "descriptor.json").write_text(text, encoding="utf-8")
        assert "UsrTyped: Type 1 without ProjectPath (expected Files/UsrTyped.csproj)" in ext.graph(root)["problems"]
        assert not any(p.startswith("UsrBase") for p in ext.graph(root)["problems"])  # no Type, no ProjectPath: a platform package


def test_push_all_stops_or_continues_and_keeps_the_failed_list():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "packages"
        for name in ("UsrA", "UsrB", "UsrC"):
            package(root, name)
        calls = []

        def fake_run(logs, operation, cmd, cwd=None, stop=True):
            calls.append(cmd[2])
            return 1 if cmd[2] == "UsrB" else 0

        ext.run, ext.pipeline.clear_ischanged = fake_run, lambda env: calls.append("clear")
        args = lambda **kw: type("A", (), {"env": "dev", "packages": str(root), "package": None, "list": None,
                                            "continue_on_error": False, "keep_ischanged": False, **kw})
        assert ext.cmd_push_all(args()) == 1
        assert calls == ["clear", "UsrA", "UsrB"]  # stopped at the failure
        failed = Path(tmp) / "error-pkg.txt"
        assert ext.read_list(failed) == ["UsrB"]
        calls.clear()
        assert ext.cmd_push_all(args(continue_on_error=True, list=str(failed), keep_ischanged=True)) == 1
        assert calls == ["UsrB"]  # the retry list, no clear
        calls.clear()
        assert ext.cmd_push_all(args(package="UsrC,UsrA")) == 0
        assert calls == ["clear", "UsrC", "UsrA"] and not failed.exists()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
