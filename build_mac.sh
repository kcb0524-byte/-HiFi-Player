#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  Nikon Chinge HiFi Music Player — macOS Universal 빌드 스크립트
#  결과물: dist/Nikon Chinge HiFi Player-1.0.0.dmg
#
#  사전 요구사항:
#    pip install pyinstaller scipy mutagen sounddevice numpy PyQt5
#    brew install create-dmg          (DMG 생성용, 없으면 hdiutil 사용)
#
#  실행:
#    bash build_mac.sh
#
#  배포 방법:
#    DMG 안에 포함된 "설치하기.command"를 더블클릭하면
#    자동으로 quarantine 속성 제거 후 /Applications에 설치됩니다.
#    (처음 실행 시 Terminal이 열리며 설치가 진행됩니다)
# ═══════════════════════════════════════════════════════════════
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

APP_NAME="Nikon Chinge HiFi Player"
BUNDLE_ID="com.twsemicon.hifi-player"
VERSION="1.0.0"
ICON="icon.icns"

# ── Python 환경 확인 및 통일 ─────────────────────────────────────
# 패키지(scipy, PyQt5 등)가 설치된 Python을 찾아서 사용
echo "▶ Python 환경 확인..."
if python3 -c "import scipy, PyQt5, sounddevice" 2>/dev/null; then
  PYTHON="python3"
elif python3.9 -c "import scipy, PyQt5, sounddevice" 2>/dev/null; then
  PYTHON="python3.9"
elif /usr/bin/python3 -c "import scipy, PyQt5, sounddevice" 2>/dev/null; then
  PYTHON="/usr/bin/python3"
else
  echo "  오류: scipy, PyQt5, sounddevice가 설치된 Python을 찾을 수 없습니다."
  exit 1
fi

echo "  사용할 Python: $PYTHON ($(${PYTHON} --version))"
echo "  패키지 위치: $(${PYTHON} -c 'import scipy; print(scipy.__file__)')"

# PyInstaller가 같은 Python 환경에 있는지 확인, 없으면 설치
if ! ${PYTHON} -m PyInstaller --version &>/dev/null; then
  echo "  PyInstaller 없음 — 설치 중..."
  ${PYTHON} -m pip install pyinstaller --user
fi

PYINSTALLER="${PYTHON} -m PyInstaller"
echo "  PyInstaller: $(${PYINSTALLER} --version)"
echo ""

# ── 1. 아이콘 생성 ──────────────────────────────────────────────
echo "▶ 아이콘 생성..."
if [ -f "icon.icns" ]; then
  echo "  기존 icon.icns 사용"
elif [ -d "icon.iconset" ]; then
  echo "  iconutil로 icon.icns 생성..."
  iconutil -c icns icon.iconset
else
  echo "  icon.iconset 없음 — create_icon.py 시도..."
  python3 create_icon.py || {
    echo "  아이콘 생성 실패 — 기본 아이콘으로 계속 진행"
    ICON=""
  }
fi

# ── 2. 이전 빌드 정리 ────────────────────────────────────────────
rm -rf build dist

# ── 3. PyInstaller .app 번들 생성 ───────────────────────────────
echo "▶ PyInstaller 빌드 (arm64)..."
${PYINSTALLER} \
  --name          "$APP_NAME" \
  --windowed \
  --icon          "$ICON" \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --target-arch   arm64 \
  \
  --add-data      "constants.py:." \
  --add-data      "ui_widgets.py:." \
  --add-data      "player_window.py:." \
  --add-data      "audio_engine.py:." \
  --add-data      "dsd_decoder.py:." \
  --add-data      "sacd_decoder.py:." \
  --add-data      "upnp_browser.py:." \
  $([ -f "libdst_wrapper.dylib" ] && echo "--add-binary libdst_wrapper.dylib:.") \
  \
  --hidden-import sounddevice \
  --hidden-import sounddevice._sounddevice \
  --hidden-import scipy \
  --hidden-import scipy.signal \
  --hidden-import scipy.signal._upfirdn \
  --hidden-import scipy.signal._upfirdn_apply \
  --hidden-import scipy.signal._sosfilt \
  --hidden-import scipy.signal.windows \
  --hidden-import scipy.signal.windows._windows \
  --hidden-import scipy.fft \
  --hidden-import scipy.fft._pocketfft \
  --hidden-import scipy.fft._pocketfft.helper \
  --hidden-import scipy._lib \
  --hidden-import scipy._lib.messagestream \
  --hidden-import scipy._lib._ccallback \
  --hidden-import scipy.interpolate \
  --hidden-import scipy.interpolate._interpolate \
  --collect-all   scipy \
  --collect-all   sounddevice \
  --hidden-import numpy \
  --hidden-import numpy.core \
  --hidden-import numpy.core._multiarray_umath \
  --hidden-import mutagen \
  --hidden-import mutagen.flac \
  --hidden-import mutagen.mp3 \
  --hidden-import mutagen.mp4 \
  --hidden-import mutagen.aiff \
  --hidden-import mutagen.oggvorbis \
  --hidden-import mutagen.id3 \
  --hidden-import mutagen.id3._util \
  --hidden-import PyQt5 \
  --hidden-import PyQt5.QtCore \
  --hidden-import PyQt5.QtGui \
  --hidden-import PyQt5.QtWidgets \
  --hidden-import PyQt5.sip \
  --hidden-import struct \
  --hidden-import threading \
  --hidden-import socket \
  --hidden-import urllib.request \
  --hidden-import xml.etree.ElementTree \
  \
  \
  --noconfirm \
  main.py

APP_PATH="dist/${APP_NAME}.app"

# ── 4. ffmpeg 번들 포함 (APE/WMA/TTA 재생용) ───────────────────
echo "▶ ffmpeg 번들 포함..."
FFMPEG_DST="${APP_PATH}/Contents/MacOS/ffmpeg"
FFMPEG_SRC=""
for candidate in \
  "$(which ffmpeg 2>/dev/null)" \
  "/opt/homebrew/bin/ffmpeg" \
  "/usr/local/bin/ffmpeg"; do
  if [ -f "$candidate" ]; then
    FFMPEG_SRC="$candidate"
    break
  fi
done

if [ -n "$FFMPEG_SRC" ]; then
  cp "$FFMPEG_SRC" "$FFMPEG_DST"
  chmod +x "$FFMPEG_DST"
  echo "  ✓ ffmpeg 복사 완료: $FFMPEG_SRC → $FFMPEG_DST"
else
  echo "  ⚠ ffmpeg를 찾을 수 없음 — APE 재생 불가 (brew install ffmpeg 후 재빌드 권장)"
fi

# ── 6. Info.plist 보완 ──────────────────────────────────────────
echo "▶ Info.plist 수정..."
INFO_PLIST="${APP_PATH}/Contents/Info.plist"

set_plist() {
  /usr/libexec/PlistBuddy -c "Set :$1 $2" "$INFO_PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :$1 $3 $2" "$INFO_PLIST" 2>/dev/null \
    || true
}

set_plist CFBundleShortVersionString "$VERSION" string
set_plist CFBundleVersion "$VERSION" string
set_plist NSHighResolutionCapable true bool
set_plist LSMinimumSystemVersion "12.0" string
# NSMicrophoneUsageDescription 제거 — 이 키가 있으면 macOS가 마이크 권한 팝업을 띄움
# 오디오 출력 전용(OutputStream)이므로 마이크 권한 불필요
/usr/libexec/PlistBuddy -c "Delete :NSMicrophoneUsageDescription" "$INFO_PLIST" 2>/dev/null || true
# 파일/볼륨 접근 권한 (음악 파일 및 ISO 로드)
set_plist NSDesktopFolderUsageDescription "음악 파일을 열기 위해 접근합니다" string
set_plist NSDocumentsFolderUsageDescription "음악 파일을 열기 위해 접근합니다" string
set_plist NSDownloadsFolderUsageDescription "음악 파일을 열기 위해 접근합니다" string
set_plist NSRemovableVolumesUsageDescription "외장 드라이브의 음악 파일 및 SACD ISO를 재생합니다" string

# ── 7. scipy 불필요 파일 제거 (용량 최적화) ──────────────────────
echo "▶ scipy 테스트/문서 파일 제거 (용량 최적화)..."
for SEARCH_DIR in "$APP_PATH/Contents/Frameworks" "$APP_PATH/Contents/Resources"; do
  # 테스트 디렉토리 삭제
  find "$SEARCH_DIR" -type d -name "tests" 2>/dev/null | xargs rm -rf 2>/dev/null || true
  # 소스/컴파일 파일 삭제
  find "$SEARCH_DIR" -name "*.pyx" -delete 2>/dev/null || true
  find "$SEARCH_DIR" -name "*.pxd" -delete 2>/dev/null || true
  find "$SEARCH_DIR" -name "*.f" -delete 2>/dev/null || true
  find "$SEARCH_DIR" -name "*.f90" -delete 2>/dev/null || true
  # __pycache__ 삭제
  find "$SEARCH_DIR" -type d -name "__pycache__" 2>/dev/null | xargs rm -rf 2>/dev/null || true
done
echo "  ✓ 불필요 파일 제거 완료"

# ── 8. 임시 코드사이닝 (ad-hoc) ─────────────────────────────────
# Apple 개발자 인증서가 없을 때는 ad-hoc 서명으로 Gatekeeper 우회 가능성 높임
# 인증서 있으면 아래 주석 해제하고 IDENTITY에 인증서명 입력:
# IDENTITY="Developer ID Application: 홍길동 (XXXXXXXXXX)"
# codesign --force --deep --sign "$IDENTITY" --options runtime "$APP_PATH"

echo "▶ Ad-hoc 코드사이닝 (entitlements 포함)..."
# entitlements.plist: 마이크 권한 팝업 억제 + 파일/볼륨 접근 명시
ENTITLEMENTS="$DIR/entitlements.plist"
if [ -f "$ENTITLEMENTS" ]; then
  codesign --force --deep --sign - \
    --options runtime \
    --entitlements "$ENTITLEMENTS" \
    "$APP_PATH" 2>/dev/null \
    && echo "  ✓ ad-hoc 서명 완료 (entitlements + hardened runtime)" \
    || echo "  ⚠ 서명 실패 (무시)"
else
  codesign --force --deep --sign - \
    --options runtime \
    "$APP_PATH" 2>/dev/null \
    && echo "  ✓ ad-hoc 서명 완료 (hardened runtime)" \
    || echo "  ⚠ 서명 실패 (무시)"
fi

# ── 8. Quarantine 속성 제거 ─────────────────────────────────────
# 빌드된 앱에 quarantine 플래그가 붙으면 첫 실행 시 Gatekeeper 차단됨
xattr -cr "$APP_PATH" 2>/dev/null && echo "▶ quarantine 속성 제거 완료" || true

# ── 9. 설치 스크립트 생성 및 스테이징 폴더 구성 ──────────────────
echo "▶ 설치하기.command 생성..."
STAGING="dist/dmg_staging"
rm -rf "$STAGING"
mkdir -p "$STAGING"

# 앱 복사
cp -R "$APP_PATH" "$STAGING/"

# 설치 스크립트 작성
INSTALLER="$STAGING/설치하기.command"
cat > "$INSTALLER" << 'INSTALLER_EOF'
#!/bin/bash
# ══════════════════════════════════════════════════════
#  Nikon Chinge HiFi Player — 설치 스크립트
#  이 파일을 더블클릭하면 자동으로 설치됩니다.
# ══════════════════════════════════════════════════════
APP_NAME="Nikon Chinge HiFi Player"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_SRC="$SCRIPT_DIR/${APP_NAME}.app"
APP_DST="/Applications/${APP_NAME}.app"

echo ""
echo "══════════════════════════════════════════════"
echo "  ${APP_NAME} 설치 중..."
echo "══════════════════════════════════════════════"

# quarantine 속성 제거 (Gatekeeper 차단 해제)
echo "  보안 속성 제거 중..."
xattr -cr "$APP_SRC" 2>/dev/null

# /Applications 에 복사
echo "  /Applications 에 복사 중..."
if [ -d "$APP_DST" ]; then
  echo "  기존 버전 삭제 중..."
  rm -rf "$APP_DST"
fi
cp -R "$APP_SRC" "$APP_DST"

# 복사된 앱의 quarantine 속성도 제거
xattr -cr "$APP_DST" 2>/dev/null

echo ""
echo "  ✅ 설치 완료!"
echo "  /Applications 에서 앱을 실행하세요."
echo ""

# 앱 실행
open "$APP_DST"
INSTALLER_EOF

chmod +x "$INSTALLER"
echo "  ✓ 설치하기.command 생성 완료"

# ── 10. DMG 생성 ────────────────────────────────────────────────
echo "▶ DMG 생성..."
DMG_NAME="${APP_NAME}-${VERSION}"
DMG_PATH="dist/${DMG_NAME}.dmg"

if command -v create-dmg &>/dev/null; then
  echo "  create-dmg 사용..."
  create-dmg \
    --volname         "$APP_NAME" \
    --volicon         "$ICON" \
    --window-pos      200 120 \
    --window-size     660 420 \
    --icon-size       100 \
    --icon            "${APP_NAME}.app"  160 200 \
    --icon            "설치하기.command" 490 200 \
    --hide-extension  "${APP_NAME}.app" \
    "$DMG_PATH" \
    "$STAGING" \
  || {
    echo "  create-dmg 실패 — hdiutil fallback"
    hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING" \
      -ov -format UDZO "$DMG_PATH"
  }
else
  echo "  hdiutil 사용 (create-dmg 없음)..."
  hdiutil create -volname "$APP_NAME" \
    -srcfolder "$STAGING" \
    -ov -format UDZO "$DMG_PATH"
fi

# ── 11. DMG quarantine 제거 ─────────────────────────────────────
xattr -d com.apple.quarantine "$DMG_PATH" 2>/dev/null || true

echo ""
echo "✅ 완료: $DMG_PATH"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📦 배포 방법 (다른 Mac에 설치할 때):"
echo ""
echo "  1. DMG 파일을 열면 앱과 '설치하기.command'가 보입니다."
echo "  2. '설치하기.command' 를 더블클릭합니다."
echo "  3. Terminal이 열리면서 자동으로 설치됩니다."
echo ""
echo "  ※ Gatekeeper 경고 시: 시스템 환경설정 → 개인 정보 보호 및 보안"
echo "     → '확인되지 않은 개발자' 옆 '열기 허용' 클릭"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
