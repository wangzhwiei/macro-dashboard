param(
    [int]$RestartDelaySeconds = 20
)

$ErrorActionPreference = "Stop"
$mutex = [Threading.Mutex]::new($true, "Local\MacroDashboardRunnerWatchdog", [ref]$createdNew)
if (-not $createdNew) { exit 0 }

$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$workspaceRoot = Split-Path $projectRoot -Parent
$runnerRoot = Join-Path $workspaceRoot "github-runner"
$runnerCommand = Join-Path $runnerRoot "run.cmd"
$logPath = Join-Path $workspaceRoot "runner-watchdog.log"

if (-not (Test-Path -LiteralPath $runnerCommand)) {
    throw "GitHub runner not found: $runnerCommand"
}

function Write-WatchdogLog([string]$Message) {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "$(Get-Date -Format o) $Message"
}

try {
    Write-WatchdogLog "watchdog started"
    while ($true) {
        $listener = Get-Process -Name "Runner.Listener" -ErrorAction SilentlyContinue
        if ($listener) {
            Start-Sleep -Seconds 30
            continue
        }
        Write-WatchdogLog "starting runner"
        $process = Start-Process -FilePath $env:ComSpec -ArgumentList "/d", "/c", "run.cmd" -WorkingDirectory $runnerRoot -WindowStyle Hidden -PassThru
        $process.WaitForExit()
        Write-WatchdogLog "runner exited with code $($process.ExitCode); restarting in $RestartDelaySeconds seconds"
        Start-Sleep -Seconds $RestartDelaySeconds
    }
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}