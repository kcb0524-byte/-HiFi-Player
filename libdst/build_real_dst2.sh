#!/bin/bash
set -e
SACD="/tmp/sacd-ripper"
LIBDST="$SACD/libs/libdstdec"
OUT="$(dirname "$0")"

echo "=== logging.h 위치 찾기 ==="
find "$SACD" -name "logging.h" 2>/dev/null
find "$SACD" -name "*.h" | xargs grep -l "logging\|log_" 2>/dev/null | head -5

echo ""
echo "=== libcommon 확인 ==="
ls "$SACD/libs/libcommon/" 2>/dev/null | head -20

echo ""
echo "=== dst_decoder.c의 include 목록 ==="
grep "#include" "$LIBDST/dst_decoder.c"

echo ""
echo "=== 빌드 (include 경로 추가) ==="
cd "$LIBDST"

# libcommon 포함해서 빌드
INCLUDES="-I. -I$SACD/libs/libcommon -I$SACD/include"

# 먼저 어떤 추가 파일들이 필요한지 확인
gcc -O2 $INCLUDES -c dst_decoder.c -o /tmp/dst_decoder.o 2>&1 | head -20
