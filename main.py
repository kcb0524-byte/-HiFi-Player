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
import io
import os
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QIcon, QFont

from player_window import HiFiPlayer


def _fix_win_encoding():
    """Windows 콘솔 stdout/stderr를 UTF-8로 강제 설정 (한글 깨짐 방지)."""
    if sys.platform != 'win32':
        return
    try:
        os.environ.setdefault('PYTHONUTF8', '1')
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        else:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass


class HiFiApplication(QApplication):
    """macOS Finder 파일 더블클릭 이벤트(QFileOpenEvent) 처리용 QApplication 서브클래스."""

    def __init__(self, argv):
        super().__init__(argv)
        self._window: HiFiPlayer = None
        self._pending_file: str = None  # 윈도우 생성 전에 도착한 파일 경로 임시 보관

    def set_window(self, window: HiFiPlayer):
        self._window = window
        # 윈도우 생성 전에 도착한 파일이 있으면 지금 열기
        if self._pending_file:
            self._open_file(self._pending_file)
            self._pending_file = None

    def event(self, event: QEvent) -> bool:
        # macOS: Finder 더블클릭 / '이 앱으로 열기' 선택 시 발생
        if event.type() == QEvent.FileOpen:
            filepath = event.file()
            if filepath:
                if self._window:
                    self._open_file(filepath)
                else:
                    self._pending_file = filepath
            return True
        return super().event(event)

    def _open_file(self, filepath: str):
        """파일을 플레이리스트에 추가하고 즉시 재생."""
        if not self._window:
            return
        try:
            self._window.open_file_from_os(filepath)
        except Exception as e:
            print(f'[FileOpen] 오류: {e}')


def main():
    # 고DPI 지원 — QApplication 생성 전에 설정해야 함
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = HiFiApplication(sys.argv)
    app.setApplicationName("Nikon Chinge HiFi Music Player")
    app.setApplicationVersion("1.0")
    app.setOrganizationName("HiFiPlayer")

    # 타이틀바 폰트: Windows는 Segoe UI, macOS는 SF Pro(시스템 기본)
    if sys.platform == 'win32':
        font = QFont("Segoe UI", 9)
        font.setWeight(QFont.Light)
        app.setFont(font)

    window = HiFiPlayer()
    window.show()
    app.set_window(window)

    # 타이틀바 아이콘 제거 — show() 이후 빈 아이콘 적용
    window.setWindowIcon(QIcon())

    # Windows / 터미널 실행: 파일 경로가 인자로 전달된 경우
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        if os.path.isfile(filepath):
            window.open_file_from_os(filepath)

    sys.exit(app.exec_())


if __name__ == '__main__':
    _fix_win_encoding()
    main()
