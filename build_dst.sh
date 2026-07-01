#!/bin/bash
# DST 디코더 라이브러리 빌드 스크립트
# sacd-ripper의 libdst를 macOS용 .dylib으로 빌드

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/dst_build"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

echo "=== DST 디코더 소스 다운로드 ==="

# sacd-ripper GitHub에서 libdst 소스 파일들 다운로드
BASE="https://raw.githubusercontent.com/sacd-ripper/sacd-ripper/master/libs/libdst"

FILES=(
    "dst_decoder.c"
    "dst_decoder.h"
    "dst_fram.c"
    "dst_fram.h"
    "dst_init.c"
    "dst_init.h"
    "dst_ac.c"
    "dst_ac.h"
    "dst_data.c"
    "dst_data.h"
    "dst_dct.c"
    "dst_dct.h"
    "dst_err.c"
    "dst_err.h"
    "dst_framehdr.c"
    "dst_framehdr.h"
    "dst_predict.c"
    "dst_predict.h"
    "dst_status.h"
    "unpack_dst.c"
    "unpack_dst.h"
)

for f in "${FILES[@]}"; do
    echo "  다운로드: $f"
    curl -fsSL "$BASE/$f" -o "$f" 2>/dev/null || echo "  SKIP: $f (없음)"
done

echo ""
echo "=== 다운로드된 파일 목록 ==="
ls -la *.c *.h 2>/dev/null || true

echo ""
echo "=== libdst.dylib 빌드 ==="
C_FILES=($(ls *.c 2>/dev/null))
if [ ${#C_FILES[@]} -eq 0 ]; then
    echo "ERROR: C 파일이 없습니다. 네트워크 오류일 수 있습니다."
    exit 1
fi

gcc -O2 -fPIC -shared \
    -I. \
    "${C_FILES[@]}" \
    -o "$SCRIPT_DIR/libdst.dylib" \
    -install_name "@rpath/libdst.dylib"

echo "빌드 성공: $SCRIPT_DIR/libdst.dylib"
ls -lh "$SCRIPT_DIR/libdst.dylib"
