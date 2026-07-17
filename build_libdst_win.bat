@echo off
rem build_libdst_win.bat — Windows용 libdst.dll 빌드 (MinGW-w64 필요)
rem
rem 사전 요구: MinGW-w64 설치 후 PATH에 추가
rem   https://winlibs.com/ 에서 다운로드 (GCC 13+ 권장)
rem   또는: winget install --id=MSYS2.MSYS2 -e

setlocal

set SCRIPT_DIR=%~dp0
set LIBDST_DIR=%SCRIPT_DIR%libdst
set OUT=%SCRIPT_DIR%libdst.dll

echo ===================================================
echo   libdst.dll 빌드 (DST SACD ISO 디코더)
echo ===================================================
echo 소스: %LIBDST_DIR%
echo 출력: %OUT%
echo.

rem GCC 확인
where gcc >nul 2>&1
if errorlevel 1 (
    echo [오류] gcc를 찾을 수 없습니다.
    echo MinGW-w64를 설치하고 PATH에 추가해 주세요.
    echo https://winlibs.com/
    pause
    exit /b 1
)

cd /d "%LIBDST_DIR%"

set SRCS=buffer_pool.c ccp_calc.c dst_ac.c dst_data.c dst_fram.c dst_init.c unpack_dst.c yarn.c dst_wrapper.c
set FLAGS=-O2 -DNDEBUG -Wall -Wno-unused-variable -Wno-unused-function

echo 컴파일 중...
gcc %FLAGS% -shared %SRCS% -o "%OUT%"

if errorlevel 1 (
    echo [실패] 빌드 오류가 발생했습니다.
    pause
    exit /b 1
)

echo.
echo ===================================================
echo   빌드 완료: %OUT%
echo ===================================================
echo 앱을 재시작하면 DST SACD ISO 재생이 활성화됩니다.
pause
