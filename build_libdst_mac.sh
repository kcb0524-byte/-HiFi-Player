#!/bin/bash
# build_libdst_mac.sh — macOS용 libdst.dylib 빌드 (arm64 + x86_64 유니버설)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIBDST_DIR="$SCRIPT_DIR/libdst"
OUT="$SCRIPT_DIR/libdst.dylib"

echo "==================================================="
echo "  libdst.dylib 빌드 (DST SACD ISO 디코더)"
echo "==================================================="
echo "소스: $LIBDST_DIR"
echo "출력: $OUT"
echo ""

# 소스 파일 목록 (libdstdec 코어 + 래퍼)
SRCS="
    buffer_pool.c
    ccp_calc.c
    dst_ac.c
    dst_data.c
    dst_fram.c
    dst_init.c
    unpack_dst.c
    yarn.c
    dst_wrapper.c
"

cd "$LIBDST_DIR"

# 소스 파일 존재 확인
for f in $SRCS; do
    f_trim=$(echo "$f" | xargs)
    [ -z "$f_trim" ] && continue
    if [ ! -f "$f_trim" ]; then
        echo "❌ 소스 파일 없음: $LIBDST_DIR/$f_trim"
        exit 1
    fi
done

FLAGS="-O2 -DNDEBUG -fPIC -Wall -Wno-unused-variable -Wno-unused-function"

# 유니버설 바이너리 시도 (arm64 + x86_64)
echo "→ 유니버설 바이너리 시도 (arm64 + x86_64)..."
if clang $FLAGS -arch arm64 -arch x86_64 \
    $SRCS \
    -dynamiclib \
    -install_name "@rpath/libdst.dylib" \
    -o "$OUT" 2>&1; then
    echo "✓ 유니버설 바이너리 빌드 성공"
else
    echo "→ 유니버설 빌드 실패, 네이티브 아키텍처로 재시도..."
    ARCH=$(uname -m)
    clang $FLAGS -arch "$ARCH" \
        $SRCS \
        -dynamiclib \
        -install_name "@rpath/libdst.dylib" \
        -o "$OUT"
    echo "✓ 네이티브 바이너리 빌드 성공 ($ARCH)"
fi

echo ""
echo "==================================================="
echo "  빌드 완료: $OUT"
echo "==================================================="
file "$OUT"
echo ""
echo "다음 단계: 앱을 재시작하면 DST SACD ISO 재생이 활성화됩니다."
