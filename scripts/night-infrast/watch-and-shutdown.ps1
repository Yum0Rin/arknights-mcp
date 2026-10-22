# 一次性看护：等凌晨基建换班进程结束后关机（用户 2026-10-18 要求）
# 用法：pwsh -NoProfile -File watch-and-shutdown.ps1 [-TargetPid 1234] [-DelaySeconds 60]
param(
    [int]$TargetPid = 0,
    [int]$DelaySeconds = 60,
    [string]$Reason = "方舟凌晨任务已结束，按计划关机"
)

$ErrorActionPreference = "Continue"
$LogFile = Join-Path $PSScriptRoot "watch-and-shutdown.log"
$StateFile = Join-Path $PSScriptRoot "watch-and-shutdown.state.json"

function Log([string]$msg) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

if ($TargetPid -le 0) {
    $proc = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -match "night_infrast\.py" } | Select-Object -First 1
    if (-not $proc) {
        Log "未找到 night_infrast.py 进程，不关机退出。"
        exit 1
    }
    $TargetPid = [int]$proc.ProcessId
}

Log "看护开始：pid=$TargetPid，每 10s 检查一次"

$started = Get-Date
$deadline = $started.AddHours(2)
$exited = $false
while ((Get-Date) -lt $deadline) {
    $p = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    if (-not $p) { $exited = $true; break }
    Start-Sleep -Seconds 10
}

if (-not $exited) {
    Log "等待超时（2h）进程仍在跑 → 不关机，退出。"
    exit 2
}

$elapsed = [int]((Get-Date) - $started).TotalSeconds
Log "任务进程已退出（看护等待 ${elapsed}s）→ ${DelaySeconds}s 后关机"

$state = [ordered]@{
    targetPid    = $TargetPid
    detectedExit = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    delaySeconds = $DelaySeconds
    action       = "shutdown"
}
$state | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8

& shutdown.exe /s /t $DelaySeconds /c $Reason
Log "已发出关机指令（shutdown /s /t $DelaySeconds），可用 shutdown /a 取消。"
