$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$python=(Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python=(Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) {
  $bundled='C:\Users\MSI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
  if (Test-Path -LiteralPath $bundled) { $python=$bundled }
}
if (-not $python) { throw '找不到 Python 3；請先安裝 Python 3.12 與 requirements.txt 內套件' }
& $python update.py
if ($LASTEXITCODE -ne 0) { throw '六合彩資料更新或分析失敗' }
& $python verify.py
if ($LASTEXITCODE -ne 0) { throw '完整檢測失敗，禁止發布' }
Start-Process (Join-Path $PSScriptRoot 'site\index.html')
