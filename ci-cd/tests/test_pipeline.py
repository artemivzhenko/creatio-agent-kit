"""Checks for the pipeline's site-free stages:  python ci-cd/tests/test_pipeline.py"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import pipeline  # noqa: E402


def package(root: Path, name: str, depends=(), schemas=(), uid_of=None):
    pkg = root / name
    pkg.mkdir(parents=True)
    (pkg / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": name, "UId": f"uid-{name}",
                                                                    "DependsOn": [{"Name": d} for d in depends]}}), encoding="utf-8")
    for schema in schemas:
        folder = pkg / "Schemas" / schema
        folder.mkdir(parents=True)
        for f in ("metadata.json", "properties.json"):
            (folder / f).write_text("{}", encoding="utf-8")
        (folder / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": schema, "UId": (uid_of or {}).get(schema, f"uid-{schema}")}}), encoding="utf-8")
    return pkg


def test_the_order_is_dependencies_first_then_the_settings_then_the_given_list():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "packages"
        package(root, "UsrApp", depends=["UsrBase"])
        package(root, "UsrBase")
        package(root, "UsrTests", depends=["UsrApp"])
        assert [p.name for p in pipeline.package_dirs(root, None)] == ["UsrBase", "UsrApp", "UsrTests"]
        (Path(tmp) / ".clio").mkdir()
        (Path(tmp) / ".clio" / "workspaceSettings.json").write_text(json.dumps({"Packages": ["UsrTests", "UsrBase"]}), encoding="utf-8")
        assert [p.name for p in pipeline.package_dirs(root, None)] == ["UsrTests", "UsrBase"]
        assert [p.name for p in pipeline.package_dirs(root, "UsrApp,UsrBase")] == ["UsrApp", "UsrBase"]


def test_the_rules_find_what_the_old_scripts_found():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "packages"
        pkg = package(root, "UsrPkg", schemas=["UsrOrderPage", "UsrOrderCopy", "UsrClean"], uid_of={"UsrOrderCopy": "uid-UsrOrderPage"})
        (pkg / "Schemas" / "UsrOrderPage" / "properties.json").unlink()
        (pkg / "Schemas" / "UsrOrderPage" / "UsrOrderPage.js").write_text("define([], function () {\n  alert('x');\n  debugger;\n  // Кириллица в комментарии\n  var s = 'Текст';\n});\n", encoding="utf-8")
        (pkg / "SqlScripts" / "UsrSeed").mkdir(parents=True)
        (pkg / "SqlScripts" / "UsrSeed" / "Other.sql").write_text("select 1", encoding="utf-8")
        (pkg / "Assemblies" / "UsrLib").mkdir(parents=True)
        errors = pipeline.check([pkg], cyrillic=False)
        text = "\n".join(errors)
        assert "properties.json not found" in text
        assert "alert()" in text and "debugger" in text
        assert "duplicate schema UId uid-usrorderpage" in text
        assert "not named after its folder" in text
        assert "0 .dll files, expected one" in text
        assert "Cyrillic" not in text
        assert len(errors) == 6, errors
        with_cyrillic = pipeline.check([pkg], cyrillic=True)
        assert sum("Cyrillic" in e for e in with_cyrillic) == 1, with_cyrillic  # the comment line passes, the literal does not
        assert pipeline.check([package(root, "UsrOk", schemas=["UsrA"])], cyrillic=True) == []


def test_deploy_runs_the_commands_in_order_with_the_flags_clio_accepts():
    seen = []
    original = pipeline.run
    pipeline.run = lambda cmd, cwd=None, check=True: seen.append(" ".join(cmd[1:3])) or 0
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pkgs = [package(Path(tmp), "UsrBase"), package(Path(tmp), "UsrApp")]
            pipeline.deploy(pkgs, "ci", restart=True, redis=True, compile_all=False)
            assert [s.split()[0] for s in seen] == ["execute-sql-script"] * 3 + ["push-pkg", "push-pkg", "compile-configuration",
                                                                                  "restart-web-app", "clear-redis-db", "healthcheck"]
            assert seen[3:5] == ["push-pkg UsrBase", "push-pkg UsrApp"]
            seen.clear()
            pipeline.deploy(pkgs, "ci", restart=False, redis=False, compile_all=True)
            assert [s.split()[0] for s in seen][-2:] == ["compile-configuration", "healthcheck"]
    finally:
        pipeline.run = original
    full = []
    pipeline.run = lambda cmd, cwd=None, check=True: full.append(cmd) or 0
    try:
        pipeline.deploy([], "ci", restart=False, redis=False, compile_all=True)
    finally:
        pipeline.run = original
    assert full[-2][-1] == "--all" and full[-1][-4:] == ["-a", "true", "-h", "true"]  # a bare -a: "Option 'a' has no value"


def test_the_templates_parse_and_no_secret_is_interpolated_by_groovy():
    templates = HERE.parent / "templates"
    try:
        import yaml
        for name in ("github-actions.yml", "gitlab-ci.yml"):
            assert isinstance(yaml.safe_load((templates / name).read_text(encoding="utf-8")), dict), name
    except ImportError:
        print("  (PyYAML absent: the YAML templates not parsed)")
    jenkins = (templates / "Jenkinsfile").read_text(encoding="utf-8")
    assert jenkins.count("{") == jenkins.count("}")
    for line in jenkins.splitlines():
        if line.strip().startswith('sh "'):
            assert "CREATIO_" not in line, line  # a GString puts the secret into the command Jenkins logs


def test_the_password_never_reaches_the_log():
    cmd = ["clio", "reg-web-app", "ci", "-u", "http://localhost", "-l", "Supervisor", "-p", "secret-value"]
    assert pipeline.shown(cmd) == "clio reg-web-app ci -u http://localhost -l Supervisor -p ***"
    assert "secret-value" not in pipeline.shown(["x", "--password", "secret-value"])


def test_the_ui_stage_writes_the_config_and_the_framework_defaults_but_never_pages():
    seen = []
    original = pipeline.run
    pipeline.run = lambda cmd, cwd=None, check=True: seen.append(cmd) or 0
    os.environ.update(CREATIO_URL="http://site", CREATIO_LOGIN="Supervisor", CREATIO_PASSWORD="secret-value")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(root=tmp, filter="case", validate_only=True)
            assert pipeline.ui(args) == 0
            conf = Path(tmp) / "Configuration"
            written = json.loads((conf / "creatio.env.config.json").read_text(encoding="utf-8"))
            assert written["BaseUrl"] == "http://site" and written["Users"][0]["Username"] == "Supervisor"
            assert all((conf / n).is_file() for n in ("creatio.site.config.json", "objects.config.json", "run.config.json"))
            assert not (conf / "pages").exists() and not (conf / "static.values.json").exists()
            assert seen[0][-3:] == ["--filter", "case", "--validate-only"] and "secret-value" not in " ".join(seen[0])
    finally:
        pipeline.run = original


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
