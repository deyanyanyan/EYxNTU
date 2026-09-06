# Windows equivalent of scrub-check.sh
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$words  = @("cpf","ccu","glide","soar","csa","medisave","mandis","wenjieb2","cpfsimulator","schemes-img")
$substr = @("central provident","ccutrainingsimulator","471112806622","rds.amazonaws","ap-southeast-1","cpf.gov.sg","sk-proj-","AKIA")
$files = Get-ChildItem -Recurse -File | Where-Object {
  $_.FullName -notmatch '\\(\.git|node_modules|\.next|\.venv|data)\\' -and $_.Name -notmatch 'scrub-check'
}
$fail = $false
foreach ($w in $words) {
  $h = $files | Select-String -Pattern "\b$w\b" -CaseSensitive:$false
  if ($h) { Write-Host "DENYLIST HIT (word): $w"; $h | ForEach-Object { Write-Host "  $($_.Path):$($_.LineNumber)" }; $fail = $true }
}
foreach ($s in $substr) {
  $h = $files | Select-String -SimpleMatch -Pattern $s -CaseSensitive:$false
  if ($h) { Write-Host "DENYLIST HIT (substring): $s"; $h | ForEach-Object { Write-Host "  $($_.Path):$($_.LineNumber)" }; $fail = $true }
}
if (-not $fail) { Write-Host "scrub-check: clean" } else { exit 1 }
