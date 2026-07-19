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
import os
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QTimer, QEvent
from PyQt5.QtGui import QIcon, QFont
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

from player_window import HiFiPlayer
from constants import APP_VERSION

# 단일 인스턴스 로컬 소켓 이름 (사용자별로 격리)
_INSTANCE_KEY = f"NikonChingeHiFiPlayer-{os.environ.get('USER') or os.environ.get('USERNAME') or 'default'}"


class HiFiApplication(QApplication):
    """macOS Finder 파일 열기(QFileOpenEvent) 처리용 QApplication.

    macOS는 파일 더블클릭 시 argv가 아니라 Apple Event(QFileOpenEvent)로
    경로를 전달한다 — 최초 실행/실행 중 양쪽 모두 이 이벤트로 온다.
    여러 파일을 한꺼번에 열면 이벤트가 파일마다 따로 오므로
    250ms 동안 모아서(batch) 한 번에 처리한다.
    """

    def __init__(self, argv):
        super().__init__(argv)
        self._open_handler = None    # window.open_files_from_external
        self._pending_open = []      # 핸들러 준비 전/배치 중 경로 버퍼
        self._flush_scheduled = False

    def set_open_handler(self, handler):
        self._open_handler = handler
        if self._pending_open and not self._flush_scheduled:
            self._schedule_flush()

    def _schedule_flush(self):
        self._flush_scheduled = True
        QTimer.singleShot(250, self._flush_open)

    def _flush_open(self):
        self._flush_scheduled = False
        if not self._pending_open:
            return
        if self._open_handler is None:
            return   # 핸들러 등록 시 다시 flush됨
        paths, self._pending_open = self._pending_open, []
        try:
            self._open_handler(paths)
        except Exception as e:
            print(f"[FileOpen] 처리 실패: {e}")

    def event(self, e):
        if e.type() == QEvent.FileOpen:
            path = e.file()
            if path:
                print(f"[FileOpen] macOS 파일 열기 이벤트: {path}")
                self._pending_open.append(path)
                if not self._flush_scheduled:
                    self._schedule_flush()
            return True
        return super().event(e)


def _audio_paths_from_argv(argv) -> list:
    """시작 인자에서 지원 오디오 파일 경로만 추출 (파일 연결 실행 대응)"""
    from audio_engine import AudioEngine
    paths = []
    for a in argv[1:]:
        try:
            if os.path.isfile(a) and \
                    os.path.splitext(a)[1].lower() in AudioEngine.SUPPORTED_FORMATS:
                paths.append(os.path.abspath(a))
        except Exception:
            pass
    return paths


def _forward_to_running_instance(paths: list) -> bool:
    """이미 실행 중인 인스턴스에 파일 경로 전달. 성공 시 True.

    경로는 UTF-8로 인코딩해 전달 — 한글/특수문자 경로 안전.
    """
    sock = QLocalSocket()
    sock.connectToServer(_INSTANCE_KEY)
    if not sock.waitForConnected(300):
        return False
    payload = '\n'.join(paths) if paths else '__RAISE__'
    sock.write(payload.encode('utf-8'))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def _start_instance_server(window: HiFiPlayer) -> QLocalServer:
    """단일 인스턴스 서버 — 두 번째 인스턴스가 보낸 파일을 기존 창에서 열기"""
    QLocalServer.removeServer(_INSTANCE_KEY)   # 비정상 종료 잔재 정리
    server = QLocalServer()
    server.listen(_INSTANCE_KEY)

    def _on_new_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def _read():
            data = bytes(conn.readAll()).decode('utf-8', errors='replace')
            files = [p for p in data.split('\n') if p and p != '__RAISE__']
            if files:
                window.open_files_from_external(files)
            # 기존 창 앞으로
            window.show()
            window.raise_()
            window.activateWindow()

        conn.readyRead.connect(_read)
        if conn.bytesAvailable():
            _read()

    server.newConnection.connect(_on_new_connection)
    return server


def main():
    # 고DPI 지원 — QApplication 생성 전에 설정해야 함
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = HiFiApplication(sys.argv)
    app.setApplicationName("Nikon Chinge HiFi Music Player")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("HiFiPlayer")

    # 파일 연결/명령행으로 전달된 오디오 파일
    startup_paths = _audio_paths_from_argv(sys.argv)

    # 이미 실행 중이면 기존 창에 경로만 넘기고 즉시 종료 (단일 인스턴스)
    if _forward_to_running_instance(startup_paths):
        return

    # 타이틀바 폰트: Windows는 Segoe UI, macOS는 SF Pro(시스템 기본)
    if sys.platform == 'win32':
        font = QFont("Segoe UI", 9)
        font.setWeight(QFont.Light)
        app.setFont(font)

    window = HiFiPlayer()

    # 타이틀바 아이콘 제거 (빈 아이콘으로 대체)
    window.setWindowIcon(QIcon())

    # 단일 인스턴스 서버 (window 수명에 묶어 GC 방지)
    window._single_instance_server = _start_instance_server(window)

    window.show()

    # macOS Finder 더블클릭(QFileOpenEvent) → 기존 창에서 열기
    app.set_open_handler(window.open_files_from_external)

    # 시작 인자 파일: 이벤트 루프 시작 후 열기 (UI 준비 완료 시점)
    if startup_paths:
        QTimer.singleShot(0, lambda: window.open_files_from_external(startup_paths))

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
