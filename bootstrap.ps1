param(
    [string]$VenvDir = "venv",
    [switch]$InstallDev,
    [switch]$RunTests,
    # Install what can be installed unattended (upx via winget) and persist a
    # discovered VMware directory to the user PATH.
    [switch]$InstallTools,
    # Exit non-zero when a required tool or stage skill is missing.
    [switch]$Strict
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

function Add-ToPath([string]$Directory, [switch]$Persist) {
    $entries = $env:Path -split ";"
    if ($entries -notcontains $Directory) {
        $env:Path = "$env:Path;$Directory"
    }
    if ($Persist) {
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        if ([string]::IsNullOrEmpty($userPath)) {
            $userPath = ""
        }
        if (($userPath -split ";") -notcontains $Directory) {
            $newPath = if ($userPath) { "$userPath;$Directory" } else { $Directory }
            [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
            Write-Host "Added $Directory to the user PATH (open a new shell to pick it up)."
        }
    }
}

function Update-SessionPath() {
    # Pick up PATH entries added by an installer without restarting the shell.
    $known = $env:Path -split ";"
    foreach ($scope in "Machine", "User") {
        $value = [Environment]::GetEnvironmentVariable("Path", $scope)
        if ([string]::IsNullOrEmpty($value)) { continue }
        foreach ($entry in ($value -split ";")) {
            if ($entry -and ($known -notcontains $entry)) {
                $env:Path = "$env:Path;$entry"
                $known += $entry
            }
        }
    }
}

# hyperagent resolves a bare `vmrun` via PATH, so a VMware install that is not
# on PATH looks missing even though it is present. Returns the install dir only
# when vmrun exists on disk but is not resolvable yet.
function Find-VmrunDirectory() {
    if (Resolve-CommandPath "vmrun") {
        return $null
    }

    $candidates = @()
    $registryKey = "HKLM:\SOFTWARE\WOW6432Node\VMware, Inc.\VMware Workstation"
    $registry = Get-ItemProperty -Path $registryKey -ErrorAction SilentlyContinue
    if ($registry -and ($registry.PSObject.Properties.Name -contains "InstallPath")) {
        $candidates += $registry.InstallPath
    }
    foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if ($base) {
            $candidates += Join-Path $base "VMware\VMware Workstation"
        }
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path (Join-Path $candidate "vmrun.exe"))) {
            return $candidate.TrimEnd("\")
        }
    }
    return $null
}

function Install-Upx() {
    $winget = Resolve-CommandPath "winget"
    if (-not $winget) {
        Write-Warning "winget not found; install upx manually (https://upx.github.io/)."
        return
    }

    & $winget install --id upx.upx --exact --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "winget could not install upx (exit code $LASTEXITCODE)."
        return
    }
    Update-SessionPath
}

function Ensure-ConfigTemplate([string]$ConfigPath) {
    if (Test-Path $ConfigPath) {
        Write-Host "Config exists, leaving it untouched: $ConfigPath"
        return
    }

    $configDir = Split-Path -Parent $ConfigPath
    if (-not (Test-Path $configDir)) {
        New-Item -ItemType Directory -Path $configDir -Force | Out-Null
    }

    # Everything is commented out so the file is valid until the user opts in.
    # Secrets (API keys, guest password) belong in environment variables.
    $template = @'
# HyperAgent configuration. Environment variables override these values.
# Uncomment and fill in what you need. Keep API keys in the environment.

# provider:
#   name: "anthropic"
#   model: ""

# vmware:                      # required for the 05-dynamic stage
#   vmx_path: "C:\\VMs\\analysis\\analysis.vmx"
#   snapshot_name: "clean"
#   guest_user: ""
#   guest_desktop: ""
#   guest_debugger: ""
#   # guest_password: set HYPERAGENT_GUEST_PASSWORD instead

# ida_mcp:
#   url: "http://localhost:13337/mcp"

# x64dbg_mcp:
#   url: "http://<guest-ip>:3000/mcp"
'@
    Set-Content -Path $ConfigPath -Value $template -Encoding UTF8
    Write-Host "Created config template: $ConfigPath"
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
$vmrunDir = Find-VmrunDirectory
if ($vmrunDir) {
    Write-Host "vmrun found at $vmrunDir but not on PATH; adding it."
    Add-ToPath -Directory $vmrunDir -Persist:$InstallTools
}
if ($InstallTools -and -not (Resolve-CommandPath "upx")) {
    Write-Host "Installing upx with winget"
    Install-Upx
}
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

Write-Step "Preparing config file"
Ensure-ConfigTemplate -ConfigPath $DefaultConfigPath

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

$missingTools = @($toolChecks | Where-Object { -not $_.Found } | ForEach-Object { $_.Name })
$missingSkills = @($skillChecks | Where-Object { -not $_.Found } | ForEach-Object { $_.Name })
$missing = @($missingTools + $missingSkills)
if ($missing.Count -gt 0) {
    $summary = "Missing: " + ($missing -join ", ")
    if ($Strict) {
        Write-Host "`n$summary" -ForegroundColor Red
        exit 1
    }
    Write-Warning "$summary (rerun with -Strict to fail on this)."
}
