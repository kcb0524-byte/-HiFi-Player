@echo off
REM ═══════════════════════════════════════════════════════════════
REM  니콘 친게 HiFi Music Player — Windows 빌드 스크립트
REM  결과물: dist\HiFiPlayer_Setup_1.0.0.exe
REM
REM  사전 요구사항:
REM    pip install pyinstaller pillow
REM    Inno Setup 6 설치: https://jrsoftware.org/isinfo.php
REM
REM  실행: Windows 명령 프롬프트에서
REM    build_windows.bat
REM ═══════════════════════════════════════════════════════════════

setlocal
set APP_NAME=HiFi Player
set VERSION=1.0.0
set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

cd /d "%~dp0"

echo [1/3] 아이콘 생성...
python create_icon.py
if errorlevel 1 goto :error

echo [2/3] PyInstaller 빌드...
rmdir /s /q build 2>nul
rmdir /s /q dist  2>nul

pyinstaller ^
  --name "%APP_NAME%" ^
  --windowed ^
  --icon icon_256.png ^
  --add-data "constants.py;." ^
  --add-data "ui_widgets.py;." ^
  --add-data "player_window.py;." ^
  --add-data "audio_engine.py;." ^
  --add-data "dsd_decoder.py;." ^
  --hidden-import sounddevice ^
  --hidden-import sounddevice._sounddevice ^
  --hidden-import mutagen ^
  --hidden-import mutagen.flac ^
  --hidden-import mutagen.mp3 ^
  --hidden-import mutagen.mp4 ^
  --hidden-import mutagen.aiff ^
  --hidden-import mutagen.oggvorbis ^
  --hidden-import numpy ^
  --hidden-import numpy.core ^
  --noconfirm ^
  main.py
if errorlevel 1 goto :error

echo [3/3] Inno Setup 인스톨러 생성...
if exist %ISCC% (
    %ISCC% installer.iss
    if errorlevel 1 goto :error
    echo.
    echo ==== 완료 ====
    echo dist\HiFiPlayer_Setup_%VERSION%.exe
) else (
    echo Inno Setup 없음 — PyInstaller 폴더만 생성됨
    echo   dist\%APP_NAME%\%APP_NAME%.exe
    echo   Inno Setup 설치 후 다시 실행하거나, installer.iss 를 수동으로 컴파일하세요.
)
goto :end

:error
echo.
echo [오류] 빌드 실패. 위 메시지를 확인하세요.
exit /b 1

:end
endlocal
