@echo off
REM HiFi Player 설치 스크립트 (Windows)
REM 더블클릭 또는 명령 프롬프트에서 실행

echo ════════════════════════════════════════
echo   HiFi Player 설치 시작 (Windows)
echo ════════════════════════════════════════
echo.

REM Python 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo X Python이 설치되지 않았습니다.
    echo   python.org에서 Python 3.10+ 설치 후 다시 시도하세요.
    echo   설치 시 "Add Python to PATH" 체크 필수!
    pause
    exit /b 1
)

echo [OK] Python 확인됨
python --version

echo.
echo [진행] pip 업그레이드 중...
python -m pip install --upgrade pip --quiet

echo.
echo [진행] 패키지 설치 중...
python -m pip install -r requirements.txt

echo.
echo ════════════════════════════════════════
echo   [완료] 설치가 완료되었습니다!
echo   실행: python main.py
echo   또는: run.bat 더블클릭
echo ════════════════════════════════════════
pause
