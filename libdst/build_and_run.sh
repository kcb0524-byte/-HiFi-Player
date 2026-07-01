#!/bin/bash
SACD="/tmp/sacd-ripper"
LIBDST="$SACD/libs/libdstdec"
DIR="$(dirname "$0")"

echo "=== 컴파일 ==="
gcc -O2 \
    -I"$LIBDST" \
    "$DIR/test_real_dst.c" \
    "$LIBDST/dst_ac.c" \
    "$LIBDST/dst_data.c" \
    "$LIBDST/dst_init.c" \
    "$LIBDST/dst_fram.c" \
    "$LIBDST/unpack_dst.c" \
    "$LIBDST/ccp_calc.c" \
    -o "$DIR/test_real_dst" \
    2>&1

if [ $? -eq 0 ]; then
    echo "컴파일 성공!"
    echo ""
    echo "=== 실행 ==="
    "$DIR/test_real_dst"
else
    echo "컴파일 실패"
fi
