param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Assert-NativeSuccess { if ($LASTEXITCODE -ne 0) { throw "Command failed: $LASTEXITCODE" } }
foreach ($script in @('scripts/Test-HarborHardware.ps1', 'scripts/Measure-HarborComparison.ps1')) {
    $tokens = $null; $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $script), [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count) { throw "PowerShell parse errors in $script" }
}
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
Copy-Item scripts/Measure-HarborComparison.ps1 dist/HarborTerminal/
Copy-Item docs/windows-hardware-testing.md dist/HarborTerminal/HARDWARE-TESTING.md
Copy-Item docs/windows-comparison.md dist/HarborTerminal/COMPARISON.md
Copy-Item docs/session-management.md dist/HarborTerminal/SESSION-MANAGEMENT.md
$sourceCommit = $null; $sourceDirty = $null
if ((Test-Path .git) -and (Get-Command git -ErrorAction SilentlyContinue)) {
    $sourceCommit = (& git rev-parse HEAD).Trim()
    Assert-NativeSuccess
    $sourceDirty = [bool](& git status --porcelain --untracked-files=no)
}
@{
    source_commit = $sourceCommit
    source_dirty = $sourceDirty
    built_utc = [DateTime]::UtcNow.ToString('o')
    python = (& .\.venv-build-win\Scripts\python.exe -c "import platform; print(platform.python_version())").Trim()
    signing = 'unsigned development build'
} | ConvertTo-Json | Set-Content -Encoding UTF8 dist/HarborTerminal/BUILD-INFO.json
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
$inventory = Join-Path (Resolve-Path artifacts/windows).Path 'serial-inventory.json'
if (Test-Path $inventory) { Remove-Item $inventory }
$process = Start-Process -FilePath $exe -ArgumentList @('--serial-report', ('"' + $inventory + '"'), '--serial-mode', 'inventory') -PassThru
if (!$process.WaitForExit(30000)) { $process.Kill(); throw 'Bundled serial inventory timed out' }
$process.Refresh()
if ($process.ExitCode -ne 0 -or !(Test-Path $inventory)) { throw 'Bundled serial inventory failed' }
$inventoryResult = Get-Content -Raw -Encoding UTF8 $inventory | ConvertFrom-Json
if ($inventoryResult.status -ne 'passed' -or $inventoryResult.mode -ne 'inventory') { throw 'Invalid serial inventory result' }
# Exercise normal GUI startup and the resource sampler against our own EXE.
# This uses no COM device and is not a SecureCRT comparison.
$desktop = Start-Process -FilePath $exe -PassThru
try {
    Start-Sleep -Seconds 2
    & ./scripts/Measure-HarborComparison.ps1 -Target Harbor -Seconds 1 -IntervalSeconds 1 -ReportRoot artifacts/windows/sampler-fixture
    $samplerReport = Get-ChildItem artifacts/windows/sampler-fixture -Recurse -Filter comparison.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $sampler = Get-Content -Raw -Encoding UTF8 $samplerReport.FullName | ConvertFrom-Json
    if ($sampler.status -ne 'completed' -or $sampler.samples -lt 1) { throw 'Resource sampler fixture failed' }
} finally {
    if (!$desktop.HasExited) {
        $desktop.CloseMainWindow() | Out-Null
        if (!$desktop.WaitForExit(10000)) { $desktop.Kill() }
    }
}
Compress-Archive -Path dist/HarborTerminal -DestinationPath artifacts/HarborTerminal-Windows-x64.zip -Force
Get-FileHash artifacts/HarborTerminal-Windows-x64.zip -Algorithm SHA256 | Format-List | Out-File artifacts/HarborTerminal-Windows-x64.sha256.txt
Write-Host 'Output: dist/HarborTerminal/HarborTerminal.exe (unsigned development build)'
