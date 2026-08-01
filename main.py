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
import traceback
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QFont

from player_window import HiFiPlayer


def _global_excepthook(etype, value, tb):
    """전역 예외 처리기 — 처리되지 않은 오류가 나도 앱을 종료하지 않고
    오류 창만 띄운다. (PyQt5는 기본적으로 슬롯 내 미처리 예외 시 앱을 강제 종료함)"""
    msg = ''.join(traceback.format_exception(etype, value, tb))
    print(f"[오류] 처리되지 않은 예외:\n{msg}", file=sys.stderr)
    try:
        box = QMessageBox()
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("오류")
        box.setText("작업 중 오류가 발생했지만 앱은 계속 실행됩니다.")
        box.setDetailedText(msg)
        box.exec_()
    except Exception:
        pass  # 오류창 표시 실패해도 앱은 유지


def main():
    sys.excepthook = _global_excepthook
    # 고DPI 지원 — QApplication 생성 전에 설정해야 함
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("Nikon Chinge HiFi Music Player - Spatial")
    app.setApplicationVersion("1.0")
    app.setOrganizationName("HiFiPlayer")

    # 타이틀바 폰트: Windows는 Segoe UI, macOS는 SF Pro(시스템 기본)
    if sys.platform == 'win32':
        font = QFont("Segoe UI", 9)
        font.setWeight(QFont.Light)
        app.setFont(font)

    window = HiFiPlayer()

    # 타이틀바 아이콘 제거 (빈 아이콘으로 대체)
    window.setWindowIcon(QIcon())

    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
