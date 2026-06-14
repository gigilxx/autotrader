@echo off
REM 한국 주식 자동매매 봇 실행 스크립트
REM Task Scheduler 또는 수동 실행용

cd /d "%~dp0"

REM .env 파일 로드 (있으면)
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
    )
)

REM PYTHONUTF8 강제 (한국어 로그 깨짐 방지)
set PYTHONUTF8=1

REM 로그 디렉토리 생성
if not exist "logs" mkdir logs

REM 봇 실행
:start
echo [%date% %time%] 봇 시작 >> logs\restart.log
python -m autotrader.run
set EXIT_CODE=%ERRORLEVEL%

echo [%date% %time%] 봇 종료 (exit code: %EXIT_CODE%) >> logs\restart.log

REM exit code 0 = 정상 종료 (장 마감) → 재시작 안 함
if %EXIT_CODE%==0 (
    echo [%date% %time%] 정상 종료 - 재시작 없음 >> logs\restart.log
    goto end
)

REM 비정상 종료 → 10초 후 재시작
echo [%date% %time%] 비정상 종료 - 10초 후 재시작 >> logs\restart.log
timeout /t 10 /nobreak >nul
goto start

:end
