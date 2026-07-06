#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  Nikon Chinge HiFi Music Player — macOS Intel x86_64 빌드 스크립트
#  결과물: dist/Nikon Chinge HiFi Player-1.0.0-IntelMac.dmg
#
#  대상: iMac 2015 Late 등 Intel Mac (x86_64)
#
#  Apple Silicon Mac에서도 실행 가능 (x86_64 크로스 컴파일)
#  단, Intel Mac에서 직접 실행하면 가장 호환성이 좋습니다.
#
#  사전 요구사항:
#    pip install pyinstaller scipy mutagen sounddevice numpy PyQt5
#    brew install create-dmg          (DMG 생성용, 없으면 hdiutil 사용)
#
#  실행:
#    bash build_mac_intel.sh
# ═══════════════════════════════════════════════════════════════
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

APP_NAME="Nikon Chinge HiFi Player"
BUNDLE_ID="com.twsemicon.hifi-player"
VERSION="1.0.0"
ICON="icon.icns"
ARCH="x86_64"

# ── Python 환경 확인 및 통일 ─────────────────────────────────────
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
echo "  아키텍처 타겟: ${ARCH}"

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
chmod -R u+w build dist 2>/dev/null || true
rm -rf build dist 2>/dev/null || true

# ── 3. PyInstaller .app 번들 생성 ───────────────────────────────
echo "▶ PyInstaller 빌드 (Intel x86_64)..."
${PYINSTALLER} \
  --name          "$APP_NAME" \
  --windowed \
  --icon          "$ICON" \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --target-arch   "$ARCH" \
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

# Intel Mac용 ffmpeg 경로 — /usr/local/bin이 Homebrew Intel 경로
for candidate in \
  "$(which ffmpeg 2>/dev/null)" \
  "/usr/local/bin/ffmpeg" \
  "/opt/homebrew/bin/ffmpeg"; do
  if [ -f "$candidate" ]; then
    # Apple Silicon에서 x86_64 크로스 빌드 시 ffmpeg도 x86_64여야 함
    CANDIDATE_ARCH=$(file "$candidate" 2>/dev/null | grep -c "x86_64" || true)
    if [ "$CANDIDATE_ARCH" -gt 0 ] || [ "$(uname -m)" = "x86_64" ]; then
      FFMPEG_SRC="$candidate"
      break
    fi
  fi
done

# fallback: 아키텍처 무관하게 첫 번째 ffmpeg 사용
if [ -z "$FFMPEG_SRC" ]; then
  for candidate in \
    "$(which ffmpeg 2>/dev/null)" \
    "/usr/local/bin/ffmpeg" \
    "/opt/homebrew/bin/ffmpeg"; do
    if [ -f "$candidate" ]; then
      FFMPEG_SRC="$candidate"
      break
    fi
  done
fi

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
# Intel Mac (iMac 2015 Late)은 최대 Monterey(12) 또는 Big Sur(11)까지 지원
# 하위 호환성을 위해 10.15(Catalina)로 낮춤
set_plist LSMinimumSystemVersion "10.15" string
/usr/libexec/PlistBuddy -c "Delete :NSMicrophoneUsageDescription" "$INFO_PLIST" 2>/dev/null || true
set_plist NSDesktopFolderUsageDescription "음악 파일을 열기 위해 접근합니다" string
set_plist NSDocumentsFolderUsageDescription "음악 파일을 열기 위해 접근합니다" string
set_plist NSDownloadsFolderUsageDescription "음악 파일을 열기 위해 접근합니다" string
set_plist NSRemovableVolumesUsageDescription "외장 드라이브의 음악 파일 및 SACD ISO를 재생합니다" string

# ── 파일 연결 (CFBundleDocumentTypes) 등록 ──────────────────────
echo "  파일 연결(CFBundleDocumentTypes) 등록 중..."
python3 - "$INFO_PLIST" <<'PYEOF'
import sys, plistlib

plist_path = sys.argv[1]
with open(plist_path, 'rb') as f:
    plist = plistlib.load(f)

audio_exts = [
    'flac', 'wav', 'aiff', 'aif',
    'mp3', 'm4a', 'aac',
    'ogg', 'opus',
    'wv', 'ape', 'tta', 'wma',
    'dsf', 'dff', 'iso',
]

plist['CFBundleDocumentTypes'] = [{
    'CFBundleTypeName': 'Audio File',
    'CFBundleTypeExtensions': audio_exts,
    'CFBundleTypeRole': 'Viewer',
    'LSHandlerRank': 'Alternate',
}]

with open(plist_path, 'wb') as f:
    plistlib.dump(plist, f)
print(f'  ✓ CFBundleDocumentTypes 등록 완료 ({len(audio_exts)}개 확장자)')
PYEOF

# ── 7. scipy 불필요 파일 제거 (용량 최적화) ──────────────────────
echo "▶ scipy 테스트/문서 파일 제거 (용량 최적화)..."
for SEARCH_DIR in "$APP_PATH/Contents/Frameworks" "$APP_PATH/Contents/Resources"; do
  find "$SEARCH_DIR" -type d -name "tests" 2>/dev/null | xargs rm -rf 2>/dev/null || true
  find "$SEARCH_DIR" -name "*.pyx" -delete 2>/dev/null || true
  find "$SEARCH_DIR" -name "*.pxd" -delete 2>/dev/null || true
  find "$SEARCH_DIR" -name "*.f" -delete 2>/dev/null || true
  find "$SEARCH_DIR" -name "*.f90" -delete 2>/dev/null || true
  find "$SEARCH_DIR" -type d -name "__pycache__" 2>/dev/null | xargs rm -rf 2>/dev/null || true
done
echo "  ✓ 불필요 파일 제거 완료"

# ── 8. Ad-hoc 코드사이닝 ─────────────────────────────────────────
echo "▶ Ad-hoc 코드사이닝 (entitlements 포함)..."
ENTITLEMENTS="$DIR/entitlements.plist"
if [ -f "$ENTITLEMENTS" ]; then
  codesign --force --deep --sign - \
    --entitlements "$ENTITLEMENTS" \
    "$APP_PATH" 2>/dev/null \
    && echo "  ✓ ad-hoc 서명 완료 (entitlements 적용)" \
    || echo "  ⚠ 서명 실패 (무시)"
else
  codesign --force --deep --sign - "$APP_PATH" 2>/dev/null \
    && echo "  ✓ ad-hoc 서명 완료" || echo "  ⚠ 서명 실패 (무시)"
fi

# ── Quarantine 속성 제거 ─────────────────────────────────────────
xattr -cr "$APP_PATH" 2>/dev/null && echo "▶ quarantine 속성 제거 완료" || true

# ── 9. DMG 생성 ─────────────────────────────────────────────────
echo "▶ DMG 생성..."
DMG_NAME="${APP_NAME}-${VERSION}-IntelMac"
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
echo "         xattr -cr '/Applications/Nikon Chinge HiFi Player.app'"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
