#!/usr/bin/env python3
"""
Sets up the kit for the AI agents on this machine: Claude Code, Codex CLI and GitHub Copilot CLI.
For every agent found it registers the MCP servers at user scope and installs the four Creatio skills;
the servers' virtual environments are created once. Every step is idempotent: re-running updates or
re-registers without duplicates.
  creatio-kb       MCP      the knowledge base, the toolkits, the describe and environment layers (44 tools)
  creatio-tests    MCP      the test framework: the DSL, the cases, validate, run, analyse (11 tools)
  context7         MCP      up-to-date library docs (Angular, RxJS, npm packages)
  microsoft-learn  MCP      official .NET / C# documentation (remote, HTTP)
  roslyn-codelens  MCP      Roslyn semantic analysis of C# solutions (needs the .NET 10 SDK)
  clio             MCP      clio's own server (`clio mcp-server`): rights, settings, DataService batches, bindings from the
                            site, the component catalogue, browser sessions; its telemetry is declined once (needs clio on PATH)
  skills           files    creatio-kb, creatio-author, creatio-tester, creatio-loop
  ponytail, graphify        Claude Code only: a plugin and a skill
    py -3 agent_setup.py                     # every agent found on PATH (python3 on macOS and Linux)
    py -3 agent_setup.py --agents codex      # one or more of claude, codex, copilot (comma-separated)
    py -3 agent_setup.py --dry-run           # print the commands only
    py -3 agent_setup.py --check             # what would be set up, register nothing
Where each agent keeps it: Claude Code `claude mcp` (user scope) and ~/.claude/skills; Codex ~/.codex/config.toml
and ~/.agents/skills; Copilot ~/.copilot/mcp-config.json and ~/.agents/skills (Copilot reads ~/.agents/skills too).
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KB = ROOT / "creatio-knowledge-base"
TESTS = ROOT / "automatic-creatio-tests"
ARGS = sys.argv[1:]
DRY_RUN = "--dry-run" in ARGS
WIN = sys.platform == "win32"
HOME = Path.home()
SKILLS = ("creatio-kb", "creatio-author", "creatio-tester", "creatio-loop")
SKILL_HOMES = {"claude": HOME / ".claude" / "skills", "codex": HOME / ".agents" / "skills", "copilot": HOME / ".agents" / "skills"}


def python_launcher() -> list[str] | None:
    """Try both launchers before making any changes: `py -3` first on Windows (a bare `python` there may be the Microsoft Store
    stub), `python3` first elsewhere. The MCP servers are registered with the venv's interpreter path, never with a launcher."""
    verdicts = []
    candidates = (["py", "-3"], ["python"]) if WIN else (["python3"], ["python"])
    for launcher in candidates:
        try:
            result = subprocess.run(launcher + ["-c", "import sys;print(sys.version)"], capture_output=True, text=True, timeout=15)
            text = (result.stdout + result.stderr).strip()
            ok = result.returncode == 0 and text.startswith("3.") and "microsoft store" not in text.lower()
        except (OSError, subprocess.TimeoutExpired) as exc:
            text, ok = str(exc), False
        print(f"{' '.join(launcher)}: {'works' if ok else 'unavailable'}" + (f" ({text.splitlines()[0]})" if text else ""))
        verdicts.append(ok)
    return next((launcher for launcher, ok in zip(candidates, verdicts) if ok), None)


def run(title: str, cmd: list[str]) -> int:
    print(f"\n== {title}\n   {' '.join(cmd)}")
    if DRY_RUN:
        return 0
    try:
        code = subprocess.run(cmd).returncode
    except FileNotFoundError:
        print(f"   warning: command not found: {cmd[0]}")  # a missing tool skips this step only
        return 127
    if code != 0:
        print(f"   warning: exit code {code}")
    return code


def find_agents() -> dict[str, str]:
    """The agent CLIs on this machine: name -> executable."""
    found = {}
    for name in ("claude", "codex", "copilot"):
        exe = shutil.which(name)
        if not exe and name == "claude":  # the VS Code extension ships its own binary that is not on PATH
            pattern = str(HOME / ".vscode" / "extensions" / "anthropic.claude-code-*" / "resources" / "native-binary" / ("claude.exe" if WIN else "claude"))
            hits = sorted(glob.glob(pattern))
            exe = hits[-1] if hits else None
        if exe and answers(exe):
            found[name] = exe
    return found


def answers(exe: str) -> bool:
    """A real CLI answers --version with exit 0; VS Code's copilot shim only prints that the CLI is not installed."""
    try:
        return subprocess.run([exe, "--version"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def wanted_agents(found: dict[str, str]) -> dict[str, str]:
    if "--agents" not in ARGS:
        return found
    names = [n.strip() for n in ARGS[ARGS.index("--agents") + 1].split(",") if n.strip()]
    missing = [n for n in names if n not in found]
    if missing:
        sys.exit(f"not installed: {', '.join(missing)} (found: {', '.join(found) or 'none'})")
    return {n: found[n] for n in names}


def register(agent: str, exe: str, name: str, command: list[str] | None = None, url: str | None = None, env: dict[str, str] | None = None) -> None:
    """One MCP server for one agent, at user scope; an existing entry of the same name is replaced."""
    env_args = [a for k, v in (env or {}).items() for a in ("--env", f"{k}={v}")]
    if agent == "claude":
        run(f"{agent}: remove old {name}", [exe, "mcp", "remove", "--scope", "user", name])
        add = [exe, "mcp", "add", "--scope", "user"]  # --env takes many values: it goes after the name, never before
        run(f"{agent}: add {name}", add + (["--transport", "http", name, url] if url else [name, *env_args, "--", *command]))
    elif agent == "codex":
        run(f"{agent}: remove old {name}", [exe, "mcp", "remove", name])
        run(f"{agent}: add {name}", [exe, "mcp", "add", name, *env_args] + (["--url", url] if url else ["--", *command]))
    elif agent == "copilot":
        run(f"{agent}: remove old {name}", [exe, "mcp", "remove", name])
        run(f"{agent}: add {name}", [exe, "mcp", "add"] + (["--transport", "http", name, url] if url else [name, *env_args, "--", *command]))


def decline_clio_telemetry() -> None:
    """clio's MCP asks every agent for telemetry consent until `~/.clio/telemetry/consent.json` holds an answer (`CLIO_TELEMETRY_HOME`
    moves it); written once as `denied`, never over an existing answer. The shape is clio's `ConsentState` (clio 8.1.0.158)."""
    root = Path(os.environ.get("CLIO_TELEMETRY_HOME") or Path.home() / ".clio" / "telemetry")
    path = root / "consent.json"
    if path.exists():
        print(f"clio telemetry: {path} exists, kept")
        return
    print(f"clio telemetry: write denied -> {path}")
    if not DRY_RUN:
        root.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        path.write_text(json.dumps({"telemetry_consent": "denied", "updated_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")


def install_skills(agent: str) -> None:
    """The four Creatio skills, copied into the agent's personal skills folder (re-running refreshes them)."""
    home = SKILL_HOMES[agent]
    print(f"\n== {agent}: skills -> {home}")
    for skill in SKILLS:
        src, dst = KB / "skill" / skill, home / skill
        print(f"   {skill}")
        if not DRY_RUN:
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)


def venv_python(server_dir: Path, launcher: list[str], install: list[str]) -> Path:
    venv = server_dir / ".venv"
    py = venv / ("Scripts/python.exe" if WIN else "bin/python")
    if not py.exists():
        run(f"{server_dir.parent.name}: venv", launcher + ["-m", "venv", str(venv)])
    run(f"{server_dir.parent.name}: pip install", [str(py), "-m", "pip", "install", "-q", *install])
    return py


def main() -> None:
    launcher = python_launcher()
    if launcher is None:
        sys.exit("Neither " + ("py -3" if WIN else "python3") + " nor python works; install Python before registering servers.")
    print("Selected Python launcher: " + " ".join(launcher))
    agents = wanted_agents(find_agents())
    sdks = subprocess.run(["dotnet", "--list-sdks"], capture_output=True, text=True).stdout if shutil.which("dotnet") else ""
    roslyn = any(line.startswith("10.") for line in sdks.splitlines())
    print("Agents: " + (", ".join(f"{n} ({e})" for n, e in agents.items()) or "none found (claude, codex, copilot not on PATH)"))
    clio = shutil.which("clio")
    if "--check" in ARGS:
        print("Servers: creatio-kb, creatio-tests, context7, microsoft-learn" + (", roslyn-codelens" if roslyn else " (roslyn-codelens skipped: no .NET 10 SDK)")
              + (", clio" if clio else " (clio skipped: not on PATH - dotnet tool install -g clio)"))
        print("Skills: " + ", ".join(SKILLS))
        return
    if not agents:
        sys.exit("No agent CLI found. Install Claude Code, Codex CLI or GitHub Copilot CLI, or add one to PATH.")

    # The servers of this kit: one venv each, created once.
    kb_py = venv_python(KB / "mcp-server", launcher, ["-e", str(KB / "mcp-server")])
    tests_py = venv_python(TESTS / "mcp-server", launcher, ["mcp>=2.0"])
    if roslyn:
        run("dotnet tool: RoslynCodeLens.Mcp", ["dotnet", "tool", "update", "-g", "RoslynCodeLens.Mcp"])
    else:
        print("\nroslyn-codelens skipped: .NET 10 SDK not found (dotnet --list-sdks).")
    context7 = ["npx", "-y", "@upstash/context7-mcp"] + (["--api-key", os.environ["CONTEXT7_API_KEY"]] if os.environ.get("CONTEXT7_API_KEY") else [])
    if clio:
        decline_clio_telemetry()
    else:
        print("\nclio skipped: not on PATH (dotnet tool install -g clio), its MCP server is not registered.")

    for agent, exe in agents.items():
        print(f"\n#### {agent}: {exe}")
        register(agent, exe, "creatio-kb", [str(kb_py), str(KB / "mcp-server" / "server.py")])
        register(agent, exe, "creatio-tests", [str(tests_py), str(TESTS / "mcp-server" / "server.py")])
        register(agent, exe, "context7", context7)
        register(agent, exe, "microsoft-learn", url="https://learn.microsoft.com/api/mcp")
        if roslyn:  # Creatio package csproj files are SDK-style (net472), which is what the server requires
            register(agent, exe, "roslyn-codelens", ["roslyn-codelens-mcp"], env={"MCP_TIMEOUT": "120000"})
        if clio:  # the long tail of its 255 tools is reached through `clio-run`; 18 resident tools in tools/list
            register(agent, exe, "clio", [clio, "mcp-server"])
        install_skills(agent)
        if agent == "claude":
            run("claude: plugin ponytail", [exe, "plugin", "install", "ponytail", "--marketplace", "DietrichGebert/ponytail"])
            run("claude: graphify pip install", [sys.executable, "-m", "pip", "install", "--upgrade", "graphifyy[mcp]"])
            run("claude: graphify register skill", [sys.executable, "-m", "graphify", "install"])  # writes ~/.claude/skills/graphify

    checks = {"claude": "claude mcp list", "codex": "codex mcp list", "copilot": "copilot mcp list"}
    print("\nDone. Restart the agents; check with: " + " / ".join(checks[a] for a in agents))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # S33-T09: a Cyrillic path must not need PYTHONIOENCODING
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    main()
