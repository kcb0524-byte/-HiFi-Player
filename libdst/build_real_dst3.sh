#!/bin/bash
SACD="/tmp/sacd-ripper"
LIBDST="$SACD/libs/libdstdec"
OUT="$(dirname "$0")"

echo "=== dst_fram.c, dst_init.c include 확인 ==="
grep "#include" "$LIBDST/dst_fram.c" | head -20
echo "---"
grep "#include" "$LIBDST/dst_init.c" | head -20
echo "---"
grep "#include" "$LIBDST/unpack_dst.c" | head -10
echo "---"
grep "#include" "$LIBDST/dst_ac.c" | head -10
echo "---"
grep "#include" "$LIBDST/dst_data.c" | head -10
echo ""

echo "=== 핵심 파일만 빌드 시도 (dst_decoder.c 제외) ==="
cd "$LIBDST"
INCLUDES="-I. -I$SACD/libs/libcommon"

gcc -O2 $INCLUDES -c dst_ac.c    -o /tmp/dst_ac.o    2>&1 && echo "dst_ac.c OK" || echo "dst_ac.c FAIL"
gcc -O2 $INCLUDES -c dst_data.c  -o /tmp/dst_data.o  2>&1 && echo "dst_data.c OK" || echo "dst_data.c FAIL"
gcc -O2 $INCLUDES -c dst_init.c  -o /tmp/dst_init.o  2>&1 | head -5; [ ${PIPESTATUS[0]} -eq 0 ] && echo "dst_init.c OK" || echo "dst_init.c FAIL"
gcc -O2 $INCLUDES -c dst_fram.c  -o /tmp/dst_fram.o  2>&1 | head -5; [ ${PIPESTATUS[0]} -eq 0 ] && echo "dst_fram.c OK" || echo "dst_fram.c FAIL"
gcc -O2 $INCLUDES -c unpack_dst.c -o /tmp/unpack_dst.o 2>&1 | head -5; [ ${PIPESTATUS[0]} -eq 0 ] && echo "unpack_dst.c OK" || echo "unpack_dst.c FAIL"
