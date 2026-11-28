"""`merge-run` (S27-T04): steps 2-8 of the package-merge procedure as one command with an evidence folder.

    merge_run(workspace, child, parent, evidence, env_name, apply=False, resume=False, engines=None) -> (text, exit code)

plan -> tests before -> snapshots before -> merge (only with `apply`) -> push -> [pause: the child's application is removed by
hand] -> snapshots after + compare -> tests after. The first stop, red case or difference ends the run with exit 1; a rehearsal
(no `apply`) ends after the snapshots, `paused` (exit 3) waits for `resume`. Every step leaves its file in the evidence folder.
`Engines` holds the five things that touch the outside world (the test utility, push, snapshot, merge, cases); the tests replace them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PAUSED = "paused.txt"
PENDING = "push-pending.txt"
COUNTS = re.compile(r"Cases:\s*(\d+)\s+passed:\s*(\d+)\s+failed:\s*(\d+)")
TOOLS = Path(__file__).resolve().parents[2]


class Stop(Exception):
    """The run ends here; the message is the last line."""


class Engines:
    """What the run calls. A subclass in a test returns canned answers."""

    def __init__(self, workspace: Path, env_name: str, tests_root: Path | str | None = None):
        self.workspace, self.env_name = Path(workspace), env_name
        self.tests_root = Path(tests_root or os.environ.get("CREATIO_TESTS_ROOT") or TOOLS.parents[2] / "automatic-creatio-tests")
        self._env = None

    @property
    def env(self):
        if self._env is None:
            from ..environment import open_environment
            self._env = open_environment(self.env_name)
        return self._env

    def merge_package(self, child: str, parent: str, apply: bool) -> tuple[str, int]:
        from .package_merge import merge_package
        return merge_package(self.workspace, child, parent, self.env, apply)

    def cases(self, child: str, out: Path) -> list[str]:
        from ..cases import cases_from_package
        from .merge import _context
        return cases_from_package(_context(self.workspace).folders[child], out, self.env, layout="root")

    def run_tests(self, root: Path, dest: Path) -> tuple[int, int, str]:
        """Runs every case under `root`; the report is copied to dest/report.*. -> (passed, failed, output)."""
        config = root / "Configuration"
        for d in ("Configuration/pages", "Configuration/processes", "Analysis"):  # the utility refuses a root without them
            (root / d).mkdir(parents=True, exist_ok=True)
        if not any((root / "Configuration/pages").glob("*.json")):  # the utility needs one page file even for backend cases only
            for f in sorted((self.tests_root / "Configuration/pages").glob("*.json"))[:1]:
                shutil.copy(f, root / "Configuration/pages" / f.name)
        secret = []  # the environment file holds a password: it is copied for the run and removed after it
        for f in (self.tests_root / "Configuration").glob("*.json"):
            if not (config / f.name).exists() and "example" not in f.name:
                config.mkdir(parents=True, exist_ok=True)
                shutil.copy(f, config / f.name)
                if "env.config" in f.name:
                    secret.append(config / f.name)
        before = set((root / "Reports").glob("*")) if (root / "Reports").is_dir() else set()
        exe = next((str(p) for c in ("Debug", "Release") if (p := self.tests_root / "src/CreatioAutoTests.Cli/bin" / c / "net8.0" /
                    ("creatio-tests.exe" if os.name == "nt" else "creatio-tests")).is_file()), None)
        cmd = [exe] if exe else ["dotnet", "run", "--project", str(self.tests_root / "src/CreatioAutoTests.Cli"), "--"]
        try:
            run = subprocess.run(cmd + ["--root", str(root), "--no-color"], cwd=root, capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=3600)
        finally:
            for f in secret:
                f.unlink(missing_ok=True)
        out = (run.stdout or "") + (run.stderr or "")
        dest.mkdir(parents=True, exist_ok=True)
        for f in sorted((root / "Reports").glob("*")) if (root / "Reports").is_dir() else []:
            if f.is_file() and f not in before:
                shutil.copy(f, dest / ("report" + f.suffix))
        m = COUNTS.search(out) or COUNTS.search("".join(p.read_text(encoding="utf-8", errors="replace") for p in dest.glob("report.txt")))
        if not m:
            return 0, 1, out + "\n(no summary line in the output: the run did not finish)"
        failed = int(m.group(3)) or int(run.returncode != 0)  # a non-zero exit with no failed case is still red
        return int(m.group(2)), failed, out

    def snapshot(self, schema: str) -> list[str]:
        from ..integrity import snapshot
        return snapshot(self.workspace, schema, self.env)

    def push(self, package: str) -> tuple[int, str]:
        from .merge import _context
        folder = _context(self.workspace).folders[package]
        run = subprocess.run([sys.executable, str(TOOLS / "push" / "push.py"), str(folder), "-e", self.env_name],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
        return run.returncode, (run.stdout or "") + (run.stderr or "")

    def descriptor_depends(self, package: str) -> list[str]:
        """The names in the package folder's descriptor `DependsOn` (the merged one, after `apply`)."""
        from .merge import _context
        path = _context(self.workspace).folders[package] / "descriptor.json"
        return [x["Name"] for x in json.loads(path.read_text(encoding="utf-8-sig"))["Descriptor"].get("DependsOn") or []]

    def site_depends(self, package: str) -> list[str]:
        """The names the site's SysPackageDependency holds for the package: push-pkg does not update them."""
        quoted = "'" + package.replace("'", "''") + "'"
        rows = self.env.sql('select d."Name" as "Name" from "SysPackageDependency" x join "SysPackage" p on p."Id" = x."SysPackageId" '
                            'join "SysPackage" d on d."Id" = x."DependOnPackageId" where p."Name" = ' + quoted)
        return [r["Name"] for r in rows]

    def audit(self, page: str) -> list[str]:
        """The `pages.py audit --all` lines of a page, wherever the workspace holds it."""
        from ..page import PageSchema
        from ..page.audit import audit
        from .merge import _context
        for folder in _context(self.workspace).folders.values():
            if (folder / "Schemas" / page / f"{page}.js").is_file():
                return audit(PageSchema(folder, page), True)
        return ["(page not found in the workspace)"]

    def order(self, packages: list[str]) -> list[str]:
        """Lower first: the package that reaches fewer others."""
        from .merge import _context
        reach = _context(self.workspace).reach
        return sorted(packages, key=lambda p: (len(reach.get(p, ())), p))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _tests(engines: Engines, root: Path, folder: Path, label: str) -> tuple[int, str]:
    passed, failed, out = engines.run_tests(root, folder)
    _write(folder / "run.txt", out)
    if failed:
        raise Stop(f"stop: tests {label}: {failed} red of {passed + failed} (see {folder.name}/report.*)")
    if not passed:
        raise Stop(f"stop: tests {label}: no case ran - nothing proves the merge")
    return passed, out


def merge_run(workspace: Path | str, child: str, parent: str, evidence: Path | str, env_name: str, apply: bool = False,
              resume: bool = False, engines: Engines | None = None) -> tuple[str, int]:
    engines = engines or Engines(Path(workspace), env_name)
    ev = Path(evidence).resolve()
    cases, before, after = ev / "cases", ev / "before", ev / "after"
    log: list[str] = []

    def say(line: str) -> None:
        log.append(line)

    def audit_pages(folder: Path) -> None:
        pages = sorted({line.split()[2] for line in (ev / "plan.txt").read_text(encoding="utf-8").splitlines()
                        if len(line.split()) >= 3 and line.split()[0] in ("layer", "move") and line.split()[1] == "page"})
        if pages:
            _write(folder / "audit.txt", "\n".join(f"=== {p}\n" + "\n".join(engines.audit(p)) for p in pages))

    def push_all(plan: str, check: bool) -> tuple[str, int]:
        if check:  # the merged descriptor may name a package the site's dependency rows of the parent do not hold
            held = set(engines.site_depends(parent))
            lacking = [d for d in engines.descriptor_depends(parent) if d != parent and d not in held]
            if lacking:
                _write(ev / PENDING, f"add the dependency {lacking[0]} to {parent} in the configuration, then rerun with --continue")
                raise Stop(f"stop: parent {parent} lacks the dependency {lacking[0]} on the site: add it in the configuration, then --continue")
        depends = [m.group(1) for m in re.finditer(r"^depends (\S+): DependsOn", plan, re.M)]
        pushed, text = [], []
        for pkg in engines.order([parent] + depends):
            rc, out = engines.push(pkg)
            text.append(f"=== {pkg}: exit {rc}\n{out}")
            _write(ev / "push.log", "\n".join(text))
            if rc:
                raise Stop(f"stop: push {pkg}: exit {rc} (push.log)")
            pushed.append(pkg)
        (ev / PENDING).unlink(missing_ok=True)
        say(f"push: {', '.join(pushed)}")
        _write(ev / PAUSED, f"remove the application of {child} on the site, then rerun with --continue")
        say(f"paused: remove the application of {child} on the site, then rerun with --continue")
        return "\n".join(log), 3

    try:
        if resume and (ev / PENDING).is_file():  # stopped before the push: the dependency is added now, the push goes on
            say(f"continue: pushing {parent} after the dependency was added")
            return push_all((ev / "plan.txt").read_text(encoding="utf-8"), True)
        if resume:
            if not (ev / PAUSED).is_file():
                raise Stop(f"stop: nothing to continue: {ev / PAUSED} does not exist")
            names = sorted(p.name.removesuffix(".snapshot") for p in before.glob("*.snapshot"))
            k = int((before / "passed.txt").read_text(encoding="utf-8").strip())
            say(f"continue: {child} removed from the site; {len(names)} snapshots to compare")
        else:
            plan, code = engines.merge_package(child, parent, False)
            _write(ev / "plan.txt", plan)
            if code:
                raise Stop(f"stop: plan: {plan.splitlines()[-1]}")
            say(f"plan: {len(plan.splitlines())} lines (plan.txt)")
            if not list(cases.rglob("*.act")):
                report = engines.cases(child, cases)
                _write(ev / "cases.txt", "\n".join(report) or "(no schema to write cases for)")
                say(f"cases: generated {sum(1 for r in report if r.startswith('wrote') and r.endswith('.act'))}, "
                    f"{sum(1 for r in report if r.startswith(('stop', 'not generated')))} not generated (cases.txt)")
            k, _ = _tests(engines, cases, before, "before")
            say(f"tests before: {k}/{k}")
            names = []
            for line in plan.splitlines():
                w = line.split()
                if len(w) >= 3 and w[0] in ("layer", "move") and w[1] in ("object", "page", "classic") and w[2] not in names:
                    names.append(w[2])
            for name in names:
                _write(before / f"{name}.snapshot", "\n".join(engines.snapshot(name)))
            (before / "passed.txt").write_text(str(k), encoding="utf-8")
            say(f"snapshots before: {len(names)}")
            audit_pages(before)
            if not apply:
                say("rehearsal: nothing written")
                return "\n".join(log), 0
            merged, code = engines.merge_package(child, parent, True)
            _write(ev / "merge.txt", merged)
            if code:
                raise Stop(f"stop: merge: {merged.splitlines()[-1]}")
            say("merge: written (merge.txt)")
            return push_all(plan, True)

        (ev / PAUSED).unlink()
        bad, compared = [], []
        for name in names:
            _write(after / f"{name}.snapshot", "\n".join(engines.snapshot(name)))
            from ..integrity import compare
            diff = compare((before / f"{name}.snapshot").read_text(encoding="utf-8").splitlines(),
                           (after / f"{name}.snapshot").read_text(encoding="utf-8").splitlines(), True)
            compared.append(f"=== {name}: {'same' if not diff else 'differs'}" + ("\n" + "\n".join(diff) if diff else ""))
            if diff:
                bad.append(name)
        audit_pages(after)
        _write(ev / "compare.txt", "(layer lines are ignored: a merge changes them by design)\n" + "\n".join(compared))
        say(f"compare: {len(names) - len(bad)} same, {len(bad)} differ (compare.txt)")
        if bad:
            raise Stop(f"stop: compare differs: {', '.join(bad)}")
        k2, _ = _tests(engines, cases, after, "after")
        if k2 != k:
            raise Stop(f"stop: tests after: {k2} cases ran, {k} before")
        plan = (ev / "plan.txt").read_text(encoding="utf-8").splitlines()
        layers, moves = (sum(1 for line in plan if line.startswith(w)) for w in ("layer", "move"))
        say(f"merged {child} into {parent}: {layers} layers, {moves} moves, tests {k}/{k} before and after, compare same")
        return "\n".join(log), 0
    except Stop as stop:
        say(str(stop))
        return "\n".join(log), 1
    finally:
        if log:
            ev.mkdir(parents=True, exist_ok=True)
            with (ev / "run.log").open("a", encoding="utf-8") as f:  # a --continue adds to the first run's lines
                f.write("\n".join(log) + "\n")
