# Windows equivalent of scrub-check.sh
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$words  = @("cpf","ccu","glide","soar","csa","medisave","mandis","wenjieb2","cpfsimulator","schemes-img")
$substr = @("central provident","ccutrainingsimulator","471112806622","rds.amazonaws","ap-southeast-1","cpf.gov.sg","sk-proj-","AKIA")
$candidates = git -c core.quotepath=false ls-files --cached --others --exclude-standard
if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate repository files.' }
$files = $candidates | Where-Object {
  $_ -notmatch 'scrub-check|\.(docx|pdf|png|jpg|woff2)$' -and (Test-Path -LiteralPath $_ -PathType Leaf)
}
$fail = $false
foreach ($w in $words) {
  $h = Select-String -LiteralPath $files -Pattern "\b$w\b" -CaseSensitive:$false
  if ($h) { Write-Host "DENYLIST HIT (word): $w"; $h | ForEach-Object { Write-Host "  $($_.Path):$($_.LineNumber)" }; $fail = $true }
}
foreach ($s in $substr) {
  $h = Select-String -LiteralPath $files -SimpleMatch -Pattern $s -CaseSensitive:$false
  if ($h) { Write-Host "DENYLIST HIT (substring): $s"; $h | ForEach-Object { Write-Host "  $($_.Path):$($_.LineNumber)" }; $fail = $true }
}
if (-not $fail) { Write-Host "scrub-check: clean" } else { exit 1 }
