param(
    [string]$TaskName = "MacroDashboard-GitHubRunner"
)

$ErrorActionPreference = "Stop"
$watchdog = Join-Path $PSScriptRoot "start_runner_watchdog.ps1"
if (-not (Test-Path -LiteralPath $watchdog)) { throw "Watchdog script not found: $watchdog" }

$userId = "$env:USERDOMAIN\$env:USERNAME"
$arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$watchdog`""
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments
$triggers = @(
    New-ScheduledTaskTrigger -AtLogOn -User $userId
    New-ScheduledTaskTrigger -Daily -At "08:20"
)
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description "Start and supervise the macro-dashboard GitHub Actions runner after logon." -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, TaskPath