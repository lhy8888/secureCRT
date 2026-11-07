param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Assert-NativeSuccess { if ($LASTEXITCODE -ne 0) { throw "Command failed: $LASTEXITCODE" } }
& $Python -c "import sys; assert sys.version_info[:2] == (3,14) and sys.version_info[:3] >= (3,14,10), 'Use official Windows Python 3.14.10 or newer in the 3.14 series'"
Assert-NativeSuccess
& $Python -m venv .venv-build-win
Assert-NativeSuccess
& .\.venv-build-win\Scripts\python.exe -m pip install -r requirements-lock.txt
Assert-NativeSuccess
& .\.venv-build-win\Scripts\python.exe -m pip install --no-deps .
Assert-NativeSuccess
& .\.venv-build-win\Scripts\python.exe -m pip install pyinstaller==6.19.0
Assert-NativeSuccess
& .\.venv-build-win\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --name HarborTerminal --copy-metadata harbor-terminal --collect-all pyte scripts/windows-entry.py
Assert-NativeSuccess
Copy-Item scripts/Test-HarborHardware.ps1 dist/HarborTerminal/
Copy-Item docs/windows-hardware-testing.md dist/HarborTerminal/HARDWARE-TESTING.md
& .\.venv-build-win\Scripts\python.exe scripts/collect_licenses.py --out dist/HarborTerminal/ThirdParty
Assert-NativeSuccess
$exe = (Resolve-Path dist/HarborTerminal/HarborTerminal.exe).Path
New-Item -ItemType Directory -Force artifacts/windows | Out-Null
foreach ($scale in @('1', '1.25', '1.5', '2', '3')) {
    $env:QT_QPA_PLATFORM = 'windows'
    $env:QT_SCALE_FACTOR = $scale
    $report = Join-Path (Resolve-Path artifacts/windows).Path "desktop-$scale.json"
    if (Test-Path $report) { Remove-Item $report }
    $process = Start-Process -FilePath $exe -ArgumentList @('--smoke-test-report', ('"' + $report + '"')) -PassThru
    if (!$process.WaitForExit(120000)) { $process.Kill(); throw "EXE smoke timed out at scale $scale" }
    $process.Refresh()
    if ($process.ExitCode -ne 0 -or !(Test-Path $report)) { throw "EXE smoke failed at scale $scale" }
    $result = Get-Content -Raw -Encoding UTF8 $report | ConvertFrom-Json
    if ($result.status -ne 'passed') { throw "EXE checks failed at scale $scale" }
}
Remove-Item Env:QT_SCALE_FACTOR
Compress-Archive -Path dist/HarborTerminal -DestinationPath artifacts/HarborTerminal-Windows-x64.zip -Force
Get-FileHash artifacts/HarborTerminal-Windows-x64.zip -Algorithm SHA256 | Format-List | Out-File artifacts/HarborTerminal-Windows-x64.sha256.txt
Write-Host 'Output: dist/HarborTerminal/HarborTerminal.exe (unsigned development build)'
