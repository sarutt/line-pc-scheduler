@echo off
REM ===== LINE PC Scheduler - ดับเบิลคลิกเพื่อเปิดระบบ =====
cd /d "%~dp0"
echo กำลังเปิด LINE PC Scheduler ...
echo (เบราว์เซอร์จะเปิด http://localhost:5000 ให้อัตโนมัติ)
echo ปิดระบบ: กด Ctrl+C หรือปิดหน้าต่างนี้
echo.
python app.py
pause
