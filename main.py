"""
HiFi Player - 고음질 음원 플레이어
DSF/DFF(DSD), FLAC, WAV, AIFF, MP3 등 광범위한 포맷 지원
외장 DAC 포함 모든 출력 장치 선택 가능

모듈 구조:
  constants.py      — 색상 테마, 스타일시트, EQ 프리셋 상수
  ui_widgets.py     — 재사용 가능한 커스텀 위젯 모음
  player_window.py  — HiFiPlayer 메인 윈도우
  audio_engine.py   — 오디오 재생 엔진
  dsd_decoder.py    — DSD(DSF/DFF) 디코더
  main.py           — 진입점 (이 파일)
"""

import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from player_window import HiFiPlayer


def main():
    # 고DPI 지원 — QApplication 생성 전에 설정해야 함
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("니콘 친게 HiFi Music Player")
    app.setApplicationVersion("1.0")
    app.setOrganizationName("HiFiPlayer")

    window = HiFiPlayer()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
