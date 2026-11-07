param(
    [ValidateSet('Harbor', 'SecureCRT', 'Both')][string]$Target = 'Both',
    [ValidateRange(1, 259200)][int]$Seconds = 600,
    [ValidateRange(1, 60)][int]$IntervalSeconds = 5,
    [string]$ReportRoot = (Join-Path $PSScriptRoot 'Diagnostics')
)
$ErrorActionPreference = 'Stop'
$names = switch ($Target) { 'Harbor' { @('HarborTerminal') }; 'SecureCRT' { @('SecureCRT') }; 'Both' { @('HarborTerminal', 'SecureCRT') } }
$tracked = @()
foreach ($name in $names) {
    $matches = @(Get-Process -Name $name -ErrorAction SilentlyContinue)
    if ($matches.Count -ne 1) { throw "Start exactly one $name process before measuring (found $($matches.Count))." }
    $process = $matches[0]
    $tracked += @{
        id = $process.Id
        name = $process.ProcessName
        started_utc = $process.StartTime.ToUniversalTime().ToString('o')
        file_version = $process.MainModule.FileVersionInfo.FileVersion
    }
    $process.Dispose()
}
$directory = Join-Path $ReportRoot ((Get-Date -Format 'yyyyMMdd-HHmmss') + '-comparison-' + [guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $directory | Out-Null
$encoding = New-Object System.Text.UTF8Encoding($false)
$file = [System.IO.File]::Open((Join-Path $directory 'resources.jsonl'), [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
$writer = New-Object System.IO.StreamWriter($file, $encoding)
$timer = [System.Diagnostics.Stopwatch]::StartNew()
$result = @{
    schema = 1
    status = 'running'
    scope = 'Local process resource observations during a user-operated workload; not a protocol pass or product ranking'
    started_utc = [DateTime]::UtcNow.ToString('o')
    requested_seconds = $Seconds
    logical_processors = [Environment]::ProcessorCount
    processes = $tracked
    samples = 0
    ended_processes = @()
}
try {
    do {
        foreach ($identity in $tracked) {
            $process = Get-Process -Id $identity.id -ErrorAction SilentlyContinue
            if (!$process -or $process.StartTime.ToUniversalTime().ToString('o') -ne $identity.started_utc) {
                $result.ended_processes += $identity.id
                $result.status = 'process_ended'
                break
            }
            $sample = @{
                elapsed_seconds = $timer.Elapsed.TotalSeconds
                utc = [DateTime]::UtcNow.ToString('o')
                process_id = $identity.id
                process_name = $identity.name
                working_set_bytes = $process.WorkingSet64
                private_bytes = $process.PrivateMemorySize64
                handles = $process.HandleCount
                threads = $process.Threads.Count
                cpu_total_ms = $process.TotalProcessorTime.TotalMilliseconds
            }
            $writer.WriteLine(($sample | ConvertTo-Json -Compress))
            $result.samples++
            $process.Dispose()
        }
        $writer.Flush()
        if ($result.status -eq 'process_ended') { break }
        $remaining = $Seconds - $timer.Elapsed.TotalSeconds
        if ($remaining -le 0) { $result.status = 'completed'; break }
        Start-Sleep -Milliseconds ([int]([Math]::Min($IntervalSeconds, $remaining) * 1000))
    } while ($true)
} catch {
    $result.status = 'measurement_error'
    $result.error_type = $_.Exception.GetType().Name
    throw
} finally {
    if ($result.status -eq 'running') { $result.status = 'interrupted' }
    $writer.Dispose()
    $result.elapsed_seconds = $timer.Elapsed.TotalSeconds
    $result | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $directory 'comparison.json')
    Write-Host "Local reports: $directory. Nothing was uploaded."
}
