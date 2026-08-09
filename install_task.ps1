# ============================================================
# install_task.ps1
# ลงทะเบียน Windows Task Scheduler ให้รัน scheduler.py อัตโนมัติทุกครั้งที่ล็อกอิน
#
# วิธีรัน (คลิกขวาที่ไฟล์ -> Run with PowerShell ไม่ได้ ให้ใช้คำสั่งนี้):
#   powershell -ExecutionPolicy Bypass -File .\install_task.ps1
#
# ถ้าเจอ Access Denied ให้เปิด PowerShell แบบ "Run as administrator" แล้วรันใหม่
# ============================================================

$ErrorActionPreference = "Stop"

$TaskName   = "LINE PC Scheduler"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $ProjectDir "scheduler.py"

if (-not (Test-Path $ScriptPath)) {
    throw "ไม่พบ scheduler.py ที่ $ScriptPath"
}

# --- หา Python (ใช้ pythonw.exe เพื่อไม่ให้มีหน้าต่าง console เด้ง) ---
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if (-not $python) { throw "ไม่พบ Python ใน PATH — ติดตั้ง Python และติ๊ก 'Add to PATH'" }
    $candidate = Join-Path (Split-Path $python) "pythonw.exe"
    $pythonw = if (Test-Path $candidate) { $candidate } else { $python }
}
Write-Host "ใช้ Python: $pythonw"
Write-Host "โฟลเดอร์งาน: $ProjectDir"

# --- ลบ task เดิมถ้ามี ---
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "พบ task เดิม กำลังลบเพื่อสร้างใหม่ ..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# --- นิยาม task ---
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$ScriptPath`"" -WorkingDirectory $ProjectDir

# หน่วง 1 นาทีหลังล็อกอิน เผื่อให้ระบบ/LINE พร้อม
$trigger = New-ScheduledTaskTrigger -AtLogOn
$trigger.Delay = "PT1M"

# ต้องรันตอนผู้ใช้ล็อกอิน (Interactive) เพราะ automation ต้องมีหน้าจอ
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Write-Host ""
Write-Host "ลงทะเบียนสำเร็จ: '$TaskName'" -ForegroundColor Green
Write-Host "  - จะรันอัตโนมัติทุกครั้งที่คุณล็อกอิน (หน่วง 1 นาที)"
Write-Host ""
Write-Host "ทดสอบรันเดี๋ยวนี้เลย:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "ดูสถานะ:              Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "ถอนการติดตั้ง:         .\uninstall_task.ps1"
Write-Host ""
Write-Host "อย่าลืม calibrate พิกัด + ปักหมุดกลุ่มก่อนใช้จริง (ดู README.md)" -ForegroundColor Yellow
