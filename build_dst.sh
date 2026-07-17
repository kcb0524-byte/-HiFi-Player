#!/bin/bash
# libdst.dylib 빌드 스크립트 (수정된 DST 디코더)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIBDST="$SCRIPT_DIR/libdst"
OUT_DIR="${1:-$(pwd)}"
echo "소스: $LIBDST"
echo "출력: $OUT_DIR/libdst.dylib"

# 필요한 파일만 명시 (dst_decoder.c 제외)
SRCS=(
  "$LIBDST/dst_fram.c"
  "$LIBDST/dst_init.c"
  "$LIBDST/unpack_dst.c"
  "$LIBDST/dst_data.c"
  "$LIBDST/ccp_calc.c"
  "$LIBDST/dst_ac.c"
  "$LIBDST/dst_wrapper.c"
)

clang -O2 -shared -fPIC -o "$OUT_DIR/libdst.dylib" "${SRCS[@]}" -I"$LIBDST" -lm \
  && echo "빌드 완료!" \
  || { echo "clang 실패, gcc 시도..."; gcc -O2 -shared -fPIC -o "$OUT_DIR/libdst.dylib" "${SRCS[@]}" -I"$LIBDST" -lm && echo "빌드 완료!"; }
