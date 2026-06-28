"""
HiFi Player — 메인 윈도우 (HiFiPlayer) 및 진입점
"""

"""
HiFi Player - 고음질 음원 플레이어
DSF/DFF(DSD), FLAC, WAV, AIFF, MP3 등 광범위한 포맷 지원
외장 DAC 포함 모든 출력 장치 선택 가능
"""

import sys
import os
import json
import random
import threading
from pathlib import Path
from typing import Optional, List

import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QListWidget, QListWidgetItem,
    QFileDialog, QComboBox, QFrame, QSplitter, QProgressBar,
    QToolButton, QSizePolicy, QMenu, QAction, QAbstractItemView,
    QMessageBox, QStyle, QGridLayout, QScrollArea, QCheckBox,
    QStackedWidget, QStyledItemDelegate,
)
from PyQt5.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QUrl, QSize, QMimeData,
    QPoint, QEvent,
)
from PyQt5.QtGui import (
    QIcon, QFont, QFontMetrics, QPalette, QColor, QDragEnterEvent, QDropEvent,
    QPixmap, QPainter, QLinearGradient, QBrush, QPen, QPainterPath,
    QRadialGradient, QConicalGradient,
)

from audio_engine import AudioEngine, AudioDevice
from dsd_decoder import DSDDecoder
from sacd_decoder import SACDDecoder
from upnp_browser import UPnPDialog


from constants import DARK, EQ_PRESETS, EQ_BAND_LABELS, STYLESHEET
from ui_widgets import (
    TrackLoader, MarqueeLabel, CDWidget, EQGraph, PresetPanel, EQPanel,
    ToggleSwitch, TransportButton, IconButton, VUMeter,
    TrackItem, PlaylistDelegate, PlaylistHeader, PlaylistWidget,
)

class HiFiPlayer(QMainWindow):
    _position_signal = pyqtSignal(float, float)
    _finished_signal = pyqtSignal()
    _error_signal = pyqtSignal(str)
    _vu_signal = pyqtSignal(float, float)
    _freq_signal = pyqtSignal(list)

    SETTINGS_FILE = str(Path.home() / '.hifi_player_settings.json')

    def __init__(self):
        super().__init__()
        self.engine = AudioEngine()
        self.current_index: int = -1
        self.current_info: dict = {}
        self._loader: Optional[TrackLoader] = None
        self._seeking = False
        self._last_finished_index: int = -1
        self._shuffle = False
        # repeat_mode: 0=없음, 1=한곡 반복, 2=전체(셔플 포함)
        # _repeat_mode는 UI 빌드 후 btn_repeat에 반영되므로 여기서는 초기값만

        self._setup_engine_callbacks()
        self._build_ui()
        self._load_devices()
        self._load_settings()

        # Windows: DWM API로 타이틀바 다크 모드 적용
        self._apply_dark_titlebar()

        # 글로벌 키보드 이벤트 필터 — 어떤 위젯이 포커스를 가져도 동작
        QApplication.instance().installEventFilter(self)

        # 시그널 연결
        self._vu_signal.connect(lambda l, r: self.vu_meter.set_level(l, r))
        self._freq_signal.connect(self.vu_meter.set_freq_levels)

        # 위치 업데이트 타이머
        self._pos_timer = QTimer(self)
        self._pos_timer.timeout.connect(self._update_position_display)
        self._pos_timer.start(200)

    # ─────────────────────────────────────────────
    # 엔진 콜백 연결 (스레드 안전)
    # ─────────────────────────────────────────────
    def _setup_engine_callbacks(self):
        self._position_signal.connect(self._on_position_changed)
        self._finished_signal.connect(self._on_playback_finished)
        self._error_signal.connect(self._on_error)

        def pos_cb(pos, dur):
            self._position_signal.emit(pos, dur)

        def fin_cb():
            self._finished_signal.emit()

        def err_cb(msg):
            self._error_signal.emit(msg)

        # 주파수 대역 경계 (Hz) — 8개 대역
        _FREQ_BANDS = [
            50, 100, 200, 400, 630, 1000,
            1600, 2500, 4000, 6300, 8000,
            10000, 12500, 14000, 16000, 20000
        ]

        def vu_cb(left, right):
            self._vu_signal.emit(left, right)

        def chunk_cb(chunk: np.ndarray, sample_rate: int):
            """오디오 청크에서 8개 주파수 대역 레벨 계산"""
            try:
                if chunk is None or len(chunk) == 0:
                    return
                mono = chunk[:, 0] if chunk.ndim > 1 else chunk
                n = len(mono)
                if n < 64:
                    return
                # FFT
                fft_mag = np.abs(np.fft.rfft(mono * np.hanning(n)))
                freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
                # 8개 대역 에너지 계산
                prev_f = 0
                band_levels = []
                for bf in _FREQ_BANDS:
                    mask = (freqs >= prev_f) & (freqs < bf)
                    if mask.any():
                        rms = float(np.sqrt(np.mean(fft_mag[mask] ** 2))) / (n * 0.5)
                        band_levels.append(min(1.0, rms * 60.0))
                    else:
                        band_levels.append(0.0)
                    prev_f = bf
                self._freq_signal.emit(band_levels)
            except Exception:
                pass

        self.engine.on_position_changed = pos_cb
        self.engine.on_playback_finished = fin_cb
        self.engine.on_error = err_cb
        self.engine.on_vu_level = vu_cb
        self.engine.on_chunk_ready = chunk_cb

    # ─────────────────────────────────────────────
    # UI 구성
    # ─────────────────────────────────────────────
    def _build_ui(self):
        self.setWindowTitle("니콘 친게 HiFi Music Player")
        self.setMinimumSize(920, 900)
        # 화면 높이에 맞게 자동 조정
        from PyQt5.QtWidgets import QDesktopWidget
        screen_h = QDesktopWidget().availableGeometry().height()
        win_h = min(1100, int(screen_h * 0.92))
        self._normal_size = (1120, win_h)
        self.resize(1120, win_h)
        self.setStyleSheet(STYLESHEET)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── QStackedWidget: 0=메인, 1=미니 ─────────────────────
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # ── 페이지 0: 메인 뷰 ───────────────────────────────────
        main_page = QWidget()
        root = QHBoxLayout(main_page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_left_panel())
        root.addWidget(self._build_right_panel(), 1)
        self._stack.addWidget(main_page)

        # ── 페이지 1: 미니플레이어 뷰 ──────────────────────────
        self._stack.addWidget(self._build_mini_panel())

        self._is_mini = False

    # ─── 섹션 헤더 헬퍼 ───────────────────────────────────────
    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(
            f"color:{DARK['accent']}; font-size:10px; font-weight:bold; letter-spacing:2px;")
        return lbl

    def _divider(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"color:{DARK['border']}; margin:2px 0;")
        return f

    # ─── 좌측 패널 ────────────────────────────────────────────
    def _build_left_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("LeftPanel")
        panel.setFixedWidth(480)

        from PyQt5.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        inner = QWidget()
        inner.setMinimumWidth(480)   # QScrollArea 수평 압축 방지
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(20, 12, 20, 8)
        lay.setSpacing(0)

        # ── 앨범 아트 영역 — 패널 폭(480) - 여백(20*2) = 440px 정사각형 ──
        ART_SIZE = 400

        art_frame = QFrame()
        art_frame.setObjectName("ArtCard")
        art_frame.setFixedSize(ART_SIZE, ART_SIZE)
        art_layout = QVBoxLayout(art_frame)
        art_layout.setContentsMargins(0, 0, 0, 0)
        art_layout.setAlignment(Qt.AlignCenter)

        # ── CD / 앨범아트 전환 스택 ──────────────────────────────
        self.art_stack = QStackedWidget()
        self.art_stack.setFixedSize(ART_SIZE, ART_SIZE)

        # index 0 — CD 애니메이션 (정사각형 내 중앙)
        cd_container = QWidget()
        cd_container.setFixedSize(ART_SIZE, ART_SIZE)
        cd_container.setStyleSheet("background:#111118;")
        cd_lay = QVBoxLayout(cd_container)
        cd_lay.setContentsMargins(0, 0, 0, 0)
        cd_lay.setAlignment(Qt.AlignCenter)
        self.cd_widget = CDWidget()
        self.cd_widget.setFixedSize(ART_SIZE, ART_SIZE)
        cd_lay.addWidget(self.cd_widget)
        self.art_stack.addWidget(cd_container)

        # index 1 — 앨범아트 QLabel (정사각형 꽉 채움)
        self.lbl_cover = QLabel()
        self.lbl_cover.setFixedSize(ART_SIZE, ART_SIZE)
        self.lbl_cover.setAlignment(Qt.AlignCenter)
        self.lbl_cover.setStyleSheet("background:#0a0a0f;")
        self.art_stack.addWidget(self.lbl_cover)

        self.art_stack.setCurrentIndex(0)
        art_layout.addWidget(self.art_stack)
        lay.addWidget(art_frame)
        lay.addSpacing(8)

        # 곡정보 레이블은 우측 패널 플레이리스트 헤더로 이동
        # (왼쪽 패널에서 제거하여 layout shift 원천 차단)
        self.lbl_title  = QLabel()   # 우측 패널에서 실제로 addWidget됨
        self.lbl_artist = QLabel()
        self.lbl_album  = QLabel()

        # ── 포맷 뱃지 + 스펙 (완전 고정 높이 — 재생 전후 동일 크기 유지) ──
        spec_container = QWidget()
        spec_container.setFixedHeight(26)
        spec_row = QHBoxLayout(spec_container)
        spec_row.setContentsMargins(0, 0, 0, 0)
        spec_row.setSpacing(8)
        spec_row.setAlignment(Qt.AlignCenter)

        # font-size는 항상 11px 고정 — 재생 전후 크기 변화 없음
        _BADGE_BASE = "font-size:11px; font-weight:bold; font-family:monospace; border-radius:3px; padding:1px 6px;"
        self.lbl_format = QLabel("—")
        self.lbl_format.setFixedHeight(20)
        self.lbl_format.setStyleSheet(
            f"color:transparent; {_BADGE_BASE} background:transparent; border:1px solid transparent;")
        self.lbl_format.setAlignment(Qt.AlignCenter)

        self.lbl_detail = QLabel("—")
        self.lbl_detail.setFixedHeight(20)
        self.lbl_detail.setStyleSheet(
            "color:transparent; font-size:11px; font-family:monospace;")

        spec_row.addWidget(self.lbl_format)
        spec_row.addWidget(self.lbl_detail)
        lay.addWidget(spec_container)
        lay.addSpacing(6)

        # 더미 레이블 (호환성 유지)
        self.lbl_samplerate = QLabel(); self.lbl_samplerate.hide()
        self.lbl_bitdepth   = QLabel(); self.lbl_bitdepth.hide()
        self.lbl_channels   = QLabel(); self.lbl_channels.hide()

        # ── 시크바 ─────────────────────────────────────────────
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)

        self.lbl_pos = QLabel("0:00")
        self.lbl_pos.setStyleSheet(f"color:{DARK['text_muted']}; font-size:11px; font-family:monospace;")
        self.lbl_pos.setFixedWidth(36)

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)

        self.lbl_dur = QLabel("0:00")
        self.lbl_dur.setStyleSheet(f"color:{DARK['text_muted']}; font-size:11px; font-family:monospace;")
        self.lbl_dur.setFixedWidth(36)
        self.lbl_dur.setAlignment(Qt.AlignRight)

        seek_row.addWidget(self.lbl_pos)
        seek_row.addWidget(self.seek_slider, 1)
        seek_row.addWidget(self.lbl_dur)
        lay.addLayout(seek_row)
        lay.addSpacing(8)

        # ── 트랜스포트 버튼 ────────────────────────────────────
        transport = QHBoxLayout()
        transport.setSpacing(0)
        transport.setAlignment(Qt.AlignCenter)

        BTN_SIZE = 44   # 모든 버튼 동일 크기

        self.btn_prev = TransportButton('prev', size=BTN_SIZE)
        self.btn_prev.setToolTip("이전 트랙")
        self.btn_prev.clicked.connect(self._prev_track)

        self.btn_play = TransportButton('play', size=BTN_SIZE, is_primary=True)
        self.btn_play.setToolTip("재생/일시정지")
        self.btn_play.clicked.connect(self._toggle_play)

        self.btn_next = TransportButton('next', size=BTN_SIZE)
        self.btn_next.setToolTip("다음 트랙")
        self.btn_next.clicked.connect(self._next_track)

        self.btn_stop = TransportButton('stop', size=BTN_SIZE)
        self.btn_stop.setToolTip("정지")
        self.btn_stop.clicked.connect(self._stop)

        # 순서: 이전 | 재생/일시정지 | 다음 | 정지
        transport.addStretch()
        transport.addWidget(self.btn_prev)
        transport.addSpacing(12)
        transport.addWidget(self.btn_play)
        transport.addSpacing(12)
        transport.addWidget(self.btn_next)
        transport.addSpacing(20)
        transport.addWidget(self.btn_stop)
        transport.addStretch()
        lay.addLayout(transport)
        lay.addSpacing(6)

        # ── 볼륨 + 셔플/반복 ──────────────────────────────────
        extra_row = QHBoxLayout()
        extra_row.setSpacing(8)

        self.btn_shuffle = IconButton('shuffle')
        self.btn_shuffle.setToolTip("Shuffle ON/OFF")
        self.btn_shuffle.clicked.connect(self._on_shuffle_clicked)
        self._update_shuffle_style()

        self.btn_repeat = IconButton('repeat')
        self.btn_repeat.setToolTip("Repeat: OFF → One → All")
        self.btn_repeat.clicked.connect(self._on_repeat_clicked)
        self._repeat_mode = 0
        self._update_repeat_style()

        vol_lbl = QLabel("VOL")
        vol_lbl.setStyleSheet(f"color:{DARK['text_muted']}; font-size:10px; letter-spacing:1px;")

        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(80)
        self.vol_slider.setToolTip("볼륨")
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        self.engine.set_volume(0.8)

        self.lbl_vol = QLabel("80%")
        self.lbl_vol.setStyleSheet(f"color:{DARK['text_dim']}; font-size:11px; font-family:monospace;")
        self.lbl_vol.setFixedWidth(34)

        extra_row.addWidget(self.btn_shuffle)
        extra_row.addWidget(self.btn_repeat)
        extra_row.addStretch()
        extra_row.addWidget(vol_lbl)
        extra_row.addWidget(self.vol_slider, 1)
        extra_row.addWidget(self.lbl_vol)
        lay.addLayout(extra_row)
        lay.addSpacing(10)

        # ── Level Meter ────────────────────────────────────────
        lay.addWidget(self._section_label("Level Meter"))
        lay.addSpacing(6)
        self.vu_meter = VUMeter()
        self.vu_meter.setFixedHeight(100)
        lay.addWidget(self.vu_meter)
        lay.addSpacing(4)

        # Replay Gain
        rg_row = QHBoxLayout()
        rg_lbl = QLabel("Replay Gain")
        rg_lbl.setStyleSheet(f"color:{DARK['text_dim']}; font-size:13px;")
        self.lbl_rg_info = QLabel("—")
        self.lbl_rg_info.setFixedHeight(16)
        self.lbl_rg_info.setStyleSheet(f"color:transparent; font-size:11px; font-family:monospace;")
        self.toggle_rg = ToggleSwitch(checked=True)
        self.toggle_rg.toggled.connect(self._on_rg_toggled)
        rg_row.addWidget(rg_lbl)
        rg_row.addWidget(self.lbl_rg_info, 1)
        rg_row.addWidget(self.toggle_rg)
        lay.addLayout(rg_row)
        lay.addSpacing(10)

        # ── Output Device ──────────────────────────────────────
        lay.addWidget(self._section_label("Output Device"))
        lay.addSpacing(4)
        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        lay.addWidget(self.device_combo)
        lay.addSpacing(10)

        # ── HiFi Options ───────────────────────────────────────
        lay.addWidget(self._section_label("HiFi Options"))
        lay.addSpacing(4)

        def _opt_row(label, desc, toggle):
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{DARK['text_dim']}; font-size:13px;")
            d = QLabel(desc)
            d.setStyleSheet(f"color:{DARK['text_muted']}; font-size:11px;")
            row.addWidget(lbl)
            row.addWidget(d, 1)
            row.addWidget(toggle)
            return row

        self.toggle_bp = ToggleSwitch(checked=False)
        self.toggle_bp.toggled.connect(self._on_bit_perfect_toggled)
        lay.addLayout(_opt_row("Bit Perfect", "EQ·RG·Volume bypass", self.toggle_bp))
        lay.addSpacing(4)

        self.toggle_dither = ToggleSwitch(checked=True)
        self.toggle_dither.toggled.connect(lambda on: self.engine.set_dither_enabled(on))
        lay.addLayout(_opt_row("TPDF Dithering", "Bit depth noise shaping", self.toggle_dither))
        lay.addSpacing(4)

        self.toggle_dop = ToggleSwitch(checked=False)
        self.toggle_dop.toggled.connect(self._on_dop_toggled)
        lay.addLayout(_opt_row("DoP Mode", "DSD over PCM (DAC 지원 필요)", self.toggle_dop))
        lay.addSpacing(6)

        sr_row = QHBoxLayout()
        sr_row.setSpacing(8)
        sr_lbl = QLabel("Sampling Rate")
        sr_lbl.setStyleSheet(f"color:{DARK['text_dim']}; font-size:13px;")
        self.combo_upsample = QComboBox()
        self.combo_upsample.addItems(["No Upsampling", "88.2 kHz", "96 kHz",
                                       "176.4 kHz", "192 kHz", "352.8 kHz", "384 kHz"])
        self.combo_upsample.currentIndexChanged.connect(self._on_upsample_changed)
        sr_row.addWidget(sr_lbl)
        sr_row.addWidget(self.combo_upsample, 1)
        lay.addLayout(sr_row)

        scroll.setWidget(inner)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)  # stretch=1: 미니 버튼 제외한 나머지 공간 전부 차지

        # ── 미니플레이어 토글 버튼 (하단 고정) ──────────────────
        btn_mini = QPushButton("⊟  미니 플레이어")
        btn_mini.setFixedHeight(32)
        btn_mini.setToolTip("미니플레이어 모드로 전환 (단축키: M)")
        btn_mini.setStyleSheet(
            f"QPushButton {{ background:{DARK['panel3']}; color:{DARK['text_muted']}; "
            f"border:none; border-top:1px solid {DARK['border']}; font-size:12px; }}"
            f"QPushButton:hover {{ color:{DARK['text']}; background:{DARK['btn_hover']}; }}")
        btn_mini.clicked.connect(self.toggle_mini_player)
        outer.addWidget(btn_mini)

        return panel

    # ─── 우측 패널 ────────────────────────────────────────────
    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("RightPanel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(1)
        splitter.setContentsMargins(0, 0, 0, 0)

        # ── 플레이리스트 ────────────────────────────────────────
        pl_frame = QWidget()
        pf_lay = QVBoxLayout(pl_frame)
        pf_lay.setContentsMargins(20, 16, 20, 12)
        pf_lay.setSpacing(6)

        # ── 헤더 1행: "Playlist" + 파일 추가 버튼 ───────────────
        pl_header = QHBoxLayout()
        pl_title = QLabel("Playlist")
        pl_title.setStyleSheet(f"color:{DARK['text']}; font-size:15px; font-weight:bold;")
        pl_header.addWidget(pl_title)
        pl_header.addStretch()

        btn_add_files = QPushButton("+ 파일")
        btn_add_files.setFixedHeight(28)
        btn_add_files.setToolTip("오디오 파일 추가")
        btn_add_files.clicked.connect(self._add_files)

        btn_add_folder = QPushButton("+ 폴더")
        btn_add_folder.setFixedHeight(28)
        btn_add_folder.setToolTip("폴더 전체 추가")
        btn_add_folder.clicked.connect(self._add_folder)

        btn_add_sacd = QPushButton("💿 SACD")
        btn_add_sacd.setFixedHeight(28)
        btn_add_sacd.setToolTip("SACD ISO 파일 열기")
        btn_add_sacd.clicked.connect(self._open_sacd_iso)

        btn_upnp = QPushButton("🌐 DLNA")
        btn_upnp.setFixedHeight(28)
        btn_upnp.setToolTip("UPnP/DLNA 미디어 서버 브라우징")
        btn_upnp.clicked.connect(self._open_upnp_browser)

        pl_header.addWidget(btn_add_files)
        pl_header.addWidget(btn_add_folder)
        pl_header.addWidget(btn_add_sacd)
        pl_header.addWidget(btn_upnp)
        pf_lay.addLayout(pl_header)

        # ── 헤더 2행: 현재 재생 트랙 정보 ───────────────────────
        now_playing_box = QWidget()
        now_playing_box.setObjectName("NowPlayingBox")
        now_playing_box.setStyleSheet(
            f"#NowPlayingBox {{ background:{DARK['panel3']}; border-radius:6px; }}")
        np_lay = QVBoxLayout(now_playing_box)
        np_lay.setContentsMargins(12, 8, 12, 8)
        np_lay.setSpacing(2)

        self.lbl_title = MarqueeLabel()
        _title_font = QFont()
        _title_font.setPixelSize(14)
        _title_font.setBold(True)
        self.lbl_title.setFont(_title_font)
        self.lbl_title.setStyleSheet(f"color:{DARK['text']};")
        self.lbl_title.setText("—")
        self.lbl_title.setFixedHeight(22)

        artist_album_row = QHBoxLayout()
        artist_album_row.setSpacing(6)
        artist_album_row.setContentsMargins(0, 0, 0, 0)

        self.lbl_artist = QLabel(" ")
        self.lbl_artist.setStyleSheet(
            f"color:{DARK['accent']}; font-size:12px; font-weight:bold; background:transparent;")
        self.lbl_artist.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_artist.setFixedHeight(18)

        self.lbl_album = QLabel(" ")
        self.lbl_album.setStyleSheet(
            f"color:{DARK['text_dim']}; font-size:12px; background:transparent;")
        self.lbl_album.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_album.setFixedHeight(18)

        artist_album_row.addWidget(self.lbl_artist)
        lbl_sep = QLabel("·")
        lbl_sep.setStyleSheet(f"color:{DARK['text_muted']}; font-size:11px; background:transparent;")
        artist_album_row.addWidget(lbl_sep)
        artist_album_row.addWidget(self.lbl_album, 1)

        np_lay.addWidget(self.lbl_title)
        np_lay.addLayout(artist_album_row)

        pf_lay.addWidget(now_playing_box)

        # 컬럼 헤더
        self.pl_header = PlaylistHeader()
        self.pl_header.sort_requested.connect(self._sort_playlist)
        pf_lay.addWidget(self.pl_header)

        self.playlist = PlaylistWidget()
        self.playlist.files_dropped.connect(self._add_file_list)
        self.playlist.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.playlist.remove_requested.connect(self._remove_track)
        self.playlist.clear_requested.connect(self._clear_playlist)
        # 헤더가 playlist를 직접 참조해 스크롤바 폭 실시간 계산
        self.pl_header.set_playlist(self.playlist)
        self.playlist.verticalScrollBar().rangeChanged.connect(
            lambda mn, mx: self.pl_header.update())
        pf_lay.addWidget(self.playlist, 1)

        self.drop_hint = QLabel(
            "파일, 폴더를 여기에 드래그하거나\n'+ 파일' / '+ 폴더' 버튼을 클릭하세요\n\n"
            "지원 형식: FLAC, WAV, AIFF, MP3, AAC\nDSF, DFF (DSD64/128/256/512)",
            self.playlist)
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.setStyleSheet(
            f"color:{DARK['text_muted']}; font-size:13px; line-height:1.6; background:transparent;")
        self.drop_hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.drop_hint.setGeometry(0, 0, self.playlist.width() or 400, self.playlist.height() or 200)
        self.drop_hint.setVisible(True)
        self.playlist._drop_hint_widget = self.drop_hint

        splitter.addWidget(pl_frame)

        # ── Parametric EQ ────────────────────────────────────
        eq_frame = QWidget()
        eq_lay = QVBoxLayout(eq_frame)
        eq_lay.setContentsMargins(20, 12, 20, 12)
        eq_lay.setSpacing(6)

        eq_header = QHBoxLayout()
        eq_title = QLabel("Parametric EQ")
        eq_title.setStyleSheet(f"color:{DARK['text']}; font-size:15px; font-weight:bold;")
        eq_header.addWidget(eq_title)
        eq_lay.addLayout(eq_header)

        self.eq_panel = EQPanel()
        self.eq_panel.params_changed.connect(self._on_eq_params_changed)
        self.eq_panel.enabled_changed.connect(self._on_eq_enabled_changed)
        eq_lay.addWidget(self.eq_panel)

        splitter.addWidget(eq_frame)
        splitter.setSizes([460, 400])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        lay.addWidget(splitter, 1)
        return panel

    # ─────────────────────────────────────────────
    # 미니플레이어
    # ─────────────────────────────────────────────
    def _build_mini_panel(self) -> QWidget:
        """미니플레이어 패널 — 앨범아트 + 제목 + 재생컨트롤 + 슬라이더."""
        w = QWidget()
        w.setObjectName("MiniPanel")
        w.setStyleSheet(f"#MiniPanel {{ background:{DARK['panel']}; }}")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)

        # ── 앨범아트 (52×52) ──────────────────────────────────
        self.mini_art = QLabel()
        self.mini_art.setFixedSize(52, 52)
        self.mini_art.setStyleSheet(
            f"background:{DARK['panel3']}; border-radius:4px;")
        self.mini_art.setScaledContents(True)
        lay.addWidget(self.mini_art)

        # ── 제목/아티스트 ────────────────────────────────────
        info = QVBoxLayout()
        info.setSpacing(1)
        info.setContentsMargins(0, 0, 0, 0)

        self.mini_title = MarqueeLabel()
        _f = QFont(); _f.setPixelSize(13); _f.setBold(True)
        self.mini_title.setFont(_f)
        self.mini_title.setStyleSheet(f"color:{DARK['text']};")
        self.mini_title.setText("—")
        self.mini_title.setFixedHeight(18)

        self.mini_artist = QLabel(" ")
        self.mini_artist.setStyleSheet(
            f"color:{DARK['text_dim']}; font-size:11px; background:transparent;")
        self.mini_artist.setFixedHeight(15)

        # 미니 슬라이더
        self.mini_seek = QSlider(Qt.Horizontal)
        self.mini_seek.setRange(0, 1000)
        self.mini_seek.setFixedHeight(14)
        self.mini_seek.sliderPressed.connect(self._on_seek_pressed)
        self.mini_seek.sliderReleased.connect(self._on_mini_seek_released)

        info.addWidget(self.mini_title)
        info.addWidget(self.mini_artist)
        info.addWidget(self.mini_seek)
        lay.addLayout(info, 1)

        # ── 재생 컨트롤 버튼 ──────────────────────────────────
        self.mini_btn_prev = TransportButton('prev', size=32)
        self.mini_btn_prev.clicked.connect(self._prev_track)

        self.mini_btn_play = TransportButton('play', size=36, is_primary=True)
        self.mini_btn_play.clicked.connect(self._toggle_play)

        self.mini_btn_next = TransportButton('next', size=32)
        self.mini_btn_next.clicked.connect(self._next_track)

        lay.addWidget(self.mini_btn_prev)
        lay.addWidget(self.mini_btn_play)
        lay.addWidget(self.mini_btn_next)

        # ── 미니→메인 복귀 버튼 ────────────────────────────────
        btn_expand = QPushButton("⤢")
        btn_expand.setFixedSize(28, 28)
        btn_expand.setToolTip("전체 화면으로 돌아가기")
        btn_expand.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{DARK['text_muted']}; "
            f"border:1px solid {DARK['border']}; border-radius:4px; font-size:14px; }}"
            f"QPushButton:hover {{ color:{DARK['text']}; border-color:{DARK['border2']}; }}")
        btn_expand.clicked.connect(self.toggle_mini_player)
        lay.addWidget(btn_expand)

        return w

    def toggle_mini_player(self):
        """미니플레이어 ↔ 메인뷰 전환."""
        if self._is_mini:
            # 메인으로 복귀
            self._stack.setCurrentIndex(0)
            self._is_mini = False
            self.setMinimumSize(920, 600)
            w, h = self._normal_size
            self.resize(w, h)
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        else:
            # 미니로 전환 — 현재 크기 저장
            self._normal_size = (self.width(), self.height())
            self._sync_mini_display()
            self._stack.setCurrentIndex(1)
            self._is_mini = True
            self.setMinimumSize(400, 80)
            self.resize(520, 80)
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.show()

    def _sync_mini_display(self):
        """메인뷰의 현재 상태를 미니플레이어에 동기화."""
        # 앨범아트
        if hasattr(self, 'lbl_cover'):
            pm = self.lbl_cover.pixmap()
            if pm and not pm.isNull():
                self.mini_art.setPixmap(
                    pm.scaled(52, 52, Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation))
        # 제목/아티스트
        if hasattr(self, 'lbl_title'):
            self.mini_title.setText(self.lbl_title._text or "—")
        if hasattr(self, 'lbl_artist'):
            self.mini_artist.setText(self.lbl_artist.text().strip() or " ")
        # 재생 아이콘 동기화
        if hasattr(self, 'btn_play'):
            self.mini_btn_play.set_icon(self.btn_play._icon)
        # 슬라이더 동기화
        if hasattr(self, 'seek_slider'):
            self.mini_seek.setValue(self.seek_slider.value())

    # ─────────────────────────────────────────────
    # 장치 관리
    # ─────────────────────────────────────────────
    @staticmethod
    def _get_macos_default_output_name() -> str:
        """macOS 현재 기본 출력 장치명을 system_profiler로 읽어옴.
        _items 리스트 안에서 coreaudio_default_audio_output_device == 'spaudio_yes' 항목의 _name 반환.
        """
        try:
            import subprocess, json
            result = subprocess.run(
                ['system_profiler', 'SPAudioDataType', '-json'],
                capture_output=True, text=True, timeout=4
            )
            data = json.loads(result.stdout)
            for top in data.get('SPAudioDataType', []):
                for dev in top.get('_items', []):
                    if dev.get('coreaudio_default_audio_output_device') == 'spaudio_yes':
                        return dev.get('_name', '')
        except Exception:
            pass
        return ''

    def _load_devices(self):
        import platform as _platform
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self._devices: List[AudioDevice] = []

        # macOS에서만 system_profiler로 기본 장치명 읽기
        if _platform.system() == 'Darwin':
            default_name = self._get_macos_default_output_name()
        else:
            default_name = ''

        default_label = f"🔊  {default_name}" if default_name else "🔊  시스템 기본"
        self.device_combo.addItem(default_label)
        self._devices.append(None)

        devices = AudioEngine.get_output_devices()

        for dev in devices:
            # 기본 출력 장치와 같은 이름이면 목록에서 제외 (중복 방지, macOS만)
            if default_name and dev.name == default_name:
                continue
            dac_keywords = ('dac', 'usb', 'external', 'pro', 'focusrite',
                            'topping', 'schiit', 'chord', 'fiio', 'smsl',
                            'realtek', 'speakers', 'headphone')
            icon = "🎧" if any(k in dev.name.lower() for k in dac_keywords) else "🔈"
            self.device_combo.addItem(f"{icon}  {dev.display_name()}")
            self._devices.append(dev)

        self.device_combo.setCurrentIndex(0)
        self.device_combo.blockSignals(False)

    def _on_device_changed(self, idx: int):
        if idx < 0 or idx >= len(self._devices):
            return
        dev = self._devices[idx]
        device_index = dev.index if dev else None
        device_name = dev.name if dev else ''
        self.engine.set_output_device(device_index, device_name)
        self._save_settings()  # 장치 변경 시 즉시 저장

    # ─────────────────────────────────────────────
    # 파일 추가
    # ─────────────────────────────────────────────
    def _add_files(self):
        exts = ' '.join(f'*{e}' for e in sorted(AudioEngine.SUPPORTED_FORMATS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "오디오 파일 추가", "",
            f"오디오 파일 ({exts});;모든 파일 (*.*)"
        )
        if paths:
            self._add_file_list(paths)

    def _open_sacd_iso(self):
        """SACD ISO 파일 열기 — 트랙 목록 다이얼로그 표시"""
        path, _ = QFileDialog.getOpenFileName(
            self, "SACD ISO 파일 열기", "",
            "SACD ISO (*.iso);;모든 파일 (*.*)"
        )
        if not path:
            return
        self._add_sacd_iso_tracks(path, show_dialog=True)

    def _add_sacd_iso_tracks(self, path: str, show_dialog: bool = False):
        """ISO 파일에서 트랙을 파싱해 플레이리스트에 추가.
        show_dialog=True면 트랙 선택 다이얼로그, False면 전체 자동 추가."""
        decoder = SACDDecoder()
        if not decoder.is_sacd_file(path):
            if show_dialog:
                QMessageBox.warning(self, "오류", "SACD ISO 파일이 아닙니다.\n파일 구조를 확인하세요.")
            return

        tracks = decoder.get_track_list(path)
        if not tracks:
            if show_dialog:
                QMessageBox.warning(self, "오류", "SACD ISO에서 트랙을 찾을 수 없습니다.")
            return

        from PyQt5.QtWidgets import QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QVBoxLayout

        if show_dialog:
            # 트랙 선택 다이얼로그
            dlg = QDialog(self)
            dlg.setWindowTitle(f"SACD 트랙 선택 — {Path(path).name}")
            dlg.resize(420, 360)
            dlg.setStyleSheet(self.styleSheet())
            lay = QVBoxLayout(dlg)
            lw  = QListWidget()
            for t in tracks:
                dur = int(t.get('duration', 0))
                m, s = divmod(dur, 60)
                lw.addItem(QListWidgetItem(f"  {t['index']+1:02d}.  {t['title']}   {m}:{s:02d}"))
            lw.setSelectionMode(QListWidget.MultiSelection)
            for i in range(lw.count()):
                lw.item(i).setSelected(True)
            lay.addWidget(lw)
            btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            lay.addWidget(btns)

            if dlg.exec_() != QDialog.Accepted:
                return

            selected_rows = [lw.row(i) for i in lw.selectedItems()]
            selected_tracks = [tracks[r] for r in selected_rows]
        else:
            # 다이얼로그 없이 전체 트랙 추가
            selected_tracks = tracks

        # 이미 추가된 트랙 집합 (ISO 파일 경로 + 트랙 인덱스로 구별)
        existing = set()
        for i in range(self.playlist.count()):
            ti = self._track_at(i)
            if ti:
                sti = ti._sacd_track_info
                track_idx = sti['index'] if isinstance(sti, dict) and 'index' in sti else -1
                existing.add((ti.filepath, track_idx))

        for t in selected_tracks:
            key = (path, t['index'])
            if key in existing:
                continue
            track = TrackItem(path)
            track.title    = t['title']
            track.artist   = ''
            track.album    = t.get('album', '')
            track.duration = t.get('duration', 0)
            track._sacd_track_info = t

            item = QListWidgetItem()
            item.setData(Qt.UserRole + 1, track)
            self._update_list_item(item, track)
            self.playlist.addItem(item)
            existing.add(key)

    def _open_upnp_browser(self):
        """UPnP/DLNA 미디어 서버 브라우저 열기"""
        dlg = UPnPDialog(self)
        dlg.track_selected.connect(self._on_upnp_track_selected)
        dlg.exec_()

    def _on_upnp_track_selected(self, url: str, title: str, artist: str, album: str, duration: float):
        """UPnP에서 선택한 트랙을 플레이리스트에 추가"""
        # URL을 filepath처럼 사용 (http:// 스트림)
        track = TrackItem(url)
        track.title    = title
        track.artist   = artist
        track.album    = album
        track.duration = duration
        track._is_upnp = True

        item = QListWidgetItem()
        item.setData(Qt.UserRole + 1, track)
        self._update_list_item(item, track)
        self.playlist.addItem(item)

    def _add_folder(self):
        dirpath = QFileDialog.getExistingDirectory(self, "폴더 추가", "")
        if dirpath:
            files = []
            for root, dirs, filenames in os.walk(dirpath):
                dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
                for fname in sorted(filenames):
                    if fname.startswith('.') or fname.startswith('._'):
                        continue
                    if Path(fname).suffix.lower() in AudioEngine.SUPPORTED_FORMATS:
                        files.append(os.path.join(root, fname))
            if files:
                self._add_file_list(files)
            else:
                QMessageBox.information(self, "알림", "폴더에서 지원 오디오 파일을 찾을 수 없습니다.")

    def _track_at(self, row: int) -> Optional[TrackItem]:
        """플레이리스트 row에서 TrackItem 반환"""
        item = self.playlist.item(row)
        if item is None:
            return None
        return item.data(Qt.UserRole + 1)

    def _track_count(self) -> int:
        return self.playlist.count()

    def _add_file_list(self, paths: list):
        # 이미 추가된 경로 집합
        existing = set()
        for i in range(self.playlist.count()):
            t = self._track_at(i)
            if t:
                existing.add(t.filepath)

        new_paths = [p for p in paths if p not in existing]
        if not new_paths:
            return

        # 배치로 추가 — QApplication.processEvents()로 UI 블로킹 방지
        from PyQt5.QtWidgets import QApplication
        for i, path in enumerate(new_paths):
            # ISO 파일은 트랙 목록으로 펼쳐서 추가 (다이얼로그 없이 전체 자동 추가)
            if path.lower().endswith('.iso'):
                self._add_sacd_iso_tracks(path, show_dialog=False)
                existing.add(path)
                continue

            track = TrackItem(path)
            existing.add(path)
            item = QListWidgetItem()
            item.setData(Qt.UserRole + 1, track)
            self._update_list_item(item, track)
            self.playlist.addItem(item)
            # 10개마다 UI 갱신 — 마지막 아이템도 확실히 렌더링
            if i % 10 == 9:
                QApplication.processEvents()

        # 추가 완료 후 한 번 더 갱신
        QApplication.processEvents()
        self.drop_hint.setVisible(self.playlist.count() == 0)

        # 첫 파일 추가 시 자동 선택
        if self.current_index < 0 and self.playlist.count() > 0:
            self.playlist.setCurrentRow(0)

    def _remove_track(self, row: int):
        """트랙 제거 — current_index 보정"""
        self.playlist.takeItem(row)
        if self.current_index == row:
            self.engine.stop()
            self.current_index = -1
        elif self.current_index > row:
            self.current_index -= 1
        self.drop_hint.setVisible(self.playlist.count() == 0)

    def _clear_playlist(self):
        """플레이리스트 전체 지우기"""
        self.engine.stop()
        self.playlist.clear()
        self.current_index = -1
        self.drop_hint.setVisible(True)

    def _sort_playlist(self, key: str, ascending: bool):
        """헤더 클릭 시 트랙 정렬. key: 'title'|'artist'|'format'|'dur'"""
        count = self.playlist.count()
        if count == 0:
            return

        # 현재 재생 중인 트랙 기억
        playing_path = None
        if 0 <= self.current_index < count:
            t = self._track_at(self.current_index)
            if t:
                playing_path = t.filepath

        # 모든 아이템 수집
        items_data = []
        for i in range(count):
            item = self.playlist.item(i)
            track = self._track_at(i)
            items_data.append((track, item.toolTip()))

        # 정렬 키 함수
        def sort_key(td):
            track = td[0]
            if track is None:
                return ''
            if key == 'title':
                return (track.title or '').lower()
            elif key == 'artist':
                return (track.artist or '').lower()
            elif key == 'format':
                return track.format.lower()
            elif key == 'dur':
                return track.duration
            return ''

        items_data.sort(key=sort_key, reverse=not ascending)

        # 리스트 재구성
        self.playlist.clear()
        from PyQt5.QtWidgets import QApplication
        for i, (track, _) in enumerate(items_data):
            if track is None:
                continue
            item = QListWidgetItem()
            self._update_list_item(item, track)
            self.playlist.addItem(item)
            if i % 20 == 19:
                QApplication.processEvents()

        # 재생 중이던 곡 위치 복원
        self.current_index = -1
        if playing_path:
            for i in range(self.playlist.count()):
                t = self._track_at(i)
                if t and t.filepath == playing_path:
                    self.current_index = i
                    self.playlist.setCurrentRow(i)
                    break
        self.playlist.set_playing_row(self.current_index)

        # 헤더 정렬 표시 업데이트
        self.pl_header.set_sort(key, ascending)

    def _update_list_item(self, item: QListWidgetItem, track: TrackItem,
                          missing: bool = False):
        """TrackItem을 아이템에 연결 (렌더링은 PlaylistDelegate가 담당)."""
        item.setData(Qt.UserRole,     track.filepath)
        item.setData(Qt.UserRole + 1, track)
        item.setToolTip(track.filepath if not missing else f"파일 없음: {track.filepath}")
        # 델리게이트에서 그리므로 setText/setForeground 불필요 — 빈 텍스트만 설정
        item.setText('')

    # ─────────────────────────────────────────────
    # 재생 제어
    # ─────────────────────────────────────────────
    def _on_item_double_clicked(self, item: QListWidgetItem):
        row = self.playlist.row(item)
        self._load_and_play(row)

    def _load_and_play(self, index: int, _skip_set: set = None):
        if index < 0 or index >= self._track_count():
            return
        track = self._track_at(index)
        if track is None:
            return
        # 파일 없는 곡이면 skip — 다음 유효한 곡 탐색
        if not os.path.exists(track.filepath):
            if _skip_set is None:
                _skip_set = set()
            _skip_set.add(index)
            total = self._track_count()
            # 순방향으로 다음 유효한 인덱스 탐색
            for offset in range(1, total):
                nxt = (index + offset) % total
                if nxt in _skip_set:
                    continue
                t = self._track_at(nxt)
                if t and os.path.exists(t.filepath):
                    self._load_and_play(nxt, _skip_set)
                    return
            return  # 유효한 곡이 하나도 없음
        self.current_index = index
        self.playlist.setCurrentRow(index)
        self.playlist.set_playing_row(index)      # 델리게이트에 현재 재생 행 전달
        self._last_finished_index = -1  # 새 곡 로드 시 finished 가드 리셋

        # 로딩 중 표시 (lbl_artist/album은 그대로 — 레이아웃 흔들림 방지)
        self.lbl_title.setText(track.title or "Loading...")
        self.btn_play.set_icon("loading")
        self.btn_play.setEnabled(False)

        # 백그라운드 로드
        if self._loader and self._loader.isRunning():
            self._loader.terminate()
        sacd_info = getattr(track, '_sacd_track_info', None)
        self._loader = TrackLoader(self.engine, track.filepath, sacd_track_info=sacd_info)
        self._loader.loaded.connect(self._on_track_loaded)
        self._loader.error.connect(self._on_error)
        self._loader.start()

    def _on_track_loaded(self, info: dict):
        self.current_info = info
        self.btn_play.setEnabled(True)
        self._update_info_display(info)
        self.engine.play()
        self.btn_play.set_icon("pause")
        self._highlight_current()

    def _toggle_play(self):
        if self._loader and self._loader.isRunning():
            return
        if self.current_index < 0:
            if self._track_count() > 0:
                self._load_and_play(0)
            return

        if self.engine.is_playing:
            self.engine.pause()
            self.btn_play.set_icon("play")
        elif self.engine.is_paused:
            self.engine.resume()
            self.btn_play.set_icon("pause")
        else:
            self._load_and_play(self.current_index)

    def _stop(self):
        self.engine.stop()
        self.btn_play.set_icon("play")
        self.seek_slider.setValue(0)
        self.lbl_pos.setText("0:00")

    # ─────────────────────────────────────────────
    # 셔플 / 반복 버튼 핸들러
    # ─────────────────────────────────────────────
    _BTN_OFF  = (f"QPushButton {{ background:transparent; color:{DARK['text_muted']}; "  # 하위호환용
                 f"border:1px solid {DARK['border']}; border-radius:16px; font-size:14px; font-family:'Arial','Helvetica',sans-serif; }}")
    _BTN_ON   = (f"QPushButton {{ background:#1e1a10; color:{DARK['accent']}; "
                 f"border:1px solid {DARK['accent']}; border-radius:16px; font-size:14px; font-family:'Arial','Helvetica',sans-serif; }}")
    _BTN_ONE  = (f"QPushButton {{ background:#1a1030; color:#c97aff; "
                 f"border:1px solid #c97aff; border-radius:16px; font-size:14px; font-family:'Arial','Helvetica',sans-serif; }}")

    def _update_shuffle_style(self):
        self.btn_shuffle.setActive(self._shuffle)

    def _update_repeat_style(self):
        self.btn_repeat.setMode(self._repeat_mode)

    def _on_shuffle_clicked(self):
        self._shuffle = not self._shuffle
        self._update_shuffle_style()

    def _on_repeat_clicked(self):
        self._repeat_mode = (self._repeat_mode + 1) % 3
        self._update_repeat_style()

    def _prev_track(self):
        if self.current_index > 0:
            self._load_and_play(self.current_index - 1)

    def _next_track(self):
        total = self._track_count()
        if total == 0:
            return
        if self._shuffle:
            idx = self.current_index
            candidates = [i for i in range(total) if i != idx] if total > 1 else [0]
            self._load_and_play(random.choice(candidates))
        elif self.current_index < total - 1:
            self._load_and_play(self.current_index + 1)

    def _on_playback_finished(self):
        # 로딩 중이면 차단 (사용자가 다른 곡 클릭 중)
        if self._loader and self._loader.isRunning():
            return
        # 같은 인덱스에서 이미 finished 처리했으면 중복 차단
        # (seek 여러 번 후 _fire_finished가 여러 번 오는 경우)
        if self._last_finished_index == self.current_index:
            return
        self._last_finished_index = self.current_index

        self.btn_play.set_icon("play")
        # 버퍼 크기를 100ms로 줄였으므로 지연 50ms로 단축 (갭리스 개선)
        QTimer.singleShot(50, self._auto_next_track)

    def _auto_next_track(self):
        if self._loader and self._loader.isRunning():
            return
        total = self._track_count()
        if total == 0:
            return

        # 한곡 반복
        if self._repeat_mode == 1:
            self._load_and_play(self.current_index)
            return

        # 셔플
        if self._shuffle:
            candidates = [i for i in range(total) if i != self.current_index] if total > 1 else [0]
            self._load_and_play(random.choice(candidates))
            return

        # 전체 반복 — 마지막 곡이면 처음으로
        if self._repeat_mode == 2:
            nxt = (self.current_index + 1) % total
            self._load_and_play(nxt)
            return

        # 기본 — 다음 곡 없으면 정지
        if self.current_index < total - 1:
            self._load_and_play(self.current_index + 1)
        else:
            self.seek_slider.setValue(0)

    # ─────────────────────────────────────────────
    # 위치 업데이트
    # ─────────────────────────────────────────────
    def _on_position_changed(self, pos: float, dur: float):
        if self._seeking:
            return
        if dur > 0:
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(int(pos / dur * 1000))
            self.seek_slider.blockSignals(False)
        self.lbl_pos.setText(self._fmt_time(pos))
        self.lbl_dur.setText(self._fmt_time(dur))

    def _update_position_display(self):
        """버튼 아이콘 + CD 회전 동기화"""
        if self.engine.is_playing:
            if self.btn_play._icon != "pause":
                self.btn_play.set_icon("pause")
                if self._is_mini:
                    self.mini_btn_play.set_icon("pause")
            self.cd_widget.set_spinning(True)
        else:
            if not self.engine.is_paused:
                if self.btn_play._icon == "pause":
                    self.btn_play.set_icon("play")
                    if self._is_mini:
                        self.mini_btn_play.set_icon("play")
            self.cd_widget.set_spinning(False)
        # 미니 슬라이더 동기화
        if self._is_mini and not self._seeking:
            self.mini_seek.setValue(self.seek_slider.value())

    def _on_seek_pressed(self):
        self._seeking = True

    def _on_seek_released(self):
        dur = self.engine.duration
        if dur > 0:
            pos = self.seek_slider.value() / 1000.0 * dur
            self.engine.seek(pos)
        self._seeking = False

    def _on_mini_seek_released(self):
        dur = self.engine.duration
        if dur > 0:
            pos = self.mini_seek.value() / 1000.0 * dur
            self.engine.seek(pos)
            self.seek_slider.setValue(self.mini_seek.value())
        self._seeking = False

    def _on_volume_changed(self, value: int):
        vol = value / 100.0
        self.engine.set_volume(vol)
        self.lbl_vol.setText(f"{value}%")

    # ─────────────────────────────────────────────
    # 정보 표시 업데이트
    # ─────────────────────────────────────────────
    def _update_info_display(self, info: dict):
        title  = info.get('title', '') or Path(info.get('filepath', '')).stem
        artist = info.get('artist', '')
        album  = info.get('album', '')
        fmt    = info.get('format', '?')
        sr     = info.get('sample_rate', 0)
        ch     = info.get('channels', 0)
        dur    = info.get('duration', 0.0)
        dsd_r  = info.get('dsd_rate', '')
        bit    = info.get('bit_depth', info.get('bits_per_sample', ''))

        self.lbl_title.setText(title or '제목 없음')
        self.lbl_artist.setText(artist)
        self.lbl_album.setText(album)

        # 앨범아트 → 있으면 lbl_cover 표시, 없으면 CD 애니메이션
        cover_data = info.get('cover_data', None)
        if cover_data:
            px = QPixmap()
            if px.loadFromData(cover_data):
                # 440×440 꽉 채우기 (중앙 크롭)
                ART = 440
                px = px.scaled(ART, ART, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                if px.width() > ART or px.height() > ART:
                    x = (px.width()  - ART) // 2
                    y = (px.height() - ART) // 2
                    px = px.copy(x, y, ART, ART)
                self.lbl_cover.setPixmap(px)
                self.art_stack.setCurrentIndex(1)
            else:
                self.art_stack.setCurrentIndex(0)
        else:
            self.art_stack.setCurrentIndex(0)

        ch_str = {1: "Mono", 2: "Stereo", 4: "4ch", 6: "5.1ch", 8: "7.1ch"}.get(ch, f"{ch}ch")

        # 포맷 뱃지 — font-size 항상 11px 고정 (크기 변화로 인한 layout shift 방지)
        _BADGE = "font-size:11px; font-weight:bold; font-family:monospace; border-radius:3px; padding:1px 6px;"
        if dsd_r:
            self.lbl_format.setText(dsd_r)
            self.lbl_format.setStyleSheet(
                f"color:{DARK['dsd']}; {_BADGE} background:#1a0a00; border:1px solid #4a2000;")
        else:
            self.lbl_format.setText(fmt)
            self.lbl_format.setStyleSheet(
                f"color:{DARK['accent']}; {_BADGE} background:#0a1828; border:1px solid #1a3050;")
        self.lbl_detail.setStyleSheet(
            f"color:{DARK['text_muted']}; font-size:11px; font-family:monospace;")

        # DSD 실제 샘플레이트 (2.8224MHz 등) vs PCM 변환 SR (44,100Hz)
        dsd_sr = info.get('dsd_sample_rate', 0)  # 원본 DSD SR (DSF/DFF/SACD)
        source = info.get('source', '')           # 'SACD ISO' 등

        # 숨긴 더미 레이블도 값 유지 (혹시 다른 곳에서 참조 시)
        if dsd_sr:
            self.lbl_samplerate.setText(f"{dsd_sr/1e6:.4f} MHz")
        else:
            self.lbl_samplerate.setText(f"{sr:,} Hz" if sr else "--")
        self.lbl_bitdepth.setText(str(bit) if bit else "--")
        self.lbl_channels.setText(ch_str)

        # bit_depth 정규화: "Signed 24 bit PCM" → "24-bit" 등
        import re as _re
        bit_str = ""
        if bit and not dsd_sr:   # DSD는 1-bit이라 별도 표시 불필요
            m = _re.search(r'(\d+)\s*bit', str(bit), _re.IGNORECASE)
            bit_str = f"{m.group(1)}-bit" if m else str(bit)

        # 상세 스펙 한 줄
        # DSD: "2.8224 MHz · 1 · Stereo · 4:27 · 1886.6 MB · 5,644 kbps | SACD ISO"
        # PCM: "96,000 Hz · 24-bit · Stereo · 4:27 · 120.3 MB · 4,608 kbps"
        parts = []
        if dsd_sr:
            parts.append(f"{dsd_sr/1e6:.4f} MHz")
        elif sr:
            parts.append(f"{sr:,} Hz")
        if bit_str:  parts.append(bit_str)
        if ch:       parts.append(ch_str)
        if dur:      parts.append(self._fmt_time(dur))
        filepath = info.get('filepath', '')
        if filepath and os.path.exists(filepath):
            size_bytes = os.path.getsize(filepath)
            size_mb = size_bytes / 1024 / 1024
            parts.append(f"{size_mb:.1f} MB")
            if dur and dur > 0:
                # DSD 비트레이트: dsd_sr × channels × 1bit
                if dsd_sr and ch:
                    kbps_dsd = (dsd_sr * ch) / 1000
                    parts.append(f"{kbps_dsd:,.0f} kbps")
                else:
                    kbps = (size_bytes * 8) / dur / 1000
                    parts.append(f"{kbps:.0f} kbps")
        detail_str = "  ·  ".join(parts)
        if source:
            detail_str += f"  |  {source}"
        self.lbl_detail.setText(detail_str)

        # ReplayGain 정보 표시
        rg_src = info.get('rg_source', '')
        if rg_src:
            self.lbl_rg_info.setText(rg_src)
            self.lbl_rg_info.setStyleSheet(
                f"color:{DARK['accent']}; font-size:11px; font-family:monospace;")
        else:
            self.lbl_rg_info.setText("—")
            self.lbl_rg_info.setStyleSheet(
                "color:transparent; font-size:11px; font-family:monospace;")

        self.lbl_dur.setText(self._fmt_time(dur))

        # ── 미니플레이어 동기화 ──────────────────────────────────
        self.mini_title.setText(title or '제목 없음')
        self.mini_artist.setText(artist if artist else (album if album else ' '))
        # 앨범아트
        cover_data = info.get('cover_data', None)
        if cover_data:
            px2 = QPixmap()
            if px2.loadFromData(cover_data):
                self.mini_art.setPixmap(
                    px2.scaled(52, 52, Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation))
        else:
            self.mini_art.setPixmap(QPixmap())

    def _highlight_current(self):
        """현재 재생 중인 트랙 강조 — 델리게이트가 색상을 처리하므로 repaint만."""
        self.playlist.set_playing_row(self.current_index)
        self.playlist.viewport().update()

    def _on_error(self, msg: str):
        self.btn_play.set_icon("play")
        self.btn_play.setEnabled(True)
        self.lbl_title.setText(f"오류: {msg}")
        self.lbl_title.setStyleSheet(f"color:{DARK['error']};")

    # ─────────────────────────────────────────────
    # 유틸
    # ─────────────────────────────────────────────
    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 0:
            return "0:00"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    # ─────────────────────────────────────────────
    # Windows 타이틀바 다크 모드
    # ─────────────────────────────────────────────
    def _apply_dark_titlebar(self):
        """Windows 10/11: DWM API로 타이틀바 다크 모드 + 아이콘 제거"""
        import sys
        if sys.platform != 'win32':
            return
        try:
            import ctypes
            import ctypes.wintypes

            hwnd = int(self.winId())

            # ── 1. 다크 타이틀바 ──────────────────────────────────
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            value = ctypes.c_int(1)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value), ctypes.sizeof(value)
            )
            if result != 0:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 19, ctypes.byref(value), ctypes.sizeof(value)
                )

            # ── 2. 타이틀바 아이콘 제거 ───────────────────────────
            # WinAPI: WM_SETICON으로 빈 아이콘 설정
            WM_SETICON   = 0x0080
            ICON_SMALL   = 0
            ICON_BIG     = 1
            GWL_STYLE    = -16
            WS_SYSMENU   = 0x00080000
            # 현재 스타일 읽기 후 SYSMENU 제거 → 아이콘+시스템 메뉴 숨김
            # (최소화/최대화/닫기 버튼은 유지됨)
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            # WS_SYSMENU 제거 시 닫기 버튼도 사라지므로 아이콘만 빈 값으로 대체
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, 0)
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, 0)

            # ── 3. 타이틀 폰트 모던하게 (Segoe UI Light) ──────────
            # Windows 타이틀바 폰트는 OS 설정이라 앱에서 직접 변경 불가
            # 대신 타이틀 텍스트를 심플하게 변경
            self.setWindowTitle("니콘 친게 HiFi Player")

        except Exception:
            pass

    # ─────────────────────────────────────────────
    # 키보드 단축키
    # ─────────────────────────────────────────────
    def eventFilter(self, obj, event):
        """QApplication 글로벌 이벤트 필터 — 포커스 위치 무관하게 키보드 단축키 처리"""
        if event.type() == QEvent.KeyPress:
            key = event.key()
            # 텍스트 입력 위젯(QLineEdit 등)에서는 가로채지 않음
            from PyQt5.QtWidgets import QLineEdit, QTextEdit
            focused = QApplication.focusWidget()
            if isinstance(focused, (QLineEdit, QTextEdit)):
                return super().eventFilter(obj, event)

            if key == Qt.Key_Up:
                new_val = min(100, self.vol_slider.value() + 5)
                self.vol_slider.setValue(new_val)
                return True
            elif key == Qt.Key_Down:
                new_val = max(0, self.vol_slider.value() - 5)
                self.vol_slider.setValue(new_val)
                return True
            elif key == Qt.Key_Space:
                self._toggle_play()
                return True
            elif key == Qt.Key_Left:
                self._prev_track()
                return True
            elif key == Qt.Key_Right:
                self._next_track()
                return True
            elif key == Qt.Key_M:
                self.toggle_mini_player()
                return True
            elif key in (Qt.Key_Delete, Qt.Key_Backspace):
                row = self.playlist.currentRow()
                if row >= 0:
                    self._remove_track(row)
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        # eventFilter가 글로벌로 처리하므로 여기서는 기본 동작만
        super().keyPressEvent(event)

    # ─────────────────────────────────────────────
    # 설정 저장/불러오기
    # ─────────────────────────────────────────────
    # ─────────────────────────────────────────────
    # HiFi 출력 품질 콜백
    # ─────────────────────────────────────────────
    def _on_rg_toggled(self, on: bool):
        self.engine.set_rg_enabled(on)

    def _on_dop_toggled(self, on: bool):
        """DoP (DSD over PCM) 모드 전환"""
        self.engine.set_dop_mode(on)
        if on:
            from PyQt5.QtWidgets import QMessageBox
            msg = QMessageBox(self)
            msg.setWindowTitle("DoP 모드 활성화")
            msg.setText(
                "DoP 모드가 활성화되었습니다.\n\n"
                "⚠️  DAC가 DoP를 지원해야 정상 재생됩니다.\n"
                "지원하지 않는 DAC에서는 심한 소음이 발생합니다.\n\n"
                "DoP 지원 DAC 예: iFi, Chord, Schiit, Topping D90SE 등\n"
                "Scarlett 오디오 인터페이스는 DoP 미지원입니다."
            )
            msg.setIcon(QMessageBox.Warning)
            msg.exec_()
        # 현재 DSD 파일 재생 중이면 즉시 재로드하여 모드 전환 반영
        if self.current_index >= 0:
            track = self._track_at(self.current_index)
            if track and hasattr(track, 'is_dsd') and track.is_dsd:
                was_playing = (self.engine._state == 'playing')
                pos = self.engine.current_position
                self._start_track(self.current_index)
                if was_playing:
                    self.engine.seek(pos)

    def _on_bit_perfect_toggled(self, on: bool):
        self.engine.set_bit_perfect(on)
        # 비트퍼펙트 ON 시 EQ·RG·디더 컨트롤 비활성화 (시각적 피드백)
        self.eq_panel.setEnabled(not on)
        self.toggle_rg.setEnabled(not on)
        self.toggle_dither.setEnabled(not on)
        self.combo_upsample.setEnabled(not on)
        # 볼륨 슬라이더: 비트퍼펙트 ON 시 비활성화 + 툴팁 안내
        self.vol_slider.setEnabled(not on)
        if on:
            self.vol_slider.setToolTip("비트퍼펙트 ON — macOS 시스템 볼륨(⌥F11/F12) 또는 DAC 볼륨으로 조절")
            self.lbl_vol.setText("BIT")
            self.lbl_vol.setStyleSheet(f"color:{DARK['dsd']};font-size:10px;font-weight:bold;")
            self.lbl_rg_info.setText("BYPASS")
            self.lbl_rg_info.setStyleSheet(f"color:{DARK['dsd']};font-size:11px;font-weight:bold;font-family:monospace;")
        else:
            self.vol_slider.setToolTip("볼륨")
            v = self.vol_slider.value()
            self.lbl_vol.setText(f"{v}%")
            self.lbl_vol.setStyleSheet(f"color:{DARK['text_dim']};font-size:11px;font-family:monospace;")
            self.lbl_rg_info.setStyleSheet(f"color:{DARK['accent']};font-size:11px;font-family:monospace;")

    _UPSAMPLE_SR = {0: 0, 1: 88200, 2: 96000, 3: 176400, 4: 192000, 5: 352800, 6: 384000}

    def _on_upsample_changed(self, idx: int):
        sr = self._UPSAMPLE_SR.get(idx, 0)
        self.engine.set_fixed_output_sr(sr)
        # 현재 로드된 파일이 있으면 재로드 필요 (업샘플링은 로드 시 적용)
        if sr > 0 and self.current_index >= 0:
            track = self._track_at(self.current_index)
            if track and os.path.exists(track.filepath):
                was_playing = self.engine.is_playing
                self._load_and_play(self.current_index)
                if not was_playing:
                    self.engine.pause()

    # ─────────────────────────────────────────────
    # EQ 콜백
    # ─────────────────────────────────────────────
    def _on_eq_enabled_changed(self, enabled: bool):
        self.engine.set_eq_enabled(enabled)
        if enabled:
            self.engine.set_eq_params(self.eq_panel.get_params())

    def _on_eq_params_changed(self, params: list):
        self.engine.set_eq_params(params)
        # 활성화 상태가 아니면 자동 ON
        if not self.eq_panel.get_enabled():
            pass  # 슬라이더 조작해도 OFF면 적용 안 함 (의도적)

    # ─────────────────────────────────────────────
    # 설정 저장/불러오기
    # ─────────────────────────────────────────────
    def _load_settings(self):
        try:
            with open(self.SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.vol_slider.setValue(data.get('volume', 80))
            # EQ 복원
            eq_enabled = data.get('eq_enabled', False)
            eq_gains   = data.get('eq_gains',  [0.0] * 8)
            eq_freqs   = data.get('eq_freqs',  None)
            eq_qs      = data.get('eq_qs',     None)
            eq_preset  = data.get('eq_preset', 'Flat')
            raw_up = data.get('user_presets', {})
            user_presets = {}
            for k, v in raw_up.items():
                if v:
                    user_presets[int(k)] = (v['name'], v['params'])
            self.eq_panel.set_state(eq_enabled, eq_gains, eq_preset,
                                    freqs=eq_freqs, qs=eq_qs,
                                    user_presets=user_presets)
            if eq_enabled:
                self.engine.set_eq_enabled(True)
                self.engine.set_eq_params(self.eq_panel.get_params())
            # HiFi 품질 옵션 복원
            rg_on      = data.get('rg_enabled', True)
            bp_on      = data.get('bit_perfect', False)
            dither_on  = data.get('dither', True)
            ups_idx    = data.get('upsample_idx', 0)
            dop_on     = data.get('dop_mode', False)
            self.toggle_rg.setChecked(rg_on)
            self.engine.set_rg_enabled(rg_on)
            self.toggle_bp.setChecked(bp_on)
            self.engine.set_bit_perfect(bp_on)
            self.toggle_dither.setChecked(dither_on)
            self.engine.set_dither_enabled(dither_on)
            self.combo_upsample.setCurrentIndex(ups_idx)
            self.engine.set_fixed_output_sr(self._UPSAMPLE_SR.get(ups_idx, 0))
            self.toggle_dop.setChecked(dop_on)
            self.engine.set_dop_mode(dop_on)
            if bp_on:
                self.eq_panel.setEnabled(False)
                self.toggle_rg.setEnabled(False)
                self.toggle_dither.setEnabled(False)
                self.combo_upsample.setEnabled(False)
            # 출력 장치 복원
            saved_dev_name = data.get('output_device_name', '')
            if saved_dev_name:
                for i, dev in enumerate(self._devices):
                    if dev and dev.name == saved_dev_name:
                        self.device_combo.blockSignals(True)
                        self.device_combo.setCurrentIndex(i)
                        self.device_combo.blockSignals(False)
                        self.engine.set_output_device(dev.index, dev.name)
                        break
            # 플레이리스트 복원
            playlist_paths = data.get('playlist', [])
            saved_index    = data.get('current_index', -1)
            if playlist_paths:
                for path in playlist_paths:
                    track   = TrackItem(path)
                    item    = QListWidgetItem()
                    item.setData(Qt.UserRole + 1, track)
                    missing = not os.path.exists(path)
                    self._update_list_item(item, track, missing=missing)
                    self.playlist.addItem(item)
                self.drop_hint.setVisible(False)
                # 마지막 재생 위치 선택 (재생은 안 함)
                if 0 <= saved_index < self.playlist.count():
                    self.playlist.setCurrentRow(saved_index)
                    self.current_index = saved_index
                    # 정보 패널 기본값 표시 (재생 없이)
                    track = self._track_at(saved_index)
                    if track and os.path.exists(track.filepath):
                        self.lbl_title.setText(track.title or Path(track.filepath).stem)
                        self.lbl_artist.setText(track.artist)
                        self.lbl_album.setText(track.album)
                else:
                    self.playlist.setCurrentRow(0)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    def _save_settings(self):
        try:
            params = self.eq_panel.get_params()
            gains  = [p[2] for p in params]
            freqs  = [p[1] for p in params]
            qs     = [p[3] for p in params]
            # 사용자 프리셋 직렬화 — _user_presets[slot] = (name, params_list) 또는 None
            up_serial = {}
            for slot, v in self.eq_panel._user_presets.items():
                if v:
                    name, pp = v
                    up_serial[str(slot)] = {
                        'name':   name,
                        'params': [list(t) for t in pp],
                    }
                else:
                    up_serial[str(slot)] = None
            # 플레이리스트 경로 저장
            playlist_paths = []
            for i in range(self.playlist.count()):
                t = self._track_at(i)
                if t:
                    playlist_paths.append(t.filepath)
            # 현재 선택된 출력 장치 이름 저장
            cur_dev_idx = self.device_combo.currentIndex()
            cur_dev = self._devices[cur_dev_idx] if 0 <= cur_dev_idx < len(self._devices) else None
            saved_device_name = cur_dev.name if cur_dev else ''

            data = {
                'volume':         self.vol_slider.value(),
                'eq_enabled':     self.eq_panel.get_enabled(),
                'eq_gains':       gains,
                'eq_freqs':       freqs,
                'eq_qs':          qs,
                'eq_preset':      self.eq_panel.get_preset(),
                'user_presets':   up_serial,
                'playlist':       playlist_paths,
                'current_index':  self.current_index,
                # HiFi 품질 옵션
                'bit_perfect':    self.toggle_bp.isChecked(),
                'dither':         self.toggle_dither.isChecked(),
                'upsample_idx':   self.combo_upsample.currentIndex(),
                'rg_enabled':     self.toggle_rg.isChecked(),
                'dop_mode':       self.toggle_dop.isChecked(),
                # 출력 장치
                'output_device_name': saved_device_name,
            }
            with open(self.SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            import traceback
            traceback.print_exc()  # 터미널에 오류 출력 (디버깅용)

    def closeEvent(self, event):
        self._save_settings()
        self.engine.cleanup()
        event.accept()


# ─────────────────────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────────────────────
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
