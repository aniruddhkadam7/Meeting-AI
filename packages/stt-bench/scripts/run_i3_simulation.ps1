# Simulates i3-class hardware by constraining the STT thread-sweep child
# process to a limited CPU affinity mask, in addition to sweeping
# STT_NUM_THREADS — this is a genuinely different (and stronger) simulation
# than just capping ONNX Runtime's thread pool, since it also constrains OS
# scheduling the way a real fewer-core machine would.
#
# THIS IS A SIMULATION on a 10-core/16-thread i5-13400, not a measurement on
# real i3 hardware — every number this script produces must be reported as
# "simulated (affinity-constrained i5)", never as "measured on i3".
#
# Usage:
#   powershell -File scripts/run_i3_simulation.ps1 -AffinityMask 0xF -Threads 1,2,4
#
# AffinityMask 0xF  = 4 logical processors (cores 0-3)  -> simulates a 4c/4t i3
# AffinityMask 0x3  = 2 logical processors (cores 0-1)  -> simulates a 2c/4t i3 (worst case)

param(
    [string]$AffinityMask = "0xF",
    [int[]]$Threads = @(1, 2, 4),
    [string]$Corpus = "corpus/synthetic",
    [string]$OutDir = "results"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$python = Join-Path $root ".venv\Scripts\python.exe"
$sweepScript = Join-Path $scriptDir "run_thread_sweep.py"
$affinity = [IntPtr]([Convert]::ToInt64($AffinityMask, 16))

Write-Output "=== i3 SIMULATION (affinity-constrained i5-13400, NOT real i3 hardware) ==="
Write-Output "Affinity mask : $AffinityMask ($([Convert]::ToInt64($AffinityMask,16)) -> logical processors constrained)"
Write-Output "Threads swept : $($Threads -join ', ')"
Write-Output ""

$results = @()

foreach ($t in $Threads) {
    $outFile = Join-Path $root "$OutDir\i3_sim_threads_$t.json"
    Write-Output "--> STT_NUM_THREADS=$t under affinity $AffinityMask"

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $python
    $psi.Arguments = "`"$sweepScript`" --threads $t --corpus `"$Corpus`" --in-process --out `"$outFile`""
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.WorkingDirectory = $root

    $proc = [System.Diagnostics.Process]::Start($psi)
    Start-Sleep -Milliseconds 150
    try {
        $proc.ProcessorAffinity = $affinity
    } catch {
        Write-Output "    WARNING: could not set affinity (process may have exited early): $($_.Exception.Message)"
    }
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()

    if (Test-Path $outFile) {
        $json = Get-Content $outFile -Raw | ConvertFrom-Json
        $r = $json.result
        Write-Output "    load=$($r.load_time_s)s  1st_partial=$($r.median_first_partial_ms)ms  finalize=$($r.median_finalization_ms)ms  wer=$([math]::Round($r.overall_wer*100,1))%  cpu_of_machine=$($r.resources.cpu_percent_mean_of_machine)%  rss_delta=$($r.resources.rss_mb_delta)MB"
        $results += $r
    } else {
        Write-Output "    FAILED — no output file. stderr tail:"
        Write-Output ($stderr -split "`n" | Select-Object -Last 8)
    }
    Write-Output ""
}

Write-Output "=== SUMMARY (simulated i3, affinity mask $AffinityMask) ==="
Write-Output "threads | load_s | 1st_ptl_ms | final_ms | wer_pct | cpu_mach_pct | rss_mb"
foreach ($r in $results) {
    $werPct = [math]::Round($r.overall_wer * 100, 1)
    $line = "$($r.num_threads) | $($r.load_time_s) | $($r.median_first_partial_ms) | $($r.median_finalization_ms) | $werPct | $($r.resources.cpu_percent_mean_of_machine) | $($r.resources.rss_mb_delta)"
    Write-Output $line
}
