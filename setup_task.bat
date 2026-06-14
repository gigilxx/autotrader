@echo off
REM Task Scheduler에 자동매매 봇 등록
REM 관리자 권한 없이도 현재 사용자로 등록 가능

echo === 자동매매 봇 Task Scheduler 등록 ===

REM 기존 태스크 삭제 (있으면)
schtasks /delete /tn "AutoTrader" /f >nul 2>&1

REM XML로 새 태스크 등록
schtasks /create /tn "AutoTrader" /xml "%~dp0autotrader_task.xml" /f

if %ERRORLEVEL%==0 (
    echo.
    echo [OK] Task Scheduler 등록 완료: "AutoTrader"
    echo      평일 08:50 자동 시작 / 장 마감 후 자동 종료
    echo.
    echo 확인: schtasks /query /tn "AutoTrader" /fo LIST
    echo 삭제: schtasks /delete /tn "AutoTrader" /f
) else (
    echo [ERROR] 등록 실패. autotrader_task.xml의 WorkingDirectory 경로를 확인하세요.
)
pause
