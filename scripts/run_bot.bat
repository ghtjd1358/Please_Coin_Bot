@echo off
REM Windows 더블클릭용 래퍼. 봇을 자동 재시작 모드로 실행.
cd /d "%~dp0\.."
.venv\Scripts\python.exe scripts\run_bot.py %*
REM 종료 시 창이 바로 닫히지 않도록 대기
pause
