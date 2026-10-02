<#
.SYNOPSIS
    Prepares the llm-compare sample subset ("Set 3") for handoff to a
    collaborator, then prints the git commands to push it.

.DESCRIPTION
    "Set 3" is the 10-sample subset (5 malware + 5 benign, flagged
    `in_llm_ablation_subset` in experiments/results/sample_selection.json)
    that `python -m experiments.run_study llm-compare` already runs against.
    The collaborator is expected to already have HyperAgent installed
    (see SETUP_NEW_MACHINE.md) -- this script does NOT package the tool,
    the VM, or any sample binaries. It only:

      1. Runs experiments/export_llm_compare_manifest.py to write a small
         reference manifest (hashes/paths/labels only, no binaries) to
         experiments/results/llm_compare_set3_manifest.json, so the
         collaborator can see exactly which 10 samples are theirs.
      2. Prints the exact `git add` / `git commit` / `git push` commands to
         run -- it does NOT run them for you. Review the diff before you
         push.

    Sample binaries are deliberately never touched by this script -- do not
    add them to git. The collaborator needs their own local copy of the 10
    sample files (see the printed hash list) at a path they can point
    HYPERAGENT config / sample_selection.json at.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\handoff_llm_compare_set3.ps1
#>
param(
    [string]$Manifest = "experiments/results/sample_selection.json",
    [string]$Out = "experiments/results/llm_compare_set3_manifest.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
        throw "Run this from inside the HyperAgent git repo (no .git found at $RepoRoot)."
    }

    Write-Host "==> Exporting Set 3 (llm-compare subset) reference manifest" -ForegroundColor Cyan
    python -m experiments.export_llm_compare_manifest --manifest $Manifest --out $Out
    if ($LASTEXITCODE -ne 0) {
        throw "export_llm_compare_manifest.py failed (exit $LASTEXITCODE)"
    }

    $Branch = git rev-parse --abbrev-ref HEAD

    Write-Host "`n==> Uncommitted changes on this branch ($Branch):" -ForegroundColor Cyan
    git status --short

    $ReliabilityFixes = @(
        "hyperagent/engine/agent_loop.py",
        "hyperagent/engine/launcher.py",
        "hyperagent/tools/vmware_tools.py"
    )
    $DirtyReliabilityFixes = $ReliabilityFixes | Where-Object {
        (git status --short -- $_) -ne ""
    }
    if ($DirtyReliabilityFixes.Count -gt 0) {
        Write-Host "`nNOTE: uncommitted fixes in this session (VM-recovery wait, " -ForegroundColor Yellow
        Write-Host "max-turns checkpointing, force-finalize) are NOT included below." -ForegroundColor Yellow
        Write-Host "They matter for llm-compare too (same 03-unpack/05-dynamic path)." -ForegroundColor Yellow
        Write-Host "Add them explicitly if you want Mariu's run to have them:" -ForegroundColor Yellow
        foreach ($f in $DirtyReliabilityFixes) { Write-Host "  git add $f" -ForegroundColor Yellow }
    }

    Write-Host "`n==> Next steps (run these yourself after reviewing the diff):" -ForegroundColor Green
    Write-Host "  git add $Out"
    Write-Host "  git commit -m `"data: export llm-compare Set 3 reference manifest`""
    Write-Host "  git push origin $Branch"

    Write-Host "`n==> Tell Mariu:" -ForegroundColor Green
    Write-Host "  1. git pull (branch: $Branch)"
    Write-Host "  2. Get his own copy of the 10 sample files listed above/in $Out"
    Write-Host "     (paths in the manifest are local to this machine, not portable)"
    Write-Host "  3. Confirm his ~/.hyperagent/config.yaml resolves the model aliases"
    Write-Host "     in LLM_CONDITIONS (kietlac/claude-opus-5, kietlac/gpt-5.6-sol)"
    Write-Host "  4. python -m experiments.run_study llm-compare --dry-run"
    Write-Host "  5. python -m experiments.run_study llm-compare"
}
finally {
    Pop-Location
}
