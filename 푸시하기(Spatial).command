#!/bin/bash
# Spatial 브랜치를 GitHub에 푸시 → Actions가 Windows/macOS 빌드를 자동 시작합니다
cd "$(dirname "$0")"
echo "GitHub로 spatial 브랜치 푸시 중..."
git push -u origin spatial
echo ""
echo "완료되면 아래 주소에서 빌드 진행 상황을 확인하세요:"
echo "https://github.com/kcb0524-byte/-HiFi-Player/actions"
read -p "Enter를 누르면 창이 닫힙니다..."
