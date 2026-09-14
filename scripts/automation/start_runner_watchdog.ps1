param(
    [int]$RestartDelaySeconds = 20
)

$ErrorActionPreference = "Stop"
$createdNew = $false
$mutex = [Threading.Mutex]::new($true, "Local\MacroDashboardRunnerWatchdog", [ref]$createdNew)
if (-not $createdNew) { exit 0 }

$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$workspaceRoot = Split-Path $projectRoot -Parent
$runnerRoot = Join-Path $workspaceRoot "github-runner"
$runnerCommand = Join-Path $runnerRoot "run.cmd"
$logPath = Join-Path $workspaceRoot "runner-watchdog.log"
$script:holdingSleepGuard = $false

Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public static class MacroDashboardPowerState {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint executionState);
}
"@

$executionStateContinuous = [Convert]::ToUInt32("80000000", 16)
$executionStateSystemRequired = [uint32]0x00000001

if (-not (Test-Path -LiteralPath $runnerCommand)) {
    throw "GitHub runner not found: $runnerCommand"
}

function Write-WatchdogLog([string]$Message) {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "$(Get-Date -Format o) $Message"
}

function Update-SleepGuard {
    $worker = Get-Process -Name "Runner.Worker" -ErrorAction SilentlyContinue
    if ($worker -and -not $script:holdingSleepGuard) {
        $state = $executionStateContinuous -bor $executionStateSystemRequired
        if ([MacroDashboardPowerState]::SetThreadExecutionState($state) -eq 0) {
            Write-WatchdogLog "WARNING: failed to hold the system awake for an active job"
        } else {
            $script:holdingSleepGuard = $true
            Write-WatchdogLog "active job detected; system sleep guard enabled"
        }
    } elseif (-not $worker -and $script:holdingSleepGuard) {
        [void][MacroDashboardPowerState]::SetThreadExecutionState($executionStateContinuous)
        $script:holdingSleepGuard = $false
        Write-WatchdogLog "job completed; system sleep guard released"
    }
}

try {
    Write-WatchdogLog "watchdog started"
    while ($true) {
        Update-SleepGuard
        $listener = Get-Process -Name "Runner.Listener" -ErrorAction SilentlyContinue
        if ($listener) {
            Start-Sleep -Seconds 15
            continue
        }
        Write-WatchdogLog "starting runner"
        Start-Process -FilePath $env:ComSpec -ArgumentList "/d", "/c", "run.cmd" -WorkingDirectory $runnerRoot -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds $RestartDelaySeconds
    }
} finally {
    if ($script:holdingSleepGuard) {
        [void][MacroDashboardPowerState]::SetThreadExecutionState($executionStateContinuous)
    }
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
