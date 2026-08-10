param(
    [switch]$Force,
    [string]$Owner = "wangzhwiei",
    [string]$Repository = "macro-dashboard",
    [string]$Workflow = "update-and-deploy.yml",
    [string]$Ref = "gh-pages"
)

$ErrorActionPreference = "Stop"
$createdNew = $false
$mutex = [Threading.Mutex]::new($true, "Local\MacroDashboardDailyUpdateDispatch", [ref]$createdNew)
if (-not $createdNew) { exit 0 }

$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$workspaceRoot = Split-Path $projectRoot -Parent
$logDirectory = Join-Path $workspaceRoot "automation-logs"
$logPath = Join-Path $logDirectory "daily-update-dispatch.log"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

function Write-DispatchLog([string]$Message) {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "$(Get-Date -Format o) $Message"
}

try {
    $now = Get-Date
    if (-not $Force -and $now.TimeOfDay -lt [TimeSpan]::FromHours(9.5)) {
        Write-DispatchLog "skip before 09:30 local time"
        exit 0
    }

    $apiHeaders = @{
        Accept = "application/vnd.github+json"
        "User-Agent" = "MacroDashboard-DailyUpdate"
        "X-GitHub-Api-Version" = "2022-11-28"
    }
    $runsUrl = "https://api.github.com/repos/$Owner/$Repository/actions/workflows/$Workflow/runs?per_page=30"
    $runs = Invoke-RestMethod -Headers $apiHeaders -Uri $runsUrl
    $todayStart = [DateTimeOffset]::new($now.Date).ToUniversalTime()
    $todayRuns = @($runs.workflow_runs | Where-Object {
        [DateTimeOffset]::Parse($_.created_at) -ge $todayStart
    })
    $alreadyHandled = @($todayRuns | Where-Object {
        $_.status -in @("queued", "in_progress", "waiting", "requested", "pending") -or
        ($_.status -eq "completed" -and $_.conclusion -eq "success")
    })
    if ($alreadyHandled.Count -gt 0) {
        $latest = $alreadyHandled | Sort-Object created_at -Descending | Select-Object -First 1
        Write-DispatchLog "skip because run $($latest.id) is $($latest.status)/$($latest.conclusion)"
        exit 0
    }

    $git = Get-Command git -ErrorAction Stop
    $credentialQuery = "protocol=https`nhost=github.com`n`n"
    $credentialLines = @($credentialQuery | & $git.Source credential fill)
    $passwordLine = $credentialLines | Where-Object { $_ -like "password=*" } | Select-Object -First 1
    if (-not $passwordLine) {
        throw "GitHub credential is unavailable from Git Credential Manager."
    }
    $token = $passwordLine.Substring("password=".Length)
    try {
        $dispatchHeaders = $apiHeaders.Clone()
        $dispatchHeaders.Authorization = "Bearer $token"
        $dispatchUrl = "https://api.github.com/repos/$Owner/$Repository/actions/workflows/$Workflow/dispatches"
        $body = @{ ref = $Ref } | ConvertTo-Json -Compress
        Invoke-RestMethod -Method Post -Headers $dispatchHeaders -ContentType "application/json" -Body $body -Uri $dispatchUrl | Out-Null
        Write-DispatchLog "workflow dispatch accepted for ref $Ref"
    } finally {
        $token = $null
        $credentialLines = $null
    }
} catch {
    Write-DispatchLog "ERROR: $($_.Exception.Message)"
    throw
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
