#!/bin/bash
# HiFi Player 설치 스크립트 (macOS)
# 터미널에서 실행: bash install_mac.sh

set -e
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  HiFi Player 설치 시작 (macOS)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Python 버전 확인
PYTHON=$(which python3 || which python)
if [ -z "$PYTHON" ]; then
    echo "❌ Python이 설치되지 않았습니다. python.org에서 Python 3.10+ 설치 후 다시 시도하세요."
    exit 1
fi
echo "✅ Python: $($PYTHON --version)"

# pip 업그레이드
echo ""
echo "📦 pip 업그레이드 중..."
$PYTHON -m pip install --upgrade pip --quiet

# 의존성 설치
echo ""
echo "📦 패키지 설치 중 (PyQt5, sounddevice, soundfile, mutagen, numpy)..."
$PYTHON -m pip install -r requirements.txt

# portaudio 확인 (sounddevice 의존)
echo ""
if ! brew list portaudio &>/dev/null 2>&1; then
    if command -v brew &>/dev/null; then
        echo "📦 portaudio 설치 중 (Homebrew)..."
        brew install portaudio
    else
        echo "⚠️  Homebrew가 없습니다. portaudio를 수동으로 설치하거나"
        echo "   https://brew.sh 에서 Homebrew 설치 후 'brew install portaudio' 실행하세요."
    fi
else
    echo "✅ portaudio 확인됨"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ 설치 완료!"
echo "  실행: python3 main.py"
echo "  또는: bash run.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
