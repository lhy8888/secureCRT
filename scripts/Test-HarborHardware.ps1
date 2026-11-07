param(
    [ValidateSet('Inventory', 'Loopback', 'Hotplug')][string]$Mode = 'Inventory',
    [ValidatePattern('^COM[1-9][0-9]{0,4}$')][string]$Port,
    [ValidateRange(1, 604800)][int]$Seconds = 60,
    [ValidateRange(50, 4000000)][int]$BaudRate = 115200,
    [switch]$ConfirmLoopback
)
$ErrorActionPreference = 'Stop'
$exe = Join-Path $PSScriptRoot 'HarborTerminal.exe'
if (!(Test-Path $exe)) { $exe = Join-Path $PSScriptRoot '../dist/HarborTerminal/HarborTerminal.exe' }
if (!(Test-Path $exe)) { throw 'Extract the Windows bundle and keep this script next to HarborTerminal.exe.' }
if ($Mode -ne 'Inventory' -and !$Port) { throw 'Specify the physical port, for example -Port COM3.' }
if ($Mode -eq 'Loopback' -and !$ConfirmLoopback) {
    Write-Host 'Disconnect all equipment from the adapter. Connect only the adapter TX and RX for loopback.'
    Write-Host 'This test sends binary data. It must not be connected to a router, switch, controller or other device.'
    if ((Read-Host 'Type LOOPBACK after preparing the loopback cable') -cne 'LOOPBACK') { throw 'Loopback was not selected.' }
}
if ($Mode -eq 'Hotplug') { Write-Host 'Unplug and reconnect the chosen adapter during the observation period. No serial bytes are sent.' }
$output = Join-Path $PSScriptRoot ('Diagnostics/' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $Mode + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Force $output | Out-Null
$report = Join-Path $output 'serial-report.json'
$nativeArgs = @('--serial-report', ('"' + $report + '"'), '--serial-mode', $Mode.ToLowerInvariant(),
    '--seconds', "$Seconds", '--baudrate', "$BaudRate")
if ($Port) { $nativeArgs += @('--serial-port', $Port) }
if ($Mode -eq 'Loopback') { $nativeArgs += '--loopback-only' }
$process = Start-Process -FilePath $exe -ArgumentList $nativeArgs -PassThru
if (!$process.WaitForExit(($Seconds + 180) * 1000)) {
    $process.Kill()
    throw "Diagnostic process did not finish. The last heartbeat report is at $report; this is not a pass."
}
$process.Refresh()
if (Test-Path $report) { Get-Content -Raw -Encoding UTF8 $report | Write-Output }
Write-Host "Local report: $report. Nothing was uploaded."
if ($process.ExitCode -ne 0) { throw "Diagnostic did not pass (exit $($process.ExitCode))." }
