#!/bin/bash
# ISO 파일 경로 자동 탐색 후 디버그 실행
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 가능한 경로들 시도
PATHS=(
  "/Volumes/KCB SSD/Rainbow - Ritchie Blackmore's Rainbow (1975) [SACD, 24-192rip] (2014)/Ritchie Blackmore's Rainbow.iso"
  "/Volumes/KCB M.2 A/Rainbow - Ritchie Blackmore's Rainbow (1975) [SACD, 24-192rip] (2014)/Ritchie Blackmore's Rainbow.iso"
  "/Volumes/KCB SSD/POP/Rainbow - Ritchie Blackmore's Rainbow (1975) [SACD, 24-192rip] (2014)/Ritchie Blackmore's Rainbow.iso"
  "/Volumes/KCB M.2 A/POP/Rainbow - Ritchie Blackmore's Rainbow (1975) [SACD, 24-192rip] (2014)/Ritchie Blackmore's Rainbow.iso"
)

ISO_PATH=""
for p in "${PATHS[@]}"; do
  if [ -f "$p" ]; then
    ISO_PATH="$p"
    break
  fi
done

# find로 fallback
if [ -z "$ISO_PATH" ]; then
  ISO_PATH=$(find /Volumes -name "Ritchie Blackmore*.iso" 2>/dev/null | head -1)
fi

if [ -z "$ISO_PATH" ]; then
  echo "ISO 파일을 찾을 수 없습니다. /Volumes 내 ISO 목록:"
  find /Volumes -name "*.iso" 2>/dev/null
  exit 1
fi

echo "ISO 경로: $ISO_PATH"
python3 "$SCRIPT_DIR/debug_sacd.py" "$ISO_PATH"
