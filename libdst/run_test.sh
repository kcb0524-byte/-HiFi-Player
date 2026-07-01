#!/bin/bash
# macOS에서 직접 실행하는 스크립트
SACD="/tmp/sacd-ripper"
LIBDST="$SACD/libs/libdstdec"
DIR="$(cd "$(dirname "$0")"; pwd)"

# sacd-ripper 없으면 클론
if [ ! -d "$LIBDST" ]; then
    echo "sacd-ripper 클론 중..."
    git clone --depth=1 https://github.com/sacd-ripper/sacd-ripper.git "$SACD"
fi

echo "=== 컴파일 ==="
gcc -O2 \
    -I"$LIBDST" \
    "$DIR/test_correct_dst.c" \
    "$LIBDST/dst_ac.c" \
    "$LIBDST/dst_data.c" \
    "$LIBDST/dst_init.c" \
    "$LIBDST/dst_fram.c" \
    "$LIBDST/unpack_dst.c" \
    "$LIBDST/ccp_calc.c" \
    -o "$DIR/test_correct_dst" 2>&1

if [ $? -eq 0 ]; then
    echo "컴파일 성공"
    echo ""
    echo "=== 실행 ==="
    "$DIR/test_correct_dst"
else
    echo "컴파일 실패"
fi
