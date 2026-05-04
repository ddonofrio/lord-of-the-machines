param(
    [switch]$BootstrapOnly,
    [int]$MaxCycles = 20,
    [int]$MaxEventsPerCycle = 10,
    [int]$IdleCyclesToStop = 2,
    [int]$MaxFollowUpRounds = 6
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

if (-not $BootstrapOnly) {
    if (-not $env:OPENAI_API_KEY -or [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
        Write-Error "OPENAI_API_KEY is not set. Export it before running this script."
        exit 2
    }
}

$env:PYTHONPATH = "src"

Write-Host "Repository: $RepoRoot"
Write-Host "PYTHONPATH=src"

Write-Host "Bootstrapping missions from config/missions.json..."
& python -m lord_of_the_machines.mission --bootstrap-only --reset-state --json
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($BootstrapOnly) {
    Write-Host "Bootstrap-only mode completed."
    exit 0
}

Write-Host "Running mission loop..."
& python -m lord_of_the_machines.mission `
    --json `
    --max-cycles $MaxCycles `
    --max-events-per-cycle $MaxEventsPerCycle `
    --idle-cycles-to-stop $IdleCyclesToStop `
    --max-follow-up-rounds $MaxFollowUpRounds `
    --require-all-completed

exit $LASTEXITCODE
