#!/bin/bash
set -e
SACD="/tmp/sacd-ripper"
LIBDST="$SACD/libs/libdstdec"
OUT="$(dirname "$0")"

# ebunch 구조체 확인
echo "=== ebunch 구조체 위치 ==="
grep -rn "ebunch\|typedef.*ebunch" "$LIBDST/" | grep -v ".c:" | head -10

echo ""
echo "=== dst_init.h 전체 ==="
cat "$LIBDST/dst_init.h"
