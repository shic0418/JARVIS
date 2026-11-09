@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  [J.A.R.V.I.S] 필요한 패키지를 설치합니다...
echo.
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  설치에 실패했습니다. Python 3.10 이상이 설치되어 있는지 확인하세요.
    pause
    exit /b 1
)
echo.
echo  완료! start_jarvis.bat 을 더블클릭해서 실행하세요.
pause
