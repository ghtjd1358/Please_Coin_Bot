@echo off
REM 스모크 테스트용. 1 tick만 실행 후 종료.
cd /d "%~dp0\.."
.venv\Scripts\python.exe scripts\run_bot.py --once
pause
