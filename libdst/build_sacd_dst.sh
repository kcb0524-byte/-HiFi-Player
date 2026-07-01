#!/bin/bash
# sacd-ripper libdst 빌드 스크립트
set -e

SACD_DIR="/tmp/sacd-ripper"
OUT_DIR="$(dirname "$0")"

echo "=== sacd-ripper 구조 확인 ==="
find "$SACD_DIR" -name "*.c" | grep -i "dst\|sacd\|dsd" | head -20
echo ""
echo "=== libs 디렉토리 ==="
ls "$SACD_DIR/libs/" 2>/dev/null || ls "$SACD_DIR/src/" 2>/dev/null || ls "$SACD_DIR"

echo ""
echo "=== libdst 파일 찾기 ==="
find "$SACD_DIR" -name "*dst*" -o -name "*DST*" 2>/dev/null | head -20
