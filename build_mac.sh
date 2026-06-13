#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  니콘 친게 HiFi Music Player — macOS Apple Silicon 빌드 스크립트
#  결과물: dist/니콘 친게 HiFi Player-1.0.0.dmg
#
#  사전 요구사항:
#    pip install pyinstaller scipy mutagen sounddevice numpy PyQt5
#    brew install create-dmg          (DMG 생성용, 없으면 hdiutil 사용)
#
#  실행:
#    bash build_mac.sh
# ═══════════════════════════════════════════════════════════════
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

APP_NAME="니콘 친게 HiFi Player"
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
echo "▶ PyInstaller 빌드 (Apple Silicon arm64)..."
${PYINSTALLER} \
  --name          "$APP_NAME" \
  --windowed \
  --icon          "$ICON" \
  --osx-bundle-identifier "$BUNDLE_ID" \
  \
  --add-data      "constants.py:." \
  --add-data      "ui_widgets.py:." \
  --add-data      "player_window.py:." \
  --add-data      "audio_engine.py:." \
  --add-data      "dsd_decoder.py:." \
  --add-data      "sacd_decoder.py:." \
  --add-data      "upnp_browser.py:." \
  \
  --hidden-import sounddevice \
  --hidden-import sounddevice._sounddevice \
  --hidden-import scipy \
  --hidden-import scipy.signal \
  --hidden-import scipy.signal._upfirdn \
  --hidden-import scipy.signal._upfirdn_apply \
  --hidden-import scipy.fft \
  --hidden-import scipy._lib \
  --hidden-import scipy._lib.messagestream \
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
  --collect-all   scipy \
  --collect-all   sounddevice \
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
# 마이크/오디오 권한 설명 (macOS 요구)
set_plist NSMicrophoneUsageDescription "오디오 출력에 사용됩니다" string

# ── 7. 임시 코드사이닝 (ad-hoc) ─────────────────────────────────
# Apple 개발자 인증서가 없을 때는 ad-hoc 서명으로 Gatekeeper 우회 가능성 높임
# 인증서 있으면 아래 주석 해제하고 IDENTITY에 인증서명 입력:
# IDENTITY="Developer ID Application: 홍길동 (XXXXXXXXXX)"
# codesign --force --deep --sign "$IDENTITY" --options runtime "$APP_PATH"

echo "▶ Ad-hoc 코드사이닝 (자체서명)..."
# --deep: 내부 프레임워크/dylib 전부 서명
# -f: 기존 서명 덮어쓰기
# '-': ad-hoc 서명 (인증서 불필요)
codesign --force --deep --sign - "$APP_PATH" 2>/dev/null && echo "  ✓ ad-hoc 서명 완료" || echo "  ⚠ 서명 실패 (무시)"

# ── 8. Quarantine 속성 제거 ─────────────────────────────────────
# 빌드된 앱에 quarantine 플래그가 붙으면 첫 실행 시 Gatekeeper 차단됨
xattr -cr "$APP_PATH" 2>/dev/null && echo "▶ quarantine 속성 제거 완료" || true

# ── 9. DMG 생성 ─────────────────────────────────────────────────
echo "▶ DMG 생성..."
DMG_NAME="${APP_NAME}-${VERSION}"
DMG_PATH="dist/${DMG_NAME}.dmg"

if command -v create-dmg &>/dev/null; then
  echo "  create-dmg 사용..."
  create-dmg \
    --volname         "$APP_NAME" \
    --volicon         "$ICON" \
    --window-pos      200 120 \
    --window-size     600 400 \
    --icon-size       128 \
    --icon            "${APP_NAME}.app" 150 185 \
    --hide-extension  "${APP_NAME}.app" \
    --app-drop-link   450 185 \
    "$DMG_PATH" \
    "$APP_PATH" \
  || {
    echo "  create-dmg 실패 — hdiutil fallback"
    hdiutil create -volname "$APP_NAME" -srcfolder "$APP_PATH" \
      -ov -format UDZO "$DMG_PATH"
  }
else
  echo "  hdiutil 사용 (create-dmg 없음)..."
  hdiutil create -volname "$APP_NAME" \
    -srcfolder "$APP_PATH" \
    -ov -format UDZO "$DMG_PATH"
fi

# ── 10. DMG quarantine 제거 ──────────────────────────────────────
xattr -d com.apple.quarantine "$DMG_PATH" 2>/dev/null || true

echo ""
echo "✅ 완료: $DMG_PATH"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ⚠ 상대방 Mac에서 처음 열 때 주의사항:"
echo ""
echo "  방법1 (권장): DMG 열고 앱을 우클릭 → '열기' 클릭"
echo "               '확인되지 않은 개발자' 경고창에서 '열기' 클릭"
echo ""
echo "  방법2: 터미널에서 아래 명령 실행 후 앱 실행"
echo "         xattr -cr '/Applications/니콘 친게 HiFi Player.app'"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
