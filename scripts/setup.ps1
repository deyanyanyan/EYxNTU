# Run from any directory: powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
if (Test-Path (Join-Path $repoRoot '.env')) {
    Write-Host '.env already exists; keeping its credentials. Continue with scripts/compose.ps1 up --build --wait.'
    exit 0
}
docker info --format '{{.ServerVersion}}' > $null
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop with Linux containers, then retry.' }
docker run --rm --mount "type=bind,source=$repoRoot,target=/workspace" python:3.12-slim python /workspace/scripts/gen_env.py
exit $LASTEXITCODE
