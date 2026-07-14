param(
    [switch]$Force,
    [switch]$SkipVerify
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $RepoRoot '.venv'
$ConfigTemplatePath = Join-Path $RepoRoot 'config.yaml.template'
$ConfigPath = Join-Path $RepoRoot 'config.yaml'
$RequirementsPath = Join-Path $RepoRoot 'requirements.txt'
$SkillSourceDir = Join-Path $RepoRoot 'skill'
$ClaudeHomeOverride = [Environment]::GetEnvironmentVariable('HYPERAGENT_CLAUDE_HOME')
$ClaudeHomeDir = if (-not [string]::IsNullOrWhiteSpace($ClaudeHomeOverride)) { $ClaudeHomeOverride } else { Join-Path $HOME '.claude' }
$InstalledSkillRootDir = Join-Path $ClaudeHomeDir 'skills'
$IdaRootOverride = [Environment]::GetEnvironmentVariable('HYPERAGENT_IDA_ROOT')
$IdaActivationOverride = [Environment]::GetEnvironmentVariable('HYPERAGENT_IDALIB_ACTIVATE')
$IdaMcpPluginCommand = 'ida-pro-mcp@mrexodia'
$IdaMarketplaceCommand = 'mrexodia/claude-marketplace'
$IdaActivationScript = $null
$IdaRootDir = $null

function Write-Step($Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Resolve-CommandPath($Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command -and $command.Source) {
        return $command.Source
    }
    return $null
}

function Copy-DirectoryContents($Source, $Destination) {
    if (-not (Test-Path $Destination)) {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }

    Get-ChildItem -Path $Source -Force | ForEach-Object {
        $targetPath = Join-Path $Destination $_.Name
        Copy-Item -Path $_.FullName -Destination $targetPath -Recurse -Force
    }
}

function Install-ClaudeSkill($SourceDir, $DestinationDir) {
    $parentDir = Split-Path -Parent $DestinationDir
    if (-not (Test-Path $parentDir)) {
        New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
    }
    if (-not (Test-Path $DestinationDir)) {
        New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null
    }

    Copy-DirectoryContents -Source $SourceDir -Destination $DestinationDir
}

function Install-NodeJs {
    $winget = Resolve-CommandPath 'winget'
    if (-not $winget) {
        throw 'Node.js is missing and winget is not available to install it automatically.'
    }

    & $winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
}

function Install-ClaudeCodeCli {
    $npm = Resolve-CommandPath 'npm'
    if (-not $npm) {
        throw 'npm is missing, so Claude Code CLI cannot be installed automatically.'
    }

    & $npm install -g @anthropic-ai/claude-code
}

function Install-Uv {
    & python -m pip install --upgrade uv
}

function Find-IdaActivationScript {
    if (-not [string]::IsNullOrWhiteSpace($IdaActivationOverride) -and (Test-Path $IdaActivationOverride)) {
        return $IdaActivationOverride
    }

    if (-not [string]::IsNullOrWhiteSpace($IdaRootOverride)) {
        $overrideCandidate = Join-Path $IdaRootOverride 'idalib\python\py-activate-idalib.py'
        if (Test-Path $overrideCandidate) {
            return $overrideCandidate
        }
    }

    $searchRoots = @('C:\Program Files', 'C:\Program Files (x86)')
    foreach ($searchRoot in $searchRoots) {
        if (-not (Test-Path $searchRoot)) {
            continue
        }

        $match = Get-ChildItem -Path $searchRoot -Directory -Filter 'IDA Professional*' -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($match) {
            $candidate = Join-Path $match.FullName 'idalib\python\py-activate-idalib.py'
            if (Test-Path $candidate) {
                return $candidate
            }
        }
    }

    return $null
}

function Install-ClaudePlugin {
    param(
        [string]$PluginSource,
        [string]$PluginName
    )

    & claude plugin marketplace add $PluginSource
    & claude plugin install $PluginName
}

function Activate-Idalib {
    param(
        [string]$ActivationScript,
        [string]$PythonExe
    )

    if (-not $ActivationScript) {
        return $false
    }

    & $PythonExe $ActivationScript
    return $true
}

function Ensure-CommandAvailable($Name, $InstallScript, $FailureMessage) {
    $resolved = Resolve-CommandPath $Name
    if ($resolved) {
        return $resolved
    }

    Write-Host "$Name not found. Attempting installation..." -ForegroundColor Yellow
    & $InstallScript

    $resolved = Resolve-CommandPath $Name
    if ($resolved) {
        return $resolved
    }

    throw $FailureMessage
}

function Resolve-ToolValue($OverrideName, $DefaultCommand) {
    $overrideValue = [Environment]::GetEnvironmentVariable($OverrideName)
    if (-not [string]::IsNullOrWhiteSpace($overrideValue)) {
        return @{
            Value = $overrideValue
            Source = "env:$OverrideName"
            Resolved = $true
        }
    }

    $resolved = Resolve-CommandPath $DefaultCommand
    if ($resolved) {
        return @{
            Value = $DefaultCommand
            Source = 'PATH'
            Resolved = $true
        }
    }

    return @{
        Value = $DefaultCommand
        Source = 'default'
        Resolved = $false
    }
}

function Resolve-CommandListValue($OverrideName, $DefaultList) {
    $overrideValue = [Environment]::GetEnvironmentVariable($OverrideName)
    if (-not [string]::IsNullOrWhiteSpace($overrideValue)) {
        try {
            $parsed = $overrideValue | ConvertFrom-Json -ErrorAction Stop
            if ($parsed -is [System.Array]) {
                return @{
                    Value = @($parsed)
                    Source = "env:$OverrideName"
                    Resolved = $true
                }
            }
        }
        catch {
        }

        return @{
            Value = @($overrideValue)
            Source = "env:$OverrideName"
            Resolved = $true
        }
    }

    $first = $DefaultList[0]
    if ($first -and (Resolve-CommandPath $first)) {
        return @{
            Value = $DefaultList
            Source = 'PATH'
            Resolved = $true
        }
    }

    return @{
        Value = $DefaultList
        Source = 'default'
        Resolved = $false
    }
}

function ConvertTo-InlineYamlArray($Values) {
    $quoted = $Values | ForEach-Object {
        '"' + ($_ -replace '"', '\"') + '"'
    }
    return '[' + ($quoted -join ', ') + ']'
}

function Update-YamlScalar($Content, $Key, $Value) {
    $quoted = '"' + ($Value -replace '"', '\"') + '"'
    $pattern = '(?m)^(\s*' + [regex]::Escape($Key) + ':\s*).*$'
    return [regex]::Replace($Content, $pattern, ('$1' + $quoted))
}

function Update-YamlArray($Content, $Key, $Values) {
    $pattern = '(?m)^(\s*' + [regex]::Escape($Key) + ':\s*).*$'
    return [regex]::Replace($Content, $pattern, ('$1' + (ConvertTo-InlineYamlArray $Values)))
}

Write-Step 'Checking prerequisites'
if (-not (Test-Path $ConfigTemplatePath)) {
    throw "Missing config template: $ConfigTemplatePath"
}
if (-not (Test-Path $RequirementsPath)) {
    throw "Missing requirements file: $RequirementsPath"
}
if (-not (Test-Path $SkillSourceDir)) {
    throw "Missing bundled skill directory: $SkillSourceDir"
}

$pythonPath = Ensure-CommandAvailable 'python' { throw 'Python is required but was not found in PATH.' } 'Python is required but was not found in PATH.'
$pythonVersion = & python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
Write-Host "Python: $pythonVersion"

$nodePath = Ensure-CommandAvailable 'node' { Install-NodeJs } 'Node.js is still unavailable after attempted installation.'
$npmPath = Ensure-CommandAvailable 'npm' { Install-NodeJs } 'npm is still unavailable after attempted Node.js installation.'
$claudePath = Ensure-CommandAvailable 'claude' { Install-ClaudeCodeCli } 'Claude Code CLI is still unavailable after attempted installation.'
$uvPath = Ensure-CommandAvailable 'uv' { Install-Uv } 'uv is still unavailable after attempted installation.'
Write-Host "Node: $nodePath"
Write-Host "npm: $npmPath"
Write-Host "claude: $claudePath"
Write-Host "uv: $uvPath"

Write-Step 'Creating virtual environment if needed'
if (-not (Test-Path $VenvDir)) {
    & python -m venv $VenvDir
}

$venvPython = Join-Path $VenvDir 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment python not found: $venvPython"
}

Write-Step 'Installing Python dependencies'
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r $RequirementsPath

Write-Step 'Discovering external tools'
$toolMap = [ordered]@{
    diec = Resolve-ToolValue 'HYPERAGENT_DIEC_PATH' 'diec.exe'
    de4dot = Resolve-ToolValue 'HYPERAGENT_DE4DOT_PATH' 'de4dot.exe'
    dnspy = Resolve-ToolValue 'HYPERAGENT_DNSPYC_PATH' 'dnspyc.exe'
    pyinstxtractor = Resolve-ToolValue 'HYPERAGENT_PYINSTXTRACTOR_PATH' 'pyinstxtractor.py'
    pycdas = Resolve-ToolValue 'HYPERAGENT_PYCDAS_PATH' 'pycdas'
}
$claudeCommand = Resolve-CommandListValue 'HYPERAGENT_CLAUDE_CMD' @('claude')
$idaServerCommand = Resolve-CommandListValue 'HYPERAGENT_IDA_SERVER_COMMAND' @('uv', 'run', 'idalib-mcp')

Write-Step 'Generating local config'
if ((Test-Path $ConfigPath) -and -not $Force) {
    Write-Host 'Keeping existing config.yaml (use -Force to regenerate).' -ForegroundColor Yellow
}
else {
    $configContent = Get-Content $ConfigTemplatePath -Raw
    foreach ($toolName in $toolMap.Keys) {
        $configContent = Update-YamlScalar $configContent $toolName $toolMap[$toolName].Value
    }
    $configContent = Update-YamlArray $configContent 'ida_server_command' $idaServerCommand.Value
    $configContent = Update-YamlArray $configContent 'claude_code_command' $claudeCommand.Value
    Set-Content -Path $ConfigPath -Value $configContent -Encoding UTF8
    Write-Host "Wrote $ConfigPath"
}

Write-Step 'Installing bundled Claude skills'
Install-ClaudeSkill -SourceDir $SkillSourceDir -DestinationDir $InstalledSkillRootDir
Write-Host "Installed skills to $InstalledSkillRootDir"

Write-Step 'Installing Claude IDA plugin'
Install-ClaudePlugin -PluginSource $IdaMarketplaceCommand -PluginName $IdaMcpPluginCommand
Write-Host "Installed Claude plugin $IdaMcpPluginCommand"

Write-Step 'Activating idalib if IDA is installed'
$IdaActivationScript = Find-IdaActivationScript
if ($IdaActivationScript) {
    $IdaRootDir = Split-Path (Split-Path (Split-Path $IdaActivationScript -Parent) -Parent) -Parent
    $idalibActivated = Activate-Idalib -ActivationScript $IdaActivationScript -PythonExe $venvPython
    if ($idalibActivated) {
        Write-Host "Activated idalib using $IdaActivationScript"
    }
}
else {
    Write-Host 'No IDA installation detected; skipping idalib activation.' -ForegroundColor Yellow
}

Write-Step 'Setup summary'
foreach ($toolName in $toolMap.Keys) {
    $tool = $toolMap[$toolName]
    $status = if ($tool.Resolved) { 'ready' } else { 'not found on this machine' }
    Write-Host ("{0}: {1} ({2}, {3})" -f $toolName, $tool.Value, $tool.Source, $status)
}
Write-Host ("claude_code_command: {0} ({1})" -f (($claudeCommand.Value) -join ' '), $claudeCommand.Source)
Write-Host ("ida_server_command: {0} ({1})" -f (($idaServerCommand.Value) -join ' '), $idaServerCommand.Source)
Write-Host ("claude_skills: {0}" -f $InstalledSkillRootDir)
Write-Host ("claude_plugin: {0}" -f $IdaMcpPluginCommand)
Write-Host ("ida_root: {0}" -f $(if ($IdaRootDir) { $IdaRootDir } else { 'not detected' }))
Write-Host ("idalib_activation: {0}" -f $(if ($IdaActivationScript) { $IdaActivationScript } else { 'skipped' }))

if (-not $SkipVerify) {
    Write-Step 'Running verification'
    & $venvPython -m pip check
    & $venvPython -c "import yaml, dotenv, fastapi, uvicorn; print('python_imports_ok')"
    & $venvPython -c "import main; print('main_import_ok')"
    & $venvPython -c "import api; print('api_import_ok')"
    & $venvPython -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('config.yaml').read_text(encoding='utf-8')); print('config_yaml_ok')"
}

Write-Step 'Done'
Write-Host 'Next steps:'
Write-Host '  .\.venv\Scripts\Activate.ps1'
Write-Host '  uvicorn api:app --host 0.0.0.0 --port 8000'
Write-Host '  python main.py C:\path\to\sample.exe'
Write-Host '  /hyperagent-malware-analyze @sample.exe'
