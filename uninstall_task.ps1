# ============================================================
# uninstall_task.ps1 — ถอนการติดตั้ง scheduled task
#   powershell -ExecutionPolicy Bypass -File .\uninstall_task.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$TaskName = "LINE PC Scheduler"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "ไม่พบ task '$TaskName' (อาจถูกลบไปแล้ว)" -ForegroundColor Yellow
    return
}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "ลบ task '$TaskName' เรียบร้อย" -ForegroundColor Green
