param(
    [string]$VenvDir = "venv",
    [switch]$InstallDev,
    [switch]$RunTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ResolvedVenvDir = if ([System.IO.Path]::IsPathRooted($VenvDir)) {
    $VenvDir
}
else {
    Join-Path $RepoRoot $VenvDir
}
$VenvPython = Join-Path $ResolvedVenvDir "Scripts\python.exe"
$SkillsRoot = if ([string]::IsNullOrWhiteSpace($env:HYPERAGENT_SKILLS_ROOT)) {
    Join-Path $RepoRoot "skill"
}
else {
    $env:HYPERAGENT_SKILLS_ROOT
}
$DefaultConfigPath = Join-Path (Join-Path $HOME ".hyperagent") "config.yaml"
$RequiredSkillDirs = @(
    "_hyperagent-common",
    "hyperagent-prepare-env",
    "hyperagent-static",
    "hyperagent-unpack",
    "hyperagent-dynamic",
    "hyperagent-intel",
    "hyperagent-deepdive",
    "hyperagent-report",
    "hyperagent-summary"
)

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Resolve-CommandPath([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command -and $command.Source) {
        return $command.Source
    }
    return $null
}

function Get-PythonCommand() {
    $pythonPath = Resolve-CommandPath "python"
    if (-not $pythonPath) {
        throw "python was not found on PATH. Install Python 3.11+ and rerun bootstrap.ps1."
    }

    $version = & $pythonPath -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    $isSupported = & $pythonPath -c "import sys; print('yes' if sys.version_info >= (3, 11) else 'no')"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to query Python version from $pythonPath"
    }
    if ($isSupported.Trim() -ne "yes") {
        throw "HyperAgent requires Python 3.11+. Found $version at $pythonPath"
    }

    Write-Host "Python: $version ($pythonPath)"
    return $pythonPath
}

function Ensure-Venv([string]$PythonPath, [string]$VenvPath) {
    if (-not (Test-Path $VenvPath)) {
        & $PythonPath -m venv $VenvPath
    }

    $venvPythonPath = Join-Path $VenvPath "Scripts\python.exe"
    if (-not (Test-Path $venvPythonPath)) {
        throw "Virtual environment Python was not created at $venvPythonPath"
    }

    return $venvPythonPath
}

function Install-PythonPackage([string]$PythonPath) {
    $editableTarget = if ($InstallDev -or $RunTests) { ".[dev]" } else { "." }

    & $PythonPath -m pip install --upgrade pip
    & $PythonPath -m pip install -e $editableTarget
}

function Test-ExternalCommand([string]$Name, [string]$NeededFor) {
    $path = Resolve-CommandPath $Name
    return [pscustomobject]@{
        Name = $Name
        NeededFor = $NeededFor
        Path = if ($path) { $path } else { "missing" }
        Found = [bool]$path
    }
}

function Test-SkillDirectories([string]$RootPath, [string[]]$SkillDirs) {
    $results = @()
    foreach ($skillDir in $SkillDirs) {
        $fullPath = Join-Path $RootPath $skillDir
        $results += [pscustomobject]@{
            Name = $skillDir
            Path = $fullPath
            Found = (Test-Path $fullPath -PathType Container)
        }
    }
    return $results
}

Write-Step "Checking Python"
$Python = Get-PythonCommand

Write-Step "Creating virtual environment"
$VenvPython = Ensure-Venv -PythonPath $Python -VenvPath $ResolvedVenvDir
Write-Host "Virtualenv: $ResolvedVenvDir"

Write-Step "Installing HyperAgent package"
Install-PythonPackage -PythonPath $VenvPython

Write-Step "Running Python smoke checks"
& $VenvPython -m pip check
& $VenvPython -c "import hyperagent; from hyperagent.config import load_config; from hyperagent.engine.launcher import STAGES; cfg = load_config(); print(f'hyperagent_import_ok stages={len(STAGES)} provider={cfg.provider.name}')"

if ($RunTests) {
    Write-Step "Running test suite"
    & $VenvPython -m pytest hyperagent/tests/ -q
}

Write-Step "Checking external tools"
$toolChecks = @(
    (Test-ExternalCommand -Name "vmrun" -NeededFor "VMware guest control for 05-dynamic"),
    (Test-ExternalCommand -Name "idalib-mcp" -NeededFor "Host-side local IDA MCP bootstrap"),
    (Test-ExternalCommand -Name "upx" -NeededFor "UPX unpack helper used by 03-unpack")
)
foreach ($tool in $toolChecks) {
    $status = if ($tool.Found) { "OK" } else { "MISSING" }
    $color = if ($tool.Found) { "Green" } else { "Yellow" }
    Write-Host ("[{0}] {1} -> {2} ({3})" -f $status, $tool.Name, $tool.Path, $tool.NeededFor) -ForegroundColor $color
}
Write-Host "x64dbg MCP is not a host CLI dependency; point HYPERAGENT_X64DBG_MCP_URL at the guest service when it is available."

Write-Step "Checking stage skills"
Write-Host "Skills root: $SkillsRoot"
$skillChecks = Test-SkillDirectories -RootPath $SkillsRoot -SkillDirs $RequiredSkillDirs
foreach ($skill in $skillChecks) {
    $status = if ($skill.Found) { "OK" } else { "MISSING" }
    $color = if ($skill.Found) { "Green" } else { "Yellow" }
    Write-Host ("[{0}] {1} -> {2}" -f $status, $skill.Name, $skill.Path) -ForegroundColor $color
}

Write-Step "Manual configuration still needed"
if ([string]::IsNullOrWhiteSpace($env:ANTHROPIC_API_KEY)) {
    Write-Warning "ANTHROPIC_API_KEY is not set. Real pipeline runs will fail until you export it."
}
else {
    Write-Host "ANTHROPIC_API_KEY is set for this shell." -ForegroundColor Green
}
Write-Host "Default config file location: $DefaultConfigPath"
Write-Host "Set HYPERAGENT_VMX_PATH, HYPERAGENT_VM_SNAPSHOT, HYPERAGENT_GUEST_USER, HYPERAGENT_GUEST_PASSWORD, HYPERAGENT_GUEST_DESKTOP, and HYPERAGENT_GUEST_DEBUGGER before using 05-dynamic."
Write-Host "Set HYPERAGENT_IDA_MCP_URL and HYPERAGENT_X64DBG_MCP_URL if you do not want the built-in defaults."
Write-Host "Set VT_API_KEY or VIRUSTOTAL_API_KEY before using 06-intel."

Write-Step "Next steps"
Write-Host ("  {0}\Scripts\Activate.ps1" -f $ResolvedVenvDir)
Write-Host "  hyperagent analyze C:\path\to\sample.exe"
Write-Host "  hyperagent analyze C:\path\to\sample.exe --stage 01-prepare-env"
