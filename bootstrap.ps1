<#
.SYNOPSIS
Installs or updates the software the kit needs on a Windows machine, then registers the MCP servers.

.DESCRIPTION
Every item is checked first: present -> upgraded in place (winget upgrade / dotnet tool update), absent -> installed.
Nothing is reinstalled from scratch. Items: Git, Python 3.12, .NET SDK 8, Node.js LTS (context7 runs through npx),
clio (dotnet tool), the Playwright Chromium of the test framework, and with -With: the .NET SDK 10 (roslyn-codelens),
Docker Desktop. Agent CLIs are not installed: install the one you use (Claude Code, Codex CLI or GitHub Copilot CLI),
then run this script; it ends with agent_setup.py, which registers the servers for every agent it finds.

.PARAMETER Check
Print the table of what is present (with versions) and what is missing; change nothing.

.PARAMETER With
Optional items to add: dotnet10, docker.

.PARAMETER SkipBrowser
Do not build the test framework or download the Playwright browser (about 150 MB).

.EXAMPLE
.\bootstrap.ps1 -Check
.\bootstrap.ps1
.\bootstrap.ps1 -With dotnet10 -SkipBrowser
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [string[]]$With = @(),
    [switch]$SkipBrowser
)

$ErrorActionPreference = "Stop"
$With = @($With | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ })  # -File passes "a,b" as one string
$unknown = @($With | Where-Object { $_ -notin @("dotnet10", "docker") })
if ($unknown.Count -gt 0) { throw "-With takes dotnet10, docker; not: $($unknown -join ', ')" }
$kit = Split-Path -Parent $MyInvocation.MyCommand.Path

function Refresh-Path {
    # a winget install changes the registry PATH, not this console's: reread both halves
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Get-Version([string]$exe, [string[]]$argv) {
    $cmd = Get-Command $exe -ErrorAction SilentlyContinue
    if ($null -eq $cmd) { return $null }
    try { $out = & $exe @argv | Select-Object -First 1 } catch { return "?" }
    if ([string]::IsNullOrWhiteSpace($out)) { return "?" }
    return ($out -replace "^[^\d]*", "").Trim()
}

function Get-DotnetSdk([string]$pattern) {
    if ($null -eq (Get-Command dotnet -ErrorAction SilentlyContinue)) { return $null }
    $sdk = dotnet --list-sdks | Where-Object { $_ -match $pattern } | Select-Object -Last 1
    if ($null -eq $sdk) { return $null }
    return ($sdk -split " ")[0]
}

function Get-ClioVersion {
    if ($null -eq (Get-Command dotnet -ErrorAction SilentlyContinue)) { return $null }
    $row = dotnet tool list -g | Where-Object { $_ -match "^clio\s" }
    if ($null -eq $row) { return $null }
    return ($row -split "\s+")[1]
}

function Get-BrowserVersion {
    $root = Join-Path $env:LOCALAPPDATA "ms-playwright"
    if (-not (Test-Path $root)) { return $null }
    $dir = Get-ChildItem $root -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue | Select-Object -Last 1
    if ($null -eq $dir) { return $null }
    return $dir.Name
}

function Invoke-Winget([string]$id, [string]$present) {
    if ($null -eq $present) {
        Write-Host "  installing $id" -ForegroundColor Yellow
        winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "  upgrading $id (have $present)" -ForegroundColor DarkGray
        winget upgrade --id $id --exact --silent --accept-package-agreements --accept-source-agreements --include-unknown
        if ($LASTEXITCODE -ne 0) { Write-Host "  no newer $id, kept" -ForegroundColor DarkGray }
    }
    $global:LASTEXITCODE = 0
    Refresh-Path
}

# --- the items: name, how to read the version, how to install or update ------------------------------------------
$items = @(
    @{ Name = "Git";          Version = { Get-Version "git" @("--version") };    Apply = { param($v) Invoke-Winget "Git.Git" $v } },
    @{ Name = "Python 3.10+ (py -3)"; Version = { Get-Version "py" @("-3", "--version") }; Apply = { param($v) Invoke-Winget "Python.Python.3.12" $v } },
    @{ Name = ".NET SDK 8+";  Version = { Get-DotnetSdk "^(8|9|\d\d)\." };                   Apply = { param($v) Invoke-Winget "Microsoft.DotNet.SDK.8" $v } },
    @{ Name = "Node.js LTS";  Version = { Get-Version "node" @("--version") };   Apply = { param($v) Invoke-Winget "OpenJS.NodeJS.LTS" $v } },
    @{ Name = "clio";         Version = { Get-ClioVersion };                     Apply = { param($v)
        if ($null -eq $v) { Write-Host "  installing clio" -ForegroundColor Yellow; dotnet tool install -g clio }
        else { Write-Host "  updating clio (have $v)" -ForegroundColor DarkGray; dotnet tool update -g clio }
        Refresh-Path } }
)
if ($With -contains "dotnet10") {
    $items += @{ Name = ".NET SDK 10 (roslyn-codelens)"; Version = { Get-DotnetSdk "^10\." }; Apply = { param($v) Invoke-Winget "Microsoft.DotNet.SDK.10" $v } }
}
if ($With -contains "docker") {
    $items += @{ Name = "Docker Desktop"; Version = { Get-Version "docker" @("--version") }; Apply = { param($v) Invoke-Winget "Docker.DockerDesktop" $v } }
}
if (-not $SkipBrowser) {
    $items += @{ Name = "Playwright Chromium"; Version = { Get-BrowserVersion }; Apply = { param($v)
        $tests = Join-Path $kit "automatic-creatio-tests"
        Write-Host "  building the test framework" -ForegroundColor DarkGray
        dotnet build $tests --nologo -v q
        if ($LASTEXITCODE -ne 0) { throw "dotnet build of automatic-creatio-tests failed" }
        $pw = Get-ChildItem (Join-Path $tests "src\CreatioAutoTests.Cli\bin") -Recurse -Filter "playwright.ps1" | Select-Object -First 1
        if ($null -eq $pw) { throw "playwright.ps1 not found under the CLI's bin folder" }
        if ($null -eq $v) { Write-Host "  installing Chromium" -ForegroundColor Yellow } else { Write-Host "  Chromium present ($v), playwright checks its version" -ForegroundColor DarkGray }
        & $pw.FullName install chromium } }
}

# --- check or apply ------------------------------------------------------------------------------------------------
Refresh-Path
$missing = 0
Write-Host ""
Write-Host ("{0,-32} {1}" -f "Item", "Present") -ForegroundColor Cyan
foreach ($item in $items) {
    $v = & $item.Version
    if ($null -eq $v) { $missing++; Write-Host ("{0,-32} {1}" -f $item.Name, "missing") -ForegroundColor Red }
    else { Write-Host ("{0,-32} {1}" -f $item.Name, $v) }
}
$agents = @("claude", "codex", "copilot") | Where-Object { $null -ne (Get-Command $_ -ErrorAction SilentlyContinue) }
if ($agents.Count -eq 0) { Write-Host ("{0,-32} {1}" -f "Agent CLI", "none: install Claude Code, Codex CLI or GitHub Copilot CLI yourself") -ForegroundColor Red }
else { Write-Host ("{0,-32} {1}" -f "Agent CLI", ($agents -join ", ")) }
Write-Host ""
if ($Check) { exit $missing }

if ($null -eq (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget is not available: install 'App Installer' from the Microsoft Store, then run this script again"
}
foreach ($item in $items) {
    Write-Host $item.Name -ForegroundColor Cyan
    $v = & $item.Version
    & $item.Apply $v
}

Write-Host ""
Write-Host "Registering the MCP servers (agent_setup.py)" -ForegroundColor Cyan
Refresh-Path
if ($agents.Count -eq 0 -and $null -eq (Get-Command claude -ErrorAction SilentlyContinue) -and $null -eq (Get-Command codex -ErrorAction SilentlyContinue) -and $null -eq (Get-Command copilot -ErrorAction SilentlyContinue)) {
    Write-Host "  no agent CLI found: install one, then run  py -3 agent_setup.py" -ForegroundColor Yellow
} else {
    & py -3 (Join-Path $kit "agent_setup.py")
}
Write-Host ""
Write-Host "Done. Open a new console so every PATH change is seen, then: .\bootstrap.ps1 -Check" -ForegroundColor Green
