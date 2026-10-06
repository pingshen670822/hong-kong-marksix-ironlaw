$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$python=(Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python=(Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) {
  $bundled='C:\Users\MSI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
  if (Test-Path -LiteralPath $bundled) { $python=$bundled }
}
if (-not $python) { throw '找不到 Python 3；請先安裝 Python 3.12 與 requirements.txt 內套件' }
& $python watchdog.py
if ($LASTEXITCODE -ne 0) { throw '六合彩自主修復仍未通過，已保留最後有效版本與故障報告' }
& $python daily_integrity_audit.py
if ($LASTEXITCODE -ne 0) { throw '歷史資料完整性稽核失敗，禁止覆寫有效版本' }
& $python verify.py
if ($LASTEXITCODE -ne 0) { throw '系統關鍵檢測失敗，禁止發布' }
& $python health_check.py
if ($LASTEXITCODE -ne 0) { throw '系統健康檢測失敗，已啟動故障狀態' }
Start-Process (Join-Path $PSScriptRoot 'site\index.html')
