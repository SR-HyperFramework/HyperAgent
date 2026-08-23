<#
.SYNOPSIS
    Packages HyperAgent for transfer to another machine.

.DESCRIPTION
    Builds a zip archive containing:
      - every git-tracked file (via `git archive`, so .gitignore is respected
        and no .git history / venv / reports / caches leak in)
      - resource/ tool binaries (DIE, pycdas/pycdc, pyinstxtractor) - these are
        gitignored on purpose (binary blobs) but required at runtime and are
        NOT fetched by bootstrap.ps1, so they must travel with the package.
      - your live config/secrets: skill/_hyperagent-common/scripts/.env (VT
        API key) and %USERPROFILE%\.hyperagent\config.yaml (Anthropic API
        key/base_url, VM credentials, MCP URLs) - bundled by request for a
        private research handoff between co-authors. Do NOT publish the
        resulting zip anywhere public.

    Deliberately excluded (recreate these on the target machine instead):
      - venv/                  -> rebuilt by bootstrap.ps1
      - .git/                  -> use `git clone`/`git push` if you want history
      - reports/, .planning/   -> local run state, not needed to install
      - pycdc/                 -> public repo (github.com/zrax/pycdc); the
        binaries it produces already ship prebuilt in resource/pycdas/

.PARAMETER OutputPath
    Path to the zip file to create. Defaults to
    "..\HyperAgent-transfer.zip" (sibling of the repo root).

.PARAMETER IncludeReports
    Also bundle reports/ (past analysis output). Off by default because it
    can be large and isn't needed to install the tool.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\package_for_transfer.ps1
#>
param(
    [string]$OutputPath,
    [switch]$IncludeReports
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
        throw "Run this from inside the HyperAgent git repo (no .git found at $RepoRoot)."
    }

    if ([string]::IsNullOrWhiteSpace($OutputPath)) {
        $OutputPath = Join-Path (Split-Path -Parent $RepoRoot) "HyperAgent-transfer.zip"
    }
    $OutputPath = [System.IO.Path]::GetFullPath($OutputPath)

    $StagingDir = Join-Path ([System.IO.Path]::GetTempPath()) ("hyperagent-package-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $StagingDir | Out-Null

    Write-Host "==> Exporting git-tracked source into staging dir" -ForegroundColor Cyan
    $SourceZip = Join-Path $StagingDir "_source.zip"
    git archive --format=zip -o $SourceZip HEAD
    Expand-Archive -Path $SourceZip -DestinationPath $StagingDir -Force
    Remove-Item $SourceZip

    Write-Host "==> Copying resource/ tool binaries (not tracked by git)" -ForegroundColor Cyan
    if (Test-Path (Join-Path $RepoRoot "resource")) {
        $DestResource = Join-Path $StagingDir "resource"
        # Skip IDA scratch/db files DIE leaves behind (*.id0/id1/id2/nam/til) -
        # regenerated on first run, not needed for a fresh install.
        robocopy (Join-Path $RepoRoot "resource") $DestResource /E /XF *.id0 *.id1 *.id2 *.nam *.til *.cache | Out-Null
    }
    else {
        Write-Warning "resource/ not found at $RepoRoot - skipping. Target machine will be missing DIE/pycdc/pyinstxtractor."
    }

    if ($IncludeReports -and (Test-Path (Join-Path $RepoRoot "reports"))) {
        Write-Host "==> Copying reports/ (per -IncludeReports)" -ForegroundColor Cyan
        robocopy (Join-Path $RepoRoot "reports") (Join-Path $StagingDir "reports") /E | Out-Null
    }

    Write-Host "==> Copying config/secrets (.env, ~/.hyperagent/config.yaml)" -ForegroundColor Cyan
    $HasEnvFile = $false
    $EnvSource = Join-Path $RepoRoot "skill\_hyperagent-common\scripts\.env"
    if (Test-Path $EnvSource) {
        Copy-Item $EnvSource (Join-Path $StagingDir "skill\_hyperagent-common\scripts\.env") -Force
        $HasEnvFile = $true
    }

    $HasUserConfig = $false
    $UserConfigSource = Join-Path $HOME ".hyperagent\config.yaml"
    if (Test-Path $UserConfigSource) {
        New-Item -ItemType Directory -Path (Join-Path $StagingDir "dotconfig\.hyperagent") -Force | Out-Null
        Copy-Item $UserConfigSource (Join-Path $StagingDir "dotconfig\.hyperagent\config.yaml") -Force
        $HasUserConfig = $true
    }
    else {
        Write-Warning "No config.yaml found at $UserConfigSource - skipping."
    }

    $ManifestPath = Join-Path $StagingDir "PACKAGE_MANIFEST.txt"
    @"
HyperAgent transfer package
Built: $(Get-Date -Format o)
Source commit: $(git rev-parse HEAD)
Branch: $(git rev-parse --abbrev-ref HEAD)

Included:
  - All git-tracked source files (hyperagent/, skill/, webui/, experiments/, docs, etc.)
  - resource/  (DIE, pycdas/pycdc, pyinstxtractor binaries)
$(if ($HasEnvFile) { "  - skill/_hyperagent-common/scripts/.env  (VT_API_KEY)" })
$(if ($HasUserConfig) { "  - dotconfig/.hyperagent/config.yaml  (Anthropic key/base_url, VM credentials, MCP URLs) - install to %USERPROFILE%\.hyperagent\config.yaml on the target machine" })
$(if ($IncludeReports) { "  - reports/  (past analysis output)" })

CONTAINS SECRETS - this zip is only safe to hand to a trusted co-author over
a private channel. Do not attach it to a public issue/PR or push it anywhere
public.
$(if ($HasUserConfig) { "config.yaml has machine-specific paths (H:\... VM path, skills_root under C:\Users\ADMIN\...) - update them if the target machine's drive letters/username differ." })

NOT included - see SETUP_NEW_MACHINE.md for how to handle each:
  - venv/                         (rebuild with bootstrap.ps1)
  - .git/                         (use git clone/push if you need history)
  - .claude/, .planning/, reports/ session/local state
  - IDA Pro, x64dbg, VMware Workstation (licensed installs, do manually)
  - pycdc/ source checkout (public repo, prebuilt binaries already in resource/pycdas/)
"@ | Set-Content -Path $ManifestPath -Encoding UTF8

    Write-Host "==> Compressing to $OutputPath" -ForegroundColor Cyan
    if (Test-Path $OutputPath) { Remove-Item $OutputPath -Force }
    Compress-Archive -Path (Join-Path $StagingDir "*") -DestinationPath $OutputPath -CompressionLevel Optimal

    Remove-Item $StagingDir -Recurse -Force

    $SizeMB = [math]::Round((Get-Item $OutputPath).Length / 1MB, 1)
    Write-Host "`nDone: $OutputPath ($SizeMB MB)" -ForegroundColor Green
    Write-Host "Next: copy this zip to the target machine, then follow SETUP_NEW_MACHINE.md" -ForegroundColor Green
}
finally {
    Pop-Location
}
