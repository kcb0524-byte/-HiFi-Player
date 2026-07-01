#!/bin/bash
echo "=== macOS ffmpeg DST 지원 확인 ==="
/usr/local/bin/ffmpeg -decoders 2>/dev/null | grep -i "dst\|dsd" || echo "DST 디코더 없음"
echo ""
echo "=== macOS ffmpeg 라이브러리 위치 ==="
ls /usr/local/lib/libav*.dylib 2>/dev/null
ls /usr/local/Cellar/ffmpeg/*/lib/libav*.dylib 2>/dev/null | head -5
echo ""
echo "=== libavcodec에 DST 심볼 있는지 ==="
LIBAV=$(ls /usr/local/Cellar/ffmpeg/*/lib/libavcodec.dylib 2>/dev/null | head -1)
if [ -n "$LIBAV" ]; then
    nm -D "$LIBAV" 2>/dev/null | grep -i "dst\|dsd" | head -20
    echo "라이브러리: $LIBAV"
else
    echo "libavcodec.dylib 없음"
fi
