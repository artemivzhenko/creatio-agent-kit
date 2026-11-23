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
        (Path(tmp) / ".clio" / "workspaceSettings.json").unlink()  # the settings' list needs no descriptor; the dependency order does
        (root / "UsrBase" / "descriptor.json").write_text('{"Descriptor": {"Name" "UsrBase"}}', encoding="utf-8")
        try:  # a broken descriptor is one line naming the package, not a JSONDecodeError traceback (S35-T01)
            pipeline.package_dirs(root, None)
            raise AssertionError("no exit")
        except SystemExit as e:
            assert str(e.code).startswith("UsrBase: descriptor.json is not valid JSON"), e.code


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


def test_a_binding_or_sql_script_changed_without_a_new_descriptor_date_is_refused():
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "packages"
        pkg = package(root, "UsrPkg")
        for folder, body in (("Data/UsrSeed", "data.json"), ("SqlScripts/UsrView", "UsrView.sql")):
            (pkg / folder).mkdir(parents=True)
            (pkg / folder / "descriptor.json").write_text(json.dumps({"Descriptor": {"Name": folder.split("/")[1], "ModifiedOnUtc": "2026-01-01T00:00:00.000Z"}}), encoding="utf-8")
            (pkg / folder / body).write_text("v1", encoding="utf-8")
        git = lambda *a: subprocess.run(["git", "-C", tmp, *a], capture_output=True, text=True, check=True)
        git("init", "-q"); git("config", "user.email", "ci@example.com"); git("config", "user.name", "ci"); git("add", "."); git("commit", "-q", "-m", "base")
        (pkg / "Data/UsrSeed/data.json").write_text("v2", encoding="utf-8")
        (pkg / "SqlScripts/UsrView/UsrView.sql").write_text("v2", encoding="utf-8")
        errors = pipeline.changed_without_date([pkg], "HEAD")
        assert len(errors) == 2 and all("ModifiedOnUtc is still 2026-01-01" in e for e in errors), errors
        (pkg / "Data/UsrSeed/descriptor.json").write_text(json.dumps({"Descriptor": {"Name": "UsrSeed", "ModifiedOnUtc": "2026-02-01T00:00:00.000Z"}}), encoding="utf-8")
        errors = pipeline.changed_without_date([pkg], "HEAD")
        assert len(errors) == 1 and "SqlScripts" in errors[0], errors
        assert pipeline.main(["check", str(root)]) == 0  # without --base the rule is off


def test_build_backup_and_deploy_share_the_artifact_shape_and_its_order():
    import zipfile
    original = pipeline.run
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "packages"
        pkgs = [package(root, "UsrBase"), package(root, "UsrApp", depends=["UsrBase"])]
        pipeline.run = lambda cmd, cwd=None, check=True: (cwd / f"{cmd[2]}.gz").write_text("gz", encoding="utf-8") and 0  # compress / pull-pkg write <name>.gz
        try:
            archive = pipeline.build(pipeline.package_dirs(root, None), Path(tmp) / "Build")
            assert zipfile.ZipFile(archive).read("order.txt").decode() == "UsrBase\nUsrApp\n"
            # backup: UsrGone is not on the site (no file written, exit 1), the archive keeps what the site had
            pipeline.run = lambda cmd, cwd=None, check=True: ((cwd / f"{cmd[2]}.gz").write_text("site", encoding="utf-8") and 0) if cmd[2] != "UsrGone" else 1
            saved = pipeline.backup(["UsrBase", "UsrApp", "UsrGone"], "ci", Path(tmp) / "Backup")
            assert saved.name.startswith("Pkg-") and zipfile.ZipFile(saved).read("order.txt").decode() == "UsrBase\nUsrApp\n"
            # deploy from the artifact: the .gz files by path, in the order file's order, after the IsChanged rule
            seen = []
            pipeline.run = lambda cmd, cwd=None, check=True: seen.append(cmd) or 0
            pipeline.deploy(pipeline.unpack(saved, Path(tmp) / "unpacked"), "ci", restart=False, redis=False, compile_all=False)
            pushes = [c for c in seen if c[1] == "push-pkg"]
            assert [Path(c[2]).name for c in pushes] == ["UsrBase.gz", "UsrApp.gz"] and all(Path(c[2]).is_absolute() for c in pushes)
            assert seen[0][1] == "execute-sql-script" and seen[-1][1] == "healthcheck"
            # verify: the kit's push.py verify per package, the worst exit code wins
            pipeline.run = lambda cmd, cwd=None, check=True: seen.append(cmd) or (1 if "UsrApp" in cmd[3] else 0)
            seen.clear()
            assert pipeline.verify(pkgs, "ci") == 1 and all(c[2] == "verify" and c[-2:] == ["-e", "ci"] for c in seen) and len(seen) == 2
        finally:
            pipeline.run = original
        try:
            pipeline.unpack(Path(tmp) / "nowhere", Path(tmp) / "x")
            assert False, "an empty artifact must stop"
        except SystemExit as e:
            assert "no package archive" in str(e)


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


def test_what_pull_pkg_wrote_becomes_name_gz():
    """clio 8.1 pull-pkg writes <name>.zip holding <name>.gz; an older clio the .gz itself (S35-T01: backup saved nothing)."""
    import zipfile
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        before = pipeline.archives(folder)
        assert pipeline.pulled_gz(folder, "UsrApp", before) is None  # nothing written: not on the site
        with zipfile.ZipFile(folder / "UsrApp.zip", "w") as z:
            z.writestr("UsrApp.gz", b"gz bytes")
        assert pipeline.pulled_gz(folder, "UsrApp", before) == folder / "UsrApp.gz"
        assert (folder / "UsrApp.gz").read_bytes() == b"gz bytes" and not (folder / "UsrApp.zip").exists()
        before = pipeline.archives(folder)
        (folder / "usrbase.gz").write_bytes(b"old clio")
        assert pipeline.pulled_gz(folder, "UsrBase", before) == folder / "UsrBase.gz" and (folder / "UsrBase.gz").read_bytes() == b"old clio"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
