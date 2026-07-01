#!/bin/bash
set -e
LIBDST="/tmp/sacd-ripper/libs/libdstdec"
OUT="$(dirname "$0")"

echo "=== libdstdec 파일 목록 ==="
ls -la "$LIBDST/"

echo ""
echo "=== dst_decoder.h 확인 ==="
cat "$LIBDST/dst_decoder.h"

echo ""
echo "=== libdstdec.dylib 빌드 ==="
cd "$LIBDST"
gcc -O2 -fPIC -shared \
    -I. \
    dst_decoder.c dst_ac.c dst_data.c dst_fram.c dst_init.c unpack_dst.c \
    -o "$OUT/libdstdec.dylib" \
    -install_name "@rpath/libdstdec.dylib" \
    && echo "빌드 성공!" \
    || echo "빌드 실패 — 오류 확인 필요"

ls -lh "$OUT/libdstdec.dylib" 2>/dev/null
