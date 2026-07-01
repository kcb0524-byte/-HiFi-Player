#!/bin/bash
echo "=== 시스템 아키텍처 ==="
uname -m
arch

echo ""
echo "=== Python 아키텍처 ==="
python3 -c "import platform; print(platform.machine())"
file $(which python3)

echo ""
echo "=== Homebrew 위치 ==="
which brew
brew --prefix

echo ""
echo "=== ffmpeg 아키텍처 ==="
file /usr/local/bin/ffmpeg
file $(which ffmpeg)

echo ""
echo "=== arm64 ffmpeg 있는지 ==="
ls /opt/homebrew/bin/ffmpeg 2>/dev/null && echo "arm64 ffmpeg 있음: /opt/homebrew/bin/ffmpeg" || echo "없음"
ls /opt/homebrew/lib/libavcodec* 2>/dev/null | head -3

echo ""
echo "=== Rosetta 여부 ==="
sysctl -n sysctl.proc_translated 2>/dev/null || echo "네이티브 실행"
