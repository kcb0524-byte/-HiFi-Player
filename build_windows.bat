@echo off
REM ═══════════════════════════════════════════════════════════════
REM  Nikon Chinge HiFi Music Player — Windows 빌드 스크립트
REM  결과물: dist\NikonChingeHiFiPlayer_Setup_1.0.0.exe
REM
REM  사전 요구사항:
REM    pip install pyinstaller scipy numpy PyQt5 sounddevice mutagen soundfile
REM    Inno Setup 6: https://jrsoftware.org/isinfo.php  (선택)
REM
REM  실행: 이 .bat 파일이 있는 폴더에서
REM    build_windows.bat
REM ═══════════════════════════════════════════════════════════════

setlocal enabledelayedexpansion
set APP_NAME=Nikon Chinge HiFi Player
set VERSION=1.0.0
set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

cd /d "%~dp0"

echo.
echo ====================================================
echo  Nikon Chinge HiFi Player Windows 빌드
echo ====================================================
echo.

REM ── 1. Python 확인 ──────────────────────────────────
echo [1/4] Python 환경 확인...
python --version >nul 2>&1
if errorlevel 1 (
    echo   오류: Python을 찾을 수 없습니다.
    echo   https://www.python.org 에서 Python 3.9 이상을 설치하세요.
    goto :error
)
python -c "import scipy, PyQt5, sounddevice, mutagen, numpy" >nul 2>&1
if errorlevel 1 (
    echo   필수 패키지 설치 중...
    pip install scipy PyQt5 sounddevice mutagen soundfile numpy pillow
    if errorlevel 1 goto :error
)
echo   OK

REM ── 2. 아이콘 생성 ──────────────────────────────────
echo [2/4] 아이콘 생성...
if not exist icon.ico (
    python create_icon.py >nul 2>&1
)
echo   OK

REM ── 3. PyInstaller 빌드 ─────────────────────────────
echo [3/4] PyInstaller 빌드 중... (수 분 소요)
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

pyinstaller ^
  --name "%APP_NAME%" ^
  --windowed ^
  --icon icon.ico ^
  --add-data "constants.py;." ^
  --add-data "ui_widgets.py;." ^
  --add-data "player_window.py;." ^
  --add-data "audio_engine.py;." ^
  --add-data "dsd_decoder.py;." ^
  --add-data "sacd_decoder.py;." ^
  --add-data "upnp_browser.py;." ^
  --hidden-import sounddevice ^
  --hidden-import sounddevice._sounddevice ^
  --hidden-import scipy ^
  --hidden-import scipy.signal ^
  --hidden-import scipy.signal._upfirdn ^
  --hidden-import scipy.signal._upfirdn_apply ^
  --hidden-import scipy.signal._sosfilt ^
  --hidden-import scipy.signal.windows ^
  --hidden-import scipy.signal.windows._windows ^
  --hidden-import scipy.fft ^
  --hidden-import scipy.fft._pocketfft ^
  --hidden-import scipy.fft._pocketfft.helper ^
  --hidden-import scipy._lib ^
  --hidden-import scipy._lib.messagestream ^
  --hidden-import scipy._lib._ccallback ^
  --hidden-import scipy.interpolate ^
  --hidden-import scipy.interpolate._interpolate ^
  --hidden-import numpy ^
  --hidden-import numpy.core ^
  --hidden-import numpy.core._multiarray_umath ^
  --hidden-import mutagen ^
  --hidden-import mutagen.flac ^
  --hidden-import mutagen.mp3 ^
  --hidden-import mutagen.mp4 ^
  --hidden-import mutagen.aiff ^
  --hidden-import mutagen.oggvorbis ^
  --hidden-import mutagen.id3 ^
  --hidden-import mutagen.id3._util ^
  --hidden-import PyQt5 ^
  --hidden-import PyQt5.QtCore ^
  --hidden-import PyQt5.QtGui ^
  --hidden-import PyQt5.QtWidgets ^
  --hidden-import PyQt5.sip ^
  --hidden-import struct ^
  --hidden-import threading ^
  --hidden-import socket ^
  --hidden-import urllib.request ^
  --hidden-import xml.etree.ElementTree ^
  --collect-all scipy ^
  --collect-all sounddevice ^
  --noconfirm ^
  main.py
if errorlevel 1 goto :error

REM ── scipy 테스트 파일 제거 (용량 최적화) ───────────
echo   scipy 불필요 파일 제거 중...
for /d /r "dist\%APP_NAME%\_internal" %%d in (tests) do (
    if exist "%%d" rmdir /s /q "%%d" 2>nul
)
echo   OK

REM ── ffmpeg 포함 (APE/WMA 등 재생용) ────────────────
where ffmpeg >nul 2>&1
if not errorlevel 1 (
    echo   ffmpeg 포함...
    copy /y "%~dp0ffmpeg.exe" "dist\%APP_NAME%\ffmpeg.exe" >nul 2>&1
    for /f "tokens=*" %%i in ('where ffmpeg') do (
        copy /y "%%i" "dist\%APP_NAME%\ffmpeg.exe" >nul 2>&1
        goto :ffmpeg_done
    )
    :ffmpeg_done
)

REM ── 4. Inno Setup 인스톨러 생성 ─────────────────────
echo [4/4] 인스톨러 생성...
if exist %ISCC% (
    REM installer.iss 자동 생성
    (
        echo [Setup]
        echo AppName=Nikon Chinge HiFi Player
        echo AppVersion=%VERSION%
        echo AppPublisher=Nikon Chinge
        echo DefaultDirName={autopf}\Nikon Chinge HiFi Player
        echo DefaultGroupName=Nikon Chinge HiFi Player
        echo OutputDir=dist
        echo OutputBaseFilename=NikonChingeHiFiPlayer_Setup_%VERSION%
        echo SetupIconFile=icon.ico
        echo Compression=lzma2
        echo SolidCompression=yes
        echo WizardStyle=modern
        echo.
        echo [Languages]
        echo Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
        echo.
        echo [Tasks]
        echo Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업:"
        echo.
        echo [Files]
        echo Source: "dist\%APP_NAME%\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
        echo.
        echo [Icons]
        echo Name: "{group}\Nikon Chinge HiFi Player"; Filename: "{app}\%APP_NAME%.exe"
        echo Name: "{group}\제거"; Filename: "{uninstallexe}"
        echo Name: "{autodesktop}\Nikon Chinge HiFi Player"; Filename: "{app}\%APP_NAME%.exe"; Tasks: desktopicon
        echo.
        echo [Run]
        echo Filename: "{app}\%APP_NAME%.exe"; Description: "Nikon Chinge HiFi Player 실행"; Flags: nowait postinstall skipifsilent
    ) > installer_win.iss

    %ISCC% installer_win.iss
    if errorlevel 1 (
        echo   Inno Setup 오류 — PyInstaller 폴더는 사용 가능합니다.
        echo   dist\%APP_NAME%\%APP_NAME%.exe
    ) else (
        echo.
        echo ====================================================
        echo  완료!
        echo  설치 파일: dist\NikonChingeHiFiPlayer_Setup_%VERSION%.exe
        echo ====================================================
    )
) else (
    echo.
    echo ====================================================
    echo  PyInstaller 빌드 완료
    echo  실행 파일: dist\%APP_NAME%\%APP_NAME%.exe
    echo.
    echo  설치 파일(.exe)을 만들려면:
    echo  Inno Setup 6 설치 후 다시 실행하세요.
    echo  https://jrsoftware.org/isinfo.php
    echo ====================================================
)
goto :end

:error
echo.
echo [오류] 빌드 실패. 위 메시지를 확인하세요.
exit /b 1

:end
endlocal
