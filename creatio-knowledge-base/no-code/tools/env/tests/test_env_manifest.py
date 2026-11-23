"""Checks for creatio_schemas/manifest.py (S40-T04):  python tests/test_env_manifest.py  (a fake clio; no site, made-up manifests)."""

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent.parent
sys.path.insert(0, str(TOOLS))

from creatio_schemas import manifest  # noqa: E402

BEFORE = """features:
- code: UsrFeatureA
  users_values:
    All employees: false
- code: UsrFeatureB
  users_values:
    All employees: true
settings:
- code: UsrMaxItems
  value: 5
- code: UsrGreeting
  value: 'it''s on'
webservices:
- url: https://dev.example.com/api
  name: UsrApi
packages:
- name: UsrPkg
  hash: 0A
  maintainer: Customer
  schemas:
  - name: UsrOrder
    hash: 11
  - name: UsrOrderPage
    hash: 22
- name: UsrOld
  hash: 0B
  maintainer: Customer
  schemas:
  - name: UsrOldThing
    hash: 33
"""

AFTER = (BEFORE.replace("    All employees: false", "    All employees: true", 1)
         .replace("  value: 5", "  value: 7")
         .replace("    hash: 11", "    hash: 12")
         .replace("  - name: UsrOrderPage\n    hash: 22\n", "  - name: UsrOrderPage\n    hash: 22\n  - name: UsrShipment\n    hash: 44\n")
         .replace("- name: UsrOld\n  hash: 0B\n  maintainer: Customer\n  schemas:\n  - name: UsrOldThing\n    hash: 33\n",
                  "- name: UsrNew\n  hash: 0C\n  maintainer: Customer\n  schemas:\n  - name: UsrNewThing\n    hash: 55\n"))


class FakeClio:
    """Records each clio call; `save-state` writes `text` to the file it is given."""

    def __init__(self, code=0, output="Done", text=BEFORE):
        self.calls, self.code, self.output, self.text = [], code, output, text

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "save-state" and not self.code:
            Path(args[1]).write_text(self.text, encoding="utf-8")
        return self.code, self.output


def raises(fn, kind, text=""):
    try:
        fn()
    except kind as e:
        assert text in str(e), (text, str(e))
        return
    raise AssertionError(f"expected {kind.__name__}")


def test_the_manifest_reads_into_paths_and_items():
    values, items = manifest.read_manifest(BEFORE)
    assert values[("features", "UsrFeatureA", "users_values", "All employees")] == "false"
    assert values[("settings", "UsrGreeting", "value")] == "it's on"  # a quoted scalar unquoted
    assert values[("packages", "UsrPkg", "schemas", "UsrOrderPage", "hash")] == "22" and values[("packages", "UsrOld", "maintainer")] == "Customer"
    assert ("packages", "UsrPkg", "schemas", "UsrOrder") in items and ("webservices", "https://dev.example.com/api") in items
    assert list(manifest.section_counts(values, items).items()) == [("features", 2), ("settings", 2), ("webservices", 1), ("packages", 2)]


def test_two_manifests_differ_by_section_one_line_per_change():
    with tempfile.TemporaryDirectory() as tmp:
        b, a = Path(tmp) / "before.yaml", Path(tmp) / "after.yaml"
        b.write_text(BEFORE, encoding="utf-8")
        a.write_text(AFTER, encoding="utf-8")
        assert manifest.manifest_diff(str(b), str(a)) == [
            "features: 1 change(s)", "  ~ UsrFeatureA users_values/All employees: false -> true",
            "settings: 1 change(s)", "  ~ UsrMaxItems value: 5 -> 7",
            "packages: 4 change(s)", "  + UsrNew", "  - UsrOld", "  + UsrPkg schemas/UsrShipment",  # a new package's schemas are part of it
            "  ~ UsrPkg schemas/UsrOrder hash: 11 -> 12"]
        assert manifest.manifest_diff(str(b), str(b)) == []


def test_save_state_composes_the_command_and_counts_the_sections():
    clio = FakeClio()
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "states" / "before.yaml"
        answer = manifest.save_state("dev", str(target), clio_run=clio)
        assert clio.calls == [["save-state", str(target.resolve()), "-e", "dev"]]
        assert answer == f"saved {target.resolve()}: features 2, settings 2, webservices 1, packages 2"
        raises(lambda: manifest.save_state("dev", str(Path(tmp) / "x.yaml"), clio_run=FakeClio(1, "[ERR] - no such environment")), RuntimeError,
               "clio save-state exited 1: [ERR] - no such environment")


def test_show_diff_passes_clio_through_without_its_progress_lines():
    clio = FakeClio(0, "[INF] - Creating temporary directory...\nLoaded 3 out of 9 features.\n[INF] - Loading packages\n[INF] - No differences found.\n")
    assert manifest.show_diff("dev", "test", clio_run=clio) == ["[INF] - No differences found."]
    assert clio.calls == [["show-diff", "--source", "dev", "--target", "test"]]
    raises(lambda: manifest.show_diff("dev", "test", clio_run=FakeClio(1, "[ERR] - Failed reading records")), RuntimeError, "exited 1: [ERR] - Failed reading records")


def test_set_feature_needs_a_dev_project_and_a_known_state():
    with tempfile.TemporaryDirectory() as tmp:
        dev, prod = Path(tmp) / "dev.json", Path(tmp) / "client.json"
        dev.write_text(json.dumps({"environment": {"clioName": "dev", "kind": "dev"}}), encoding="utf-8")
        prod.write_text(json.dumps({"environment": {"clioName": "dev", "kind": "client"}}), encoding="utf-8")
        clio = FakeClio()
        assert manifest.set_feature("dev", "UsrFeatureA", "on", str(dev), clio_run=clio) == "feature UsrFeatureA on for all users on dev"
        assert manifest.set_feature("dev", "UsrFeatureA", "OFF", str(dev), clio_run=clio).startswith("feature UsrFeatureA off")
        assert clio.calls == [["set-feature", "UsrFeatureA", "1", "-e", "dev"], ["set-feature", "UsrFeatureA", "0", "-e", "dev"]]
        refused = FakeClio()
        raises(lambda: manifest.set_feature("dev", "UsrFeatureA", "on", str(prod), clio_run=refused), PermissionError, "refused: dev is not a dev environment")
        raises(lambda: manifest.set_feature("test", "UsrFeatureA", "on", str(dev), clio_run=refused), PermissionError, "refused: test")  # another clioName
        raises(lambda: manifest.set_feature("dev", "UsrFeatureA", "on", None, clio_run=refused), PermissionError, "refused")
        raises(lambda: manifest.set_feature("dev", "UsrFeatureA", "maybe", str(dev), clio_run=refused), ValueError, "on or off")
        raises(lambda: manifest.set_feature("dev", "Usr Feature; x", "on", str(dev), clio_run=refused), ValueError, "not a feature code")
        assert refused.calls == []  # nothing reached clio
        raises(lambda: manifest.set_feature("dev", "UsrFeatureA", "on", str(dev), clio_run=FakeClio(1, "[ERR] - rejected")), RuntimeError, "set-feature exited 1")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
