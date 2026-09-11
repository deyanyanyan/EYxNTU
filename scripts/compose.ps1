param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ComposeArgs)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $repoRoot '.env'))) { throw 'Run scripts/setup.ps1 first.' }
docker compose --env-file (Join-Path $repoRoot '.env') -f (Join-Path $repoRoot 'infra/docker-compose.yml') @ComposeArgs
exit $LASTEXITCODE
