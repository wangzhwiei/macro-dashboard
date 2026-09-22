param(
    [switch]$DryRun,
    [string]$Repository = $env:GITHUB_REPOSITORY
)

$ErrorActionPreference = "Stop"
if (-not $Repository) { throw "GITHUB_REPOSITORY is required." }
if (-not $env:GH_TOKEN) { throw "GH_TOKEN is required to persist generated data." }

$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$api = "https://api.github.com/repos/$Repository"
$headers = @{
    Authorization = "Bearer $env:GH_TOKEN"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent" = "MacroDashboard-DailyUpdate"
}

function Get-GitBlobSha([byte[]]$bytes) {
    $prefix = [Text.Encoding]::ASCII.GetBytes("blob $($bytes.Length)`0")
    $buffer = [byte[]]::new($prefix.Length + $bytes.Length)
    [Buffer]::BlockCopy($prefix, 0, $buffer, 0, $prefix.Length)
    [Buffer]::BlockCopy($bytes, 0, $buffer, $prefix.Length, $bytes.Length)
    $sha1 = [Security.Cryptography.SHA1]::Create()
    try {
        return -join ($sha1.ComputeHash($buffer) | ForEach-Object { $_.ToString("x2") })
    } finally {
        $sha1.Dispose()
    }
}

for ($attempt = 1; $attempt -le 3; $attempt++) {
    $branch = Invoke-RestMethod -Headers $headers -Uri "$api/git/ref/heads/main" -TimeoutSec 60
    $headSha = $branch.object.sha
    $base = Invoke-RestMethod -Headers $headers -Uri "$api/git/commits/$headSha" -TimeoutSec 60
    $snapshot = Invoke-RestMethod -Headers $headers -Uri "$api/git/trees/$($base.tree.sha)?recursive=1" -TimeoutSec 60
    if ($snapshot.truncated) { throw "GitHub source tree was truncated; refusing an incomplete persistence check." }

    $changed = @()
    foreach ($item in $snapshot.tree) {
        $path = [string]$item.path
        if ($item.type -ne "blob" -or -not (
            $path.StartsWith("data/") -or $path.StartsWith("outputs/") -or
            $path -eq "public/data/dashboard.json" -or $path -eq "public/data/forecasts.json"
        )) { continue }
        $local = Join-Path $root ($path.Replace("/", "\"))
        if (-not (Test-Path -LiteralPath $local -PathType Leaf)) { continue }
        # All tracked generated artifacts are UTF-8 text. Git stores LF even
        # when Windows checks them out with CRLF, so compare/upload that form.
        $text = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($local))
        $bytes = [Text.Encoding]::UTF8.GetBytes($text.Replace("`r`n", "`n"))
        if ((Get-GitBlobSha $bytes) -ne $item.sha) {
            $changed += [pscustomobject]@{ path = $path; bytes = $bytes }
        }
    }
    Write-Host "Tracked generated files changed: $($changed.Count)"
    if ($DryRun) {
        $changed | ForEach-Object { Write-Host "Would persist $($_.path)" }
        exit 0
    }
    if (-not $changed.Count) { exit 0 }

    $entries = @()
    foreach ($file in $changed) {
        $blobBody = @{ content = [Convert]::ToBase64String($file.bytes); encoding = "base64" } | ConvertTo-Json -Compress
        $blob = Invoke-RestMethod -Method Post -Headers $headers -Uri "$api/git/blobs" -Body $blobBody -ContentType "application/json" -TimeoutSec 120
        $entries += @{ path = $file.path; mode = "100644"; type = "blob"; sha = $blob.sha }
        Write-Host "Uploaded $($file.path)"
    }
    $treeBody = @{ base_tree = $base.tree.sha; tree = $entries } | ConvertTo-Json -Depth 6 -Compress
    $tree = Invoke-RestMethod -Method Post -Headers $headers -Uri "$api/git/trees" -Body $treeBody -ContentType "application/json" -TimeoutSec 120
    $commitBody = @{ message = "data: automated daily refresh"; tree = $tree.sha; parents = @($headSha) } | ConvertTo-Json -Depth 5 -Compress
    $commit = Invoke-RestMethod -Method Post -Headers $headers -Uri "$api/git/commits" -Body $commitBody -ContentType "application/json" -TimeoutSec 120

    try {
        $refBody = @{ sha = $commit.sha; force = $false } | ConvertTo-Json -Compress
        Invoke-RestMethod -Method Patch -Headers $headers -Uri "$api/git/refs/heads/main" -Body $refBody -ContentType "application/json" -TimeoutSec 60 | Out-Null
        Write-Host "Persisted generated data to main: $($commit.sha)"
        exit 0
    } catch {
        if ($attempt -eq 3) { throw }
        Write-Warning "main moved while persisting; retrying with the new base tree."
    }
}
